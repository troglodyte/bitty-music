"""The pipeline's spine: a JSON-serializable chiptune arrangement.

Everything upstream of this file is musical analysis; everything
downstream is signal processing. It is deliberately free of music21 and of
sample rates, so a hand-edited arrangement can be re-rendered on its own.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields

MAX_VELOCITY = 15


@dataclass(frozen=True)
class Event:
    t: float  # seconds from the start of the arrangement
    pitch: int  # MIDI note number
    dur: float  # seconds
    vel: int  # 0-15


@dataclass(frozen=True)
class Instrument:
    """One channel's timbre. Every field past `wave` is optional.

    Flat rather than nested because this is the hand-edit surface: a person
    fixing a passage in `arrangement.json` should not have to navigate a tree.
    """

    wave: str  # "pulse", "triangle", "saw", or "noise"
    duty: float = 0.5  # pulse only
    volume_env: tuple[int, ...] = ()  # levels 0-15, 60 steps/sec, last sustains
    pitch_env: tuple[int, ...] = ()  # semitone offsets, same rate
    cutoff_hz: float | None = None  # None means no filtering at all
    resonance: float = 0.7071  # biquad Q; 0.7071 is flat, higher peaks
    quantize: int | None = None  # triangle amplitude steps, e.g. 16 for NES


@dataclass(frozen=True)
class Echo:
    delay_sec: float
    level: float  # 0.0-1.0, relative to the dry channel


@dataclass(frozen=True)
class Channel:
    role: str
    instrument: Instrument
    events: tuple[Event, ...]
    pan: float = 0.0  # -1.0 hard left, +1.0 hard right
    echo: Echo | None = None


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
            channels=tuple(_channel_from(c) for c in raw["channels"]),
        )


def _channel_from(raw: dict) -> Channel:
    echo = raw.get("echo")
    return Channel(
        role=raw["role"],
        instrument=_instrument_from(raw["instrument"]),
        events=tuple(Event(**event) for event in raw["events"]),
        pan=raw.get("pan", 0.0),
        echo=Echo(**echo) if echo else None,
    )


def _instrument_from(raw: dict) -> Instrument:
    """Build an Instrument, dropping any field this build does not know.

    A hand-edited or newer-bitty arrangement should render with the fields we
    understand rather than fail to load at all.
    """
    known = {f.name for f in fields(Instrument)}
    kwargs = {k: v for k, v in raw.items() if k in known}
    for env in ("volume_env", "pitch_env"):
        if env in kwargs:
            kwargs[env] = tuple(kwargs[env])
    return Instrument(**kwargs)
