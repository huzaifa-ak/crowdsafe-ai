"""The cell vocabulary.

A venue's grid is stored as one flat string of digits, row-major, so a 5x3 room
is 15 characters. One digit per cell keeps venues small enough to send in a
single request and simple enough to diff by eye in tests.

Both the API validators and the simulation engine read their codes from here so
there is only ever one definition of what a 4 means.
"""

FLOOR = "0"
WALL = "1"
BARRIER = "2"
ENTRANCE = "3"
EXIT = "4"
SPAWN = "5"

CELL_NAMES = {
    FLOOR: "floor",
    WALL: "wall",
    BARRIER: "barrier",
    ENTRANCE: "entrance",
    EXIT: "exit",
    SPAWN: "spawn",
}

VALID_CODES = frozenset(CELL_NAMES)

# Cells an agent may stand on. Walls and barriers are solid; barriers exist as a
# separate code so the editor can distinguish structure from furniture, and so
# recommendations can suggest moving a barrier but never a wall.
WALKABLE = frozenset({FLOOR, ENTRANCE, EXIT, SPAWN})

# Rendering order for the editor legend, coarse structure first.
PALETTE_ORDER = (FLOOR, WALL, BARRIER, SPAWN, EXIT, ENTRANCE)


def invalid_codes(cells: str) -> set[str]:
    """Characters in `cells` that are not part of the vocabulary."""
    return set(cells) - VALID_CODES


def count_by_code(cells: str) -> dict[str, int]:
    """How many cells of each kind, keyed by name. Always includes every kind."""
    counts = {name: 0 for name in CELL_NAMES.values()}
    for char in cells:
        name = CELL_NAMES.get(char)
        if name is not None:
            counts[name] += 1
    return counts


def to_rows(cells: str, width: int) -> list[str]:
    """Split the flat string into rows, top to bottom."""
    return [cells[i:i + width] for i in range(0, len(cells), width)]


def at(cells: str, width: int, x: int, y: int) -> str:
    return cells[y * width + x]
