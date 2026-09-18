"""The grid, as the engine sees it.

The API stores a venue as a flat digit string; this turns that into something
that can answer questions — what is walkable, what is next to what, where the
exits are and how wide each one is.

Nothing here mutates. A Grid is built once per simulation run from the venue
snapshot and read many times, so it precomputes the cell lists it will be asked
for repeatedly rather than scanning the string each time.
"""

from dataclasses import dataclass

from ..cells import CHECKPOINT, ENTRANCE, EXIT, SPAWN, WALKABLE

# Fixed order, so any traversal that depends on neighbour order is reproducible
# from one run to the next. North, east, south, west.
NEIGHBOUR_OFFSETS = ((0, -1), (1, 0), (0, 1), (-1, 0))

Point = tuple[int, int]


@dataclass(frozen=True)
class Doorway:
    """One doorway: a contiguous run of cells of the same kind.

    Two exit cells side by side are one 2 m door, not two 1 m doors, and that
    distinction drives everything downstream — throughput, exit-usage share and
    the width-weighted imbalance measure.
    """

    id: int
    cells: tuple[Point, ...]

    @property
    def width(self) -> int:
        """Cells wide, which is also how many agents it passes per tick."""
        return len(self.cells)


# Exits were the only kind of doorway until arrivals were added. The name is
# kept so nothing that reads a result has to change.
Exit = Doorway


class Grid:
    def __init__(self, width: int, height: int, cells: str):
        if len(cells) != width * height:
            raise ValueError(
                f"Expected {width * height} cells for {width}x{height}, got {len(cells)}"
            )
        self.width = width
        self.height = height
        self.cells = cells

        self.spawn_cells = self._cells_matching(SPAWN)
        self.entrance_cells = self._cells_matching(ENTRANCE)
        self.exit_cells = self._cells_matching(EXIT)
        self.exits = self._group_into_doorways(self.exit_cells)
        self.entrances = self._group_into_doorways(self.entrance_cells)

        # Checkpoints are grouped the same way, because they are the same
        # thing: a run of cells that passes one person per cell per tick. A
        # four-cell security lane is one station of width four, not four
        # stations, and the distinction drives its throughput exactly as it
        # does for a door.
        self.checkpoint_cells = self._cells_matching(CHECKPOINT)
        self.checkpoints = self._group_into_doorways(self.checkpoint_cells)

        # Anywhere you can only get to by passing a checkpoint. Worked out from
        # the plan rather than painted separately: a restricted area *is* the
        # part of the building behind the security line, and asking someone to
        # mark it twice would just be a way for the two to disagree.
        self.restricted_cells = self._find_restricted()
        self.restricted_spawn_cells = [
            cell for cell in self.spawn_cells if cell in self.restricted_cells
        ]
        self.general_spawn_cells = [
            cell for cell in self.spawn_cells if cell not in self.restricted_cells
        ]

    @classmethod
    def from_venue(cls, venue: dict) -> "Grid":
        return cls(venue["width"], venue["height"], venue["cells"])

    # Cell access ------------------------------------------------------------

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def at(self, x: int, y: int) -> str:
        return self.cells[y * self.width + x]

    def is_walkable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.cells[y * self.width + x] in WALKABLE

    def neighbours(self, x: int, y: int) -> list[Point]:
        """Walkable four-neighbours, always in the same order."""
        found = []
        for dx, dy in NEIGHBOUR_OFFSETS:
            nx, ny = x + dx, y + dy
            if self.is_walkable(nx, ny):
                found.append((nx, ny))
        return found

    def _cells_matching(self, code: str) -> list[Point]:
        """Every cell of one kind, in row-major order."""
        found = []
        start = 0
        while True:
            index = self.cells.find(code, start)
            if index == -1:
                return found
            found.append((index % self.width, index // self.width))
            start = index + 1

    # Exits ------------------------------------------------------------------

    def _group_into_doorways(self, cells: list[Point]) -> list[Doorway]:
        """Group adjacent cells of one kind into doorways.

        Components are numbered in row-major order of their topmost-leftmost
        cell, so exit 1 is always the same doorway for the same venue — ids end
        up in saved results and in recommendations, and must not shuffle
        between runs.
        """
        remaining = set(cells)
        exits: list[Doorway] = []

        for cell in cells:  # already row-major
            if cell not in remaining:
                continue
            component: list[Point] = []
            stack = [cell]
            remaining.discard(cell)
            while stack:
                x, y = stack.pop()
                component.append((x, y))
                for dx, dy in NEIGHBOUR_OFFSETS:
                    neighbour = (x + dx, y + dy)
                    if neighbour in remaining:
                        remaining.discard(neighbour)
                        stack.append(neighbour)
            component.sort(key=lambda p: (p[1], p[0]))
            exits.append(Doorway(id=len(exits) + 1, cells=tuple(component)))

        return exits

    def _find_restricted(self) -> set[Point]:
        """Walkable cells unreachable from the public doors without a checkpoint.

        Flood the building from the entrances — or the exits, for a plan that
        has no entrances yet — treating checkpoint cells as solid. Whatever the
        flood cannot touch is behind the line.
        """
        if not self.checkpoints:
            return set()

        seeds = self.entrance_cells or self.exit_cells
        if not seeds:
            return set()

        blocked = set(self.checkpoint_cells)
        public = set()
        stack = [cell for cell in seeds if cell not in blocked]
        public.update(stack)

        while stack:
            x, y = stack.pop()
            for dx, dy in NEIGHBOUR_OFFSETS:
                neighbour = (x + dx, y + dy)
                if neighbour in public or neighbour in blocked:
                    continue
                if not self.is_walkable(*neighbour):
                    continue
                public.add(neighbour)
                stack.append(neighbour)

        everywhere = {
            (i % self.width, i // self.width)
            for i, cell in enumerate(self.cells) if cell in WALKABLE
        }
        return everywhere - public - blocked

    @property
    def total_checkpoint_width(self) -> int:
        """Combined width of every checkpoint, in cells."""
        return sum(station.width for station in self.checkpoints)

    @property
    def total_entrance_width(self) -> int:
        """Combined width of every entrance, in cells."""
        return sum(door.width for door in self.entrances)

    @property
    def total_exit_width(self) -> int:
        """Combined width of every exit, in cells.

        This is the venue's throughput ceiling: with one agent admitted per exit
        cell per tick, no evacuation can finish faster than
        `agent_count / total_exit_width` ticks however short the walk is.
        """
        return sum(exit_.width for exit_ in self.exits)

    def exit_for_cell(self, cell: Point) -> Doorway | None:
        for exit_ in self.exits:
            if cell in exit_.cells:
                return exit_
        return None

    def entrance_for_cell(self, cell: Point) -> Doorway | None:
        for door in self.entrances:
            if cell in door.cells:
                return door
        return None

    def checkpoint_for_cell(self, cell: Point) -> Doorway | None:
        for station in self.checkpoints:
            if cell in station.cells:
                return station
        return None
