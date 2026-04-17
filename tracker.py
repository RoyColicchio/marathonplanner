import requests
import json
import time
import pandas as pd

# Load client credentials from secrets
with open('secrets.json') as f:
    secrets = json.load(f)

CLIENT_ID = secrets['client_id']
CLIENT_SECRET = secrets['client_secret']

# Load existing tokens
with open('tokens.json') as f:
    tokens = json.load(f)

# Refresh token if expired
if time.time() > tokens['expires_at']:
    print("Access token expired. Refreshing...")
    response = requests.post(
        url='https://www.strava.com/oauth/token',
        data={
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'refresh_token': tokens['refresh_token']
        }
    )
    tokens = response.json()

    # Save new tokens
    with open('tokens.json', 'w') as f:
        json.dump(tokens, f)
    print("Access token refreshed and saved.")

# Use access token to fetch recent activities
access_token = tokens['access_token']
headers = {'Authorization': f'Bearer {access_token}'}

response = requests.get(
    'https://www.strava.com/api/v3/athlete/activities',
    headers=headers,
    params={'per_page': 5}
)

activities = response.json()
df = pd.json_normalize(activities)
print("\nRecent Runs:")
print(df[['name', 'distance', 'moving_time', 'elapsed_time', 'average_speed']])
