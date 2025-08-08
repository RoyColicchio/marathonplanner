import streamlit as st
st.set_page_config(layout="wide")
from streamlit_oauth import OAuth2Component
import json
from pathlib import Path
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
from pace_utils import marathon_pace_seconds, get_pace_range
import requests
import time

# --- Google OAuth2 Authentication ---
oauth2 = OAuth2Component(
    client_id=st.secrets["google_client_id"],
    client_secret=st.secrets["google_client_secret"],
    authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
    token_endpoint="https://oauth2.googleapis.com/token",
    redirect_uri="https://marathonplanner.streamlit.app/",
    scope="openid email profile"
)

result = oauth2.authorize_button("Login with Google", key="google")
if result and "token" in result:
    user_info = oauth2.get_user_info(result["token"]["access_token"], "https://openidconnect.googleapis.com/v1/userinfo")
    st.session_state["user_email"] = user_info["email"]
    st.success(f"Logged in as {user_info['email']}")
else:
    st.stop()

def dashboard_logic(name, username):
    st.write(f"Welcome, {name}!")
    # Load or initialize user settings
    settings_path = Path("user_settings.json")
    if settings_path.exists():
        with open(settings_path, "r") as f:
            all_settings = json.load(f)
    else:
        all_settings = {}
    user_settings = all_settings.get(username, {
        "name": name,
        "start_date": "",
        "plan": "run_plan.csv",
        "goal_time": "3:30:00"
    })



    # --- Plan selection dropdown with friendly name ---
    plan_options = {"run_plan.csv": "Pfitz 18/55"}
    plan_files = list(plan_options.keys())
    plan_labels = list(plan_options.values())
    # Find current plan label
    current_plan_file = user_settings.get("plan", "run_plan.csv")
    current_plan_label = plan_options.get(current_plan_file, current_plan_file)
    plan_label = st.selectbox("Select plan", plan_labels, index=plan_labels.index(current_plan_label) if current_plan_label in plan_labels else 0)
    # Map label back to filename
    selected_plan_file = [k for k, v in plan_options.items() if v == plan_label][0]
    user_settings["plan"] = selected_plan_file

    # (Plan preview removed as requested)

    # --- Prompt for start date and goal time if not set ---
    if not user_settings.get("start_date") or not user_settings.get("goal_time"):
        st.sidebar.header("Setup")
        start_date_input = st.sidebar.date_input("Select your plan start date")
        goal_time_input = st.sidebar.text_input("Enter your marathon goal time (hh:mm:ss)", value=user_settings.get("goal_time", "3:30:00"))
        if st.sidebar.button("Continue to Dashboard"):
            user_settings["start_date"] = str(start_date_input)
            user_settings["goal_time"] = goal_time_input
            all_settings[username] = user_settings
            with open(settings_path, "w") as f:
                json.dump(all_settings, f, indent=2)
            st.session_state['start_date_set'] = True
            st.rerun()
        if st.session_state.get('start_date_set'):
            del st.session_state['start_date_set']
        else:
            st.sidebar.info("Please select a start date, enter your goal time, and click 'Continue to Dashboard' to view your plan.")
            st.stop()

    # --- Always show dashboard after start_date is set ---
    plan_choice = user_settings["plan"]
    start_date = user_settings["start_date"]
    goal_marathon_time = user_settings["goal_time"]
    # Guard: if start_date is empty, stop and prompt user
    if not start_date or start_date in ["", None, "NaT"]:
        st.error("No valid start date set. Please select a start date in the sidebar.")
        st.stop()
    # If start_date is a string, parse it to datetime.date
    if isinstance(start_date, str) and start_date not in ("", "NaT", None):
        try:
            start_date_parsed = datetime.strptime(start_date, "%Y-%m-%d").date()
            start_date = start_date_parsed
        except Exception as e:
            pass
    # Guard: start_date must be valid
    if not start_date or start_date in ["", None, "NaT"]:
        st.error("No valid start date set. Please select a start date in the sidebar.")
        st.stop()
    try:
        start = pd.to_datetime(start_date)
    except Exception as e:
        st.error(f"Invalid start date: {start_date}. Error: {e}")
        st.stop()
    try:
        activities = get_activities()
        comparison = compare_plan_vs_actual(activities, plan_choice, start_date)
        # Add suggested pace column using goal_marathon_time and activity type, and move it to the left of 'Planned Distance (mi)'
        # Convert goal_marathon_time to seconds once
        try:
            gmp_sec = marathon_pace_seconds(goal_marathon_time)
        except Exception as e:
            st.write(f"Error parsing goal marathon time '{goal_marathon_time}': {e}")
            gmp_sec = None

        def get_suggested_pace(row):
            try:
                if gmp_sec is None:
                    return ""
                return get_pace_range(row['Activity'], gmp_sec)
            except Exception:
                return ""
        # Insert 'Suggested Pace' to the left of 'Planned Distance (mi)'
        insert_idx = comparison.columns.get_loc('Planned Distance (mi)')
        comparison.insert(insert_idx, 'Suggested Pace', comparison.apply(get_suggested_pace, axis=1))
        st.subheader("📅 Plan vs. Actual")
        columns_to_hide = ["Calendar Date", "Calendar Date Str", "Hit?"]
        display_df = comparison.drop(columns=[col for col in columns_to_hide if col in comparison.columns])
        # Shrink the width of the rightmost 4 columns (Planned Distance, Actual Distance, Diff, Suggested Pace)
        gb = GridOptionsBuilder.from_dataframe(display_df)
        # Set default min/max width for all columns
        gb.configure_default_column(minWidth=80, maxWidth=300)
        # Find the rightmost 4 columns
        rightmost_cols = display_df.columns[-4:]
        for col in rightmost_cols:
            gb.configure_column(col, minWidth=70, maxWidth=120, width=90)
        grid_options = gb.build()
        AgGrid(display_df, gridOptions=grid_options, theme="streamlit", fit_columns_on_grid_load=True)
        rec, expl = make_recommendation(activities, plan_choice, start_date)
        st.subheader("💡 Recommendation")
        st.write(rec)
        with st.expander("Show details"):
            st.text(expl)
        # Weekly mileage section removed as requested
    except Exception as e:
        st.error(f"Error showing plan: {e}")

