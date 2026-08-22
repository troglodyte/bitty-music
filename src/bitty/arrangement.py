"""The pipeline's spine: a JSON-serializable chiptune arrangement.

Everything upstream of this file is musical analysis; everything
downstream is signal processing. It is deliberately free of music21 and of
sample rates, so a hand-edited arrangement can be re-rendered on its own.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields

MAX_VELOCITY = 15

# Vibrato's shape is timbre, so it travels in the arrangement rather than
# living in the synth: a hand-edited file renders the same with no config
# anywhere. This module is the bottom of the import graph, which is what makes
# it the right owner of the values every other module measures against.
VIBRATO_CENTS = 25.0
VIBRATO_DELAY = 0.3
VIBRATO_RATE_HZ = 5.5


@dataclass(frozen=True)
class Event:
    t: float  # seconds from the start of the arrangement
    pitch: int  # MIDI note number
    dur: float  # seconds
    vel: int  # 0-15
    vibrato: bool = False  # a delayed LFO on the pitch; see lfo.py


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
    vibrato_cents: float = VIBRATO_CENTS  # depth of the sustain LFO
    vibrato_delay: float = VIBRATO_DELAY  # seconds of silence before it fades in
    vibrato_rate_hz: float = VIBRATO_RATE_HZ  # oscillations per second, once it fades in


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
class Loop:
    """Where the audio comes back around. Seconds, like every other time here.

    Two floats and no more. `source` and the measured seam explain a decision
    already made; this file is the hand-edit surface, where an extra field
    invites someone to change it and expect something to happen.
    """

    start_sec: float
    end_sec: float


@dataclass(frozen=True)
class Arrangement:
    meta: dict
    channels: tuple[Channel, ...]
    loop: Loop | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> Arrangement:
        raw = json.loads(text)
        return cls(
            meta=raw["meta"],
            channels=tuple(_channel_from(c) for c in raw["channels"]),
            loop=_loop_from(raw.get("loop")),
        )


def _channel_from(raw: dict) -> Channel:
    echo = raw.get("echo")
    return Channel(
        role=raw["role"],
        instrument=_instrument_from(raw["instrument"]),
        events=tuple(_event_from(e) for e in raw["events"]),
        pan=raw.get("pan", 0.0),
        echo=Echo(**echo) if echo else None,
    )


def _event_from(raw: dict) -> Event:
    """Build an Event, dropping any field this build does not know.

    The same contract `_instrument_from` keeps, for the same reason: adding a
    field should not turn every older build into a hard failure on load.
    """
    known = {f.name for f in fields(Event)}
    return Event(**{k: v for k, v in raw.items() if k in known})


def _loop_from(raw: dict | None) -> Loop | None:
    """Same drop-unknown-fields contract the other loaders keep."""
    if not raw:
        return None
    known = {f.name for f in fields(Loop)}
    return Loop(**{k: v for k, v in raw.items() if k in known})


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
