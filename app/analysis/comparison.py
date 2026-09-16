"""Comparing two runs.

The point of the whole tool is answering "would this change help?", and the
only honest answer is two runs of the same crowd through two layouts. Estimates
were what Day 14 could offer; this measures.

Which makes the comparison's first job checking that the two runs are
comparable at all. Two runs with different crowd sizes, or different seeds, or
different exit-choice models, differ for reasons that have nothing to do with
the layout — and a table of deltas presented without that caveat is worse than
no table, because it looks like evidence.
"""

# Config fields that must match for a difference to be attributable to the
# layout. `max_ticks` is left out: it bounds a run rather than shaping it.
MUST_MATCH = ("num_agents", "speed", "cell_capacity", "seed", "routing", "reroute",
              "entrances_are_exits")

FIELD_NAMES = {
    "num_agents": "crowd size",
    "speed": "walking speed",
    "cell_capacity": "density cap",
    "seed": "seed",
    "routing": "exit choice",
    "reroute": "rerouting",
    "entrances_are_exits": "entrances as exits",
}

# Two pinch points within this many metres of each other are treated as the
# same place, so a bottleneck that shifts slightly is not reported as one
# resolved and one new.
SAME_PLACE_METRES = 4


def compare(baseline: dict, variant: dict) -> dict:
    warnings = _config_warnings(baseline.get("config", {}), variant.get("config", {}))
    changes = _changes(baseline, variant)
    findings = _finding_changes(baseline.get("bottlenecks", []),
                               variant.get("bottlenecks", []))

    base_score = (baseline.get("assessment") or {}).get("score")
    variant_score = (variant.get("assessment") or {}).get("score")

    return {
        "comparable": not warnings,
        "warnings": warnings,
        "score": {
            "baseline": base_score,
            "variant": variant_score,
            "delta": (variant_score - base_score)
            if base_score is not None and variant_score is not None else None,
            "baseline_grade": (baseline.get("assessment") or {}).get("grade"),
            "variant_grade": (variant.get("assessment") or {}).get("grade"),
        },
        "changes": changes,
        "findings": findings,
        "verdict": _verdict(base_score, variant_score, changes, warnings),
    }


def _config_warnings(baseline: dict, variant: dict) -> list[dict]:
    warnings = []
    for field in MUST_MATCH:
        before, after = baseline.get(field), variant.get(field)
        if before != after:
            warnings.append({
                "field": field,
                "message": f"The two runs used a different {FIELD_NAMES[field]} "
                           f"({before} against {after}), so the difference between "
                           "them is not only the layout.",
            })
    return warnings


def _changes(baseline: dict, variant: dict) -> list[dict]:
    """The measurements worth putting side by side.

    `better` says which direction is an improvement, because it is not the same
    for every row: less time is better, more evacuated is better, and a change
    in exit width is neither on its own.
    """
    before = baseline.get("metrics") or {}
    after = variant.get("metrics") or {}
    if not before or not after:
        return []

    rows = [
        _row("Clearing time", before["time"]["clearing_seconds"],
             after["time"]["clearing_seconds"], "s", lower_is_better=True),
        _row("Against free flow", before["time"]["time_ratio"],
             after["time"]["time_ratio"], "×", lower_is_better=True),
        _row("Evacuated", before["crowd"]["evacuated"], after["crowd"]["evacuated"],
             "people", lower_is_better=False),
        _row("Crowded floor", _percent(before["congestion"]["crowded_share"]),
             _percent(after["congestion"]["crowded_share"]), "%", lower_is_better=True),
        _row("Worst density", before["congestion"]["peak_density"],
             after["congestion"]["peak_density"], "people/m²", lower_is_better=True),
        _row("Longest crowded spell", before["congestion"]["longest_crowded_spell"],
             after["congestion"]["longest_crowded_spell"], "ticks", lower_is_better=True),
        _row("Total exit width", before["exits"]["total_width"],
             after["exits"]["total_width"], "m", lower_is_better=None),
        _row("Exit imbalance", before["exits"]["imbalance"], after["exits"]["imbalance"],
             "", lower_is_better=True),
    ]

    if before["crowd"]["stranded"] or after["crowd"]["stranded"]:
        rows.append(_row("Stranded", before["crowd"]["stranded"],
                         after["crowd"]["stranded"], "people", lower_is_better=True))

    return rows


def _percent(share) -> float | None:
    return round(share * 100, 1) if share is not None else None


def _row(name, before, after, unit, lower_is_better) -> dict:
    delta = None
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        delta = round(after - before, 2)

    better = None
    if delta not in (None, 0) and lower_is_better is not None:
        better = delta < 0 if lower_is_better else delta > 0

    change_percent = None
    if delta is not None and before:
        change_percent = round((after - before) / before * 100, 1)

    return {
        "name": name,
        "baseline": before,
        "variant": after,
        "delta": delta,
        "percent": change_percent,
        "better": better,
        "unit": unit,
    }


def _finding_changes(before: list[dict], after: list[dict]) -> dict:
    """Which bottlenecks went away, which appeared, and which are still there.

    Matched by kind and location rather than by index, because the ranking can
    reorder between runs — the point of a change is often that the worst
    problem stopped being the worst problem.
    """
    remaining, resolved = [], []
    unmatched = list(after)

    for old in before:
        match = next((n for n in unmatched if _same_place(old, n)), None)
        if match is None:
            resolved.append(old)
        else:
            unmatched.remove(match)
            remaining.append({
                "label": match["label"],
                "kind": match["kind"],
                "at": match["pinch_at"],
                "severity_before": old["severity"],
                "severity_after": match["severity"],
                "improved": match["severity"] < old["severity"],
            })

    return {"resolved": resolved, "new": unmatched, "remaining": remaining}


def _same_place(a: dict, b: dict) -> bool:
    """Whether two findings are about the same place.

    A queue is identified by which door it is at, not by where its worst cell
    happened to be. Widening a door moves that cell, and matching on
    coordinates reported the queue as resolved and an identical one as new —
    which is the opposite of what happened.
    """
    if a["kind"] != b["kind"]:
        return False
    if a["kind"] == "exit_approach":
        return a.get("nearest_exit") == b.get("nearest_exit")
    ax, ay = a["pinch_at"]
    bx, by = b["pinch_at"]
    return abs(ax - bx) + abs(ay - by) <= SAME_PLACE_METRES


def _verdict(base_score, variant_score, changes, warnings) -> str:
    if warnings:
        return ("These two runs differ in more than the layout, so the numbers "
                "below cannot be read as the effect of the change.")
    if base_score is None or variant_score is None:
        return "Not enough information to compare these runs."

    time_row = next((c for c in changes if c["name"] == "Clearing time"), None)
    delta = variant_score - base_score

    if time_row and time_row["percent"] is not None and abs(time_row["percent"]) >= 5:
        direction = "faster" if time_row["percent"] < 0 else "slower"
        timing = f"{abs(time_row['percent']):.0f}% {direction}"
    else:
        timing = "about the same speed"

    if delta >= 5:
        return f"The change is an improvement: {timing}, and {delta} points better."
    if delta <= -5:
        return f"The change makes things worse: {timing}, and {abs(delta)} points worse."
    return f"Little difference either way — {timing}, and {abs(delta)} points apart."
