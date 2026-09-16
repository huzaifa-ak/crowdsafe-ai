"""The safety score.

A single number out of 100 with an A–F grade, built by subtracting penalties
from a clean sheet. Every penalty is bounded and every one names what caused
it, so the score is always explainable rather than being a verdict from
nowhere.

Three components, not four. The plan had bottlenecks as a separate axis, but a
venue with one narrow door trips the time, congestion and exit penalties at
once — adding a fourth would punish the same fault a fourth time and bunch
every imperfect venue at the bottom of the scale. Bottlenecks are reported as
findings with locations instead (Day 13), which is more useful than another
subtraction.

Thresholds here are first estimates, revisited during tuning on Day 15.
"""

# Weights. They add to 100.
TIME_WEIGHT = 35
CONGESTION_WEIGHT = 40
EXIT_WEIGHT = 25

# Time. Guidance for assembly buildings is generally couched in two to three
# minutes to clear. The original 60–240 s range left this term barely engaged:
# across the reference venues it never exceeded 10 of its 25 points, because
# none of them came close to four minutes. 45–180 s spans the range real
# venues of this size actually occupy.
COMFORTABLE_SECONDS = 45
ALARMING_SECONDS = 180
ABSOLUTE_SHARE = 25

# Efficiency, as a secondary term. Some overhead above free flow is
# unavoidable — people start in different places and cannot all walk at once —
# so 1.3x is treated as clean.
CLEAN_RATIO = 1.3
POOR_RATIO = 3.0
EFFICIENCY_SHARE = 10

# Congestion. Calibrated against measured runs on venues that fail in
# different ways: a hall with generous exits sits near 0.13 crowded share, a
# lopsided pair of doors near 0.22, and a single 1 m door near 0.37. The
# ceiling is set beyond the worst of those so that the scale still separates
# bad venues from catastrophic ones instead of saturating on both.
HEAVY_CROWDED_SHARE = 0.35
# Cell-ticks over the threshold as a share of all cell-ticks available.
HEAVY_INTENSITY = 0.12

# Exits. How long the doors alone need to pass the crowd.
COMFORTABLE_DOOR_TICKS = 40
ALARMING_DOOR_TICKS = 150

GRADES = ((85, "A"), (70, "B"), (55, "C"), (40, "D"))

# Anyone left inside is disqualifying. A venue people cannot get out of does
# not earn a passing grade because its density figures happened to look calm.
STRANDED_CEILING = 35


def _ramp(value, good, bad, weight):
    """Zero at `good`, full `weight` at `bad`, linear between."""
    if value is None:
        return 0.0
    if bad == good:
        return 0.0
    fraction = (value - good) / (bad - good)
    return max(0.0, min(1.0, fraction)) * weight


def score(metrics: dict) -> dict:
    penalties = [
        _time_penalty(metrics["time"]),
        _congestion_penalty(metrics["congestion"]),
        _exit_penalty(metrics["exits"], metrics["time"]),
    ]

    total = round(max(0.0, 100 - sum(p["penalty"] for p in penalties)))
    caps = []

    crowd = metrics["crowd"]
    if crowd["stranded"]:
        total = min(total, STRANDED_CEILING)
        caps.append(f"{crowd['stranded']} people had no route to an exit")
    elif crowd["status"] != "complete":
        total = min(total, STRANDED_CEILING)
        caps.append("the venue did not clear within the time limit")

    return {
        "score": total,
        "grade": _grade(total),
        "components": penalties,
        "capped_by": caps,
    }


def _grade(total: int) -> str:
    for threshold, letter in GRADES:
        if total >= threshold:
            return letter
    return "F"