def refresh_access_token():
    refresh_token = tokens["refresh_token"]
    response = requests.post(
        url="https://www.strava.com/api/v3/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    new_tokens = response.json()
    with open("tokens.json", "w") as f:
        json.dump(new_tokens, f)
    return new_tokens["access_token"]

def get_activities():
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers)
    return r.json()

def display_weekly_mileage(activities):
    df = pd.DataFrame(activities)
    df['start_date'] = pd.to_datetime(df['start_date'])
    df['week'] = df['start_date'].dt.isocalendar().week
    df['year'] = df['start_date'].dt.year
    df['distance_mi'] = df['distance'] / 1609.34  # meters to miles

    weekly_miles = df.groupby(['year', 'week'])['distance_mi'].sum().reset_index()
    weekly_miles = weekly_miles.sort_values(['year', 'week'], ascending=False)

    st.subheader("📈 Weekly Mileage")
    st.dataframe(weekly_miles, use_container_width=True)

def load_run_plan(plan_path, start_date):
    # Debug: print the first 7 computed dates and days
    debug_rows = []
    for i in range(min(7, len(plan_df))):
        debug_rows.append((plan_df['Calendar Date'].iloc[i], plan_df['Day'].iloc[i]))
    print("DEBUG: First 7 Calendar Dates and Days:")
    for d, day in debug_rows:
        print(f"  {d} => {day}")
    plan_df = pd.read_csv(plan_path)
    plan_df.columns = plan_df.columns.str.strip()
    if 'Date' not in plan_df.columns:
        st.write('Plan CSV columns:', plan_df.columns.tolist())
        raise KeyError("'Date' column not found in run_plan.csv. Check the CSV header row.")
    import re
    plan_df = plan_df[plan_df['Date'].notnull() & plan_df['Plan'].notnull()]
    plan_df['Date'] = plan_df['Date'].astype(str)
    def extract_miles(plan):
        match = re.search(r'(\d+(?:\.\d+)?)', str(plan))
        return float(match.group(1)) if match else 0.0
    plan_df['Planned Distance (mi)'] = plan_df['Plan'].apply(extract_miles)
    plan_df = plan_df.reset_index(drop=True)
    # Guard: start_date must be valid
    if not start_date or start_date in ["", None, "NaT"]:
        st.error("No valid start date set. Please select a start date in the sidebar.")
        st.stop()
    try:
        start = pd.to_datetime(start_date)
    except Exception as e:
        st.error(f"Invalid start date: {start_date}. Error: {e}")
        st.stop()
    plan_dates = [start + timedelta(days=i) for i in range(len(plan_df))]
    plan_df['Calendar Date'] = [pd.to_datetime(d).date() for d in plan_dates]
    plan_df['Calendar Date Str'] = plan_df['Calendar Date'].astype(str)
    # Remove any existing Day column from CSV
    if 'Day' in plan_df.columns:
        plan_df = plan_df.drop(columns=['Day'])
    # Always compute the Day column from the Calendar Date
    weekday_map = {0: 'M', 1: 'Tu', 2: 'W', 3: 'Th', 4: 'F', 5: 'Sa', 6: 'Su'}
    plan_df['Day'] = [weekday_map[d.weekday()] for d in plan_df['Calendar Date']]
    def expand_activity(plan):
        mapping = {
            'GA': 'General Aerobic',
            'Sp': 'Sprints',
            'MP': 'Marathon Pace',
            'LT': 'Lactate Threshold',
            'HMP': 'Half Marathon Pace',
            'Rec': 'Recovery',
            'MLR': 'Medium-Long Run',
            'LR': 'Long Run'
        }
        s = str(plan)
        for abbr, full in mapping.items():
            s = s.replace(abbr, full)
        return s
    plan_df['Activity'] = plan_df['Plan'].apply(expand_activity)
    return plan_df[['Calendar Date', 'Calendar Date Str', 'Date', 'Day', 'Activity', 'Planned Distance (mi)']]

