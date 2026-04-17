import streamlit as st
import requests
import urllib.parse
from datetime import date, timedelta, datetime

st.set_page_config(page_title="Marathon Planner", page_icon="🏃", layout="wide")

CLIENT_ID     = st.secrets["STRAVA_CLIENT_ID"]
CLIENT_SECRET = st.secrets["STRAVA_CLIENT_SECRET"]
REDIRECT_URI  = st.secrets["REDIRECT_URI"]

PLANS = {
    "pfitz-18-55": dict(name="Pfitz 18/55", weeks=18, peak_mpw=55, desc="18-week, peaks at 55 mpw"),
    "pfitz-18-70": dict(name="Pfitz 18/70", weeks=18, peak_mpw=70, desc="18-week, peaks at 70 mpw"),
    "pfitz-12-55": dict(name="Pfitz 12/55", weeks=12, peak_mpw=55, desc="12-week, peaks at 55 mpw"),
    "pfitz-12-70": dict(name="Pfitz 12/70", weeks=12, peak_mpw=70, desc="12-week, peaks at 70 mpw"),
}

BASE_18_55 = [
    dict(w=1,  runs=[dict(d=1,t="easy",m=7), dict(d=3,t="easy",m=8), dict(d=4,t="tempo",m=9), dict(d=6,t="easy",m=5), dict(d=0,t="long",m=13)]),
    dict(w=2,  runs=[dict(d=1,t="easy",m=8), dict(d=3,t="easy",m=8), dict(d=4,t="vo2",m=9),   dict(d=6,t="easy",m=5), dict(d=0,t="long",m=15)]),
    dict(w=3,  runs=[dict(d=1,t="easy",m=9), dict(d=2,t="easy",m=6), dict(d=3,t="tempo",m=10),dict(d=5,t="easy",m=5), dict(d=0,t="long",m=17)]),
    dict(w=4,  runs=[dict(d=1,t="easy",m=7), dict(d=3,t="easy",m=7), dict(d=4,t="easy",m=8),  dict(d=6,t="easy",m=4), dict(d=0,t="long",m=14)]),
    dict(w=5,  runs=[dict(d=1,t="easy",m=9), dict(d=2,t="easy",m=6), dict(d=3,t="tempo",m=11),dict(d=5,t="easy",m=5), dict(d=0,t="long",m=18)]),
    dict(w=6,  runs=[dict(d=1,t="easy",m=9), dict(d=2,t="easy",m=6), dict(d=3,t="vo2",m=10),  dict(d=5,t="easy",m=6), dict(d=0,t="long",m=17)]),
    dict(w=7,  runs=[dict(d=1,t="easy",m=9), dict(d=2,t="easy",m=6), dict(d=3,t="tempo",m=11),dict(d=5,t="easy",m=6), dict(d=0,t="long",m=19)]),
    dict(w=8,  runs=[dict(d=1,t="easy",m=7), dict(d=3,t="easy",m=8), dict(d=4,t="easy",m=8),  dict(d=6,t="easy",m=5), dict(d=0,t="long",m=15)]),
    dict(w=9,  runs=[dict(d=1,t="easy",m=10),dict(d=2,t="easy",m=6), dict(d=3,t="vo2",m=11),  dict(d=5,t="easy",m=6), dict(d=0,t="long",m=20)]),
    dict(w=10, runs=[dict(d=1,t="easy",m=10),dict(d=2,t="easy",m=6), dict(d=3,t="tempo",m=12),dict(d=5,t="easy",m=6), dict(d=0,t="long",m=20)]),
    dict(w=11, runs=[dict(d=1,t="easy",m=10),dict(d=2,t="easy",m=7), dict(d=3,t="vo2",m=12),  dict(d=5,t="easy",m=7), dict(d=0,t="long",m=20)]),
    dict(w=12, runs=[dict(d=1,t="easy",m=8), dict(d=3,t="easy",m=9), dict(d=4,t="tempo",m=9), dict(d=6,t="easy",m=5), dict(d=0,t="long",m=16)]),
    dict(w=13, runs=[dict(d=1,t="easy",m=10),dict(d=2,t="easy",m=7), dict(d=3,t="tempo",m=12),dict(d=5,t="easy",m=7), dict(d=0,t="long",m=20)]),
    dict(w=14, runs=[dict(d=1,t="easy",m=10),dict(d=2,t="easy",m=7), dict(d=3,t="vo2",m=12),  dict(d=5,t="easy",m=7), dict(d=0,t="long",m=20)]),
    dict(w=15, runs=[dict(d=1,t="easy",m=10),dict(d=2,t="easy",m=7), dict(d=3,t="tempo",m=13),dict(d=5,t="easy",m=7), dict(d=0,t="long",m=20)]),
    dict(w=16, runs=[dict(d=1,t="easy",m=8), dict(d=3,t="easy",m=9), dict(d=4,t="easy",m=8),  dict(d=6,t="easy",m=4), dict(d=0,t="long",m=14)]),
    dict(w=17, runs=[dict(d=1,t="easy",m=8), dict(d=3,t="tempo",m=8),dict(d=4,t="easy",m=6),  dict(d=6,t="easy",m=4), dict(d=0,t="long",m=12)]),
    dict(w=18, runs=[dict(d=1,t="easy",m=6), dict(d=3,t="easy",m=5), dict(d=4,t="easy",m=4),  dict(d=6,t="easy",m=3)]),
]

