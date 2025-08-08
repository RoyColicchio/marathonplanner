import streamlit as st
st.set_page_config(
    page_title="Marathon Planner",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Modern CSS styling
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    * {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Modern card styling */
    .stApp > div:first-child {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        min-height: 100vh;
    }
    
    .main {
        background: #ffffff;
        border-radius: 12px;
        margin: 1rem;
        box-shadow: 0 4px 20px rgba(0,0,0,0.1);
    }
    
    /* Headers */
    h1 {
        font-weight: 700;
        font-size: 2.5rem;
        color: #1a1a1a;
        margin-bottom: 0.5rem;
        letter-spacing: -0.02em;
    }
    
    h2 {
        font-weight: 600;
        font-size: 1.75rem;
        color: #374151;
        margin-bottom: 1rem;
        margin-top: 2rem;
    }
    
    h3 {
        font-weight: 600;
        font-size: 1.25rem;
        color: #374151;
        margin-bottom: 0.75rem;
    }
    
    /* Text styling */
    p, .stMarkdown {
        color: #6b7280;
        font-size: 1rem;
        line-height: 1.6;
    }
    
    /* Button styling */
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.75rem 1.5rem;
        font-weight: 500;
        font-size: 1rem;
        transition: all 0.2s ease;
        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
    }
    
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
    
    /* Form styling */
    .stSelectbox > div > div {
        border-radius: 8px;
        border: 1px solid #e5e7eb;
    }
    
    .stTextInput > div > div > input {
        border-radius: 8px;
        border: 1px solid #e5e7eb;
        padding: 0.75rem;
    }
    
    .stDateInput > div > div > input {
        border-radius: 8px;
        border: 1px solid #e5e7eb;
        padding: 0.75rem;
    }
    
    /* Info boxes */
    .stInfo {
        background: #f0f9ff;
        border: 1px solid #bae6fd;
        border-radius: 8px;
        padding: 1rem;
    }
    
    .stSuccess {
        background: #f0fdf4;
        border: 1px solid #bbf7d0;
        border-radius: 8px;
        padding: 1rem;
    }
    
    .stError {
        background: #fef2f2;
        border: 1px solid #fecaca;
        border-radius: 8px;
        padding: 1rem;
    }
    
    .stWarning {
        background: #fffbeb;
        border: 1px solid #fed7aa;
        border-radius: 8px;
        padding: 1rem;
    }
    
    /* Sidebar styling */
    .css-1d391kg {
        background: #f9fafb;
        border-right: 1px solid #e5e7eb;
    }
    
    /* Modern metrics */
    div[data-testid="metric-container"] {
        background: #f9fafb;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 1rem;
    }
    
    /* Code blocks */
    .stCode {
        background: #f3f4f6;
        border-radius: 8px;
        border: 1px solid #e5e7eb;
    }
    
    /* Progress bar */
    .stProgress .css-pxxe24 {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 4px;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2rem;
    }
    
    .stTabs [data-baseweb="tab"] {
        padding: 0.5rem 0;
        border-bottom: 2px solid transparent;
        color: #6b7280;
        font-weight: 500;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        color: #374151;
    }
    
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        color: #667eea;
        border-bottom-color: #667eea;
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
    result = oauth2.authorize_button(
        name="Continue with Google",
        icon="https://developers.google.com/identity/images/g-logo.png",
        redirect_uri="http://localhost:8501",
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
    redirect_uri = "http://localhost:8501"
    scope = "read,activity:read_all"
    
    return (f"https://www.strava.com/oauth/authorize?"
           f"client_id={client_id}&"
           f"response_type=code&"
           f"redirect_uri={redirect_uri}&"
           f"approval_prompt=force&"
           f"scope={scope}")

def exchange_strava_code_for_token(code):
    """Exchange authorization code for access token."""
    client_id = "138833"
    client_secret = "b8e5025cad1ad68fe29e6c6cd52b0db30c6b0f49"
    
    token_url = "https://www.strava.com/oauth/token"
    
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code"
    }
    
    try:
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
            st.error(f"Failed to get Strava token: {response.status_code}")
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
        goal_time = st.text_input(
            "Goal Marathon Time (HH:MM:SS)", 
            value=settings.get("goal_time", "4:00:00"),
            help="Your target marathon finish time"
        )
        
        current_weekly_miles = st.number_input(
            "Current Weekly Miles", 
            min_value=0.0, 
            max_value=150.0, 
            value=float(settings.get("current_weekly_miles", 30.0)), 
            step=5.0,
            help="Your current weekly mileage"
        )
        
        experience_level = st.selectbox(
            "Experience Level",
            ["Beginner", "Intermediate", "Advanced"],
            index=["Beginner", "Intermediate", "Advanced"].index(settings.get("experience_level", "Intermediate"))
        )
    
    with col2:
        race_date = st.date_input(
            "Race Date", 
            value=datetime.strptime(settings.get("race_date", "2024-12-01"), "%Y-%m-%d").date() if settings.get("race_date") else datetime.now().date() + timedelta(days=120),
            help="Your marathon race date"
        )
        
        training_days = st.multiselect(
            "Training Days",
            ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            default=settings.get("training_days", ["Tuesday", "Thursday", "Saturday", "Sunday"]),
            help="Days you prefer to train"
        )
        
        long_run_day = st.selectbox(
            "Long Run Day",
            ["Saturday", "Sunday"],
            index=0 if settings.get("long_run_day", "Sunday") == "Saturday" else 1
        )
    
    if st.button("Save Training Plan", use_container_width=True):
        new_settings = {
            **settings,
            "goal_time": goal_time,
            "current_weekly_miles": current_weekly_miles,
            "experience_level": experience_level,
            "race_date": race_date.strftime("%Y-%m-%d"),
            "training_days": training_days,
            "long_run_day": long_run_day
        }
        save_user_settings(user_hash, new_settings)
        st.success("Training plan saved!")
        st.rerun()
    
    return settings

def calculate_training_paces(goal_time):
    """Calculate training paces based on goal time."""
    try:
        # Parse goal time
        time_parts = goal_time.split(":")
        if len(time_parts) == 3:
            hours, minutes, seconds = map(int, time_parts)
            goal_seconds = hours * 3600 + minutes * 60 + seconds
        else:
            st.error("Invalid time format. Use HH:MM:SS")
            return None
        
        goal_pace_seconds = goal_seconds / 26.2  # seconds per mile
        
        paces = {
            "Marathon Pace": goal_pace_seconds,
            "Easy Run": goal_pace_seconds + 60,  # 1 minute slower per mile
            "Long Run": goal_pace_seconds + 30,  # 30 seconds slower per mile
            "Tempo Run": goal_pace_seconds - 20, # 20 seconds faster per mile
            "Interval": goal_pace_seconds - 40,  # 40 seconds faster per mile
        }
        
        # Convert back to pace format (MM:SS per mile)
        pace_formatted = {}
        for pace_type, seconds in paces.items():
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            pace_formatted[pace_type] = f"{minutes}:{secs:02d}"
        
        return pace_formatted
        
    except Exception as e:
        st.error(f"Error calculating paces: {e}")
        return None

def show_dashboard():
    """Display the main dashboard."""
    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)
    
    if not settings.get("goal_time"):
        st.info("Please complete your training plan setup first.")
        return training_plan_setup()
    
    # Calculate days to race
    try:
        race_date = datetime.strptime(settings["race_date"], "%Y-%m-%d").date()
        days_to_race = (race_date - datetime.now().date()).days
    except:
        days_to_race = 0
    
    # Header metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Days to Race", days_to_race)
    with col2:
        st.metric("Goal Time", settings.get("goal_time", "N/A"))
    with col3:
        st.metric("Weekly Miles", settings.get("current_weekly_miles", "N/A"))
    with col4:
        st.metric("Experience", settings.get("experience_level", "N/A"))
    
    # Training paces
    st.header("Training Paces")
    paces = calculate_training_paces(settings["goal_time"])
    if paces:
        cols = st.columns(len(paces))
        for i, (pace_type, pace) in enumerate(paces.items()):
            with cols[i]:
                st.metric(pace_type, f"{pace}/mile")
    
    # Tabs for different sections
    tab1, tab2, tab3 = st.tabs(["Weekly Plan", "Activity History", "Settings"])
    
    with tab1:
        show_weekly_plan(settings)
    
    with tab2:
        show_activity_history()
    
    with tab3:
        training_plan_setup()