def compare_plan_vs_actual(activities, plan_path, start_date):
    plan = load_run_plan(plan_path, start_date)
    df = pd.DataFrame(activities)
    df['start_date'] = pd.to_datetime(df['start_date'])
    df['date_str'] = df['start_date'].dt.strftime('%Y-%m-%d')
    df['distance_mi'] = df['distance'] / 1609.34

    # Sum actual miles per day (in case of multiple runs)
    actual = df.groupby('date_str')['distance_mi'].sum().reset_index()
    actual = actual.rename(columns={'distance_mi': 'Actual Distance (mi)', 'date_str': 'Calendar Date Str'})

    merged = plan.merge(actual, on='Calendar Date Str', how='left')
    merged['Actual Distance (mi)'] = merged['Actual Distance (mi)'].fillna(0)
    merged['Planned Distance (mi)'] = merged['Planned Distance (mi)'].fillna(0)
    today = pd.Timestamp.today().date()
    def diff_if_past(row):
        if row['Calendar Date'] < today:
            return row['Actual Distance (mi)'] - row['Planned Distance (mi)']
        return ""
    def hit_if_past(row):
        if row['Calendar Date'] < today:
            planned = row['Planned Distance (mi)']
            actual = row['Actual Distance (mi)']
            if planned == 0 and actual == 0:
                return True
            if planned == 0:
                return False
            return abs(actual - planned) / planned <= 0.2
        return ""
    def actual_if_past(row):
        if row['Calendar Date'] <= today:
            val = row['Actual Distance (mi)']
            # Show blank if value is 0 and in the future
            if pd.isna(val) or (row['Calendar Date'] > today):
                return ""
            # Show blank if value is 0 and not in the past
            if row['Calendar Date'] == today and val == 0:
                return ""
            return str(val) if val != 0 else ""
        return ""
    merged['Diff (mi)'] = merged.apply(diff_if_past, axis=1)
    merged['Hit?'] = merged.apply(hit_if_past, axis=1)
    merged['Actual Distance (mi)'] = merged.apply(actual_if_past, axis=1).astype(str)
    # Sort so today is at the top, past above, future below
    merged['sort_key'] = (merged['Calendar Date'] - today).apply(lambda x: x.days)
    merged = merged.sort_values('sort_key', key=lambda x: x.abs())
    merged = merged.reset_index(drop=True)
    merged['Calendar MM/DD'] = pd.to_datetime(merged['Calendar Date']).dt.strftime('%m/%d')
    return merged[['Calendar Date', 'Calendar Date Str', 'Calendar MM/DD', 'Day', 'Activity', 'Planned Distance (mi)', 'Actual Distance (mi)', 'Diff (mi)', 'Hit?']]

