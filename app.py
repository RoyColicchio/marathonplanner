import streamlit as st
import os
import sys

# Enable debugging if needed - for local development only
DEBUG_SECRETS = os.getenv("DEBUG_SECRETS", "").lower() in ("true", "1", "yes")

st.set_page_config(
    page_title="Marathon Planner",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Simple, clean styling that doesn't interfere with functionality
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main .block-container {
        padding-top: 2rem;
        max-width: 1200px;
    }
    
    h1 {
        color: #1f2937;
        font-weight: 600;
    }
    
    h2 {
        color: #374151;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

from streamlit_oauth import OAuth2Component
import json
import hashlib
from pathlib import Path
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
from pace_utils import marathon_pace_seconds, get_pace_range
import requests
import time
import os
import pandas as pd
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote

# Helper: get Strava credentials from secrets (section or top-level) or environment
def get_strava_credentials():
    client_id = None
    client_secret = None

    try:
        # Prefer section
        if "strava" in st.secrets:
            sect = st.secrets["strava"]
            client_id = sect.get("client_id")
            client_secret = sect.get("client_secret")
        # Fallback: top-level keys
        if (not client_id or not client_secret):
            client_id = client_id or st.secrets.get("strava_client_id")
            client_secret = client_secret or st.secrets.get("strava_client_secret")
    except Exception:
        pass

    # Fallback: read local .streamlit/secrets.toml directly (simple parser)
    if not client_id or not client_secret:
        try:
            path = os.path.join(os.getcwd(), ".streamlit", "secrets.toml")
            if os.path.exists(path):
                current_section = None
                top = {}
                sections = {}
                with open(path, "r", encoding="utf-8") as f:
                    for raw in f:
                        line = raw.strip()
                        if not line or line.startswith("#") or line.startswith(";"):
                            continue
                        if line.startswith("[") and line.endswith("]"):
                            current_section = line[1:-1].strip()
                            sections.setdefault(current_section, {})
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip()
                            # strip quotes if present
                            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                                val = val[1:-1]
                            if current_section:
                                sections[current_section][key] = val
                            else:
                                top[key] = val
                # Pull values from parsed data
                if not client_id:
                    client_id = (sections.get("strava", {}) or {}).get("client_id") or top.get("strava_client_id")
                if not client_secret:
                    client_secret = (sections.get("strava", {}) or {}).get("client_secret") or top.get("strava_client_secret")
        except Exception:
            pass

    # Environment fallback
    if not client_id:
        client_id = os.getenv("STRAVA_CLIENT_ID")
    if not client_secret:
        client_secret = os.getenv("STRAVA_CLIENT_SECRET")

    # Normalize
    if isinstance(client_id, str):
        client_id = client_id.strip("\"' ")
    if isinstance(client_secret, str):
        client_secret = client_secret.strip("\"' ")

    return client_id, client_secret

# Resolve Google OAuth credentials
google_client_id = st.secrets.get("google_client_id") or os.getenv("GOOGLE_CLIENT_ID")
google_client_secret = st.secrets.get("google_client_secret") or os.getenv("GOOGLE_CLIENT_SECRET")

if not google_client_id or not google_client_secret:
    st.error("Missing Google OAuth credentials. Set google_client_id and google_client_secret in Streamlit Cloud Secrets.")
    st.stop()

# Initialize session state
if "current_user" not in st.session_state:
    st.session_state.current_user = None
if "google_oauth_component" not in st.session_state:
    st.session_state.google_oauth_component = None

def get_google_oauth_component():
    """Initialize Google OAuth component."""
    if st.session_state.google_oauth_component is None:
        st.session_state.google_oauth_component = OAuth2Component(
            client_id=google_client_id,
            client_secret=google_client_secret,
            authorize_endpoint="https://accounts.google.com/o/oauth2/auth",
            token_endpoint="https://oauth2.googleapis.com/token",
            refresh_token_endpoint="https://oauth2.googleapis.com/token",
            revoke_token_endpoint="https://oauth2.googleapis.com/revoke",
        )
    return st.session_state.google_oauth_component

def get_user_info(access_token):
    """Get user info from Google API."""
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get("https://openidconnect.googleapis.com/v1/userinfo", headers=headers)
    if response.status_code == 200:
        return response.json()
    return None

def get_user_hash(email):
    """Create a consistent hash for the user based on email."""
    return hashlib.sha256(email.encode()).hexdigest()[:16]

def load_user_settings(user_hash):
    """Load user-specific settings from JSON file."""
    try:
        settings_path = Path("user_settings.json")
        if settings_path.exists():
            with settings_path.open("r") as f:
                all_settings = json.load(f)
            return all_settings.get(user_hash, {})
        return {}
    except Exception as e:
        st.error(f"Error loading user settings: {e}")
        return {}

def save_user_settings(user_hash, settings):
    """Save user-specific settings to JSON file."""
    try:
        settings_path = Path("user_settings.json")
        all_settings = {}
        if settings_path.exists():
            with settings_path.open("r") as f:
                all_settings = json.load(f)
        
        all_settings[user_hash] = settings
        
        with settings_path.open("w") as f:
            json.dump(all_settings, f, indent=2)
    except Exception as e:
        st.error(f"Error saving user settings: {e}")

def google_login():
    """Handle Google OAuth login."""
    st.title("Marathon Training Dashboard")
    st.markdown("### Sign in with your Google account to get started")
    
    oauth2 = get_google_oauth_component()
    
    # Use a redirect URI that exactly matches what's registered in Google Cloud Console
    # Based on the error message, this should be without trailing slash
    redirect_uri = "https://marathonplanner.streamlit.app"
    
    # Read the URI from secrets if available
    if "google_redirect_uri" in st.secrets:
        redirect_uri = st.secrets.get("google_redirect_uri")
    
    # Debug output to help troubleshoot
    st.write(f"Using Google redirect URI: {redirect_uri}")
    st.write("Note: This exact URI must be registered in Google Cloud Console.")
    
    # Also display client ID for verification (masked for security)
    client_id_masked = google_client_id[:8] + "..." + google_client_id[-8:] if len(google_client_id) > 16 else google_client_id
    st.write(f"Using client ID: {client_id_masked}")
    
    result = oauth2.authorize_button(
        name="Continue with Google",
        icon="https://developers.google.com/identity/images/g-logo.png",
        redirect_uri=redirect_uri,
        scope="openid email profile",
        key="google_oauth",
        use_container_width=True
    )
    
    if result and "token" in result:
        user_info = get_user_info(result["token"]["access_token"])
        if user_info:
            st.session_state.current_user = {
                "email": user_info.get("email"),
                "name": user_info.get("name", user_info.get("email")),
                "picture": user_info.get("picture", ""),
                "access_token": result["token"]["access_token"]
            }
            st.rerun()

def show_header():
    """Display the app header with user info."""
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.title("Marathon Training Dashboard")
    
    with col2:
        if st.session_state.current_user:
            user = st.session_state.current_user
            st.markdown(f"**{user['name']}**")
            if st.button("Sign Out", key="signout"):
                st.session_state.current_user = None
                st.rerun()

def get_strava_auth_url():
    """Generate URL for Strava OAuth."""
    try:
        # Strava requires a fully-qualified URI
        redirect_uri = (
            st.secrets.get("strava_redirect_uri")
            or os.getenv("STRAVA_REDIRECT_URI")
            or "https://marathonplanner.streamlit.app"
        )

        client_id, client_secret = get_strava_credentials()
        if not client_id or not client_secret:
            st.error("Missing Strava client_id/client_secret. Add them to secrets or env.")
            try:
                st.caption(f"Secrets keys: {list(st.secrets.keys())}")
            except Exception:
                pass
            return None

        scope = "read,activity:read_all"
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "approval_prompt": "auto",
            "scope": scope,
        }
        auth_url = "https://www.strava.com/oauth/authorize?" + urlencode(params)
        return auth_url
    except Exception as e:
        st.error(f"Error generating Strava auth URL: {e}")
        return None

def refresh_strava_token_if_needed():
    """Refresh Strava token if expired or close to expiry. Returns True if token is usable."""
    try:
        user_hash = get_user_hash(st.session_state.current_user["email"])
        settings = load_user_settings(user_hash)
        if not settings.get("strava_refresh_token"):
            return False
        # If expires within 60s, refresh
        if not settings.get("strava_expires_at") or time.time() >= settings["strava_expires_at"] - 60:
            client_id, client_secret = get_strava_credentials()
            if not client_id or not client_secret:
                return False
            token_url = "https://www.strava.com/oauth/token"
            data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": settings["strava_refresh_token"],
            }
            r = requests.post(token_url, data=data, timeout=10)
            if r.status_code == 200:
                token_data = r.json()
                settings["strava_token"] = token_data.get("access_token", settings.get("strava_token"))
                settings["strava_refresh_token"] = token_data.get("refresh_token", settings.get("strava_refresh_token"))
                settings["strava_expires_at"] = token_data.get("expires_at", int(time.time()) + 3600)
                save_user_settings(user_hash, settings)
                return True
            return False
        return True
    except Exception:
        return False

