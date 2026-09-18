"""Turning advice into a plan.

The recommendations say what to change. This makes the change, so the suggestion
can be run rather than read — which matters, because an estimate derived from
one run is a much weaker thing than a second run.

Only the advice that is a change to the *plan* can be drawn. Signage, marshals
and capping attendance are all real recommendations and none of them is a wall,
so they are passed through as notes rather than silently dropped.

Nothing here decides what is worth doing. That judgement was made by the rules
in recommendations.py; this only draws the result.
"""

from ..cells import BARRIER, EXIT, FLOOR, WALL
from ..engine.grid import Grid
from ..engine.layout import inspect

# How far to look along a wall when widening a doorway.
MAX_WIDEN_REACH = 8


class _Plan:
    """A mutable copy of a venue's cells, with a record of what was changed."""

    def __init__(self, grid: Grid):
        self.width = grid.width
        self.height = grid.height
        self.cells = list(grid.cells)
        self.grid = grid
        self.changes: list[dict] = []
        self.touched: set[tuple[int, int]] = set()

    def at(self, x: int, y: int) -> str | None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        return self.cells[y * self.width + x]

    def set(self, x: int, y: int, code: str) -> bool:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        index = y * self.width + x
        if self.cells[index] == code:
            return False
        self.cells[index] = code
        self.touched.add((x, y))
        return True

    def note(self, title: str, detail: str) -> None:
        self.changes.append({"title": title, "detail": detail, "drawn": True})

    def as_string(self) -> str:
        return "".join(self.cells)


def improve(grid: Grid, recommendations: list[dict]) -> dict | None:
    """A version of the venue with the buildable advice applied.

    Returns None when nothing could be drawn, so the caller can tell the
    difference between "no changes" and "changes that are not plan changes".
    """
    plan = _Plan(grid)
    notes: list[dict] = []

    for item in recommendations:
        drawn = _apply(plan, item)
        if not drawn:
            notes.append({
                "title": item["title"],
                "detail": item["action"],
                "drawn": False,
            })

    if not plan.changes:
        return None

    # A proposal that cannot be simulated is worse than no proposal. It should
    # not happen — every change here either adds exit width or opens a
    # passage — but handing somebody an unusable plan would be a very
    # confusing way to find out otherwise.
    candidate = Grid(plan.width, plan.height, plan.as_string())
    report = inspect(candidate)
    if not report["ok"]:
        return None

    return {
        "width": plan.width,
        "height": plan.height,
        "cells": plan.as_string(),
        "changed_cells": sorted(list(cell) for cell in plan.touched),
        "changes": plan.changes + notes,
    }


def _apply(plan: _Plan, item: dict) -> bool:
    title = item["title"]
    evidence = item.get("evidence") or {}

    if title.startswith("Widen exit") or title.startswith("Widen entrance"):
        return _widen_doorway(plan, item, evidence)
    if "entrance is not being used as an exit" in title:
        return _open_entrances_as_exits(plan, evidence)
    if "gap at" in title:
        return _widen_gap(plan, evidence)
    return False


def _widen_doorway(plan: _Plan, item: dict, evidence: dict) -> bool:
    """Extend a doorway along its own wall.

    A doorway runs in a line, so it is widened by converting the wall cells at
    either end of that line. Growing from both ends keeps it centred on where
    it was, which matters: a door that creeps sideways is a different door, and
    the approach to it changes with it.
    """
    door_id = evidence.get("exit_id")
    wanted = evidence.get("proposed_width")
    is_exit = "exit" in item["title"]
    doorways = plan.grid.exits if is_exit else plan.grid.entrances
    door = next((d for d in doorways if d.id == door_id), None)
    if door is None or not wanted or wanted <= door.width:
        return False

    code = EXIT if is_exit else plan.at(*door.cells[0])
    cells = sorted(door.cells)
    horizontal = len({y for _, y in cells}) == 1
    axis = (1, 0) if horizontal else (0, 1)

    added = 0
    low, high = cells[0], cells[-1]
    for step in range(1, MAX_WIDEN_REACH + 1):
        if door.width + added >= wanted:
            break
        for anchor, direction in ((high, 1), (low, -1)):
            if door.width + added >= wanted:
                break
            x = anchor[0] + axis[0] * step * direction
            y = anchor[1] + axis[1] * step * direction
            if plan.at(x, y) != WALL:
                continue
            if plan.set(x, y, code):
                added += 1

    if not added:
        return False

    word = "Exit" if is_exit else "Entrance"
    plan.note(
        f"{word} {door_id} widened from {door.width} m to {door.width + added} m",
        f"{added} m of wall either side of it opened up.",
    )
    return True


def _open_entrances_as_exits(plan: _Plan, evidence: dict) -> bool:
    """Mark the entrances as exits too.

    The cheapest change in the whole set, because it is not building work: the
    doors are already there and already wide enough. Whether they can be opened
    outwards in an evacuation is a question for whoever owns the building, and
    the recommendation says so.
    """
    changed = 0
    for x, y in plan.grid.entrance_cells:
        if plan.set(x, y, EXIT):
            changed += 1
    if not changed:
        return False
    plan.note(
        f"{changed} m of entrance marked as exit",
        "No building work: the doors exist and are wide enough already.",
    )
    return True


def _widen_gap(plan: _Plan, evidence: dict) -> bool:
    """Open out a constriction.

    Widened across the narrow axis, because that is the one doing the
    constricting. Barriers go before walls: a barrier is furniture and a wall
    is a building, and the cheaper change is worth offering first.
    """
    at = evidence.get("at")
    if not at:
        return False
    x, y = at

    horizontal = _run_length(plan, x, y, 1, 0)
    vertical = _run_length(plan, x, y, 0, 1)
    axis = (1, 0) if horizontal <= vertical else (0, 1)

    # Barriers first, then walls, and only one cell each side, because a
    # suggestion that demolishes half the venue is not a suggestion.
    opened = 0
    for code in (BARRIER, WALL):
        for direction in (1, -1):
            nx = x + axis[0] * direction
            ny = y + axis[1] * direction
            # Never the outer shell. A proposal that opens a hole in the side
            # of the building is not a proposal.
            if nx in (0, plan.width - 1) or ny in (0, plan.height - 1):
                continue
            if plan.at(nx, ny) != code:
                continue
            if plan.set(nx, ny, FLOOR):
                opened += 1
                break
        if opened:
            break

    if not opened:
        return False

    was = min(horizontal, vertical)
    plan.note(
        f"Gap at {x}, {y} widened from {was} m to {was + opened} m",
        "The narrower side of the passage opened out by one metre.",
    )
    return True


def _run_length(plan: _Plan, x: int, y: int, dx: int, dy: int) -> int:
    """Contiguous walkable cells through (x, y) along one axis."""
    from ..cells import WALKABLE

    length = 1
    for direction in (1, -1):
        step = 1
        while True:
            cell = plan.at(x + dx * step * direction, y + dy * step * direction)
            if cell not in WALKABLE:
                break
            length += 1
            step += 1
    return length