def make_recommendation(activities, plan_path, start_date):
    plan = load_run_plan(plan_path, start_date)
    df = pd.DataFrame(activities)
    df['start_date'] = pd.to_datetime(df['start_date'])
    df['date_str'] = df['start_date'].dt.strftime('%Y-%m-%d')
    df['distance_mi'] = df['distance'] / 1609.34

    today = pd.Timestamp.today().normalize()
    last_7 = [today - pd.Timedelta(days=i) for i in range(7)]
    last_7_str = [d.strftime('%Y-%m-%d') for d in last_7]

    plan7 = plan[plan['Calendar Date Str'].isin(last_7_str)].set_index('Calendar Date Str')
    actual7 = df.groupby('date_str')['distance_mi'].sum()

    summary = []
    for d in last_7_str:
        planned = plan7['Planned Distance (mi)'].get(d, 0)
        actual = actual7.get(d, 0)
        summary.append({'date': d, 'planned': planned, 'actual': actual, 'diff': actual - planned})

    last2 = summary[1:3]
    last2_diff = sum(x['diff'] for x in last2)
    today_plan = summary[0]['planned']

    rec = ""
    if last2_diff < -1:
        rec = f"You've been under your plan by {abs(last2_diff):.1f} miles the last two days. Consider adding 1 mile to today's planned run (planned: {today_plan:.1f} mi → recommended: {today_plan+1:.1f} mi)."
    elif last2_diff > 1:
        rec = f"You've been over your plan by {last2_diff:.1f} miles the last two days. Consider going 1 mile shorter today (planned: {today_plan:.1f} mi → recommended: {max(today_plan-1,0):.1f} mi)."
    else:
        rec = f"You're close to your plan for the last two days. Stick with today's planned run: {today_plan:.1f} mi."

    expl = (
        f"Last 7 days (most recent first):\n" +
        "\n".join([f"{x['date']}: planned {x['planned']:.1f}, actual {x['actual']:.1f}, diff {x['diff']:+.1f}" for x in summary])
    )
    return rec, expl

# --- Guest mode persistence ---


def parse_time_to_seconds(timestr):
    parts = [int(p) for p in timestr.strip().split(":")]
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m = 0, parts[0]
        s = parts[1]
    else:
        raise ValueError("Invalid time format")
    return h * 3600 + m * 60 + s
import requests
import json
import time
import pandas as pd

import numpy as np
from datetime import datetime, timedelta

# Load client_id and client_secret
with open("secrets.json") as f:
    secrets = json.load(f)

client_id = secrets["client_id"]
client_secret = secrets["client_secret"]

# Load tokens
with open("tokens.json") as f:
    tokens = json.load(f)

def refresh_access_token():
    refresh_token = tokens["refresh_token"]
    response = requests.post(
        url="https://www.strava.com/api/v3/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    new_tokens = response.json()
    with open("tokens.json", "w") as f:
        json.dump(new_tokens, f)
    return new_tokens["access_token"]

# Check if token is expired
if time.time() > tokens["expires_at"]:
    access_token = refresh_access_token()
else:
    access_token = tokens["access_token"]

# Fetch activities
def get_activities():
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers)
    return r.json()


# Display weekly mileage
def display_weekly_mileage(activities):
    df = pd.DataFrame(activities)
    df['start_date'] = pd.to_datetime(df['start_date'])
    df['week'] = df['start_date'].dt.isocalendar().week
    df['year'] = df['start_date'].dt.year
    df['distance_mi'] = df['distance'] / 1609.34  # meters to miles

    weekly_miles = df.groupby(['year', 'week'])['distance_mi'].sum().reset_index()
    weekly_miles = weekly_miles.sort_values(['year', 'week'], ascending=False)

    st.subheader("📈 Weekly Mileage")
    st.dataframe(weekly_miles, use_container_width=True)

