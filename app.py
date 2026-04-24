import streamlit as st
import requests
import urllib.parse
from datetime import date, timedelta, datetime

st.set_page_config(page_title="Marathon Planner", page_icon="🏃", layout="wide")

CLIENT_ID     = st.secrets["STRAVA_CLIENT_ID"]
CLIENT_SECRET = st.secrets["STRAVA_CLIENT_SECRET"]
REDIRECT_URI  = st.secrets["REDIRECT_URI"]

PLANS = {
    "pfitz-18-55":  dict(kind="pfitz", name="Pfitz 18/55", weeks=18, peak_mpw=55, desc="18-week, peaks at 55 mpw"),
    "pfitz-18-70":  dict(kind="pfitz", name="Pfitz 18/70", weeks=18, peak_mpw=70, desc="18-week, peaks at 70 mpw"),
    "pfitz-12-55":  dict(kind="pfitz", name="Pfitz 12/55", weeks=12, peak_mpw=55, desc="12-week, peaks at 55 mpw"),
    "pfitz-12-70":  dict(kind="pfitz", name="Pfitz 12/70", weeks=12, peak_mpw=70, desc="12-week, peaks at 70 mpw"),
    "me-gale-70":   dict(kind="me", me_plan="gale",    weeks=18, peak_mpw=70, name="ME Gale 70",    desc="Marathon Excellence — 18-week Gale, peaks at 70 mpw"),
    "me-gale-80":   dict(kind="me", me_plan="gale",    weeks=18, peak_mpw=80, name="ME Gale 80",    desc="Marathon Excellence — 18-week Gale, peaks at 80 mpw"),
    "me-tornado-85":dict(kind="me", me_plan="tornado", weeks=18, peak_mpw=85, name="ME Tornado 85", desc="Marathon Excellence — 18-week Tornado, peaks at 85 mpw"),
    "me-tornado-95":dict(kind="me", me_plan="tornado", weeks=18, peak_mpw=95, name="ME Tornado 95", desc="Marathon Excellence — 18-week Tornado, peaks at 95 mpw"),
}

# ── Marathon Excellence plans (John Davis) ──────────────────
# Each week: (primary_workout, secondary_workout_or_None, weekend_workout, gale_70_mi, gale_80_mi)
# For Gale and Tornado, indexes 3 and 4 are the two mileage variants
ME_GALE = [
    ("6 mi Kenyan-style progression run",                            "8 × 3 min at 90–92% 5k w/ 1 min jog",             "9–10 × 2 min at 100% 5k w/ 1.5 min jog",                                  50, 55),
    ("7 mi Kenyan-style progression run",                            "6 mi at 85% 5k",                                  "5 mi easy + 3 sets of: 1.5 mi at 88–90% 5k, 0.5 mi moderate",            55, 60),
    ("4 × (3-2-1 min at 98-100-102% 5k w/ 1-1-2 min jog)",           "7 × 4 min at 90–92% 5k w/ 1 min jog",             "12–13 mi at 80% 5k through hills",                                        60, 65),
    ("7 mi at 85% 5k",                                               None,                                              "14–15 mi easy through hills",                                             50, 55),
    ("6 × 5 min at 90–92% 5k w/ 1 min jog",                          "8 × 1 km at 95% 5k w/ 2 min jog",                 "8 mi Kenyan-style progression w/ fast finish",                            60, 67),
    ("8 mi at 85% 5k",                                               "8 × 800m at 100% 5k w/ 2–3 min walk/jog",         "14–15 mi at 80% 5k",                                                      64, 72),
    ("5 × 1 mi at 95% 5k w/ 3 min jog",                              "6–7 × (1200m at 90–92% 5k, 400m at 80% 5k)",     "16–18 mi easy through hills",                                             68, 76),
    ("9–10 mi at 100% MP",                                           None,                                              "4 × 2 km at 108–110% MP w/ 3–4 min jog",                                  55, 63),
    ("5 × (1600m at 105–107% MP, 400m at 95–98% MP)",                None,                                              "16–18 mi at 90–92% MP",                                                   70, 80),
    ("3 × (2 km at 108% MP, 2 min jog, 1 km at 110% MP, 5 min walk/jog)", None,                                         "10–11 mi at 100% MP",                                                     70, 80),
    ("9–10 × (1 km at 105% MP, 1 km at 90% MP)",                     None,                                              "18–20 mi at 90–92% MP",                                                   70, 80),
    ("3 × 3 km at 108–110% MP w/ 4–5 min walk/jog",                  None,                                              "8 × (2 km at 100% MP, 1 km at 90% MP)",                                   58, 68),
    ("6–7 × (2 km at 105% MP, 1 km at 90% MP)",                      None,                                              "5 mi at 90%; 5 mi at 92%; 5 mi at 94%; 3–5 mi at 96% MP",                 70, 80),
    ("12–15 × 500m at 108–110% MP w/ 30–45 sec walk",                None,                                              "6 × (3 km at 100% MP, 1 km at 90% MP)",                                   68, 73),
    ("3.5–5.5 mi at 105% MP",                                        None,                                              "20–21 mi at 95% MP",                                                      63, 68),
    ("8 mi Kenyan-style progression run",                            None,                                              "5 × (4 km at 100% MP, 1 km at 90% MP)",                                   63, 68),
    ("7–8 × (1 km at 103–105% MP, 1 km at 92–94% MP)",               None,                                              "5–6 × 1200m at 107–110% MP w/ 2–3 min jog",                               55, 60),
    ("5–6 × 4 min at 103–106% MP w/ 1 min jog",                      None,                                              "Marathon",                                                                26, 26),
]

