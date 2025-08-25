import streamlit as st
import os
import sys
import numpy as np

# Enable debugging if needed - for local development only
DEBUG_SECRETS = os.getenv("DEBUG_SECRETS", "").lower() in ("true", "1", "yes")

def _is_debug():
    """Return True if diagnostics should be shown (env, secrets, or ?debug)."""
    try:
        if DEBUG_SECRETS:
            return True
        if bool(st.secrets.get("show_strava_debug", False)):
            return True
        if "debug" in st.query_params:
            return True
    except Exception:
        pass
    return False

st.set_page_config(
    page_title="Marathon Planner",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="collapsed"
)

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
        box-shadow: 0 2px 10px rgba(2,6,23,0.35);
    }
    /* Buttons */
    .stButton>button, a[data-baseweb="button"] {
        border-radius: 12px !important;
        border: 1px solid var(--border) !important;
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
import json
import hashlib
from pathlib import Path
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, GridUpdateMode, DataReturnMode
from pace_utils import marathon_pace_seconds, get_pace_range
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
            except Exception:
                # ignore unreadable files silently
                pass

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
    if name == "run_plan.csv":
        return "18 Weeks, 55 Mile/Week Peak"
    if lname in ("unofficial-pfitz-18-63.ics", "pfitz-18-63.ics"):
        return "18 Weeks, 63 Mile/Week Peak"
    if lname in ("18-weeks-50-miles-peak-hal.csv",):
        return "18 Weeks, 50 Miles/Week Peak (Hal)"
    if lname.endswith(".ics") and "63" in lname:
        return "18 Weeks, 63 Mile/Week Peak"
    return name

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

# --- Goal Time Coach helpers ---
import re as _re_gc
from math import floor as _floor

def _gc_seconds_to_hms(total_s: float) -> str:
    s = max(0, int(round(total_s)))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h}:{m:02d}:{sec:02d}"

def _gc_parse_time_str(t: str) -> int | None:
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

def training_plan_setup():
    """Handle training plan configuration."""
    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)

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
            if result and "token" in result:
                user_info = get_user_info(result["token"]["access_token"])
                if user_info:
                    st.session_state.current_user = {
                        "email": user_info.get("email"),
                        "name": user_info.get("name", user_info.get("email")),
                        "picture": user_info.get("picture", ""),
                        "access_token": result["token"]["access_token"],
                    }
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
                st.session_state.current_user = {
                    "email": dev_email.strip() or "demo@local",
                    "name": dev_name.strip() or "Demo User",
                    "picture": "",
                    "access_token": None,
                }
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
        st.error("Strava credentials not found.")
        st.info("Add [strava] client_id/client_secret to .streamlit/secrets.toml or set STRAVA_CLIENT_ID/STRAVA_CLIENT_SECRET env vars.")
        try:
            st.caption(f"Secrets keys available: {list(st.secrets.keys())}")
        except Exception:
            pass
        return False

    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)

    query_params = st.query_params
    if "code" in query_params:
        code = query_params["code"]
        if exchange_strava_code_for_token(code):
            st.success("✅ Successfully connected to your Strava account! Your Strava activities will now appear in the dashboard.")
            st.info("Your Strava data will refresh automatically when you visit the dashboard.")
            st.query_params.clear()
            st.rerun()

    if settings.get("strava_token") and settings.get("strava_expires_at"):
        if time.time() < settings["strava_expires_at"]:
            return True

    st.warning("Connect your Strava account to see your training data.")
    auth_url = get_strava_auth_url()
    if auth_url:
        st.info("⚠️ **Note:** The next step will take you to Strava's website. You'll need to log in with your **Strava** credentials, not your app credentials.")
        
        # Add a custom button with clearer instructions
        button_html = f"""
        <style>
        .strava-btn {{
            background-color: #FC4C02;
            color: white;
            padding: 10px 15px;
            border-radius: 5px;
            font-weight: bold;
            text-align: center;
            margin: 10px 0;
            display: block;
            text-decoration: none;
        }}
        </style>
        <a href="{auth_url}" class="strava-btn">
            Connect to Strava Account
            <div style="font-size: 0.8em; font-weight: normal; margin-top: 5px;">
                (You'll need to log in with your Strava credentials)
            </div>
        </a>
        """
        st.markdown(button_html, unsafe_allow_html=True)
    else:
        st.error("Unable to generate Strava authorization URL. Please check your Strava API credentials.")
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
                break
            batch = r.json() or []
            all_acts.extend(batch)
            if len(batch) < params_base.get("per_page", 30):
                break
        return all_acts
    except Exception as e:
        st.error(f"Error fetching Strava activities: {e}")
        return []


def extract_primary_miles(text: str) -> float | None:
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


def get_activity_tooltip(activity_description):
    """Generate detailed tooltip explanations based on Hal Higdon guidelines."""
    desc_lower = activity_description.lower()
    
    if 'rest' in desc_lower:
        return "Complete rest day. No running or cross-training. Rest is crucial for muscle recovery and injury prevention."
    
    elif 'easy' in desc_lower:
        return "Easy pace: 30-90 seconds per mile slower than marathon pace. Should allow comfortable conversation throughout."
    
    elif 'general aerobic' in desc_lower or 'aerobic' in desc_lower:
        return "General aerobic pace: Comfortable effort building aerobic capacity. Slightly faster than easy pace but still conversational."
    
    elif 'hill repeat' in desc_lower:
        return "Hill training: Run hard uphill (like 400m track repeat pace), jog down easy. Builds quadriceps strength and speed with less impact than track work."
    
    elif 'tempo' in desc_lower:
        return "Tempo run: Build gradually to near 10K race pace for 3-6 minutes in the middle, then ease back. Should feel 'comfortably hard' at peak."
    
    elif '800m interval' in desc_lower or '800' in desc_lower:
        return "800m intervals: Run each 800m faster than marathon pace with 400m recovery jog between. Try 'Yasso 800s' - run time matching your marathon goal (3:10 marathon = 3:10 800s)."
    
    elif '400m interval' in desc_lower or '400' in desc_lower:
        return "400m intervals: Short, fast repeats at mile pace or faster. Focus on speed and running form with full recovery between repeats."
    
    elif 'marathon pace' in desc_lower:
        return "Marathon pace: The exact pace you plan to run in your goal marathon. Practice race-day rhythm and fueling strategy."
    
    elif 'long run' in desc_lower:
        return "Long run: Run 30-90 seconds per mile slower than marathon pace. Focus on time on feet, not speed. Save energy for weekday speed work."
    
    elif 'half marathon' in desc_lower:
        return "Half marathon race: Goal race to assess fitness and practice race-day strategies. Use as a training run, not an all-out effort."
    
    elif 'marathon' in desc_lower and 'pace' not in desc_lower:
        return "Marathon race: Your goal race! Trust your training and stick to your planned pace strategy."
    
    else:
        return f"Planned workout: {activity_description}. Follow your training plan and listen to your body."


