import streamlit as st
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
        # For consistency, let's use the direct domain without protocol
        no_protocol_url = "marathonplanner.streamlit.app"
        
        # Check if Strava credentials exist in secrets with proper formatting
        if "strava" not in st.secrets:
            st.error("Strava API credentials not found in secrets.")
            return None
            
        if "client_id" not in st.secrets["strava"] or "client_secret" not in st.secrets["strava"]:
            st.error("Missing client_id or client_secret in Strava secrets.")
            return None
            
        # Check for string vs integer client_id
        client_id = st.secrets["strava"]["client_id"]
        # If client_id is stored as a string with quotes, strip them and convert to integer
        if isinstance(client_id, str):
            client_id = client_id.strip('"\'')
        
        scope = "read,activity:read_all"
        
        # Display debug information
        st.write("### Strava Auth URL Debug Info")
        st.write(f"Using redirect URI: {no_protocol_url}")
        st.write(f"Client ID type: {type(client_id).__name__}")
        
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": no_protocol_url,
            "approval_prompt": "auto",
            "scope": scope,
        }
        
        # Show the exact params that will be used
        st.write("### Strava Auth Parameters:")
        st.json(params)
        
        auth_url = "https://www.strava.com/oauth/authorize?" + urlencode(params)
        st.write(f"### Full Strava Auth URL:")
        st.code(auth_url)
        
        return auth_url
    except Exception as e:
        st.error(f"Error generating Strava auth URL: {e}")
        st.exception(e)  # Display full traceback for better debugging
        return None

def exchange_strava_code_for_token(code):
    """Exchange authorization code for access token."""
    # Check if Strava credentials exist in secrets
    if "strava" not in st.secrets:
        st.error("Strava API credentials not found in secrets.")
        return False
        
    token_url = "https://www.strava.com/oauth/token"
    
    # Get credentials from secrets
    client_id = st.secrets["strava"]["client_id"]
    client_secret = st.secrets["strava"]["client_secret"]
    
    # If client_id is stored as a string with quotes, strip them
    if isinstance(client_id, str):
        client_id = client_id.strip('"\'')
        
    # If client_secret is stored with quotes, strip them
    if isinstance(client_secret, str):
        client_secret = client_secret.strip('"\'')
    
    # Use the same redirect URI formats as in the auth URL function
    streamlit_app_url = "https://marathonplanner.streamlit.app"
    no_protocol_url = "marathonplanner.streamlit.app"
    
    # Show detailed debug information
    st.write("### Strava Token Exchange Debug Info")
    st.write(f"Code being exchanged: {code[:5]}...{code[-5:] if len(code) > 10 else code}")
    st.write(f"Client ID type: {type(client_id).__name__}")
    st.write(f"Client Secret type: {type(client_secret).__name__}")
    
    # Show redirect URI variations we'll try
    st.write("### Redirect URI Variations for Token Exchange")
    st.code(f"With https: {streamlit_app_url}")
    st.code(f"Without protocol: {no_protocol_url}")
    
    # First try with the no-protocol version
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": no_protocol_url
    }
    
    try:
        # Display full request data for debugging
        st.write("Sending token request with data:")
        st.json(data)
        
        response = requests.post(token_url, data=data, timeout=10)
        
        # Display raw response for debugging
        st.write(f"Response status code: {response.status_code}")
        st.write(f"Response headers: {dict(response.headers)}")
        
        try:
            response_json = response.json()
            st.write("Response JSON:")
            st.json(response_json)
        except:
            st.write(f"Raw response text: {response.text}")
        
        if response.status_code == 200:
            token_data = response.json()
            # Save token to user settings
            user_hash = get_user_hash(st.session_state.current_user["email"])
            settings = load_user_settings(user_hash)
            settings["strava_token"] = token_data["access_token"]
            settings["strava_refresh_token"] = token_data["refresh_token"]
            settings["strava_expires_at"] = token_data["expires_at"]
            save_user_settings(user_hash, settings)
            return True
        else:
            st.error(f"Failed to get Strava token: {response.status_code} - {response.text}")
            
            # Try with alternate redirect URI formats
            if "redirect_uri" in response.text.lower():
                # Try with https version
                st.warning("Trying with HTTPS version...")
                data["redirect_uri"] = "https://marathonplanner.streamlit.app"
                st.write(f"New redirect_uri: {data['redirect_uri']}")
                
                https_response = requests.post(token_url, data=data, timeout=10)
                st.write(f"HTTPS response: {https_response.status_code} - {https_response.text}")
                
                if https_response.status_code == 200:
                    token_data = https_response.json()
                    user_hash = get_user_hash(st.session_state.current_user["email"])
                    settings = load_user_settings(user_hash)
                    settings["strava_token"] = token_data["access_token"]
                    settings["strava_refresh_token"] = token_data["refresh_token"]
                    settings["strava_expires_at"] = token_data["expires_at"]
                    save_user_settings(user_hash, settings)
                    return True
                
                # Try with HTTP version
                st.warning("Trying with HTTP version...")
                data["redirect_uri"] = "http://marathonplanner.streamlit.app"
                st.write(f"New redirect_uri: {data['redirect_uri']}")
                
                http_response = requests.post(token_url, data=data, timeout=10)
                st.write(f"HTTP response: {http_response.status_code} - {http_response.text}")
                
                if http_response.status_code == 200:
                    token_data = http_response.json()
                    user_hash = get_user_hash(st.session_state.current_user["email"])
                    settings = load_user_settings(user_hash)
                    settings["strava_token"] = token_data["access_token"]
                    settings["strava_refresh_token"] = token_data["refresh_token"]
                    settings["strava_expires_at"] = token_data["expires_at"]
                    save_user_settings(user_hash, settings)
                    return True
                
                # Try with trailing slash
                st.warning("Trying with trailing slash...")
                data["redirect_uri"] = "marathonplanner.streamlit.app/"
                st.write(f"New redirect_uri: {data['redirect_uri']}")
                
                slash_response = requests.post(token_url, data=data, timeout=10)
                st.write(f"Trailing slash response: {slash_response.status_code} - {slash_response.text}")
                
                if slash_response.status_code == 200:
                    token_data = slash_response.json()
                    user_hash = get_user_hash(st.session_state.current_user["email"])
                    settings = load_user_settings(user_hash)
                    settings["strava_token"] = token_data["access_token"]
                    settings["strava_refresh_token"] = token_data["refresh_token"]
                    settings["strava_expires_at"] = token_data["expires_at"]
                    save_user_settings(user_hash, settings)
                    return True
            
            return False
    except Exception as e:
        st.error(f"Error exchanging Strava code: {e}")
        st.exception(e)  # Display full traceback for better debugging
        return False

