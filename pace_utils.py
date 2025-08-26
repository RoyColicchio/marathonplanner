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


def get_pace_range(activity_description: str, goal_marathon_pace_seconds: float, plan_file: str = "") -> str:
    """
    Get the suggested pace range for a given workout.

    Args:
        activity_description: The description of the workout (e.g., "Long Run", "Tempo").
        goal_marathon_pace_seconds: The goal marathon pace in seconds per mile.
        plan_file: The path to the plan file, used to apply adjustments.

    Returns:
        A string representing the pace range (e.g., "8:30-9:00").
    """
    if not activity_description or not isinstance(activity_description, str):
        return "—"

    desc = activity_description.lower()
    gmp_sec = goal_marathon_pace_seconds

    adjustment_factor = 1.0
    if plan_file:
        plan_name = plan_file.lower()
        # "run_plan.csv" is the 18/55 plan, and "18-63" is in the Pfitz 18/63 plan name
        if "run_plan.csv" in plan_name or "unofficial-pfitz-18-63" in plan_name:
            adjustment_factor = 1.05

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

            if adjustment_factor != 1.0:
                # For paces faster than marathon pace, being less aggressive means slower (closer to MP)
                # For paces slower than marathon pace, being less aggressive means even slower (further from MP)
                # A simple multiplier works for both cases.
                low *= adjustment_factor
                high *= adjustment_factor
            
            # Format to M:SS
            low_min, low_sec = divmod(int(low), 60)
            high_min, high_sec = divmod(int(high), 60)
            
            return f"{low_min}:{low_sec:02d} - {high_min}:{high_sec:02d}"

    # Default for unrecognized runs
    if "run" in desc or "mile" in desc:
        low = gmp_sec + 30
        high = gmp_sec + 90
        if adjustment_factor != 1.0:
            low *= adjustment_factor
            high *= adjustment_factor
        low_min, low_sec = divmod(int(low), 60)
        high_min, high_sec = divmod(int(high), 60)
        return f"{low_min}:{low_sec:02d} - {high_min}:{high_sec:02d}"

    return "—"
