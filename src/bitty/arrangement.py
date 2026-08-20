"""The pipeline's spine: a JSON-serializable chiptune arrangement.

Everything upstream of this file is musical analysis; everything
downstream is signal processing. It is deliberately free of music21 and of
sample rates, so a hand-edited arrangement can be re-rendered on its own.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

MAX_VELOCITY = 15


@dataclass(frozen=True)
class Event:
    t: float  # seconds from the start of the arrangement
    pitch: int  # MIDI note number
    dur: float  # seconds
    vel: int  # 0-15


@dataclass(frozen=True)
class Instrument:
    wave: str  # "pulse" or "triangle"
    duty: float = 0.5


@dataclass(frozen=True)
class Channel:
    role: str
    instrument: Instrument
    events: tuple[Event, ...]


@dataclass(frozen=True)
class Arrangement:
    meta: dict
    channels: tuple[Channel, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> Arrangement:
        raw = json.loads(text)
        return cls(
            meta=raw["meta"],
            channels=tuple(
                Channel(
                    role=channel["role"],
                    instrument=Instrument(**channel["instrument"]),
                    events=tuple(Event(**event) for event in channel["events"]),
                )
                for channel in raw["channels"]
            ),
        )
