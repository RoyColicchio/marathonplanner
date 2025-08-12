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
                if "Plan" in cols:
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

    # Environment fallback
    if not client_id:
        client_id = os.getenv("STRAVA_CLIENT_ID")
    if not client_secret:
        client_secret = os.getenv("STRAVA_CLIENT_SECRET")

    # Normalize
    if isinstance(client_id, str):
        client_id = client_id.strip("\"' ")
    if isinstance(client_secret, str):
        client_secret = client_secret.strip("\"' ")

    return client_id, client_secret

# Resolve Google OAuth credentials
google_client_id = st.secrets.get("google_client_id") or os.getenv("GOOGLE_CLIENT_ID")
google_client_secret = st.secrets.get("google_client_secret") or os.getenv("GOOGLE_CLIENT_SECRET")

if not google_client_id or not google_client_secret:
    st.error("Missing Google OAuth credentials. Set google_client_id and google_client_secret in Streamlit Cloud Secrets.")
    st.stop()

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
    """Handle Google OAuth login."""
    st.title("Marathon Training Dashboard")
    st.markdown("### Sign in with your Google account to get started")

    oauth2 = get_google_oauth_component()

    # Use a redirect URI that exactly matches what's registered in Google Cloud Console
    redirect_uri = "https://marathonplanner.streamlit.app"
    if "google_redirect_uri" in st.secrets:
        redirect_uri = st.secrets.get("google_redirect_uri")

    if _is_debug():
        st.write(f"Using Google redirect URI: {redirect_uri}")
        st.write("Note: This exact URI must be registered in Google Cloud Console.")
        client_id_masked = google_client_id[:8] + "..." + google_client_id[-8:] if len(google_client_id) > 16 else google_client_id
        st.write(f"Using client ID: {client_id_masked}")

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
            try:
                st.caption(f"Secrets keys: {list(st.secrets.keys())}")
            except Exception:
                pass
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
        st.error(f"Error generating Strava auth URL: {e}")
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
            return False
    except Exception as e:
        st.error(f"Error exchanging Strava code: {e}")
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
            st.success("Successfully connected to Strava!")
            st.query_params.clear()
            st.rerun()

    if settings.get("strava_token") and settings.get("strava_expires_at"):
        if time.time() < settings["strava_expires_at"]:
            return True

    st.warning("Connect your Strava account to see your training data.")
    auth_url = get_strava_auth_url()
    if auth_url:
        st.link_button("Connect to Strava", auth_url, use_container_width=True)
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


def generate_training_plan(start_date, plan_file: str | None = None):
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
            plan_df.dropna(subset=['Plan'], inplace=True)
            plan_df = plan_df[plan_df['Plan'].str.strip() != '']
            activities = plan_df['Plan'].str.strip().copy().reset_index(drop=True)
        if len(activities):
            activities = activities[~activities.apply(is_weekly_summary)].reset_index(drop=True)

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
        def expand_abbreviations(activity_string):
            sorted_keys = sorted(activity_map.keys(), key=len, reverse=True)
            for abbr in sorted_keys:
                activity_string = re.sub(r'\b' + re.escape(abbr) + r'\b', activity_map[abbr], activity_string)
            return activity_string

        expanded_activities = activities.apply(expand_abbreviations)
        planned_miles = activities.apply(extract_primary_miles)

        num_days = len(activities)
        dates = [start_date + timedelta(days=i) for i in range(num_days)]
        days_of_week = [date.strftime("%A") for date in dates]

        new_plan_df = pd.DataFrame({
            'Date': dates,
            'Day': days_of_week,
            'Activity_Abbr': activities,
            'Activity': expanded_activities,
            'Plan_Miles': planned_miles,
        })
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
        
        # Get session overrides
        session_overrides = st.session_state.get("plan_overrides_by_plan", {}) or {}
        sess = session_overrides.get(sig, {}) or {}
        
        # Get saved overrides from settings
        by_plan = settings.get("overrides_by_plan", {}) or {}
        saved = by_plan.get(sig, {}) or {}
        
        # Combine them, session overrides win
        combined = {**saved, **sess}
        
        # Debug output
        if _is_debug():
            st.session_state["_debug_override_source"] = {
                "sig": sig,
                "session": sess,
                "saved": saved,
                "combined": combined
            }
            
        return combined
    except Exception as e:
        if _is_debug():
            st.error(f"Error getting overrides: {e}")
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
            st.session_state["_debug_saved_overrides"] = {
                "sig": sig,
                "overrides": overrides,
                "session_overrides": st.session_state["plan_overrides_by_plan"]
            }
            
    except Exception as e:
        st.error(f"Error saving overrides: {e}")


