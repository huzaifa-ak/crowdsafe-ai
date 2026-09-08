# Decisions

Locked before Day 1. Changing any of these mid-build means changing tests and
stored results, so they are recorded here rather than argued twice.

## Architecture

| # | Decision | Reason |
|---|----------|--------|
| D1 | The tick loop runs in Python on the server. JavaScript is the editor, playback and rendering only. The server returns a full per-tick trace and the browser replays it. | One source of truth for grid semantics; deterministic and testable; comparison needs reproducible runs. |
| D2 | Cell = 1 m × 1 m. Tick = 0.7 s (base walking speed ≈ 1.4 m/s). | Densities come out in people/m², which maps onto real crowd-safety thresholds. |
| D3 | Cell capacity defaults to 3 people, configurable 1–5. | Free movement breaks down around 3 p/m², so congestion emerges rather than being scripted. |
| D4 | 4-neighbour movement, no diagonals. | Matches "one grid square at a time" and avoids corner-cutting through walls. |
| D5 | Every run takes a seed. Same venue + config + seed produces identical results. | Required for comparison and for golden tests. |
| D6 | Each exit cell admits one agent per tick (≈ 1.4 people/m/s). | Without a flow cap, exits never bottleneck. |
| D7 | Entrances are walkable and visually distinct but are not exits, unless `entrances_are_exits` is set. | The spec separates entrances from exits. People arriving over time is a later addition. |
| D8 | Grid ≤ 80 × 60, agents ≤ 300, ticks ≤ 600. Enforced server-side. | Keeps runtime and trace size within budget. |
| D9 | Metrics, heatmaps, bottlenecks and recommendations stored as JSON; the trace as a compressed blob. | Saved runs can be replayed and compared later. |
| D10 | Hosted on Render, auto-deploying from `main`. | Auto-deploy was worth more than persistence; example venues are seeded on boot so an ephemeral database is still demo-ready. |
| D11 | Exits may be placed anywhere, not only on the boundary. | Stairwell and lobby doors are real cases, and exits are already handled as connected components. |
| D12 | The trace is persisted, not just the metrics. | Roughly 150 KB gzipped, and replaying a saved run is most of the demo. |

## Corrections to the first draft of the plan

Six things were wrong or unspecified in the implementation plan and are fixed
here before any code depends on them.

1. **Free-flow baseline must account for throughput.** The longest walking
   distance alone ignores the fact that 300 people cannot pass through a 1 m
   door faster than one per tick. Use:

   ```
   free_flow_ticks = max(longest_bfs_distance / speed,
                         num_agents / total_enabled_exit_width)
   ```

   Otherwise `time_ratio` saturates the time penalty for every narrow-exit
   venue regardless of how good the rest of the layout is.

2. **Density accumulators iterate agents, not cells.** Computing a 3×3 window
   density for all 4,800 cells on every tick is ~52M operations per run in
   CPython. Occupancy is sparse — at most 300 occupied cells — so update only
   the windows around occupied cells. This, not A*, is the real performance
   risk.

3. **Speed is capped at one cell per tick.** Movement credit is clamped to 1.0,
   so `speed` acts purely as a slowdown factor and the valid range is 0.5–1.0.
   The earlier 0.5–1.5 range had no effect above 1.0.

4. **`max_ticks` capped at 600, not 1200.** At 300 agents, 1,200 ticks produces
   a ~2.9 MB raw trace against a 2 MB budget. 600 ticks is seven minutes of
   simulated evacuation, which is long enough.

5. **Exit imbalance is weighted by exit width.** A 3 m exit next to a 1 m exit
   *should* carry three quarters of the crowd. Compare each exit's share
   against its capacity share, not against an even split.

6. **Two determinism leaks to close.** The A* priority queue needs an explicit
   tiebreaker counter so equal f-scores never compare payloads, and initial
   path planning must happen in the seeded shuffle order because
   `planned_usage` grows as each agent plans.

## Behaviour changes

**Day 9 — rerouting and the balanced routing model.** Agents now abandon a
route they have been stuck on for eight ticks, subject to a twenty-tick
cooldown, and reconsider which door to head for. The queue for a door is
measured as the number of people still heading for it divided by its width —
the wait in ticks — rather than by how full the cells at the doorway are, which
cannot tell a queue of a hundred from a queue of three.

Exit assignment gained a second model. `nearest` is unchanged and remains the
default: people walk to the closest door and ignore how busy it is, which is
what an unsignposted crowd does and what exposes a lopsided layout. `balanced`
adds the expected wait to the walk, modelling marshals or clear signage.
Running one layout both ways measures what crowd management alone is worth.

Measured on a hall with two equal doors and the crowd bunched at one end:

| Model | Clearing ticks | Exit split |
|---|---|---|
| nearest, no reroute | 127 | 120 / 0 |
| nearest + reroute | 77 | 76 / 44 |
| balanced | 72 | 62 / 58 |

The golden digest was regenerated for this change; the reason is recorded in
`tests/test_golden.py`.

Open for Day 15: a single narrow exit currently trips the time, density,
bottleneck and exit penalties at once, so a poor layout and a dangerous one can
both grade F. Decide then whether to cap the combined penalty.