def get_suggested_pace(activity_description, goal_marathon_time_str="4:00:00"):
    """Calculate suggested pace based on activity type and goal marathon time."""
    try:
        # Parse goal marathon time
        time_parts = goal_marathon_time_str.split(":")
        goal_seconds = int(time_parts[0]) * 3600 + int(time_parts[1]) * 60 + int(time_parts[2])
        marathon_pace_seconds = goal_seconds / 26.2  # seconds per mile
        
        desc_lower = activity_description.lower()
        
        if 'rest' in desc_lower:
            return "—"
        
        elif 'easy' in desc_lower:
            # Easy: 30-90 seconds slower than marathon pace
            easy_seconds = marathon_pace_seconds + 60  # Use middle of range
            return f"{int(easy_seconds//60)}:{int(easy_seconds%60):02d}"
        
        elif 'general aerobic' in desc_lower or 'aerobic' in desc_lower:
            # GA: 15-45 seconds slower than marathon pace  
            ga_seconds = marathon_pace_seconds + 30
            return f"{int(ga_seconds//60)}:{int(ga_seconds%60):02d}"
        
        elif 'hill repeat' in desc_lower:
            return "Hard uphill effort"
        
        elif 'tempo' in desc_lower:
            # Tempo: Near 10K pace (roughly 15-30 seconds faster than marathon pace)
            tempo_seconds = marathon_pace_seconds - 20
            return f"{int(tempo_seconds//60)}:{int(tempo_seconds%60):02d}"
        
        elif '800m interval' in desc_lower or '800' in desc_lower:
            return "Yasso 800s pace"
        
        elif '400m interval' in desc_lower or '400' in desc_lower:
            return "Mile pace or faster"
        
        elif 'marathon pace' in desc_lower:
            return f"{int(marathon_pace_seconds//60)}:{int(marathon_pace_seconds%60):02d}"
        
        elif 'long run' in desc_lower:
            # Long run: 30-90 seconds slower than marathon pace
            long_seconds = marathon_pace_seconds + 60
            return f"{int(long_seconds//60)}:{int(long_seconds%60):02d}"
        
        elif 'half marathon' in desc_lower:
            # Half marathon: ~15 seconds faster than marathon pace
            hm_seconds = marathon_pace_seconds - 15
            return f"{int(hm_seconds//60)}:{int(hm_seconds%60):02d}"
        
        elif 'marathon' in desc_lower and 'pace' not in desc_lower:
            return f"{int(marathon_pace_seconds//60)}:{int(marathon_pace_seconds%60):02d}"
        
        else:
            # Default to general aerobic
            default_seconds = marathon_pace_seconds + 30
            return f"{int(default_seconds//60)}:{int(default_seconds%60):02d}"
            
    except Exception:
        return "See plan"


def enhance_activity_description(activity_string):
    """Convert raw activity string to enhanced, user-friendly description with tooltips."""
    orig = activity_string.strip()
    
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
            return f"{minutes}-Minute Tempo Run"
        return "Tempo Run"
    
    if 'x 800' in orig.lower():
        num = re.search(r'(\d+)\s*x\s*800', orig.lower())
        count = num.group(1) if num else '800m'
        return f"{count} × 800m Intervals"
    
    if 'x 400' in orig.lower():
        num = re.search(r'(\d+)\s*x\s*400', orig.lower())
        count = num.group(1) if num else '400m'
        return f"{count} × 400m Intervals"
    
    if 'pace' in orig.lower():
        miles_match = re.search(r'(\d+(?:\.\d+)?)\s*mi.*pace', orig.lower())
        if miles_match:
            miles = miles_match.group(1)
            return f"{miles} Miles at Marathon Pace"
        return "Marathon Pace Run"
    
    if 'half marathon' in orig.lower():
        return "Half Marathon Race"
    
    if 'marathon' in orig.lower() and 'half' not in orig.lower():
        return "Marathon Race"
    
    # Handle simple distance runs
    miles_match = re.search(r'(\d+(?:\.\d+)?)\s*mi(?:\s+run)?', orig.lower())
    if miles_match:
        miles = miles_match.group(1)
        if float(miles) <= 4:
            return f"{miles} Miles Easy"
        elif float(miles) <= 8:
            return f"{miles} Miles General Aerobic"
        else:
            return f"{miles} Miles Long Run"
    
    # Fallback: use basic expansion
    activity_map = {
        "GA": "General Aerobic",
        "Rec": "Recovery", 
        "MLR": "Medium-Long Run",
        "LR": "Long Run",
        "SP": "Sprints",
        "V8": "VO₂Max",
        "LT": "Lactate Threshold",
        "HMP": "Half Marathon Pace",
        "MP": "Marathon Pace",
    }
    
    sorted_keys = sorted(activity_map.keys(), key=len, reverse=True)
    for abbr in sorted_keys:
        orig = re.sub(r'\b' + re.escape(abbr) + r'\b', activity_map[abbr], orig)
    
    return orig


def generate_training_plan(start_date, plan_file: str | None = None, goal_time: str = "4:00:00"):
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

        enhanced_activities = activities.apply(enhance_activity_description)
        planned_miles = activities.apply(extract_primary_miles)

        num_days = len(activities)
        dates = [start_date + timedelta(days=i) for i in range(num_days)]
        days_of_week = [date.strftime("%A") for date in dates]

        new_plan_df = pd.DataFrame({
            'Date': dates,
            'Day': days_of_week,
            'Activity_Abbr': activities,
            'Activity': enhanced_activities,
            'Plan_Miles': planned_miles,
        })
        
        # Add activity tooltips
        new_plan_df['Activity_Tooltip'] = new_plan_df['Activity'].apply(get_activity_tooltip)
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
                idx = group[miles_col].nlargest(min(k, len(group))).index
                group.loc[idx, miles_col] = (group.loc[idx, miles_col] + (1 * sign)).clip(lower=0)
                return group
            out = out.groupby("_mp_week", group_keys=False).apply(_adjust_week)

        if "_mp_week" in out.columns:
            out.drop(columns=["_mp_week"], inplace=True)
        if date_col:
            out.sort_values(by=date_col, inplace=True, ignore_index=True)
        return out
    except Exception:
        return df