def exchange_strava_code_for_token(code):
    """Exchange authorization code for access token."""
    client_id, client_secret = get_strava_credentials()
    if not client_id or not client_secret:
        st.error("Missing Strava client_id/client_secret for token exchange.")
        return False

    token_url = "https://www.strava.com/oauth/token"
    redirect_uri = (
        st.secrets.get("strava_redirect_uri")
        or os.getenv("STRAVA_REDIRECT_URI")
        or "https://marathonplanner.streamlit.app"
    )

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    try:
        response = requests.post(token_url, data=data, timeout=10)
        if response.status_code == 200:
            token_data = response.json()
            user_hash = get_user_hash(st.session_state.current_user["email"])
            settings = load_user_settings(user_hash)
            settings["strava_token"] = token_data["access_token"]
            settings["strava_refresh_token"] = token_data.get("refresh_token")
            settings["strava_expires_at"] = token_data.get("expires_at")
            # Save scope and athlete id for diagnostics
            settings["strava_scope"] = token_data.get("scope")
            athlete = token_data.get("athlete") or {}
            settings["strava_athlete_id"] = athlete.get("id")
            save_user_settings(user_hash, settings)
            return True
        else:
            st.error(f"Failed to get Strava token: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        st.error(f"Error exchanging Strava code: {e}")
        return False

def strava_connect():
    """Handle Strava connection."""
    client_id, client_secret = get_strava_credentials()

    if not client_id or not client_secret:
        st.error("Strava credentials not found.")
        st.info("Add [strava] client_id/client_secret to .streamlit/secrets.toml or set STRAVA_CLIENT_ID/STRAVA_CLIENT_SECRET env vars.")
        # Light introspection only
        try:
            st.caption(f"Secrets keys available: {list(st.secrets.keys())}")
        except Exception:
            pass
        return False

    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)

    # Handle authorization callback
    query_params = st.query_params
    if "code" in query_params:
        code = query_params["code"]
        if exchange_strava_code_for_token(code):
            st.success("Successfully connected to Strava!")
            st.query_params.clear()
            st.rerun()

    # Check existing token
    if settings.get("strava_token") and settings.get("strava_expires_at"):
        if time.time() < settings["strava_expires_at"]:
            return True

    st.warning("Connect your Strava account to see your training data.")
    auth_url = get_strava_auth_url()
    if auth_url:
        st.link_button("Connect to Strava", auth_url, use_container_width=True)
    return False

