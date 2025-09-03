import streamlit as st
import os
import sys
import numpy as np
import json
import hashlib
import time
import traceback
import requests
import pandas as pd
import re

# Build/version identifier to verify deployment
BUILD_SHA = "6ef227c"

# Enable debugging if needed - for local development only
DEBUG_SECRETS = os.getenv("DEBUG_SECRETS", "").lower() in ("true", "1", "yes")

# Debug helper function
def _is_debug():
    """Return True if diagnostics should be shown (env, secrets, or ?debug)."""
    try:
        if DEBUG_SECRETS:
            return True
        if bool(st.secrets.get("show_strava_debug", False)):
            return True
        if "debug" in st.query_params:
            return True
        return (
            os.getenv("DEBUG", "").lower() in ("1", "true", "yes")
            or bool(st.secrets.get("debug", False))
        )
    except Exception:
        return False

def _debug_info(msg, *args):
    """Show debug info if debug mode is enabled."""
    if _is_debug():
        if args:
            st.info(f"Debug: {msg}: {args}")
        else:
            st.info(f"Debug: {msg}")

st.set_page_config(
    page_title="Marathon Planner",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Show a tiny build tag to confirm which version is running
st.caption(f"Build: {BUILD_SHA}")

# Simple, clean styling that doesn't interfere with functionality
st.markdown("""
<style>
    :root {
        --bg: #0b1220;
        --card: #0f172a;
        --muted: #94a3b8;
        --text: #e2e8f0;
        --accent: #22c55e;
        --accent-2: #06b6d4;
        --border: #1e293b;
    }
    html, body, [class*="css"], [data-testid="stAppViewContainer"] * {
        font-family: 'Inter', system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    }
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(180deg, #0a0f1e, #0b1220 30%);
        color: var(--text);
    }
    .main .block-container {
        padding-top: 1.5rem;
        max-width: 1200px;
    }
    /* Title with subtle gradient */
    h1, h2, h3 { color: var(--text); }
    h1 span.gradient {
        background: linear-gradient(90deg, var(--accent), var(--accent-2));
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    /* Cards */
    .mp-card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 16px 18px;
        background: linear-gradient(180deg, #0b152a 0%, #0a1427 100%) !important;
        color: var(--text) !important;
        transition: transform .05s ease, border-color .2s ease;
    }
    .stButton>button:hover, a[data-baseweb="button"]:hover {
        border-color: var(--accent) !important;
        transform: translateY(-1px);
    }
    /* Dataframe wrapper */
    [data-testid="stDataFrame"] div[data-testid="stVerticalBlock"] {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 6px 6px 2px 6px;
    }
    /* Hide Streamlit chrome for a cleaner look */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

from streamlit_oauth import OAuth2Component
# Try to import the specific error to catch state mismatches explicitly
try:
    from streamlit_oauth import StreamlitOauthError  # type: ignore
except Exception:
    class StreamlitOauthError(Exception):
        pass

import json
import hashlib
from pathlib import Path
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, GridUpdateMode, DataReturnMode

# Import pace_utils with error handling
try:
    from pace_utils import marathon_pace_seconds, get_pace_range
except ImportError as e:
    st.error(f"Failed to import pace_utils: {e}")
    # Provide fallback functions
    def marathon_pace_seconds(goal_time: str) -> float:
        try:
            h, m, s = map(int, goal_time.split(':'))
            total_seconds = h * 3600 + m * 60 + s
            return total_seconds / 26.2188
        except Exception:
            return 600.0
    
    def get_pace_range(activity_description: str, goal_marathon_pace_seconds: float, plan_file: str = "") -> str:
        return "—"

import requests
import time
import os
import pandas as pd
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote
from pathlib import Path

# Helper: list available plan CSVs (root and ./plans), validate by presence of 'Plan' column
def list_available_plans():
    try:
        candidates = []
        seen = set()

        def add_if_valid(p: Path):
            try:
                if not p.exists() or p.suffix.lower() != ".csv":
                    return
                if p.name in seen:
                    return
                # validate columns
                df = pd.read_csv(p, nrows=1, header=0)
                cols = [str(c).strip() for c in df.columns]
                cols_lower = {c.lower() for c in cols}
                # Accept either simple list CSV (with 'Plan' column) or weekly matrix CSVs (with weekday columns)
                weekday_cols = {"monday","tuesday","wednesday","thursday","friday","saturday","sunday"}
                if ("plan" in cols_lower) or (len(cols_lower.intersection(weekday_cols)) >= 3):
                    candidates.append(str(p))
                    seen.add(p.name)
                    return
            except Exception:
                # ignore unreadable files but fall through to filename-based allowlist below
                pass
            # Fallback: explicitly allow known plan files by filename if they exist
            if p.name.lower() in {"18-weeks-50-miles-peak-hal.csv"}:
                candidates.append(str(p))
                seen.add(p.name)

        def add_ics_if_valid(p: Path):
            try:
                if not p.exists() or p.suffix.lower() != ".ics":
                    return
                if p.name in seen:
                    return
                # quick validation: contains VEVENT and SUMMARY
                with p.open("r", encoding="utf-8") as f:
                    head = f.read(4096)
                if "BEGIN:VEVENT" in head and "SUMMARY" in head:
                    candidates.append(str(p))
                    seen.add(p.name)
            except Exception:
                pass

        add_if_valid(Path("run_plan.csv"))
        for p in Path(".").glob("*.csv"):
            add_if_valid(p)
        for p in Path(".").glob("*.ics"):
            add_ics_if_valid(p)
        plan_dir = Path("plans")
        if plan_dir.exists():
            for p in plan_dir.glob("*.csv"):
                add_if_valid(p)
            for p in plan_dir.glob("*.ics"):
                add_ics_if_valid(p)

        # Fallback to default if none validated
        if not candidates and Path("run_plan.csv").exists():
            candidates.append("run_plan.csv")
        return candidates
    except Exception:
        return ["run_plan.csv"] if Path("run_plan.csv").exists() else []

# Friendly names for plan files
def plan_display_name(p: str) -> str:
    name = Path(p).name
    lname = name.lower()

    # Helper to compute peak weekly mileage for CSV plans with weekday columns
    def _compute_peak_weekly_miles(csv_path: str):
        try:
            df = pd.read_csv(csv_path, header=0)
            df.columns = [str(c).strip() for c in df.columns]
            day_cols = [c for c in df.columns if c.lower() in [
                "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
            ]]
            if not day_cols:
                return None
            peak = 0.0
            for _, row in df.iterrows():
                # Skip race week totals so peak reflects training, not marathon week
                row_text = " ".join(str(row.get(c, "")) for c in day_cols)
                if isinstance(row_text, str) and "marathon race" in row_text.lower():
                    continue
                total = 0.0
                for c in day_cols:
                    cell = row.get(c, "")
                    if pd.isna(cell):
                        continue
                    s = str(cell).strip()
                    if not s or s.lower() == "nan":
                        continue
                    # Extract the first primary miles number, ignoring x-reps and K distances
                    found = None
                    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\b", s):
                        start, end = m.span(1)
                        # Ignore kilometer tokens like 10K
                        if end < len(s) and s[end].lower() == 'k':
                            continue
                        # Ignore repeated segment counts like 6 x 1 mile
                        prev = s[max(0, start-2):start].lower()
                        if 'x' in prev:
                            continue
                        try:
                            found = float(m.group(1))
                            break
                        except Exception:
                            pass
                    if found is not None:
                        total += found
                peak = max(peak, total)
            return int(round(peak)) if peak > 0 else None
        except Exception:
            return None

    # Known mappings
    if name == "run_plan.csv":
        return "18 Weeks, 55 Mile/Week Peak"
    if lname in ("unofficial-pfitz-18-63.ics", "pfitz-18-63.ics"):
        return "18 Weeks, 63 Mile/Week Peak"
    if lname in ("18-weeks-50-miles-peak-hal.csv",):
        return "18 Weeks, 50 Miles/Week Peak (Hal)"
    if lname.endswith(".ics") and "63" in lname:
        return "18 Weeks, 63 Mile/Week Peak"

    # Jack Daniels 2Q variants with dynamic peak MPW
    if lname.startswith("jd-2q-18w-") and lname.endswith(".csv"):
        vol = "Volume"
        if "low" in lname:
            vol = "Low Volume"
        elif "mid" in lname:
            vol = "Mid Volume"
        elif "high" in lname:
            vol = "High Volume"
        elif "elite" in lname:
            vol = "Elite"
        peak = _compute_peak_weekly_miles(p)
        suffix = f", Peak {peak} mi/wk" if peak else ""
        return f"Jack Daniels 2Q (18 Weeks, {vol}{suffix})"

    return name

# ---- Plan stats helpers for UI ----
def compute_peak_weekly_miles(csv_path: str):
    try:
        if not str(csv_path).lower().endswith('.csv'):
            return None
        df = pd.read_csv(csv_path, header=0)
        df.columns = [str(c).strip() for c in df.columns]
        day_cols = [c for c in df.columns if c.lower() in [
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
        ]]
        if not day_cols:
            return None
        peak = 0.0
        for _, row in df.iterrows():
            row_text = " ".join(str(row.get(c, "")) for c in day_cols)
            if isinstance(row_text, str) and "marathon race" in row_text.lower():
                continue
            total = 0.0
            for c in day_cols:
                val = row.get(c, "")
                if pd.isna(val) or not str(val).strip():
                    continue
                miles = extract_primary_miles(str(val))
                if miles:
                    total += float(miles)
            peak = max(peak, total)
        return int(round(peak)) if peak > 0 else None
    except Exception:
        return None

def compute_weekly_miles_series(csv_path: str):
    try:
        if not str(csv_path).lower().endswith('.csv'):
            return []
        df = pd.read_csv(csv_path, header=0)
        df.columns = [str(c).strip() for c in df.columns]
        day_cols = [c for c in df.columns if c.lower() in [
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
        ]]
        if not day_cols:
            return []
        series = []
        for _, row in df.iterrows():
            row_text = " ".join(str(row.get(c, "")) for c in day_cols)
            if isinstance(row_text, str) and "marathon race" in row_text.lower():
                continue
            total = 0.0
            for c in day_cols:
                val = row.get(c, "")
                if pd.isna(val) or not str(val).strip():
                    continue
                miles = extract_primary_miles(str(val))
                if miles:
                    total += float(miles)
            series.append(total)
        return series
    except Exception:
        return []

def count_weeks(csv_path: str):
    try:
        if not str(csv_path).lower().endswith('.csv'):
            return None
        df = pd.read_csv(csv_path, header=0)
        df.columns = [str(c).strip() for c in df.columns]
        day_cols = [c for c in df.columns if c.lower() in [
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
        ]]
        if not day_cols:
            return None
        # Count rows that have any non-empty day value
        valid_rows = 0
        for _, row in df.iterrows():
            if any(bool(str(row.get(c, "")).strip()) for c in day_cols):
                valid_rows += 1
        return valid_rows or None
    except Exception:
        return None

# Lightweight ICS parser for plan activities
def parse_ics_activities(file_path: str) -> list[str]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return []
    # Unfold lines per RFC 5545 (lines starting with space/tab continue previous)
    lines = raw.replace("\r\n", "\n").split("\n")
    unfolded = []
    for line in lines:
        if line.startswith(" ") or line.startswith("\t"):
            if unfolded:
                unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    events = []
    current = None
    for line in unfolded:
        s = line.strip()
        if s == "BEGIN:VEVENT":
            current = {}
        elif s == "END:VEVENT":
            if current and ("SUMMARY" in current or any(k.startswith("SUMMARY") for k in current)):
                # pick DTSTART-like key
                dt_val = None
                for k, v in current.items():
                    if k.startswith("DTSTART"):
                        dt_val = v
                        break
                dt_parsed = None
                if dt_val:
                    m = re.search(r"(\d{8})(T\d{6}Z?)?", dt_val)
                    if m:
                        ymd = m.group(1)
                        try:
                            dt_parsed = datetime.strptime(ymd, "%Y%m%d")
                        except Exception:
                            dt_parsed = None
                # get summary value
                summary = None
                if "SUMMARY" in current:
                    summary = current["SUMMARY"]
                else:
                    for k, v in current.items():
                        if k.startswith("SUMMARY"):
                            summary = v
                            break
                if summary:
                    events.append({"date": dt_parsed, "summary": summary})
            current = None
        else:
            if current is not None and ":" in line:
                k, v = line.split(":", 1)
                current[k] = v
    # sort by date if available
    events.sort(key=lambda e: e["date"] or datetime.max)
    activities = [e["summary"].strip() for e in events if e.get("summary")]
    return activities

# Filter: weekly summary lines like "Training Week 1 Distance: 47 mi"
def is_weekly_summary(text: str) -> bool:
    try:
        if not isinstance(text, str):
            return False
        s = text.strip().lower()
        if not s:
            return False
        # Must start with "training week" and include distance/total or a mileage number
        if s.startswith("training week"):
            if "distance" in s or "total" in s:
                return True
            if re.search(r"\b\d+\s*(mi|mile|miles|km|kilometer|kilomet(er|re)s)\b", s):
                return True
        return False
    except Exception:
        return False

# Helper: get Strava credentials from secrets (section or top-level) or environment
def get_strava_credentials():
    client_id = None
    client_secret = None

    try:
        # Prefer section
        if "strava" in st.secrets:
            sect = st.secrets["strava"]
            client_id = sect.get("client_id")
            client_secret = sect.get("client_secret")
        # Fallback: top-level keys
        if (not client_id or not client_secret):
            client_id = client_id or st.secrets.get("strava_client_id")
            client_secret = client_secret or st.secrets.get("strava_client_secret")
    except Exception:
        pass

    # Fallback: read local .streamlit/secrets.toml directly (simple parser)
    if not client_id or not client_secret:
        try:
            path = os.path.join(os.getcwd(), ".streamlit", "secrets.toml")
            if os.path.exists(path):
                current_section = None
                top = {}
                sections = {}
                with open(path, "r", encoding="utf-8") as f:
                    for raw in f:
                        line = raw.strip()
                        if not line or line.startswith("#") or line.startswith(";"):
                            continue
                        if line.startswith("[") and line.endswith("]"):
                            current_section = line[1:-1].strip()
                            sections.setdefault(current_section, {})
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip()
                            # strip quotes if present
                            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                                val = val[1:-1]
                            if current_section:
                                sections[current_section][key] = val
                            else:
                                top[key] = val
                # Pull values from parsed data
                if not client_id:
                    client_id = (sections.get("strava", {}) or {}).get("client_id") or top.get("strava_client_id")
                if not client_secret:
                    client_secret = (sections.get("strava", {}) or {}).get("client_secret") or top.get("strava_client_secret")
        except Exception:
            pass

    # Try loading from secrets.json file directly
    if not client_id or not client_secret:
        try:
            secrets_path = os.path.join(os.getcwd(), "secrets.json")
            if os.path.exists(secrets_path):
                with open(secrets_path, "r", encoding="utf-8") as f:
                    secrets_data = json.load(f)
                    # Try to get from strava section
                    if "strava" in secrets_data:
                        client_id = client_id or secrets_data["strava"].get("client_id")
                        client_secret = client_secret or secrets_data["strava"].get("client_secret")
                    # Also try top-level keys
                    client_id = client_id or secrets_data.get("strava_client_id") or secrets_data.get("client_id")
                    client_secret = client_secret or secrets_data.get("strava_client_secret") or secrets_data.get("client_secret")
        except Exception as e:
            st.warning(f"Error reading secrets.json: {str(e)}")

    # Environment fallback
    if not client_id:
        client_id = os.getenv("STRAVA_CLIENT_ID")
    if not client_secret:
        client_secret = os.getenv("STRAVA_CLIENT_SECRET")

    # We could add debug output here if needed in the future
    
    # Normalize
    if isinstance(client_id, str):
        client_id = client_id.strip("\"' ")
    if isinstance(client_secret, str):
        client_secret = client_secret.strip("\"' ")

    return client_id, client_secret

# Resolve Google OAuth credentials
google_client_id = st.secrets.get("google_client_id") or os.getenv("GOOGLE_CLIENT_ID")
google_client_secret = st.secrets.get("google_client_secret") or os.getenv("GOOGLE_CLIENT_SECRET")

# Development mode toggle (allows local login without Google OAuth)
DEV_MODE = (
    os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes")
    or bool(st.secrets.get("dev_mode", False))
)

_missing_google_creds = not google_client_id or not google_client_secret

# Do not stop the app if creds are missing; we'll render a fallback login instead
if _missing_google_creds and not DEV_MODE:
    st.warning(
        "Google OAuth is not configured. Set google_client_id and google_client_secret in Secrets or environment."
    )

# Initialize session state
if "current_user" not in st.session_state:
    st.session_state.current_user = None
if "google_oauth_component" not in st.session_state:
    st.session_state.google_oauth_component = None
if "auth_checked" not in st.session_state:
    st.session_state.auth_checked = False
# Goal Time Coach state
if "goal_coach_open" not in st.session_state:
    st.session_state.goal_coach_open = False
if "goal_coach_messages" not in st.session_state:
    st.session_state.goal_coach_messages = []
if "goal_coach_step" not in st.session_state:
    st.session_state.goal_coach_step = 0
if "goal_coach_answers" not in st.session_state:
    st.session_state.goal_coach_answers = {}
if "goal_coach_cons" not in st.session_state:
    st.session_state.goal_coach_cons = None
if "goal_coach_amb" not in st.session_state:
    st.session_state.goal_coach_amb = None
if "plan_grid_sel" not in st.session_state:
    st.session_state.plan_grid_sel = []
if "plan_needs_refresh" not in st.session_state:
    st.session_state.plan_needs_refresh = False
if "plan_setup_visible" not in st.session_state:
    st.session_state.plan_setup_visible = False  # Collapsed by default
if "current_week" not in st.session_state:
    st.session_state.current_week = 1
if "last_plan_sig" not in st.session_state:
    st.session_state.last_plan_sig = None

# --- Goal Time Coach helpers ---
import re as _re_gc
from math import floor as _floor

def _gc_seconds_to_hms(total_s: float) -> str:
    s = max(0, int(round(total_s)))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h}:{m:02d}:{sec:02d}"

def _gc_parse_time_str(t: str):
    if not isinstance(t, str):
        return None
    t = t.strip()
    # Accept H:MM:SS or M:SS
    if _re_gc.fullmatch(r"\d{1,2}:\d{2}:\d{2}", t):
        h, m, s = [int(x) for x in t.split(":")]
        return h * 3600 + m * 60 + s
    if _re_gc.fullmatch(r"\d{1,2}:\d{2}", t):
        m, s = [int(x) for x in t.split(":")]
        return m * 60 + s
    # Also accept just minutes integer
    if _re_gc.fullmatch(r"\d{1,3}", t):
        return int(t) * 60
    return None

def _gc_parse_race(msg: str):
    if not isinstance(msg, str):
        return None, None
    txt = msg.strip().lower()
    if txt in ("skip", "none", "no"):
        return None, None
    # distance keywords
    dist_map = {
        "5k": 5000,
        "10k": 10000,
        "half": 21097.5,
        "half marathon": 21097.5,
        "hm": 21097.5,
        "marathon": 42195,
        "full": 42195,
    }
    found_d = None
    for k, d in dist_map.items():
        if k in txt:
            found_d = d
            break
    # time pattern
    m = _re_gc.search(r"(\d{1,2}:\d{2}:\d{2}|\d{1,2}:\d{2}|\b\d{1,3}\b)", txt)
    secs = _gc_parse_time_str(m.group(1)) if m else None
    if found_d and secs:
        return found_d, secs
    return None, None

def _gc_riegel(t1_sec: float, d1_m: float, d2_m: float = 42195.0) -> float:
    # Riegel prediction with exponent 1.06
    if not t1_sec or not d1_m:
        return 0.0
    return float(t1_sec) * ((d2_m / float(d1_m)) ** 1.06)

def _gc_mileage_baseline_pace(mpw: float, lr_mi: float) -> float:
    # Rough baseline pace (sec/mi) from mileage and long run
    # Buckets chosen to be conservative
    if mpw is None:
        mpw = 0
    pace = 11 * 60  # default 11:00/mi
    if mpw >= 65:
        pace = 7 * 60 + 30
    elif mpw >= 55:
        pace = 8 * 60 + 15
    elif mpw >= 45:
        pace = 8 * 60 + 45
    elif mpw >= 35:
        pace = 9 * 60 + 30
    elif mpw >= 25:
        pace = 10 * 60 + 30
    # Long-run adjustment
    if lr_mi and lr_mi >= 20:
        pace -= 15
    elif lr_mi and lr_mi < 16:
        pace += 15
    return max(5 * 60, pace)

def _gc_recommend(ans: dict) -> tuple[str, str]:
    mpw = float(ans.get("mpw") or 0)
    lr = float(ans.get("lr") or 0)
    d = ans.get("race_dist_m")
    t = ans.get("race_time_s")

    if d and t:
        base = _gc_riegel(t, d)
        # mileage factor
        if mpw < 30:
            base *= 1.05
        elif mpw < 45:
            base *= 1.02
        elif mpw > 60:
            base *= 0.99
        # longest run factor
        if lr >= 20:
            base *= 0.99
        elif lr and lr < 16:
            base *= 1.01
    else:
        # build from baseline pace
        pace = _gc_mileage_baseline_pace(mpw, lr)
        base = pace * 26.2188

    conservative = base * 1.03
    ambitious = base * 0.98
    return _gc_seconds_to_hms(conservative), _gc_seconds_to_hms(ambitious)

def _gc_reset():
    st.session_state.goal_coach_open = True
    st.session_state.goal_coach_step = 0
    st.session_state.goal_coach_answers = {}
    st.session_state.goal_coach_messages = [
        {
            "role": "assistant",
            "content": "I can help choose a realistic marathon goal. Do you have a recent race result (e.g., '5K 23:45' or 'Half 1:45:00')? Type 'skip' if not.",
        }
    ]
    st.session_state.goal_coach_cons = None
    st.session_state.goal_coach_amb = None

def _gc_handle(user_msg: str):
    msgs = st.session_state.goal_coach_messages
    msgs.append({"role": "user", "content": user_msg})
    step = st.session_state.goal_coach_step
    ans = st.session_state.goal_coach_answers

    if step == 0:
        d, t = _gc_parse_race(user_msg)
        if d and t:
            ans["race_dist_m"], ans["race_time_s"] = d, t
            msgs.append({"role": "assistant", "content": "Great! What's your average weekly mileage over the last 6–8 weeks?"})
        else:
            ans["race_dist_m"], ans["race_time_s"] = None, None
            msgs.append({"role": "assistant", "content": "No problem. What's your average weekly mileage over the last 6–8 weeks?"})
        st.session_state.goal_coach_step = 1
        return

    if step == 1:
        nums = _re_gc.findall(r"\d+(?:\.\d+)?", user_msg)
        ans["mpw"] = float(nums[0]) if nums else 0.0
        msgs.append({"role": "assistant", "content": "What's your longest recent long run (in miles)?"})
        st.session_state.goal_coach_step = 2
        return

    if step == 2:
        nums = _re_gc.findall(r"\d+(?:\.\d+)?", user_msg)
        ans["lr"] = float(nums[0]) if nums else 0.0
        cons, amb = _gc_recommend(ans)
        st.session_state.goal_coach_cons = cons
        st.session_state.goal_coach_amb = amb
        msgs.append({
            "role": "assistant",
            "content": f"Based on your answers, a conservative goal is {cons} and an ambitious goal is {amb}. Use a button below to apply one.",
        })
        st.session_state.goal_coach_step = 3
        return

if "plan_setup_visible" not in st.session_state:
    st.session_state.plan_setup_visible = False  # Collapsed by default

def training_plan_setup():
    """Handle training plan configuration."""
    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)

    if not st.session_state.plan_setup_visible:
        if st.button("Adjust Plan"):
            st.session_state.plan_setup_visible = True
            st.rerun()
        return settings

    with st.container():
        st.header("Training Plan Setup")

        col1, col2 = st.columns(2)

        with col1:
            start_date = st.date_input(
                "Start Date",
                value=datetime.strptime(settings.get("start_date", str(datetime.now().date())), "%Y-%m-%d").date(),
                help="The start date of your training plan"
            )

        with col2:
            # Input + Goal Coach button side-by-side
            sub1, sub2 = st.columns([3, 1])
            with sub1:
                goal_time = st.text_input(
                    "Goal Marathon Time (HH:MM:SS)",
                    value=settings.get("goal_time", "4:00:00"),
                    key="goal_time_input",
                    help="Your target marathon finish time"
                )
            with sub2:
                if st.button("Goal Coach", key="open_goal_coach_btn"):
                    _gc_reset()

        # Plan selection with friendly titles; defaults to run_plan.csv
        available_paths = list_available_plans()
        default_plan_path = settings.get("plan_file", "run_plan.csv")
        if default_plan_path not in available_paths and available_paths:
            default_plan_path = available_paths[0]
        labels = [plan_display_name(p) for p in available_paths] or ["18 Weeks, 55 Mile/Week Peak"]
        # index must match the order of labels/paths
        try:
            default_index = available_paths.index(default_plan_path) if available_paths else 0
        except ValueError:
            default_index = 0
        selected_label = st.selectbox(
            "Training Plan",
            options=labels,
            index=min(default_index, len(labels)-1),
            help="Select a plan. Place CSVs or ICS files in the repo root or plans/ folder."
        )
        # map label back to path
        label_to_path = {plan_display_name(p): p for p in available_paths}
        selected_plan_path = label_to_path.get(selected_label, default_plan_path)

        # Adjustment controls with persisted defaults
        c1, c2 = st.columns(2)
        with c1:
            week_adjust = st.selectbox(
                "Adjust plan length (weeks)",
                options=[-2, -1, 0, 1, 2],
                index=[-2, -1, 0, 1, 2].index(int(settings.get("week_adjust", 0) or 0)),
                help="-1: combine w1&2; -2: also combine w3&4; +1: duplicate w6; +2: duplicate w6 & w12",
            )
        with c2:
            weekly_miles_delta = st.slider(
                "Weekly mileage adjustment (mi/week)",
                min_value=-5, max_value=5, step=1, value=int(settings.get("weekly_miles_delta", 0) or 0),
                help="Adjust K longest runs per week by ±1 mile (K = |value|)",
            )

        # Goal Coach UI (chat-like) below the controls
        if st.session_state.goal_coach_open:
            st.markdown("#### Goal Time Coach")
            chat_supported = hasattr(st, "chat_message") and hasattr(st, "chat_input")
            # Render history
            for m in st.session_state.goal_coach_messages:
                if chat_supported:
                    st.chat_message(m["role"]).write(m["content"])  # type: ignore[attr-defined]
                else:
                    if m["role"] == "assistant":
                        st.info(m["content"])  # fallback styling
                    else:
                        st.write(f"You: {m['content']}")
            # Input
            user_msg = None
            if chat_supported:
                user_msg = st.chat_input("Your answer…")  # type: ignore[attr-defined]
            else:
                user_msg = st.text_input("Your answer…", key="goal_coach_fallback_input")
                if st.button("Send", key="goal_coach_send_btn"):
                    user_msg = st.session_state.get("goal_coach_fallback_input", "")
            if user_msg:
                _gc_handle(user_msg)
                st.rerun()
            # Recommendation buttons when ready
            if st.session_state.goal_coach_step >= 3:
                c1b, c2b, c3b = st.columns([1, 1, 2])
                cons = st.session_state.goal_coach_cons
                amb = st.session_state.goal_coach_amb
                if c1b.button(f"Use {cons}", key="use_cons_goal"):
                    st.session_state["goal_time_input"] = cons
                    st.session_state.goal_coach_open = False
                    st.success(f"Goal time set to {cons}")
                    st.rerun()
                if c2b.button(f"Use {amb}", key="use_amb_goal"):
                    st.session_state["goal_time_input"] = amb
                    st.session_state.goal_coach_open = False
                    st.success(f"Goal time set to {amb}")
                    st.rerun()
                c3b.button("Close Coach", key="close_goal_coach", on_click=lambda: st.session_state.update({"goal_coach_open": False}))

        if st.button("Save Training Plan", use_container_width=True):
            new_settings = {
                **settings,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "goal_time": st.session_state.get("goal_time_input", goal_time),
                "plan_file": selected_plan_path,
                "week_adjust": int(week_adjust),
                "weekly_miles_delta": int(weekly_miles_delta),
            }
            save_user_settings(user_hash, new_settings)
            st.session_state.plan_setup_visible = False
            st.success("Training plan saved!")
            st.rerun()

    return settings

def get_google_oauth_component():
    """Initialize Google OAuth component."""
    # If we don't have creds, return None so the caller can fall back
    if _missing_google_creds:
        return None
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
        settings = {}
        
        if settings_path.exists():
            with settings_path.open("r") as f:
                all_settings = json.load(f)
            settings = all_settings.get(user_hash, {})
        
        # Initialize default settings structure if missing keys
        if "goal_time" not in settings:
            settings["goal_time"] = "4:00:00"
            
        if "start_date" not in settings:
            settings["start_date"] = datetime.now().strftime("%Y-%m-%d")
            
        if "plan_file" not in settings:
            settings["plan_file"] = "run_plan.csv"
            
        # Make sure overrides structure exists
        if "overrides_by_plan" not in settings:
            settings["overrides_by_plan"] = {}
            
        # Ensure plan signature exists as a key in overrides_by_plan
        plan_sig = _plan_signature(settings)
        if plan_sig not in settings["overrides_by_plan"]:
            settings["overrides_by_plan"][plan_sig] = {}
            
        # Also initialize session state if needed
        if "plan_overrides_by_plan" not in st.session_state:
            st.session_state["plan_overrides_by_plan"] = {}
            
        if plan_sig not in st.session_state.get("plan_overrides_by_plan", {}):
            st.session_state["plan_overrides_by_plan"][plan_sig] = {}
            
        return settings
    except Exception as e:
        st.error(f"Error loading user settings: {e}")
        return {
            "goal_time": "4:00:00",
            "start_date": datetime.now().strftime("%Y-%m-%d"),
            "plan_file": "run_plan.csv",
            "overrides_by_plan": {}
        }


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


def check_persistent_login():
    """Check for persistent login data using URL parameters or session storage."""
    if st.session_state.auth_checked:
        return
    
    st.session_state.auth_checked = True
    
    if _is_debug():
        st.write("Debug: Checking for persistent login...")
    
    # First, check if we have restoration data in query parameters
    if st.query_params.get("restored") == "true":
        if _is_debug():
            st.write("Debug: Found 'restored=true' in query params")
        
        user_email = st.query_params.get("user_email")
        user_name = st.query_params.get("user_name") 
        user_picture = st.query_params.get("user_picture", "")
        user_token = st.query_params.get("user_token", "")
        
        if _is_debug():
            st.write(f"Debug: Extracted email: {user_email}, name: {user_name}")
        
        if user_email and user_name:
            # URL decode the values
            try:
                from urllib.parse import unquote
                user_email = unquote(user_email)
                user_name = unquote(user_name)
                user_picture = unquote(user_picture) if user_picture else ""
                user_token = unquote(user_token) if user_token else None
            except:
                pass
                
            st.session_state.current_user = {
                "email": user_email,
                "name": user_name,
                "picture": user_picture,
                "access_token": user_token,
            }
            if _is_debug():
                st.write("Debug: User restored from localStorage, clearing query params and rerunning")
            # Clean up the URL
            st.query_params.clear()
            st.rerun()
            return
    
    # Try to check localStorage and set up restoration parameters
    # Use a simpler approach: create a hidden iframe that does the localStorage check
    import streamlit.components.v1 as components
    
    if _is_debug():
        st.write("Debug: Setting up localStorage check")
    
    # Create a more reliable localStorage checker using an iframe
    iframe_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <script>
        window.onload = function() {
            try {
                const userData = localStorage.getItem('strava_dashboard_user');
                console.log('iframe: Checking localStorage:', userData ? 'found' : 'not found');
                
                if (userData && !window.parent.location.search.includes('restored=true')) {
                    console.log('iframe: Found user data, redirecting parent');
                    const user = JSON.parse(userData);
                    
                    // Build new URL with parameters
                    const params = new URLSearchParams();
                    params.set('restored', 'true');
                    params.set('user_email', encodeURIComponent(user.email));
                    params.set('user_name', encodeURIComponent(user.name));
                    params.set('user_picture', encodeURIComponent(user.picture || ''));
                    params.set('user_token', encodeURIComponent(user.access_token || ''));
                    
                    // Redirect parent window
                    window.parent.location.href = window.parent.location.pathname + '?' + params.toString();
                } else if (!userData) {
                    console.log('iframe: No stored user data found');
                }
            } catch (e) {
                console.error('iframe: Error:', e);
                localStorage.removeItem('strava_dashboard_user');
            }
        };
        </script>
    </head>
    <body></body>
    </html>
    """
    
    components.html(iframe_html, height=0)


def save_user_to_storage(user_data):
    """Save user data to browser localStorage."""
    import streamlit.components.v1 as components
    
    js_code = f"""
    <script>
    try {{
        localStorage.setItem('strava_dashboard_user', JSON.stringify({json.dumps(user_data)}));
        console.log('User data saved to localStorage');
    }} catch (e) {{
        console.error('Failed to save user data:', e);
    }}
    </script>
    """
    components.html(js_code, height=0)


def clear_user_from_storage():
    """Clear user data from browser localStorage."""
    import streamlit.components.v1 as components
    
    js_code = """
    <script>
    try {
        localStorage.removeItem('strava_dashboard_user');
        console.log('User data cleared from localStorage');
    } catch (e) {
        console.error('Failed to clear user data:', e);
    }
    </script>
    """
    components.html(js_code, height=0)


def google_login():
    """Handle Google OAuth login or a graceful dev fallback when creds are missing."""
    st.title("Marathon Training Dashboard")
    st.markdown("### Sign in to get started")

    fallback_needed = False
    fallback_error = None

    if _missing_google_creds:
        fallback_needed = True
        fallback_error = "Google sign-in is temporarily unavailable because credentials are not configured."
    else:
        oauth2 = get_google_oauth_component()
        redirect_uri = "https://marathonplanner.streamlit.app"
        if "google_redirect_uri" in st.secrets:
            redirect_uri = st.secrets.get("google_redirect_uri")
        if _is_debug():
            st.write(f"Using Google redirect URI: {redirect_uri}")
            st.write("Note: This exact URI must be registered in Google Cloud Console.")
            client_id_masked = google_client_id[:8] + "..." + google_client_id[-8:] if len(google_client_id or "") > 16 else google_client_id
            st.write(f"Using client ID: {client_id_masked}")
        try:
            # Render Google button with a safe fallback
            result = None
            try:
                if oauth2 is None:
                    raise RuntimeError("OAuth component not initialized")
                result = oauth2.authorize_button(
                    name="Continue with Google",
                    icon="https://developers.google.com/identity/images/g-logo.png",
                    redirect_uri=redirect_uri,
                    scope="openid email profile",
                    key="google_oauth",
                    use_container_width=True,
                )
            except StreamlitOauthError:
                # Reset any stale OAuth state and retry cleanly
                for k in list(st.session_state.keys()):
                    if "oauth" in k.lower() or "google" in k.lower():
                        st.session_state.pop(k, None)
                try:
                    st.query_params.clear()
                except Exception:
                    pass
                st.warning("Login session expired. Please click Continue with Google again.")
                st.rerun()
            except Exception as e:
                st.error("Google sign-in failed to initialize.")
                if _is_debug():
                    st.caption(str(e))
                with st.expander("Sign in without Google", expanded=True):
                    dev_email = st.text_input("Email", value="demo@local")
                    dev_name = st.text_input("Name", value="Demo User")
                    if st.button("Continue"):
                        user_data = {
                            "email": dev_email.strip() or "demo@local",
                            "name": dev_name.strip() or "Demo User",
                            "picture": "",
                            "access_token": None,
                        }
                        st.session_state.current_user = user_data
                        save_user_to_storage(user_data)
                        st.rerun()
            else:
                if result and "token" in result:
                    user_info = get_user_info(result["token"]["access_token"])
                    if user_info:
                        user_data = {
                            "email": user_info.get("email"),
                            "name": user_info.get("name", user_info.get("email")),
                            "picture": user_info.get("picture", ""),
                            "access_token": result["token"]["access_token"],
                        }
                        st.session_state.current_user = user_data
                        save_user_to_storage(user_data)
                        st.rerun()
        except Exception as e:
            fallback_needed = True
            fallback_error = f"Google sign-in failed to initialize: {e}"

    if fallback_needed:
        if fallback_error:
            st.error(fallback_error)
        with st.expander("Sign in without Google", expanded=True):
            dev_email = st.text_input("Email", value="demo@local")
            dev_name = st.text_input("Name", value="Demo User")
            if st.button("Continue"):
                user_data = {
                    "email": dev_email.strip() or "demo@local",
                    "name": dev_name.strip() or "Demo User",
                    "picture": "",
                    "access_token": None,
                }
                st.session_state.current_user = user_data
                save_user_to_storage(user_data)
                st.rerun()


def show_header():
    """Display the app header with user info."""
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("# <span class='gradient'>Marathon Training Dashboard</span>", unsafe_allow_html=True)
    with col2:
        if st.session_state.current_user:
            user = st.session_state.current_user
            av_col, info_col = st.columns([1, 2])
            with av_col:
                if user.get("picture"):
                    st.image(user["picture"], width=44)
            with info_col:
                st.markdown(f"**{user['name']}**")
                st.button("Sign Out", key="signout")
                if st.session_state.get("signout"):
                    st.session_state.current_user = None
                    clear_user_from_storage()
                    st.rerun()


def get_strava_auth_url():
    """Generate URL for Strava OAuth."""
    try:
        redirect_uri = (
            st.secrets.get("strava_redirect_uri")
            or os.getenv("STRAVA_REDIRECT_URI")
            or "https://marathonplanner.streamlit.app"
        )

        client_id, client_secret = get_strava_credentials()
        if not client_id or not client_secret:
            st.error("Missing Strava client_id/client_secret. Add them to secrets or env.")
            # We don't want to expose secret keys information to users
            return None
        
        scope = "read,activity:read_all"
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "approval_prompt": "auto",
            "scope": scope,
        }
        auth_url = "https://www.strava.com/oauth/authorize?" + urlencode(params)
        return auth_url
    except Exception as e:
        st.error(f"Error generating Strava auth URL: {str(e)}")
        import traceback
        st.caption(f"Exception traceback: {traceback.format_exc()}")
        return None


def refresh_strava_token_if_needed():
    """Refresh Strava token if expired or close to expiry. Returns True if token is usable."""
    try:
        user_hash = get_user_hash(st.session_state.current_user["email"])
        settings = load_user_settings(user_hash)
        if not settings.get("strava_refresh_token"):
            return False
        if not settings.get("strava_expires_at") or time.time() >= settings["strava_expires_at"] - 60:
            client_id, client_secret = get_strava_credentials()
            if not client_id or not client_secret:
                return False
            token_url = "https://www.strava.com/oauth/token"
            data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": settings["strava_refresh_token"],
            }
            r = requests.post(token_url, data=data, timeout=10)
            if r.status_code == 200:
                token_data = r.json()
                settings["strava_token"] = token_data.get("access_token", settings.get("strava_token"))
                settings["strava_refresh_token"] = token_data.get("refresh_token", settings.get("strava_refresh_token"))
                settings["strava_expires_at"] = token_data.get("expires_at", int(time.time()) + 3600)
                save_user_settings(user_hash, settings)
                return True
            return False
        return True
    except Exception:
        return False


