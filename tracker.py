import requests
import webbrowser
import pandas as pd

CLIENT_ID = "171563"
CLIENT_SECRET = "db5b605f66158bcf80d1ddda5a6a2739e66899dd"
REDIRECT_URI = 'http://localhost/exchange_token'

# Step 1: Get Strava authorization code
def get_authorization_code():
    auth_url = (
        f"https://www.strava.com/oauth/authorize?client_id={CLIENT_ID}"
        f"&response_type=code&redirect_uri={REDIRECT_URI}"
        f"&approval_prompt=force&scope=activity:read"
    )
    print("Open this URL in your browser:")
    print(auth_url)
    print("\nAfter logging in, paste the 'code' param from the redirected URL here:")
    return input("Auth code: ")


# Step 2: Exchange code for access token
def get_access_token(code):
    token_url = "https://www.strava.com/oauth/token"
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code'
    }
    response = requests.post(token_url, data=payload)
    return response.json()['access_token']

# Step 3: Get activities
def get_activities(token):
    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {'Authorization': f'Bearer {token}'}
    params = {'per_page': 50, 'page': 1}
    res = requests.get(url, headers=headers, params=params)
    return pd.DataFrame(res.json())

# Run everything
if __name__ == "__main__":
    auth_code = get_authorization_code()
    token = get_access_token(auth_code)
    df = get_activities(token)

    print("\nRecent Runs:")
    print(df[['name', 'distance', 'moving_time', 'elapsed_time', 'average_speed']].head())
import matplotlib.pyplot as plt

# Convert date column to datetime
df['start_date'] = pd.to_datetime(df['start_date'])

# Filter to runs only (optional)
runs = df[df['type'] == 'Run'].copy()

# Extract ISO week number
runs['week'] = runs['start_date'].dt.isocalendar().week

# Sum distance per week (convert meters → miles or km)
weekly_miles = runs.groupby('week')['distance'].sum() / 1609.34
weekly_miles = weekly_miles.sort_index()

plt.figure(figsize=(10, 5))
weekly_miles.plot(kind='bar', title='Weekly Running Distance (miles)', color='skyblue')
plt.xlabel("Week Number")
plt.ylabel("Distance (miles)")