ME_TORNADO = [
    ("7 mi Kenyan-style progression run",                            "8–9 × 3 min at 90–92% 5k w/ 45 sec jog",          "7 mi easy + 5 mi progressing moderate to 90% 5k + 1 mi easy",            60, 65),
    ("7 mi at 85% 5k",                                               "10 × 2 min at 100–102% 5k w/ 1.5 min jog",        "8 mi Kenyan-style progression run",                                      65, 70),
    ("8 × 1 km at 95% 5k w/ 2 min jog",                              "8 mi at 85% 5k",                                  "13–14 mi at 80% 5k through rolling hills",                               70, 76),
    ("2 sets of 4-3-2-1 min at 96-98-100-102% 5k w/ 1 min mod / 2–3 min jog", None,                                      "7–8 × 4 min at 90–92% 5k w/ 1 min jog",                                  60, 65),
    ("5 × 1 mi at 95% 5k w/ 3 min jog",                              "9–10 mi at 85% 5k",                               "16–18 mi easy through rolling hills",                                    72, 78),
    ("3-2-1-3-2-1 km at 86–88% 5k w/ 2 min walk",                    "7 × (1200m at 90–92% 5k, 400m at 80% 5k)",        "15–16 mi at 80% 5k through rolling hills",                               78, 84),
    ("3 × (2 km at 108% MP, 2 min jog, 1 km at 110–112% MP, 4–5 min jog)", None,                                         "10–11 mi at 100% MP",                                                    83, 90),
    ("6 × (1600m at 105–107% MP, 400m at 95–98% MP)",                None,                                              "4-1, 3-1, 2-1, 1-1 km at 101–103% / 105% MP w/ 2 min walk between all",  75, 82),
    ("5 × 2 km at 108–110% MP w/ 4 min jog",                         None,                                              "17–19 mi at 90–92% MP through rolling hills",                            85, 95),
    ("AM: 7 × 1 km at 103–106% MP w/ 1 min jog / PM: 12 × 500m at 108–110% MP w/ 30 sec walk", None,                     "12–13 mi at 100% MP",                                                    85, 95),
    ("10 × (1 km at 105% MP, 1 km at 90–92% MP)",                    None,                                              "5-5-5-(3 to 5) mi at 90-92-94-96% MP",                                   85, 95),
    ("AM: 5–6 × 2 km at 103% MP w/ 2 min walk / PM: 4 × 500m at 108–110% MP w/ 30 sec walk; 4 min rest; 3–5 km at 108–110% MP", None, "6 × (3 km at 100% MP, 1 km at 90% MP)",                                  80, 90),
    ("4–5 × 3 km at 103–105% MP w/ 2–3 min walk",                    None,                                              "20–22 mi at 95% MP",                                                     74, 82),
    ("AM: 3-2-1-1 km at 102–106% MP w/ 2 min walk / PM: 12–15 × 400m at 108–110% MP w/ 25 sec walk", None,               "6 × (4 km at 100% MP, 1 km at 90% MP)",                                  78, 83),
    ("8–10 × 3 min at 104–107% MP w/ 30 sec jog",                    None,                                              "7-6-5-(2 to 4) mi at 92-94-96-98% MP",                                   73, 83),
    ("12 × 500m at 108–110% MP w/ 30 sec walk",                      None,                                              "6-5-4-3-2-1 km at 98–102% w/ 1 km at 90% MP",                            70, 81),
    ("8 × (1 km at 103–105% MP, 1 km at 92–94% MP)",                 None,                                              "2 × 2 km at 107% MP; 2–4 × 1 km at 108–110% MP w/ 3 min jog",            63, 70),
    ("6–8 × 3 min at 105–107% MP w/ 45 sec jog",                     None,                                              "Marathon",                                                               26, 26),
]

ME_SCHEDULES = dict(gale=ME_GALE, tornado=ME_TORNADO)

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
    if p.get("kind") == "me":
        return build_me_schedule(p)
    scale = p["peak_mpw"] / 55
    src = BASE_18_55[6:] if p["weeks"] == 12 else BASE_18_55
    return [dict(w=i+1, runs=[dict(d=r["d"],t=r["t"],m=round(r["m"]*scale)) for r in wk["runs"]]) for i,wk in enumerate(src)]