def build_schedule(plan_key):
    p = PLANS[plan_key]
    scale = p["peak_mpw"] / 55
    src = BASE_18_55[6:] if p["weeks"] == 12 else BASE_18_55
    return [dict(w=i+1, runs=[dict(d=r["d"],t=r["t"],m=round(r["m"]*scale)) for r in wk["runs"]]) for i,wk in enumerate(src)]

def goal_pace_secs(time_str):
    parts = [int(x) for x in (time_str or "3:30:00").strip().split(":")]
    total = parts[0]*3600 + parts[1]*60 + (parts[2] if len(parts)==3 else 0)
    return round(total / 26.2)

def fmt_pace(spm):
    spm = max(1, round(spm))
    m, s = divmod(spm, 60)
    return f"{m}:{s:02d}/mi"

def fmt_time(secs):
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def build_planned_map(plan_key, race_date_str):
    schedule = build_schedule(plan_key)
    p = PLANS[plan_key]
    race_date = date.fromisoformat(race_date_str)
    plan_start = race_date - timedelta(weeks=p["weeks"])
    planned = {}
    for wi, wk in enumerate(schedule):
        for run in wk["runs"]:
            d = plan_start + timedelta(days=wi*7+run["d"])
            ds = d.isoformat()
            if ds != race_date_str and d < race_date:
                planned[ds] = run
    planned[race_date_str] = dict(t="race", m=26)
    return planned, plan_start.isoformat()

# ── structured segments ───────────────────────────────────────
def fmt_range(lo, hi):
    """Format a pace range e.g. 7:40–8:15/mi"""
    return f"{fmt_pace(lo)}–{fmt_pace(hi)}"

