
import streamlit as st
st.set_page_config(layout="wide")
import streamlit_authenticator as stauth
import yaml
import json
from pathlib import Path
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
from pace_utils import marathon_pace_seconds, get_pace_range

# --- Authentication ---
with open('config.yaml') as file:
    config = yaml.safe_load(file)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days'],
    config['preauthorized']
)

name, authentication_status, username = authenticator.login('Login', 'main')

if authentication_status:
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

PACE_MAPPING = [
    {"type": "Long Run", "keywords": ["Long Run", "LR"], "delta": (45, 90)},
    {"type": "Medium-Long Run", "keywords": ["Medium-Long Run", "MLR"], "delta": (30, 75)},
    {"type": "General Aerobic", "keywords": ["General Aerobic"], "delta": (45, 90)},
    {"type": "Recovery Run", "keywords": ["Recovery"], "delta": (90, 144)},
    {"type": "Marathon Pace Run", "keywords": ["Marathon Pace"], "delta": (0, 0)},
    {"type": "LT/Tempo Run", "keywords": ["Lactate Threshold", "Tempo"], "delta": (-48, -24)},
    {"type": "VO₂ Max Intervals", "keywords": ["VO₂Max"], "delta": (-96, -72)},
    {"type": "Strides", "keywords": ["Sprints", "Strides"], "delta": (-50, -35)},
]

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
    # Find the first row in the plan (assume it's the first Monday or first day)
    plan_df = plan_df.reset_index(drop=True)
    # Map plan to calendar dates
    start = pd.to_datetime(start_date)
    plan_dates = []
    for i, row in plan_df.iterrows():
        plan_dates.append(start + timedelta(days=i))
    plan_df['Calendar Date'] = [pd.to_datetime(d).date() for d in plan_dates]
    plan_df['Calendar Date Str'] = plan_df['Calendar Date'].astype(str)
    # Expand abbreviations in Activity
    def expand_activity(plan):
        mapping = {
            'GA': 'General Aerobic',
            'Sp': 'Sprints',
            'MP': 'Marathon Pace',
            'LT': 'Lactate Threshold',
            'HMP': 'Half Marathon Pace',
            'Rec': 'Recovery',
            'MLR': 'Medium-Long Run',
            'LR': 'Long Run',
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




# --- Always show plan and recommendations automatically ---
if authentication_status:
    plan_choice = user_settings["plan"]
    start_date = user_settings["start_date"]
    goal_marathon_time = user_settings["goal_time"]
    try:
        activities = get_activities()
        comparison = compare_plan_vs_actual(activities, plan_choice, start_date)
        # Calculate GMP pace in seconds
        gmp_sec = marathon_pace_seconds(goal_marathon_time)
        # Add suggested pace range column
        comparison["Suggested Pace Range"] = comparison["Activity"].apply(lambda x: get_pace_range(x, gmp_sec))
        # Find today's row index
        today_str = pd.Timestamp.today().strftime('%Y-%m-%d')
        if today_str in comparison['Calendar Date Str'].values:
            today_idx = comparison[comparison['Calendar Date Str'] == today_str].index[0]
        else:
            today_idx = 0

        st.subheader("Your Plan")
        # Prepare main_df for AgGrid
        main_cols = ["Calendar MM/DD", "Day", "Activity", "Suggested Pace Range", "Planned Distance (mi)", "Actual Distance (mi)", "Diff (mi)", "Hit?"]
        main_cols = [c for c in main_cols if c in comparison.columns]
        main_df = comparison[main_cols].reset_index(drop=True)
        # Custom cellStyle JS for zebra striping and bolding today's row
        # Use Calendar MM/DD for bolding since that's the visible column
        today_mmdd = pd.Timestamp.today().strftime('%m/%d')
        bold_today_zebra_js = JsCode('''
        function(params) {
            const todayStr = '%s';
            const isToday = params.data && params.data['Calendar MM/DD'] === todayStr;
            let style = {};
            if (params.node.rowIndex %% 2 === 0) {
                style.backgroundColor = '#f7f7f7';
                style.color = '#222';
            }
            if (isToday) {
                style.backgroundColor = '#ffe066';
                style.fontWeight = 'bold';
            }
            return style;
        }
        ''' % today_mmdd)
        default_col_width = 160
        gb = GridOptionsBuilder.from_dataframe(main_df)
        gb.configure_default_column(resizable=True, filter=True, sortable=True, cellStyle={"fontSize": "16px"})
        gb.configure_grid_options(domLayout='normal')
        for col in main_cols:
            if col == "Activity":
                gb.configure_column(col, headerClass="ag-header-bold", cellStyle=bold_today_zebra_js, width=350, wrapText=True, autoHeight=True)
            else:
                gb.configure_column(col, headerClass="ag-header-bold", cellStyle=bold_today_zebra_js, width=default_col_width)
        grid_options = gb.build()
        # Add onGridReady to scroll to today's row
        scroll_to_today_js = f'''
        function onGridReady(params) {{
            let rowIndex = null;
            params.api.forEachNode((node) => {{
                if (node.data['Calendar Date Str'] === '{today_str}') {{
                    rowIndex = node.rowIndex;
                }}
            }});
            if (rowIndex !== null) {{
                params.api.ensureIndexVisible(rowIndex, 'middle');
            }}
        }}
        '''
        grid_options['onGridReady'] = scroll_to_today_js
        grid_return = AgGrid(
            main_df,
            gridOptions=grid_options,
            height=750,
            theme="alpine",
            allow_unsafe_jscode=True,
            reload_data=True,
            update_mode="NO_UPDATE",
            fit_columns_on_grid_load=False,
            use_container_width=True
        )

        # Full details in expander
        with st.expander("Show all plan columns"):
            st.dataframe(comparison, use_container_width=True, height=600)

        rec, expl = make_recommendation(activities, plan_choice, start_date)
        st.subheader("📝 Recommendation for Today")
        st.write(rec)
        with st.expander("Show logic and last 7 days summary"):
            st.text(expl)
    except Exception as e:
        st.error(f"Error showing plan: {e}")
else:
    if authentication_status is False:
        st.error('Username/password is incorrect')
    elif authentication_status is None:
        st.warning('Please enter your username and password')