def build_me_schedule(plan_meta):
    """Build Marathon Excellence week structure.
    Day convention: 0=Sun, 1=Mon, ..., 6=Sat. We use:
      Mon (d=1): rest (no run)
      Tue (d=2): primary workout
      Wed (d=3): easy
      Thu (d=4): secondary workout if present, else easy
      Fri (d=5): easy
      Sat (d=6): easy
      Sun (d=0): weekend workout (long)
    Easy miles are distributed to hit the weekly target.
    """
    sched_key = plan_meta["me_plan"]
    variant = 0 if plan_meta["peak_mpw"] in (70, 85) else 1
    raw = ME_SCHEDULES[sched_key]

    # Estimate workout mileage from the prescription text.
    # Approach: pull explicit mile ranges if present; otherwise use category defaults.
    # Since ME plans specify mileage via the weekly total column, the workout-level
    # estimates just need to be in the right ballpark so easy days get a sensible
    # remainder.
    def workout_miles(text, slot="primary"):
        import re
        if text is None: return 0
        if "Marathon" == text.strip(): return 26.2

        # Explicit mi pattern, e.g. "7 mi at 85%"  or  "16–18 mi easy"
        mi = re.findall(r"(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*mi(?!n)", text)
        if mi:
            total = 0
            for m in mi:
                lo = float(m[0]); hi = float(m[1]) if m[1] else lo
                total += (lo + hi) / 2
            # Weekend workouts with explicit miles = full workout miles (incl WU/CD embedded)
            return total

        # km-based: estimate total from the listed intervals + add WU/CD
        total_km = 0
        rep = re.search(r"(\d+)\s*×\s*\(([^)]+)\)", text)
        if rep:
            n = int(rep.group(1))
            inner_km = re.findall(r"(\d+(?:\.\d+)?)\s*km", rep.group(2))
            inner_m_match = re.search(r"(\d+)\s*m(?!i)", rep.group(2))
            total_km = n * sum(float(x) for x in inner_km)
            if inner_m_match: total_km += n * int(inner_m_match.group(1)) / 1000
        else:
            km_matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*km", text)
            for m in km_matches:
                lo = float(m[0]); hi = float(m[1]) if m[1] else lo
                total_km += (lo + hi) / 2
            # treat "N × 500m" style too
            m_rep = re.findall(r"(\d+)\s*×\s*(\d+)\s*m(?!i)", text)
            for n, mm in m_rep:
                total_km += int(n) * int(mm) / 1000
        if total_km > 0:
            total_km += 4   # WU + CD
            return total_km * 0.621

        # Pure time-based intervals, fallback by slot
        defaults = dict(primary=7, secondary=7, weekend=9)
        return defaults.get(slot, 7)

    weeks = []
    for wi, row in enumerate(raw):
        primary, secondary, weekend, mi_a, mi_b = row
        week_total = mi_a if variant == 0 else mi_b

        is_race_week = (wi == len(raw) - 1)

        # Assign workout miles
        primary_mi   = round(workout_miles(primary,   slot="primary"), 1)
        secondary_mi = round(workout_miles(secondary, slot="secondary"), 1) if secondary else 0
        weekend_mi   = round(workout_miles(weekend,   slot="weekend"), 1)
        # Floors so estimates stay sensible even when text parsing falls short
        primary_mi   = max(primary_mi, 6)
        if secondary: secondary_mi = max(secondary_mi, 6)
        weekend_mi   = max(weekend_mi, 8 if not is_race_week else weekend_mi)

        if is_race_week:
            # Only schedule the marathon itself, plus light shake-outs in the week
            runs = [
                dict(d=2, t="easy_me",    m=5,   note=primary),
                dict(d=4, t="easy",       m=4),
                dict(d=6, t="easy",       m=3),
                dict(d=0, t="race",       m=26, note="Marathon"),
            ]
            weeks.append(dict(w=wi+1, runs=runs))
            continue

        # Cap workout mileage at the week total to prevent overshoot
        fixed_total = primary_mi + secondary_mi + weekend_mi
        if fixed_total > week_total:
            # scale down proportionally (rare — only if estimator overshoots)
            scale = week_total / fixed_total
            primary_mi   = round(primary_mi * scale, 1)
            secondary_mi = round(secondary_mi * scale, 1)
            weekend_mi   = round(weekend_mi * scale, 1)
            fixed_total  = primary_mi + secondary_mi + weekend_mi

        easy_budget = max(0, week_total - fixed_total)

        # Distribute easy miles with realistic cadence:
        #   Wed = recovery (after Tue primary) — shortest
        #   Fri = medium-long if primary was AM+PM or big; else medium
        #   Sat = recovery (before Sun long run) — shorter
        #   Thu = easy if no secondary
        # Absorb extra volume into Fri (medium-long day)
        if secondary is None:
            easy_days_idx = [3, 4, 5, 6]  # Wed, Thu, Fri, Sat
            weights = [0.18, 0.22, 0.38, 0.22]
        else:
            easy_days_idx = [3, 5, 6]  # Wed, Fri, Sat
            weights = [0.25, 0.50, 0.25]

        easy_miles_list = [round(easy_budget * w * 2) / 2 for w in weights]
        diff = round((easy_budget - sum(easy_miles_list)) * 2) / 2
        max_idx = weights.index(max(weights))
        easy_miles_list[max_idx] = max(0, easy_miles_list[max_idx] + diff)

        # Iteratively cap any single easy day based on weekly volume.
        # Higher-mileage weeks allow longer easy days (runners doing 90+ mpw
        # often have one medium-long day around 14–16 mi).
        if   week_total >= 90: EASY_CAP = 16
        elif week_total >= 75: EASY_CAP = 14
        elif week_total >= 60: EASY_CAP = 13
        else:                  EASY_CAP = 11
        for _ in range(5):
            over_indices = [i for i,m in enumerate(easy_miles_list) if m > EASY_CAP]
            if not over_indices: break
            for i in over_indices:
                overflow = easy_miles_list[i] - EASY_CAP
                easy_miles_list[i] = EASY_CAP
                # distribute only to days not already over cap
                others = [j for j in range(len(easy_miles_list)) if j not in over_indices and easy_miles_list[j] < EASY_CAP]
                if not others: break
                per = overflow / len(others)
                for j in others:
                    easy_miles_list[j] = round((easy_miles_list[j] + per) * 2) / 2

        runs = []
        runs.append(dict(d=2, t="me_primary", m=primary_mi, note=primary))
        if secondary:
            runs.append(dict(d=4, t="me_secondary", m=secondary_mi, note=secondary))
        for idx, em in zip(easy_days_idx, easy_miles_list):
            if em > 0:
                runs.append(dict(d=idx, t="easy", m=em))
        runs.append(dict(d=0, t="me_weekend", m=weekend_mi, note=weekend))

        weeks.append(dict(w=wi+1, runs=runs))

    return weeks

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

def apply_swaps(planned_map, swaps):
    """Apply user day-swaps on top of the base planned map."""
    result = dict(planned_map)
    for ds, run in swaps.items():
        if run is None:
            result.pop(ds, None)
        else:
            result[ds] = run
    return result

# ── structured segments ───────────────────────────────────────
def fmt_range(lo, hi):
    """Format a pace range e.g. 7:40–8:15/mi"""
    return f"{fmt_pace(lo)}–{fmt_pace(hi)}"