def workout_segments(wtype, total_miles, gps):
    easy_p  = fmt_range(gps + 60, gps + 90)   # 60–90 sec/mi slower than MP
    long_p  = fmt_range(gps + 45, gps + 75)   # 45–75 sec/mi slower than MP
    tempo_p = fmt_range(gps + 10, gps + 20)   # ~15 sec/mi slower than MP (LT)
    vo2_p   = fmt_range(gps - 70, gps - 50)   # ~60 sec/mi faster than MP
    mp_p    = fmt_pace(gps)
    rec_p   = fmt_range(gps + 80, gps + 105)  # very easy recovery jog

    if wtype == "easy":
        return [("Full run", f"{total_miles} mi", easy_p, "Conversational effort throughout — you should be able to speak full sentences")]

    elif wtype == "long":
        easy_m = round(total_miles * 0.75, 1)
        mp_m   = round(total_miles - easy_m, 1)
        return [
            ("Easy portion", f"{easy_m} mi", long_p, "Relaxed aerobic effort"),
            ("Final portion (optional)", f"{mp_m} mi", mp_p, "Finish at marathon pace only if feeling strong — skip if fatigued"),
        ]

    elif wtype == "tempo":
        wu = min(2.0, round(total_miles * 0.20, 1))
        cd = min(2.0, round(total_miles * 0.20, 1))
        lt = round(total_miles - wu - cd, 1)
        return [
            ("Warmup", f"{wu} mi", easy_p, "Easy effort, gradually loosening up"),
            ("Lactate threshold", f"{lt} mi", tempo_p, "Comfortably hard — labored breathing, few words. This is the key effort"),
            ("Cooldown", f"{cd} mi", easy_p, "Easy effort, flush the legs"),
        ]

    elif wtype == "vo2":
        wu = min(2.0, round(total_miles * 0.18, 1))
        cd = min(2.0, round(total_miles * 0.18, 1))
        interval_block = round(total_miles - wu - cd, 1)
        hard_m = round(interval_block * 0.60, 1)
        rec_m  = round(interval_block * 0.40, 1)
        # Estimate rep count based on total hard miles
        if hard_m <= 3.0:
            rep_str = "5×1000m or 4×1200m"
        elif hard_m <= 4.5:
            rep_str = "5×1200m or 6×1000m"
        else:
            rep_str = "6×1200m or 8×1000m"
        return [
            ("Warmup", f"{wu} mi", easy_p, "Easy jog — get loose, strides optional"),
            (f"Intervals — work ({rep_str})", f"{hard_m} mi", vo2_p, "5K race effort. Hard but controlled — not an all-out sprint"),
            ("Intervals — recovery jogs", f"{rec_m} mi", rec_p, "~400m easy jog between each rep. Full recovery before next interval"),
            ("Cooldown", f"{cd} mi", easy_p, "Easy jog home — shake out the legs"),
        ]

    elif wtype == "race":
        return [
            ("Miles 1–13.1 (first half)", "13.1 mi", mp_p, "Disciplined and patient — resist the crowd and adrenaline"),
            ("Miles 13.1–18 (second half, early)", "4.9 mi", mp_p, "Stay locked in. This stretch decides the race"),
            ("Miles 18–22 (the wall zone)", "4 mi", mp_p, "Dig deep. Shorten stride, stay relaxed, keep turnover high"),
            ("Miles 22–26.2 (finish)", "4.2 mi", fmt_pace(gps - 10), "Give what you have — controlled aggression"),
        ]

    return [("Full run", f"{total_miles} mi", fmt_pace(gps + 75), "")]

# ── pill styles ───────────────────────────────────────────────
PILL_STYLE = {
    "easy":   ("rgba(93,202,165,0.15)",  "#085041", "#5DCAA5"),
    "long":   ("rgba(155,143,232,0.15)", "#3C3489", "#9b8fe8"),
    "tempo":  ("rgba(232,168,37,0.15)",  "#633806", "#e8a825"),
    "vo2":    ("rgba(224,87,87,0.15)",   "#791F1F", "#e05757"),
    "race":   ("#FC4C02",                "#ffffff", "#FC4C02"),
    "actual": ("rgba(91,163,232,0.15)",  "#0C447C", "#5ba3e8"),
    "both":   ("rgba(93,202,165,0.2)",   "#065f46", "#5DCAA5"),
    "missed": ("rgba(224,87,87,0.12)",   "#991b1b", "#e05757"),
}
WTYPE_LABEL = dict(easy="Easy run", long="Long run", tempo="Lactate threshold", vo2="VO2 max", race="Race day")
WTYPE_PURPOSE = dict(
    easy="Aerobic base building and active recovery.",
    long="Builds endurance, fat oxidation, and mental toughness. The most important run of the week.",
    tempo="Raises lactate threshold — the pace you can sustain for extended periods.",
    vo2="Increases maximal aerobic capacity. High stress, high reward.",
    race="Your goal marathon. Patient first half — the race truly begins at mile 18.",
)

def seg_table(segments):
    rows = ""
    for name, dist, pace, note in segments:
        rows += f"""
          <tr>
            <td style="padding:5px 10px 5px 0;color:#ccc;font-size:11px;white-space:nowrap;vertical-align:top">{name}</td>
            <td style="padding:5px 6px;color:#fff;font-family:monospace;font-size:11px;white-space:nowrap;vertical-align:top">{dist}</td>
            <td style="padding:5px 0 5px 6px;color:#FC4C02;font-family:monospace;font-size:11px;white-space:nowrap;vertical-align:top">{pace}</td>
          </tr>
          <tr><td colspan="3" style="padding:0 0 6px 0;color:#555;font-size:10px;font-style:italic;line-height:1.4">{note}</td></tr>
        """
    return f'<table style="width:100%;border-collapse:collapse">{rows}</table>'

