"""Draw the example venues.

Run once to regenerate app/seed/venues/*.txt. Those files are the source of
truth and can be hand-edited afterwards; this exists because placing rectangles
by hand in a 48-column ASCII grid is a reliable way to introduce a
one-character wall nobody notices until the crowd walks through it.

    python tools/draw_examples.py
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "seed" / "venues"

WALL, FLOOR, BARRIER, ENTRANCE, EXIT, SPAWN, CHECKPOINT = "#", ".", "B", "N", "E", "S", "C"


class Plan:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.cells = [[FLOOR] * width for _ in range(height)]
        for x in range(width):
            self.cells[0][x] = WALL
            self.cells[height - 1][x] = WALL
        for y in range(height):
            self.cells[y][0] = WALL
            self.cells[y][width - 1] = WALL

    def rect(self, x0, y0, x1, y1, char):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.cells[y][x] = char
        return self

    def text(self, name, notes):
        head = [f"# {name}"] + [f"# {line}" for line in notes]
        return "\n".join(head + ["".join(row) for row in self.cells]) + "\n"


def arena():
    p = Plan(32, 20)
    # The court is solid. People do not evacuate across a playing surface, and
    # that is what makes the concourse a ring rather than a room.
    p.rect(10, 7, 21, 12, BARRIER)
    p.rect(8, 3, 23, 4, SPAWN)      # north stand
    p.rect(8, 15, 23, 16, SPAWN)    # south stand
    p.rect(3, 8, 4, 11, SPAWN)      # west stand
    p.rect(27, 8, 28, 11, SPAWN)    # east stand
    p.rect(15, 0, 16, 0, EXIT)
    p.rect(15, 19, 16, 19, EXIT)
    p.rect(0, 8, 0, 10, EXIT)
    p.rect(31, 8, 31, 10, EXIT)

    # Turnstile banks at two corners. Ways in, not ways out: a turnstile does
    # not work in reverse, which is exactly the distinction an entrance models.
    p.rect(3, 0, 5, 0, ENTRANCE)
    p.rect(26, 19, 28, 19, ENTRANCE)

    # A VIP box in the bottom-left concourse corner, walled off and reached
    # only through a two-cell checkpoint. The restricted area falls out of the
    # geometry: there is no way in that does not pass the security line.
    p.rect(1, 15, 6, 15, WALL)
    p.rect(1, 16, 1, 18, WALL)
    p.rect(6, 16, 6, 18, WALL)
    p.rect(2, 16, 5, 18, SPAWN)
    p.rect(3, 15, 4, 15, CHECKPOINT)
    return "arena", "Arena", p, [
        "Four stands around a court, with a gate on each side and turnstile",
        "banks at two corners. The court is solid, so the concourse is a ring",
        "and the crowd has to travel round it rather than across it.",
        "",
        "Worth running both ways: the turnstiles are the limit coming in, and",
        "they are not exits, so they count for nothing going out. The bag",
        "boxes in two corners are reached only through a checkpoint, so they",
        "are where the VIPs go.",
    ]


def nightclub():
    """The one that fails. Dense floor, a bar in the way, and a fire exit that
    is technically present and practically unreachable."""
    p = Plan(20, 14)

    # A packed floor: 150 people across 56 m² is about 2.7 per m², which is
    # what a busy club actually looks like and well past comfortable.
    p.rect(2, 2, 9, 5, SPAWN)           # dance floor
    p.rect(2, 8, 9, 10, SPAWN)          # seating

    p.rect(13, 5, 18, 8, BARRIER)       # bar
    p.rect(13, 10, 18, 11, BARRIER)     # stock

    # The route to the fire exit runs behind the bar, one metre wide.
    p.rect(12, 5, 12, 12, FLOOR)

    p.rect(5, 13, 6, 13, EXIT)          # main doors
    p.rect(19, 12, 19, 12, EXIT)        # fire exit behind the bar
    return "nightclub", "Nightclub", p, [
        "A packed floor, a bar taking up one end, and a fire exit reached down",
        "a one-metre gap behind it. The fire exit is present, signed and, for",
        "most of the room, not worth walking to.",
    ]


def theatre():
    p = Plan(30, 20)
    p.rect(8, 1, 21, 2, BARRIER)             # stage
    p.rect(3, 5, 26, 8, SPAWN)               # orchestra
    p.rect(3, 12, 26, 14, SPAWN)             # balcony
    for x in (10, 19):                       # longitudinal aisles
        p.rect(x, 5, x, 8, FLOOR)
        p.rect(x, 12, x, 14, FLOOR)
    p.rect(1, 10, 28, 10, FLOOR)             # cross aisle
    p.rect(10, 19, 11, 19, EXIT)
    p.rect(18, 19, 19, 19, EXIT)
    p.rect(0, 6, 0, 6, EXIT)
    p.rect(29, 6, 29, 6, EXIT)
    # The foyer doors, at the back. An audience arrives through these and
    # leaves through everything.
    p.rect(4, 19, 5, 19, ENTRANCE)
    p.rect(24, 19, 25, 19, ENTRANCE)
    return "theatre", "Theatre", p, [
        "A stage, an orchestra block and a balcony, with aisles between them.",
        "The stage is solid, so the whole audience leaves by the back and the",
        "side doors. It arrives through the two foyer doors, which is a much",
        "narrower way in than the way out — run it both ways and compare.",
    ]


def stadium():
    p = Plan(36, 24)
    p.rect(12, 9, 23, 14, BARRIER)           # pitch

    # Kept deliberately tight: 150 people across 76 m² of seating is about two
    # per m², which is a full stand rather than a quiet one. A stadium drawn
    # at true scale would need thousands of people to stress anything.
    p.rect(13, 6, 22, 7, SPAWN)              # lower tier
    p.rect(13, 16, 22, 17, SPAWN)
    p.rect(7, 10, 8, 13, SPAWN)
    p.rect(27, 10, 28, 13, SPAWN)

    p.rect(13, 2, 22, 2, SPAWN)              # upper tier
    p.rect(13, 21, 22, 21, SPAWN)
    p.rect(2, 10, 3, 13, SPAWN)
    p.rect(32, 10, 33, 13, SPAWN)

    # Wall the tiers off from the concourse, then cut the vomitories back in.
    p.rect(9, 4, 26, 4, WALL)
    p.rect(9, 19, 26, 19, WALL)
    p.rect(5, 9, 5, 14, WALL)
    p.rect(30, 9, 30, 14, WALL)
    for x in (17,):
        p.rect(x, 4, x, 4, FLOOR)
        p.rect(x, 19, x, 19, FLOOR)
    for y in (11,):
        p.rect(5, y, 5, y, FLOOR)
        p.rect(30, y, 30, y, FLOOR)

    p.rect(16, 0, 19, 0, EXIT)
    p.rect(16, 23, 19, 23, EXIT)
    p.rect(0, 10, 0, 13, EXIT)
    p.rect(35, 10, 35, 13, EXIT)
    return "stadium", "Stadium", p, [
        "Two tiers around a pitch, reached only through vomitories. There is",
        "plenty of exit width on the outside of the building and very little",
        "between the crowd and it.",
    ]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.txt"):
        old.unlink()
    for build in (arena, nightclub, theatre, stadium):
        slug, name, plan, notes = build()
        (OUT / f"{slug}.txt").write_text(plan.text(name, notes), encoding="utf-8")
        print(f"wrote {slug}.txt  {plan.width}x{plan.height}")


if __name__ == "__main__":
    main()
