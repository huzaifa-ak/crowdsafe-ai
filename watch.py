"""Watch a simulation run in the terminal.

Not part of the app — a scratch tool for eyeballing the engine before there is
a UI. Run with `python watch.py`.
"""

import os
import time

from app.engine.grid import Grid
from app.engine.simulation import SimulationConfig, simulate

LAYOUT = """
##################
#SSSSSS....#.....#
#SSSSSS....#.....#
#SSSSSS....#.....#
#SSSSSS..........#
#SSSSSS....#.....#
#..........#.....#
#..........#.....#
##########EE######
"""

CHARS = {".": "0", "#": "1", "B": "2", "N": "3", "E": "4", "S": "5"}
SHADE = " ·:*#"  # 0, 1, 2, 3+ people in a cell


def build(layout: str) -> Grid:
    rows = [line for line in layout.strip().splitlines() if line]
    cells = "".join(CHARS[char] for row in rows for char in row)
    return Grid(len(rows[0]), len(rows), cells)


def frame(grid: Grid, positions: list[int]) -> str:
    counts: dict[tuple[int, int], int] = {}
    for x, y in zip(positions[0::2], positions[1::2]):
        counts[(x, y)] = counts.get((x, y), 0) + 1

    lines = []
    for y in range(grid.height):
        row = ""
        for x in range(grid.width):
            here = counts.get((x, y), 0)
            if here:
                row += SHADE[min(here, len(SHADE) - 1)]
            else:
                cell = grid.at(x, y)
                row += {"1": "█", "2": "▒", "4": "▓", "5": "‧"}.get(cell, " ")
        lines.append(row)
    return "\n".join(lines)


def main() -> None:
    grid = build(LAYOUT)
    config = SimulationConfig(num_agents=60, speed=1.0, cell_capacity=3,
                              max_ticks=600, seed=42)
    result = simulate(grid, config)

    for tick, positions in enumerate(result.trace):
        os.system("cls" if os.name == "nt" else "clear")
        print(frame(grid, positions))
        remaining = len(positions) // 2
        print(f"\ntick {tick:3d}   {remaining:3d} still inside   "
              f"{result.agent_count - remaining:3d} out")
        time.sleep(0.06)

    seconds = (result.clearing_ticks or result.ticks) * 0.7
    floor = result.agent_count / grid.total_exit_width
    print(f"\nstatus       {result.status}")
    print(f"cleared in   {result.clearing_ticks} ticks ({seconds:.0f} s)")
    print(f"exit width   {grid.total_exit_width} m")
    print(f"floor        {floor:.0f} ticks — the fastest this door could ever manage")
    print(f"exit usage   {result.exit_usage}")


if __name__ == "__main__":
    main()