def exchange_strava_code_for_token(code):
    """Exchange authorization code for access token."""
    client_id, client_secret = get_strava_credentials()
    if not client_id or not client_secret:
        st.error("Missing Strava client_id/client_secret for token exchange.")
        return False

    token_url = "https://www.strava.com/oauth/token"
    redirect_uri = (
        st.secrets.get("strava_redirect_uri")
        or os.getenv("STRAVA_REDIRECT_URI")
        or "https://marathonplanner.streamlit.app"
    )

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    try:
        response = requests.post(token_url, data=data, timeout=10)
        if response.status_code == 200:
            token_data = response.json()
            user_hash = get_user_hash(st.session_state.current_user["email"])
            settings = load_user_settings(user_hash)
            settings["strava_token"] = token_data["access_token"]
            settings["strava_refresh_token"] = token_data.get("refresh_token")
            settings["strava_expires_at"] = token_data.get("expires_at")
            settings["strava_scope"] = token_data.get("scope")
            athlete = token_data.get("athlete") or {}
            settings["strava_athlete_id"] = athlete.get("id")
            save_user_settings(user_hash, settings)
            return True
        else:
            st.error(f"Failed to get Strava token: {response.status_code} - {response.text}")
            st.info("This error occurred when connecting to Strava. Please try connecting again or contact support if the issue persists.")
            return False
    except Exception as e:
        st.error(f"Error exchanging Strava code: {e}")
        st.info("This error occurred when connecting to Strava. Please try connecting again or contact support if the issue persists.")
        return False