def make_tooltip(mode, wtype, planned_miles, gps, actual=None):
    label   = WTYPE_LABEL.get(wtype, "Run") if wtype else (actual or {}).get("name","Run")
    purpose = WTYPE_PURPOSE.get(wtype, "")
    status_map = dict(planned="#5ba3e8", both="#5DCAA5", missed="#e05757", actual="#5ba3e8")
    status_lbl = dict(planned="Upcoming", both="Completed", missed="Missed", actual="Unplanned")
    sc = status_map.get(mode, "#aaa")
    sl = status_lbl.get(mode, "")

    body = ""

    if mode in ("planned", "both", "missed") and wtype:
        segs = workout_segments(wtype, planned_miles, gps)
        body += f"""
        <div style="font-size:13px;color:#aaa;margin-bottom:10px">{planned_miles} mi planned</div>
        <div style="font-size:10px;color:#555;margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em">Workout structure</div>
        {seg_table(segs)}"""

    if mode == "both" and actual:
        body += f"""
        <div style="border-top:1px solid #2a2a2a;margin-top:10px;padding-top:10px">
        <div style="font-size:10px;color:#555;margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em">Your actual run</div>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Distance</td><td style="color:#fff;font-family:monospace;font-size:11px">{actual['miles']:.2f} mi</td></tr>
          <tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Avg pace</td><td style="color:#FC4C02;font-family:monospace;font-size:11px">{fmt_pace(actual['pace'])}</td></tr>
          {"" if not actual.get("hr") else f'<tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Avg HR</td><td style="color:#fff;font-family:monospace;font-size:11px">{round(actual["hr"])} bpm</td></tr>'}
          {"" if not actual.get("elev") else f'<tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Elevation</td><td style="color:#fff;font-family:monospace;font-size:11px">{actual["elev"]} ft</td></tr>'}
          <tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Time</td><td style="color:#fff;font-family:monospace;font-size:11px">{fmt_time(actual['moving_time'])}</td></tr>
        </table></div>"""

    if mode == "actual" and actual:
        body += f"""
        <table style="width:100%;border-collapse:collapse;margin-top:8px">
          <tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Distance</td><td style="color:#fff;font-family:monospace;font-size:11px">{actual['miles']:.2f} mi</td></tr>
          <tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Avg pace</td><td style="color:#FC4C02;font-family:monospace;font-size:11px">{fmt_pace(actual['pace'])}</td></tr>
          {"" if not actual.get("hr") else f'<tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Avg HR</td><td style="color:#fff;font-family:monospace;font-size:11px">{round(actual["hr"])} bpm</td></tr>'}
          {"" if not actual.get("elev") else f'<tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Elevation</td><td style="color:#fff;font-family:monospace;font-size:11px">{actual["elev"]} ft</td></tr>'}
          <tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Time</td><td style="color:#fff;font-family:monospace;font-size:11px">{fmt_time(actual['moving_time'])}</td></tr>
        </table>"""

    html = f"""
    <div style="background:#111;border:1px solid #2a2a2a;border-radius:10px;padding:14px 16px;width:290px;font-family:system-ui,sans-serif">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <div style="font-size:15px;font-weight:600;color:#fff">{label}</div>
        <div style="font-size:10px;color:{sc};background:{sc}22;padding:2px 8px;border-radius:20px;font-weight:600">{sl}</div>
      </div>
      <div style="font-size:11px;color:#555;line-height:1.5;margin-bottom:8px">{purpose if mode != "actual" else ""}</div>
      {body}
    </div>"""
    return html

def tooltip_css():
    return """
<style>
.tip-wrap{position:relative;display:block}
.tip-pill{font-size:10px;padding:2px 6px;border-radius:4px;font-weight:600;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:default;line-height:1.6;display:block}
.tip-box{display:none;position:absolute;z-index:9999;left:0;top:110%;min-width:290px;max-width:320px;pointer-events:none}
.tip-wrap:hover .tip-box{display:block}
</style>"""

def pill_html(label, ptype, tooltip_html):
    bg, fg, _ = PILL_STYLE.get(ptype, PILL_STYLE["easy"])
    return f'''
<div class="tip-wrap">
  <div class="tip-pill" style="background:{bg};color:{fg}">{label}</div>
  <div class="tip-box">{tooltip_html}</div>
</div>'''  

