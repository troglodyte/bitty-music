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

import tomllib
from dataclasses import dataclass, replace
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


class ConfigError(Exception):
    """A config file that cannot be obeyed.

    Names the source and the key path in the message itself. A tuning tool's
    worst outcome is a typo'd key that silently does nothing, so nothing here
    warns and continues.
    """

    def __init__(self, source: str, key_path: str, message: str) -> None:
        self.source = source
        self.key_path = key_path
        where = f"{source}: {key_path}: " if key_path else f"{source}: "
        super().__init__(f"{where}{message}")


def _number(value, source, key_path, *, low=None, high=None):
    # bool is a subclass of int, so `level = true` would otherwise pass as 1.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(source, key_path, f"expected a number, got {value!r}")
    if low is not None and value < low:
        raise ConfigError(source, key_path, f"expected at least {low}, got {value!r}")
    if high is not None and value > high:
        raise ConfigError(source, key_path, f"expected at most {high}, got {value!r}")
    return float(value)


def _ranged(low=None, high=None):
    def check(value, source, key_path):
        return _number(value, source, key_path, low=low, high=high)

    return check


def _ms(low=0.0):
    """Milliseconds in the file, seconds in the code. The only place that converts."""

    def check(value, source, key_path):
        return _number(value, source, key_path, low=low) / 1000.0

    return check


def _whole(low=None, high=None):
    def check(value, source, key_path):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(source, key_path, f"expected a whole number, got {value!r}")
        if low is not None and value < low:
            raise ConfigError(source, key_path, f"expected at least {low}, got {value!r}")
        if high is not None and value > high:
            raise ConfigError(source, key_path, f"expected at most {high}, got {value!r}")
        return value

    return check


def _flag(value, source, key_path):
    if not isinstance(value, bool):
        raise ConfigError(source, key_path, f"expected true or false, got {value!r}")
    return value


def _text(value, source, key_path):
    if not isinstance(value, str):
        raise ConfigError(source, key_path, f"expected a string, got {value!r}")
    return value


def _one_of(*allowed):
    def check(value, source, key_path):
        chosen = _text(value, source, key_path)
        if chosen not in allowed:
            raise ConfigError(
                source, key_path, f"expected one of {', '.join(allowed)}, got {chosen!r}"
            )
        return chosen

    return check


def _folder(value, source, key_path):
    return Path(_text(value, source, key_path))


# TOML key -> (dataclass field, validator). The two names differ exactly where
# a unit is converted, which is the only place the file and the code disagree.
# `output.target` is checked against the registry by the CLI, not here: config
# has no business importing the targets module to learn what a target is.
_TABLES = {
    "output": {
        "target": ("target", _text),
        "format": ("format", _one_of("ogg", "wav")),
        "dir": ("dir", _folder),
        "sample_rate": ("sample_rate", _whole(low=8000, high=192000)),
    },
    "echo": {
        "on": ("on", _flag),
        "delay_beats": ("delay_beats", _ranged(low=0.0, high=16.0)),
        "level": ("level", _ranged(low=0.0, high=1.0)),
    },
    "arp": {"rate_ms": ("step_sec", _ms(low=1.0))},
    "vibrato": {
        "depth_cents": ("depth_cents", _ranged(low=0.0, high=1200.0)),
        "delay_ms": ("delay_sec", _ms()),
        "rate_hz": ("rate_hz", _ranged(low=0.0, high=40.0)),
        "min_note_ms": ("min_note_sec", _ms()),
    },
    "loop": {
        "min_bars": ("min_bars", _whole(low=1)),
        "seam_ratio": ("seam_ratio", _ranged(low=0.0)),
    },
}


def _table(current, name, raw, source):
    spec = _TABLES[name]
    if not isinstance(raw, dict):
        raise ConfigError(source, name, f"expected a table, e.g. [{name}]")
    changes = {}
    for key, value in raw.items():
        if key not in spec:
            raise ConfigError(
                source,
                f"{name}.{key}",
                f"unknown key; [{name}] accepts {', '.join(sorted(spec))}",
            )
        field, check = spec[key]
        changes[field] = check(value, source, f"{name}.{key}")
    return replace(current, **changes)


def merge(config: Config, text: str, source: str) -> Config:
    """Apply one file's worth of TOML to a config. The file wins."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(source, "", f"not valid TOML: {error}") from error

    changes = {}
    for name, body in raw.items():
        if name not in _TABLES:
            # "voices" is deliberately absent here: [voices.<role>] support
            # lands in Task 4. Until then this genuinely rejects a [voices]
            # table, so advertising it as accepted would be a lie.
            known = ", ".join(sorted(_TABLES))
            raise ConfigError(source, name, f"unknown table; bitty config accepts {known}")
        changes[name] = _table(getattr(config, name), name, body, source)
    return replace(config, **changes)
