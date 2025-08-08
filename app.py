import streamlit as st
st.set_page_config(
    page_title="Marathon Planner",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Test if the app loads at all
st.title("Marathon Training Dashboard")
st.write("✅ App is loading successfully!")

# Check if we have basic imports
try:
    from streamlit_oauth import OAuth2Component
    st.write("✅ streamlit-oauth imported")
except ImportError as e:
    st.error(f"❌ streamlit-oauth import failed: {e}")

try:
    import pandas as pd
    st.write("✅ pandas imported")
except ImportError as e:
    st.error(f"❌ pandas import failed: {e}")

try:
    from st_aggrid import AgGrid
    st.write("✅ st_aggrid imported")
except ImportError as e:
    st.error(f"❌ st_aggrid import failed: {e}")

try:
    from pace_utils import marathon_pace_seconds
    st.write("✅ pace_utils imported")
except ImportError as e:
    st.error(f"❌ pace_utils import failed: {e}")

# Check environment
st.write("🔍 **Environment Check:**")
import os
google_client_id = st.secrets.get("google_client_id") or os.getenv("GOOGLE_CLIENT_ID")
google_client_secret = st.secrets.get("google_client_secret") or os.getenv("GOOGLE_CLIENT_SECRET")
st.write(f"Google Client ID found: {bool(google_client_id)}")
st.write(f"Google Client Secret found: {bool(google_client_secret)}")

if not google_client_id or not google_client_secret:
    st.error("❌ Missing Google OAuth credentials!")
    st.info("Please set google_client_id and google_client_secret in Streamlit Cloud Secrets.")
    st.stop()

st.success("✅ Basic app structure is working! This confirms the deployment is successful.")
st.info("If you can see this message, the app is loading correctly. The blank page issue should be resolved.")