# Load run plan from CSV
def load_run_plan(plan_path, start_date):
    plan_df = pd.read_csv(plan_path)
    plan_df.columns = plan_df.columns.str.strip()
    if 'Date' not in plan_df.columns:
        st.write('Plan CSV columns:', plan_df.columns.tolist())
        raise KeyError("'Date' column not found in run_plan.csv. Check the CSV header row.")
    import re
    plan_df = plan_df[plan_df['Date'].notnull() & plan_df['Plan'].notnull()]
    plan_df['Date'] = plan_df['Date'].astype(str)
    def extract_miles(plan):
        match = re.search(r'(\d+(?:\.\d+)?)', str(plan))
        return float(match.group(1)) if match else 0.0
    plan_df['Planned Distance (mi)'] = plan_df['Plan'].apply(extract_miles)
    # Assign actual calendar dates based on user-selected start date
    plan_df = plan_df.reset_index(drop=True)
    # Guard: start_date must be valid
    if not start_date or start_date in ["", None, "NaT"]:
        st.error("No valid start date set. Please select a start date in the sidebar.")
        st.stop()
    try:
        start = pd.to_datetime(start_date)
    except Exception as e:
        st.error(f"Invalid start date: {start_date}. Error: {e}")
        st.stop()
    plan_dates = []
    for i, row in plan_df.iterrows():
        plan_dates.append(start + timedelta(days=i))
    plan_df['Calendar Date'] = [pd.to_datetime(d).date() for d in plan_dates]
    plan_df['Calendar Date Str'] = plan_df['Calendar Date'].astype(str)
    # Remove any existing Day column from CSV
    if 'Day' in plan_df.columns:
        plan_df = plan_df.drop(columns=['Day'])
    # Always compute the Day column from the Calendar Date
    weekday_map = {0: 'M', 1: 'Tu', 2: 'W', 3: 'Th', 4: 'F', 5: 'Sa', 6: 'Su'}
    plan_df['Day'] = [weekday_map[d.weekday()] for d in plan_df['Calendar Date']]
    # Debug: print the first 7 computed dates and days
    debug_rows = []
    for i in range(min(7, len(plan_df))):
        debug_rows.append((plan_df['Calendar Date'].iloc[i], plan_df['Day'].iloc[i]))
    print("DEBUG: First 7 Calendar Dates and Days:")
    for d, day in debug_rows:
        print(f"  {d} => {day}")
    def expand_activity(plan):
        mapping = {
            'GA': 'General Aerobic',
            'Sp': 'Sprints',
            'MP': 'Marathon Pace',
            'LT': 'Lactate Threshold',
            'HMP': 'Half Marathon Pace',
            'Rec': 'Recovery',
            'MLR': 'Medium-Long Run',
            'LR': 'Long Run'
        }
        s = str(plan)
        for abbr, full in mapping.items():
            s = s.replace(abbr, full)
        return s
    plan_df['Activity'] = plan_df['Plan'].apply(expand_activity)
    return plan_df[['Calendar Date', 'Calendar Date Str', 'Date', 'Day', 'Activity', 'Planned Distance (mi)']]

