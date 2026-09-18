"""Example venues, loaded on boot when the database is empty.

Render's free tier throws its disk away on every deploy, so a fresh instance
starts with no venues at all (D10). That is fine for the developer, who has a
local database, and useless for anyone opening the link — the first thing they
would see is an empty dashboard and no way to judge whether the tool does
anything.

Seeding only happens when there are no venues. A venue someone drew is never
overwritten, and a restart never produces duplicates.

The files are ASCII plans rather than JSON, because the point of an example is
that a person can read it and a grid of digits is not readable. Lines starting
with a hash followed by a space are comments, and the first of them is the
venue's name. Grid rows never contain spaces, so a wall row of hashes is never
mistaken for a comment.
"""

from pathlib import Path

VENUES_DIR = Path(__file__).parent / "venues"

CHAR_TO_CODE = {".": "0", "#": "1", "B": "2", "N": "3", "E": "4", "S": "5",
                "C": "6"}
CODE_TO_CHAR = {code: char for char, code in CHAR_TO_CODE.items()}


def _is_comment(line: str) -> bool:
    return not line.strip() or line.startswith("# ") or line.rstrip() == "#"


def parse(text: str, fallback_name: str) -> dict:
    """One plan file to a venue dict. Raises ValueError on anything malformed."""
    lines = text.splitlines()

    name = fallback_name
    for line in lines:
        if line.startswith("# "):
            name = line[2:].strip()
            break

    rows = [line.rstrip() for line in lines if not _is_comment(line)]
    if not rows:
        raise ValueError("no grid rows")

    width = len(rows[0])
    ragged = [i for i, row in enumerate(rows) if len(row) != width]
    if ragged:
        raise ValueError(f"rows {ragged} are not {width} characters wide")

    unknown = {c for row in rows for c in row} - set(CHAR_TO_CODE)
    if unknown:
        raise ValueError(f"unknown characters: {', '.join(sorted(unknown))}")

    return {
        "name": name,
        "width": width,
        "height": len(rows),
        "cells": "".join(CHAR_TO_CODE[c] for row in rows for c in row),
    }


def load_examples(directory: Path = VENUES_DIR) -> list[dict]:
    """Every example plan, in filename order so seeding is reproducible."""
    venues = []
    for path in sorted(directory.glob("*.txt")):
        try:
            venues.append(parse(path.read_text(encoding="utf-8"), path.stem))
        except ValueError as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
    return venues


def seed_if_empty(app) -> int:
    """Load the examples if there are no venues. Returns how many were added."""
    from ..db import repository

    with app.app_context():
        if repository.count_venues():
            return 0

        added = 0
        for venue in load_examples():
            try:
                repository.create_venue(**venue)
                added += 1
            except Exception:
                # A broken example is not worth refusing to start over: it would
                # take the whole deployment down for the sake of a demo venue.
                app.logger.exception("Could not seed example venue %r", venue["name"])
        if added:
            app.logger.info("Seeded %d example venues", added)
        return added


def to_ascii(venue: dict) -> str:
    """A stored venue back to a plan file, for turning something drawn in the
    editor into a new example."""
    cells = venue["cells"]
    width = venue["width"]
    rows = [cells[i:i + width] for i in range(0, len(cells), width)]
    body = "\n".join("".join(CODE_TO_CHAR[c] for c in row) for row in rows)
    return f"# {venue['name']}\n{body}\n"
