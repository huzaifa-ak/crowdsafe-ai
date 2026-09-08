"""Request validation.

Every validator collects all the problems it finds and raises once, so the
editor can show a person everything that is wrong in one go instead of making
them fix errors one save at a time.
"""

from flask import current_app

from ..cells import invalid_codes
from .errors import ValidationError

MAX_NAME_LENGTH = 100


def _problem(field: str, message: str) -> dict:
    return {"field": field, "message": message}


def _validate_dimension(payload: dict, field: str, minimum: int, maximum: int,
                        problems: list) -> int | None:
    value = payload.get(field)
    if value is None:
        problems.append(_problem(field, f"{field} is required"))
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(_problem(field, f"{field} must be a whole number"))
        return None
    if not minimum <= value <= maximum:
        problems.append(_problem(field, f"{field} must be between {minimum} and {maximum}"))
        return None
    return value


def validate_venue(payload) -> dict:
    """Check a venue create/replace payload and return the cleaned fields.

    Raises ValidationError listing every problem found.
    """
    config = current_app.config
    problems: list[dict] = []

    if not isinstance(payload, dict):
        raise ValidationError(
            "Expected a JSON object describing a venue.",
            [_problem("body", "body must be a JSON object")],
        )

    name = payload.get("name")
    cleaned_name = None
    if not isinstance(name, str) or not name.strip():
        problems.append(_problem("name", "name is required"))
    elif len(name.strip()) > MAX_NAME_LENGTH:
        problems.append(_problem("name", f"name must be {MAX_NAME_LENGTH} characters or fewer"))
    else:
        cleaned_name = name.strip()

    width = _validate_dimension(payload, "width", config["MIN_WIDTH"], config["MAX_WIDTH"], problems)
    height = _validate_dimension(
        payload, "height", config["MIN_HEIGHT"], config["MAX_HEIGHT"], problems
    )

    cells = payload.get("cells")
    if not isinstance(cells, str) or not cells:
        problems.append(_problem("cells", "cells is required"))
        cells = None
    else:
        bad = invalid_codes(cells)
        if bad:
            listed = ", ".join(sorted(bad))
            problems.append(
                _problem("cells", f"cells contains characters that are not cell codes: {listed}")
            )
        # Only checkable once both dimensions are known to be sane.
        if width is not None and height is not None:
            expected = width * height
            if len(cells) != expected:
                problems.append(
                    _problem(
                        "cells",
                        f"cells must be exactly {expected} characters "
                        f"for a {width}x{height} grid, got {len(cells)}",
                    )
                )

    if problems:
        raise ValidationError("This venue could not be saved.", problems)

    return {"name": cleaned_name, "width": width, "height": height, "cells": cells}


def _validate_number(payload: dict, field: str, minimum, maximum, default, problems: list,
                     integer: bool = True):
    value = payload.get(field, default)
    if isinstance(value, bool):
        problems.append(_problem(field, f"{field} must be a number"))
        return None
    if integer and not isinstance(value, int):
        problems.append(_problem(field, f"{field} must be a whole number"))
        return None
    if not integer and not isinstance(value, (int, float)):
        problems.append(_problem(field, f"{field} must be a number"))
        return None
    if not minimum <= value <= maximum:
        problems.append(_problem(field, f"{field} must be between {minimum} and {maximum}"))
        return None
    return value


def validate_simulation_config(payload) -> dict:
    """Check a run's settings and fill in the defaults.

    Every limit is enforced here rather than in the engine, so a request can
    never start a run that would blow the time or trace budget (D8).
    """
    config = current_app.config
    problems: list[dict] = []

    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValidationError(
            "Expected a JSON object of simulation settings.",
            [_problem("config", "config must be a JSON object")],
        )

    cleaned = {
        "num_agents": _validate_number(
            payload, "num_agents", config["MIN_AGENTS"], config["MAX_AGENTS"],
            config["DEFAULT_AGENTS"], problems),
        "speed": _validate_number(
            payload, "speed", config["MIN_SPEED"], config["MAX_SPEED"],
            config["DEFAULT_SPEED"], problems, integer=False),
        "cell_capacity": _validate_number(
            payload, "cell_capacity", config["MIN_CELL_CAPACITY"], config["MAX_CELL_CAPACITY"],
            config["CELL_CAPACITY"], problems),
        "max_ticks": _validate_number(
            payload, "max_ticks", 1, config["MAX_TICKS"], config["MAX_TICKS"], problems),
        "seed": _validate_number(
            payload, "seed", 0, 2**31 - 1, config["DEFAULT_SEED"], problems),
    }

    for flag, default in (("entrances_are_exits", False), ("reroute", True)):
        value = payload.get(flag, default)
        if not isinstance(value, bool):
            problems.append(_problem(flag, f"{flag} must be true or false"))
        else:
            cleaned[flag] = value

    routing = payload.get("routing", "nearest")
    if routing not in ("nearest", "balanced"):
        problems.append(_problem("routing", "routing must be 'nearest' or 'balanced'"))
    else:
        cleaned["routing"] = routing

    if problems:
        raise ValidationError("These simulation settings could not be used.", problems)

    return cleaned