# Compare plan vs. actual
def compare_plan_vs_actual(activities, plan_path, start_date):
    plan = load_run_plan(plan_path, start_date)
    df = pd.DataFrame(activities)
    df['start_date'] = pd.to_datetime(df['start_date'])
    df['date_str'] = df['start_date'].dt.strftime('%Y-%m-%d')
    df['distance_mi'] = df['distance'] / 1609.34

    # Sum actual miles per day (in case of multiple runs)
    actual = df.groupby('date_str')['distance_mi'].sum().reset_index()
    actual = actual.rename(columns={'distance_mi': 'Actual Distance (mi)', 'date_str': 'Calendar Date Str'})

    merged = plan.merge(actual, on='Calendar Date Str', how='left')
    merged['Actual Distance (mi)'] = merged['Actual Distance (mi)'].fillna(0)
    merged['Planned Distance (mi)'] = merged['Planned Distance (mi)'].fillna(0)
    today = pd.Timestamp.today().date()
    def diff_if_past(row):
        if row['Calendar Date'] < today:
            return row['Actual Distance (mi)'] - row['Planned Distance (mi)']
        return ""
    def hit_if_past(row):
        if row['Calendar Date'] < today:
            planned = row['Planned Distance (mi)']
            actual = row['Actual Distance (mi)']
            if planned == 0 and actual == 0:
                return True
            if planned == 0:
                return False
            return abs(actual - planned) / planned <= 0.2
        return ""
    def actual_if_past(row):
        if row['Calendar Date'] <= today:
            val = row['Actual Distance (mi)']
            # Show blank if value is 0 and in the future
            if pd.isna(val) or (row['Calendar Date'] > today):
                return ""
            # Show blank if value is 0 and not in the past
            if row['Calendar Date'] == today and val == 0:
                return ""
            return str(val) if val != 0 else ""
        return ""
    merged['Diff (mi)'] = merged.apply(diff_if_past, axis=1)
    merged['Hit?'] = merged.apply(hit_if_past, axis=1)
    merged['Actual Distance (mi)'] = merged.apply(actual_if_past, axis=1).astype(str)
    # Sort so today is at the top, past above, future below
    merged['sort_key'] = (merged['Calendar Date'] - today).apply(lambda x: x.days)
    merged = merged.sort_values('sort_key', key=lambda x: x.abs())
    merged = merged.reset_index(drop=True)
    merged['Calendar MM/DD'] = pd.to_datetime(merged['Calendar Date']).dt.strftime('%m/%d')
    return merged[['Calendar Date', 'Calendar Date Str', 'Calendar MM/DD', 'Day', 'Activity', 'Planned Distance (mi)', 'Actual Distance (mi)', 'Diff (mi)', 'Hit?']]

# Recommendation section
def make_recommendation(activities, plan_path, start_date):
    plan = load_run_plan(plan_path, start_date)
    df = pd.DataFrame(activities)
    df['start_date'] = pd.to_datetime(df['start_date'])
    df['date_str'] = df['start_date'].dt.strftime('%Y-%m-%d')
    df['distance_mi'] = df['distance'] / 1609.34

    today = pd.Timestamp.today().normalize()
    last_7 = [today - pd.Timedelta(days=i) for i in range(7)]
    last_7_str = [d.strftime('%Y-%m-%d') for d in last_7]

    plan7 = plan[plan['Calendar Date Str'].isin(last_7_str)].set_index('Calendar Date Str')
    actual7 = df.groupby('date_str')['distance_mi'].sum()

    summary = []
    for d in last_7_str:
        planned = plan7['Planned Distance (mi)'].get(d, 0)
        actual = actual7.get(d, 0)
        summary.append({'date': d, 'planned': planned, 'actual': actual, 'diff': actual - planned})

    last2 = summary[1:3]
    last2_diff = sum(x['diff'] for x in last2)
    today_plan = summary[0]['planned']

    rec = ""
    if last2_diff < -1:
        rec = f"You've been under your plan by {abs(last2_diff):.1f} miles the last two days. Consider adding 1 mile to today's planned run (planned: {today_plan:.1f} mi → recommended: {today_plan+1:.1f} mi)."
    elif last2_diff > 1:
        rec = f"You've been over your plan by {last2_diff:.1f} miles the last two days. Consider going 1 mile shorter today (planned: {today_plan:.1f} mi → recommended: {max(today_plan-1,0):.1f} mi)."
    else:
        rec = f"You're close to your plan for the last two days. Stick with today's planned run: {today_plan:.1f} mi."

    expl = (
        f"Last 7 days (most recent first):\n" +
        "\n".join([f"{x['date']}: planned {x['planned']:.1f}, actual {x['actual']:.1f}, diff {x['diff']:+.1f}" for x in summary])
    )
    return rec, expl


# Streamlit UI
login_placeholder = st.empty()

# Use Google OAuth user info for dashboard
user_email = st.session_state.get("user_email")
if user_email:
    dashboard_logic(user_email, user_email)





