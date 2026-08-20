"""The musical model produced by ingest, upstream of any chiptune decisions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Note:
    """One sounding pitch, with times already resolved to seconds."""

    pitch: int  # MIDI note number
    start: float  # seconds from the start of the score
    dur: float  # seconds
    velocity: int  # 0-127, as written in the source
    part: int  # index of the source part or staff


@dataclass(frozen=True)
class Score:
    notes: tuple[Note, ...]
    bpm: float
    time_signature: tuple[int, int]
    title: str
