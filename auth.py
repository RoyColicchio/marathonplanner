import requests
import json
import time
import os

#
CLIENT_ID = 171563
CLIENT_SECRET = db5b605f66158bcf80d1ddda5a6a2739e66899dd
REFRESH_URL = "https://www.strava.com/api/v3/oauth/token"
TOKENS_FILE = "tokens.json"

def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, "r") as f:
            return json.load(f)
    else:
        raise FileNotFoundError("tokens.json not found. Run manual auth first.")

def save_tokens(tokens):
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f)

def refresh_access_token(refresh_token):
    print("🔄 Refreshing Strava access token...")
    response = requests.post(REFRESH_URL, data={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
    })

    if response.status_code != 200:
        raise Exception("Failed to refresh token:", response.text)

    tokens = response.json()
    save_tokens(tokens)
    return tokens

def get_access_token():
    tokens = load_tokens()
    now = int(time.time())

    if tokens['expires_at'] < now:
        tokens = refresh_access_token(tokens['refresh_token'])

    return tokens['access_token']
