"""Print the calibration table.

    python calibrate.py

Shows every reference venue with its score, grade, expected band and the
penalties that produced it. This is the view used to tune the thresholds in
app/analysis/score.py — the corresponding test asserts the bands hold.
"""

import sys

from app.analysis.bottlenecks import detect
from app.analysis.metrics import compute
from app.analysis.recommendations import recommend
from app.analysis.score import score
from app.engine.layout import inspect
from app.engine.simulation import SimulationConfig, simulate

sys.path.insert(0, "tests")
from reference_venues import SCENARIOS, build, in_band  # noqa: E402


def assess(scenario: dict) -> dict:
    grid = build(scenario)
    settings = {
        "num_agents": scenario["agents"], "speed": 1.0, "cell_capacity": 3,
        "max_ticks": 600, "seed": 42, "routing": "nearest", "reroute": True,
        "entrances_are_exits": False,
    }
    result = simulate(grid, SimulationConfig(**settings))
    metrics = compute(grid, result, settings, inspect(grid)["longest_walk"])
    findings = detect(grid, result.density)
    return {
        "metrics": metrics,
        "assessment": score(metrics),
        "advice": recommend(grid, metrics, findings, settings),
    }


def main() -> None:
    header = f"{'venue':30} {'people':>6} {'clear':>7} {'ratio':>6} {'score':>5} {'got':>4} {'want':>6}"
    print(header)
    print("-" * len(header))

    failures = []
    for scenario in SCENARIOS:
        out = assess(scenario)
        time = out["metrics"]["time"]
        assessment = out["assessment"]
        band = scenario["expect"]
        ok = in_band(assessment["grade"], band)
        if not ok:
            failures.append((scenario["name"], assessment["grade"], band))

        clearing = time["clearing_seconds"]
        print(
            f"{scenario['name'][:30]:30} {scenario['agents']:6} "
            f"{(f'{clearing:.0f}s' if clearing else '—'):>7} "
            f"{str(time['time_ratio'] or '—'):>6} "
            f"{assessment['score']:5} {assessment['grade']:>4} "
            f"{band[0] + '–' + band[1]:>6} {'' if ok else '  <-- outside band'}"
        )

        penalties = "  ".join(
            f"{c['name'][:4]} -{c['penalty']:.0f}" for c in assessment["components"]
        )
        top = out["advice"][0]["title"] if out["advice"] else "nothing to suggest"
        print(f"{'':30} {penalties}   |  {top}")

    print()
    if failures:
        for name, grade, band in failures:
            print(f"outside band: {name} graded {grade}, expected {band[0]}–{band[1]}")
        raise SystemExit(1)
    print("all venues inside their bands")


if __name__ == "__main__":
    main()