def strava_connect():
    """Handle Strava connection."""
    client_id, client_secret = get_strava_credentials()

    if not client_id or not client_secret:
        st.error("Strava credentials not found. Add [strava] client_id/client_secret to .streamlit/secrets.toml or set STRAVA_CLIENT_ID/STRAVA_CLIENT_SECRET env vars.")
        return False

    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)

    query_params = st.query_params
    if "code" in query_params:
        code = query_params["code"]
        if exchange_strava_code_for_token(code):
            st.success("Successfully connected to Strava.")
            st.query_params.clear()
            st.rerun()

    if settings.get("strava_token") and settings.get("strava_expires_at"):
        if time.time() < settings["strava_expires_at"]:
            return True

    auth_url = get_strava_auth_url()
    st.markdown(f"[Connect to Strava Account]({auth_url})", unsafe_allow_html=True)
    return False


def get_strava_activities(start_date=None, end_date=None, max_pages=4):
    """Fetch activities from Strava API with optional date range and pagination."""
    refresh_strava_token_if_needed()

    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)

    if not settings.get("strava_token"):
        st.warning("No Strava token found. Please connect your Strava account.")
        return []

    headers = {"Authorization": f"Bearer {settings['strava_token']}"}

    params_base = {"per_page": 200}
    try:
        if start_date is not None:
            start_ts = int(datetime.combine(start_date, datetime.min.time()).timestamp()) - 86400
            params_base["after"] = start_ts
        if end_date is not None:
            end_ts = int(datetime.combine(end_date, datetime.max.time()).timestamp()) + 86400
            params_base["before"] = end_ts
    except Exception:
        pass

    all_acts = []
    try:
        for page in range(1, max_pages + 1):
            params = {**params_base, "page": page}
            r = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers, params=params, timeout=15)
            if r.status_code != 200:
                st.error(f"Failed to fetch Strava activities: {r.status_code}")
                if r.status_code == 401:
                    st.error("Authentication failed. Please reconnect your Strava account.")
                break
            batch = r.json() or []
            all_acts.extend(batch)
            if len(batch) < params_base.get("per_page", 30):
                break
        return all_acts
    except Exception as e:
        st.error(f"Error fetching Strava activities: {e}")
        return []


