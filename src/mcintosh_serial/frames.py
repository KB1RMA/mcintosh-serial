"""Frame parsing shared by every parenthesized McIntosh dialect.

Both the "zoned" dialect (``(VST Z1 8)``) and the "simple" dialect
(``(VOL 65)``) wrap a payload in ``(`` and ``)``. Responses end in CR/LF, but
the unit reads a continuous stream, so framing is done on the parentheses.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

_FRAME_RE = re.compile(r"\(([^()]*)\)")
# A partial frame longer than this is garbage, not a command still arriving.
MAX_PARTIAL = 512


@dataclass(frozen=True, slots=True)
class Frame:
    """One parsed ``(NAME arg arg ...)`` message."""

    name: str
    args: tuple[str, ...]
    raw: str


def parse_payload(payload: str) -> Frame | None:
    """Turn the text between the parentheses into a Frame (None if empty)."""
    tokens = payload.split()
    return Frame(tokens[0], tuple(tokens[1:]), payload.strip()) if tokens else None


def parse_frames(buffer: str) -> tuple[tuple[Frame, ...], str]:
    """Split a receive buffer into complete frames and the unparsed remainder.

    NUL bytes (seen when the unit loses power) are dropped. Text before an
    opening parenthesis is discarded; an unterminated frame is kept so the next
    chunk can complete it.
    """
    cleaned = buffer.replace("\x00", "")
    matches = tuple(_FRAME_RE.finditer(cleaned))
    frames = tuple(
        frame
        for frame in (parse_payload(match.group(1)) for match in matches)
        if frame is not None
    )
    tail = cleaned[matches[-1].end() :] if matches else cleaned
    start = tail.find("(")
    rest = tail[start:] if start >= 0 else ""
    return frames, rest if len(rest) <= MAX_PARTIAL else ""
