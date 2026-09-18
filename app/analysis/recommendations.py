"""Recommendations.

Rules, not a model. Each one looks at the measurements, decides whether it
applies, and if so says what to change and roughly what it would be worth.

Two things are load-bearing here.

Every recommendation carries the evidence that produced it. A suggestion you
cannot check is a suggestion you cannot trust, and the person reading this
knows their venue far better than the simulation does.

Savings are labelled as estimates and derived openly, because they are
extrapolations from one run rather than measurements of a second one. Where an
estimate would be guesswork, the rule says what to try instead — the app can
simply run it, and a measured answer beats a modelled one.
"""

from ..config import Config

# Ordered worst first; the UI relies on this.
PRIORITIES = ("critical", "high", "medium", "low")


def _door_word(metrics: dict) -> str:
    """Whether this run's doors are exits or entrances.

    Every door rule reads the same metrics, because filling a room and emptying
    it are the same arithmetic pointed in opposite directions. Only the noun
    changes, and getting it wrong would send someone to the wrong side of the
    building.
    """
    return "entrance" if metrics.get("mode") == "arrival" else "exit"


def recommend(grid, metrics: dict, findings: list[dict], settings: dict) -> list[dict]:
    arriving = metrics.get("mode") == "arrival"

    shared = (
        _not_enough_exit,
        _uneven_exit_use,
        _pinch_points,
        _crowd_too_large,
    )
    rules = (
        (_people_left_behind, _did_not_clear)
        + shared
        + ((_stopped_short,) if arriving else
           (_entrances_could_be_exits, _crowd_starts_packed, _distance_is_the_problem))
    )

    out = []
    for rule in rules:
        result = rule(grid, metrics, findings, settings)
        if result:
            out.extend(result if isinstance(result, list) else [result])

    out.sort(key=lambda r: (PRIORITIES.index(r["priority"]), -r["weight"]))
    for index, item in enumerate(out, start=1):
        item["id"] = index
    return out


def _tip(priority, title, detail, action, evidence, estimate=None, weight=0.0) -> dict:
    return {
        "priority": priority,
        # Roughly how many ticks per person this is worth, used to order items
        # of equal priority. Two suggestions can both be urgent; the one that
        # buys more time should be read first.
        "weight": round(weight, 1),
        "title": title,
        "detail": detail,
        "action": action,
        "estimate": estimate,
        "evidence": evidence,
    }


def _seconds(ticks: float) -> float:
    return round(ticks * Config.SECONDS_PER_TICK, 1)


# Rules ----------------------------------------------------------------------


def _people_left_behind(grid, metrics, findings, settings):
    stranded = metrics["crowd"]["stranded"]
    if not stranded:
        return None
    word = _door_word(metrics)
    return _tip(
        "critical",
        f"{stranded} people have no route {'in' if word == 'entrance' else 'out'}",
        f"Part of the floor is cut off from every {word}. Nothing else about "
        "this venue matters until that is fixed.",
        f"Check for a wall or barrier closing off that area, or add {'an' if word == 'entrance' else 'an'} "
        f"{word} to it.",
        {"stranded": stranded},
    )


def _did_not_clear(grid, metrics, findings, settings):
    if metrics["crowd"]["status"] == "complete":
        return None
    arriving = metrics.get("mode") == "arrival"
    outstanding = metrics["crowd"]["agents"] - metrics["crowd"]["evacuated"]
    return _tip(
        "critical",
        "The venue did not fill" if arriving else "The venue did not empty",
        (f"{outstanding} people never reached a place."
         if arriving else
         f"{outstanding} people were still inside when the simulation ended."),
        ("Widen the entrances, open the floor up, or reduce the crowd, then run "
         "it again." if arriving else
         "Widen the exits or reduce the crowd, then run it again."),
        {"outstanding": outstanding, "status": metrics["crowd"]["status"]},
    )


def _stopped_short(grid, metrics, findings, settings):
    """People who gave up on reaching a place and stood in a gangway.

    Only meaningful for an arrival. It is the clearest sign a venue is being
    filled beyond what its circulation routes support: everyone got in, and
    some of them had nowhere to go once they had.
    """
    stopped = metrics["crowd"].get("stopped_short", 0)
    if not stopped:
        return None
    return _tip(
        "high",
        f"{stopped} people ended up standing in a circulation route",
        "They could not reach anywhere to stand and stopped where they were. "
        "A gangway with people standing in it is not a gangway.",
        "Widen the routes into the seating, or reduce the crowd until everyone "
        "has somewhere to go.",
        {"stopped_short": stopped},
        weight=20,
    )