def apply_user_plan_adjustments(plan_df, settings, start_date):
    return adjust_training_plan(
        plan_df,
        start_date=start_date,
        week_adjust=int(settings.get("week_adjust", 0) or 0),
        weekly_miles_delta=int(settings.get("weekly_miles_delta", 0) or 0),
    )


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
        print(f"DEBUG: Plan signature = {signature}, from {plan_file} and {start_date}")
        
    return signature


def _get_overrides_for_plan(settings: dict) -> dict:
    """Get overrides for the current plan, combining session and saved overrides."""
    try:
        sig = _plan_signature(settings)
        
        if _is_debug():
            st.write("### _get_overrides_for_plan debug")
            st.write(f"Plan signature: {sig}")
            st.write(f"Settings contains overrides_by_plan: {'overrides_by_plan' in settings}")
            st.write(f"Settings overrides_by_plan type: {type(settings.get('overrides_by_plan', {}))}")
            st.write(f"Settings overrides_by_plan: {settings.get('overrides_by_plan', {})}")
            st.write(f"Session has plan_overrides_by_plan: {'plan_overrides_by_plan' in st.session_state}")
            if 'plan_overrides_by_plan' in st.session_state:
                st.write(f"Session plan_overrides_by_plan type: {type(st.session_state['plan_overrides_by_plan'])}")
                st.write(f"Session plan_overrides_by_plan: {st.session_state['plan_overrides_by_plan']}")
        
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
        
        if _is_debug():
            st.write(f"Session overrides: {session_overrides}")
            st.write(f"Saved overrides: {saved_overrides}")
            st.write(f"Combined overrides: {combined}")
        
        # Debug output
        if _is_debug():
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
        
        if _is_debug():
            st.write("### _save_overrides_for_plan debug")
            st.write(f"Signature: {sig}")
            st.write(f"Overrides to save: {overrides}")
            st.write(f"Settings before update: {settings.get('overrides_by_plan', {})}")
        
        # First update the settings dictionary
        by_plan = settings.get("overrides_by_plan", {}) or {}
        by_plan[sig] = overrides
        settings["overrides_by_plan"] = by_plan
        
        if _is_debug():
            st.write(f"Settings after update: {settings.get('overrides_by_plan', {})}")
        
        # Save to persistent storage
        save_user_settings(user_hash, settings)
        
        # Also update session_state for immediate UI update
        if "plan_overrides_by_plan" not in st.session_state:
            st.session_state["plan_overrides_by_plan"] = {}
            
        st.session_state["plan_overrides_by_plan"][sig] = overrides
        
        if _is_debug():
            st.write(f"Session state after update: {st.session_state.get('plan_overrides_by_plan', {})}")
        
        # Debug info
        if _is_debug():
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
        overrides = _get_overrides_for_plan(settings)
        
        if _is_debug():
            st.write("#### Applying Plan Overrides")
            st.write(f"**Retrieved overrides:** {overrides}")
            st.session_state["_debug_overrides"] = overrides
        
        # Fix for None vs empty dict confusion
        if overrides is None:
            overrides = {}
            
        if not overrides or plan_df is None or plan_df.empty:
            if _is_debug():
                st.write("**No overrides to apply or empty DataFrame**")
            return plan_df
            
        # Make a fresh copy to avoid modifying the original
        out = plan_df.copy()
        
        # Make sure Date is in proper datetime format
        if "Date" in out.columns:
            out["Date"] = pd.to_datetime(out["Date"]).dt.date
            
        # For each date with an override, apply the changes
        applied_overrides = []
        
        for date_iso, payload in overrides.items():
            try:
                if _is_debug():
                    st.write(f"**Applying override for date:** {date_iso}")
                    st.write(f"**Override payload:** {payload}")
                
                dt = datetime.strptime(str(date_iso), "%Y-%m-%d").date()
                
                # Try finding the row with DateISO first, then fall back to Date
                if "DateISO" in out.columns:
                    mask = (out["DateISO"] == date_iso)
                else:
                    mask = (out["Date"] == dt)
                
                if _is_debug():
                    st.write(f"**Matching rows found:** {mask.sum() if mask is not None else 'N/A'}")
                
                if mask is not None and mask.any():
                    # Apply each field from the override to the matching row
                    for k, v in payload.items():
                        if k in out.columns:
                            if _is_debug():
                                st.write(f"**Setting {k}={v} for date {date_iso}**")
                            out.loc[mask, k] = v
                        else:
                            if _is_debug():
                                st.write(f"**Column {k} not found in DataFrame!**")
                    applied_overrides.append(date_iso)
                else:
                    if _is_debug():
                        st.write(f"**NO MATCHING ROWS FOUND for date {date_iso}!**")
                        if "DateISO" in out.columns:
                            st.write(f"**All DateISO values in DataFrame:** {out['DateISO'].unique().tolist()[:10]}...")
                        else:
                            st.write(f"**All Date values in DataFrame:** {out['Date'].unique().tolist()[:10]}...")
            except Exception as e:
                if _is_debug():
                    st.error(f"Override apply error for {date_iso}: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                continue
                
        if _is_debug():
            st.session_state["_debug_applied_overrides"] = applied_overrides
            st.write(f"**Successfully applied overrides for dates:** {applied_overrides or 'None'}")
            
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
    try:
        if _is_debug():
            st.write("### SWAP DEBUG: Starting swap operation")
            st.write("**Swap Parameters:**", {
                "date_a": str(date_a),
                "date_b": str(date_b),
                "user_hash": user_hash[:5] + "...",  # Only show part of hash for privacy
                "settings_has_overrides": "overrides_by_plan" in settings,
                "plan_signature": _plan_signature(settings),
            })
        
        # Use merged_df with DateISO to ensure correct row selection
        df = plan_df.copy()
        df["Date"] = pd.to_datetime(df["Date"]).dt.date
        
        # Find the rows for the two selected dates
        if "DateISO" in df.columns:
            date_a_str = date_a.strftime("%Y-%m-%d")
            date_b_str = date_b.strftime("%Y-%m-%d")
            row_a = df[df["DateISO"] == date_a_str]
            row_b = df[df["DateISO"] == date_b_str]
        else:
            date_a_str = date_a.strftime("%Y-%m-%d")
            date_b_str = date_b.strftime("%Y-%m-%d")
            row_a = df[df["Date"] == date_a]
            row_b = df[df["Date"] == date_b]
            
        if row_a.empty or row_b.empty:
            error_msg = f"Selected dates are not in the plan: {date_a}, {date_b}"
            if _is_debug():
                st.write("**SWAP ERROR:**", error_msg)
                st.write("**DateISO in DataFrame:**", "DateISO" in df.columns)
                st.write("**Unique DateISO values:**", df["DateISO"].unique().tolist() if "DateISO" in df.columns else "N/A")
            raise ValueError(error_msg)
            
        # Debug output
        if _is_debug():
            st.session_state["_debug_swap_rows"] = {
                "date_a": date_a_str,
                "date_b": date_b_str,
                "row_a_found": not row_a.empty,
                "row_b_found": not row_b.empty,
                "row_a_date": row_a.iloc[0]["Date"] if not row_a.empty else None,
                "row_b_date": row_b.iloc[0]["Date"] if not row_b.empty else None,
            }
            st.write("**Found rows for dates:**", st.session_state["_debug_swap_rows"])
            
        # Only swap workout fields, not date/day
        workout_fields = ["Activity_Abbr", "Activity", "Plan_Miles"]
        
        # Extract the workout details from each row
        pa = {k: row_a.iloc[0][k] for k in workout_fields if k in row_a.columns}
        pb = {k: row_b.iloc[0][k] for k in workout_fields if k in row_b.columns}
        
        # Debug the extracted payloads
        if _is_debug():
            st.session_state["_debug_swap_payloads"] = {
                "pa": pa,
                "pb": pb
            }
            st.write("**Extracted workout details:**", st.session_state["_debug_swap_payloads"])
        
        # Get existing overrides 
        overrides = _get_overrides_for_plan(settings)
        if overrides is None:
            overrides = {}
            
        if _is_debug():
            st.write("**Current overrides before swap:**", overrides)
        
        # Store the workouts swapped (b's workout goes to a's date, a's workout goes to b's date)
        overrides[date_a_str] = pb
        overrides[date_b_str] = pa
        
        if _is_debug():
            st.write("**Updated overrides after swap:**", overrides)
        
        # Save the updated overrides
        _save_overrides_for_plan(user_hash, settings, overrides)
        
        # Also apply the overrides directly to the global plan DataFrame for immediate effect
        if 'DateISO' in plan_df.columns:
            a_mask = (plan_df['DateISO'] == date_a_str)
            b_mask = (plan_df['DateISO'] == date_b_str)
        else:
            a_mask = (plan_df['Date'] == date_a)
            b_mask = (plan_df['Date'] == date_b)
            
        if _is_debug():
            st.write(f"**Direct DataFrame update - rows found:**")
            st.write(f"- Day A ({date_a_str}): {a_mask.sum()} rows")
            st.write(f"- Day B ({date_b_str}): {b_mask.sum()} rows")
            
        # Swap the values directly in the DataFrame for each field
        for field in workout_fields:
            if field in plan_df.columns:
                try:
                    # Save the original values
                    a_val = plan_df.loc[a_mask, field].values[0] if any(a_mask) else None
                    b_val = plan_df.loc[b_mask, field].values[0] if any(b_mask) else None
                    
                    if _is_debug():
                        st.write(f"**Swapping field {field}:** {a_val} ↔ {b_val}")
                    
                    # Swap them if both exist
                    if a_val is not None and b_val is not None:
                        plan_df.loc[a_mask, field] = b_val
                        plan_df.loc[b_mask, field] = a_val
                        
                        if _is_debug():
                            st.write(f"**✓ Successfully swapped {field} in DataFrame**")
                    else:
                        if _is_debug():
                            st.write(f"**✗ Could not swap {field} - missing values**")
                except Exception as e:
                    if _is_debug():
                        st.write(f"**✗ Error swapping {field}: {e}**")
        
        if _is_debug():
            st.write("**SWAP SUCCESS:**", f"Swapped {date_a_str} and {date_b_str}")
            
            # Show the plan DataFrame with updates
            st.write("**Plan DataFrame after direct update:**")
            display_df = plan_df.copy()
            if 'DateISO' in display_df.columns:
                display_df['Date_Highlighted'] = display_df.apply(
                    lambda row: f"**{row['Date']}**" if row['DateISO'] in [date_a_str, date_b_str] else row['Date'], 
                    axis=1
                )
                display_cols = ['Date_Highlighted', 'DateISO', 'Activity', 'Plan_Miles']
                st.dataframe(display_df[display_cols])
        
        # Log success
        st.success(f"Swapped {date_a.strftime('%a %m-%d')} and {date_b.strftime('%a %m-%d')}")
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

def show_dashboard():
    """Display the main dashboard."""
    user_hash = get_user_hash(st.session_state.current_user["email"])
    settings = load_user_settings(user_hash)

    if not settings.get("goal_time") or not settings.get("start_date"):
        st.info("Please complete your training plan setup first.")
        return training_plan_setup()

    tab1, tab2 = st.tabs(["🏃 Training Plan", "⚙️ Settings"])

    with tab1:
        show_training_plan_table(settings)
    with tab2:
        training_plan_setup()


def show_training_plan_table(settings):
    """Display the training plan in a table with in-table swap controls."""
    first_name = "Your"
    try:
        user = st.session_state.get("current_user") or {}
        display_name = (user.get("name") or "").strip()
        if display_name:
            first_name = display_name.split()[0]
        elif user.get("email"):
            first_name = user["email"].split("@")[0]
    except Exception:
        pass
    # Create header with view options
    col1, col2 = st.columns([2, 1])
    with col1:
        st.header(f"{first_name}'s Training Plan")
    
    # Get user hash at the beginning of the function to avoid UnboundLocalError
    user_hash = get_user_hash(st.session_state.current_user["email"])
    
    # Initialize view preference in session state if not already set
    if "plan_view" not in st.session_state:
        st.session_state.plan_view = "full_plan"
        
    # Always using full plan view - no need for toggle
    with col2:
        # Set the view to full plan
        st.session_state.plan_view = "full_plan"
        # Add a spacer for layout balance
        st.write("")
    
    goal_time = settings.get("goal_time", "4:00:00")
    start_date = settings.get("start_date", datetime.now().strftime("%Y-%m-%d"))
    plan_file = settings.get("plan_file", "run_plan.csv")

    start_date = datetime.strptime(settings["start_date"], "%Y-%m-%d").date()
    goal_time = settings["goal_time"]
    plan_file = settings.get("plan_file", "run_plan.csv")
    
    # Check if we need to clear selection after a swap
    refresh_needed = st.session_state.get("plan_needs_refresh", False)
    force_refresh_key = st.session_state.get("_force_plan_refresh", "")
    
    if refresh_needed:
        if _is_debug():
            st.write(f"**REFRESH triggered by plan_needs_refresh: {refresh_needed}, force key: {force_refresh_key}**")
        st.session_state.plan_grid_sel = []  # Clear selection
        st.session_state.pop("plan_needs_refresh", None)  # Clear flag

    # Reload user settings each time to get latest overrides
    if refresh_needed or force_refresh_key:
        if _is_debug():
            st.write("**Reloading user settings due to refresh flag**")
        settings = load_user_settings(user_hash)  # Reload settings 

    plan_df = generate_training_plan(start_date, plan_file=plan_file, goal_time=goal_time)
    plan_df = apply_user_plan_adjustments(plan_df, settings, start_date)

    # Apply any saved per-user overrides (e.g., swaps)
    user_hash = get_user_hash(st.session_state.current_user["email"])
    
    # SUPER DEBUG: Show state before applying overrides
    if _is_debug():
        st.write("#### Debug: Plan Overrides State")
        st.write("**Settings BEFORE override application:**", {
            "user_hash": user_hash,
            "plan_file": settings.get("plan_file"),
            "start_date": settings.get("start_date"),
            "overrides_in_settings": bool(settings.get("overrides_by_plan")),
            "overrides_by_plan_count": len(settings.get("overrides_by_plan", {}) or {}),
            "plan_signature": _plan_signature(settings),
        })
        
        # Show session state for overrides
        st.write("**Session State for overrides:**", {
            "has_plan_overrides_by_plan": "plan_overrides_by_plan" in st.session_state,
            "plan_overrides_count": len(st.session_state.get("plan_overrides_by_plan", {}) or {}),
        })
        
        # Get and show overrides for the current plan
        current_overrides = _get_overrides_for_plan(settings)
        st.write("**Current plan overrides (before applying):**", current_overrides or "None")
        
    # Apply the overrides to the dataframe
    plan_df = apply_plan_overrides(plan_df, settings)

    if not plan_df.empty and "Plan_Miles" in plan_df.columns:
        def _apply_txt(row):
            pm = row.get("Plan_Miles")
            if pm is None or (isinstance(pm, float) and pd.isna(pm)) or pm == 0:
                return row
            row["Activity_Abbr"] = replace_primary_miles(row.get("Activity_Abbr", ""), pm)
            row["Activity"] = replace_primary_miles(row.get("Activity", ""), pm)
            return row
        plan_df = plan_df.apply(_apply_txt, axis=1)

    if plan_df.empty:
        return

    plan_df['Date'] = pd.to_datetime(plan_df['Date']).dt.date
    plan_min = min(plan_df['Date'])
    plan_max = max(plan_df['Date'])

    if not strava_connect():
        activities = []
    else:
        activities = get_strava_activities(start_date=plan_min, end_date=plan_max)

    runs = [a for a in activities if a.get("type") == "Run"]

    m1, m2, m3 = st.columns(3)
    m1.metric("Plan Start", plan_min.strftime("%b %d"))
    m2.metric("Plan End", plan_max.strftime("%b %d"))
    m3.metric("Goal Time", goal_time)

    if runs:
        def miles_and_pace(run):
            meters = run.get("distance", 0) or 0
            moving_time = run.get("moving_time", 0) or 0
            miles = meters * 0.000621371
            if miles > 0 and moving_time > 0:
                sec_per_mile = moving_time / miles
                minutes = int(sec_per_mile // 60)
                seconds = int(sec_per_mile % 60)
                pace = f"{minutes}:{seconds:02d}"
            else:
                pace = "N/A"
            date_str = (run.get("start_date_local") or run.get("start_date") or "").split("T")[0]
            try:
                run_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except Exception:
                run_date = None
            return run_date, round(miles, 2), pace

        rows = []
        for run in runs:
            d, m, p = miles_and_pace(run)
            if d is not None:
                rows.append({"Date": d, "Actual Miles": m, "Actual Pace": p})

        strava_df = pd.DataFrame(rows)
        merged_df = pd.merge(plan_df, strava_df, on="Date", how="left")
    else:
        merged_df = plan_df.copy()
        merged_df["Actual Miles"] = None
        merged_df["Actual Pace"] = None

    # Reapply overrides to ensure the displayed table reflects latest swaps
    merged_df = apply_plan_overrides(merged_df, settings)

    # Use the enhanced suggested pace if available, otherwise fall back to get_pace_range
    gmp_sec = marathon_pace_seconds(goal_time)
    # Always compute a range using pace_utils.get_pace_range based on enhanced Activity text
    merged_df["Suggested Pace"] = merged_df.apply(
        lambda row: get_pace_range(row.get("Activity") or row.get("Activity_Abbr", ""), gmp_sec), axis=1
    )

    # Build display rows with week grouping and flags for styling/selection
    work = merged_df[[
        "Date", "Day", "Activity", "Suggested Pace", "Actual Miles", "Actual Pace", "Plan_Miles"
    ]].copy()
    work["Date"] = pd.to_datetime(work["Date"]).dt.date
    base_date = plan_min
    work.sort_values("Date", inplace=True)
    
    # Calculate week numbers from base date
    work["_week"] = ((pd.to_datetime(work["Date"]) - pd.to_datetime(base_date)).dt.days // 7) + 1
    
    if _is_debug():
        st.write("### Week Calculation Debug")
        st.write(f"Base date: {base_date}")
        st.write(f"Date range: {plan_min} to {plan_max}")
        st.write("First 5 rows with week calculation:")
        st.dataframe(work[["Date", "_week"]].head())
        
    display_rows = []
    today = datetime.now().date()

    for wk, grp in work.groupby("_week", sort=True):
        for _, row in grp.iterrows():
            # Handle None values for actual data
            actual_miles = row.get("Actual Miles", None)
            actual_pace = row.get("Actual Pace", None)
            
            # Convert None to empty string for future days
            if row["Date"] >= today:
                actual_miles = "" if actual_miles is None else actual_miles
                actual_pace = "" if actual_pace is None else actual_pace
                
            # Improved date formatting
            display_date = row["Date"]
            date_label = display_date.strftime("%m-%d")
            delta_days = (display_date - today).days
            
            if delta_days == 0:
                date_label = "Today"
            elif delta_days == 1:
                date_label = "Tomorrow"
            elif delta_days == -1:
                date_label = "Yesterday"
            elif 1 < delta_days < 7:
                date_label = f"In {delta_days}d"
            elif -7 < delta_days < -1:
                date_label = f"{abs(delta_days)}d ago"
                
            # Calculate plan adherence for color coding
            plan_adherence = ""
            if row["Date"] < today and not pd.isna(row.get("Plan_Miles")) and not pd.isna(actual_miles) and actual_miles != "":
                plan_miles = float(row.get("Plan_Miles", 0))
                if isinstance(actual_miles, str) and actual_miles.strip():
                    try:
                        actual_miles_float = float(actual_miles)
                    except:
                        actual_miles_float = 0
                else:
                    actual_miles_float = float(actual_miles) if actual_miles else 0
                
                if plan_miles > 0:
                    adherence_ratio = actual_miles_float / plan_miles
                    if adherence_ratio >= 0.9:  # 90%+ of planned
                        plan_adherence = "great"
                    elif adherence_ratio >= 0.7:  # 70-90% of planned
                        plan_adherence = "good"
                    elif adherence_ratio > 0:  # Some miles, but less than 70%
                        plan_adherence = "low"
                    else:  # Zero miles when some were planned
                        plan_adherence = "missed"
                
            display_rows.append({
                "DateISO": row["Date"].strftime("%Y-%m-%d"),
                "Week": int(wk),
                "is_summary": False,
                "is_today": bool(row["Date"] == today),
                "is_past": bool(row["Date"] < today),
                "Date": display_date,  # Keep original date for sorting
                "DateLabel": date_label,  # Add new human-friendly label
                "Day": row["Day"],
                "Activity": row["Activity"],
                "Activity_Tooltip": row.get("Activity_Tooltip", ""),  # Add tooltip data
                "Suggested Pace": row["Suggested Pace"],
                "Actual Miles": actual_miles,
                "Actual Pace": actual_pace,
                "plan_adherence": plan_adherence,  # New field for color coding
            })
        planned_sum = pd.to_numeric(grp.get("Plan_Miles", pd.Series([])), errors="coerce").fillna(0).sum()
        actual_sum = pd.to_numeric(grp.get("Actual Miles", pd.Series([])), errors="coerce").fillna(0).sum()
        display_rows.append({
            "DateISO": "",
            "Week": int(wk),
            "is_summary": True,
            "is_today": False,
            "is_past": False,
            "Date": None,
            "Day": f"Week {int(wk)} Summary",
            "Activity": f"Total planned miles: {planned_sum:.1f} mi",
            "Activity_Tooltip": f"Weekly summary for week {int(wk)}. This shows your planned vs actual mileage for the week.",
            "Suggested Pace": "",
            "Actual Miles": float(actual_sum),
            "Actual Pace": "",
        })

    grid_df = pd.DataFrame(display_rows)
    
    # No filtering needed - always show full plan
    # (Code removed - we now always show the full plan)
        
    # Format display Date and keep ISO for actions
    grid_df["Date"] = grid_df["Date"].apply(lambda d: "" if pd.isna(d) or d is None else pd.to_datetime(d).strftime("%m-%d"))

    # The selection UI is now below the table (after AgGrid)

    # Reorder columns so a visible column (Date) is first; keep technical fields at the end
    ordered_cols = [
        "Date", "DateLabel", "Day", "Activity", "Suggested Pace", "Actual Miles", "Actual Pace",
        "DateISO", "Week", "is_summary", "is_today"
    ]
    grid_df = grid_df[ordered_cols]

    # Ensure required columns exist and fill missing with False
    for col in ['is_past', 'is_summary', 'is_today']:
        if col not in grid_df.columns:
            grid_df[col] = False
        else:
            grid_df[col] = grid_df[col].fillna(False)
            
    # Make sure DateISO column exists
    if 'DateISO' not in grid_df.columns:
        grid_df['DateISO'] = ''
        
    # Add a column to indicate which rows are selectable (for visual indicator)
    grid_df['is_selectable'] = False
    selectable_filters = [(grid_df['is_summary'] == False)]
    if 'is_past' in grid_df.columns:
        selectable_filters.append(grid_df['is_past'] == False)
    if 'DateISO' in grid_df.columns:
        selectable_filters.append(grid_df['DateISO'] != '')
    
    if len(selectable_filters) > 0:
        grid_df.loc[np.logical_and.reduce(selectable_filters), 'is_selectable'] = True
        
    # Debug: show grid_df and which rows are selectable
    if _is_debug():
        st.write('grid_df for AgGrid:')
        st.dataframe(grid_df)
        
        selectable_rows = grid_df[grid_df['is_selectable'] == True]
        st.write(f"Selectable rows (should be today/future, not summary): {len(selectable_rows)}")
        st.dataframe(selectable_rows)

    # Configure AgGrid
    gb = GridOptionsBuilder.from_dataframe(grid_df)
    # Disable selection in the grid (we use custom checkboxes below)
    gb.configure_selection(
        selection_mode="multiple",
        use_checkbox=False,
        rowMultiSelectWithClick=False,
        header_checkbox=False,
        suppressRowDeselection=True,
        suppressRowClickSelection=True,
    )
    
    # Add selection checkpoint using grid update
    if st.session_state.get("plan_grid_sel") and _is_debug():
        st.write(f"Pre-selected rows from session: {st.session_state['plan_grid_sel']}")
        
    gb.configure_column(
        "Date",
        header_name="Date ⓘ",
        headerTooltip="Calendar date (MM-DD). Use the checkbox to select rows for swapping.",
        width=100,
        checkboxSelection=True,
        pinned="left"
    )
    # Add informative tooltip to Suggested Pace column
    pace_tip = (
        "For multi-segment workouts, the pace shown reflects the working segment. "
        "Assume other miles are General Aerobic unless otherwise noted."
    )
    gb.configure_column(
        "Suggested Pace",
        header_name="Target Pace ⓘ",
        headerTooltip="Target pace range for this workout based on your marathon goal time.",
        width=160,
        # Hide on small screens (mobile)
        hide=JsCode(
        """
        function(params) {
          return window.innerWidth < 768;
        }
        """)
    )
    
    gb.configure_column("Actual Miles", 
                      header_name="Actual Miles ⓘ", 
                      headerTooltip="Miles you actually ran, pulled from your Strava activities. Compare with planned miles to track your training adherence.", 
                      width=120, 
                      type=["numericColumn", "numberColumnFilter"])
                      
    gb.configure_column("Actual Pace", 
                      header_name="Actual Pace ⓘ", 
                      headerTooltip="Your actual average pace from Strava (min/mile). Compare with target pace to gauge your workout intensity.", 
                      width=120,
                      # Hide on small screens (mobile)
                      hide=JsCode("""
                      function(params) {
                        return window.innerWidth < 640;
                      }
                      """))

    # Build grid options safely
    try:
        grid_options = gb.build()
    except Exception as e:
        if _is_debug():
            st.error(f"Error building grid options: {e}")
        grid_options = {
            'columnDefs': [
                {'field': 'DateLabel', 'headerName': 'Date', 'width': 120, 'pinned': 'left'},
                {'field': 'Day', 'headerName': 'Day', 'width': 120},
                {'field': 'Activity', 'headerName': 'Workout', 'flex': 2},
                {'field': 'Suggested Pace', 'headerName': 'Target Pace', 'width': 160},
                {'field': 'Actual Miles', 'headerName': 'Actual Miles', 'width': 120},
                {'field': 'Actual Pace', 'headerName': 'Actual Pace', 'width': 120}
            ],
            'rowSelection': 'single',
        }

    # Render the plan table with AgGrid so header tooltips work
    st.subheader("Training Plan")
    AgGrid(
        grid_df,
        gridOptions=grid_options,
        height=500,
        data_return_mode=DataReturnMode.FILTERED,
        update_mode=GridUpdateMode.NO_UPDATE,
        fit_columns_on_grid_load=True,
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
    )

    # Create a manual selection mechanism with checkboxes (below the table)
    filtered_df = grid_df[(~grid_df['is_summary']) & (~grid_df['is_past']) & (grid_df['DateISO'] != '')].copy()
    
    # Group by week for better organization
    week_groups = filtered_df.groupby('Week')
    
    # Display full plan always visible for reference
    # st.dataframe(...) removed in favor of AgGrid above
    
    # Track current selections - ensure we have no duplicates
    # First ensure plan_grid_sel is properly initialized
    if "plan_grid_sel" not in st.session_state:
        st.session_state.plan_grid_sel = []
    
    # Remove any duplicate selections by DateISO
    if len(st.session_state.plan_grid_sel) > 0:
        seen_dates = set()
        unique_selections = []
        for r in st.session_state.plan_grid_sel:
            date_iso = r.get('DateISO')
            if date_iso and date_iso not in seen_dates:
                seen_dates.add(date_iso)
                unique_selections.append(r)
        st.session_state.plan_grid_sel = unique_selections
    
    # Now get the current selections after de-duplication
    current_selections = [r.get('DateISO') for r in st.session_state.get('plan_grid_sel', [])]
    
    # Initialize swap UI visibility in session state if not already set
    if "show_swap_ui" not in st.session_state:
        st.session_state.show_swap_ui = False
    
    # Add a button to show/hide the swap functionality
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("Need to adjust this week's schedule?" if not st.session_state.show_swap_ui else "Hide schedule adjustment tools", 
                    type="secondary", use_container_width=True):
            # Toggle the state
            st.session_state.show_swap_ui = not st.session_state.show_swap_ui
    
    # Show a clear button if there are selections but swap UI is not shown
    with col2:
        if not st.session_state.show_swap_ui and len(st.session_state.get('plan_grid_sel', [])) > 0:
            if st.button("❌ Clear Selection", type="secondary", use_container_width=True):
                st.session_state.plan_grid_sel = []
                st.rerun()
    
    # Create a container for the selection UI with a clean, modern design
    selection_container = st.container()
    
    # Only show swap functionality if the button is clicked
    if st.session_state.show_swap_ui:
        with selection_container:
            # Use a card-like container for the swap functionality
            st.markdown("""
            <style>
            .swap-card {
                border: 1px solid rgba(49, 51, 63, 0.2);
                border-radius: 0.5rem;
                padding: 1rem;
                margin-bottom: 1rem;
                background-color: rgba(247, 248, 249, 0.8);
            }
            </style>
            <div class="swap-card">
            """, unsafe_allow_html=True)
            
            st.markdown("### 🔄 Swap Training Days")
            st.write("Select two days from the same week to swap their workouts.")
        
        # Force refresh session state to ensure we have the latest data
        # This is crucial when Streamlit reruns parts of the app but not others
        st.session_state.plan_grid_sel = st.session_state.get('plan_grid_sel', [])
        
        # Calculate selection count directly from session state
        selected_count = len(st.session_state.plan_grid_sel)
        
        # Add debug output
        if _is_debug():
            st.write(f"Selection count: {selected_count}")
            st.write(f"Selected items: {[item.get('DateISO') for item in st.session_state.plan_grid_sel]}")
            st.write(f"Raw selections: {st.session_state.plan_grid_sel}")
        
        # Create a clean status display
        col1, col2 = st.columns([1, 3])
        with col1:
            # Ensure this is in sync with actual data
            st.metric("Selected", f"{selected_count}/2", delta=None)
            
        with col2:
            # Only show the swap/clear buttons when we have selections
            if len(st.session_state.plan_grid_sel) == 2:
                # Check same week requirement
                try:
                    week1 = int(st.session_state.plan_grid_sel[0].get("Week", 0))
                    week2 = int(st.session_state.plan_grid_sel[1].get("Week", 0))
                    same_week = week1 == week2 and week1 > 0
                except (ValueError, TypeError):
                    same_week = False
                    
                if same_week:
                    # Create a clean swap interface
                    swap_col1, swap_col2 = st.columns([3, 1])
                    with swap_col1:
                        st.success("✓ Selected days are in the same week")
                        st.write("**Days to swap:**")
                        st.markdown(f"1. **{st.session_state.plan_grid_sel[0].get('Day')} {st.session_state.plan_grid_sel[0].get('Date')}**: {st.session_state.plan_grid_sel[0].get('Activity')}")
                        st.markdown(f"2. **{st.session_state.plan_grid_sel[1].get('Day')} {st.session_state.plan_grid_sel[1].get('Date')}**: {st.session_state.plan_grid_sel[1].get('Activity')}")
                    
                    with swap_col2:
                        # Add some spacing to align button with content
                        st.write("")
                        st.write("")
                        # Use a regular button for better UI flow
                        if st.button("Swap These Days", type="primary", key="swap_btn", use_container_width=True):
                            try:
                                # Make sure we have the user_hash for the swap operation
                                d1 = datetime.strptime(st.session_state.plan_grid_sel[0].get("DateISO"), "%Y-%m-%d").date()
                                d2 = datetime.strptime(st.session_state.plan_grid_sel[1].get("DateISO"), "%Y-%m-%d").date()
                                
                                # Perform the swap and clear selection
                                success = swap_plan_days(user_hash, settings, plan_df, d1, d2)
                                
                                # Clear selection after swap
                                st.session_state.plan_grid_sel = []
                                
                                # Force reload of the page to show updated plan
                                if success:
                                    # Set both flags to force refresh
                                    st.session_state["plan_needs_refresh"] = True
                                    st.session_state["_force_plan_refresh"] = datetime.now().isoformat()
                                    # Keep swap UI visible after refresh
                                    st.session_state.show_swap_ui = True
                                    st.toast(f"Swapped {d1.strftime('%a %m-%d')} and {d2.strftime('%a %m-%d')}")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Swap failed: {e}")
                        
                        # Add a clear button
                        if st.button("Clear Selection", key="clear_btn", use_container_width=True):
                            st.session_state.plan_grid_sel = []
                            # Keep swap UI visible
                            st.session_state.show_swap_ui = True
                            st.rerun()
                else:
                    st.error("⚠️ Selected days must be in the same week")
                    # Add a clear button
                    if st.button("Clear Selection", key="clear_btn_error", use_container_width=True):
                        st.session_state.plan_grid_sel = []
                        # Keep swap UI visible
                        st.session_state.show_swap_ui = True
                        st.rerun()
            elif selected_count > 0:
                st.info(f"Select {2-selected_count} more day{'s' if 2-selected_count > 1 else ''} from the same week to swap")
                # Add a clear button if we have any selections
                if st.button("Clear Selection", key="clear_btn_partial", use_container_width=True):
                    st.session_state.plan_grid_sel = []
                    # Keep swap UI visible
                    st.session_state.show_swap_ui = True
                    st.rerun()
        
        st.markdown("<hr>", unsafe_allow_html=True)
        
        # Show week-by-week training days that can be selected
        days_tabs = st.tabs([f"Week {week}" for week, _ in week_groups])
        
        # Track if selection has changed to avoid unnecessary reruns
        selection_changed = False
        
        for i, (week_num, group) in enumerate(week_groups):
            with days_tabs[i]:
                st.write(f"Select training days from Week {week_num}:")
                
                # Create a clean grid layout for the days
                cols = st.columns(min(3, len(group)))
                for j, (_, row) in enumerate(group.iterrows()):
                    col_idx = j % len(cols)
                    with cols[col_idx]:
                        date_iso = row['DateISO']
                        label = f"{row['Day']} {row['Date']}"
                        description = row['Activity']
                        
                        # Directly check session state for a more reliable check
                        is_selected = False
                        for item in st.session_state.get('plan_grid_sel', []):
                            if item.get('DateISO') == date_iso:
                                is_selected = True
                                break
                                
                        # Create a more compact checkbox with better formatting
                        # Add the on_change parameter to force updates
                        checkbox_key = f"sel_{date_iso}"
                        checkbox_selected = st.checkbox(
                            label, 
                            value=is_selected, 
                            key=checkbox_key,
                            help=description
                        )
                        
                        # Handle selection state changes
                        if checkbox_selected and not is_selected:
                            # Add to selection if not already there
                            if 'plan_grid_sel' not in st.session_state:
                                st.session_state.plan_grid_sel = []
                            
                            # First check if we already have 2 selections
                            if len(st.session_state.plan_grid_sel) >= 2:
                                # Too many selections - don't add more
                                st.warning(f"You can only select 2 days. Please clear your selection first.")
                                # Don't mark as changed - we're ignoring this selection
                            else:
                                # Get the full row data and add it
                                row_data = row.to_dict()
                                st.session_state.plan_grid_sel.append(row_data)
                                # Ensure swap UI remains visible after selecting an item
                                st.session_state.show_swap_ui = True
                                selection_changed = True
                                # Force rerun if needed
                                if len(st.session_state.plan_grid_sel) >= 2:
                                    st.rerun()
                            
                        elif not checkbox_selected and is_selected:
                            # Remove from selection
                            st.session_state.plan_grid_sel = [
                                r for r in st.session_state.get('plan_grid_sel', []) 
                                if r.get('DateISO') != date_iso
                            ]
                            selection_changed = True
                        
                        # Show the workout description below the checkbox
                        st.caption(description)
        
        # Close the card container
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Only rerun once after all checkboxes are processed, and only if something changed
        if selection_changed:
            # Make sure swap UI stays visible on rerun
            st.session_state.show_swap_ui = True
            
            # Force a full state refresh to ensure consistent UI
            selected_count_final = len(st.session_state.get('plan_grid_sel', []))
            
            # Check if we've reached exactly 2 selections after the changes
            if selected_count_final == 2:
                # Don't rerun immediately - let the user see both selections
                st.success("Two days selected! Use the buttons above to swap or clear.")
            elif selected_count_final == 1:
                # Only one day selected, provide guidance but don't rerun
                st.info("Select one more day from the same week to swap")
            else:
                # No selections or invalid number, we can rerun
                st.rerun()
    
    # Get the current selection from session state
    current_sel = st.session_state.get('plan_grid_sel', [])
    
    # Debug info (only show in sidebar if _is_debug is active)
    if _is_debug():
        st.info(f"Selected rows (persisted in session): {current_sel}")
        
        # Show override debug info
        if st.session_state.get("_debug_overrides") is not None:
            st.write("### Debug: Swap Information")
            st.write("**Current overrides (processed):**", st.session_state["_debug_overrides"])
            
        if st.session_state.get("_debug_override_source"):
            st.write("**Override sources:**", st.session_state["_debug_override_source"])
            
        if st.session_state.get("_debug_applied_overrides"):
            st.write("**Applied to dates:**", st.session_state["_debug_applied_overrides"])
            
        if st.session_state.get("_debug_swap_rows"):
            st.write("**Last swap rows:**", st.session_state["_debug_swap_rows"])
            
        if st.session_state.get("_debug_swap_payloads"):
            st.write("**Last swap payloads:**", st.session_state["_debug_swap_payloads"])
            
        if st.session_state.get("_debug_saved_overrides"):
            st.write("**Last saved overrides:**", st.session_state["_debug_saved_overrides"])
                
            # This section used to contain swap_button handling code
            # It has been replaced by the swap_selected button in the new interface
        # This section used to contain the helper text for the old selection method
        # Now replaced by inline helper text in the new interface

    if _is_debug():
        with st.expander("Strava connection details"):
            user_hash = get_user_hash(st.session_state.current_user["email"])
            s = load_user_settings(user_hash)
            st.write({
                "token_present": bool(s.get("strava_token")),
                "expires_at": s.get("strava_expires_at"),
                "scope": s.get("strava_scope"),
                "athlete_id": s.get("strava_athlete_id"),
                "activities_returned": len(activities) if isinstance(activities, list) else 0,
            })


def main():
    """Main application logic."""
    if not st.session_state.current_user:
        google_login()
        return

    show_header()
    show_dashboard()