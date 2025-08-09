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
    
    # Get the exact URI registered in Google Cloud Console
    # From error message, the exact URI is being used without trailing slash
    redirect_uri = "https://marathonplanner.streamlit.app"
    
    # Debug output to help troubleshoot
    st.write(f"Using Google redirect URI: {redirect_uri}")
    
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
    """Generate Strava OAuth URL."""
    client_id = "138833"
    
    # The exact redirect URI as registered in Strava API settings
    # This must match EXACTLY what's in your Strava app settings
    redirect_uri = "marathonplanner.streamlit.app"
    
    # Log the redirect URI to help debug
    st.write(f"Using exact Strava redirect URI: {redirect_uri}")
    
    # Try direct construction of URL for debugging
    direct_url = f"https://www.strava.com/oauth/authorize?client_id={client_id}&response_type=code&redirect_uri={redirect_uri}&approval_prompt=force&scope=read,activity:read_all"
    
    st.write(f"Using direct URL: {direct_url}")
    
    return direct_url

def exchange_strava_code_for_token(code):
    """Exchange authorization code for access token."""
    client_id = "138833"
    client_secret = "b8e5025cad1ad68fe29e6c6cd52b0db30c6b0f49"
    
    token_url = "https://www.strava.com/oauth/token"
    
    # The exact same redirect URI as used in the authorization URL
    redirect_uri = "marathonplanner.streamlit.app"
    
    # Show the URI for debugging
    st.write(f"Token exchange - using exact redirect URI: {redirect_uri}")
    
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri  # Must match exactly what was used in authorization
    }
    
    try:
        st.write(f"Exchanging code for token with redirect_uri: {redirect_uri}")
        response = requests.post(token_url, data=data, timeout=10)
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
            return False
    except Exception as e:
        st.error(f"Error exchanging Strava code: {e}")
        return False

def strava_connect():
    """Handle Strava connection."""
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
    st.link_button("Connect to Strava", auth_url, use_container_width=True)
    return False

def get_strava_activities():
    """Fetch activities from Strava API."""
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