def get_strava_activities(start_date=None, end_date=None, max_pages=4):
    """Fetch activities from Strava API with optional date range and pagination."""
    # Ensure token is valid/refresh if needed
    refresh_strava_token_if_needed()

    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)
    
    if not settings.get("strava_token"):
        st.warning("No Strava token found. Please connect your Strava account.")
        return []
    
    headers = {"Authorization": f"Bearer {settings['strava_token']}"}

    params_base = {"per_page": 200}
    # Strava expects epoch seconds for filters
    try:
        if start_date is not None:
            # include activities from the previous day to handle TZ differences
            start_ts = int(datetime.combine(start_date, datetime.min.time()).timestamp()) - 86400
            params_base["after"] = start_ts
        if end_date is not None:
            # include activities up to the next day end
            end_ts = int(datetime.combine(end_date, datetime.max.time()).timestamp()) + 86400
            params_base["before"] = end_ts
    except Exception:
        pass

    all_acts = []
    try:
        for page in range(1, max_pages + 1):
            params = {**params_base, "page": page}
            r = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers, params=params, timeout=15)
            if r.status_code != 200:
                st.error(f"Failed to fetch Strava activities: {r.status_code}")
                break
            batch = r.json() or []
            all_acts.extend(batch)
            if len(batch) < params_base.get("per_page", 30):
                break
        return all_acts
    except Exception as e:
        st.error(f"Error fetching Strava activities: {e}")
        return []

