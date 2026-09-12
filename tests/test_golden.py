"""The golden run.

Determinism is checked elsewhere by running the same thing twice in one
process. That catches accidental randomness but not a change in behaviour: two
runs of a subtly different engine still agree with each other.

This pins the engine to a specific answer. If a refactor changes any agent's
position on any tick, the digest moves and this fails. That is the point — the
comparison feature is meaningless if the same venue quietly evacuates
differently after an unrelated change.

If a change to the engine is deliberate, regenerate with:

    python -m tests.test_golden

and commit the new digest with an explanation of what changed and why.
"""

import hashlib
import json
from pathlib import Path

from app.engine.grid import Grid
from app.engine.simulation import SimulationConfig, simulate

GOLDEN_PATH = Path(__file__).parent / "scenarios" / "golden.json"

# A hall with a pillar, a corridor and two doors of different widths: enough
# structure that routing, queueing and exit choice all matter.
LAYOUT = """
##################
#SSSSSS....#.....#
#SSSSSS.##.#..#..#
#SSSSSS.##....#..#
#SSSSSS.......#..E
#SSSSSS....#..#..#
#..........#.....#
#..........#.....#
##########EE######
"""

CHARS = {".": "0", "#": "1", "B": "2", "N": "3", "E": "4", "S": "5"}
CONFIG = {"num_agents": 60, "speed": 1.0, "cell_capacity": 3,
          "max_ticks": 600, "seed": 42, "routing": "nearest", "reroute": True}

# History of deliberate changes to this digest:
#   Day 9 — rerouting added. Agents now leave a route they are stuck on, so
#           the same venue evacuates differently and faster. Regenerated.
#   Day 14 — density now records when each cell was crowded as well as for how
#            long. The tick loop is unchanged; the digest covers the trace only,
#            so this did not move it.
#   Day 9 — exit-choice cost changed from walk + queue to max(walk, queue).
#           The sum treated everyone assigned to a door as already standing at
#           it, so it avoided queues that drain long before most of the crowd
#           arrives. Regenerated.


def _grid() -> Grid:
    rows = [line for line in LAYOUT.strip().splitlines() if line]
    cells = "".join(CHARS[char] for row in rows for char in row)
    return Grid(len(rows[0]), len(rows), cells)


def _run() -> dict:
    grid = _grid()
    result = simulate(grid, SimulationConfig(**CONFIG))
    digest = hashlib.sha256(
        json.dumps(result.trace, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "config": CONFIG,
        "status": result.status,
        "ticks": result.ticks,
        "clearing_ticks": result.clearing_ticks,
        "evacuated": result.evacuated,
        "stranded": result.stranded,
        "exit_usage": {str(k): v for k, v in result.exit_usage.items()},
        "trace_sha256": digest,
    }


def test_the_golden_run_has_not_changed():
    expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    actual = _run()
    assert actual["trace_sha256"] == expected["trace_sha256"], (
        "The engine now produces a different evacuation for the same venue, "
        "config and seed. If that change was intended, regenerate the golden "
        "file; if not, something has become non-deterministic."
    )
    assert actual == expected


if __name__ == "__main__":
    GOLDEN_PATH.write_text(json.dumps(_run(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {GOLDEN_PATH}")
