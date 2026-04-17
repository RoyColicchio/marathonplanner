# Marathon Training Planner

Pfitzinger-based marathon training calendar with Strava integration.

## Deploy to Streamlit Cloud

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "initial"
git remote add origin https://github.com/YOUR_USERNAME/marathon-planner.git
git push -u origin main
```

### 2. Deploy on Streamlit Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Click **New app**
3. Select your repo, branch `main`, file `app.py`
4. Under **Advanced settings > Secrets**, paste:

```toml
STRAVA_CLIENT_ID = "171563"
STRAVA_CLIENT_SECRET = "61d6da8af3fe3273ed909dadaee7af693a8bd1df"
REDIRECT_URI = "https://YOUR-APP-NAME.streamlit.app"
```

Replace `YOUR-APP-NAME` with whatever Streamlit assigns (e.g. `marathonplanner`).

### 3. Update Strava callback domain

Go to [strava.com/settings/api](https://www.strava.com/settings/api) and set:
- **Authorization Callback Domain**: `YOUR-APP-NAME.streamlit.app`

That's it — no localhost, no file://, no token issues.
