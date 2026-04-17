import streamlit as st
import requests
import urllib.parse
from datetime import date, timedelta, datetime
import json
import math

# ── config ────────────────────────────────────────────────────
st.set_page_config(page_title="Marathon Planner", page_icon="🏃", layout="wide")

CLIENT_ID     = st.secrets["STRAVA_CLIENT_ID"]
CLIENT_SECRET = st.secrets["STRAVA_CLIENT_SECRET"]
REDIRECT_URI  = st.secrets["REDIRECT_URI"]

# ── plans ─────────────────────────────────────────────────────
PLANS = {
    "pfitz-18-55": dict(name="Pfitz 18/55", weeks=18, peak_mpw=55, desc="18-week, peaks at 55 mpw"),
    "pfitz-18-70": dict(name="Pfitz 18/70", weeks=18, peak_mpw=70, desc="18-week, peaks at 70 mpw"),
    "pfitz-12-55": dict(name="Pfitz 12/55", weeks=12, peak_mpw=55, desc="12-week, peaks at 55 mpw"),
    "pfitz-12-70": dict(name="Pfitz 12/70", weeks=12, peak_mpw=70, desc="12-week, peaks at 70 mpw"),
}

WORKOUT_INFO = {
    "easy":  dict(label="Easy run",           purpose="Aerobic base building and active recovery. The backbone of Pfitzinger training.", effort="Fully conversational", pace_note="60–90 sec/mi slower than goal MP"),
    "long":  dict(label="Long run",           purpose="Builds endurance, fat oxidation, and mental toughness. Most important run of the week.", effort="Comfortable aerobic effort", pace_note="45–75 sec/mi slower than goal MP"),
    "tempo": dict(label="Lactate threshold",  purpose="Raises the pace you can sustain for extended periods. Direct marathon performance benefit.", effort="Comfortably hard — few words only", pace_note="~25–30 sec/mi slower than 10K pace"),
    "vo2":   dict(label="VO2 max intervals",  purpose="Increases maximal aerobic capacity and running economy. High stress, high reward.", effort="Hard — ~5K race effort", pace_note="3K–5K race pace"),
    "race":  dict(label="Race day",           purpose="Your goal marathon. Patient first half — the race truly begins at mile 18.", effort="Goal marathon effort, disciplined", pace_note="Goal MP from the gun"),
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
    return [
        dict(w=i+1, runs=[dict(d=r["d"], t=r["t"], m=round(r["m"]*scale)) for r in wk["runs"]])
        for i, wk in enumerate(src)
    ]

def goal_pace_secs(time_str):
    parts = [int(x) for x in time_str.strip().split(":")]
    total = parts[0]*3600 + parts[1]*60 + (parts[2] if len(parts)==3 else 0)
    return round(total / 26.2)

def fmt_pace(secs_per_mile):
    m, s = divmod(round(secs_per_mile), 60)
    return f"{m}:{s:02d}/mi"

def fmt_time(secs):
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def pace_for_type(workout_type, gps):
    offsets = dict(easy=75, long=60, tempo=15, vo2=-60, race=0)
    return fmt_pace(gps + offsets.get(workout_type, 75))

def build_planned_map(plan_key, race_date_str):
    schedule = build_schedule(plan_key)
    p = PLANS[plan_key]
    race_date = date.fromisoformat(race_date_str)
    plan_start = race_date - timedelta(weeks=p["weeks"])
    planned = {}
    for wi, wk in enumerate(schedule):
        for run in wk["runs"]:
            d = plan_start + timedelta(days=wi*7 + run["d"])
            ds = d.isoformat()
            if ds != race_date_str and d < race_date:
                planned[ds] = run
    planned[race_date_str] = dict(t="race", m=26)
    return planned, plan_start.isoformat()

# ── strava oauth ──────────────────────────────────────────────
def get_auth_url():
    params = dict(
        client_id=CLIENT_ID,
        response_type="code",
        redirect_uri=REDIRECT_URI,
        scope="activity:read_all",
        approval_prompt="force",
    )
    return "https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode(params)

def exchange_code(code):
    r = requests.post("https://www.strava.com/oauth/token", json=dict(
        client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
        code=code, grant_type="authorization_code", redirect_uri=REDIRECT_URI,
    ))
    return r.json()

def refresh_token(refresh):
    r = requests.post("https://www.strava.com/oauth/token", json=dict(
        client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
        refresh_token=refresh, grant_type="refresh_token",
    ))
    return r.json()

def get_valid_token():
    ss = st.session_state
    if not ss.get("access_token"):
        return None
    exp = ss.get("token_expires_at", 0)
    if datetime.utcnow().timestamp() < exp - 60:
        return ss["access_token"]
    # refresh
    data = refresh_token(ss.get("refresh_token", ""))
    if "access_token" in data:
        ss["access_token"]      = data["access_token"]
        ss["refresh_token"]     = data.get("refresh_token", ss["refresh_token"])
        ss["token_expires_at"]  = data["expires_at"]
        return data["access_token"]
    return None

def fetch_athlete(token):
    r = requests.get("https://www.strava.com/api/v3/athlete",
                     headers={"Authorization": f"Bearer {token}"})
    return r.json()

def fetch_activities(token):
    since = int((datetime.utcnow() - timedelta(days=65)).timestamp())
    all_acts, page = [], 1
    while True:
        r = requests.get(
            f"https://www.strava.com/api/v3/athlete/activities?per_page=100&after={since}&page={page}",
            headers={"Authorization": f"Bearer {token}"}
        )
        data = r.json()
        if not isinstance(data, list) or not data:
            break
        runs = [a for a in data if a.get("type") == "Run" or a.get("sport_type") == "Run"]
        all_acts.extend(runs)
        if len(data) < 100:
            break
        page += 1
    return all_acts

# ── calendar html ─────────────────────────────────────────────
PILL_COLORS = {
    "easy":   ("#E1F5EE", "#085041"),
    "long":   ("#EEEDFE", "#3C3489"),
    "tempo":  ("#FAEEDA", "#633806"),
    "vo2":    ("#FCEBEB", "#791F1F"),
    "race":   ("#FC4C02", "#ffffff"),
    "actual": ("#dbeafe", "#1e40af"),
    "both":   ("#d1fae5", "#065f46"),
    "missed": ("#fee2e2", "#991b1b"),
}

def pill_html(label, ptype, tooltip_lines):
    bg, fg = PILL_COLORS.get(ptype, ("#eee", "#333"))
    tip = "&#10;".join(tooltip_lines)
    return (
        f'<div title="{tip}" style="'
        f'background:{bg};color:{fg};font-size:10px;padding:2px 5px;'
        f'border-radius:4px;font-weight:600;margin-top:2px;white-space:nowrap;'
        f'overflow:hidden;text-overflow:ellipsis;cursor:default;'
        f'line-height:1.5">{label}</div>'
    )

def build_calendar_html(planned_map, plan_start_str, actual_runs, goal_time, race_date_str, plan_key):
    today = date.today()
    today_str = today.isoformat()
    race_date = date.fromisoformat(race_date_str)
    plan_start = date.fromisoformat(plan_start_str)
    cal_start = today - timedelta(days=60)
    gps = goal_pace_secs(goal_time)

    # Build month range
    months = []
    cur = date(cal_start.year, cal_start.month, 1)
    end_month = date(race_date.year, race_date.month, 1)
    while cur <= end_month:
        months.append(cur)
        if cur.month == 12:
            cur = date(cur.year+1, 1, 1)
        else:
            cur = date(cur.year, cur.month+1, 1)

    MONTH_NAMES = ["January","February","March","April","May","June",
                   "July","August","September","October","November","December"]
    DOW = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]

    html_parts = []

    # legend
    legend_items = [
        ("Easy", "easy"), ("Long run", "long"), ("Tempo", "tempo"),
        ("VO2", "vo2"), ("Race", "race"), ("Actual (unplanned)", "actual"),
        ("Planned + done", "both"), ("Missed", "missed"),
    ]
    legend_html = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:1.5rem">'
    for lbl, pt in legend_items:
        bg, fg = PILL_COLORS[pt]
        legend_html += f'<span style="background:{bg};color:{fg};font-size:11px;padding:3px 8px;border-radius:4px;font-weight:600">{lbl}</span>'
    legend_html += "</div>"
    html_parts.append(legend_html)

    for month_start in months:
        yr, mo = month_start.year, month_start.month
        days_in_month = (date(yr, mo+1, 1) - timedelta(days=1)).day if mo < 12 else 31
        first_dow = month_start.weekday()  # Mon=0
        first_dow = (first_dow + 1) % 7    # convert to Sun=0

        html_parts.append(f'<div style="margin-bottom:2rem">')
        html_parts.append(f'<div style="font-size:15px;font-weight:600;margin-bottom:8px;color:#1f2937">{MONTH_NAMES[mo-1]} {yr}</div>')
        html_parts.append('<div style="display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:3px">')

        for d in DOW:
            html_parts.append(f'<div style="font-size:10px;color:#9ca3af;text-align:center;padding:4px 0">{d}</div>')

        for _ in range(first_dow):
            html_parts.append('<div></div>')

        for day in range(1, days_in_month+1):
            ds = f"{yr}-{mo:02d}-{day:02d}"
            d_obj = date(yr, mo, day)
            is_today = ds == today_str
            is_past = d_obj < today
            in_window = d_obj >= plan_start

            planned = planned_map.get(ds)
            actual_list = actual_runs.get(ds)

            border = "2px solid #FC4C02" if is_today else "1px solid #e5e7eb"
            bg_cell = "#f9fafb" if is_past and not actual_list and not planned else "#ffffff"
            day_num_color = "#FC4C02" if is_today else "#9ca3af"

            html_parts.append(
                f'<div style="min-height:56px;border-radius:6px;padding:4px 5px;'
                f'border:{border};background:{bg_cell}">'
                f'<div style="font-size:10px;color:{day_num_color};font-weight:{"600" if is_today else "400"};margin-bottom:2px">{day}</div>'
            )

            if planned and actual_list:
                act = actual_list[0]
                tip = [
                    f"{WORKOUT_INFO[planned['t']]['label']} — COMPLETED",
                    f"Planned: {planned['m']} mi @ {pace_for_type(planned['t'], gps)}",
                    f"Actual: {act['miles']:.2f} mi",
                    f"Pace: {fmt_pace(act['pace'])}",
                ]
                if act.get("hr"): tip.append(f"Avg HR: {round(act['hr'])} bpm")
                if act.get("elev"): tip.append(f"Elevation: {act['elev']} ft")
                tip.append(f"Time: {fmt_time(act['moving_time'])}")
                tip.append("")
                tip.append(WORKOUT_INFO[planned["t"]]["purpose"])
                html_parts.append(pill_html(f"{planned['m']}mi / {act['miles']:.1f}mi", "both", tip))

            elif planned and is_past and in_window:
                wi = WORKOUT_INFO.get(planned["t"], WORKOUT_INFO["easy"])
                tip = [
                    f"{wi['label']} — MISSED",
                    f"Planned: {planned['m']} mi",
                    f"Target pace: {pace_for_type(planned['t'], gps)}",
                    "",
                    wi["purpose"],
                ]
                html_parts.append(pill_html(f"Missed {planned['m']}mi", "missed", tip))

            elif planned and not is_past:
                wi = WORKOUT_INFO.get(planned["t"], WORKOUT_INFO["easy"])
                tip = [
                    wi["label"],
                    f"Distance: {planned['m']} mi",
                    f"Target pace: {pace_for_type(planned['t'], gps)}",
                    f"Effort: {wi['effort']}",
                    "",
                    wi["purpose"],
                    wi["pace_note"],
                ]
                lbl = "Race" if planned["t"] == "race" else f"{planned['m']}mi"
                html_parts.append(pill_html(lbl, planned["t"], tip))

            elif actual_list and not planned:
                act = actual_list[0]
                tip = [
                    f"Unplanned run: {act['name']}",
                    f"Distance: {act['miles']:.2f} mi",
                    f"Pace: {fmt_pace(act['pace'])}",
                ]
                if act.get("hr"): tip.append(f"Avg HR: {round(act['hr'])} bpm")
                if act.get("elev"): tip.append(f"Elevation: {act['elev']} ft")
                tip.append(f"Time: {fmt_time(act['moving_time'])}")
                html_parts.append(pill_html(f"{act['miles']:.1f}mi", "actual", tip))

            html_parts.append("</div>")

        html_parts.append("</div></div>")

    return "\n".join(html_parts)