def day_cell(ds, planned, actuals, today_str, plan_start_str, gps):
    is_today = ds == today_str
    is_past  = ds < today_str
    in_win   = ds >= plan_start_str
    border   = "2px solid #FC4C02" if is_today else "1px solid #e5e7eb"
    bg       = "#f9fafb" if (is_past and not actuals and not planned) else "#fff"
    nc       = "#FC4C02" if is_today else "#9ca3af"
    nw       = "600" if is_today else "400"
    day_num  = int(ds.split("-")[2])

    inner = f'<div style="font-size:10px;color:{nc};font-weight:{nw};margin-bottom:3px">{day_num}</div>'

    if planned and actuals:
        act = actuals[0]
        tip = make_tooltip("both", planned["t"], planned["m"], gps, actual=act)
        inner += pill_html(f"{planned['m']}mi / {act['miles']:.1f}mi", "both", tip)
    elif planned and is_past and in_win:
        tip = make_tooltip("missed", planned["t"], planned["m"], gps)
        inner += pill_html(f"Missed {planned['m']}mi", "missed", tip)
    elif planned and not is_past:
        tip = make_tooltip("planned", planned["t"], planned["m"], gps)
        lbl = "Race day" if planned["t"] == "race" else f"{planned['m']}mi"
        inner += pill_html(lbl, planned["t"], tip)
    elif actuals and not planned:
        act = actuals[0]
        tip = make_tooltip("actual", None, act["miles"], gps, actual=act)
        inner += pill_html(f"{act['miles']:.1f}mi", "actual", tip)

    return f'<div style="min-height:60px;border-radius:7px;padding:5px 6px;border:{border};background:{bg}">{inner}</div>'

def render_week(ws, planned_map, act_runs, plan_start_str, gps, is_current):
    today_str = date.today().isoformat()
    DOWS = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]
    hbg  = "#fff8f5" if is_current else "#fff"
    hbdr = "2px solid #FC4C02" if is_current else "1px solid #e5e7eb"
    lbl  = f"Week of {ws.strftime('%b %-d')}" + (" · current week" if is_current else "")

    plan_mi = sum(planned_map[(ws+timedelta(days=i)).isoformat()]["m"]
                  for i in range(7) if (ws+timedelta(days=i)).isoformat() in planned_map)
    act_mi  = sum(sum(r["miles"] for r in act_runs.get((ws+timedelta(days=i)).isoformat(),[]))
                  for i in range(7))

    plan_badge = f'Planned <b>{plan_mi} mi</b>' if plan_mi else ""
    act_badge  = f'Actual <b style="color:#FC4C02">{act_mi:.1f} mi</b>' if act_mi else ""
    badges = " &nbsp;·&nbsp; ".join(x for x in [plan_badge, act_badge] if x)

    dow_headers = "".join(f'<div style="font-size:10px;color:#9ca3af;text-align:center;padding:2px 0">{d}</div>' for d in DOWS)
    cells = "".join(day_cell((ws+timedelta(days=i)).isoformat(), planned_map.get((ws+timedelta(days=i)).isoformat()),
                             act_runs.get((ws+timedelta(days=i)).isoformat()), today_str, plan_start_str, gps)
                    for i in range(7))

    return f"""
    <div style="background:{hbg};border:{hbdr};border-radius:10px;padding:12px 14px;margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:13px;font-weight:600;color:#374151">{lbl}</div>
        <div style="font-size:12px;color:#6b7280">{badges}</div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px">
        {dow_headers}{cells}
      </div>
    </div>"""

# ── oauth ─────────────────────────────────────────────────────
def get_auth_url():
    return "https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode(dict(
        client_id=CLIENT_ID, response_type="code", redirect_uri=REDIRECT_URI,
        scope="activity:read_all", approval_prompt="force"))

def exchange_code(code):
    return requests.post("https://www.strava.com/oauth/token", json=dict(
        client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
        code=code, grant_type="authorization_code", redirect_uri=REDIRECT_URI)).json()

def do_refresh(ref):
    return requests.post("https://www.strava.com/oauth/token", json=dict(
        client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
        refresh_token=ref, grant_type="refresh_token")).json()

def get_valid_token():
    ss = st.session_state
    if not ss.get("access_token"): return None
    if datetime.utcnow().timestamp() < ss.get("token_expires_at", 0) - 60:
        return ss["access_token"]
    data = do_refresh(ss.get("refresh_token",""))
    if "access_token" in data:
        ss["access_token"] = data["access_token"]
        ss["refresh_token"] = data.get("refresh_token", ss["refresh_token"])
        ss["token_expires_at"] = data["expires_at"]
        return data["access_token"]
    return None

