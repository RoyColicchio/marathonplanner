def marathon_pace_seconds(goal_marathon_time: str) -> float:
    """
    Calculate marathon pace in seconds per mile from a goal time string.
    Returns total seconds per mile as a float.
    """
    try:
        h, m, s = map(int, goal_marathon_time.split(':'))
        total_seconds = h * 3600 + m * 60 + s
        # miles in a marathon: 26.2188
        return total_seconds / 26.2188
    except Exception:
        # Return a default pace (e.g., 10 min/mile) if format is wrong
        return 600.0


def get_pace_range(activity_description: str, goal_marathon_pace_seconds: float) -> str:
    """
    Get the suggested pace range for a given workout.

    Args:
        activity_description: The description of the workout (e.g., "Long Run", "Tempo").
        goal_marathon_pace_seconds: The goal marathon pace in seconds per mile.

    Returns:
        A string representing the pace range (e.g., "8:30-9:00").
    """
    if not activity_description or not isinstance(activity_description, str):
        return "—"

    desc = activity_description.lower()
    gmp_sec = goal_marathon_pace_seconds

    # Pace mappings: keyword -> (low_delta, high_delta) in seconds from marathon pace
    pace_map = {
        "easy": {"delta": (45, 90), "label": "Easy"},
        "general aerobic": {"delta": (30, 60), "label": "Aerobic"},
        "aerobic": {"delta": (30, 60), "label": "Aerobic"},
        "recovery": {"delta": (60, 120), "label": "Recovery"},
        "rec": {"delta": (60, 120), "label": "Recovery"},
        "medium-long": {"delta": (30, 75), "label": "MLR"},
        "mlr": {"delta": (30, 75), "label": "MLR"},
        "long run": {"delta": (45, 90), "label": "Long Run"},
        "lr": {"delta": (45, 90), "label": "Long Run"},
        "marathon pace": {"delta": (-5, 5), "label": "MP"},
        "mp": {"delta": (-5, 5), "label": "MP"},
        "lactate threshold": {"delta": (-25, -15), "label": "LT"},
        "lt": {"delta": (-25, -15), "label": "LT"},
        "tempo": {"delta": (-25, -15), "label": "Tempo"},
        "half marathon pace": {"delta": (-20, -10), "label": "HMP"},
        "hmp": {"delta": (-20, -10), "label": "HMP"},
        "vo₂max": {"delta": (-50, -40), "label": "VO₂Max"},
        "v8": {"delta": (-50, -40), "label": "VO₂Max"},
        "hill": {"delta": None, "label": "Hard effort"},
        "sprint": {"delta": None, "label": "Max effort"},
        "sp": {"delta": None, "label": "Max effort"},
        "race": {"delta": None, "label": "Race Pace"},
    }

    # Find the best matching pace type
    for keyword, mapping in pace_map.items():
        if keyword in desc:
            if mapping["delta"] is None:
                return mapping["label"]
            
            low = gmp_sec + mapping["delta"][0]
            high = gmp_sec + mapping["delta"][1]
            
            # Format to M:SS
            low_min, low_sec = divmod(int(low), 60)
            high_min, high_sec = divmod(int(high), 60)
            
            return f"{low_min}:{low_sec:02d} - {high_min}:{high_sec:02d}"

    # Default for unrecognized runs
    if "run" in desc or "mile" in desc:
        low = gmp_sec + 30
        high = gmp_sec + 90
        low_min, low_sec = divmod(int(low), 60)
        high_min, high_sec = divmod(int(high), 60)
        return f"{low_min}:{low_sec:02d} - {high_min}:{high_sec:02d}"

    return "—"