def _time_penalty(time: dict) -> dict:
    """Mostly how long it took, plus a smaller term for how wasteful that was.

    Neither measure works alone, and they fail in opposite directions.

    The ratio grows a baseline of its own: once the doors are the binding
    limit, free flow rises with the crowd, so adding people can *lower* the
    ratio while the venue plainly gets worse. And it flatters bad venues —
    somewhere with one narrow door has such a slow theoretical best that
    matching it looks like efficiency.

    Absolute time has neither problem, so it carries most of the weight. But it
    cannot tell a venue that is slow because it is enormous from one that is
    slow because it is badly laid out, which is what the ratio is for. Summing
    them, weighted, rather than taking the worse of the two: a venue that
    clears in a minute is not dangerous merely for being inefficient about it.
    """
    seconds = time["clearing_seconds"]
    ratio = time["time_ratio"]

    absolute = _ramp(seconds, COMFORTABLE_SECONDS, ALARMING_SECONDS, ABSOLUTE_SHARE)
    efficiency = _ramp(ratio, CLEAN_RATIO, POOR_RATIO, EFFICIENCY_SHARE)
    penalty = min(TIME_WEIGHT, absolute + efficiency)

    if penalty < 1:
        detail = "Clears quickly and close to the theoretical best."
    elif absolute >= efficiency:
        detail = f"Takes {seconds:.0f} s to clear."
    else:
        detail = f"Takes {ratio}x longer than an unobstructed evacuation would."

    return {
        "name": "Time",
        "penalty": round(penalty, 1),
        "weight": TIME_WEIGHT,
        "detail": detail,
    }


def _congestion_penalty(congestion: dict) -> dict:
    """How much of the floor got tight, and how sustained it was.

    Split evenly between extent and persistence. A venue where a fifth of the
    floor briefly touches the threshold and one where a single corridor stays
    jammed throughout are both bad, in different ways, and one measure cannot
    see both.
    """
    half = CONGESTION_WEIGHT / 2
    extent = _ramp(congestion["crowded_share"], 0.0, HEAVY_CROWDED_SHARE, half)
    persistence = _ramp(congestion["crowded_intensity"], 0.0, HEAVY_INTENSITY, half)
    penalty = extent + persistence

    cells = congestion["crowded_cells"]
    if not cells:
        detail = f"Never exceeded {congestion['threshold']} people per m²."
    else:
        share = congestion["crowded_share"] * 100
        detail = (
            f"{cells} cells ({share:.0f}% of the floor) went over "
            f"{congestion['threshold']} people per m², the worst for "
            f"{congestion['longest_crowded_spell']} ticks."
        )

    return {
        "name": "Congestion",
        "penalty": round(penalty, 1),
        "weight": CONGESTION_WEIGHT,
        "detail": detail,
    }


def _exit_penalty(exits: dict, time: dict) -> dict:
    """Whether there is enough door, and whether it is being used evenly.

    Imbalance is measured against each door's share of the total width, so a
    wide door carrying more of the crowd is correct rather than penalised.
    """
    capacity_share = EXIT_WEIGHT * 0.6
    balance_share = EXIT_WEIGHT * 0.4

    capacity = _ramp(time["door_floor_ticks"], COMFORTABLE_DOOR_TICKS,
                     ALARMING_DOOR_TICKS, capacity_share)
    # An imbalance of 0.5 means a door carried half the crowd more than its
    # width justifies — as lopsided as it gets in practice.
    balance = _ramp(exits["imbalance"], 0.1, 0.5, balance_share)
    penalty = capacity + balance

    worst = max(exits["doors"], key=lambda d: d["overload"], default=None)
    if capacity >= balance and capacity > 1:
        detail = (
            f"{exits['total_width']} m of exit for {exits['people_per_metre']:.0f} "
            "people per metre."
        )
    elif worst and balance > 1:
        detail = (
            f"Exit {worst['id']} took {worst['share'] * 100:.0f}% of the crowd "
            f"on {worst['capacity_share'] * 100:.0f}% of the exit width."
        )
    else:
        detail = "Exits are wide enough and evenly used."

    return {
        "name": "Exits",
        "penalty": round(penalty, 1),
        "weight": EXIT_WEIGHT,
        "detail": detail,
    }