def fetch_activities(token):
    since = int((datetime.utcnow()-timedelta(days=65)).timestamp())
    all_acts, page = [], 1
    while True:
        r = requests.get(f"https://www.strava.com/api/v3/athlete/activities?per_page=100&after={since}&page={page}",
                         headers={"Authorization": f"Bearer {token}"}).json()
        if not isinstance(r, list) or not r: break
        all_acts.extend(a for a in r if a.get("type")=="Run" or a.get("sport_type")=="Run")
        if len(r) < 100: break
        page += 1
    return all_acts

# ── main ──────────────────────────────────────────────────────
def main():
    ss = st.session_state
    params = st.query_params

    if "code" in params and "access_token" not in ss:
        with st.spinner("Connecting to Strava..."):
            data = exchange_code(params["code"])
        if "access_token" in data:
            ss["access_token"] = data["access_token"]
            ss["refresh_token"] = data["refresh_token"]
            ss["token_expires_at"] = data["expires_at"]
            ss["athlete"] = data.get("athlete", {})
            st.query_params.clear()
            st.rerun()
        else:
            st.error(f"Auth failed: {data.get('message','unknown')}")
            st.stop()

    token = get_valid_token()

    if not token:
        st.markdown("## Marathon Training Planner")
        st.markdown("Connect Strava to load your runs and build a Pfitzinger training calendar.")
        st.markdown(
            f'<a href="{get_auth_url()}" style="display:inline-flex;align-items:center;gap:8px;'
            f'background:#FC4C02;color:white;padding:10px 20px;border-radius:6px;'
            f'text-decoration:none;font-weight:600;font-size:14px">'
            f'<svg width="18" height="18" viewBox="0 0 24 24" fill="white">'
            f'<path d="M15.387 17.944l-2.089-4.116h-3.065L15.387 24l5.15-10.172h-3.066'
            f'm-7.008-5.599l2.836 5.598h4.172L10.463 0l-7 13.828h4.169"/></svg>'
            f'Connect with Strava</a>', unsafe_allow_html=True)
        st.stop()

    if "activities" not in ss:
        with st.spinner("Loading Strava activities..."):
            if not ss.get("athlete"):
                ss["athlete"] = requests.get("https://www.strava.com/api/v3/athlete",
                                              headers={"Authorization":f"Bearer {token}"}).json()
            acts = fetch_activities(token)
            rm = {}
            for a in acts:
                k = (a.get("start_date_local") or "")[:10]
                if not k or not a.get("distance"): continue
                rm.setdefault(k,[]).append(dict(
                    name=a.get("name","Run"), miles=a["distance"]/1609.34,
                    moving_time=a.get("moving_time",0),
                    pace=a.get("moving_time",0)/(a["distance"]/1609.34),
                    hr=a.get("average_heartrate"),
                    elev=round((a.get("total_elevation_gain") or 0)*3.28084)))
            ss["activities"] = rm
            recent = [a for a in acts if (datetime.utcnow()-datetime.fromisoformat(a["start_date_local"][:19])).days<28]
            ss["weekly_mpw"] = round(sum(a["distance"]/1609.34 for a in recent)/4)

    athlete = ss.get("athlete", {})
    act_runs = ss["activities"]
    mpw = ss.get("weekly_mpw", 0)

    with st.sidebar:
        if athlete:
            name = f"{athlete.get('firstname','')} {athlete.get('lastname','')}".strip()
            pic  = athlete.get("profile","")
            c1,c2 = st.columns([1,3])
            with c1:
                if pic and "large.jpg" not in pic: st.image(pic, width=48)
            with c2:
                st.markdown(f"**{name}**")
                st.markdown("🟢 Connected")
            st.divider()
        st.markdown("### Race goal")
        goal_time = st.text_input("Finish time", value=ss.get("goal_time","3:30:00"), placeholder="3:30:00")
        default_race = ss.get("race_date", date.today()+timedelta(weeks=20))
        race_date = st.date_input("Race date", value=default_race, min_value=date.today()+timedelta(weeks=8))
        st.divider()
        st.markdown("### Training plan")
        auto = "pfitz-18-70" if mpw>=60 else "pfitz-18-55" if mpw>=45 else "pfitz-12-55"
        if "selected_plan" not in ss: ss["selected_plan"] = auto
        if mpw > 0: st.caption(f"Recent avg: ~{mpw} mpw")
        plan_key = st.radio("Plan", options=list(PLANS.keys()),
                            format_func=lambda k: f"{PLANS[k]['name']} — {PLANS[k]['desc']}",
                            index=list(PLANS.keys()).index(ss["selected_plan"]),
                            label_visibility="collapsed")
        ss["selected_plan"] = plan_key
        ss["goal_time"] = goal_time
        ss["race_date"] = race_date
        st.divider()
        if st.button("Disconnect Strava"):
            for k in ["access_token","refresh_token","token_expires_at","athlete","activities","weekly_mpw"]:
                ss.pop(k,None)
            st.rerun()

    plan = PLANS[plan_key]
    race_date_str = race_date.isoformat()
    today = date.today()
    today_str = today.isoformat()
    gps = goal_pace_secs(goal_time)

    planned_map, plan_start_str = build_planned_map(plan_key, race_date_str)
    plan_start = date.fromisoformat(plan_start_str)

    miles_ahead = sum(r["m"] for ds,r in planned_map.items() if ds >= today_str)
    completed   = sum(1 for ds in act_runs if planned_map.get(ds) and ds < today_str)
    missed      = sum(1 for ds in planned_map if ds < today_str and ds >= plan_start_str and ds not in act_runs)

    st.markdown(f"## {plan['name']} &nbsp;·&nbsp; {goal_time} goal")
    st.caption(f"{plan['weeks']} weeks · race on {race_date.strftime('%B %-d, %Y')}")

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Weeks", plan["weeks"])
    c2.metric("Miles remaining", round(miles_ahead))
    c3.metric("Planned runs hit", completed)
    c4.metric("Missed", missed)
    st.divider()

    # Build week list: 60 days back (aligned to Sunday) through race date
    cal_start = today - timedelta(days=60)
    cal_start -= timedelta(days=(cal_start.weekday()+1)%7)
    all_weeks = []
    w = cal_start
    race_date_obj = date.fromisoformat(race_date_str)
    while w <= race_date_obj:
        all_weeks.append(w)
        w += timedelta(weeks=1)

    # Find current week
    cur_idx = next((i for i,ws in enumerate(all_weeks) if ws <= today < ws+timedelta(weeks=1)), 0)

    if "week_offset" not in ss: ss["week_offset"] = 0
    WINDOW = 4
    total = len(all_weeks)
    start_idx = max(0, min(cur_idx + ss["week_offset"], total - WINDOW))

    nc1, nc2, nc3 = st.columns([1,4,1])
    with nc1:
        if st.button("← Earlier"):
            ss["week_offset"] -= WINDOW
            st.rerun()
    with nc2:
        wa = all_weeks[start_idx]
        wb = all_weeks[min(start_idx+WINDOW-1, total-1)]
        st.markdown(f'<div style="text-align:center;color:#6b7280;font-size:13px">{wa.strftime("%b %-d")} – {(wb+timedelta(days=6)).strftime("%b %-d, %Y")}</div>', unsafe_allow_html=True)
    with nc3:
        if st.button("Later →"):
            ss["week_offset"] += WINDOW
            st.rerun()

    col_j, _ = st.columns([1,3])
    with col_j:
        if st.button("Jump to today", type="secondary"):
            ss["week_offset"] = 0
            st.rerun()

    # Legend
    legend_items = [("Easy","easy"),("Long run","long"),("Tempo","tempo"),("VO2","vo2"),("Race","race"),
                    ("Actual (unplanned)","actual"),("Planned + done","both"),("Missed","missed")]
    leg = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 16px">'
    for lbl,pt in legend_items:
        bg,fg,_ = PILL_STYLE[pt]
        leg += f'<span style="background:{bg};color:{fg};font-size:11px;padding:2px 8px;border-radius:4px;font-weight:600">{lbl}</span>'
    leg += "</div>"
    st.html(leg)

    cal_html = tooltip_css()
    for i in range(WINDOW):
        idx = start_idx + i
        if idx >= total: break
        ws = all_weeks[idx]
        we = ws + timedelta(days=6)
        cal_html += render_week(ws, planned_map, act_runs, plan_start_str, gps, ws <= today <= we)
    st.html(cal_html)

main()
