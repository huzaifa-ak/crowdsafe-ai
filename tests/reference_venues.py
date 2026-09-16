"""Reference venues.

A fixed set of layouts spanning the range from "obviously fine" to "obviously
dangerous", each with the grade band a person would give it. The thresholds in
app/analysis/score.py are tuned against this set, and the calibration test
fails if any venue leaves its band.

The bands are deliberately wide. The claim being made is not that a particular
venue scores 71; it is that a hall with generous exits and a modest crowd
outranks a hall with one narrow door and a large one, and that neither ends up
in the wrong half of the scale. A score precise enough to defend to the decimal
would be a score fitted to these eight layouts rather than to reality.

`python calibrate.py` prints the table.
"""

CHARS = {".": "0", "#": "1", "B": "2", "N": "3", "E": "4", "S": "5"}


def _grid(layout: str):
    rows = [line.strip() for line in layout.strip().splitlines() if line.strip()]
    width = len(rows[0])
    assert all(len(row) == width for row in rows), "ragged layout"
    return width, len(rows), "".join(CHARS[c] for row in rows for c in row)


SCENARIOS = [
    {
        "name": "Small room, small crowd",
        "why": "Twenty people, a 2 m door, nowhere to get stuck.",
        "agents": 20,
        "expect": ("A", "A"),
        "layout": """
            ##########
            #SSSS....#
            #SSSS....#
            #SSSS....#
            #........#
            ####EE####
        """,
    },
    {
        "name": "Hall with generous exits",
        "why": "9 m of door for 120 people, short walks, no obstructions.",
        "agents": 120,
        "expect": ("A", "B"),
        "layout": """
            ######################
            #....................#
            #.SSSSSSSS.SSSSSSSS..#
            #.SSSSSSSS.SSSSSSSS..#
            #.SSSSSSSS.SSSSSSSS..#
            #....................#
            EEEE#########EEEEE####
        """,
    },
    {
        "name": "Hall at capacity",
        "why": "Same doors, nearly twice the crowd.",
        "agents": 200,
        "expect": ("B", "D"),
        "layout": """
            ######################
            #.SSSSSSSSSSSSSSSSSS.#
            #.SSSSSSSSSSSSSSSSSS.#
            #.SSSSSSSSSSSSSSSSSS.#
            #.SSSSSSSSSSSSSSSSSS.#
            #....................#
            EEEE#########EEEEE####
        """,
    },
    {
        "name": "Lopsided doors",
        "why": "Two equal doors, but the crowd is bunched at one end.",
        "agents": 120,
        "expect": ("B", "D"),
        "layout": """
            ######################
            #SSSSSSSSSSSS........#
            #SSSSSSSSSSSS........#
            #SSSSSSSSSSSS........#
            #SSSSSSSSSSSS........#
            E....................E
            ######################
        """,
    },
    {
        "name": "Pinched corridor",
        "why": "Everyone must pass a 2 m gap to reach the only door.",
        "agents": 110,
        "expect": ("C", "F"),
        "layout": """
            ######################
            #SSSSSSSS............#
            #SSSSSSSS............#
            #SSSSSSSS............#
            #SSSSSSSS............#
            #SSSSSSSS............#
            #########..###########
            #####................#
            #####................#
            #####...............E#
            ######################
        """,
    },
    {
        "name": "Long thin venue",
        "why": ("Walking distance is the limit; the doors are fine. Sixty people "
                "out in under a minute is a safe evacuation, so this grades well "
                "even though the far corner is a long way from a door — that is a "
                "recommendation, not a penalty. The band was originally B–D, set "
                "when the free-flow ratio was still scored and was inflating the "
                "time penalty on any venue with generous exits."),
        "agents": 60,
        "expect": ("A", "C"),
        "layout": """
            ##############################
            #SSSSSS......................#
            #SSSSSS......................#
            #SSSSSS......................#
            #SSSSSS......................#
            ############################EE
            ##############################
        """,
    },
    {
        "name": "One narrow door",
        "why": "120 people through 1 m of exit.",
        "agents": 120,
        "expect": ("D", "F"),
        "layout": """
            ######################
            #SSSSSSSSSSSS........#
            #SSSSSSSSSSSS........#
            #SSSSSSSSSSSS........#
            #SSSSSSSSSSSS........#
            ##########E###########
        """,
    },
    {
        "name": "Part of the floor is sealed off",
        "why": "A third of the crowd has no route to any exit.",
        "agents": 45,
        "expect": ("F", "F"),
        "layout": """
            ###############
            #SSS#....SSSSS#
            #SSS#....SSSSSE
            #SSS#....SSSSS#
            ###############
        """,
    },
]

GRADE_ORDER = "ABCDF"


def build(scenario: dict):
    from app.engine.grid import Grid

    width, height, cells = _grid(scenario["layout"])
    return Grid(width, height, cells)


def in_band(grade: str, band: tuple[str, str]) -> bool:
    low, high = band
    return GRADE_ORDER.index(low) <= GRADE_ORDER.index(grade) <= GRADE_ORDER.index(high)