# ── main app ──────────────────────────────────────────────────
def main():
    ss = st.session_state

    # Handle OAuth callback
    params = st.query_params
    if "code" in params and "access_token" not in ss:
        with st.spinner("Connecting to Strava..."):
            data = exchange_code(params["code"])
        if "access_token" in data:
            ss["access_token"]     = data["access_token"]
            ss["refresh_token"]    = data["refresh_token"]
            ss["token_expires_at"] = data["expires_at"]
            ss["athlete"]          = data.get("athlete", {})
            st.query_params.clear()
            st.rerun()
        else:
            st.error(f"Strava auth failed: {data.get('message','unknown error')}")
            st.stop()

    token = get_valid_token()

    # ── not connected ─────────────────────────────────────────
    if not token:
        st.markdown("## Marathon Training Planner")
        st.markdown("Connect your Strava account to load your recent runs and build a Pfitzinger training calendar.")
        auth_url = get_auth_url()
        st.markdown(
            f'<a href="{auth_url}" style="display:inline-flex;align-items:center;gap:8px;'
            f'background:#FC4C02;color:white;padding:10px 20px;border-radius:6px;'
            f'text-decoration:none;font-weight:600;font-size:14px">'
            f'<svg width="18" height="18" viewBox="0 0 24 24" fill="white">'
            f'<path d="M15.387 17.944l-2.089-4.116h-3.065L15.387 24l5.15-10.172h-3.066'
            f'm-7.008-5.599l2.836 5.598h4.172L10.463 0l-7 13.828h4.169"/></svg>'
            f'Connect with Strava</a>',
            unsafe_allow_html=True
        )
        st.stop()

    # ── load data if needed ───────────────────────────────────
    if "activities" not in ss:
        with st.spinner("Loading your Strava activities..."):
            if "athlete" not in ss or not ss["athlete"]:
                ss["athlete"] = fetch_athlete(token)
            acts = fetch_activities(token)
            run_map = {}
            for a in acts:
                key = (a.get("start_date_local") or "")[:10]
                if not key: continue
                dist_m = a.get("distance", 0)
                if dist_m == 0: continue
                run_map.setdefault(key, []).append(dict(
                    name=a.get("name", "Run"),
                    miles=dist_m / 1609.34,
                    moving_time=a.get("moving_time", 0),
                    pace=a.get("moving_time", 0) / (dist_m / 1609.34),
                    hr=a.get("average_heartrate"),
                    elev=round((a.get("total_elevation_gain") or 0) * 3.28084),
                ))
            ss["activities"] = run_map
            recent = [a for a in acts if (datetime.utcnow() - datetime.fromisoformat(a["start_date_local"][:19])).days < 28]
            ss["weekly_mpw"] = round(sum(a["distance"]/1609.34 for a in recent) / 4)

    athlete  = ss.get("athlete", {})
    act_runs = ss["activities"]
    mpw      = ss.get("weekly_mpw", 0)

    # ── sidebar ───────────────────────────────────────────────
    with st.sidebar:
        if athlete:
            name = f"{athlete.get('firstname','')} {athlete.get('lastname','')}".strip()
            pic  = athlete.get("profile","")
            if pic and "large.jpg" not in pic:
                st.image(pic, width=60)
            st.markdown(f"**{name}**")
            st.markdown("🟢 Strava connected")
            st.divider()

        st.markdown("### Race goal")
        goal_time = st.text_input("Finish time", value=ss.get("goal_time","3:30:00"), placeholder="3:30:00")
        default_race = ss.get("race_date", date.today() + timedelta(weeks=20))
        race_date = st.date_input("Race date", value=default_race, min_value=date.today() + timedelta(weeks=8))

        st.divider()
        st.markdown("### Training plan")

        auto_plan = "pfitz-18-70" if mpw >= 60 else "pfitz-18-55" if mpw >= 45 else "pfitz-12-55"
        if "selected_plan" not in ss:
            ss["selected_plan"] = auto_plan

        if mpw > 0:
            st.caption(f"Recent avg: ~{mpw} mpw (4 weeks) — auto-selected plan below")

        plan_key = st.radio(
            "Plan",
            options=list(PLANS.keys()),
            format_func=lambda k: f"{PLANS[k]['name']} — {PLANS[k]['desc']}",
            index=list(PLANS.keys()).index(ss["selected_plan"]),
            label_visibility="collapsed",
        )
        ss["selected_plan"] = plan_key
        ss["goal_time"]     = goal_time
        ss["race_date"]     = race_date

        st.divider()
        if st.button("Disconnect Strava"):
            for k in ["access_token","refresh_token","token_expires_at","athlete","activities","weekly_mpw"]:
                ss.pop(k, None)
            st.rerun()

    # ── main area ─────────────────────────────────────────────
    plan = PLANS[plan_key]
    race_date_str = race_date.isoformat()
    today = date.today()

    planned_map, plan_start_str = build_planned_map(plan_key, race_date_str)
    plan_start = date.fromisoformat(plan_start_str)

    miles_ahead   = sum(r["m"] for ds, r in planned_map.items() if ds >= today.isoformat())
    completed     = sum(1 for ds in act_runs if planned_map.get(ds) and ds < today.isoformat())
    missed        = sum(1 for ds, r in planned_map.items() if ds < today.isoformat() and ds >= plan_start_str and ds not in act_runs)

    st.markdown(f"## {plan['name']} / {goal_time}")
    st.caption(f"{plan['weeks']} weeks · race on {race_date.strftime('%B %-d, %Y')}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Weeks", plan["weeks"])
    c2.metric("Miles remaining", round(miles_ahead))
    c3.metric("Planned runs hit", completed)
    c4.metric("Missed", missed)

    st.divider()

    cal_html = build_calendar_html(planned_map, plan_start_str, act_runs, goal_time, race_date_str, plan_key)
    st.html(cal_html)

main()