def strava_connect():
    """Handle Strava connection."""
    # Debug output to verify Strava credentials
    st.write("### Strava Credentials Check")
    
    # Debug output to see all available secrets keys
    st.write("Available secret sections:")
    st.code(str(st.secrets._secrets.sections()))
    
    # Show all top-level keys in secrets
    st.write("All top-level keys in secrets:")
    all_keys = list(st.secrets._secrets.keys())
    st.code(str(all_keys))
    
    # Try accessing with different case
    strava_found = False
    for key in all_keys:
        if key.lower() == "strava":
            st.write(f"Found Strava section as '{key}' (case sensitivity matters)")
            strava_found = True
    
    if "strava" in st.secrets:
        st.success("✅ 'strava' found in secrets")
        if "client_id" in st.secrets["strava"] and "client_secret" in st.secrets["strava"]:
            st.success("✅ Strava credentials found in secrets")
            # Mask the credentials for security
            client_id = st.secrets["strava"]["client_id"]
            st.write(f"Client ID: {client_id}")
            st.write("Client Secret: [Hidden for security]")
        else:
            st.error("❌ Strava section found but missing client_id or client_secret")
            # Debug: show all keys in the strava section
            st.write("Keys in strava section:")
            st.code(str(list(st.secrets["strava"].keys())))
    else:
        st.error("❌ Strava section not found in secrets")
        if strava_found:
            st.warning("Note: A 'Strava' section was found but with different case. TOML is case-sensitive.")
        st.info("""
        To use Strava integration, you need to add your Strava API credentials to the Streamlit secrets.
        1. Create a Strava API application at https://www.strava.com/settings/api
        2. Add the following to your .streamlit/secrets.toml file or Streamlit Cloud secrets:
        ```
        [strava]
        client_id = "YOUR_STRAVA_CLIENT_ID"
        client_secret = "YOUR_STRAVA_CLIENT_SECRET"
        ```
        3. Set the redirect URI in your Strava API application to: marathonplanner.streamlit.app
        """)
        return False
        
    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)
    
    # Check for authorization code in URL
    query_params = st.query_params
    if "code" in query_params:
        code = query_params["code"]
        if exchange_strava_code_for_token(code):
            st.success("Successfully connected to Strava!")
            # Clear the query params
            st.query_params.clear()
            st.rerun()
    
    # Check if user has valid Strava token
    if settings.get("strava_token") and settings.get("strava_expires_at"):
        if time.time() < settings["strava_expires_at"]:
            return True
    
    st.warning("Connect your Strava account to see your training data.")
    auth_url = get_strava_auth_url()
    if auth_url:
        st.link_button("Connect to Strava", auth_url, use_container_width=True)
    return False

def get_strava_activities():
    """Fetch activities from Strava API."""
    # Check if Strava credentials exist in secrets
    if "strava" not in st.secrets:
        return []
        
    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)
    
    if not settings.get("strava_token"):
        return []
    
    headers = {"Authorization": f"Bearer {settings['strava_token']}"}
    
    try:
        r = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers)
        if r.status_code == 200:
            return r.json()
        else:
            st.error(f"Failed to fetch Strava activities: {r.status_code}")
            return []
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

    # Get Strava data
    if not strava_connect():
        activities = []
    else:
        activities = get_strava_activities()

    runs = [a for a in activities if a.get("type") == "Run"]
    
    if runs:
        strava_df = pd.DataFrame([{
            "Date": datetime.strptime(run.get("start_date_local", "").split("T")[0], "%Y-%m-%d").date(),
            "Actual Miles": round(run.get("distance", 0) * 0.000621371, 2),
            "Actual Pace": f"{int(run.get('moving_time', 0) / (run.get('distance', 1) * 0.000621371) // 60)}:{int(run.get('moving_time', 0) / (run.get('distance', 1) * 0.000621371) % 60):02d}" if run.get('distance', 0) > 0 else "N/A"
        } for run in runs])
        
        # Merge plan with strava data
        plan_df['Date'] = pd.to_datetime(plan_df['Date']).dt.date
        merged_df = pd.merge(plan_df, strava_df, on="Date", how="left")
    else:
        merged_df = plan_df
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