def training_plan_setup():
    """Handle training plan configuration."""
    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)
    
    st.header("Training Plan Setup")
    
    col1, col2 = st.columns(2)
    
    with col1:
        start_date = st.date_input(
            "Start Date", 
            value=datetime.strptime(settings.get("start_date", str(datetime.now().date())), "%Y-%m-%d").date(),
            help="The start date of your training plan"
        )
        
    with col2:
        goal_time = st.text_input(
            "Goal Marathon Time (HH:MM:SS)", 
            value=settings.get("goal_time", "4:00:00"),
            help="Your target marathon finish time"
        )
    
    if st.button("Save Training Plan", use_container_width=True):
        new_settings = {
            **settings,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "goal_time": goal_time,
        }
        save_user_settings(user_hash, new_settings)
        st.success("Training plan saved!")
        st.rerun()
    
    return settings

def show_dashboard():
    """Display the main dashboard."""
    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)
    
    if not settings.get("goal_time") or not settings.get("start_date"):
        st.info("Please complete your training plan setup first.")
        return training_plan_setup()

    # Tabs for different sections
    tab1, tab2 = st.tabs(["Training Plan", "Settings"])
    
    with tab1:
        show_training_plan_table(settings)
    
    with tab2:
        training_plan_setup()

def generate_training_plan(start_date):
    """Loads the training plan from run_plan.csv and adjusts dates."""
    try:
        # Load the plan using the first row as the header
        plan_df = pd.read_csv("run_plan.csv", header=0)
        plan_df.columns = [col.strip() for col in plan_df.columns]

        # Drop rows that are separators or don't have an activity
        plan_df.dropna(subset=['Plan'], inplace=True)
        plan_df = plan_df[plan_df['Plan'].str.strip() != '']
        
        activities = plan_df['Plan'].str.strip().copy().reset_index(drop=True)
        
        activity_map = {
            "GA": "General Aerobic",
            "Rec": "Recovery",
            "MLR": "Medium-Long Run",
            "LR": "Long Run",
            "SP": "Sprints",
            "V8": "VO₂Max",
            "LT": "Lactate Threshold",
            "HMP": "Half Marathon Pace",
            "MP": "Marathon Pace"
        }
        
        def expand_abbreviations(activity_string):
            # Sort keys by length, descending, to match longer abbreviations first.
            sorted_keys = sorted(activity_map.keys(), key=len, reverse=True)
            for abbr in sorted_keys:
                # Use word boundaries to avoid replacing parts of other words.
                activity_string = re.sub(r'\b' + re.escape(abbr) + r'\b', activity_map[abbr], activity_string)
            return activity_string

        expanded_activities = activities.apply(expand_abbreviations)

        num_days = len(activities)
        dates = [start_date + timedelta(days=i) for i in range(num_days)]
        days_of_week = [date.strftime("%A") for date in dates]
        
        new_plan_df = pd.DataFrame({
            'Date': dates,
            'Day': days_of_week,
            'Activity_Abbr': activities,
            'Activity': expanded_activities
        })

        return new_plan_df

    except FileNotFoundError:
        st.error("`run_plan.csv` not found. Please make sure it's in the root directory.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error processing `run_plan.csv`: {e}")
        return pd.DataFrame()