def show_weekly_plan(settings):
    """Display weekly training plan."""
    st.subheader("This Week's Training")
    
    training_days = settings.get("training_days", [])
    if not training_days:
        st.info("No training days configured. Please update your settings.")
        return
    
    # Simple weekly plan based on experience level
    experience = settings.get("experience_level", "Intermediate")
    
    if experience == "Beginner":
        weekly_plan = {
            "Monday": "Rest or Cross-training",
            "Tuesday": "Easy Run (3-4 miles)",
            "Wednesday": "Rest",
            "Thursday": "Easy Run (3-4 miles)",
            "Friday": "Rest",
            "Saturday": "Easy Run (2-3 miles)",
            "Sunday": "Long Run (6-12 miles)"
        }
    elif experience == "Advanced":
        weekly_plan = {
            "Monday": "Easy Run (6-8 miles)",
            "Tuesday": "Tempo Run (5-8 miles with tempo)",
            "Wednesday": "Easy Run (4-6 miles)",
            "Thursday": "Intervals (6-8 miles with speedwork)",
            "Friday": "Rest or Easy (3-4 miles)",
            "Saturday": "Easy Run (4-6 miles)",
            "Sunday": "Long Run (12-20 miles)"
        }
    else:  # Intermediate
        weekly_plan = {
            "Monday": "Rest or Cross-training",
            "Tuesday": "Easy Run (4-6 miles)",
            "Wednesday": "Tempo Run (5-7 miles)",
            "Thursday": "Easy Run (3-5 miles)",
            "Friday": "Rest",
            "Saturday": "Easy Run (3-4 miles)",
            "Sunday": "Long Run (8-16 miles)"
        }
    
    for day, workout in weekly_plan.items():
        with st.container():
            col1, col2 = st.columns([1, 3])
            with col1:
                st.write(f"**{day}**")
            with col2:
                if day in training_days:
                    st.write(workout)
                else:
                    st.write("Rest Day")

