"""Density accumulators.

Two things need recording as a run proceeds: how busy each cell was overall,
and how tightly packed each part of the room got at its worst.

The obvious implementation walks all 4,800 cells every tick and averages a 3x3
window around each. At 600 ticks that is roughly 26 million window lookups in
CPython — tens of seconds, dwarfing everything else the engine does.

Occupancy is sparse. There are at most 300 agents, so at most 300 occupied
cells, and every cell with a non-zero window sum is within one step of one of
them. So instead of reading outwards from every cell, this pushes outwards from
the occupied ones: about 2,700 additions per tick regardless of how big the
venue is. Same numbers, two orders of magnitude less work.

(docs/decisions.md, correction 2.)
"""

from .grid import Grid

# People per square metre at which movement is meaningfully impeded. Real crowd
# guidance puts free movement below about 2 and serious risk above 4; the
# engine's own cap is 3 per cell, so 2.0 is the useful warning line here.
# Revisited during tuning on Day 15.
DENSITY_THRESHOLD = 2.0


class DensityAccumulator:
    def __init__(self, grid: Grid):
        self.grid = grid
        self.width = grid.width
        size = grid.width * grid.height

        # Total agent-ticks spent in each cell. This is the heatmap: a cell
        # holding two people for fifty ticks scores the same as one holding
        # fifty people for two, which is what "how busy was this spot" means.
        self.visits = [0] * size

        # Peak 3x3 average occupancy, and how long each cell spent over the
        # threshold. Peak finds the worst moment; duration separates a brief
        # surge from a sustained crush, which matter differently.
        self.peak_density = [0.0] * size
        self.ticks_above = [0] * size

        # When each cell first and last went over the threshold. Without these
        # the accumulator cannot tell a crowd that starts packed from a queue
        # that builds: both look like "crowded for N ticks". Two more arrays,
        # and the difference decides whether a finding is a bottleneck or an
        # artefact of how many people were placed in the spawn area.
        self.first_crowded = [-1] * size
        self.last_crowded = [-1] * size
        self.tick = 0

        # Walkable cells within each cell's 3x3 window, precomputed once. A
        # window against a wall covers fewer cells, and dividing by 9 there
        # would understate the density in exactly the corners where crowding
        # is worst.
        self._window: list[list[int]] = []
        self._window_size: list[int] = []
        for y in range(grid.height):
            for x in range(grid.width):
                cells = [
                    ny * grid.width + nx
                    for ny in range(max(0, y - 1), min(grid.height, y + 2))
                    for nx in range(max(0, x - 1), min(grid.width, x + 2))
                    if grid.is_walkable(nx, ny)
                ]
                self._window.append(cells)
                self._window_size.append(len(cells))

    def record(self, occupancy: list[int], occupied: list[int], tick: int = 0) -> None:
        """Fold one tick into the accumulators.

        `occupied` is the indices of cells holding at least one agent — the
        caller already knows them, and rediscovering them here would undo the
        point of the exercise.
        """
        window_sums: dict[int, int] = {}
        window = self._window
        visits = self.visits

        for index in occupied:
            count = occupancy[index]
            visits[index] += count
            for neighbour in window[index]:
                window_sums[neighbour] = window_sums.get(neighbour, 0) + count

        peak = self.peak_density
        above = self.ticks_above
        sizes = self._window_size
        for index, total in window_sums.items():
            density = total / sizes[index]
            if density > peak[index]:
                peak[index] = density
            if density >= DENSITY_THRESHOLD:
                above[index] += 1
                if self.first_crowded[index] < 0:
                    self.first_crowded[index] = tick
                self.last_crowded[index] = tick

    def as_dict(self) -> dict:
        """Flat arrays in the same row-major order as the cell string, so the
        browser can index them against the grid without a lookup table."""
        return {
            "width": self.grid.width,
            "height": self.grid.height,
            "visits": self.visits,
            "peak_density": [round(v, 2) for v in self.peak_density],
            "ticks_above_threshold": self.ticks_above,
            "first_crowded_tick": self.first_crowded,
            "last_crowded_tick": self.last_crowded,
            "threshold": DENSITY_THRESHOLD,
        }