def show_training_plan_table(settings):
    """Display the training plan in a table."""
    st.header("Your Training Plan")

    start_date = datetime.strptime(settings["start_date"], "%Y-%m-%d").date()
    goal_time = settings["goal_time"]
    
    # Generate plan
    plan_df = generate_training_plan(start_date)
    
    if plan_df.empty:
        return

    # Determine date window from the plan
    plan_df['Date'] = pd.to_datetime(plan_df['Date']).dt.date
    plan_min = min(plan_df['Date'])
    plan_max = max(plan_df['Date'])

    # Get Strava data for the plan window
    if not strava_connect():
        activities = []
    else:
        activities = get_strava_activities(start_date=plan_min, end_date=plan_max)

    runs = [a for a in activities if a.get("type") == "Run"]
    
    if runs:
        def miles_and_pace(run):
            meters = run.get("distance", 0) or 0
            moving_time = run.get("moving_time", 0) or 0
            miles = meters * 0.000621371
            if miles > 0 and moving_time > 0:
                sec_per_mile = moving_time / miles
                minutes = int(sec_per_mile // 60)
                seconds = int(sec_per_mile % 60)
                pace = f"{minutes}:{seconds:02d}"
            else:
                pace = "N/A"
            # use local start date if available, else utc
            date_str = (run.get("start_date_local") or run.get("start_date") or "").split("T")[0]
            try:
                run_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except Exception:
                run_date = None
            return run_date, round(miles, 2), pace

        rows = []
        for run in runs:
            d, m, p = miles_and_pace(run)
            if d is not None:
                rows.append({"Date": d, "Actual Miles": m, "Actual Pace": p})

        strava_df = pd.DataFrame(rows)
        merged_df = pd.merge(plan_df, strava_df, on="Date", how="left")
    else:
        merged_df = plan_df.copy()
        merged_df["Actual Miles"] = None
        merged_df["Actual Pace"] = None

    # Calculate suggested pace
    gmp_sec = marathon_pace_seconds(goal_time)
    merged_df["Suggested Pace"] = merged_df["Activity_Abbr"].apply(lambda x: get_pace_range(x, gmp_sec))

    # Reorder and format columns
    merged_df = merged_df[["Date", "Day", "Activity", "Suggested Pace", "Actual Miles", "Actual Pace"]]
    merged_df['Date'] = pd.to_datetime(merged_df['Date']).dt.strftime('%m-%d')

    # Display table
    st.dataframe(merged_df.fillna(""), height=600)

    # Diagnostics
    with st.expander("Strava connection details"):
        user_hash = get_user_hash(st.session_state.current_user["email"])
        s = load_user_settings(user_hash)
        st.write({
            "token_present": bool(s.get("strava_token")),
            "expires_at": s.get("strava_expires_at"),
            "scope": s.get("strava_scope"),
            "athlete_id": s.get("strava_athlete_id"),
            "activities_returned": len(activities) if isinstance(activities, list) else 0,
        })

def main():
    """Main application logic."""
    # Check if user is logged in
    if not st.session_state.current_user:
        google_login()
        return
    
    # Show header
    show_header()
    
    # Show main dashboard
    show_dashboard()

if __name__ == "__main__":
    main()