def show_activity_history():
    """Display Strava activity history."""
    st.subheader("Recent Activities")
    
    if not strava_connect():
        return
    
    activities = get_strava_activities()
    
    if not activities:
        st.info("No recent activities found.")
        return
    
    # Filter for runs only
    runs = [a for a in activities if a.get("type") == "Run"]
    
    if not runs:
        st.info("No recent runs found.")
        return
    
    # Create DataFrame
    df_data = []
    for run in runs[:10]:  # Show last 10 runs
        df_data.append({
            "Date": run.get("start_date_local", "").split("T")[0],
            "Name": run.get("name", ""),
            "Distance (miles)": round(run.get("distance", 0) * 0.000621371, 2),
            "Time": str(timedelta(seconds=run.get("moving_time", 0))),
            "Pace (min/mile)": f"{int(run.get('moving_time', 0) / (run.get('distance', 1) * 0.000621371) // 60)}:{int(run.get('moving_time', 0) / (run.get('distance', 1) * 0.000621371) % 60):02d}" if run.get('distance', 0) > 0 else "N/A"
        })
    
    df = pd.DataFrame(df_data)
    
    # Display with AgGrid
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_pagination(paginationPageSize=10)
    gb.configure_default_column(groupable=True, value=True, enableRowGroup=True, aggFunc='sum', editable=False)
    gridOptions = gb.build()
    
    AgGrid(df, gridOptions=gridOptions, enable_enterprise_modules=True)

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