def extract_primary_miles(text: str):
    """Extract the primary planned distance in miles from a plan text like 'MLR 12' or 'MP 13 w/ 8 @ MP'."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\b", s):
        start, end = m.span()
        val = m.group(1)
        if end < len(s) and s[end].lower() == 'k':
            continue
        prev = s[max(0, start-2):start].lower()
        if 'x' in prev:
            continue
        try:
            return float(val)
        except Exception:
            continue
    return None


def replace_primary_miles(text: str, new_miles: float) -> str:
    """Replace the first primary miles number in the text with new_miles (formatted nicely)."""
    if not isinstance(text, str):
        return text
    if new_miles is None:
        return text
    fmt = f"{int(round(new_miles))}" if abs(new_miles - round(new_miles)) < 0.05 else f"{new_miles:.1f}"

    def _repl(match: re.Match):
        number = match.group(1)
        span = match.span(1)
        end = span[1]
        if end < len(text) and text[end].lower() == 'k':
            return number
        prev = text[max(0, span[0]-2):span[0]].lower()
        if 'x' in prev:
            return number
        return fmt

    return re.sub(r"\b(\d+(?:\.\d+)?)\b", _repl, text, count=1)


# JD workout parser to extract total miles and segments (LT/Tempo, MP, strides)
def _parse_jd_workout(activity_text: str):
    try:
        s = str(activity_text or "").strip()
        s_lower = s.lower()
        # Total miles: try patterns like 'tempo 6', 'mp 8', 'lr 16', 'dress rehearsal 6', 'easy 5'
        m_total = re.search(r"\b(?:tempo|mp|marathon\s*pace|lr|long\s*run|dress\s*rehearsal|easy)\s*(\d+(?:\.\d+)?)", s_lower)
        total = float(m_total.group(1)) if m_total else None
        # Fallback: a number before a 'w/' segment
        if total is None:
            m_first = re.search(r"\b(\d+(?:\.\d+)?)\b[^\n]*?w/", s_lower)
            if m_first:
                total = float(m_first.group(1))
        breakdown = {"LT": 0.0, "MP": 0.0}
        segments = []  # tuples: (type, miles, reps or None, seg_len or None)
        # Parse 'w/ <reps>x<seg_mi> @ <label>' or 'w/ <seg_mi> @ <label>'
        for m in re.finditer(r"(?i)w/\s*(?:(\d+)\s*x\s*)?(\d+(?:\.\d+)?)\s*@\s*([A-Za-z ]+)", s):
            reps = int(m.group(1)) if m.group(1) else 1
            seg_mi = float(m.group(2))
            label = m.group(3).strip().lower()
            miles = seg_mi * reps
            if any(k in label for k in ["tempo", "15k", "hmp", "lactate"]):
                breakdown["LT"] += miles
                segments.append(("LT", miles, reps if m.group(1) else None, seg_mi if m.group(1) else None))
            elif "mp" in label or "marathon" in label:
                breakdown["MP"] += miles
                segments.append(("MP", miles, reps if m.group(1) else None, seg_mi if m.group(1) else None))
            else:
                segments.append(("Other", miles, reps if m.group(1) else None, seg_mi if m.group(1) else None))
        # MP continuous pattern
        m_cont = re.search(r"(?i)\bmp\s*(\d+(?:\.\d+)?)\s*(?:mi|mile|miles)?\s*continuous", s)
        if m_cont:
            mi = float(m_cont.group(1))
            breakdown["MP"] += mi
            total = total or mi
        # Strides pattern: 'Easy X w/ N x 100m strides'
        strides = None
        m_strides = re.search(r"(?i)\b(\d+(?:\.\d+)?)\b[^\n]*?w/\s*(\d+)\s*x\s*(\d+)\s*(?:m|meter|meters)\s*strides", s)
        if m_strides:
            total = total or float(m_strides.group(1))
            strides = (int(m_strides.group(2)), int(m_strides.group(3)))
        easy = None
        if total is not None:
            easy = max(0.0, total - (breakdown["LT"] + breakdown["MP"]))
        return {
            "total": total,
            "breakdown": breakdown,
            "strides": strides,
            "segments": segments,
            "raw": s,
        }
    except Exception:
        return None

def get_activity_short_description(activity_description):
    """Generate short, one-sentence descriptions for activity hover tooltips based on Pfitzinger principles."""
    desc_lower = activity_description.lower()
    orig = activity_description.strip()

    # Prefer explicit breakdowns for JD-style entries when possible
    try:
        # Pattern: Total X with Y @ Tempo/MP/etc.
        m = re.search(r'(?i)\b(?P<total>\d+(?:\.\d+)?)\b[^\n]*?w/\s*(?P<seg>\d+(?:\.\d+)?)\s*@\s*(?P<label>tempo|mp|marathon\s*pace|15k\s*to\s*hmp|hmp)', orig)
        if m:
            total = float(m.group('total'))
            seg = float(m.group('seg'))
            remain = max(0.0, total - seg)
            label = m.group('label').lower()
            if label in ('tempo', '15k to hmp', 'hmp'):
                pace_name = 'Lactate Threshold (Tempo)'
            else:
                pace_name = 'Marathon Pace'
            total_str = f"{int(total)}" if abs(total - round(total)) < 0.05 else f"{total:.1f}"
            seg_str = f"{int(seg)}" if abs(seg - round(seg)) < 0.05 else f"{seg:.1f}"
            rem_str = f"{int(remain)}" if abs(remain - round(remain)) < 0.05 else f"{remain:.1f}"
            return f"Total {total_str} mi: {seg_str} mi at {pace_name}, {rem_str} mi easy."
        # Pattern: MP X continuous
        m2 = re.search(r'(?i)\bmp\s*(?P<total>\d+(?:\.\d+)?)\s*(?:mi|mile|miles)?\s*continuous', orig)
        if m2:
            total = float(m2.group('total'))
            total_str = f"{int(total)}" if abs(total - round(total)) < 0.05 else f"{total:.1f}"
            return f"Total {total_str} mi at Marathon Pace (continuous)."
        # Pattern: Easy X w/ N x 100 strides
        m3 = re.search(r'(?i)\beasy\s*(?P<total>\d+(?:\.\d+)?)\b[^\n]*?w/\s*(?P<reps>\d+)\s*x\s*(?P<dist>\d+)\s*(?:m|meter|meters)', orig)
        if m3:
            total = float(m3.group('total')); reps = int(m3.group('reps')); dist = int(m3.group('dist'))
            total_str = f"{int(total)}" if abs(total - round(total)) < 0.05 else f"{total:.1f}"
            return f"Easy {total_str} mi with {reps} × {dist}m strides."
    except Exception:
        pass
    
    if 'rest' in desc_lower:
        return "Rest day for recovery - no running, but light cross-training is fine."
    
    elif 'easy' in desc_lower:
        miles = re.search(r'(\d+(?:\.\d+)?)', orig)
        miles_str = f"{miles.group(1)} miles " if miles else ""
        return f"Easy {miles_str}run at comfortable, conversational pace to build aerobic base."
    
    elif 'general aerobic' in desc_lower or 'aerobic' in desc_lower:
        miles = re.search(r'(\d+(?:\.\d+)?)', orig)
        miles_str = f"{miles.group(1)} miles " if miles else ""
        return f"General aerobic {miles_str}run at comfortable pace to build foundational fitness."
    
    elif 'recovery' in desc_lower or 'rec' in desc_lower:
        miles = re.search(r'(\d+(?:\.\d+)?)', orig)
        miles_str = f"{miles.group(1)} miles " if miles else ""
        return f"Recovery {miles_str}run at very easy pace to promote active recovery."
    
    elif 'tempo' in desc_lower or 'lactate threshold' in desc_lower or 'lt' in desc_lower:
        # Look for "LT X w/ Y @ pace" format first
        lt_segment_match = re.search(r'lt\s+(\d+(?:\.\d+)?)\s+w/\s*(\d+(?:\.\d+)?)\s*@?\s*(?:15k|hmp|half|marathon|tempo)', desc_lower)
        if lt_segment_match:
            total_miles = float(lt_segment_match.group(1))
            tempo_miles = float(lt_segment_match.group(2))
            return f"{total_miles}-mile run with {tempo_miles} miles at lactate threshold pace (continuous block)."
        
        # Look for tempo segments
        tempo_match = re.search(r'(?:with|w/)\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*(?:at\s*)?tempo', desc_lower)
        if tempo_match:
            tempo_miles = float(tempo_match.group(1))
            total_miles = re.search(r'^(\d+(?:\.\d+)?)', orig)
            total_str = f"{total_miles.group(1)}-mile run with " if total_miles else ""
            return f"{total_str}{tempo_miles} miles at tempo pace (continuous block in middle)."
        
        time_match = re.search(r'(\d+)', orig)
        time_str = f"{time_match.group(1)}-minute " if time_match else ""
        return f"{time_str}tempo run at sustained, challenging pace to improve lactate clearance."
    
    elif 'vo2' in desc_lower or 'v8' in desc_lower or '800m interval' in desc_lower or '800' in desc_lower:
        # Look for specific interval patterns
        interval_match = re.search(r'(\d+)\s*×\s*(?:(\d+(?:\.\d+)?)\s*(?:mi|mile|miles|m|meter|meters)?|(\d+)\s*(?:min|minute|minutes))', desc_lower)
        if interval_match:
            reps = interval_match.group(1)
            distance = interval_match.group(2)
            time_mins = interval_match.group(3)
            
            if distance and 'm' in desc_lower and not 'mi' in desc_lower:  # meters
                return f"{reps} × {distance}m intervals at 5K pace (equal time recovery)."
            elif distance:  # miles
                return f"{reps} × {distance}-mile intervals at 5K-10K pace (2-3 min recovery)."
            elif time_mins:  # time-based
                return f"{reps} × {time_mins}-minute intervals at 5K pace (half-time recovery)."
        
        num_match = re.search(r'(\d+)', orig)
        num_str = f"{num_match.group(1)} " if num_match else ""
        return f"{num_str}× intervals at 5K-10K pace to boost maximal oxygen uptake."
    
    elif '400m interval' in desc_lower or '400' in desc_lower:
        # Look for 400m patterns
        interval_400_match = re.search(r'(\d+)\s*×\s*400', desc_lower)
        if interval_400_match:
            reps = interval_400_match.group(1)
            return f"{reps} × 400m speed intervals at mile pace (full recovery between)."
        
        num_match = re.search(r'(\d+)', orig)
        num_str = f"{num_match.group(1)} " if num_match else ""
        return f"{num_str}× 400m speed intervals with full recovery between repeats."
    
    elif 'hill repeat' in desc_lower or 'hill' in desc_lower:
        # Look for hill repeat patterns
        hill_match = re.search(r'(\d+)\s*(?:×\s*)?hill', desc_lower)
        if hill_match:
            reps = hill_match.group(1)
            return f"{reps} hill repeats at 5K effort (walk/jog down for recovery)."
        
        num_match = re.search(r'(\d+)', orig)
        num_str = f"{num_match.group(1)} " if num_match else ""
        return f"{num_str}hill repeats to build leg strength and power."
    
    elif 'marathon pace' in desc_lower or 'mp' in desc_lower:
        # Look for "MP/LT X w/ Y @ pace" format first (often includes marathon pace segments)
        mp_lt_segment_match = re.search(r'(?:mp|lt)\s+(\d+(?:\.\d+)?)\s+w/\s*(\d+(?:\.\d+)?)\s*@?\s*(?:mp|marathon\s*pace|15k\s*to\s*hmp|hmp)', desc_lower)
        if mp_lt_segment_match:
            total_miles = float(mp_lt_segment_match.group(1))
            segment_miles = float(mp_lt_segment_match.group(2))
            return f"{total_miles}-mile run with {segment_miles} miles at marathon pace (aim for middle of run)."
        
        # Check for specific segment patterns
        segment_match = re.search(r'(?:with|w/)\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*(?:at\s*)?(?:marathon\s*pace|mp)', desc_lower)
        if segment_match:
            segment_miles = float(segment_match.group(1))
            total_miles = re.search(r'^(\d+(?:\.\d+)?)', orig)
            total_str = f"{total_miles.group(1)}-mile run with " if total_miles else ""
            return f"{total_str}{segment_miles} miles at marathon pace (aim for middle of run)."
        else:
            miles = re.search(r'(\d+(?:\.\d+)?)', orig)
            miles_str = f"{miles.group(1)} miles " if miles else ""
            return f"{miles_str}at goal marathon pace to develop race rhythm."
    
    elif 'long run' in desc_lower or 'lr' in desc_lower:
        # Check for marathon pace segments
        if 'marathon pace' in desc_lower or 'mp' in desc_lower:
            segment_match = re.search(r'(?:with|w/)\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*(?:at\s*)?(?:marathon\s*pace|mp)', desc_lower)
            if segment_match:
                segment_miles = float(segment_match.group(1))
                total_miles = re.search(r'^(\d+(?:\.\d+)?)', orig)
                total_str = f"{total_miles.group(1)}-mile " if total_miles else ""
                return f"Long {total_str}run with {segment_miles} miles at marathon pace (execute when fatigued)."
        
        miles = re.search(r'(\d+(?:\.\d+)?)', orig)
        miles_str = f"{miles.group(1)} miles " if miles else ""
        return f"Long {miles_str}run to build endurance, may include marathon pace segments."
    
    elif 'medium-long' in desc_lower or 'mlr' in desc_lower:
        # Check for marathon pace segments
        if 'marathon pace' in desc_lower or 'mp' in desc_lower:
            segment_match = re.search(r'(?:with|w/)\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*(?:at\s*)?(?:marathon\s*pace|mp)', desc_lower)
            if segment_match:
                segment_miles = float(segment_match.group(1))
                total_miles = re.search(r'^(\d+(?:\.\d+)?)', orig)
                total_str = f"{total_miles.group(1)}-mile " if total_miles else ""
                return f"Medium-long {total_str}run with {segment_miles} miles at marathon pace (middle portion)."
        
        miles = re.search(r'(\d+(?:\.\d+)?)', orig)
        miles_str = f"{miles.group(1)} miles " if miles else ""
        return f"Medium-long {miles_str}run to build endurance while managing fatigue."
    
    elif 'progression' in desc_lower:
        miles = re.search(r'(\d+(?:\.\d+)?)', orig)
        miles_str = f"{miles.group(1)} miles " if miles else ""
        return f"Progression {miles_str}run starting slow and gradually increasing pace."
    
    elif 'half marathon' in desc_lower:
        return "Half marathon race to assess fitness and practice race strategies."
    
    elif 'marathon' in desc_lower and 'pace' not in desc_lower:
        return "Marathon race day - execute your race plan and trust your training!"
    
    else:
        # Try to extract basic info for generic activities
        miles = re.search(r'(\d+(?:\.\d+)?)', orig)
        if miles:
            miles_val = float(miles.group(1))
            if miles_val <= 4:
                return f"{miles.group(1)} miles at easy, conversational pace."
            elif miles_val <= 8:
                return f"{miles.group(1)} miles at comfortable aerobic effort."
            else:
                return f"{miles.group(1)} miles focusing on endurance and aerobic development."
        return f"Training run as prescribed in your plan."


def get_activity_tooltip(activity_description):
    """Generate detailed tooltip explanations based on Pfitzinger training principles."""
    desc_lower = activity_description.lower()
    orig = activity_description.strip()
    
    # JD-style explicit, actionable instructions when segments detected
    try:
        parsed = _parse_jd_workout(orig)
        if parsed and parsed.get("total") and (parsed["breakdown"].get("LT", 0) > 0 or parsed["breakdown"].get("MP", 0) > 0):
            total = parsed["total"] or 0.0
            lt = parsed["breakdown"].get("LT", 0.0)
            mp = parsed["breakdown"].get("MP", 0.0)
            easy = max(0.0, total - lt - mp)
            def _fmt(x):
                return f"{int(x)}" if abs(x - round(x)) < 0.05 else f"{x:.1f}"
            lines = [f"Do a {_fmt(total)}-mile run:"]
            # Segment details (prefer rep formats when available)
            lt_seg = next((seg for seg in parsed["segments"] if seg[0] == "LT" and seg[2]), None)
            mp_seg = next((seg for seg in parsed["segments"] if seg[0] == "MP" and seg[2]), None)
            if lt > 0:
                if lt_seg:
                    lines.append(f"- LT/Tempo: {lt_seg[2]} × {_fmt(lt_seg[3])} mi (total {_fmt(lt)} mi) at LT (15K–HMP effort)")
                else:
                    lines.append(f"- LT/Tempo: {_fmt(lt)} mi continuous at 15K–HMP effort")
            if mp > 0:
                if mp_seg:
                    lines.append(f"- Marathon Pace: {mp_seg[2]} × {_fmt(mp_seg[3])} mi (total {_fmt(mp)} mi) at goal MP")
                else:
                    lines.append(f"- Marathon Pace: {_fmt(mp)} mi continuous at goal MP")
            if easy > 0:
                lines.append(f"- Easy: {_fmt(easy)} mi easy pace to complete the total")
            # Execution guidance
            lines.append("Execution: Warm up 15–20 min easy. Place LT/MP work in the middle. Cool down easy to reach the total distance. Keep LT as comfortably-hard and MP as steady race pace.")
            return "\n".join(lines)
        # Strides explicit
        if parsed and parsed.get("strides") and parsed.get("total"):
            reps, distm = parsed["strides"]
            t = parsed["total"]
            def _fmt(x):
                return f"{int(x)}" if abs(x - round(x)) < 0.05 else f"{x:.1f}"
            return f"Do an easy {_fmt(t)}-mile run with {reps} × {distm}m strides (95% effort, full recovery) near the end."
    except Exception:
        pass

    if 'rest' in desc_lower:
        return "Rest day. No running, but light cross-training (swimming, yoga, walking) is fine. Rest is crucial for muscle recovery and injury prevention."
    
    elif 'easy' in desc_lower:
        return "Easy pace: Comfortable, conversational pace to build aerobic base fitness. Should feel relaxed and sustainable."
    
    elif 'general aerobic' in desc_lower or 'aerobic' in desc_lower:
        return "General Aerobic: Foundational runs at comfortable, conversational pace to build aerobic base fitness and endurance."
    
    elif 'recovery' in desc_lower or 'rec' in desc_lower:
        return "Recovery Run: Short, low-intensity run after harder workouts to promote active recovery and blood flow, helping the body adapt to training stress."
    
    elif 'tempo' in desc_lower or 'lactate threshold' in desc_lower or 'lt' in desc_lower:
        base_text = "Lactate Threshold (Tempo): Sustained, challenging pace (15K-half marathon pace) to improve your body's ability to clear lactic acid."
        
        # Look for "LT X w/ Y @ pace" format or "with Y miles tempo" format
        lt_segment_match = re.search(r'lt\s+(\d+(?:\.\d+)?)\s+w/\s*(\d+(?:\.\d+)?)\s*@?\s*(?:15k|hmp|half|marathon|tempo)', desc_lower)
        tempo_miles_match = re.search(r'(?:with|w/)\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*(?:at\s*)?tempo', desc_lower)
        
        if lt_segment_match:
            total_miles = float(lt_segment_match.group(1))
            tempo_miles = float(lt_segment_match.group(2))
            if tempo_miles >= 4:
                return f"{base_text}\n\nExecution: This is a {total_miles}-mile run with {tempo_miles} miles at lactate threshold pace. Run the first {total_miles - tempo_miles} miles at easy pace, then execute all {tempo_miles} miles at sustained tempo effort (15K-half marathon pace) as one continuous block, followed by easy running to finish. If unable to complete as one block, split into two segments with 2-3 minutes easy running between them."
            else:
                return f"{base_text}\n\nExecution: This is a {total_miles}-mile run with {tempo_miles} miles at lactate threshold pace. After warming up, run the {tempo_miles}-mile tempo segment continuously at sustained effort, then finish with easy running. If needed, you can split this into two shorter segments with brief recovery between."
        elif tempo_miles_match:
            tempo_miles = float(tempo_miles_match.group(1))
            if tempo_miles >= 5:
                return f"{base_text}\n\nExecution: Run {tempo_miles} miles at tempo pace as one continuous block. Start with 2-3 miles easy warm-up, then sustain tempo effort for all {tempo_miles} miles, followed by 1-2 miles easy cool-down. Focus on controlled breathing and steady rhythm. If unable to maintain pace for the full distance, split into two segments with 2-3 minutes easy recovery between them."
            elif tempo_miles >= 3:
                return f"{base_text}\n\nExecution: Run {tempo_miles} miles at tempo pace continuously in the middle of your run. Warm up for 15-20 minutes, then maintain steady tempo effort. If struggling to sustain pace, you can break into 2 segments with 2-3 minutes recovery."
            else:
                return f"{base_text}\n\nExecution: Run {tempo_miles} miles at tempo pace after proper warm-up. This shorter tempo should feel 'comfortably hard' - challenging but sustainable throughout."
        
        # Look for time-based tempo like "20 minute tempo" or "2 x 15 minutes"
        tempo_time_match = re.search(r'(?:(\d+)\s*×\s*)?(\d+)\s*(?:-?\s*)?minute.*tempo', desc_lower)
        if tempo_time_match:
            if tempo_time_match.group(1):  # Multiple segments like "2 × 15 minutes"
                reps = tempo_time_match.group(1)
                minutes = tempo_time_match.group(2)
                return f"{base_text}\n\nExecution: Run {reps} separate {minutes}-minute tempo segments with 3-5 minutes easy recovery between each. Warm up for 15-20 minutes, then maintain steady tempo effort during work intervals."
            else:  # Single segment like "20 minutes tempo"
                minutes = tempo_time_match.group(2)
                return f"{base_text}\n\nExecution: Run {minutes} continuous minutes at tempo pace. Start with 15-20 minute warm-up, sustain tempo effort throughout, then cool down with easy running."
        
        return base_text
    
    elif 'vo2' in desc_lower or 'v8' in desc_lower or '800m interval' in desc_lower or '800' in desc_lower:
        base_text = "VO₂ Max: Shorter, faster intervals at 5K-10K pace to increase your body's maximal oxygen uptake capacity."
        
        # Look for interval patterns like "6 × 800m" or "8 × 3 minutes"
        interval_count_match = re.search(r'(\d+)\s*×\s*(?:(\d+(?:\.\d+)?)\s*(?:mi|mile|miles|m|meter|meters)?|(\d+)\s*(?:min|minute|minutes))', desc_lower)
        if interval_count_match:
            reps = int(interval_count_match.group(1))
            distance = interval_count_match.group(2)
            time_mins = interval_count_match.group(3)
            
            if distance:  # Distance-based intervals
                if 'm' in desc_lower and not 'mi' in desc_lower:  # meters
                    return f"{base_text}\n\nExecution: Run {reps} × {distance}m intervals at 5K pace with equal time recovery (jog/walk). Complete 15-20 minute warm-up including strides. Focus on smooth, controlled speed with full recovery between repeats."
                else:  # miles
                    return f"{base_text}\n\nExecution: Run {reps} × {distance}-mile intervals at 5K-10K pace with 2-3 minutes recovery between each. Warm up thoroughly, then maintain steady hard effort during work intervals."
            elif time_mins:  # Time-based intervals
                recovery_time = max(2, int(time_mins) // 2)  # Recovery roughly half the work time
                return f"{base_text}\n\nExecution: Run {reps} × {time_mins}-minute intervals at 5K pace with {recovery_time}-minute easy recovery between each. Focus on maintaining consistent pace and effort across all intervals."
        
        # Look for Yasso 800s specifically
        if 'yasso' in desc_lower or ('800' in desc_lower and any(x in desc_lower for x in ['goal', 'marathon', 'time'])):
            return f"{base_text}\n\nExecution: Yasso 800s - run each 800m in minutes:seconds matching your marathon goal hours:minutes (e.g., 4:00 marathon = 4:00 per 800m). Take equal recovery time between intervals. Start conservatively and build consistency."
        
        return base_text
    
    elif '400m interval' in desc_lower or '400' in desc_lower:
        base_text = "Speed Intervals: Short, fast repeats at mile pace or faster. Focus on speed and running form with full recovery between repeats."
        
        # Look for 400m interval patterns
        interval_400_match = re.search(r'(\d+)\s*×\s*400', desc_lower)
        if interval_400_match:
            reps = int(interval_400_match.group(1))
            recovery_time = "90 seconds to 2 minutes" if reps >= 8 else "2-3 minutes"
            return f"{base_text}\n\nExecution: Run {reps} × 400m repeats at mile pace or slightly faster with {recovery_time} complete recovery (walk/easy jog). Warm up thoroughly with dynamic drills. Focus on relaxed speed and good form - these should feel fast but controlled."
        
        # Look for other short speed intervals
        short_interval_match = re.search(r'(\d+)\s*×\s*(\d+(?:\.\d+)?)\s*(?:mi|mile|miles)', desc_lower)
        if short_interval_match and float(short_interval_match.group(2)) <= 0.5:  # Quarter-mile or shorter
            reps = int(short_interval_match.group(1))
            distance = short_interval_match.group(2)
            return f"{base_text}\n\nExecution: Run {reps} × {distance}-mile repeats at mile pace with full recovery between each. These are neuromuscular speed sessions - focus on turnover and form rather than grinding out pace."
        
        return base_text
    
    elif 'hill repeat' in desc_lower or 'hill' in desc_lower:
        base_text = "Hill Repeats: Run hard uphill efforts with easy recovery. Builds leg strength and power with less impact than track work."
        
        # Look for hill repeat patterns
        hill_count_match = re.search(r'(\d+)\s*(?:×\s*)?hill', desc_lower)
        if hill_count_match:
            reps = int(hill_count_match.group(1))
            return f"{base_text}\n\nExecution: Run {reps} hill repeats on a moderate grade (4-6%). Run uphill at 5K effort for 60-90 seconds, then walk/jog slowly back down for full recovery. Focus on strong arm drive and maintaining form. The effort should feel hard but sustainable across all repeats."
        
        # Look for time or distance-based hill work
        hill_time_match = re.search(r'(\d+)\s*(?:×\s*)?(\d+)\s*(?:second|sec|minute|min)', desc_lower)
        if hill_time_match:
            reps = int(hill_time_match.group(1))
            duration = hill_time_match.group(2)
            unit = "seconds" if "sec" in desc_lower else "minutes"
            return f"{base_text}\n\nExecution: Run {reps} × {duration}-{unit} hill repeats at 5K-10K effort. Use the downhill for complete recovery between repeats. Focus on driving with your arms and maintaining quick turnover uphill."
        
        # Generic hill workout advice
        if 'hill' in desc_lower:
            return f"{base_text}\n\nExecution: Find a steady 4-6% grade hill. Run uphill at a strong, controlled effort (5K pace feel), focusing on form and power. Walk or jog easily downhill for full recovery between efforts."
        
        return base_text
    
    elif 'marathon pace' in desc_lower or 'mp' in desc_lower:
        # Check for specific marathon pace segments and provide execution guidance
        base_text = "Marathon Pace: Training at your goal marathon race pace to develop race rhythm and metabolic efficiency."
        
        # Look for "MP X w/ Y @ MP" or "LT X w/ Y @ 15K to HMP" patterns (which are often marathon pace segments)
        mp_lt_segment_match = re.search(r'(?:mp|lt)\s+(\d+(?:\.\d+)?)\s+w/\s*(\d+(?:\.\d+)?)\s*@?\s*(?:mp|marathon\s*pace|15k\s*to\s*hmp|hmp)', desc_lower)
        
        # Look for segment patterns like "with X miles at Marathon Pace"
        segment_match = re.search(r'(?:with|w/)\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*(?:at\s*)?(?:marathon\s*pace|mp)', desc_lower)
        
        if mp_lt_segment_match:
            total_miles = float(mp_lt_segment_match.group(1))
            segment_miles = float(mp_lt_segment_match.group(2))
            if segment_miles >= 6:
                return f"{base_text}\n\nExecution: This is a {total_miles}-mile run with {segment_miles} miles at marathon pace. Run the first {total_miles - segment_miles} miles at easy pace, then execute all {segment_miles} miles at goal marathon pace as one continuous block, followed by easy cool-down miles. If unable to complete as one block, split into two segments with 1-2 miles easy running between them."
            elif segment_miles >= 3:
                return f"{base_text}\n\nExecution: This is a {total_miles}-mile run with {segment_miles} miles at marathon pace. After warming up, run the {segment_miles}-mile marathon pace segment continuously, or split into two segments with 1 mile of general aerobic pace between them if needed."
            else:
                return f"{base_text}\n\nExecution: This is a {total_miles}-mile run with {segment_miles} miles at marathon pace. Run this segment continuously in the middle of your run after a proper warm-up."
        elif segment_match:
            segment_miles = float(segment_match.group(1))
            if segment_miles >= 6:
                return f"{base_text}\n\nExecution: Run the {segment_miles} marathon pace miles as one continuous block in the middle of your run. Start with 2-3 miles of easy warm-up, then execute all {segment_miles} miles at goal pace, followed by easy cool-down miles. If unable to complete as one block, split into two segments with 1-2 miles easy running between them."
            elif segment_miles >= 3:
                return f"{base_text}\n\nExecution: Run the {segment_miles} marathon pace miles in the middle of your run after a proper warm-up. If this feels too challenging, you can split into two segments (e.g., {segment_miles//2}mi + {segment_miles-segment_miles//2}mi) with 1 mile of general aerobic pace between them."
            else:
                return f"{base_text}\n\nExecution: Run the {segment_miles} marathon pace miles in the middle of your run. This shorter segment should be done continuously after warming up for 2-3 miles."
        
        # Look for multiple segment patterns like "3 × 2 mile Marathon Pace segments"
        multi_segment_match = re.search(r'(\d+)\s*×\s*(\d+(?:\.\d+)?)\s*mile.*marathon\s*pace\s*segment', desc_lower)
        if multi_segment_match:
            reps = int(multi_segment_match.group(1))
            distance = float(multi_segment_match.group(2))
            return f"{base_text}\n\nExecution: Run {reps} separate {distance}-mile segments at marathon pace with 0.5-1 mile of easy recovery between each segment. Start with a 2-3 mile warm-up, then alternate between marathon pace segments and recovery intervals."
        
        # Look for time-based segments
        time_match = re.search(r'(\d+)\s*(?:×\s*)?(\d+)\s*(?:-?\s*)?minute.*marathon\s*pace', desc_lower)
        if time_match:
            if time_match.group(1):  # Multiple segments like "2 × 20-minute"
                reps = time_match.group(1)
                minutes = time_match.group(2)
                return f"{base_text}\n\nExecution: Run {reps} separate {minutes}-minute segments at marathon pace with 2-3 minutes of easy jogging recovery between segments. Warm up for 10-15 minutes before starting the first marathon pace segment."
            else:  # Single segment like "20 minutes"
                minutes = time_match.group(2)
                return f"{base_text}\n\nExecution: Run {minutes} continuous minutes at marathon pace in the middle of your run. Start with a 10-15 minute warm-up, execute the marathon pace segment, then cool down with easy running."
        
        return base_text
    
    elif 'long run' in desc_lower or 'lr' in desc_lower:
        base_text = "Long Run: Cornerstone workout to build endurance. May include marathon pace segments to train for race-day efforts."
        
        # Check for marathon pace segments in long runs
        if 'marathon pace' in desc_lower or 'mp' in desc_lower:
            segment_match = re.search(r'(?:with|w/)\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*(?:at\s*)?(?:marathon\s*pace|mp)', desc_lower)
            if segment_match:
                segment_miles = float(segment_match.group(1))
                return f"{base_text}\n\nExecution: This long run includes {segment_miles} miles at marathon pace. Run the first 30-40% of your total distance at easy pace, then execute the {segment_miles} marathon pace miles continuously, followed by easy running to finish. This simulates race-day fatigue and teaches you to hit goal pace when tired."
        
        return base_text
    
    elif 'medium-long' in desc_lower or 'mlr' in desc_lower:
        base_text = "Medium-Long Run: Extended aerobic run shorter than your long run, building endurance while managing fatigue."
        
        # Check for marathon pace segments in medium-long runs
        if 'marathon pace' in desc_lower or 'mp' in desc_lower:
            segment_match = re.search(r'(?:with|w/)\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*(?:at\s*)?(?:marathon\s*pace|mp)', desc_lower)
            if segment_match:
                segment_miles = float(segment_match.group(1))
                return f"{base_text}\n\nExecution: Include {segment_miles} miles at marathon pace in the middle portion of this run. Start with 25-30% easy running, then execute the marathon pace segment, followed by easy running to finish. This builds race-specific endurance."
        
        return base_text
    
    elif 'progression' in desc_lower:
        base_text = "Progression Run: Start slow and gradually increase pace, particularly in the second half. Challenging but sustainable workout."
        
        # Look for progression run specifics
        miles_match = re.search(r'(\d+(?:\.\d+)?)', orig)
        if miles_match:
            total_miles = float(miles_match.group(1))
            if total_miles >= 8:
                return f"{base_text}\n\nExecution: Start at easy pace for the first {total_miles//3:.0f} miles, progress to general aerobic pace for the middle third, then finish the final {total_miles//3:.0f} miles at tempo pace. The progression should feel natural and controlled. If the tempo finish feels too aggressive, you can ease back to half-marathon pace instead."
            elif total_miles >= 5:
                return f"{base_text}\n\nExecution: Start at easy pace for the first half, then progress to tempo pace for the second half. Focus on negative splitting - each mile should be slightly faster than the previous. If tempo pace feels unsustainable, target half-marathon pace instead."
            else:
                return f"{base_text}\n\nExecution: Start at easy pace, then gradually increase to tempo pace over the final 1-2 miles. The acceleration should feel smooth and controlled."
        
        return base_text
    
    elif 'half marathon' in desc_lower:
        return "Half Marathon: Goal race to assess fitness and practice race-day strategies. Use as training run, not all-out effort."
    
    elif 'marathon' in desc_lower and 'pace' not in desc_lower:
        return "Marathon Race: Your goal race! Trust your training and execute your planned pace strategy."
    
    else:
        # Check for other structured workout patterns
        
        # Fartlek patterns
        if 'fartlek' in desc_lower:
            return f"Fartlek: Unstructured speed play with varying paces and efforts. Mix periods of faster running (30 seconds to 3 minutes) with easy recovery. Keep it fun and spontaneous - use landmarks, terrain, or how you feel to guide the surges."
        
        # Strides or pickups
        if 'stride' in desc_lower or 'pickup' in desc_lower:
            stride_match = re.search(r'(\d+)\s*(?:×\s*)?stride', desc_lower)
            if stride_match:
                reps = stride_match.group(1)
                return f"Strides: {reps} × 100m accelerations to 95% effort, focusing on form and turnover. Use these after easy runs or as part of pre-race preparation. Walk back for full recovery between each."
            return f"Strides: Short, controlled accelerations to near-maximum speed focusing on running form and leg turnover."
        
        # Mixed pace workouts
        if 'aerobic' in desc_lower and 'tempo' in desc_lower:
            return f"Mixed Aerobic/Tempo: Combination workout alternating between comfortable aerobic pace and tempo efforts. Structure the segments with proper warm-up and recovery between different pace zones."
        
        return f"Training Run: {orig}. Follow your plan and listen to your body."


def pace_to_seconds(pace_str):
    """Convert pace string (MM:SS) to seconds per mile."""
    if not isinstance(pace_str, str) or pace_str in ["—", "", "Hard uphill effort", "Yasso 800s pace", "Mile pace or faster", "See plan"]:
        return None
    try:
        if ":" in pace_str:
            parts = pace_str.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        return None
    except:
        return None


def is_pace_in_range(actual_pace, suggested_pace_range):
    """Check if actual pace is within the suggested pace range."""
    actual_seconds = pace_to_seconds(actual_pace)
    
    if actual_seconds is None:
        return False
        
    # Handle range format like "8:45 - 9:15"
    if " - " in str(suggested_pace_range):
        try:
            faster_pace, slower_pace = suggested_pace_range.split(" - ")
            faster_seconds = pace_to_seconds(faster_pace.strip())
            slower_seconds = pace_to_seconds(slower_pace.strip())
            
            if faster_seconds is None or slower_seconds is None:
                return False
                
            return faster_seconds <= actual_seconds <= slower_seconds
        except:
            return False
    
    # Fallback for single pace values (backward compatibility)
    suggested_seconds = pace_to_seconds(suggested_pace_range)
    if suggested_seconds is None:
        return False
    
    # Allow for ±30 seconds range around single pace
    return abs(actual_seconds - suggested_seconds) <= 30


def is_miles_in_range(actual_miles, suggested_miles):
    """Check if actual miles is within 10% of suggested miles."""
    if actual_miles is None or suggested_miles is None:
        return False
    try:
        actual = float(actual_miles)
        suggested = float(suggested_miles)
        if suggested == 0:
            return actual == 0
        return abs(actual - suggested) / suggested <= 0.10
    except:
        return False


def get_suggested_pace(activity_description, goal_marathon_time_str="4:00:00"):
    """Calculate suggested pace range based on activity type and goal marathon time."""
    try:
        # Parse goal marathon time
        time_parts = goal_marathon_time_str.split(":")
        goal_seconds = int(time_parts[0]) * 3600 + int(time_parts[1]) * 60 + int(time_parts[2])
        marathon_pace_seconds = goal_seconds / 26.2  # seconds per mile
        
        # Apply 10% slower adjustment to all paces (was 5%, now more conservative)
        marathon_pace_seconds *= 1.10
        
        desc_lower = activity_description.lower()
        
        def format_pace_range(base_seconds):
            """Return pace range: 3% faster to 4% slower"""
            faster_seconds = base_seconds * 0.97
            slower_seconds = base_seconds * 1.04  # Changed from 1.03 to 1.04 (4% slower)
            
            faster_pace = f"{int(faster_seconds//60)}:{int(faster_seconds%60):02d}"
            slower_pace = f"{int(slower_seconds//60)}:{int(slower_seconds%60):02d}"
            
            return f"{faster_pace} - {slower_pace}"
        
        if 'rest' in desc_lower:
            return "—"
        
        elif 'recovery' in desc_lower or 'rec' in desc_lower:
            # Recovery: Slowest pace - 120+ seconds slower than marathon pace
            recovery_seconds = marathon_pace_seconds + 120  # Much slower than easy
            return format_pace_range(recovery_seconds)
        
        elif 'medium-long' in desc_lower or 'mlr' in desc_lower:
            # Medium-Long: Flipped with GA - now faster (was 75s, now 45s)
            mlr_seconds = marathon_pace_seconds + 45  # Faster than before
            return format_pace_range(mlr_seconds)
        
        elif 'easy' in desc_lower:
            # Easy: 60-120 seconds slower than marathon pace (was 30-90)
            easy_seconds = marathon_pace_seconds + 90  # More conservative
            return format_pace_range(easy_seconds)
        
        elif 'general aerobic' in desc_lower or 'aerobic' in desc_lower:
            # GA: Flipped with MLR - now slower (was 45s, now 75s)
            ga_seconds = marathon_pace_seconds + 75  # Slower than before
            return format_pace_range(ga_seconds)
        
        elif 'hill repeat' in desc_lower:
            return "Hard uphill effort"
        
        elif 'tempo' in desc_lower:
            # Tempo: Near 10K pace (roughly 10-20 seconds faster than marathon pace, was 15-30 faster)
            tempo_seconds = marathon_pace_seconds - 15
            return format_pace_range(tempo_seconds)
        
        elif '800m interval' in desc_lower or '800' in desc_lower:
            return "Yasso 800s pace"
        
        elif '400m interval' in desc_lower or '400' in desc_lower:
            return "Mile pace or faster"
        
        elif 'marathon pace' in desc_lower:
            return format_pace_range(marathon_pace_seconds)
        
        elif 'long run' in desc_lower:
            # Long run: Same pace as medium-long run (45s slower)
            long_seconds = marathon_pace_seconds + 45  # Same as MLR
            return format_pace_range(long_seconds)
        
        elif 'half marathon' in desc_lower:
            # Half marathon: ~10 seconds faster than marathon pace (was 15 faster)
            hm_seconds = marathon_pace_seconds - 10
            return format_pace_range(hm_seconds)
        
        elif 'marathon' in desc_lower and 'pace' not in desc_lower:
            return format_pace_range(marathon_pace_seconds)
        
        else:
            # Default to general aerobic
            default_seconds = marathon_pace_seconds + 45  # More conservative
            return format_pace_range(default_seconds)
            
    except Exception:
        return "See plan"


def enhance_activity_description(activity_string):
    """Convert raw activity string to enhanced, user-friendly description, removing only the primary total distance."""
    orig = activity_string.strip()
    
    # Debug output for activity description generation
    if _is_debug():
        _debug_info(f"enhance_activity_description: '{activity_string}'")
    
    # Handle rest days
    if orig.lower() in ['rest', 'off']:
        return "Rest Day"
    
    # Handle specific workout patterns from new Hal plan
    if 'x hill' in orig.lower():
        num = re.search(r'(\d+)\s*x\s*hill', orig.lower())
        count = num.group(1) if num else 'Hill'
        return f"{count} Hill Repeats"
    
    if 'tempo' in orig.lower():
        time_match = re.search(r'(\d+)\s*tempo', orig.lower())
        if time_match:
            minutes = time_match.group(1)
            return f"Lactate Threshold Run ({minutes} min tempo)"
        return "Lactate Threshold Run"
    
    if 'x 800' in orig.lower():
        num = re.search(r'(\d+)\s*x\s*800', orig.lower())
        count = num.group(1) if num else '800m'
        return f"{count} × 800m Intervals"
    
    if 'x 400' in orig.lower():
        num = re.search(r'(\d+)\s*x\s*400', orig.lower())
        count = num.group(1) if num else '400m'
        return f"{count} × 400m Intervals"
    
    # Handle complex marathon pace workouts like "MLR 15 w/ 4 @ MP" -> "Medium-Long Run with 4 miles at Marathon Pace"
    if 'mp' in orig.lower() or 'marathon pace' in orig.lower():
        # Look for patterns like "w/ X @ MP" or "X @ MP" or "X miles @ MP"
        mp_match = re.search(r'(?:w/|with)?\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*@?\s*(?:mp|marathon\s*pace)', orig.lower())
        if mp_match:
            mp_miles = mp_match.group(1)
            if 'mlr' in orig.lower() or 'medium' in orig.lower():
                return f"Medium-Long Run with {mp_miles} miles at Marathon Pace"
            elif 'lr' in orig.lower() or 'long' in orig.lower():
                return f"Long Run with {mp_miles} miles at Marathon Pace"
            else:
                return f"Run with {mp_miles} miles at Marathon Pace"
        
        # Look for multiple segment patterns like "3x2mi @ MP" or "2x3 @ MP"
        segment_match = re.search(r'(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(?:mi|miles?)?\s*@?\s*(?:mp|marathon\s*pace)', orig.lower())
        if segment_match:
            reps = segment_match.group(1)
            distance = segment_match.group(2)
            if 'mlr' in orig.lower() or 'medium' in orig.lower():
                return f"Medium-Long Run with {reps} × {distance} mile Marathon Pace segments"
            elif 'lr' in orig.lower() or 'long' in orig.lower():
                return f"Long Run with {reps} × {distance} mile Marathon Pace segments"
            else:
                return f"Run with {reps} × {distance} mile Marathon Pace segments"
        
        # Look for time-based segments like "20 min @ MP" or "2x20min @ MP"
        time_segment_match = re.search(r'(?:(\d+)\s*x\s*)?(\d+)\s*min(?:utes?)?\s*@?\s*(?:mp|marathon\s*pace)', orig.lower())
        if time_segment_match:
            reps = time_segment_match.group(1)
            minutes = time_segment_match.group(2)
            if reps:
                segment_desc = f"{reps} × {minutes}-minute Marathon Pace segments"
            else:
                segment_desc = f"{minutes} minutes at Marathon Pace"
                
            if 'mlr' in orig.lower() or 'medium' in orig.lower():
                return f"Medium-Long Run with {segment_desc}"
            elif 'lr' in orig.lower() or 'long' in orig.lower():
                return f"Long Run with {segment_desc}"
            else:
                return f"Run with {segment_desc}"
        
        # Generic fallback - try to be more specific based on distance
        else:
            primary_miles = extract_primary_miles(orig)
            if primary_miles and primary_miles >= 8:
                return f"Long Run with Marathon Pace segments"
            elif 'mlr' in orig.lower():
                return f"Medium-Long Run with Marathon Pace segments"
            elif 'lr' in orig.lower():
                return f"Long Run with Marathon Pace segments"
            else:
                # Last resort - show the original text for context
                return f"Marathon Pace workout: {orig}"
    
    if 'half marathon' in orig.lower():
        return "Half Marathon Race"
    
    if 'marathon' in orig.lower() and 'half' not in orig.lower() and 'pace' not in orig.lower():
        return "Marathon Race"
    
    # Handle simple distance runs - categorize based on Pfitzinger methodology
    miles_match = re.search(r'(\d+(?:\.\d+)?)\s*mi(?:\s+run)?', orig.lower())
    if miles_match:
        miles = float(miles_match.group(1))
        if miles <= 4:
            return "Recovery Run"  # Short, easy runs for recovery
        elif miles <= 8:
            return "General Aerobic Run"  # Bread and butter easy runs
        elif miles <= 12:
            return "Medium-Long Run"  # ~2 hours, push pace slightly
        else:
            return "Long Run"  # 2+ hours, push pace slightly
    
    if _is_debug():
        _debug_info(f"  → Using smart activity descriptions, preserving workout-specific mileage")
    
    # Fallback: use context-aware expansion for abbreviations, removing only the primary total distance
    def get_contextual_description(abbr, original_text):
        primary_miles = extract_primary_miles(original_text)
        
        if abbr == "GA":
            if primary_miles and primary_miles <= 4:
                return "Short General Aerobic Run"
            elif primary_miles and primary_miles >= 10:
                return "Long General Aerobic Run"
            else:
                return "General Aerobic Run"
        
        elif abbr == "Rec":
            return "Recovery Run"  # Always easy, regardless of distance
        
        elif abbr == "MLR":
            # Check for marathon pace segments in MLR with specific details
            if 'mp' in original_text.lower() or '@' in original_text.lower():
                # Look for segment patterns like "3x2mi @ MP" or "2x3 @ MP"
                segment_match = re.search(r'(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(?:mi|miles?)?\s*@?\s*mp', original_text.lower())
                if segment_match:
                    reps = segment_match.group(1)
                    distance = segment_match.group(2)
                    return f"Medium-Long Run with {reps} × {distance} mile Marathon Pace segments"
                
                # Look for simple patterns like "w/ 4 @ MP"
                mp_match = re.search(r'(?:w/|with)?\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*@?\s*mp', original_text.lower())
                if mp_match:
                    return f"Medium-Long Run with {mp_match.group(1)} miles at Marathon Pace"
                
                # Look for time-based segments
                time_match = re.search(r'(?:(\d+)\s*x\s*)?(\d+)\s*min(?:utes?)?\s*@?\s*mp', original_text.lower())
                if time_match:
                    reps = time_match.group(1)
                    minutes = time_match.group(2)
                    if reps:
                        return f"Medium-Long Run with {reps} × {minutes}-minute Marathon Pace segments"
                    else:
                        return f"Medium-Long Run with {minutes} minutes at Marathon Pace"
                
                return "Medium-Long Run with Marathon Pace segments"
            return "Medium-Long Run"  # ~2 hours, push pace slightly
        
        elif abbr == "LR":
            # Check for marathon pace segments in LR with specific details
            if 'mp' in original_text.lower() or '@' in original_text.lower():
                # Look for segment patterns like "3x2mi @ MP" or "2x3 @ MP"
                segment_match = re.search(r'(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(?:mi|miles?)?\s*@?\s*mp', original_text.lower())
                if segment_match:
                    reps = segment_match.group(1)
                    distance = segment_match.group(2)
                    return f"Long Run with {reps} × {distance} mile Marathon Pace segments"
                
                # Look for simple patterns like "w/ 8 @ MP"
                mp_match = re.search(r'(?:w/|with)?\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*@?\s*mp', original_text.lower())
                if mp_match:
                    return f"Long Run with {mp_match.group(1)} miles at Marathon Pace"
                
                # Look for time-based segments
                time_match = re.search(r'(?:(\d+)\s*x\s*)?(\d+)\s*min(?:utes?)?\s*@?\s*mp', original_text.lower())
                if time_match:
                    reps = time_match.group(1)
                    minutes = time_match.group(2)
                    if reps:
                        return f"Long Run with {reps} × {minutes}-minute Marathon Pace segments"
                    else:
                        return f"Long Run with {minutes} minutes at Marathon Pace"
                
                return "Long Run with Marathon Pace segments"
            return "Long Run"  # 2+ hours, push pace slightly
        
        elif abbr == "SP":
            return "Speed Work"
        
        elif abbr in ["V8", "V9", "V10"]:
            return "VO₂Max Intervals"  # 600m-1200m at 5K pace
        
        elif abbr == "LT":
            # Lactate Threshold runs have significant portions at tempo pace
            if primary_miles and primary_miles >= 8:
                return "Long Run with Lactate Threshold segments"
            else:
                return "Lactate Threshold Run"
        
        elif abbr == "HMP":
            # Half Marathon Pace workouts
            if primary_miles and primary_miles >= 8:
                return "Long Run with Half Marathon Pace segments"
            else:
                return "Half Marathon Pace Run"
        
        elif abbr == "MP":
            # Marathon Pace - extract specific segment details
            # Look for segment patterns like "3x2mi @ MP" or "2x3 @ MP"
            segment_match = re.search(r'(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(?:mi|miles?)?\s*@?\s*mp', original_text.lower())
            if segment_match:
                reps = segment_match.group(1)
                distance = segment_match.group(2)
                if primary_miles and primary_miles >= 8:
                    return f"Long Run with {reps} × {distance} mile Marathon Pace segments"
                else:
                    return f"Run with {reps} × {distance} mile Marathon Pace segments"
            
            # Look for simple patterns like "w/ 4 @ MP"
            mp_match = re.search(r'(?:w/|with)?\s*(\d+(?:\.\d+)?)\s*(?:miles?)?\s*@?\s*mp', original_text.lower())
            if mp_match:
                if primary_miles and primary_miles >= 8:
                    return f"Long Run with {mp_match.group(1)} miles at Marathon Pace"
                else:
                    return f"Run with {mp_match.group(1)} miles at Marathon Pace"
            
            # Look for time-based segments
            time_match = re.search(r'(?:(\d+)\s*x\s*)?(\d+)\s*min(?:utes?)?\s*@?\s*mp', original_text.lower())
            if time_match:
                reps = time_match.group(1)
                minutes = time_match.group(2)
                if reps:
                    segment_desc = f"{reps} × {minutes}-minute Marathon Pace segments"
                else:
                    segment_desc = f"{minutes} minutes at Marathon Pace"
                    
                if primary_miles and primary_miles >= 8:
                    return f"Long Run with {segment_desc}"
                else:
                    return f"Run with {segment_desc}"
            
            # Generic marathon pace - should specify it's segments, not the whole run
            if primary_miles and primary_miles >= 8:
                return "Long Run with Marathon Pace segments"
            else:
                return "Run with Marathon Pace segments"
        
        # Fallback to basic descriptions
        base_map = {
            "GA": "General Aerobic Run",
            "Rec": "Recovery Run", 
            "MLR": "Medium-Long Run",
            "LR": "Long Run",
            "SP": "Speed Work",
            "V8": "VO₂Max Intervals",
            "V9": "VO₂Max Intervals",
            "V10": "VO₂Max Intervals",
            "LT": "Lactate Threshold Run",
            "HMP": "Half Marathon Pace Run",
            "MP": "Marathon Pace Run",
        }
        
        return base_map.get(abbr, abbr)
    
    activity_map = {
        "GA": lambda: get_contextual_description("GA", orig),
        "Rec": lambda: get_contextual_description("Rec", orig),
        "MLR": lambda: get_contextual_description("MLR", orig),
        "LR": lambda: get_contextual_description("LR", orig),
        "SP": lambda: get_contextual_description("SP", orig),
        "V8": lambda: get_contextual_description("V8", orig),
        "V9": lambda: get_contextual_description("V9", orig),
        "V10": lambda: get_contextual_description("V10", orig),
        "LT": lambda: get_contextual_description("LT", orig),
        "HMP": lambda: get_contextual_description("HMP", orig),
        "MP": lambda: get_contextual_description("MP", orig),
    }
    
    sorted_keys = sorted(activity_map.keys(), key=len, reverse=True)
    for abbr in sorted_keys:
        if re.search(r'\b' + re.escape(abbr) + r'\b', orig):
            result = activity_map[abbr]()  # Call the lambda function
            if _is_debug():
                _debug_info(f"  → Matched '{abbr}', returning: '{result}'")
            return result
    
    if _is_debug():
        _debug_info(f"  → No pattern matched, removing only primary distance from: '{orig}'")
    
    # Smart cleanup: remove only the first/primary distance number, preserve workout-specific numbers
    # This removes patterns like "MLR 12" -> "MLR" but keeps "4 @ MP" -> "4 @ MP"
    def remove_primary_distance(text):
        # Remove leading distance like "12 MLR" -> "MLR"
        text = re.sub(r'^\s*\d+(?:\.\d+)?\s+', '', text)
        # Remove trailing distance like "MLR 12" -> "MLR" but preserve "MLR 12 w/ 4 @ MP"
        if not re.search(r'(?:@|with|w/)', text.lower()):
            text = re.sub(r'\s+\d+(?:\.\d+)?\s*$', '', text)
        return text.strip()
    
    cleaned = remove_primary_distance(orig)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()  # Clean up extra spaces
    return cleaned if cleaned else orig


def generate_training_plan(start_date, plan_file=None, goal_time: str = "4:00:00"):
    """Loads the training plan from a CSV or ICS and adjusts dates. plan_file defaults to run_plan.csv."""
    try:
        csv_path = plan_file or "run_plan.csv"
        if str(csv_path).lower().endswith(".ics"):
            activities_list = parse_ics_activities(csv_path)
            if not activities_list:
                st.error(f"`{csv_path}` could not be parsed or has no events.")
                return pd.DataFrame()
            activities = pd.Series(activities_list, dtype="object")
        else:
            plan_df = pd.read_csv(csv_path, header=0)
            plan_df.columns = [col.strip() for col in plan_df.columns]
            cols_lower = {c.lower() for c in plan_df.columns}
            # Case 1: Simple list with 'Plan' column
            if "plan" in cols_lower:
                plan_df.dropna(subset=['Plan'], inplace=True)
                plan_df = plan_df[plan_df['Plan'].str.strip() != '']
                activities = plan_df['Plan'].str.strip().copy().reset_index(drop=True)
            else:
                # Case 2: Weekly matrix with weekday columns; flatten Monday..Sunday rows
                weekday_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
                present_days = [d for d in weekday_order if d in plan_df.columns]
                if not present_days:
                    st.error(f"`{csv_path}` has no 'Plan' column or weekday columns.")
                    return pd.DataFrame()
                day_values = []
                for _, row in plan_df.iterrows():
                    for d in present_days:
                        val = row.get(d)
                        if pd.isna(val) or str(val).strip() == "":
                            continue
                        txt = str(val).strip()
                        # Strip leading date like 'YYYY-MM-DD: '
                        if ":" in txt:
                            parts = txt.split(":", 1)
                            # If left side looks like a date, keep only RHS
                            left = parts[0].strip()
                            rhs = parts[1].strip()
                            if len(left) >= 8 and left[0:4].isdigit():
                                txt = rhs
                        day_values.append(txt)
                activities = pd.Series(day_values, dtype="object")
        if len(activities):
            activities = activities[~activities.apply(is_weekly_summary)].reset_index(drop=True)

        enhanced_activities = activities.apply(lambda x: enhance_activity_description(x))
        planned_miles = activities.apply(extract_primary_miles)

        num_days = len(activities)
        dates = [start_date + timedelta(days=i) for i in range(num_days)]
        days_of_week = [date.strftime("%A") for date in dates]

        new_plan_df = pd.DataFrame({
            'Date': pd.to_datetime(dates).strftime("%Y-%m-%d"),
            'Day': days_of_week,
            'Activity_Abbr': activities,
            'Activity': enhanced_activities,
            'Plan_Miles': planned_miles,
        })
        
        # Add activity tooltips
        new_plan_df['Activity_Tooltip'] = new_plan_df.apply(
            lambda row: get_activity_tooltip(row.get('Activity_Abbr', row.get('Activity', ''))), axis=1
        )
        new_plan_df['Activity_Short_Description'] = new_plan_df['Activity'].apply(get_activity_short_description)
        # Do not add single-value pace here; we'll compute ranges later using get_pace_range
        
        return new_plan_df

    except FileNotFoundError:
        st.error(f"`{plan_file or 'run_plan.csv'}` not found. Please make sure it's in the repo (root or plans/).")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error processing `{plan_file or 'run_plan.csv'}`: {e}")
        return pd.DataFrame()


# -------- Plan adjustment helpers --------

def _find_column(df, candidates=None, contains=None):
    cols = {str(c).lower().replace(" ", "").replace("_", ""): c for c in df.columns}
    if candidates:
        for cand in candidates:
            key = cand.lower().replace(" ", "").replace("_", "")
            if key in cols:
                return cols[key]
    if contains:
        for c in df.columns:
            if contains.lower() in str(c).lower():
                return c
    return None


def _get_date_col(df):
    return _find_column(df, candidates=["date", "run_date"], contains="date")


def _get_miles_col(df):
    col = _find_column(df, candidates=["plan_miles", "miles", "planned_miles", "distance", "plan_miles", "dist"]) or _find_column(df, contains="mile") or _find_column(df, contains="dist")
    return col


def _compute_week_index(df, date_col, start_date=None):
    if start_date is not None:
        base = pd.to_datetime(start_date)
    else:
        base = pd.to_datetime(df[date_col].min())
    d = pd.to_datetime(df[date_col]) - base
    return (d.dt.days // 7) + 1


def _weekday_series(df, date_col):
    if date_col is None:
        return None
    return pd.to_datetime(df[date_col]).dt.weekday


def _combine_week_pair_best_effort(df, date_col, miles_col, w_a, w_b):
    out = df.copy()
    weeks = set(out["_mp_week"]) if "_mp_week" in out.columns else set()
    if w_a not in weeks or w_b not in weeks:
        return out

    a = out[out["_mp_week"] == w_a].copy()
    b = out[out["_mp_week"] == w_b].copy()

    if date_col and miles_col and len(a) and len(b):
        a_wd = _weekday_series(a, date_col)
        b_wd = _weekday_series(b, date_col)
        a.loc[:, "_mp_wd"] = a_wd
        b.loc[:, "_mp_wd"] = b_wd
        b_sum = b.groupby("_mp_wd")[miles_col].sum() if miles_col in b.columns else {}
        a[miles_col] = pd.to_numeric(a[miles_col], errors="coerce").fillna(0.0) + a["_mp_wd"].map(b_sum).fillna(0.0)
        a.drop(columns=["_mp_wd"], inplace=True, errors="ignore")
        out.loc[a.index, miles_col] = a[miles_col]

    out = out[out["_mp_week"] != w_b].copy()

    if date_col:
        mask_after = out["_mp_week"] > w_b
        out.loc[mask_after, date_col] = pd.to_datetime(out.loc[mask_after, date_col]) - timedelta(days=7)

    if date_col:
        out["_mp_week"] = _compute_week_index(out, date_col, pd.to_datetime(out[date_col]).min())
    else:
        uniq = {wk: i + 1 for i, wk in enumerate(sorted(out["_mp_week"].unique()))}
        out["_mp_week"] = out["_mp_week"].map(uniq)

    return out


def adjust_training_plan(df, start_date=None, week_adjust=0, weekly_miles_delta=0):
    try:
        if df is None or len(df) == 0:
            return df
        out = df.copy()
        date_col = _get_date_col(out)
        miles_col = _get_miles_col(out)
        if miles_col:
            out[miles_col] = pd.to_numeric(out[miles_col], errors="coerce").fillna(0.0)
        if date_col:
            out["_mp_week"] = _compute_week_index(out, date_col, start_date)
        else:
            guess = _find_column(out, candidates=["week"])
            if guess:
                out["_mp_week"] = pd.to_numeric(out[guess], errors="coerce").fillna(1).astype(int)
            else:
                out["_mp_week"] = (pd.Series(range(len(out))) // 7) + 1

        wa = int(week_adjust or 0)
        if wa < 0:
            if wa == -1:
                out = _combine_week_pair_best_effort(out, date_col, miles_col, 1, 2)
            elif wa == -2:
                out = _combine_week_pair_best_effort(out, date_col, miles_col, 1, 2)
                out = _combine_week_pair_best_effort(out, date_col, miles_col, 3, 4)
        elif wa > 0:
            to_dup = [6] if wa == 1 else [6, 12] if wa == 2 else []
            if to_dup:
                current_max = int(out["_mp_week"].max())
                blocks = [out]
                append_i = 1
                for w in to_dup:
                    src_w = w if w in set(out["_mp_week"]) else current_max
                    nb = out[out["_mp_week"] == src_w].copy()
                    new_w = current_max + append_i
                    nb["_mp_week"] = new_w
                    if date_col:
                        nb[date_col] = pd.to_datetime(nb[date_col]) + timedelta(days=(new_w - src_w) * 7)
                    blocks.append(nb)
                    append_i += 1
                out = pd.concat(blocks, ignore_index=True)

        delta = int(weekly_miles_delta or 0)
        if miles_col and delta != 0:
            k = abs(delta)
            sign = 1 if delta > 0 else -1
            def _adjust_week(group):
                if k <= 0 or len(group) == 0:
                    return group
                # Fix DataFrame boolean context issue
                if miles_col not in group.columns:
                    return group
                largest_values = group[miles_col].nlargest(min(k, len(group)))
                if largest_values.empty:
                    return group
                idx = largest_values.index
                group.loc[idx, miles_col] = (group.loc[idx, miles_col] + (1 * sign)).clip(lower=0)
                return group
            out = out.groupby("_mp_week", group_keys=False).apply(_adjust_week, include_groups=False)

        if "_mp_week" in out.columns:
            out.drop(columns=["_mp_week"], inplace=True)
        if date_col:
            out.sort_values(by=date_col, inplace=True, ignore_index=True)
        return out
    except Exception:
        return df


def apply_user_plan_adjustments(plan_df, settings, start_date):
    adjusted_df = adjust_training_plan(
        plan_df,
        start_date=start_date,
        week_adjust=int(settings.get("week_adjust", 0) or 0),
        weekly_miles_delta=int(settings.get("weekly_miles_delta", 0) or 0),
    )
    
    weekly_miles_delta = int(settings.get("weekly_miles_delta", 0) or 0)
    if _is_debug():
        _debug_info(f"Applying weekly_miles_delta: {weekly_miles_delta}")
    
    # After adjusting miles, update the Activity descriptions to reflect the new mileage
    # Check if any mileage has changed from the original plan
    mileage_changed = False
    if 'Activity_Abbr' in adjusted_df.columns and 'Plan_Miles' in adjusted_df.columns:
        if _is_debug():
            _debug_info("Checking for mileage changes...")
        for idx in adjusted_df.index:
            if idx in plan_df.index:
                original_miles = plan_df.loc[idx, 'Plan_Miles'] if pd.notna(plan_df.loc[idx, 'Plan_Miles']) else 0
                adjusted_miles = adjusted_df.loc[idx, 'Plan_Miles'] if pd.notna(adjusted_df.loc[idx, 'Plan_Miles']) else 0
                if abs(original_miles - adjusted_miles) > 0.01:  # Allow for small floating point differences
                    if _is_debug():
                        _debug_info(f"Mileage change detected at row {idx}: {original_miles} -> {adjusted_miles}")
                    mileage_changed = True
                    break
    
    if _is_debug():
        _debug_info(f"Mileage changed: {mileage_changed}")
    
    if mileage_changed:
        if _is_debug():
            _debug_info("Updating activity descriptions with adjusted mileage")
        
        # Update the raw activity descriptions with adjusted mileage
        for idx in adjusted_df.index:
            original_miles = plan_df.loc[idx, 'Plan_Miles'] if idx in plan_df.index else None
            adjusted_miles = adjusted_df.loc[idx, 'Plan_Miles']
            
            if _is_debug() and pd.notna(adjusted_miles) and adjusted_miles > 0:
                original_abbr = adjusted_df.loc[idx, 'Activity_Abbr']
                _debug_info(f"Row {idx}: '{original_abbr}' - Original miles: {original_miles}, Adjusted miles: {adjusted_miles}")
            
            if pd.notna(adjusted_miles) and adjusted_miles > 0:
                original_abbr = adjusted_df.loc[idx, 'Activity_Abbr']
                # Update the abbreviated activity description with new mileage
                new_abbr = replace_primary_miles(original_abbr, adjusted_miles)
                adjusted_df.loc[idx, 'Activity_Abbr'] = new_abbr
                
                if _is_debug() and new_abbr != original_abbr:
                    _debug_info(f"Updated '{original_abbr}' -> '{new_abbr}'")
        
        # Regenerate the enhanced activity descriptions based on updated abbreviations
        if _is_debug():
            _debug_info("Regenerating activity descriptions...")
        adjusted_df['Activity'] = adjusted_df.apply(lambda row: enhance_activity_description(row['Activity_Abbr']), axis=1)
        
        # Also update tooltips based on new activity descriptions
        adjusted_df['Activity_Tooltip'] = adjusted_df.apply(
            lambda row: get_activity_tooltip(row.get('Activity_Abbr', row.get('Activity', ''))), axis=1
        )
        adjusted_df['Activity_Short_Description'] = adjusted_df.apply(lambda row: get_activity_short_description(row['Activity']), axis=1)
        
        if _is_debug():
            changed_count = len([idx for idx in adjusted_df.index if idx in plan_df.index and adjusted_df.loc[idx, 'Activity_Abbr'] != plan_df.loc[idx, 'Activity_Abbr']])
            _debug_info(f"Updated activity descriptions for {changed_count} rows")
        
        if _is_debug():
            _debug_info("Finished updating activity descriptions")
    
    return adjusted_df


# -------- Per-user plan overrides (swap days) --------

def _plan_signature(settings: dict) -> str:
    """Create a unique signature for the current plan to store overrides."""
    plan_file = settings.get('plan_file', 'run_plan.csv')
    start_date = settings.get('start_date', '')
    
    # If start_date is a datetime, convert to string
    if hasattr(start_date, 'strftime'):
        start_date = start_date.strftime('%Y-%m-%d')
        
    # Fallback to today if no start date (shouldn't happen)
    if not start_date:
        start_date = datetime.now().strftime('%Y-%m-%d')
    
    signature = f"{plan_file}|{start_date}"
    
    if _is_debug():
        _debug_info(f"Plan signature: {signature} (plan_file={plan_file}, start_date={start_date})")
        
    return signature


def _get_overrides_for_plan(settings: dict) -> dict:
    """Get overrides for the current plan, combining session and saved overrides."""
    try:
        sig = _plan_signature(settings)
        
        # Get session overrides - simplified logic
        session_overrides = {}
        if 'plan_overrides_by_plan' in st.session_state:
            if sig in st.session_state['plan_overrides_by_plan']:
                session_overrides = st.session_state['plan_overrides_by_plan'][sig] or {}
        
        # Get saved overrides from settings - simplified logic
        saved_overrides = {}
        if 'overrides_by_plan' in settings:
            if sig in settings['overrides_by_plan']:
                saved_overrides = settings['overrides_by_plan'][sig] or {}
        
        # Combine them, session overrides win
        combined = {**saved_overrides, **session_overrides}
        
        # Debug output
        if _is_debug():
            st.write(f"Debug _get_overrides_for_plan:")
            st.write(f"  Plan signature: '{sig}'")
            st.write(f"  Session overrides: {session_overrides}")
            st.write(f"  Saved overrides: {saved_overrides}") 
            st.write(f"  Combined overrides: {combined}")
            st.session_state["_debug_override_source"] = {
                "sig": sig,
                "session": session_overrides,
                "saved": saved_overrides,
                "combined": combined
            }
            
        return combined
    except Exception as e:
        if _is_debug():
            st.error(f"Error getting overrides: {e}")
            import traceback
            st.code(traceback.format_exc())
        return {}


def _save_overrides_for_plan(user_hash: str, settings: dict, overrides: dict):
    """Save overrides for the current plan, both to settings and session state."""
    try:
        sig = _plan_signature(settings)
        
        # First update the settings dictionary
        by_plan = settings.get("overrides_by_plan", {}) or {}
        by_plan[sig] = overrides
        settings["overrides_by_plan"] = by_plan
        
        # Save to persistent storage
        save_user_settings(user_hash, settings)
        
        # Also update session_state for immediate UI update
        if "plan_overrides_by_plan" not in st.session_state:
            st.session_state["plan_overrides_by_plan"] = {}
            
        st.session_state["plan_overrides_by_plan"][sig] = overrides
        
        # Debug info
        if _is_debug():
            st.write(f"Debug _save_overrides_for_plan:")
            st.write(f"  Plan signature: '{sig}'")
            st.write(f"  Saving {len(overrides)} overrides")
            st.write(f"  Override keys: {list(overrides.keys())}")
            st.session_state["_debug_saved_overrides"] = {
                "sig": sig,
                "overrides": overrides,
                "session_overrides": st.session_state["plan_overrides_by_plan"]
            }
            
    except Exception as e:
        st.error(f"Error saving overrides: {e}")
        if _is_debug():
            import traceback
            st.code(traceback.format_exc())


def apply_plan_overrides(plan_df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """Apply user-defined overrides to the plan DataFrame."""
    try:
        if _is_debug():
            st.write(f"🔧 DEBUG: apply_plan_overrides called with build {BUILD_SHA}")
        
        overrides = _get_overrides_for_plan(settings)
        
        if _is_debug():
            st.write(f"Debug apply_plan_overrides: Starting with {len(plan_df) if plan_df is not None else 0} rows")
            if plan_df is not None and 'DateISO' in plan_df.columns:
                sample_dates = plan_df['DateISO'].head(3).tolist()
                st.write(f"  Sample DateISO values: {sample_dates}")
            else:
                st.write("  No DateISO column found!")
            
            # Add detailed override debug info
            st.write(f"Debug apply_plan_overrides: Checking overrides...")
            plan_sig = _plan_signature(settings)
            st.write(f"  Plan signature: {plan_sig}")
            st.write(f"  Overrides found: {overrides}")
            st.write(f"  Override keys: {list(overrides.keys()) if overrides else 'None'}")
            
            # Store this in session state for persistent debugging
            if "swap_debug_history" not in st.session_state:
                st.session_state.swap_debug_history = []
            st.session_state.swap_debug_history.append({
                "timestamp": datetime.now().isoformat(),
                "operation": "apply_overrides_start",
                "plan_sig": plan_sig,
                "override_count": len(overrides) if overrides else 0,
                "override_keys": list(overrides.keys()) if overrides else [],
                "plan_df_has_dateiso": 'DateISO' in (plan_df.columns if plan_df is not None else [])
            })
        
        # Fix for None vs empty dict confusion
        if overrides is None:
            overrides = {}
            
        if not overrides or plan_df is None or plan_df.empty:
            if _is_debug():
                st.write(f"Debug apply_plan_overrides: Early exit - overrides empty: {not overrides}, plan_df empty: {plan_df is None or plan_df.empty}")
                st.write(f"  Overrides type: {type(overrides)}")
                st.write(f"  Overrides length: {len(overrides) if hasattr(overrides, '__len__') else 'N/A'}")
                st.write(f"  Plan_df is None: {plan_df is None}")
                st.write(f"  Plan_df is empty: {plan_df.empty if plan_df is not None else 'N/A'}")
                
                # Store early exit debug info
                st.session_state.swap_debug_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "operation": "apply_overrides_early_exit",
                    "overrides_empty": not overrides,
                    "plan_df_none": plan_df is None,
                    "plan_df_empty": plan_df.empty if plan_df is not None else True,
                    "overrides_type": str(type(overrides)),
                    "overrides_len": len(overrides) if hasattr(overrides, '__len__') else 0
                })
            return plan_df
            
        # Make a fresh copy to avoid modifying the original
        out = plan_df.copy()
        
        # Make sure Date is in proper datetime format
        if "Date" in out.columns:
            out["Date"] = pd.to_datetime(out["Date"]).dt.date
            
        # For each date with an override, apply the changes
        applied_overrides = []
        
        if _is_debug():
            st.write(f"Debug apply_plan_overrides: Starting override processing loop...")
            st.write(f"  Processing {len(overrides)} override(s)")
            for i, (k, v) in enumerate(overrides.items()):
                st.write(f"  Override {i+1}: {k} -> {v}")
        
        for date_iso, payload in overrides.items():
            try:
                if _is_debug():
                    st.write(f"Debug apply_plan_overrides: Processing override for {date_iso}")
                    st.write(f"  Payload: {payload}")
                    
                dt = datetime.strptime(str(date_iso), "%Y-%m-%d").date()
                
                # Try finding the row with DateISO first, then fall back to Date
                if "DateISO" in out.columns:
                    mask = (out["DateISO"] == date_iso)
                    if _is_debug():
                        st.write(f"  Using DateISO column, mask matches: {mask.sum()}")
                        if mask.sum() == 0:
                            # Show what DateISO values we have
                            unique_dates = out["DateISO"].unique()[:10]  # Show first 10
                            st.write(f"  Available DateISO values (first 10): {unique_dates}")
                else:
                    mask = (out["Date"] == dt)
                    if _is_debug():
                        st.write(f"  Using Date column, mask matches: {mask.sum()}")
                
                if mask is not None and mask.any():
                    applied_overrides.append(date_iso)
                    if _is_debug():
                        st.write(f"  ✓ Found matching row(s) for {date_iso}")
                        matching_indices = out[mask].index.tolist()
                        st.write(f"    Matching indices: {matching_indices}")
                        
                    # Apply each field from the override to the matching row
                    for k, v in payload.items():
                        if k in out.columns:
                            if _is_debug():
                                old_val = out.loc[mask, k].values[0] if any(mask) else "N/A"
                                st.write(f"    Updating {k}: '{old_val}' -> '{v}'")
                            out.loc[mask, k] = v
                        elif _is_debug():
                            st.write(f"    Skipping field {k} - not in DataFrame columns")
                elif _is_debug():
                    st.write(f"  ❌ No matching row found for date {date_iso}")
                    st.write(f"     Mask is None: {mask is None}")
                    st.write(f"     Mask any(): {mask.any() if mask is not None else 'N/A'}")
            except Exception as e:
                if _is_debug():
                    st.error(f"Override apply error for {date_iso}: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                continue
                
        if _is_debug():
            st.write(f"Debug apply_plan_overrides: Applied overrides for dates: {applied_overrides}")
            st.session_state["_debug_applied_overrides"] = applied_overrides
            
        return out
    except Exception as e:
        if _is_debug():
            st.error(f"Error applying overrides: {e}")
            import traceback
            st.code(traceback.format_exc())
        return plan_df


def _override_payload_from_row(row: pd.Series) -> dict:
    return {
        "Activity_Abbr": row.get("Activity_Abbr", ""),
        "Activity": row.get("Activity", ""),
        "Plan_Miles": float(row.get("Plan_Miles")) if pd.notna(row.get("Plan_Miles")) else None,
    }


def swap_plan_days(user_hash: str, settings: dict, plan_df: pd.DataFrame, date_a, date_b):
    """Swap the workout details between two days in the plan."""
    if _is_debug():
        _debug_info(f"swap_plan_days: Starting swap between {date_a} and {date_b}")
        _debug_info(f"swap_plan_days: DataFrame columns: {list(plan_df.columns)}")
        _debug_info(f"swap_plan_days: DataFrame shape: {plan_df.shape}")
    
    try:
        # Use merged_df with DateISO to ensure correct row selection
        df = plan_df.copy()
        df["Date"] = pd.to_datetime(df["Date"]).dt.date
        
        if _is_debug():
            _debug_info(f"swap_plan_days: After Date conversion, DateISO in columns: {'DateISO' in df.columns}")
        
        # Find the rows for the two selected dates
        if "DateISO" in df.columns:
            date_a_str = date_a.strftime("%Y-%m-%d")
            date_b_str = date_b.strftime("%Y-%m-%d")
            row_a = df[df["DateISO"] == date_a_str]
            row_b = df[df["DateISO"] == date_b_str]
            
            if _is_debug():
                _debug_info(f"swap_plan_days: Looking for DateISO {date_a_str}, found {len(row_a)} rows")
                _debug_info(f"swap_plan_days: Looking for DateISO {date_b_str}, found {len(row_b)} rows")
        else:
            date_a_str = date_a.strftime("%Y-%m-%d")
            date_b_str = date_b.strftime("%Y-%m-%d")
            row_a = df[df["Date"] == date_a]
            row_b = df[df["Date"] == date_b]
            
            if _is_debug():
                _debug_info(f"swap_plan_days: Looking for Date {date_a}, found {len(row_a)} rows")
                _debug_info(f"swap_plan_days: Looking for Date {date_b}, found {len(row_b)} rows")
            
        if row_a.empty or row_b.empty:
            error_msg = f"Selected dates are not in the plan: {date_a}, {date_b}"
            if _is_debug():
                _debug_info(f"swap_plan_days: ERROR - {error_msg}")
                if row_a.empty:
                    _debug_info(f"swap_plan_days: Row A empty for date {date_a_str}")
                if row_b.empty:
                    _debug_info(f"swap_plan_days: Row B empty for date {date_b_str}")
            raise ValueError(error_msg)
            
        # Only swap workout fields, not date/day
        workout_fields = ["Activity_Abbr", "Activity", "Plan_Miles"]
        
        if _is_debug():
            _debug_info(f"swap_plan_days: Row A data: {dict(row_a.iloc[0])}")
            _debug_info(f"swap_plan_days: Row B data: {dict(row_b.iloc[0])}")
        
        # Extract the workout details from each row and swap them
        # pa will be stored as the override for date A, so it should contain row_b's data
        # pb will be stored as the override for date B, so it should contain row_a's data  
        pa = {k: row_b.iloc[0][k] for k in workout_fields if k in row_b.columns}
        pb = {k: row_a.iloc[0][k] for k in workout_fields if k in row_a.columns}
        
        if _is_debug():
            st.write(f"Debug swap_plan_days: Swapping {date_a_str} <-> {date_b_str}")
            st.write(f"  Date A ({date_a_str}) will get: {pa}")
            st.write(f"  Date B ({date_b_str}) will get: {pb}")
            _debug_info(f"swap_plan_days: Creating override data - pa={pa}, pb={pb}")
            
            # Store debug info in session state
            if "swap_debug_history" not in st.session_state:
                st.session_state.swap_debug_history = []
            st.session_state.swap_debug_history.append({
                "timestamp": datetime.now().isoformat(),
                "operation": "swap_data_created",
                "dates": f"{date_a_str} <-> {date_b_str}",
                "override_data": f"A gets: {pa}, B gets: {pb}"
            })
        
        # Generate fresh tooltips for the swapped activities
        # pa contains row_b's activity, so generate tooltip for that activity  
        if "Activity" in pa:
            pa["Activity_Tooltip"] = get_activity_tooltip(pa["Activity"])
            pa["Activity_Short_Description"] = get_activity_short_description(pa["Activity"])
        # pb contains row_a's activity, so generate tooltip for that activity
        if "Activity" in pb:
            pb["Activity_Tooltip"] = get_activity_tooltip(pb["Activity"])
            pb["Activity_Short_Description"] = get_activity_short_description(pb["Activity"])
        
        # Get existing overrides 
        plan_sig = _plan_signature(settings)
        overrides = _get_overrides_for_plan(settings)
        if overrides is None:
            overrides = {}
            
        if _is_debug():
            _debug_info(f"swap_plan_days: Plan signature: {plan_sig}")
            _debug_info(f"swap_plan_days: Existing overrides count: {len(overrides)}")
            _debug_info(f"swap_plan_days: Existing overrides keys: {list(overrides.keys())}")
            
        # Store the workouts swapped (b's workout goes to a's date, a's workout goes to b's date)
        overrides[date_a_str] = pb
        overrides[date_b_str] = pa
        
        if _is_debug():
            st.write(f"Debug: Saving overrides: {len(overrides)} total overrides")
            st.write(f"  {date_a_str}: {overrides[date_a_str]}")
            st.write(f"  {date_b_str}: {overrides[date_b_str]}")
            _debug_info(f"swap_plan_days: Updated overrides - total count: {len(overrides)}")
            _debug_info(f"swap_plan_days: About to save overrides for plan: {plan_sig}")
            
            # Store debug info in session state
            if "swap_debug_history" not in st.session_state:
                st.session_state.swap_debug_history = []
            st.session_state.swap_debug_history.append({
                "timestamp": datetime.now().isoformat(),
                "operation": "saving_overrides",
                "plan_sig": plan_sig,
                "override_count": len(overrides),
                "dates": f"{date_a_str}, {date_b_str}"
            })
        
        # Save the updated overrides
        _save_overrides_for_plan(user_hash, settings, overrides)
        
        if _is_debug():
            st.write("Debug: Checking if overrides were saved correctly...")
            saved_overrides = _get_overrides_for_plan(settings)
            st.write(f"  Saved overrides count: {len(saved_overrides) if saved_overrides else 0}")
            if saved_overrides and date_a_str in saved_overrides:
                st.write(f"  {date_a_str}: {saved_overrides[date_a_str]}")
            if saved_overrides and date_b_str in saved_overrides:
                st.write(f"  {date_b_str}: {saved_overrides[date_b_str]}")
            _debug_info(f"swap_plan_days: Verification - saved overrides count: {len(saved_overrides) if saved_overrides else 0}")
            
            # Store verification info in session state
            st.session_state.swap_debug_history.append({
                "timestamp": datetime.now().isoformat(),
                "operation": "override_verification",
                "saved_count": len(saved_overrides) if saved_overrides else 0,
                "found_date_a": date_a_str in saved_overrides if saved_overrides else False,
                "found_date_b": date_b_str in saved_overrides if saved_overrides else False
            })
        
        # Force refresh of plan to ensure changes are visible
        st.session_state.plan_needs_refresh = True
        
        if _is_debug():
            _debug_info("swap_plan_days: Swap completed successfully, plan refresh triggered")
        
        return True
    except Exception as e:
        st.error(f"Swap failed: {e}")
        if _is_debug():
            import traceback
            st.code(traceback.format_exc())
        return False


def clear_override_day(user_hash: str, settings: dict, date_x):
    try:
        overrides = _get_overrides_for_plan(settings)
        key = date_x.strftime("%Y-%m-%d")
        if key in overrides:
            del overrides[key]
            _save_overrides_for_plan(user_hash, settings, overrides)
            st.success(f"Cleared override for {date_x.strftime('%a %m-%d')}.")
        else:
            st.info("No override set for that date.")
    except Exception as e:
        st.error(f"Clear failed: {e}")


def clear_all_overrides(user_hash: str, settings: dict):
    try:
        sig = _plan_signature(settings)
        by_plan = settings.get("overrides_by_plan", {}) or {}
        if sig in by_plan:
            del by_plan[sig]
            settings["overrides_by_plan"] = by_plan
            save_user_settings(user_hash, settings)
            st.success("Cleared all overrides for this plan.")
        else:
            st.info("No overrides to clear.")
    except Exception as e:
               st.error(f"Reset failed: {e}")

def main():
    """Main application logic."""
    # Check for persistent login data first
    if not st.session_state.current_user:
        if _is_debug():
            st.write("Debug: No current user, checking persistent login...")
        check_persistent_login()
        
    if not st.session_state.current_user:
        if _is_debug():
            st.write("Debug: Still no current user after persistent login check, showing login page...")
            # Show query params for debugging
            if st.query_params:
                st.write(f"Debug: Current query params: {dict(st.query_params)}")
        google_login()
        return

    if _is_debug():
        st.write(f"Debug: User logged in: {st.session_state.current_user.get('email', 'Unknown')}")
    
    show_header()
    show_dashboard()

def show_dashboard():
    """Display the main dashboard with training plan and Strava data."""
    try:
        user = st.session_state.get("current_user") or {}
        email = user.get("email", "demo@local")
        user_hash = get_user_hash(email)
    except Exception:
        user_hash = "anon"

    settings = training_plan_setup()

    st.markdown("---")
    st.header("Your Training Schedule")

    # Show persistent swap results if they exist
    if "swap_result" in st.session_state:
        swap_result = st.session_state.swap_result
        if swap_result.get("success"):
            st.success(swap_result["message"])
        # Clear the result after showing it once
        del st.session_state.swap_result

    # Show real-time swap status
    if "swap_in_progress" in st.session_state:
        st.warning("🔄 Swap operation in progress...")
        
    # Show any recent swap errors prominently
    if "swap_debug_history" in st.session_state:
        recent_errors = [e for e in st.session_state.swap_debug_history[-3:] if 'error' in e or e.get('operation') == 'swap_failed']
        if recent_errors:
            st.error(f"⚠️ Recent swap issue: {recent_errors[-1].get('operation', 'Unknown error')}")

    # Debug mode information and persistent debug history
    if _is_debug():
        st.warning("🔧 Debug mode active (add ?debug to URL to enable)")
        
        # Show current overrides state
        with st.expander("Current Overrides State", expanded=False):
            plan_sig = _plan_signature(settings)
            current_overrides = _get_overrides_for_plan(settings)
            st.code(f"Plan signature: {plan_sig}")
            st.code(f"Override count: {len(current_overrides) if current_overrides else 0}")
            if current_overrides:
                for date_key, override_data in list(current_overrides.items())[:10]:  # Show first 10
                    st.code(f"{date_key}: {override_data}")
        
        # Show persistent debug history
        if "swap_debug_history" in st.session_state and st.session_state.swap_debug_history:
            with st.expander("Debug History (Persistent) - Click to expand", expanded=True):
                # Show most recent entries first, limit to last 15 for readability
                recent_entries = list(reversed(st.session_state.swap_debug_history[-15:]))
                
                for i, entry in enumerate(recent_entries):
                    # Color code different operations
                    if entry['operation'] == 'swap_success':
                        st.success(f"✅ [{entry['timestamp'][-8:]}] {entry['operation']}")
                    elif entry['operation'] == 'swap_failed':
                        st.error(f"❌ [{entry['timestamp'][-8:]}] {entry['operation']}")
                    elif 'error' in entry:
                        st.error(f"⚠️ [{entry['timestamp'][-8:]}] {entry['operation']}")
                    else:
                        st.info(f"🔧 [{entry['timestamp'][-8:]}] {entry['operation']}")
                    
                    # Show details in a code block
                    details = []
                    for key, value in entry.items():
                        if key not in ['timestamp', 'operation']:
                            details.append(f"  {key}: {value}")
                    if details:
                        st.code("\n".join(details))
                    
                    # Add separator between entries
                    if i < len(recent_entries) - 1:
                        st.markdown("---")
                
                col1, col2 = st.columns([1, 3])
                with col1:
                    if st.button("Clear Debug History"):
                        st.session_state.swap_debug_history = []
                        st.rerun()
                with col2:
                    st.caption(f"Showing {len(recent_entries)} of {len(st.session_state.swap_debug_history)} total debug entries")
        
        # Add a manual debug snapshot button
        if st.button("📸 Capture Current State"):
            plan_sig = _plan_signature(settings)
            current_overrides = _get_overrides_for_plan(settings)
            if "swap_debug_history" not in st.session_state:
                st.session_state.swap_debug_history = []
            st.session_state.swap_debug_history.append({
                "timestamp": datetime.now().isoformat(),
                "operation": "manual_state_snapshot",
                "plan_signature": plan_sig,
                "override_count": len(current_overrides) if current_overrides else 0,
                "session_state_keys": list(st.session_state.keys())
            })
            st.rerun()
    
    start_date_str = settings.get("start_date")
    if not start_date_str:
        st.warning("Please set a start date to see your plan.")
        return

    # Adjust start date to the Monday of the selected week to align the plan correctly
    user_start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    # Monday is 0, Sunday is 6. Adjust to the Monday of the user's selected week.
    start_date = user_start_date - timedelta(days=user_start_date.weekday())
    
    if start_date != user_start_date:
        # This message is now conditional and only shows if an adjustment was made.
        st.info(f"Your training plan has been aligned to start on Monday, {start_date.strftime('%B %d, %Y')}.")

    plan_file = settings.get("plan_file", "run_plan.csv")
    goal_time = settings.get("goal_time", "4:00:00")

    base_plan_df = generate_training_plan(start_date, plan_file, goal_time)
    if base_plan_df.empty:
        return

    adjusted_plan_df = apply_user_plan_adjustments(base_plan_df, settings, start_date)
    
    # Add DateISO for reliable joins and overrides BEFORE applying overrides
    adjusted_plan_df['DateISO'] = pd.to_datetime(adjusted_plan_df['Date']).dt.strftime('%Y-%m-%d')
    
    # IMPORTANT: Apply overrides *after* adjustments and *after* DateISO is added
    final_plan_df = apply_plan_overrides(adjusted_plan_df, settings)
    
    # Only regenerate activity descriptions for rows that don't have overrides
    # (to avoid overwriting swapped activities)
    overrides = _get_overrides_for_plan(settings)
    if _is_debug():
        st.write(f"Debug: Found {len(overrides) if overrides else 0} overrides after applying to plan")
        if overrides:
            for date_key, override_data in list(overrides.items())[:3]:  # Show first 3
                st.write(f"  {date_key}: {override_data}")
    
    if 'Activity_Abbr' in final_plan_df.columns and 'Activity' in final_plan_df.columns:
        if overrides:
            # Only update rows that don't have overrides
            regenerated_count = 0
            for idx in final_plan_df.index:
                date_iso = final_plan_df.loc[idx, 'DateISO']
                if date_iso not in overrides:
                    # No override for this date, safe to regenerate
                    final_plan_df.loc[idx, 'Activity'] = enhance_activity_description(final_plan_df.loc[idx, 'Activity_Abbr'])
                    regenerated_count += 1
            if _is_debug():
                st.write(f"Debug: Regenerated {regenerated_count} activity descriptions, preserved {len(overrides)} overrides")
        else:
            # No overrides at all, safe to regenerate everything
            final_plan_df['Activity'] = final_plan_df['Activity_Abbr'].apply(enhance_activity_description)
            if _is_debug():
                st.write("Debug: No overrides found, regenerated all activity descriptions")
    
    # Regenerate tooltips and descriptions for all rows (they should match current Activity values)
    if 'Activity' in final_plan_df.columns:
        final_plan_df['Activity_Tooltip'] = final_plan_df.apply(
            lambda row: get_activity_tooltip(row.get('Activity_Abbr', row.get('Activity', ''))), axis=1
        )
        final_plan_df['Activity_Short_Description'] = final_plan_df['Activity'].apply(get_activity_short_description)

    # Strava data merge
    strava_connected = strava_connect()
    merged_df = final_plan_df.copy()
    
    if strava_connected:
        # Expand the date range to include recent activities around current date
        today = datetime.now().date()
        plan_start = pd.to_datetime(final_plan_df['Date'].min()).date()
        plan_end = pd.to_datetime(final_plan_df['Date'].max()).date()
        
        # Use a broader date range: from 30 days before plan start OR 30 days ago (whichever is earlier)
        # to plan end OR 30 days from today (whichever is later)
        fetch_start = min(plan_start - timedelta(days=30), today - timedelta(days=30))
        fetch_end = max(plan_end, today + timedelta(days=30))
        
        activities = get_strava_activities(start_date=fetch_start, end_date=fetch_end)
        _debug_info(f"Fetched {len(activities)} activities from Strava (range: {fetch_start} to {fetch_end})")
        if activities:
            strava_df = pd.DataFrame(activities)
            strava_df['start_date_local'] = pd.to_datetime(strava_df['start_date_local'])
            # Convert to string format to match training plan Date format
            strava_df['Date'] = strava_df['start_date_local'].dt.strftime('%Y-%m-%d')
            runs_only = strava_df[strava_df['type'] == 'Run']
            _debug_info(f"Found {len(runs_only)} running activities out of {len(strava_df)} total")
            strava_df = runs_only
            strava_df['Actual_Miles'] = (strava_df['distance'] * 0.000621371).round(2)
            strava_df['Actual_Pace_Sec'] = strava_df['moving_time'] / strava_df['Actual_Miles']
            
            daily_strava = strava_df.groupby('Date').agg(
                Actual_Miles=('Actual_Miles', 'sum'),
                Moving_Time_Sec=('moving_time', 'sum'),
                Activity_Count=('id', 'count'),
                Strava_URL=('id', lambda x: f"https://www.strava.com/activities/{x.iloc[0]}" if len(x) == 1 else None)
            ).reset_index()
            
            # Round aggregated actual miles to 2 decimal places
            daily_strava['Actual_Miles'] = daily_strava['Actual_Miles'].round(2)
            
            # Calculate weighted average pace for the day
            daily_strava['Actual_Pace'] = daily_strava.apply(
                lambda row: f"{int((row['Moving_Time_Sec'] / row['Actual_Miles']) // 60)}:{int((row['Moving_Time_Sec'] / row['Actual_Miles']) % 60):02d}" if row['Actual_Miles'] > 0 else "—",
                axis=1
            )
            
            # Rename the Date column to DateISO for consistent merging
            daily_strava['DateISO'] = daily_strava['Date']
            merged_df = pd.merge(final_plan_df, daily_strava[['DateISO', 'Actual_Miles', 'Actual_Pace', 'Strava_URL']], on='DateISO', how='left')
            actual_activities_count = len(merged_df[merged_df['Actual_Miles'] > 0])
            _debug_info(f"Merged data shows {actual_activities_count} days with actual miles > 0")
            
            # Show diagnostic if activities exist but none show up in plan
            if actual_activities_count == 0 and not daily_strava.empty:
                st.info("ℹ️ Found Strava running activities, but none match your training plan dates.")
                plan_date_range = f"{final_plan_df['DateISO'].min()} to {final_plan_df['DateISO'].max()}"
                strava_date_range = f"{daily_strava['DateISO'].min()} to {daily_strava['DateISO'].max()}"
                st.markdown(f"""
                - **Plan date range**: {plan_date_range}
                - **Strava activities date range**: {strava_date_range}
                
                Try adjusting your plan start date or check if your activities are within the plan period.
                """)
            
            merged_df['Actual_Miles'] = merged_df['Actual_Miles'].fillna(0.0)
            merged_df['Actual_Pace'] = merged_df['Actual_Pace'].fillna("—")
            merged_df['Strava_URL'] = merged_df['Strava_URL'].fillna("")
        else:
            # No activities found - provide diagnostic info
            st.info("ℹ️ Strava connected but no activities found. This could be because:")
            st.markdown("""
            - Your activities are outside the training plan date range
            - You have no running activities in Strava
            - There's a token scope issue (try reconnecting)
            """)
            merged_df['Actual_Miles'] = 0
            merged_df['Actual_Pace'] = "—"
            merged_df['Strava_URL'] = None
    else:
        merged_df['Actual_Miles'] = 0
        merged_df['Actual_Pace'] = "—"
        merged_df['Strava_URL'] = None

    # Add pace ranges using our custom pace calculation
    merged_df['Pace'] = merged_df['Activity'].apply(lambda x: get_suggested_pace(x, goal_time))
    
    # Debug: Show some pace calculations if debug mode is on
    if _is_debug() and not merged_df.empty:
        sample_activities = merged_df[['Activity', 'Pace']].head(5).values.tolist()
        _debug_info(f"Goal time: {goal_time}, Sample paces", sample_activities)

    # Add week number to the DataFrame
    merged_df['Week'] = _compute_week_index(merged_df, 'Date', start_date)

    # --- Week-by-week display ---
    total_weeks = merged_df['Week'].max() if not merged_df.empty else 0
    
    # Reset week view if plan changes
    plan_sig = _plan_signature(settings)
    if st.session_state.get("last_plan_sig") != plan_sig:
        st.session_state.current_week = 1
        st.session_state.last_plan_sig = plan_sig

    if 'current_week' not in st.session_state:
        st.session_state.current_week = 1

    if st.session_state.current_week < total_weeks:
        if st.button("Show Next Week"):
            st.session_state.current_week += 1
            st.rerun()

    # Filter to current week
    display_df_filtered = merged_df[merged_df['Week'] <= st.session_state.current_week].copy()

    # --- Weekly Summary Rows ---
    summary_rows = []
    for week_num in range(1, st.session_state.current_week + 1):
        week_df = display_df_filtered[display_df_filtered['Week'] == week_num]
        if not week_df.empty:
            last_date_of_week = pd.to_datetime(week_df['Date']).max()
            summary_date = last_date_of_week + pd.Timedelta(hours=12)
            
            summary_row = pd.DataFrame([{
                'Date': summary_date,
                'Day': '',
                'Activity': f'**Week {week_num} Summary**',
                'Plan_Miles': week_df['Plan_Miles'].sum(),
                'Actual_Miles': round(week_df['Actual_Miles'].sum(), 2),
                'Pace': '',
                'Actual_Pace': '',
                'Week': week_num,
                'DateISO': last_date_of_week.strftime('%Y-%m-%d'),
                'Activity_Tooltip': 'Weekly totals for planned and actual miles.',
                'Activity_Short_Description': 'Weekly mileage summary.',
                'Strava_URL': None
            }])
            summary_rows.append(summary_row)

    if summary_rows:
        summary_df = pd.concat(summary_rows, ignore_index=True)
        display_df_with_summaries = pd.concat([display_df_filtered, summary_df], ignore_index=True)
        display_df_with_summaries['Date_sort'] = pd.to_datetime(display_df_with_summaries['Date'])
        display_df_with_summaries = display_df_with_summaries.sort_values(by='Date_sort').reset_index(drop=True)
        display_df_with_summaries['Date'] = display_df_with_summaries['Date_sort'].dt.strftime('%Y-%m-%d')
        display_df = display_df_with_summaries
    else:
        display_df = display_df_filtered
    
    # --- AgGrid table ---
    display_df = display_df.rename(columns={
        "Activity": "Workout",
        "Plan_Miles": "Plan (mi)",
        "Actual_Miles": "Actual (mi)",
        "Pace": "Suggested Pace",
        "Actual_Pace": "Actual Pace"
    })

    column_order = ["Date", "Day", "Workout", "Plan (mi)", "Suggested Pace", "Actual (mi)", "Actual Pace"]
    # Keep the tooltip and helper columns that we need but will hide later
    display_columns = column_order + ["Activity_Short_Description", "Activity_Tooltip", "DateISO", "Week", "Date_sort", "Strava_URL", "Activity_Abbr"]
    existing_columns = [col for col in display_columns if col in display_df.columns]
    display_df = display_df[existing_columns]
    
    gb = GridOptionsBuilder.from_dataframe(display_df)

    # Disable all filters and sorting
    gb.configure_default_column(
        filterable=False, 
        sortable=False, 
        resizable=True,
        suppressMenu=True
    )

    date_renderer = JsCode("""
        class DateRenderer {
            init(params) {
                this.eGui = document.createElement('span');
                if (params.value) {
                    const parts = params.value.split('-');
                    this.eGui.innerHTML = parseInt(parts[1], 10) + '/' + parseInt(parts[2], 10);
                    
                    // Add helpful date tooltip
                    const date = new Date(params.value);
                    const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
                    this.eGui.title = date.toLocaleDateString('en-US', options);
                }
            }
            getGui() { return this.eGui; }
        }
    """)
    gb.configure_column("Date", cellRenderer=date_renderer, width=80, pinned='left')
    
    day_renderer = JsCode("""
        class DayRenderer {
            init(params) {
                this.eGui = document.createElement('span');
                this.eGui.innerHTML = params.value;
                
                // Add contextual day tooltips
                const day = params.value ? params.value.toLowerCase() : '';
                if (day.includes('mon')) {
                    this.eGui.title = 'Monday - Start the week strong!';
                } else if (day.includes('tue')) {
                    this.eGui.title = 'Tuesday - Quality workout day';
                } else if (day.includes('wed')) {
                    this.eGui.title = 'Wednesday - Mid-week training';
                } else if (day.includes('thu')) {
                    this.eGui.title = 'Thursday - Another key workout day';
                } else if (day.includes('fri')) {
                    this.eGui.title = 'Friday - Prepare for the weekend';
                } else if (day.includes('sat')) {
                    this.eGui.title = 'Saturday - Long run day';
                } else if (day.includes('sun')) {
                    this.eGui.title = 'Sunday - Recovery or long run day';
                } else {
                    this.eGui.title = params.value;
                }
            }
            getGui() { return this.eGui; }
        }
    """)
    gb.configure_column("Day", cellRenderer=day_renderer, width=100, pinned='left')

    workout_renderer = JsCode("""
        class WorkoutRenderer {
            init(params) {
                this.eGui = document.createElement('span');
                this.eGui.style.cursor = 'default';
                
                if (params.value && params.value.includes('Summary')) {
                    this.eGui.innerHTML = params.value;
                    this.eGui.title = params.data.Activity_Tooltip || params.data.Activity_Short_Description || '';
                } else {
                    // Check if this activity has a Strava URL (completed activity)
                    const stravaUrl = params.data.Strava_URL;
                    
                    if (stravaUrl) {
                        // Make it clickable for completed activities
                        this.eGui.innerHTML = params.value;
                        this.eGui.style.cursor = 'pointer';
                        this.eGui.style.color = '#22c55e';
                        this.eGui.style.textDecoration = 'underline';
                        this.eGui.title = (params.data.Activity_Tooltip || params.data.Activity_Short_Description || '') + '\\n\\n(Click to view on Strava)';
                        
                        this.eGui.onclick = () => {
                            window.open(stravaUrl, '_blank');
                        };
                    } else {
                        // Regular activity, show detailed tooltip explanation
                        this.eGui.innerHTML = params.value;
                        this.eGui.title = params.data.Activity_Tooltip || params.data.Activity_Short_Description || '';
                    }
                }
            }
            getGui() { return this.eGui; }
        }
    """)
    gb.configure_column("Workout", cellRenderer=workout_renderer, width=280, wrapText=True, autoHeight=True)
    
    # Mileage renderer with tooltips
    mileage_renderer = JsCode("""
        class MileageRenderer {
            init(params) {
                this.eGui = document.createElement('span');
                if (params.value !== null && params.value !== undefined) {
                    this.eGui.innerHTML = params.value;
                    
                    if (params.colDef.field === 'Plan (mi)') {
                        const workoutType = params.data.Workout || '';
                        this.eGui.title = `Planned distance: ${params.value} miles for ${workoutType}`;
                    } else if (params.colDef.field === 'Actual (mi)') {
                        if (params.value && params.value > 0) {
                            this.eGui.title = `Actual distance completed: ${params.value} miles (from Strava)`;
                        } else {
                            this.eGui.title = 'Distance will appear here after completing the workout';
                        }
                    }
                } else {
                    this.eGui.innerHTML = '—';
                    this.eGui.title = params.colDef.field === 'Plan (mi)' ? 
                        'No specific distance planned' : 
                        'Complete the workout to see distance';
                }
            }
            getGui() { return this.eGui; }
        }
    """)
    
    # Actual mileage renderer with green highlighting when within 1 mile of planned
    actual_mileage_renderer = JsCode("""
        class ActualMileageRenderer {
            init(params) {
                this.eGui = document.createElement('span');
                if (params.value !== null && params.value !== undefined) {
                    this.eGui.innerHTML = params.value;
                    
                    // Check if within 1 mile of planned distance
                    const actualMiles = parseFloat(params.value);
                    const plannedMiles = parseFloat(params.data['Plan (mi)']);
                    
                    if (!isNaN(actualMiles) && !isNaN(plannedMiles) && actualMiles > 0 && plannedMiles > 0) {
                        const diff = Math.abs(actualMiles - plannedMiles);
                        if (diff <= 1.0) {
                            this.eGui.style.backgroundColor = 'rgba(34, 197, 94, 0.2)';
                            this.eGui.style.color = '#22c55e';
                            this.eGui.style.fontWeight = 'bold';
                            this.eGui.style.padding = '2px 4px';
                            this.eGui.style.borderRadius = '3px';
                            this.eGui.title = `Actual distance: ${params.value} miles - within 1 mile of planned ${plannedMiles} miles!`;
                        } else {
                            this.eGui.title = `Actual distance completed: ${params.value} miles (from Strava)`;
                        }
                    } else if (params.value && params.value > 0) {
                        this.eGui.title = `Actual distance completed: ${params.value} miles (from Strava)`;
                    } else {
                        this.eGui.title = 'Distance will appear here after completing the workout';
                    }
                } else {
                    this.eGui.innerHTML = '—';
                    this.eGui.title = 'Complete the workout to see distance';
                }
            }
            getGui() { return this.eGui; }
        }
    """)
    
    gb.configure_column("Plan (mi)", cellRenderer=mileage_renderer, width=90, type=["numericColumn"], precision=1)
    gb.configure_column("Actual (mi)", cellRenderer=actual_mileage_renderer, width=90, type=["numericColumn"], precision=2)
    gb.configure_column("Suggested Pace", width=130)
    gb.configure_column("Actual Pace", width=110)

    pace_range_renderer = JsCode("""
        class PaceRangeRenderer {
            init(params) {
                this.eGui = document.createElement('span');
                if (params.value) {
                    this.eGui.innerHTML = params.value;
                    
                    // Add specific tooltips based on column and workout type
                    if (params.colDef.field === 'Suggested Pace') {
                        const workoutType = params.data.Workout || '';
                        const workoutLower = workoutType.toLowerCase();
                        
                        if (workoutLower.includes('rest')) {
                            this.eGui.title = 'Rest day - no running required';
                        } else if (workoutLower.includes('recovery')) {
                            this.eGui.title = 'Recovery pace: Very easy, comfortable effort for active recovery';
                        } else if (workoutLower.includes('easy') || workoutLower.includes('general aerobic')) {
                            this.eGui.title = 'Easy pace: Conversational effort to build aerobic base';
                        } else if (workoutLower.includes('marathon pace')) {
                            this.eGui.title = 'Marathon pace: Goal race pace to develop race rhythm';
                        } else if (workoutLower.includes('tempo') || workoutLower.includes('lactate threshold')) {
                            this.eGui.title = 'Tempo pace: Sustained, challenging effort at lactate threshold';
                        } else if (workoutLower.includes('long run')) {
                            this.eGui.title = 'Long run pace: Aerobic effort for building endurance';
                        } else if (workoutLower.includes('medium-long')) {
                            this.eGui.title = 'Medium-long run pace: Steady aerobic effort';
                        } else if (workoutLower.includes('interval') || workoutLower.includes('800')) {
                            this.eGui.title = 'VO₂ Max pace: Fast intervals at 5K-10K race pace';
                        } else if (workoutLower.includes('hill')) {
                            this.eGui.title = 'Hill repeats: Hard uphill effort with easy recovery';
                        } else {
                            this.eGui.title = 'Suggested training pace range for this workout';
                        }
                    } else if (params.colDef.field === 'Actual Pace') {
                        if (params.value && params.value !== '—') {
                            this.eGui.title = 'Your actual pace from Strava activity';
                        } else {
                            this.eGui.title = 'Pace will appear here after completing the workout';
                        }
                    }
                } else {
                    this.eGui.innerHTML = '—';
                    this.eGui.title = params.colDef.field === 'Suggested Pace' ? 
                        'No specific pace target for this workout' : 
                        'Complete the workout to see your pace';
                }
            }
            getGui() { return this.eGui; }
        }
    """)
    gb.configure_column("Suggested Pace", cellRenderer=pace_range_renderer)
    gb.configure_column("Actual Pace", cellRenderer=pace_range_renderer)

    # Hide helper columns
    for col in ["Activity_Abbr", "Activity_Tooltip", "Activity_Short_Description", "DateISO", "Week", "Date_sort", "Strava_URL"]:
        if col in display_df.columns:
            gb.configure_column(col, hide=True)

    gb.configure_selection(selection_mode="multiple", use_checkbox=True)
    
    get_row_style = JsCode("""
        function(params) {
            // Helper function to parse pace strings to seconds
            function parsePaceToSeconds(paceStr) {
                if (!paceStr || typeof paceStr !== 'string') return null;
                const parts = paceStr.split(':');
                if (parts.length === 2) {
                    const minutes = parseInt(parts[0]);
                    const seconds = parseInt(parts[1]);
                    if (!isNaN(minutes) && !isNaN(seconds)) {
                        return minutes * 60 + seconds;
                    }
                }
                return null;
            }
            
            if (params.data.Workout && params.data.Workout.includes('Summary')) {
                return { 
                    'background-color': 'rgba(100, 116, 139, 0.15)',
                    'font-weight': 'bold',
                    'border-bottom': '1px solid var(--border)',
                    'border-top': '1px solid var(--border)'
                };
            }
            
            // Make current day text bold (no green background)
            if (params.data.DateISO === new Date().toISOString().slice(0, 10)) {
                return {
                    'font-weight': 'bold'
                };
            }
            
            // Check if pace and/or miles are in range
            const actualPace = params.data['Actual Pace'];
            const suggestedPace = params.data['Suggested Pace'];
            const actualMiles = params.data['Actual (mi)'];
            const plannedMiles = params.data['Plan (mi)'];
            
            let paceInRange = false;
            let milesInRange = false;
            
            // Check pace range (±30 seconds)
            if (actualPace && suggestedPace && suggestedPace !== '—' && 
                !suggestedPace.includes('uphill') && !suggestedPace.includes('800s') && 
                !suggestedPace.includes('Mile pace') && !suggestedPace.includes('See plan')) {
                
                const actualSeconds = parsePaceToSeconds(actualPace);
                const suggestedSeconds = parsePaceToSeconds(suggestedPace);
                
                if (actualSeconds && suggestedSeconds) {
                    paceInRange = Math.abs(actualSeconds - suggestedSeconds) <= 30;
                }
            }
            
            // Check miles range (within 10%) - now handled at cell level for Actual Miles
            if (actualMiles && plannedMiles) {
                const actual = parseFloat(actualMiles);
                const planned = parseFloat(plannedMiles);
                if (!isNaN(actual) && !isNaN(planned) && planned > 0) {
                    // Miles highlighting is now handled at cell level, not row level
                    milesInRange = false; // Don't highlight entire row for miles
                }
            }
            
            // Highlight row only if pace is in range (not miles)
            if (paceInRange) {
                return {
                    'background-color': 'rgba(34, 197, 94, 0.1)',
                    'border-left': '2px solid rgba(34, 197, 94, 0.5)'
                };
            }
            
            return null;
        }
    """)

    gb.configure_grid_options(
        domLayout='autoHeight',
        rowStyle={'background': 'transparent'},
        getRowStyle=get_row_style,
        suppressHorizontalScroll=False,
        alwaysShowHorizontalScroll=False,
        suppressColumnVirtualisation=True
    )
    grid_options = gb.build()

    grid_response = AgGrid(
        display_df,
        gridOptions=grid_options,
        data_return_mode=DataReturnMode.AS_INPUT,
        update_mode=GridUpdateMode.MODEL_CHANGED,
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        fit_columns_on_grid_load=True,
        width='100%',
        key='training_plan_grid'
    )
    
    if st.session_state.get("plan_needs_refresh"):
        st.session_state.plan_needs_refresh = False

    # Get selected rows with better error handling - try multiple possible keys
    selected_rows = None
    for key in ['selected_data', 'selected_rows']:
        if key in grid_response and grid_response[key] is not None:
            selected_rows = grid_response[key]
            if _is_debug():
                _debug_info(f"Found selection data in key '{key}': {len(selected_rows) if isinstance(selected_rows, list) else 'not a list'}")
            break
    
    if selected_rows is None:
        selected_rows = []
        if _is_debug():
            _debug_info("No selection data found in grid response")
    
    # Debug: Show raw grid response if debug mode is on
    if _is_debug():
        _debug_info(f"Raw grid response keys: {list(grid_response.keys())}")
        _debug_info(f"Raw selected_rows type: {type(selected_rows)}")
    
    # Handle both list and DataFrame formats robustly
    if hasattr(selected_rows, 'empty') and hasattr(selected_rows, 'to_dict'):
        # It's a DataFrame
        if not selected_rows.empty:
            selected_rows = selected_rows.to_dict('records')
            if _is_debug():
                _debug_info(f"Converted DataFrame to {len(selected_rows)} records")
        else:
            selected_rows = []
    elif not isinstance(selected_rows, list):
        # Ensure it's a list
        selected_rows = list(selected_rows) if selected_rows else []
    
    # Ensure selected_rows contains dictionaries, not strings
    valid_selected_rows = []
    for row in selected_rows:
        if isinstance(row, dict):
            valid_selected_rows.append(row)
        elif isinstance(row, str):
            # Skip string entries - they may be from grid state issues
            if _is_debug():
                _debug_info(f"Skipping string row: {row}")
            continue
    selected_rows = valid_selected_rows
    
    # Debug: Show what's selected if debug mode is on
    _debug_info(f"Selected {len(selected_rows)} rows", [row.get('Date', 'Unknown') for row in selected_rows if isinstance(row, dict)])
    
    # Additional debug for swap logic
    if _is_debug() and selected_rows:
        for i, row in enumerate(selected_rows):
            _debug_info(f"Row {i+1} type: {type(row)}")
            if isinstance(row, dict):
                _debug_info(f"Row {i+1} keys: {list(row.keys())}")
                _debug_info(f"Row {i+1} DateISO: {row.get('DateISO', 'MISSING')}")
                _debug_info(f"Row {i+1} Date: {row.get('Date', 'MISSING')}")
    
    # --- Swap Days Button ---
    today = datetime.now().date()
    can_swap = False
    future_selected_count = 0
    
    if selected_rows and len(selected_rows) == 2:
        # Check if both selected days are current or future
        for row in selected_rows:
            if not isinstance(row, dict):
                continue
            date_str = row.get('DateISO', row.get('Date'))
            if date_str:
                try:
                    row_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    _debug_info(f"Checking date: {date_str} -> {row_date} >= {today} = {row_date >= today}")
                    if row_date >= today:
                        future_selected_count += 1
                except Exception as e:
                    _debug_info(f"Date parsing error: {e}")
        
        can_swap = future_selected_count == 2
    
    _debug_info(f"Swap logic: future_selected_count={future_selected_count}, can_swap={can_swap}")
    
    # Always show the button, but disable it when conditions aren't met
    button_disabled = not can_swap
    button_text = "Swap Days"
    if len(selected_rows) == 0:
        button_text = "Swap Days (select 2 rows)"
    elif len(selected_rows) == 1:
        button_text = "Swap Days (select 1 more row)"
    elif len(selected_rows) > 2:
        button_text = "Swap Days (select only 2 rows)"
    elif not can_swap:
        button_text = "Swap Days (past dates cannot be swapped)"
    
    swap_clicked = st.button(button_text, disabled=button_disabled, use_container_width=True)
    
    # --- Handle Swap Logic ---
    if swap_clicked and can_swap:
        row_a = selected_rows[0]
        row_b = selected_rows[1]
        
        # Safety check - ensure both rows are dictionaries
        if not isinstance(row_a, dict) or not isinstance(row_b, dict):
            st.error("Invalid row selection. Please try selecting the rows again.")
            return
        
        date_a_str = row_a.get('DateISO', row_a.get('Date'))
        date_b_str = row_b.get('DateISO', row_b.get('Date'))

        if _is_debug():
            _debug_info(f"Swap button clicked - date_a_str: {date_a_str}, date_b_str: {date_b_str}")
            
            # Store immediate debug info in session state
            if "swap_debug_history" not in st.session_state:
                st.session_state.swap_debug_history = []
            st.session_state.swap_debug_history.append({
                "timestamp": datetime.now().isoformat(),
                "operation": "swap_button_clicked",
                "date_a_str": date_a_str,
                "date_b_str": date_b_str,
                "row_a_workout": row_a.get('Workout', 'Unknown'),
                "row_b_workout": row_b.get('Workout', 'Unknown')
            })

        if date_a_str and date_b_str:
            try:
                date_a = datetime.strptime(date_a_str, '%Y-%m-%d').date()
                date_b = datetime.strptime(date_b_str, '%Y-%m-%d').date()
                
                if _is_debug():
                    _debug_info(f"Parsed dates - date_a: {date_a}, date_b: {date_b}")
                    _debug_info(f"About to call swap_plan_days with merged_df shape: {merged_df.shape}")
                    
                    # Store parsed dates info
                    st.session_state.swap_debug_history.append({
                        "timestamp": datetime.now().isoformat(),
                        "operation": "dates_parsed",
                        "date_a": str(date_a),
                        "date_b": str(date_b),
                        "merged_df_shape": str(merged_df.shape)
                    })
                
                # Set swap in progress flag
                st.session_state.swap_in_progress = True
                
                success = swap_plan_days(user_hash, settings, merged_df, date_a, date_b)
                
                # Clear the in progress flag
                if "swap_in_progress" in st.session_state:
                    del st.session_state.swap_in_progress
                if success:
                    # Store swap result in session state so it persists across reruns
                    st.session_state.swap_result = {
                        "success": True,
                        "message": f"Swapped **{row_a['Workout']}** on {date_a.strftime('%a, %b %d')} with **{row_b['Workout']}** on {date_b.strftime('%a, %b %d')}!",
                        "timestamp": datetime.now().isoformat()
                    }
                    st.session_state.plan_needs_refresh = True
                    if _is_debug():
                        _debug_info("Swap successful, storing result and triggering rerun")
                        # Store debug info in session state so it persists
                        if "swap_debug_history" not in st.session_state:
                            st.session_state.swap_debug_history = []
                        st.session_state.swap_debug_history.append({
                            "timestamp": datetime.now().isoformat(),
                            "operation": "swap_success",
                            "dates": f"{date_a} <-> {date_b}",
                            "workouts": f"{row_a['Workout']} <-> {row_b['Workout']}"
                        })
                    st.rerun()
                else:
                    st.error("Could not perform swap.")
                    if _is_debug():
                        if "swap_debug_history" not in st.session_state:
                            st.session_state.swap_debug_history = []
                        st.session_state.swap_debug_history.append({
                            "timestamp": datetime.now().isoformat(),
                            "operation": "swap_failed",
                            "dates": f"{date_a} <-> {date_b}",
                            "error": "swap_plan_days returned False"
                        })
            except Exception as e:
                st.error(f"Error performing swap: {e}")
                if _is_debug():
                    import traceback
                    _debug_info(f"Swap error: {traceback.format_exc()}")
        else:
            st.error("Could not identify dates to swap.")
    
    # --- Single row selected - Clear Override Option ---
    if selected_rows and len(selected_rows) == 1:
        st.subheader("Clear Override")
        row_x = selected_rows[0]
        
        # Safety check - ensure row is a dictionary
        if not isinstance(row_x, dict):
            st.warning("Invalid row selection. Please try selecting the row again.")
            return
            
        date_x_str = row_x.get('DateISO', row_x.get('Date'))
        if not date_x_str:
            st.warning("Could not identify date to clear.")
            return
            
        date_x = datetime.strptime(date_x_str, '%Y-%m-%d').date()
        st.write(f"Clear override for **{row_x['Workout']}** on {date_x.strftime('%a, %b %d')}?")
        if st.button("Clear This Override"):
            clear_override_day(user_hash, settings, date_x)
            st.session_state.plan_needs_refresh = True
            st.rerun()

    # --- Clear All Overrides ---
    st.subheader("Manage Overrides")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Clear All Swaps/Overrides for This Plan"):
            clear_all_overrides(user_hash, settings)
            st.session_state.plan_needs_refresh = True
            st.rerun()
    
    with col2:
        if st.button("Fix Tooltip Mismatches", help="Regenerate all tooltips to fix any mismatched descriptions"):
            # Clear all tooltips AND activity descriptions from overrides so they get regenerated
            try:
                overrides = _get_overrides_for_plan(settings)
                if overrides:
                    # Remove any tooltip and activity columns from overrides to force regeneration
                    for date_key, override_data in overrides.items():
                        if isinstance(override_data, dict):
                            override_data.pop('Activity_Tooltip', None)
                            override_data.pop('Activity_Short_Description', None)
                            # Also remove Activity descriptions so they get regenerated from Activity_Abbr
                            override_data.pop('Activity', None)
                    _save_overrides_for_plan(user_hash, settings, overrides)
                
                st.success("Tooltips and descriptions reset! The page will refresh and regenerate everything from the base activity abbreviations.")
                st.session_state.plan_needs_refresh = True
                st.rerun()
            except Exception as e:
                st.error(f"Error fixing tooltips: {e}")

if __name__ == "__main__":
    main()