import streamlit as st
import requests
import pandas as pd

st.title("🏃‍♂️ Strava Weekly Mileage Tracker")

# Step 1: Auth fields
client_id = st.text_input("Strava Client ID", "")
client_secret = st.text_input("Strava Client Secret", "", type="password")
auth_code = st.text_input("Authorization Code (from redirect URL)", "")

# Step 2: On button click
if st.button("Get My Weekly Miles") and client_id and client_secret and auth_code:
    # Step 3: Get access token
    token_url = "https://www.strava.com/oauth/token"
    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': auth_code,
        'grant_type': 'authorization_code'
    }
    res = requests.post(token_url, data=payload)
    access_token = res.json().get("access_token")

    # Step 4: Get activities
    headers = {'Authorization': f'Bearer {access_token}'}
    activities_url = "https://www.strava.com/api/v3/athlete/activities"
    params = {'per_page': 100, 'page': 1}
    act_res = requests.get(activities_url, headers=headers, params=params)
    df = pd.DataFrame(act_res.json())

    # Step 5: Show chart
    if df.empty:
        st.warning("No activities found.")
    else:
        df['start_date'] = pd.to_datetime(df['start_date'])
        runs = df[df['type'] == 'Run'].copy()
        runs['week'] = runs['start_date'].dt.isocalendar().week
        weekly_miles = runs.groupby('week')['distance'].sum() / 1609.34

        st.subheader("📊 Weekly Mileage")
        st.bar_chart(weekly_miles.sort_index())

        st.markdown("🔁 Paste a new authorization code if token expires.")