def apply_plan_overrides(plan_df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """Apply user-defined overrides to the plan DataFrame."""
    try:
        overrides = _get_overrides_for_plan(settings)
        
        if _is_debug():
            st.write("#### Applying Plan Overrides")
            st.write("**Retrieved overrides:**", overrides or "None")
            st.session_state["_debug_overrides"] = overrides
        
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
        
        # Get existing overrides and update with new swaps
        overrides = _get_overrides_for_plan(settings)
        
        if _is_debug():
            st.write("**Current overrides before swap:**", overrides)
        
        # Store the workouts swapped (b's workout goes to a's date, a's workout goes to b's date)
        overrides[date_a_str] = pb
        overrides[date_b_str] = pa
        
        if _is_debug():
            st.write("**Updated overrides after swap:**", overrides)
        
        # Save the updated overrides
        _save_overrides_for_plan(user_hash, settings, overrides)
        
        if _is_debug():
            st.write("**SWAP SUCCESS:**", f"Swapped {date_a_str} and {date_b_str}")
        
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
    st.header(f"{first_name}'s Training Plan")

    start_date = datetime.strptime(settings["start_date"], "%Y-%m-%d").date()
    goal_time = settings["goal_time"]
    plan_file = settings.get("plan_file", "run_plan.csv")
    
    # Check if we need to clear selection after a swap
    if st.session_state.get("plan_needs_refresh", False):
        st.session_state.plan_grid_sel = []
        st.session_state.pop("plan_needs_refresh", None)

    plan_df = generate_training_plan(start_date, plan_file=plan_file)
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

    gmp_sec = marathon_pace_seconds(goal_time)
    merged_df["Suggested Pace"] = merged_df["Activity_Abbr"].apply(lambda x: get_pace_range(x, gmp_sec))

    # Build display rows with week grouping and flags for styling/selection
    work = merged_df[[
        "Date", "Day", "Activity", "Suggested Pace", "Actual Miles", "Actual Pace", "Plan_Miles"
    ]].copy()
    work["Date"] = pd.to_datetime(work["Date"]).dt.date
    base_date = plan_min
    work.sort_values("Date", inplace=True)
    work["_week"] = ((pd.to_datetime(work["Date"]) - pd.to_datetime(base_date)).dt.days // 7) + 1

    display_rows = []
    today = datetime.now().date()

    for wk, grp in work.groupby("_week", sort=True):
        for _, row in grp.iterrows():
            display_rows.append({
                "DateISO": row["Date"].strftime("%Y-%m-%d"),
                "Week": int(wk),
                "is_summary": False,
                "is_today": bool(row["Date"] == today),
                "is_past": bool(row["Date"] < today),
                "Date": row["Date"],
                "Day": row["Day"],
                "Activity": row["Activity"],
                "Suggested Pace": row["Suggested Pace"],
                "Actual Miles": row.get("Actual Miles", None),
                "Actual Pace": row.get("Actual Pace", None),
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
            "Suggested Pace": "",
            "Actual Miles": float(actual_sum),
            "Actual Pace": "",
        })

    grid_df = pd.DataFrame(display_rows)
    # Format display Date and keep ISO for actions
    grid_df["Date"] = grid_df["Date"].apply(lambda d: "" if pd.isna(d) or d is None else pd.to_datetime(d).strftime("%m-%d"))

    # Placeholder for a top action bar (will render above the grid)
    top_bar = st.container()

    # Reorder columns so a visible column (Date) is first; keep technical fields at the end
    ordered_cols = [
        "Date", "Day", "Activity", "Suggested Pace", "Actual Miles", "Actual Pace",
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
        
    # Debug: show grid_df and which rows are selectable
    if _is_debug():
        st.write('grid_df for AgGrid:')
        st.dataframe(grid_df)
        # Only filter on columns we're sure exist
        selectable_filters = [(grid_df['is_summary'] == False)]
        if 'is_past' in grid_df.columns:
            selectable_filters.append(grid_df['is_past'] == False)
        if 'DateISO' in grid_df.columns:
            selectable_filters.append(grid_df['DateISO'] != '')
        selectable_rows = grid_df[np.logical_and.reduce(selectable_filters)]
        st.write(f"Selectable rows (should be today/future, not summary): {len(selectable_rows)}")
        st.dataframe(selectable_rows)

    # Configure AgGrid
    gb = GridOptionsBuilder.from_dataframe(grid_df)
    gb.configure_selection(selection_mode="multiple", use_checkbox=True, rowMultiSelectWithClick=True)
    gb.configure_column(
        "Date",
        header_name="Date ⓘ",
        headerTooltip="Calendar date (MM-DD). Use the checkbox to select rows for swapping.",
        width=100,
        checkboxSelection=True,
    )
    # Add informative tooltip to Suggested Pace column
    pace_tip = (
        "For multi-segment workouts, the pace shown reflects the working segment. "
        "Assume other miles are General Aerobic unless otherwise noted."
    )
    gb.configure_column(
        "Suggested Pace",
        header_name="Suggested Pace",
        width=200,
        headerTooltip=pace_tip,
        tooltipValueGetter=JsCode(f"function(params){{ return '{pace_tip}'; }}"),
    )
    gb.configure_grid_options(
        suppressRowClickSelection=True,
        isRowSelectable=JsCode(
            """
            function (params) {
                // Only allow selection for non-summary, non-past rows
                if (!params.data) return false;
                const isSummary = params.data.is_summary === true;
                const isPast = params.data.is_past === true;
                return !isSummary && !isPast;
            }
            """
        ),
        getRowStyle=JsCode(
            """
            function (params) {
              if (!params.data) return null;
              if (params.data.is_summary === true) {
                return {fontWeight: '700', backgroundColor: 'rgba(34,197,94,0.10)'};
              }
              if (params.data.is_today === true) {
                return {fontStyle: 'italic', backgroundColor: 'rgba(6,182,212,0.12)'};
              }
              if (params.data.is_past === true) {
                return {color: '#888', backgroundColor: 'rgba(100,100,100,0.07)'};
              }
              return null;
            }
            """
        ),
        tooltipShowDelay=100,
    )
    # Hide technical columns
    for c in ["DateISO", "Week", "is_summary", "is_today"]:
        gb.configure_column(c, hide=True)

    # Friendlier column sizing and header tooltips
    gb.configure_column("Day", header_name="Day ⓘ", headerTooltip="Day of the week for the planned workout.", width=120)
    gb.configure_column("Activity", header_name="Activity ⓘ", headerTooltip="Planned workout description for the day.", flex=2)
    # Suggested Pace already configured with tooltip above
    gb.configure_column("Actual Miles", header_name="Actual Miles ⓘ", headerTooltip="Miles recorded from Strava on that date.", width=120, type=["numericColumn", "numberColumnFilter"])
    gb.configure_column("Actual Pace", header_name="Actual Pace ⓘ", headerTooltip="Average pace from the Strava activity (min/mi).", width=120)

    grid_options = gb.build()

    st.markdown('<div class="mp-card">', unsafe_allow_html=True)
    grid_resp = AgGrid(
        grid_df,
        gridOptions=grid_options,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=True,
        height=600,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        enable_enterprise_modules=False,
        theme="streamlit",
        key="plan_grid",
    )
    st.markdown('</div>', unsafe_allow_html=True)

    # Persist selection across reruns
    if "plan_grid_sel" not in st.session_state:
        st.session_state.plan_grid_sel = []

    sel_now = []
    try:
        if isinstance(grid_resp, dict) and "selected_rows" in grid_resp:
            sr = grid_resp["selected_rows"]
            if isinstance(sr, pd.DataFrame):
                sel_now = sr.to_dict("records")
            elif isinstance(sr, list):
                sel_now = sr
    except Exception:
        sel_now = []

    # Filter out summary and past rows from selection
    sel_now = [r for r in sel_now if not r.get("is_summary") and not r.get("is_past") and r.get("DateISO")]  # must have DateISO
    # Only update session selection if non-empty, otherwise preserve previous
    if len(sel_now) > 0:
        st.session_state.plan_grid_sel = sel_now
    current_sel = st.session_state.get("plan_grid_sel", [])
    # Debug: show what is being selected
    if _is_debug():
        st.info(f"Selected rows: {current_sel}")
        
        # Show override debug info
        if st.session_state.get("_debug_overrides"):
            st.write("### Debug: Swap Information")
            st.write("**Current overrides:**", st.session_state["_debug_overrides"])
            
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

    # Render the top action bar now that we have (persisted) selection info
    with top_bar:
        c1, c2 = st.columns([1, 6])
        with c1:
            if st.button("Swap selected", use_container_width=True):
                if len(current_sel) != 2:
                    st.warning("Select exactly two days.")
                elif any(r.get("is_past") for r in current_sel):
                    st.warning("You can only swap today or future activities.")
                else:
                    # Enforce same-week
                    if int(current_sel[0].get("Week")) != int(current_sel[1].get("Week")):
                        st.warning("Please select two days from the same week.")
                    else:
                        try:
                            d1 = datetime.strptime(current_sel[0].get("DateISO"), "%Y-%m-%d").date()
                            d2 = datetime.strptime(current_sel[1].get("DateISO"), "%Y-%m-%d").date()
                            
                            # Perform the swap and clear selection
                            success = swap_plan_days(user_hash, settings, plan_df, d1, d2)
                            st.session_state.plan_grid_sel = []
                            
                            # Force reload of the page to show updated plan
                            if success:
                                st.session_state["plan_needs_refresh"] = True
                                st.toast(f"Swapped {d1.strftime('%a %m-%d')} and {d2.strftime('%a %m-%d')}")
                                st.rerun()
                            else:
                                st.error("Swap failed. Check debug output for details.")
                        except Exception as e:
                            st.error(f"Swap failed: {e}")
        with c2:
            st.caption("Tip: select two days in the same week to swap their planned workouts. Weekly summary rows are not selectable.")

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


if __name__ == "__main__":
    main()