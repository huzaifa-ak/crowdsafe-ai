"""Storing and shipping traces.

A trace is one flat list of coordinates per tick. At the configured limits —
300 agents, 600 ticks — that is around 350 KB of JSON, which is fine to hold in
memory and wasteful to store as-is.

Coordinates repeat heavily from tick to tick and the alphabet is tiny, so gzip
does very well here: roughly a tenth of the raw size. That is cheap enough that
persisting the full trace is worth it, which is what makes a saved run
replayable rather than just a row of numbers (D12).
"""

import gzip
import json

# gzip level 6 is the default and the right trade here: level 9 costs several
# times the CPU for a percent or two, on a payload written once per run.
COMPRESSION_LEVEL = 6


def encode(trace: list[list[int]]) -> bytes:
    """Trace to a compressed blob for storage."""
    raw = json.dumps(trace, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=COMPRESSION_LEVEL)


def decode(blob: bytes | None) -> list[list[int]]:
    """Compressed blob back to a trace.

    Uncompressed JSON is accepted too, so runs stored before compression was
    added still load.
    """
    if not blob:
        return []
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    return json.loads(blob.decode("utf-8"))


def raw_size(trace: list[list[int]]) -> int:
    """Bytes the trace would take uncompressed. Used by the budget test."""
    return len(json.dumps(trace, separators=(",", ":")).encode("utf-8"))


def summarise(trace: list[list[int]], blob: bytes) -> dict:
    """What this trace cost, for the run's stored metrics."""
    raw = raw_size(trace)
    return {
        "ticks": len(trace),
        "raw_bytes": raw,
        "stored_bytes": len(blob),
        "compression_ratio": round(raw / len(blob), 1) if blob else None,
    }