def _not_enough_exit(grid, metrics, findings, settings):
    """Doors are the binding limit, so widening one has a computable payoff."""
    time = metrics["time"]
    exits = metrics["exits"]
    if time["binding_constraint"] != "doors" or not time["clearing_ticks"]:
        return None
    if time["door_floor_ticks"] < 40:
        return None

    word = _door_word(metrics)
    busiest = max(exits["doors"], key=lambda d: d["used"])
    extra = max(1, busiest["width"])          # doubling the busiest door
    new_width = exits["total_width"] + extra

    # The run's overhead above its own floor is assumed to carry across. That
    # is an assumption, not a result: widening a door can move the bottleneck
    # somewhere else entirely, which is why this says "about".
    overhead = time["clearing_ticks"] / time["free_flow_ticks"]
    new_floor = max(time["walk_floor_ticks"], metrics["crowd"]["agents"] / new_width)
    predicted = new_floor * overhead
    saving = 1 - predicted / time["clearing_ticks"]

    if saving < 0.05:
        return None

    return _tip(
        "high",
        f"Widen {word} {busiest['id']}",
        f"The doors are what limits this venue: {exits['total_width']} m of {word} "
        f"for {exits['people_per_metre']:.0f} people per metre. Even with no "
        "congestion at all, the crowd cannot pass through faster than "
        f"{_seconds(time['door_floor_ticks'])} s.",
        f"Take {word} {busiest['id']} from {busiest['width']} m to "
        f"{busiest['width'] + extra} m.",
        {
            "exit_id": busiest["id"],
            "current_width": busiest["width"],
            "proposed_width": busiest["width"] + extra,
            "door_floor_seconds": _seconds(time["door_floor_ticks"]),
        },
        estimate=f"about {saving * 100:.0f}% faster, roughly "
                 f"{_seconds(time['clearing_ticks'])} s down to {_seconds(predicted)} s",
        weight=time["clearing_ticks"] - predicted,
    )


def _uneven_exit_use(grid, metrics, findings, settings):
    """One door doing more than its width justifies.

    No number is offered here. Whether people would actually spread out depends
    on signage, marshals and sightlines, none of which the simulation knows
    about — but it can be measured directly by running the venue again with
    managed exit choice, so the rule says to do that.
    """
    exits = metrics["exits"]
    if len(exits["doors"]) < 2 or exits["imbalance"] < 0.15:
        return None

    word = _door_word(metrics)
    worst = max(exits["doors"], key=lambda d: d["overload"])
    idle = min(exits["doors"], key=lambda d: d["overload"])
    if worst["overload"] < 0.15:
        return None

    already_managed = settings.get("routing") == "balanced"
    action = (
        f"Signage or marshals directing people towards {word} {idle['id']}."
        if not already_managed
        else f"{word.capitalize()} {idle['id']} is underused even with managed "
             "routing — it is probably hard to reach rather than hard to find."
    )

    return _tip(
        "high",
        f"{word.capitalize()} {worst['id']} is doing too much of the work",
        f"It took {worst['share'] * 100:.0f}% of the crowd on "
        f"{worst['capacity_share'] * 100:.0f}% of the {word} width, while "
        f"{word} {idle['id']} took {idle['share'] * 100:.0f}%.",
        action,
        {
            "overloaded_exit": worst["id"],
            "underused_exit": idle["id"],
            "imbalance": exits["imbalance"],
        },
        estimate=None if already_managed
        else "run again with Exit choice set to Managed to measure what this would save",
    )


def _pinch_points(grid, metrics, findings, settings):
    """Constrictions, worst first. At most two, so the list stays a list of
    actions rather than a catalogue of every tight spot."""
    pinches = [f for f in findings if f["kind"] == "pinch"][:2]
    out = []
    for pinch in pinches:
        x, y = pinch["pinch_at"]
        out.append(_tip(
            "high" if pinch is pinches[0] else "medium",
            f"Widen the {pinch['passage_width']} m gap at {x}, {y}",
            f"{pinch['detail']} People spent {pinch['person_ticks']:,} person-ticks "
            f"({_seconds(pinch['person_ticks'] / max(1, metrics['crowd']['agents']))} s "
            "each on average) in this area.",
            f"Move whatever is narrowing the route at {x}, {y}, or open a second "
            "way past it.",
            {
                "at": pinch["pinch_at"],
                "passage_width": pinch["passage_width"],
                "peak_density": pinch["peak_density"],
                "person_ticks": pinch["person_ticks"],
            },
            weight=pinch["person_ticks"] / max(1, metrics["crowd"]["agents"]),
        ))
    return out


