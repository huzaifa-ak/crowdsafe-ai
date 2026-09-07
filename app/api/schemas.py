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
