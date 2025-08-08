def marathon_pace_seconds(goal_time_str):
    """Convert marathon goal time (hh:mm:ss) to pace per mile in seconds."""
    parts = [int(p) for p in goal_time_str.strip().split(":")]
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m = 0, parts[0]
        s = parts[1]
    else:
        raise ValueError("Invalid time format")
    total_seconds = h * 3600 + m * 60 + s
    marathon_miles = 26.2188
    pace_sec = total_seconds / marathon_miles
    return pace_sec

def get_pace_range(activity, gmp_sec):
    """Return suggested pace range string for an activity type and goal marathon pace (in seconds)."""
    if not isinstance(activity, str):
        return ""
    activity_lower = activity.lower()
    for mapping in [
        {"type": "Long Run", "keywords": ["long run", "lr"], "delta": (45, 90)},
        {"type": "Medium-Long Run", "keywords": ["medium-long run", "mlr"], "delta": (30, 75)},
        {"type": "General Aerobic", "keywords": ["general aerobic", "ga"], "delta": (45, 90)},
        {"type": "Recovery Run", "keywords": ["recovery", "rec"], "delta": (90, 144)},
        {"type": "Marathon Pace Run", "keywords": ["marathon pace", "mp"], "delta": (0, 0)},
        {"type": "LT/Tempo Run", "keywords": ["lactate threshold", "tempo", "lt", "hmp"], "delta": (-48, -24)},
        {"type": "VO₂ Max Intervals", "keywords": ["vo₂max", "vo2max", "vo2 max"], "delta": (-96, -72)},
        {"type": "Strides", "keywords": ["sprints", "strides", "sp"], "delta": (-50, -35)},
    ]:
        for kw in mapping["keywords"]:
            if kw in activity_lower:
                low = gmp_sec + mapping["delta"][0]
                high = gmp_sec + mapping["delta"][1]
                def sec_to_str(sec):
                    m = int(sec // 60)
                    s = int(round(sec % 60))
                    return f"{m}:{s:02d}/mi"
                return f"{sec_to_str(low)} - {sec_to_str(high)}"
    return ""