def _entrances_could_be_exits(grid, metrics, findings, settings):
    """A venue with doors it is not using.

    Entrances are walkable but nobody leaves through them (D7). When the exits
    are the binding limit and there are entrances sitting idle, that is worth
    saying — it may be the cheapest change available, needing no building work.
    """
    if not grid.entrance_cells or settings.get("entrances_are_exits"):
        return None
    if metrics["time"]["binding_constraint"] != "doors":
        return None

    width = len(grid.entrance_cells)
    time = metrics["time"]
    total = metrics["exits"]["total_width"]

    # Same arithmetic as widening a door, because that is what this is: extra
    # exit width, at no building cost.
    overhead = time["clearing_ticks"] / time["free_flow_ticks"]
    predicted = max(time["walk_floor_ticks"],
                    metrics["crowd"]["agents"] / (total + width)) * overhead
    saving = 1 - predicted / time["clearing_ticks"]

    return _tip(
        "high",
        f"{width} m of entrance is not being used as an exit",
        "The doors are what limits this venue, and it has entrances that nobody "
        "is leaving through. If they can be opened outwards in an evacuation, "
        f"the usable exit width goes from {total} m to {total + width} m.",
        "Mark the entrances as exits, or run again with entrances treated as "
        "exits to see what it would be worth.",
        {"entrance_cells": width, "current_exit_width": total},
        estimate=f"about {saving * 100:.0f}% faster, roughly "
                 f"{_seconds(time['clearing_ticks'])} s down to {_seconds(predicted)} s"
                 if saving > 0.05 else None,
        weight=max(0.0, time["clearing_ticks"] - predicted),
    )


def _crowd_too_large(grid, metrics, findings, settings):
    congestion = metrics["congestion"]
    if congestion["crowded_share"] < 0.15:
        return None

    agents = metrics["crowd"]["agents"]
    # No capacity figure is computed here. Crowded share does not scale with
    # the crowd in any way worth extrapolating — queue length shrinks, the area
    # the queue occupies often does not — and an invented number carries more
    # authority than it deserves. A starting point for bisecting is honest; a
    # calculated capacity would not be.
    starting_point = int(agents * 0.7)

    return _tip(
        "medium",
        "There are more people than this layout handles comfortably",
        f"{congestion['crowded_share'] * 100:.0f}% of the floor went over "
        f"{congestion['threshold']} people per m², the worst of it for "
        f"{congestion['longest_crowded_spell']} ticks.",
        f"If the layout cannot change, find the number this venue does handle: "
        f"try {starting_point} and work from there.",
        {
            "crowded_share": congestion["crowded_share"],
            "try_next": starting_point,
            "current": agents,
        },
        estimate="the comfortable capacity has to be measured, not calculated",
        weight=5,
    )


def _crowd_starts_packed(grid, metrics, findings, settings):
    packed = [f for f in findings if f["kind"] == "spawn_density"]
    if not packed:
        return None
    worst = max(packed, key=lambda f: f["peak_density"])
    return _tip(
        "low",
        "The crowd starts at high density",
        f"The spawn area reaches {worst['peak_density']} people per m² before "
        "anyone has moved. That is how many people were placed in the space, "
        "not congestion the layout caused.",
        "Enlarge the spawn area or lower the crowd size if this is not how the "
        "venue really fills.",
        {"peak_density": worst["peak_density"], "at": worst["pinch_at"]},
    )


def _distance_is_the_problem(grid, metrics, findings, settings):
    time = metrics["time"]
    if time["binding_constraint"] != "walking":
        return None
    if time["walk_floor_ticks"] < 30:
        return None

    return _tip(
        "medium",
        "The far side of the venue is a long way from any exit",
        f"The longest walk to a door takes {_seconds(time['walk_floor_ticks'])} s "
        "with nobody in the way. Widening the existing doors would change little, "
        "because they are not what is holding things up.",
        "Add an exit nearer the far side of the floor, or open a more direct "
        "route to one of the existing doors.",
        {
            "walk_floor_seconds": _seconds(time["walk_floor_ticks"]),
            "door_floor_seconds": _seconds(time["door_floor_ticks"] or 0),
        },
    )
