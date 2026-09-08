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

Exit-choice cost combines the walk and the queue as a **maximum**, not a sum.
An agent leaves once it has both arrived and outlasted the queue, whichever
happens later. The first version added the two terms, which treats everyone
assigned to a door as already standing at it — so it fled queues that drain
long before most of the crowd arrives, and made `balanced` slower than
`nearest` on any venue where walking dominates. This is the same reasoning as
correction 1 above, applied to a different formula.

Measured on two venues that fail for different reasons:

| Model | Lopsided hall (queue-bound) | Three spread doors (walk-bound) |
|---|---|---|
| nearest, no reroute | 127 | 48 |
| nearest + reroute | 74 | 38 |
| balanced, no reroute | 75 | 48 |

The point of the second column is that `balanced` does no harm there. A model
that helps when queues are the constraint and is neutral when they are not is
the one worth shipping.

The golden digest was regenerated twice for this day's work; both reasons are
recorded in `tests/test_golden.py`.

**Day 12 — three score components, not four.** The plan had bottlenecks as a
separate axis. A venue with one narrow door already trips the time, congestion
and exit penalties, so a fourth would punish the same fault a fourth time and
bunch every imperfect venue at the bottom. Bottlenecks are reported as findings
with locations instead, which is more actionable than another subtraction. This
resolves the double-counting concern raised before Day 1.

**Day 12 — the time penalty is mostly absolute.** Measured on a crowd sweep, a
score driven by the free-flow ratio *rose* as the crowd grew past the point
where the doors became the binding limit, because the baseline grows with the
crowd. It also flattered bad venues: somewhere with one narrow door has such a
slow theoretical best that matching it looks efficient. Absolute clearing time
now carries 25 of the 35 points and the ratio carries 10, summed rather than
taking the worse of the two — a venue that clears in a minute is not dangerous
merely for being inefficient about it.

Calibration measured on three venues at 150 people:

| Venue | Score | Time | Congestion | Exits |
|---|---|---|---|---|
| 9 m of exits | 69 (C) | −10 | −16 | −6 |
| Two 1 m doors, lopsided | 61 (C) | −6 | −24 | −9 |
| One 1 m door | 38 (F) | −7 | −40 | −15 |

At 40 people all three grade A, which is correct: forty people leaving through
one door is genuinely fine, and a score that condemned it would be measuring
the layout rather than the risk.

Open for Day 15: the free-flow ratio still treats a venue with excellent exits
harshly, because its theoretical best is so fast that any overhead looks large.
Its weight is capped at 10 points, which bounds the damage, but a baseline that
accounted for how long a dense spawn area takes to disperse would be better.
