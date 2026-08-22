"""Resolved settings: defaults, a preset, TOML files, then flags.

Three separable pieces, so each tests without the others: `discover` is pure
path logic, `merge`/`load` parse and layer, and `resolve` composes them. The
CLI applies flags on top, because the CLI is what owns flags.

Milliseconds are the TOML unit and seconds are the code unit. The conversion
happens once, here, so neither side has to hold the other's convention.

This module imports only the bottom of the graph — `arrangement`, `voices`,
`lfo`. `arrange` and `loop` import *this*, so their constants cannot be
imported back; those values are literals here, and `tests/test_config.py`
asserts the copies agree.
"""

from dataclasses import dataclass
from pathlib import Path

from bitty.arrangement import VIBRATO_CENTS, VIBRATO_DELAY, VIBRATO_RATE_HZ
from bitty.lfo import MIN_NOTE_SEC
from bitty.voices import ECHO_BEATS, ECHO_LEVEL, ROSTER, Voice


@dataclass(frozen=True)
class Output:
    """Where the audio goes and in what shape. `dir` and `format` are also flags."""

    target: str = "bevy"
    format: str = "ogg"
    dir: Path = Path("out")
    sample_rate: int = 44100  # asserted equal to synth.SAMPLE_RATE


@dataclass(frozen=True)
class EchoSettings:
    on: bool = True
    delay_beats: float = ECHO_BEATS
    level: float = ECHO_LEVEL


@dataclass(frozen=True)
class Arp:
    step_sec: float = 0.016  # asserted equal to arrange.ARP_STEP_SEC


@dataclass(frozen=True)
class Vibrato:
    """The shape every voice inherits, plus the threshold that picks the notes.

    `min_note_sec` is arranger policy rather than timbre — it decides which
    notes get vibrato at all — so it stays global while the other three are
    spread onto each instrument.
    """

    depth_cents: float = VIBRATO_CENTS
    delay_sec: float = VIBRATO_DELAY
    rate_hz: float = VIBRATO_RATE_HZ
    min_note_sec: float = MIN_NOTE_SEC


@dataclass(frozen=True)
class LoopSettings:
    min_bars: int = 8  # asserted equal to loop.MIN_LOOP_BARS
    seam_ratio: float = 1.0  # asserted equal to loop.SEAM_RATIO


@dataclass(frozen=True)
class Config:
    output: Output = Output()
    echo: EchoSettings = EchoSettings()
    arp: Arp = Arp()
    vibrato: Vibrato = Vibrato()
    loop: LoopSettings = LoopSettings()
    voices: tuple[Voice, ...] = ROSTER


DEFAULTS = Config()