# ── Marathon Excellence pace math ─────────────────────────────
# 5K pace from marathon goal via Riegel (T2 = T1 * (D2/D1)^1.06)
# Given marathon pace per mile, returns 5K pace per mile.
def fivek_pace_secs(marathon_gps):
    marathon_time_secs = marathon_gps * 26.2
    fivek_time_secs = marathon_time_secs * (3.10686 / 26.2) ** 1.06
    return fivek_time_secs / 3.10686

def fmt_elapsed(secs):
    """Short elapsed time format — 1:23 or 5:02 or 1:02:30"""
    if secs < 60:
        return f"{int(round(secs))}s"
    if secs < 3600:
        m, s = divmod(int(round(secs)), 60)
        return f"{m}:{s:02d}"
    h, rem = divmod(int(round(secs)), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"

def pace_for_pct(pct_lo, pct_hi, base_pace_secs):
    """Given % of reference pace (5k or MP) and base pace sec/mi, return formatted range.
       Higher % effort = faster pace = fewer seconds per mile.
       % is effort relative to reference race pace, so 100% = base_pace, 108% MP = faster."""
    # 108% of MP effort means running at a pace that's faster than MP.
    # Convert: target pace secs = base_pace / (pct/100)
    lo_pace = base_pace_secs / (pct_hi / 100)   # faster pace comes from higher %
    hi_pace = base_pace_secs / (pct_lo / 100)
    if abs(lo_pace - hi_pace) < 2:
        return fmt_pace(lo_pace)
    return f"{fmt_pace(lo_pace)}–{fmt_pace(hi_pace)}"

def parse_me_segments(note, gps):
    """Parse a Marathon Excellence workout description into structured segments.
    Returns list of (label, distance_str, pace_str, detail).
    Also includes a warmup and cooldown line.
    """
    import re
    if not note:
        return []

    text = note
    fivek_p = fivek_pace_secs(gps)  # 5K pace sec/mi
    mp_p    = gps
    segs    = []

    # Always prefix with a warmup
    segs.append(("Warmup", "~2 mi", fmt_range(gps + 60, gps + 90), "Easy jog to get loose"))

    # Helper to extract % ranges: "90–92% 5k" or "108% MP"
    def find_pct_pace(s):
        """Return (pct_lo, pct_hi, ref) or None. ref = '5k' or 'MP'."""
        m = re.search(r"(\d+)(?:[-–](\d+))?\s*%\s*(5k|MP)", s, re.IGNORECASE)
        if not m: return None
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        return lo, hi, m.group(3).upper()

    def pace_str_for(pct_info):
        lo, hi, ref = pct_info
        base = fivek_p if ref == "5K" else mp_p
        return pace_for_pct(lo, hi, base)

    # Handle each class of workout

    # 1) Time-based rep: e.g. "8 × 3 min at 90–92% 5k w/ 1 min jog"
    m = re.search(r"(\d+)(?:[-–](\d+))?\s*×\s*(\d+(?:\.\d+)?)\s*min\s*at\s*([^,w]+?)(?:\s*w/\s*(.+))?$", text, re.IGNORECASE)
    if m:
        reps_lo = int(m.group(1))
        reps_hi = int(m.group(2)) if m.group(2) else reps_lo
        rep_min = float(m.group(3))
        pct = find_pct_pace(m.group(4))
        jog = m.group(5) or "jog"
        if pct:
            reps_str = f"{reps_lo}" if reps_lo == reps_hi else f"{reps_lo}–{reps_hi}"
            lo, hi, ref = pct
            base = fivek_p if ref == "5K" else mp_p
            rep_pace_lo = base / (hi / 100)
            rep_pace_hi = base / (lo / 100)
            # Distance covered per rep
            dist_lo = rep_min * 60 / rep_pace_hi  # miles
            dist_hi = rep_min * 60 / rep_pace_lo
            avg_dist = (dist_lo + dist_hi) / 2
            total_hard_mi = reps_lo * avg_dist
            segs.append((
                f"{reps_str} × {rep_min:g} min @ {lo}–{hi}% {ref}" if lo != hi else f"{reps_str} × {rep_min:g} min @ {lo}% {ref}",
                f"~{total_hard_mi:.1f} mi",
                pace_str_for(pct),
                f"Each rep {fmt_elapsed(rep_min*60)} (~{avg_dist:.2f} mi). Recovery: {jog}"
            ))
            segs.append(("Cooldown", "~1–2 mi", fmt_range(gps + 60, gps + 90), "Easy jog"))
            return segs

    # 2) Distance-based rep: "5 × 1 mi at 95% 5k w/ 3 min jog" or "8 × 1 km at 95% 5k"
    m = re.search(r"(\d+)(?:[-–](\d+))?\s*×\s*(\d+(?:\.\d+)?)\s*(mi|km|m)\b\s*at\s*([^,w]+?)(?:\s*w/\s*(.+))?$", text, re.IGNORECASE)
    if m:
        reps_lo = int(m.group(1))
        reps_hi = int(m.group(2)) if m.group(2) else reps_lo
        rep_dist = float(m.group(3))
        unit = m.group(4).lower()
        pct = find_pct_pace(m.group(5))
        jog = m.group(6) or "jog"
        # Convert rep distance to miles
        if unit == "km":
            rep_mi = rep_dist * 0.621371
            dist_label = f"{rep_dist:g} km"
        elif unit == "m":
            rep_mi = rep_dist / 1609.34
            dist_label = f"{rep_dist:g}m"
        else:
            rep_mi = rep_dist
            dist_label = f"{rep_dist:g} mi"
        if pct:
            reps_str = f"{reps_lo}" if reps_lo == reps_hi else f"{reps_lo}–{reps_hi}"
            lo, hi, ref = pct
            base = fivek_p if ref == "5K" else mp_p
            rep_pace_lo = base / (hi / 100)
            rep_pace_hi = base / (lo / 100)
            rep_time_lo = rep_mi * rep_pace_lo
            rep_time_hi = rep_mi * rep_pace_hi
            total_hard_mi = reps_lo * rep_mi
            time_str = (f"{fmt_elapsed(rep_time_lo)}" if abs(rep_time_hi - rep_time_lo) < 2
                        else f"{fmt_elapsed(rep_time_lo)}–{fmt_elapsed(rep_time_hi)}")
            pct_str = f"{lo}–{hi}% {ref}" if lo != hi else f"{lo}% {ref}"
            segs.append((
                f"{reps_str} × {dist_label} @ {pct_str}",
                f"~{total_hard_mi:.1f} mi total",
                pace_str_for(pct),
                f"Each rep: {time_str}. Recovery: {jog}"
            ))
            segs.append(("Cooldown", "~1–2 mi", fmt_range(gps + 60, gps + 90), "Easy jog"))
            return segs

    # 3) Continuous effort: e.g. "7 mi at 85% 5k" or "9–10 mi at 100% MP"
    m = re.search(r"(\d+(?:\.\d+)?)(?:[-–](\d+(?:\.\d+)?))?\s*mi\s*at\s*([^,]+)$", text, re.IGNORECASE)
    if m:
        d_lo = float(m.group(1))
        d_hi = float(m.group(2)) if m.group(2) else d_lo
        pct = find_pct_pace(m.group(3))
        if pct:
            lo, hi, ref = pct
            base = fivek_p if ref == "5K" else mp_p
            pace_lo = base / (hi / 100)
            pace_hi = base / (lo / 100)
            total_time_lo = d_lo * pace_hi
            total_time_hi = d_hi * pace_lo
            d_str = f"{d_lo:g} mi" if d_lo == d_hi else f"{d_lo:g}–{d_hi:g} mi"
            pct_str = f"{lo}–{hi}% {ref}" if lo != hi else f"{lo}% {ref}"
            time_str = f"{fmt_elapsed(total_time_lo)}–{fmt_elapsed(total_time_hi)}"
            segs = segs[:-1] if segs and segs[-1][0] == "Warmup" else segs  # keep warmup
            segs.append((
                f"Continuous @ {pct_str}",
                d_str,
                pace_str_for(pct),
                f"Total elapsed: {time_str}"
            ))
            segs.append(("Cooldown", "~1–2 mi", fmt_range(gps + 60, gps + 90), "Easy jog"))
            return segs

    # 4) Kenyan-style progression — describe the concept
    if "Kenyan-style" in text or "kenyan-style" in text.lower():
        d = re.search(r"(\d+(?:\.\d+)?)\s*mi", text)
        dist = f"{d.group(1)} mi" if d else f"~{6} mi"
        segs = []
        segs.append((
            "Kenyan-style progression",
            dist,
            fmt_range(gps + 30, gps + 75),
            "Start at easy/long pace, progressively pick up to finish near or at MP"
        ))
        segs.append(("Finish effort (last ~1 mi)", "", fmt_pace(gps), "Should feel strong but controlled"))
        return segs

    # 5) Fallback — just show the note verbatim with reference paces
    segs.append((
        "Full session",
        f"~{total_miles_placeholder_unused()} mi" if False else "—",
        "See prescription",
        note
    ))
    # Include reference paces so user has something to anchor against
    segs.append(("Your 5K pace (est.)",  "—", fmt_pace(fivek_p), "From Riegel formula vs marathon goal"))
    segs.append(("Your MP (goal)",       "—", fmt_pace(mp_p),    "Marathon goal pace"))
    return segs

def total_miles_placeholder_unused(): return 0  # avoid NameError in fallback branch

def workout_segments(wtype, total_miles, gps, note=None):
    easy_p  = fmt_range(gps + 60, gps + 90)   # 60–90 sec/mi slower than MP
    long_p  = fmt_range(gps + 45, gps + 75)   # 45–75 sec/mi slower than MP
    tempo_p = fmt_range(gps + 10, gps + 20)   # ~15 sec/mi slower than MP (LT)
    vo2_p   = fmt_range(gps - 70, gps - 50)   # ~60 sec/mi faster than MP
    mp_p    = fmt_pace(gps)
    rec_p   = fmt_range(gps + 80, gps + 105)  # very easy recovery jog

    # Marathon Excellence workouts: parse the verbatim note into structured segments
    if wtype in ("me_primary", "me_secondary", "me_weekend"):
        parsed = parse_me_segments(note, gps) if note else []
        if parsed:
            # Prepend verbatim prescription at the top for reference
            header = [("Prescription", "—", "—", note)] if note else []
            return header + parsed
        return [("Session", f"~{total_miles} mi", "—", note or "See book")]

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
WTYPE_LABEL = dict(
    easy="Easy run", long="Long run", tempo="Lactate threshold", vo2="VO2 max", race="Race day",
    me_primary="Primary workout", me_secondary="Secondary workout", me_weekend="Weekend workout",
)
WTYPE_PURPOSE = dict(
    easy="Aerobic base building and active recovery.",
    long="Builds endurance, fat oxidation, and mental toughness. The most important run of the week.",
    tempo="Raises lactate threshold — the pace you can sustain for extended periods.",
    vo2="Increases maximal aerobic capacity. High stress, high reward.",
    race="Your goal marathon. Patient first half — the race truly begins at mile 18.",
    me_primary="Main quality session for the week. The most important workout.",
    me_secondary="Second quality session of the week, usually lower intensity than the primary.",
    me_weekend="Long run or marathon-specific session. Often the highest volume of the week.",
)

def seg_table(segments):
    rows = ""
    for name, dist, pace, note in segments:
        # Prescription row has "—" for dist and pace - render it as a single full-width row
        if name == "Prescription":
            rows += f"""
          <tr><td colspan="3" style="padding:6px 0;color:#fff;font-size:11px;font-weight:600;line-height:1.5;word-wrap:break-word;white-space:normal">{note}</td></tr>
            """
            continue
        rows += f"""
          <tr>
            <td style="padding:5px 8px 5px 0;color:#ccc;font-size:11px;vertical-align:top;word-wrap:break-word;white-space:normal">{name}</td>
            <td style="padding:5px 4px;color:#fff;font-family:monospace;font-size:11px;white-space:nowrap;vertical-align:top">{dist}</td>
            <td style="padding:5px 0 5px 4px;color:#FC4C02;font-family:monospace;font-size:11px;white-space:nowrap;vertical-align:top;text-align:right">{pace}</td>
          </tr>
          {f'<tr><td colspan="3" style="padding:0 0 6px 0;color:#555;font-size:10px;font-style:italic;line-height:1.4;word-wrap:break-word;white-space:normal">{note}</td></tr>' if note else ''}
        """
    return f'''<table style="width:100%;border-collapse:collapse;table-layout:fixed">
      <colgroup>
        <col style="width:38%">
        <col style="width:27%">
        <col style="width:35%">
      </colgroup>
      {rows}
    </table>'''

def make_tooltip(mode, wtype, planned_miles, gps, actual=None, note=None):
    label   = WTYPE_LABEL.get(wtype, "Run") if wtype else (actual or {}).get("name","Run")
    purpose = WTYPE_PURPOSE.get(wtype, "")
    status_map = dict(planned="#5ba3e8", both="#5DCAA5", missed="#e05757", actual="#5ba3e8")
    status_lbl = dict(planned="Upcoming", both="Completed", missed="Missed", actual="Unplanned")
    sc = status_map.get(mode, "#aaa")
    sl = status_lbl.get(mode, "")

    body = ""

    if mode in ("planned", "both", "missed") and wtype:
        segs = workout_segments(wtype, planned_miles, gps, note=note)
        is_me = wtype in ("me_primary", "me_secondary", "me_weekend")
        mi_prefix = "~" if is_me else ""
        body += f"""
        <div style="font-size:13px;color:#aaa;margin-bottom:10px">{mi_prefix}{planned_miles} mi planned</div>
        <div style="font-size:10px;color:#555;margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em">Workout structure</div>
        {seg_table(segs)}"""

    if mode == "both" and actual:
        # Distance delta
        dist_diff = actual["miles"] - planned_miles
        dist_pct  = dist_diff / planned_miles * 100 if planned_miles else 0
        if abs(dist_pct) < 5:
            dist_verdict = ("✓ On target", "#5DCAA5")
        elif dist_diff > 0:
            dist_verdict = (f"+{dist_diff:.1f} mi over", "#5ba3e8")
        else:
            dist_verdict = (f"{dist_diff:.1f} mi short", "#e8a825")

        # Pace delta vs target pace for this workout type
        target_spm = gps + {"easy":75,"long":60,"tempo":15,"vo2":-60,"race":0}.get(wtype, 75)
        pace_diff  = actual["pace"] - target_spm  # positive = slower than target
        if abs(pace_diff) < 15:
            pace_verdict = ("✓ On pace", "#5DCAA5")
        elif pace_diff > 0:
            pace_verdict = (f"{abs(round(pace_diff))}s/mi too slow", "#e8a825")
        else:
            pace_verdict = (f"{abs(round(pace_diff))}s/mi too fast", "#e05757")

        body += f"""
        <div style="border-top:1px solid #2a2a2a;margin-top:10px;padding-top:10px">
        <div style="font-size:10px;color:#555;margin-bottom:8px;text-transform:uppercase;letter-spacing:.06em">Your actual run</div>
        <table style="width:100%;border-collapse:collapse">
          <tr>
            <td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Distance</td>
            <td style="color:#fff;font-family:monospace;font-size:11px">{actual["miles"]:.2f} mi</td>
            <td style="color:{dist_verdict[1]};font-size:10px;text-align:right;padding-left:6px">{dist_verdict[0]}</td>
          </tr>
          <tr>
            <td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Avg pace</td>
            <td style="color:#FC4C02;font-family:monospace;font-size:11px">{fmt_pace(actual["pace"])}</td>
            <td style="color:{pace_verdict[1]};font-size:10px;text-align:right;padding-left:6px">{pace_verdict[0]}</td>
          </tr>
          {"" if not actual.get("hr") else f'<tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Avg HR</td><td style="color:#fff;font-family:monospace;font-size:11px" colspan="2">{round(actual["hr"])} bpm</td></tr>'}
          {"" if not actual.get("elev") else f'<tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Elevation</td><td style="color:#fff;font-family:monospace;font-size:11px" colspan="2">{actual["elev"]} ft</td></tr>'}
          <tr><td style="color:#ccc;font-size:11px;padding:3px 10px 3px 0">Time</td><td style="color:#fff;font-family:monospace;font-size:11px" colspan="2">{fmt_time(actual["moving_time"])}</td></tr>
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
.tip-box{
  display:none;
  position:absolute;
  z-index:9999;
  top:calc(100% + 4px);
  left:0;
  width:320px;
  max-width:320px;
  max-height:420px;
  overflow-y:auto;
  pointer-events:auto;
}
/* On the left-side columns of the week grid, flip tooltip to align to pill's LEFT edge going right.
   On the right-side columns, anchor to RIGHT edge going left.
   This is handled per-day using data-col attribute below. */
.tip-wrap[data-col="0"] .tip-box,
.tip-wrap[data-col="1"] .tip-box,
.tip-wrap[data-col="2"] .tip-box,
.tip-wrap[data-col="3"] .tip-box{left:0;right:auto}
.tip-wrap[data-col="4"] .tip-box,
.tip-wrap[data-col="5"] .tip-box,
.tip-wrap[data-col="6"] .tip-box{left:auto;right:0}
.tip-wrap:hover .tip-box{display:block}
/* Keep hover alive while moving mouse across the small gap */
.tip-wrap::after{content:"";position:absolute;top:100%;left:-8px;right:-8px;height:8px}
</style>"""

def pill_html(label, bg, tooltip_html, fg=None, col=0):
    # fg auto-selects based on bg lightness if not provided
    light_bgs = {"#e5e7eb", "#dbeafe", "#f3f4f6"}
    if fg is None:
        fg = "#374151" if bg in light_bgs else "#fff"
    return f'''
<div class="tip-wrap" data-col="{col}">
  <div class="tip-pill" style="background:{bg};color:{fg}">{label}</div>
  <div class="tip-box">{tooltip_html}</div>
</div>'''  

WTYPE_SHORT = dict(
    easy="Easy", long="Long", tempo="Tempo", vo2="VO2", race="Race",
    me_primary="Primary", me_secondary="Secondary", me_weekend="Weekend",
)

def completion_color(dist_pct):
    """Smooth green→red gradient. Generous — 80%+ is solidly green."""
    # Clamp to 0–100, map 80–100% → green, 0–50% → red, interpolate between
    pct = max(0, min(dist_pct, 100))
    # Normalize: 100% = 1.0, 50% = 0.0 (below 50 is all red)
    t = max(0.0, (pct - 50) / 50)
    # Ease the curve so 80%+ looks green
    t = t ** 0.6
    # green: #5DCAA5  red: #e05757
    r = round(0x5D + (0xe0 - 0x5D) * (1 - t))
    g = round(0xCA + (0x57 - 0xCA) * (1 - t))
    b = round(0xA5 + (0x57 - 0xA5) * (1 - t))
    return f"#{r:02x}{g:02x}{b:02x}"

def week_grade(plan_mi, act_mi, planned_days, completed_days, missed_days):
    """Letter grade + gradient color matching completion_color logic."""
    if plan_mi == 0:
        return None, None
    pct = act_mi / plan_mi * 100 if plan_mi else 0
    miss_rate = missed_days / planned_days if planned_days else 0
    # Penalize missed days slightly
    effective_pct = pct * (1 - miss_rate * 0.3)
    color = completion_color(effective_pct)
    if effective_pct >= 90:   grade = "A"
    elif effective_pct >= 78: grade = "B"
    elif effective_pct >= 63: grade = "C"
    elif effective_pct >= 48: grade = "D"
    else:                     grade = "F"
    return grade, color

def day_cell(ds, planned, actuals, today_str, plan_start_str, gps, col=0):
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
        dist_pct = (act["miles"] / planned["m"] * 100) if planned["m"] else 100
        color = completion_color(dist_pct)
        tip = make_tooltip("both", planned["t"], planned["m"], gps, actual=act, note=planned.get("note"))
        short = WTYPE_SHORT.get(planned["t"], "Run")
        inner += pill_html(f"{short} · {act['miles']:.1f}mi", color, tip, col=col)
    elif planned and is_past and in_win:
        tip = make_tooltip("missed", planned["t"], planned["m"], gps, note=planned.get("note"))
        short = WTYPE_SHORT.get(planned["t"], "Run")
        inner += pill_html(f"{short} · missed", "#e05757", tip, col=col)
    elif planned and not is_past:
        tip = make_tooltip("planned", planned["t"], planned["m"], gps, note=planned.get("note"))
        short = WTYPE_SHORT.get(planned["t"], "Run")
        lbl = "Race day" if planned["t"] == "race" else f"{short} · {planned['m']}mi"
        inner += pill_html(lbl, "#e5e7eb", tip, fg="#374151", col=col)
    elif actuals and not planned:
        act = actuals[0]
        tip = make_tooltip("actual", None, act["miles"], gps, actual=act)
        inner += pill_html(f"Run · {act['miles']:.1f}mi", "#dbeafe", tip, fg="#1e40af", col=col)

    return f'<div style="min-height:60px;border-radius:7px;padding:5px 6px;border:{border};background:{bg};overflow:visible">{inner}</div>'

def render_week(ws, planned_map, act_runs, plan_start_str, gps, is_current):
    today_str = date.today().isoformat()
    today     = date.today()
    DOWS = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]
    hbg  = "#fff8f5" if is_current else "#fff"
    hbdr = "2px solid #FC4C02" if is_current else "1px solid #e5e7eb"
    lbl  = f"Week of {ws.strftime('%b %-d')}" + (" · this week" if is_current else "")

    week_dates = [(ws+timedelta(days=i)).isoformat() for i in range(7)]
    plan_mi = sum(planned_map[ds]["m"] for ds in week_dates if ds in planned_map)
    act_mi  = sum(sum(r["miles"] for r in act_runs.get(ds,[])) for ds in week_dates)

    # Only grade fully past weeks (last day < today)
    week_end = ws + timedelta(days=6)
    is_past_week = week_end < today

    grade_html = ""
    if is_past_week and plan_mi > 0:
        planned_days   = sum(1 for ds in week_dates if ds in planned_map and date.fromisoformat(ds) >= date.fromisoformat(plan_start_str))
        completed_days = sum(1 for ds in week_dates if ds in act_runs and ds in planned_map)
        missed_days    = sum(1 for ds in week_dates if ds in planned_map and ds not in act_runs and date.fromisoformat(ds) < today and date.fromisoformat(ds) >= date.fromisoformat(plan_start_str))
        grade, gc = week_grade(plan_mi, act_mi, planned_days, completed_days, missed_days)
        if grade:
            pct = round(act_mi / plan_mi * 100) if plan_mi else 0
            grade_html = (f'<div style="display:flex;align-items:center;gap:8px">' +
                f'<div style="font-size:18px;font-weight:700;color:{gc}">{grade}</div>' +
                f'<div style="font-size:11px;color:#9ca3af">{act_mi:.1f}/{plan_mi} mi ({pct}%)</div>' +
                f'</div>')
    elif plan_mi > 0:
        plan_badge = f'<span style="color:#6b7280;font-size:12px">Planned <b style="color:#374151">{plan_mi} mi</b></span>'
        act_part   = f' &nbsp;·&nbsp; <span style="color:#6b7280;font-size:12px">So far <b style="color:#FC4C02">{act_mi:.1f} mi</b></span>' if act_mi > 0 else ""
        grade_html = plan_badge + act_part

    dow_headers = "".join(f'<div style="font-size:10px;color:#9ca3af;text-align:center;padding:2px 0">{d}</div>' for d in DOWS)
    cells = "".join(day_cell((ws+timedelta(days=i)).isoformat(), planned_map.get((ws+timedelta(days=i)).isoformat()),
                             act_runs.get((ws+timedelta(days=i)).isoformat()), today_str, plan_start_str, gps, col=i)
                    for i in range(7))

    return f"""
    <div style="background:{hbg};border:{hbdr};border-radius:10px;padding:12px 14px;margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:13px;font-weight:600;color:#374151">{lbl}</div>
        <div>{grade_html}</div>
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
    leg = """
    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:16px;margin:12px 0 16px;font-size:11px;color:#6b7280">
      <div style="display:flex;align-items:center;gap:8px">
        <div style="width:120px;height:14px;border-radius:4px;background:linear-gradient(to right,#e05757,#e8a825,#5DCAA5)"></div>
        <span>On target &rarr; Missed</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px">
        <span style="background:#e5e7eb;color:#374151;padding:2px 8px;border-radius:4px;font-weight:600">Upcoming</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px">
        <span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-weight:600">Unplanned run</span>
      </div>
    </div>"""
    st.html(leg)

    # Apply any user swaps
    if "swaps" not in ss: ss["swaps"] = {}
    effective_map = apply_swaps(planned_map, ss["swaps"])

    cal_html = tooltip_css()
    for i in range(WINDOW):
        idx = start_idx + i
        if idx >= total: break
        ws = all_weeks[idx]
        we = ws + timedelta(days=6)
        cal_html += render_week(ws, effective_map, act_runs, plan_start_str, gps, ws <= today <= we)
    st.html(cal_html)

    # ── swap UI ───────────────────────────────────────────────
    # Show swap controls for weeks that have at least 2 future planned days
    DOWS_FULL = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]
    for i in range(WINDOW):
        idx = start_idx + i
        if idx >= total: break
        ws = all_weeks[idx]
        week_dates = [(ws+timedelta(days=j)).isoformat() for j in range(7)]
        future_planned = [ds for ds in week_dates if ds >= today_str and effective_map.get(ds) and effective_map[ds]["t"] != "race"]
        if len(future_planned) < 2: continue

        we = ws + timedelta(days=6)
        week_label = f"Week of {ws.strftime('%b %-d')}"
        with st.expander(f"↕ Swap days — {week_label}"):
            # Show current schedule for this week
            sched_lines = []
            for ds in week_dates:
                run = effective_map.get(ds)
                if run:
                    d_obj = date.fromisoformat(ds)
                    dow = DOWS_FULL[d_obj.weekday() + 1 if d_obj.weekday() < 6 else 0]  # Mon=0 → Sun=6
                    # correct: date.weekday() Mon=0, Sun=6. We want Sun=0
                    dow_idx = (d_obj.weekday() + 1) % 7
                    dow = DOWS_FULL[dow_idx]
                    short = WTYPE_SHORT.get(run["t"], "Run")
                    is_future = ds >= today_str
                    marker = "" if is_future else " ✓" if ds in act_runs else " (past)"
                    sched_lines.append(f"{dow} {d_obj.strftime('%-m/%-d')}: {short} {run['m']}mi{marker}")
            st.caption("  ·  ".join(sched_lines))

            # Only allow swapping future days
            swap_options = {}
            for ds in future_planned:
                d_obj = date.fromisoformat(ds)
                dow_idx = (d_obj.weekday() + 1) % 7
                dow = DOWS_FULL[dow_idx]
                run = effective_map[ds]
                short = WTYPE_SHORT.get(run["t"], "Run")
                swap_options[f"{dow} ({d_obj.strftime('%-m/%-d')}) — {short} {run['m']}mi"] = ds

            col_a, col_b, col_c = st.columns([2, 2, 1])
            with col_a:
                day_a_label = st.selectbox("Move this day", options=list(swap_options.keys()),
                                           key=f"swap_a_{ws.isoformat()}")
            with col_b:
                day_b_label = st.selectbox("to this day", options=list(swap_options.keys()),
                                           key=f"swap_b_{ws.isoformat()}",
                                           index=min(1, len(swap_options)-1))
            with col_c:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if st.button("Swap", key=f"do_swap_{ws.isoformat()}", type="primary"):
                    ds_a = swap_options[day_a_label]
                    ds_b = swap_options[day_b_label]
                    if ds_a != ds_b:
                        run_a = effective_map[ds_a]
                        run_b = effective_map[ds_b]
                        ss["swaps"][ds_a] = run_b
                        ss["swaps"][ds_b] = run_a
                        st.rerun()
                    else:
                        st.warning("Pick two different days to swap.")

    # Show reset button if any swaps exist
    if ss.get("swaps"):
        st.divider()
        rc1, _ = st.columns([1, 3])
        with rc1:
            if st.button("Reset all swaps", type="secondary"):
                ss["swaps"] = {}
                st.rerun()

main()
