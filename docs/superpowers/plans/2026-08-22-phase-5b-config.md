# Phase 5b Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give bitty a TOML config layer — defaults, presets, project and per-piece files, then flags — without changing a note of what the defaults produce.

**Architecture:** A new `bitty/config.py` owns a frozen `Config` dataclass tree and three separable functions: `discover` (pure path logic), `merge`/`load` (parse, validate, layer), and `resolve` (compose the two). The CLI resolves config once and passes it to `arrange` and to the loop cascade; everything the synth needs then rides in the arrangement itself, so `bitty render` on a hand-edited file reproduces the same audio with no config present. Vibrato's shape moves onto `Instrument` to make that true.

**Tech Stack:** Python 3.11+, `tomllib` (standard library), `importlib.resources` for shipped presets, Typer for the CLI, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-22-phase-5b-config-design.md`

## Global Constraints

- **The defaults must reproduce today's output exactly.** `Config()` carries
  today's constants, so every existing test passes untouched. The only
  intended change to the golden files is the three new `Instrument` fields.
- **No new dependencies.** `tomllib` is standard library on the project's
  `requires-python = ">=3.11"` floor.
- **Milliseconds in TOML, seconds in code.** `delay_ms`, `min_note_ms`,
  `rate_ms`, and `vibrato_delay_ms` convert once, at load.
- **Strict validation.** An unknown table, an unknown key, an unknown voice
  role, or an out-of-range value raises `ConfigError` naming the source and
  the key path. Nothing is written before config resolves.
- **Run tests with the project venv:** `.venv/bin/pytest`.
- **5b wires existing knobs.** No `[transform]`, no `dynamics.levels`, no
  `voices.count`. See the spec's "Deliberately out of scope".

---

### Task 1: Vibrato becomes timbre

Vibrato's *decision* is already arrange-time (`Event.vibrato`), but its
*shape* is read from `lfo` module constants at render time and appears
nowhere in the arrangement. Move the shape onto `Instrument` so a configured
value survives into `bitty render`. `arrangement.py` becomes the single
source for the three default values, because it is the bottom of the import
graph — it imports nothing but the standard library.

**Files:**
- Modify: `src/bitty/arrangement.py` (add constants near `MAX_VELOCITY:13`, add fields to `Instrument:26-40`)
- Modify: `src/bitty/lfo.py` (whole file)
- Modify: `src/bitty/synth.py:144-147`
- Modify: `tests/test_lfo.py:4` (import moves)
- Test: `tests/test_lfo.py`, `tests/test_synth.py`
- Regenerate: `tests/goldens/{chorale,minuet,ragtime}.arrangement.json`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `arrangement.VIBRATO_CENTS: float = 25.0`,
  `arrangement.VIBRATO_DELAY: float = 0.3`,
  `arrangement.VIBRATO_RATE_HZ: float = 5.5`;
  `Instrument.vibrato_cents: float`, `Instrument.vibrato_delay: float`,
  `Instrument.vibrato_rate_hz: float`;
  `lfo.vibrato_cents(length: int, sample_rate: int, depth_cents: float = VIBRATO_CENTS, delay_sec: float = VIBRATO_DELAY, rate_hz: float = VIBRATO_RATE_HZ) -> np.ndarray`.

- [ ] **Step 1: Capture the audio baseline before touching anything**

This is the evidence that Task 1 changes the JSON and not the sound. Run it
first, while the tree is still clean.

```bash
.venv/bin/python - <<'PY' > "${TMPDIR:-/tmp}/bitty-5b-baseline.txt"
import hashlib
from pathlib import Path
from bitty.arrange import arrange
from bitty.ingest import ingest
from bitty.synth import render

for name in ("chorale", "minuet", "ragtime"):
    audio = render(arrange(ingest(Path("tests/fixtures") / f"{name}.mxl")))
    print(name, hashlib.sha256(audio.tobytes()).hexdigest())
PY
cat "${TMPDIR:-/tmp}/bitty-5b-baseline.txt"
```

Expected: three lines, one hash each.

- [ ] **Step 2: Write the failing tests**

Replace the import line at the top of `tests/test_lfo.py`:

```python
from bitty.arrangement import VIBRATO_CENTS, VIBRATO_DELAY
from bitty.lfo import vibrato_cents
```

Then find and replace `DEPTH_CENTS` with `VIBRATO_CENTS` and `DELAY_SEC` with
`VIBRATO_DELAY` throughout that file, and append:

```python
def test_a_deeper_instrument_swings_further():
    shallow = vibrato_cents(44100, 44100, depth_cents=10.0)
    deep = vibrato_cents(44100, 44100, depth_cents=50.0)
    assert np.max(np.abs(deep)) > 4.0 * np.max(np.abs(shallow))


def test_a_longer_delay_stays_silent_longer():
    """Before the delay elapses the depth clips to zero, exactly."""
    late = vibrato_cents(44100, 44100, delay_sec=0.8)
    assert np.array_equal(late[: int(0.8 * 44100)], np.zeros(int(0.8 * 44100)))


def crossings(wave):
    return int(np.count_nonzero(np.diff(np.sign(wave))))


def test_a_faster_rate_crosses_zero_more_often():
    slow = vibrato_cents(44100, 44100, delay_sec=0.0, rate_hz=2.0)
    fast = vibrato_cents(44100, 44100, delay_sec=0.0, rate_hz=8.0)
    assert crossings(fast) > 3 * crossings(slow)
```

Append to `tests/test_synth.py`:

```python
def test_instrument_vibrato_depth_reaches_the_rendered_audio():
    """The shape travels in the arrangement, so two depths must not render alike."""

    def rendered(cents):
        instrument = Instrument(wave="pulse", vibrato_cents=cents)
        event = Event(t=0.0, pitch=69, dur=1.5, vel=15, vibrato=True)
        channel = Channel(role="lead", instrument=instrument, events=(event,))
        return render(Arrangement(meta={}, channels=(channel,)))

    assert not np.array_equal(rendered(25.0), rendered(80.0))


def test_an_instrument_without_vibrato_events_ignores_its_vibrato_fields():
    """`Event.vibrato` is still the switch; the instrument only shapes it."""

    def rendered(cents):
        instrument = Instrument(wave="pulse", vibrato_cents=cents)
        event = Event(t=0.0, pitch=69, dur=1.5, vel=15, vibrato=False)
        channel = Channel(role="lead", instrument=instrument, events=(event,))
        return render(Arrangement(meta={}, channels=(channel,)))

    assert np.array_equal(rendered(25.0), rendered(80.0))
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_lfo.py tests/test_synth.py -v`
Expected: FAIL — `ImportError: cannot import name 'VIBRATO_CENTS' from 'bitty.arrangement'`.

- [ ] **Step 4: Add the constants and the fields to `arrangement.py`**

Below `MAX_VELOCITY = 15`:

```python
# Vibrato's shape is timbre, so it travels in the arrangement rather than
# living in the synth: a hand-edited file renders the same with no config
# anywhere. This module is the bottom of the import graph, which is what makes
# it the right owner of the values every other module measures against.
VIBRATO_CENTS = 25.0
VIBRATO_DELAY = 0.3
VIBRATO_RATE_HZ = 5.5
```

Append three fields to `Instrument`, after `quantize`:

```python
    vibrato_cents: float = VIBRATO_CENTS  # depth of the sustain LFO
    vibrato_delay: float = VIBRATO_DELAY  # seconds of silence before it fades in
    vibrato_rate_hz: float = VIBRATO_RATE_HZ
```

`_instrument_from` already drops unknown fields and needs no change, so an
older arrangement.json loads with these defaults.

- [ ] **Step 5: Parameterize `lfo.vibrato_cents`**

Replace the body of `src/bitty/lfo.py` below its docstring:

```python
import numpy as np

from bitty.arrangement import VIBRATO_CENTS, VIBRATO_DELAY, VIBRATO_RATE_HZ

MIN_NOTE_SEC = 0.5  # the spec's [vibrato] min_note_ms; the arranger's threshold
FADE_SEC = 0.15  # a step change in pitch would click


def vibrato_cents(
    length: int,
    sample_rate: int,
    depth_cents: float = VIBRATO_CENTS,
    delay_sec: float = VIBRATO_DELAY,
    rate_hz: float = VIBRATO_RATE_HZ,
) -> np.ndarray:
    """Per-sample pitch offset in cents: silent, then fading in to full depth.

    The shape comes from the instrument now. The defaults are here so a caller
    that has no instrument — a test, a probe — still gets the house sound.
    """
    if length <= 0:
        return np.zeros(0, dtype=np.float64)

    t = np.arange(length, dtype=np.float64) / sample_rate
    depth = np.clip((t - delay_sec) / FADE_SEC, 0.0, 1.0) * depth_cents
    return depth * np.sin(2.0 * np.pi * rate_hz * t)
```

Note `DEPTH_CENTS`, `DELAY_SEC`, and `RATE_HZ` are gone; `arrangement` owns
those values now.

- [ ] **Step 6: Pass the instrument's shape through in `synth.py`**

Replace lines 144-147:

```python
    if event.vibrato:
        # Composed with the pitch envelope, not replacing it: the blip is the
        # attack, the vibrato is the sustain.
        cents = vibrato_cents(
            length,
            sample_rate,
            instrument.vibrato_cents,
            instrument.vibrato_delay,
            instrument.vibrato_rate_hz,
        )
        inc = inc * 2.0 ** (cents / 1200.0)
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/pytest tests/test_lfo.py tests/test_synth.py -v`
Expected: PASS.

- [ ] **Step 8: Run the whole suite to see the expected golden failure**

Run: `.venv/bin/pytest`
Expected: `tests/test_goldens.py::test_arrangement_matches_its_golden` fails
for all three names. Every other test passes. If anything else fails, stop —
that is a real regression, not golden churn.

- [ ] **Step 9: Regenerate the goldens and read the diff**

```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
git diff --stat tests/goldens/
git diff tests/goldens/ | grep '^[-+]' | grep -v '^[-+][-+]' | sort | uniq -c | sort -rn
```

Expected: every changed line is an *addition* of `"vibrato_cents": 25.0`,
`"vibrato_delay": 0.3`, or `"vibrato_rate_hz": 5.5`. There must be **no
removed lines** and no other added keys. If a value or an event moved, stop
and find out why before continuing.

- [ ] **Step 10: Prove the audio did not change**

```bash
.venv/bin/python - <<'PY' > "${TMPDIR:-/tmp}/bitty-5b-after.txt"
import hashlib
from pathlib import Path
from bitty.arrange import arrange
from bitty.ingest import ingest
from bitty.synth import render

for name in ("chorale", "minuet", "ragtime"):
    audio = render(arrange(ingest(Path("tests/fixtures") / f"{name}.mxl")))
    print(name, hashlib.sha256(audio.tobytes()).hexdigest())
PY
diff "${TMPDIR:-/tmp}/bitty-5b-baseline.txt" "${TMPDIR:-/tmp}/bitty-5b-after.txt" && echo "audio unchanged"
```

Expected: `audio unchanged`. If the hashes differ, the vibrato defaults do
not match what the constants were — fix that before committing.

- [ ] **Step 11: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/bitty/arrangement.py src/bitty/lfo.py src/bitty/synth.py tests/test_lfo.py tests/test_synth.py tests/goldens/
git commit -m "feat: carry vibrato's shape in the arrangement"
```

---

### Task 2: The Config tree and its defaults

`config.py` owns the resolved settings. It imports only `arrangement`,
`voices`, and `lfo` — never `arrange`, `loop`, or `synth`, because those will
import *it*. Where a value's natural owner is a module config cannot import,
the value is a literal here and a test asserts the two agree.

**Files:**
- Create: `src/bitty/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `arrangement.VIBRATO_CENTS`, `arrangement.VIBRATO_DELAY`, `arrangement.VIBRATO_RATE_HZ` (Task 1).
- Produces: `config.Output`, `config.EchoSettings`, `config.Arp`, `config.Vibrato`, `config.LoopSettings`, `config.Config`, `config.DEFAULTS: Config`. Field names as written below — later tasks read them by name.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
from pathlib import Path

from bitty import arrangement, lfo, synth, voices
from bitty.arrange import ARP_STEP_SEC
from bitty.config import DEFAULTS
from bitty.loop import MIN_LOOP_BARS, SEAM_RATIO


def test_defaults_match_the_constants_they_replace():
    """The guard that lets every other test in the suite stay untouched.

    Some of these values live in modules config cannot import, because those
    modules import config. This assertion is the seam that keeps the two
    copies honest.
    """
    assert DEFAULTS.echo.delay_beats == voices.ECHO_BEATS
    assert DEFAULTS.echo.level == voices.ECHO_LEVEL
    assert DEFAULTS.vibrato.depth_cents == arrangement.VIBRATO_CENTS
    assert DEFAULTS.vibrato.delay_sec == arrangement.VIBRATO_DELAY
    assert DEFAULTS.vibrato.rate_hz == arrangement.VIBRATO_RATE_HZ
    assert DEFAULTS.vibrato.min_note_sec == lfo.MIN_NOTE_SEC
    assert DEFAULTS.arp.step_sec == ARP_STEP_SEC
    assert DEFAULTS.loop.min_bars == MIN_LOOP_BARS
    assert DEFAULTS.loop.seam_ratio == SEAM_RATIO
    assert DEFAULTS.output.sample_rate == synth.SAMPLE_RATE
    assert DEFAULTS.voices == voices.ROSTER


def test_the_defaults_describe_the_shipped_behaviour():
    assert DEFAULTS.echo.on is True
    assert DEFAULTS.output.target == "bevy"
    assert DEFAULTS.output.format == "ogg"
    assert DEFAULTS.output.dir == Path("out")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bitty.config'`.

- [ ] **Step 3: Write `src/bitty/config.py`**

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS, both tests.

- [ ] **Step 5: Commit**

```bash
git add src/bitty/config.py tests/test_config.py
git commit -m "feat: add the Config tree, defaulting to today's constants"
```

---

### Task 3: TOML parsing and strict validation

One public function, `merge(config, text, source) -> Config`, applies one
file's worth of TOML to a config. Validation is a table of per-key
validators; an unknown table, unknown key, or out-of-range value raises
`ConfigError` naming the source and the key path. `[voices]` is handled in
Task 4 and skipped here.

**Files:**
- Modify: `src/bitty/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Config`, `DEFAULTS` (Task 2).
- Produces: `config.ConfigError(source: str, key_path: str, message: str)`, `config.merge(config: Config, text: str, source: str) -> Config`, and the private `_TABLES` mapping later tasks read.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
import pytest

from bitty.config import ConfigError, merge


def test_a_value_from_a_file_beats_the_default():
    result = merge(DEFAULTS, "[echo]\nlevel = 0.9\n", "bitty.toml")
    assert result.echo.level == 0.9
    assert result.echo.delay_beats == DEFAULTS.echo.delay_beats, "untouched keys survive"


def test_milliseconds_become_seconds():
    text = "[vibrato]\ndelay_ms = 300\nmin_note_ms = 750\n\n[arp]\nrate_ms = 20\n"
    result = merge(DEFAULTS, text, "bitty.toml")
    assert result.vibrato.delay_sec == 0.3
    assert result.vibrato.min_note_sec == 0.75
    assert result.arp.step_sec == 0.02


def test_an_unknown_key_names_the_file_the_key_and_the_alternatives():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[echo]\nlevl = 0.5\n", "bitty.toml")
    message = str(caught.value)
    assert "bitty.toml" in message
    assert "echo.levl" in message
    assert "level" in message, "a typo should be told what it nearly was"


def test_an_unknown_table_is_refused():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[reverb]\non = true\n", "bitty.toml")
    assert "reverb" in str(caught.value)


def test_a_value_over_its_range_is_refused():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[echo]\nlevel = 3.0\n", "bitty.toml")
    assert "echo.level" in str(caught.value)
    assert "at most 1.0" in str(caught.value)


def test_a_value_of_the_wrong_type_is_refused():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, '[echo]\nlevel = "loud"\n', "bitty.toml")
    assert "expected a number" in str(caught.value)


def test_true_is_not_a_number():
    """bool is an int in Python; a config file should not get away with it."""
    with pytest.raises(ConfigError):
        merge(DEFAULTS, "[echo]\nlevel = true\n", "bitty.toml")


def test_a_whole_number_field_refuses_a_fraction():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[loop]\nmin_bars = 8.5\n", "bitty.toml")
    assert "whole number" in str(caught.value)


def test_broken_toml_names_the_file():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[echo\nlevel = 0.5\n", "bitty.toml")
    assert "bitty.toml" in str(caught.value)
    assert "not valid TOML" in str(caught.value)


def test_the_format_key_accepts_only_the_two_it_can_write():
    assert merge(DEFAULTS, '[output]\nformat = "wav"\n', "x").output.format == "wav"
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, '[output]\nformat = "flac"\n', "x")
    assert "ogg, wav" in str(caught.value)


def test_the_out_dir_becomes_a_path():
    assert merge(DEFAULTS, '[output]\ndir = "build/audio"\n', "x").output.dir == Path("build/audio")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'ConfigError'`.

- [ ] **Step 3: Add the error type and the validators**

Add to `src/bitty/config.py`, after the imports (add `import tomllib` and
`from dataclasses import dataclass, replace` to the import block):

```python
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
```

- [ ] **Step 4: Add the table spec and `merge`**

```python
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
            known = ", ".join(sorted([*_TABLES, "voices"]))
            raise ConfigError(source, name, f"unknown table; bitty config accepts {known}")
        changes[name] = _table(getattr(config, name), name, body, source)
    return replace(config, **changes)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS, all of them.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/config.py tests/test_config.py
git commit -m "feat: parse and validate the scalar config tables"
```

---

### Task 4: `[voices.<role>]` over the roster

Config can reshape any of the five voices but cannot add or remove one. The
`[vibrato]` table spreads onto every instrument first; `[voices.<role>]` then
overrides one. Only the vibrato keys a file actually names are spread, so an
unrelated later file does not reset an earlier per-voice override.

**Files:**
- Modify: `src/bitty/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `merge`, `_TABLES`, the validators (Task 3).
- Produces: `merge` now handles the `voices` table; `Config.voices` stays `tuple[Voice, ...]` in roster order.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def roles(config):
    return {voice.role: voice for voice in config.voices}


def test_a_voice_override_reshapes_only_that_voice():
    result = merge(DEFAULTS, '[voices.lead]\nduty = 0.125\npan = 0.0\n', "bitty.toml")
    assert roles(result)["lead"].instrument.duty == 0.125
    assert roles(result)["lead"].pan == 0.0
    assert roles(result)["counter"] == roles(DEFAULTS)["counter"]


def test_the_roster_keeps_its_order_and_its_size():
    result = merge(DEFAULTS, "[voices.bass]\nquantize = 8\n", "bitty.toml")
    assert [v.role for v in result.voices] == [v.role for v in DEFAULTS.voices]


def test_an_unknown_voice_is_refused_and_lists_the_roster():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[voices.strings]\npan = 0.0\n", "bitty.toml")
    assert "voices.strings" in str(caught.value)
    assert "lead" in str(caught.value) and "bass" in str(caught.value)


def test_an_unknown_voice_key_is_refused():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[voices.lead]\nreverb = 0.5\n", "bitty.toml")
    assert "voices.lead.reverb" in str(caught.value)


def test_an_envelope_must_be_levels_in_range():
    result = merge(DEFAULTS, "[voices.lead]\nvolume_env = [15, 12, 9]\n", "x")
    assert roles(result)["lead"].instrument.volume_env == (15, 12, 9)
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[voices.lead]\nvolume_env = [15, 99]\n", "x")
    assert "volume_env[1]" in str(caught.value)


def test_the_global_vibrato_table_spreads_onto_every_voice():
    result = merge(DEFAULTS, "[vibrato]\ndepth_cents = 40.0\n", "bitty.toml")
    for voice in result.voices:
        assert voice.instrument.vibrato_cents == 40.0
    assert result.vibrato.depth_cents == 40.0, "the arranger's copy moves too"


def test_a_per_voice_vibrato_beats_the_global_one_in_the_same_file():
    text = "[vibrato]\ndepth_cents = 40.0\n\n[voices.lead]\nvibrato_cents = 10.0\n"
    result = merge(DEFAULTS, text, "bitty.toml")
    assert roles(result)["lead"].instrument.vibrato_cents == 10.0
    assert roles(result)["bass"].instrument.vibrato_cents == 40.0


def test_a_file_with_no_vibrato_table_leaves_per_voice_overrides_alone():
    """Spreading only the keys a file names is what keeps layering honest."""
    first = merge(DEFAULTS, "[voices.lead]\nvibrato_cents = 10.0\n", "a.toml")
    second = merge(first, "[echo]\nlevel = 0.5\n", "b.toml")
    assert roles(second)["lead"].instrument.vibrato_cents == 10.0


def test_per_voice_vibrato_delay_is_milliseconds_like_every_other_delay():
    result = merge(DEFAULTS, "[voices.lead]\nvibrato_delay_ms = 500\n", "x")
    assert roles(result)["lead"].instrument.vibrato_delay == 0.5
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `unknown table; bitty config accepts ...` from `merge`.

- [ ] **Step 3: Add the envelope validators and the voice key tables**

Add to `src/bitty/config.py`, after `_folder`, and add `MAX_VELOCITY` to the
existing `bitty.arrangement` import:

```python
def _levels(value, source, key_path):
    """A volume envelope: whole numbers inside the arrangement's 0-15 range."""
    if not isinstance(value, list):
        raise ConfigError(source, key_path, f"expected a list of levels, got {value!r}")
    check = _whole(low=0, high=MAX_VELOCITY)
    return tuple(check(item, source, f"{key_path}[{i}]") for i, item in enumerate(value))


def _semitones(value, source, key_path):
    """A pitch envelope: whole semitone offsets, positive or negative."""
    if not isinstance(value, list):
        raise ConfigError(source, key_path, f"expected a list of offsets, got {value!r}")
    check = _whole(low=-48, high=48)
    return tuple(check(item, source, f"{key_path}[{i}]") for i, item in enumerate(value))


# `pan` belongs to the Voice; everything else belongs to its Instrument. Split
# because those are two dataclasses, and the TOML should not have to know that.
_VOICE_KEYS = {"pan": ("pan", _ranged(low=-1.0, high=1.0))}
_INSTRUMENT_KEYS = {
    "wave": ("wave", _one_of("pulse", "triangle", "saw", "noise")),
    "duty": ("duty", _ranged(low=0.0, high=1.0)),
    "volume_env": ("volume_env", _levels),
    "pitch_env": ("pitch_env", _semitones),
    "cutoff_hz": ("cutoff_hz", _ranged(low=20.0)),
    "resonance": ("resonance", _ranged(low=0.1, high=20.0)),
    "quantize": ("quantize", _whole(low=2, high=256)),
    "vibrato_cents": ("vibrato_cents", _ranged(low=0.0, high=1200.0)),
    "vibrato_delay_ms": ("vibrato_delay", _ms()),
    "vibrato_rate_hz": ("vibrato_rate_hz", _ranged(low=0.0, high=40.0)),
}

# Which [vibrato] keys land on an instrument, and under what name there.
_VIBRATO_SPREAD = {
    "depth_cents": "vibrato_cents",
    "delay_sec": "vibrato_delay",
    "rate_hz": "vibrato_rate_hz",
}
```

- [ ] **Step 4: Add the voices merge**

```python
def _spread(roster, vibrato, named):
    """Push the [vibrato] keys this file named onto every instrument.

    Only the keys it named: spreading all three every time would let a later
    file with an unrelated [vibrato] table silently undo an earlier
    [voices.lead] override.
    """
    if not named:
        return roster
    changes = {_VIBRATO_SPREAD[field]: getattr(vibrato, field) for field in named}
    return tuple(
        replace(voice, instrument=replace(voice.instrument, **changes))
        for voice in roster
    )


def _voices(roster, raw, source):
    by_role = {voice.role: voice for voice in roster}
    if not isinstance(raw, dict):
        raise ConfigError(source, "voices", "expected tables like [voices.lead]")

    for role, body in raw.items():
        if role not in by_role:
            raise ConfigError(
                source,
                f"voices.{role}",
                f"unknown voice; the roster is {', '.join(by_role)}",
            )
        if not isinstance(body, dict):
            raise ConfigError(source, f"voices.{role}", "expected a table")

        voice_changes, instrument_changes = {}, {}
        for key, value in body.items():
            key_path = f"voices.{role}.{key}"
            if key in _VOICE_KEYS:
                field, check = _VOICE_KEYS[key]
                voice_changes[field] = check(value, source, key_path)
            elif key in _INSTRUMENT_KEYS:
                field, check = _INSTRUMENT_KEYS[key]
                instrument_changes[field] = check(value, source, key_path)
            else:
                known = ", ".join(sorted([*_VOICE_KEYS, *_INSTRUMENT_KEYS]))
                raise ConfigError(source, key_path, f"unknown key; a voice accepts {known}")

        voice = by_role[role]
        by_role[role] = replace(
            voice,
            instrument=replace(voice.instrument, **instrument_changes),
            **voice_changes,
        )

    return tuple(by_role[voice.role] for voice in roster)
```

- [ ] **Step 5: Teach `merge` the ordering**

Replace the body of `merge` below the `tomllib.loads` block:

```python
    changes = {}
    for name, body in raw.items():
        if name == "voices":
            continue  # handled below, after [vibrato] has had its say
        if name not in _TABLES:
            known = ", ".join(sorted([*_TABLES, "voices"]))
            raise ConfigError(source, name, f"unknown table; bitty config accepts {known}")
        changes[name] = _table(getattr(config, name), name, body, source)

    config = replace(config, **changes)

    # Order within one file: the global [vibrato] table sets every voice, then
    # [voices.<role>] overrides one. Across files the later file wins.
    named = [
        _TABLES["vibrato"][key][0]
        for key in raw.get("vibrato", {})
        if _TABLES["vibrato"][key][0] in _VIBRATO_SPREAD
    ]
    roster = _spread(config.voices, config.vibrato, named)
    if "voices" in raw:
        roster = _voices(roster, raw["voices"], source)
    return replace(config, voices=roster)
```

Note the `raw.get("vibrato", {})` read happens after `_table` has already
validated that table, so every key in it is known.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/bitty/config.py tests/test_config.py
git commit -m "feat: let config reshape the voice roster"
```

---

### Task 5: Layering, presets, and the two shipped preset files

**Files:**
- Modify: `src/bitty/config.py`
- Create: `src/bitty/presets/nes-tight.toml`
- Create: `src/bitty/presets/lush.toml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `merge` (Tasks 3-4).
- Produces: `config.preset_names() -> tuple[str, ...]`, `config.load(paths: list[Path], preset: str | None = None) -> Config`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
from bitty.config import load, preset_names


def test_a_later_file_beats_an_earlier_one(tmp_path):
    first = tmp_path / "a.toml"
    second = tmp_path / "b.toml"
    first.write_text("[echo]\nlevel = 0.1\ndelay_beats = 0.5\n")
    second.write_text("[echo]\nlevel = 0.9\n")
    result = load([first, second])
    assert result.echo.level == 0.9, "the later file wins the key it sets"
    assert result.echo.delay_beats == 0.5, "and leaves the rest of the earlier one"


def test_a_file_beats_the_preset_it_started_from(tmp_path):
    override = tmp_path / "bitty.toml"
    override.write_text("[echo]\non = true\n")
    assert load([override], preset="nes-tight").echo.on is True


def test_both_presets_ship_and_load():
    assert set(preset_names()) == {"lush", "nes-tight"}
    for name in preset_names():
        load([], preset=name)


def test_nes_tight_turns_the_echo_off_and_centres_the_image():
    result = load([], preset="nes-tight")
    assert result.echo.on is False
    assert all(voice.pan == 0.0 for voice in result.voices), "mono hardware, mono image"


def test_lush_widens_the_image_and_deepens_the_vibrato():
    result = load([], preset="lush")
    assert result.echo.on is True
    assert max(abs(voice.pan) for voice in result.voices) > 0.5
    assert result.vibrato.depth_cents > DEFAULTS.vibrato.depth_cents


def test_the_two_presets_actually_differ():
    assert load([], preset="lush") != load([], preset="nes-tight")


def test_an_unknown_preset_lists_the_ones_that_exist():
    with pytest.raises(ConfigError) as caught:
        load([], preset="chunky")
    assert "chunky" in str(caught.value)
    assert "nes-tight" in str(caught.value)


def test_loading_nothing_is_the_defaults():
    assert load([]) == DEFAULTS
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'load'`.

- [ ] **Step 3: Write the preset files**

`src/bitty/presets/nes-tight.toml`:

```toml
# Close to the hardware: no echo, a mono image, shallow late vibrato, and
# envelopes that decay rather than sit. The name overclaims slightly — without
# [voices] count this cannot drop to four channels, so it changes timbre only.

[echo]
on = false

[vibrato]
depth_cents = 12.0
delay_ms = 420

[voices.lead]
volume_env = [15, 14, 12, 10, 9, 8, 8]
pan = 0.0

[voices.counter]
duty = 0.125
volume_env = [12, 11, 9, 8, 7, 7]
pan = 0.0

[voices.inner_a]
volume_env = [11, 9, 8, 7, 7]
pan = 0.0

[voices.inner_b]
volume_env = [11, 9, 8, 7, 7]
pan = 0.0

[voices.bass]
volume_env = [15, 13, 11, 10]
pan = 0.0
```

`src/bitty/presets/lush.toml`:

```toml
# The other direction: a longer, louder echo, a wide image, and vibrato that
# arrives early enough to sing on ordinary phrase-length notes.

[echo]
level = 0.5
delay_beats = 1.0

[vibrato]
depth_cents = 40.0
delay_ms = 220
min_note_ms = 350

[voices.lead]
volume_env = [15, 15, 15, 14, 14, 13, 13, 13]
pan = -0.35
vibrato_cents = 55.0

[voices.counter]
pan = 0.65

[voices.inner_a]
pan = -0.65

[voices.inner_b]
pan = 0.35

[voices.bass]
volume_env = [15, 15, 14, 13, 13]
```

- [ ] **Step 4: Add `preset_names` and `load`**

Add `from importlib import resources` to the imports, then append to
`src/bitty/config.py`:

```python
PRESET_DIR = "presets"


def preset_names() -> tuple[str, ...]:
    """The shipped presets. The directory is the list, like TARGETS is for targets."""
    folder = resources.files("bitty") / PRESET_DIR
    return tuple(
        sorted(
            item.name.removesuffix(".toml")
            for item in folder.iterdir()
            if item.name.endswith(".toml")
        )
    )


def _preset_text(name: str) -> str:
    if name not in preset_names():
        raise ConfigError(
            f"preset {name}", "", f"unknown preset; try one of {', '.join(preset_names())}"
        )
    return (resources.files("bitty") / PRESET_DIR / f"{name}.toml").read_text()


def load(paths: list[Path], preset: str | None = None) -> Config:
    """Defaults, then the preset, then each file in order. Later wins."""
    config = DEFAULTS
    if preset is not None:
        config = merge(config, _preset_text(preset), f"preset {preset}")
    for path in paths:
        config = merge(config, path.read_text(), str(path))
    return config
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 6: Confirm the presets ship in a built wheel**

Hatchling includes every file under the package directory, but a preset that
does not reach an installed copy is a bug that only shows up after release.

```bash
.venv/bin/python -m pip install --quiet build 2>/dev/null || true
.venv/bin/python -c "
from importlib import resources
print(sorted(p.name for p in (resources.files('bitty') / 'presets').iterdir()))
"
```

Expected: `['lush.toml', 'nes-tight.toml']`. If the project is installed
non-editable and this returns nothing, add to `pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/bitty/presets" = "bitty/presets"
```

- [ ] **Step 7: Commit**

```bash
git add src/bitty/config.py src/bitty/presets tests/test_config.py
git commit -m "feat: layer config files over presets over defaults"
```

---

### Task 6: Discovery

**Files:**
- Modify: `src/bitty/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `load` (Task 5).
- Produces: `config.PROJECT_NAME = "bitty.toml"`, `config.PIECE_SUFFIX = ".bitty.toml"`, `config.discover(directory: Path, stem: str) -> list[Path]`, `config.resolve(directory: Path, stem: str, *, preset: str | None = None, explicit: Path | None = None) -> Config`.

`discover` takes a directory and a stem rather than a score path because
`bitty render` is handed `foo.arrangement.json` and still wants `foo.bitty.toml`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
from bitty.config import discover, resolve


def test_nothing_found_is_not_an_error(tmp_path):
    assert discover(tmp_path, "minuet") == []


def test_the_project_file_is_found_in_the_score_s_own_directory(tmp_path):
    (tmp_path / "bitty.toml").write_text("[echo]\nlevel = 0.5\n")
    assert discover(tmp_path, "minuet") == [tmp_path / "bitty.toml"]


def test_the_project_file_is_found_by_walking_upward(tmp_path):
    scores = tmp_path / "assets" / "scores"
    scores.mkdir(parents=True)
    (tmp_path / "bitty.toml").write_text("[echo]\nlevel = 0.5\n")
    assert discover(scores, "minuet") == [tmp_path / "bitty.toml"]


def test_the_nearest_project_file_wins_outright(tmp_path):
    """First hit, not merged across levels: a config either applies whole or not."""
    scores = tmp_path / "scores"
    scores.mkdir()
    (tmp_path / "bitty.toml").write_text("[echo]\nlevel = 0.1\n")
    (scores / "bitty.toml").write_text("[echo]\nlevel = 0.9\n")
    assert discover(scores, "minuet") == [scores / "bitty.toml"]


def test_the_per_piece_file_sits_above_the_project_file(tmp_path):
    (tmp_path / "bitty.toml").write_text("[echo]\nlevel = 0.1\n")
    (tmp_path / "minuet.bitty.toml").write_text("[echo]\nlevel = 0.9\n")
    assert discover(tmp_path, "minuet") == [
        tmp_path / "bitty.toml",
        tmp_path / "minuet.bitty.toml",
    ]
    assert resolve(tmp_path, "minuet").echo.level == 0.9


def test_a_per_piece_file_belongs_to_its_own_piece_only(tmp_path):
    (tmp_path / "minuet.bitty.toml").write_text("[echo]\nlevel = 0.9\n")
    assert discover(tmp_path, "ragtime") == []


def test_an_explicit_config_beats_everything_discovered(tmp_path):
    (tmp_path / "bitty.toml").write_text("[echo]\nlevel = 0.1\n")
    (tmp_path / "minuet.bitty.toml").write_text("[echo]\nlevel = 0.2\n")
    explicit = tmp_path / "elsewhere.toml"
    explicit.write_text("[echo]\nlevel = 0.9\n")
    assert resolve(tmp_path, "minuet", explicit=explicit).echo.level == 0.9


def test_a_discovered_file_beats_the_preset(tmp_path):
    (tmp_path / "bitty.toml").write_text("[echo]\non = true\n")
    assert resolve(tmp_path, "minuet", preset="nes-tight").echo.on is True


def test_resolve_with_nothing_around_is_the_defaults(tmp_path):
    assert resolve(tmp_path, "minuet") == DEFAULTS
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'discover'`.

- [ ] **Step 3: Implement discovery**

Append to `src/bitty/config.py`:

```python
PROJECT_NAME = "bitty.toml"
PIECE_SUFFIX = ".bitty.toml"


def discover(directory: Path, stem: str) -> list[Path]:
    """The project file then the per-piece file, lowest precedence first.

    The upward walk stops at the first `bitty.toml` it finds: a config two
    directories up either applies whole or not at all. Merging across levels
    would mean the value in front of you is never the whole story.

    The per-piece file is `<stem>.bitty.toml` rather than `<stem>.toml`,
    following the `.arrangement.json` convention — a bare `minuet.toml` would
    collide with whatever else in the directory wants that name.
    """
    directory = directory.resolve()
    found: list[Path] = []

    for folder in (directory, *directory.parents):
        candidate = folder / PROJECT_NAME
        if candidate.is_file():
            found.append(candidate)
            break

    piece = directory / f"{stem}{PIECE_SUFFIX}"
    if piece.is_file():
        found.append(piece)
    return found


def resolve(
    directory: Path,
    stem: str,
    *,
    preset: str | None = None,
    explicit: Path | None = None,
) -> Config:
    """Everything but the flags. The CLI applies those, because it owns them.

    `explicit` goes last because an explicit path is a deliberate act and
    should beat a file that merely happened to be found.
    """
    paths = discover(directory, stem)
    if explicit is not None:
        paths.append(explicit)
    return load(paths, preset)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bitty/config.py tests/test_config.py
git commit -m "feat: find project and per-piece config beside the score"
```

---

### Task 7: `arrange` takes a config

**Files:**
- Modify: `src/bitty/arrange.py` (imports:20-34, `arrange`:55-83, `_assign`:85, `_texture`:137-159, `_events`:195, `_arpeggiate`:233, `_arp_cycle`:263)
- Test: `tests/test_arrange.py`

**Interfaces:**
- Consumes: `config.Config`, `config.DEFAULTS`, `config.EchoSettings` (Task 2).
- Produces: `arrange(score: Score, config: Config = DEFAULTS) -> Arrangement`; `arrange.ARP_STEP_SEC` stays importable and now reads `DEFAULTS.arp.step_sec`.

The default argument is the regression seam: every existing caller and test
keeps working unchanged, and Task 2's assertion proves the default path is
byte-identical.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_arrange.py` (add `from bitty.config import DEFAULTS` and
`from dataclasses import replace` to its imports):

```python
def test_echo_off_leaves_the_lead_with_no_echo_object():
    """Not a silent echo — none. The arrangement should say which it is."""
    score = ingest(FIXTURE)
    settings = replace(DEFAULTS, echo=replace(DEFAULTS.echo, on=False))
    for channel in arrange(score, settings).channels:
        assert channel.echo is None


def test_the_echo_level_and_delay_come_from_config():
    score = ingest(FIXTURE)
    settings = replace(DEFAULTS, echo=replace(DEFAULTS.echo, level=0.6, delay_beats=1.5))
    lead = next(c for c in arrange(score, settings).channels if c.echo is not None)
    assert lead.echo.level == 0.6
    assert lead.echo.delay_sec == 1.5 * 60.0 / score.bpm


def test_a_reshaped_voice_reaches_the_channel_it_names():
    score = ingest(FIXTURE)
    roster = tuple(
        replace(v, instrument=replace(v.instrument, duty=0.125)) if v.role == "lead" else v
        for v in DEFAULTS.voices
    )
    lead = next(c for c in arrange(score, replace(DEFAULTS, voices=roster)).channels if c.role == "lead")
    assert lead.instrument.duty == 0.125


def test_the_vibrato_threshold_decides_which_notes_get_it():
    score = ingest(FIXTURE)
    never = replace(DEFAULTS, vibrato=replace(DEFAULTS.vibrato, min_note_sec=999.0))
    always = replace(DEFAULTS, vibrato=replace(DEFAULTS.vibrato, min_note_sec=0.0))
    assert not any(e.vibrato for c in arrange(score, never).channels for e in c.events)
    assert all(e.vibrato for c in arrange(score, always).channels for e in c.events)


def test_the_arpeggio_step_comes_from_config():
    score = ingest(Path(__file__).parent / "fixtures" / "ragtime.mxl")
    settings = replace(DEFAULTS, arp=replace(DEFAULTS.arp, step_sec=0.032))
    events = [e for c in arrange(score, settings).channels if c.role == "inner_b" for e in c.events]
    assert any(abs(e.dur - 0.032) < 1e-9 for e in events)
    assert not any(abs(e.dur - 0.016) < 1e-9 for e in events)


def test_the_default_argument_still_arranges():
    score = ingest(FIXTURE)
    assert arrange(score) == arrange(score, DEFAULTS)
```

Check the top of `tests/test_arrange.py` for the existing `FIXTURE` constant
and `ingest` import; reuse them rather than redefining. If `Path` is not
already imported there, add `from pathlib import Path`.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_arrange.py -v`
Expected: FAIL — `TypeError: arrange() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Rewrite `arrange` and `_echo`**

In `src/bitty/arrange.py`, replace `ARP_STEP_SEC = 0.016  # ...` with:

```python
ARP_STEP_SEC = DEFAULTS.arp.step_sec  # kept: tests and goldens read this name
```

Add `from bitty.config import DEFAULTS, Config, EchoSettings` to the imports,
and drop `MIN_NOTE_SEC` from the `bitty.lfo` import and `ROSTER` from the
`bitty.voices` import — neither is used after this task.

```python
def arrange(score: Score, config: Config = DEFAULTS) -> Arrangement:
    tracks, leftovers = _assign(score, config.voices)
    tracks[ARP_ROLE] = _arpeggiate(leftovers, tracks[ARP_ROLE], config.arp.step_sec)

    channels: list[Channel] = []
    for voice in config.voices:
        events = _events(tracks[voice.role], config.vibrato.min_note_sec)
        if not events:
            continue  # a two-voice score should not carry three silent channels
        channels.append(
            Channel(
                role=voice.role,
                instrument=voice.instrument,
                events=events,
                pan=voice.pan,
                echo=_echo(score.bpm, config.echo) if voice.role == LEAD_ROLE else None,
            )
        )

    meta = {"title": score.title, "bpm": score.bpm}
    if score.bars:
        meta["bars"] = [score.bars[0].number, score.bars[-1].number]

    return Arrangement(meta=meta, channels=tuple(channels))


def _echo(bpm: float, settings: EchoSettings) -> Echo | None:
    """None when echo is off, rather than an Echo at level zero.

    A channel with a silent echo is not the same object as a channel with
    none, and the arrangement is where that distinction is recorded.
    """
    if not settings.on:
        return None
    return Echo(delay_sec=settings.delay_beats * 60.0 / bpm, level=settings.level)
```

- [ ] **Step 4: Thread the roster and the two rates through the helpers**

`_assign` takes the roster:

```python
def _assign(score: Score, roster: tuple[Voice, ...]) -> tuple[Tracks, list[tuple[float, list[Note]]]]:
    tracks: Tracks = {voice.role: [] for voice in roster}
```

Add `Voice` to the `bitty.voices` import. `_texture` reads the roster off the
tracks it was given, which removes its dependency on `ROSTER` without
threading a second argument — the dict is built in roster order:

```python
    standing: list[int] = []
    for role, takes in tracks.items():
        held = _sounding(takes, onset)
        pitch = held if held is not None else (None if role == without else _last_pitch(takes))
        if pitch is not None:
            standing.append(pitch)
    return standing
```

`_events` takes the threshold:

```python
def _events(takes: list[_Take], min_note_sec: float) -> tuple[Event, ...]:
```

and its `vibrato=take.dur >= MIN_NOTE_SEC` becomes
`vibrato=take.dur >= min_note_sec`.

`_arpeggiate` and `_arp_cycle` take the step:

```python
def _arpeggiate(
    leftovers: list[tuple[float, list[Note]]], takes: list[_Take], step_sec: float
) -> list[_Take]:
```

with its final call becoming `out.extend(_arp_cycle(onset, span, pitches, vel, step_sec))`, and:

```python
def _arp_cycle(
    onset: float, span: float, pitches: list[int], vel: int, step_sec: float
) -> list[_Take]:
```

with `ARP_STEP_SEC` replaced by `step_sec` at all three uses inside it.

- [ ] **Step 5: Run the arranger tests**

Run: `.venv/bin/pytest tests/test_arrange.py tests/test_goldens.py tests/test_quality.py -v`
Expected: PASS, all of them. The goldens must not change — if
`test_arrangement_matches_its_golden` fails, the default path is not
identical and something in the threading is wrong.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/bitty/arrange.py tests/test_arrange.py
git commit -m "feat: arrange from a config rather than from module constants"
```

---

### Task 8: The loop cascade takes its slice

`Choice.describe()` reports a candidate against the limit it was judged by,
so the limit becomes a field on `Choice` rather than a module constant read
at print time.

**Files:**
- Modify: `src/bitty/loop.py` (constants:25-26, `candidates`:78, `_from_repeats`:104, `_from_sections`:149, `Choice`:178-206, `choose`:209, `_measure`:233)
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `config.DEFAULTS`, `config.LoopSettings` (Task 2).
- Produces: `loop.candidates(score, sections, loop_from=None, min_bars=MIN_LOOP_BARS)`, `loop.choose(candidates, audio, arrangement, sample_rate, seam_ratio=SEAM_RATIO)`, `Choice.seam_ratio: float`. `MIN_LOOP_BARS` and `SEAM_RATIO` stay importable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_loop.py`:

```python
def test_a_higher_min_bars_rejects_the_short_candidates():
    score = ingest(MINUET)
    sections = analyze(score)
    assert loop.candidates(score, sections, min_bars=4)
    assert not loop.candidates(score, sections, min_bars=999)


def test_min_bars_defaults_to_the_configured_value():
    score = ingest(MINUET)
    sections = analyze(score)
    assert loop.candidates(score, sections) == loop.candidates(
        score, sections, min_bars=loop.MIN_LOOP_BARS
    )


def test_a_stricter_seam_ratio_refuses_a_candidate_a_looser_one_accepts():
    score = ingest(MINUET)
    arrangement = arrange(score)
    audio = render(arrangement)
    found = loop.candidates(score, analyze(score))
    assert loop.choose(found, audio, arrangement, SAMPLE_RATE, seam_ratio=1000.0) is not None
    assert loop.choose(found, audio, arrangement, SAMPLE_RATE, seam_ratio=0.0) is None


def test_describe_reports_the_limit_it_was_judged_by():
    choice = loop.Choice(
        loop=Loop(start_sec=0.0, end_sec=1.0),
        candidate=loop.LoopCandidate(
            first_bar=1, last_bar=8, start=0.0, end=1.0, source="section"
        ),
        ratio=5.0,
        severed=0,
        echo_tails=0,
        seam_ratio=2.0,
    )
    assert "over 2" in choice.describe()
```

Check the imports already at the top of `tests/test_loop.py` — it imports
`arrange`, `render`, `SAMPLE_RATE`, `Loop`, and the fixtures. Add
`from bitty.analyze import analyze` and a `MINUET` fixture path if they are
not already there, matching how `tests/test_cli.py:13` defines its own.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_loop.py -v`
Expected: FAIL — `TypeError: candidates() got an unexpected keyword argument 'min_bars'`.

- [ ] **Step 3: Point the constants at the config defaults**

Replace lines 25-26 of `src/bitty/loop.py`, and add
`from bitty.config import DEFAULTS` to its imports:

```python
MIN_LOOP_BARS = DEFAULTS.loop.min_bars  # kept: the name callers and tests read
SEAM_RATIO = DEFAULTS.loop.seam_ratio  # real candidates measure 0.02-0.38
```

- [ ] **Step 4: Thread `min_bars` through the candidate builders**

```python
def candidates(
    score: Score, sections, loop_from: int | None = None, min_bars: int = MIN_LOOP_BARS
) -> tuple[LoopCandidate, ...]:
```

Inside it, pass `min_bars` to both `_from_repeats` and `_from_sections`, whose
signatures become:

```python
def _from_repeats(bars: tuple[Bar, ...], min_bars: int) -> list[LoopCandidate]:
def _from_sections(sections, min_bars: int) -> list[LoopCandidate]:
```

and whose filters become `if _length(first, last) >= min_bars` (line 145) and
`if last.last_bar - first.first_bar + 1 >= min_bars` (line 170). The manual
path (`_manual`) is unaffected: a typed bar number is not second-guessed.

- [ ] **Step 5: Put the limit on `Choice`**

Add a field to `Choice`, after `echo_tails`:

```python
    seam_ratio: float = SEAM_RATIO  # the limit this verdict was judged by
```

and in `describe()` replace the three `SEAM_RATIO` reads with
`self.seam_ratio`:

```python
        if self.ratio > self.seam_ratio:
            parts.append(f"seam ratio {self.ratio:.2f}, over {self.seam_ratio:g}")
        if not self.severed and self.ratio <= self.seam_ratio:
            parts.append("seam ok")
```

- [ ] **Step 6: Thread `seam_ratio` through `choose` and `_measure`**

```python
def choose(
    candidates: tuple[LoopCandidate, ...],
    audio: np.ndarray,
    arrangement: Arrangement,
    sample_rate: int,
    seam_ratio: float = SEAM_RATIO,
) -> Choice | None:
```

with the acceptance test becoming
`verdict.ratio <= seam_ratio and not verdict.severed`, the call becoming
`_measure(candidate, audio, arrangement, sample_rate, ordinary, seam_ratio)`,
and `_measure` gaining a trailing `seam_ratio: float` parameter that it passes
into the `Choice` it builds as `seam_ratio=seam_ratio`.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/pytest tests/test_loop.py tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 8: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/bitty/loop.py tests/test_loop.py
git commit -m "feat: take the loop thresholds from config"
```

---

### Task 9: The sample rate reaches the file that is written

5a's known gap: `write_audio` hard-codes 44100 while the kira emitter already
reads `render.sample_rate`. A configurable rate makes that inconsistency
audible, so it closes here.

**Files:**
- Modify: `src/bitty/targets.py:23-36` and its five `write_audio` call sites (lines 120, 150, 156, 162, 179)
- Test: `tests/test_targets.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `targets.write_audio(audio, out_dir, stem, audio_format="ogg", sample_rate=SAMPLE_RATE) -> Path`.

The default keeps the existing direct callers in `tests/test_targets.py`
working; every emitter passes `render.sample_rate` explicitly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_targets.py`:

```python
def test_write_audio_honours_the_sample_rate_it_is_given(tmp_path):
    path = targets.write_audio(a_render().audio, tmp_path, "piece", "wav", sample_rate=22050)
    _, rate = sf.read(path)
    assert rate == 22050


def test_an_emitter_writes_at_the_render_s_own_rate(tmp_path):
    """The 5a gap: the manifest said one rate and the file was written at another."""
    render = replace(a_render(), sample_rate=22050)
    targets.TARGETS["generic"](render, tmp_path, "piece", audio_format="wav")
    _, rate = sf.read(tmp_path / "piece.wav")
    assert rate == 22050
```

Add `from dataclasses import replace` and `import soundfile as sf` to that
file if they are not already imported. `Render` has `eq=False`, so `replace`
works but equality comparison does not — assert on the file, not the object.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_targets.py -v`
Expected: FAIL — `TypeError: write_audio() got an unexpected keyword argument 'sample_rate'`.

- [ ] **Step 3: Parameterize `write_audio`**

```python
def write_audio(
    audio: np.ndarray,
    out_dir: Path,
    stem: str,
    audio_format: str = "ogg",
    sample_rate: int = SAMPLE_RATE,
) -> Path:
    """Write a buffer and report it. Moved here from cli, echo intact."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.{audio_format}"

    if audio_format == "wav":
        sf.write(path, audio, sample_rate)
    else:
        sf.write(path, audio, sample_rate, format="OGG", subtype="VORBIS")

    typer.echo(f"{path}  ({len(audio) / sample_rate:.1f}s)")
    return path
```

Change the import at the top from `from bitty.synth import Render` to
`from bitty.synth import SAMPLE_RATE, Render`.

- [ ] **Step 4: Pass the render's rate at all five call sites**

Each becomes `write_audio(..., audio_format, sample_rate=render.sample_rate)`.
Find them with:

```bash
rg -n 'write_audio\(' src/bitty/targets.py
```

Expected: five call sites at lines 120, 150, 156, 162, and 179. The two split
calls (`_intro`, `_loop`) slice `render.audio` but keep the same rate.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_targets.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/bitty/targets.py tests/test_targets.py
git commit -m "fix: write audio at the render's own sample rate"
```

---

### Task 10: The CLI resolves config, and flags win

**Files:**
- Modify: `src/bitty/cli.py` (whole file)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `config.resolve`, `config.preset_names`, `config.ConfigError`, `config.Config` (Tasks 2-6); `arrange(score, config)` (Task 7); `loop.candidates(..., min_bars=)`, `loop.choose(..., seam_ratio=)` (Task 8); `Render.of(arrangement, audio, sample_rate)`.
- Produces: `--preset` and `--config` on `convert`, `render`, and `sections`; `--wav` / `--ogg`; config-backed defaults for `--target` and `-o`.

Every config-backed flag defaults to `None`. That is how the CLI tells "not
given" from "given the value that happens to be the default" — without it a
config file could never set a value a flag also has.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py` (add `import shutil` to its imports):

```python
def scored(tmp_path, name="two_part"):
    """Copy a fixture somewhere writable so config files can sit beside it."""
    target = tmp_path / f"{name}.musicxml"
    shutil.copy(FIXTURE, target)
    return target


def test_a_config_file_beside_the_score_changes_the_output_format(tmp_path):
    score = scored(tmp_path)
    (tmp_path / "bitty.toml").write_text('[output]\nformat = "wav"\n')
    result = runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "two_part.wav").exists()


def test_a_flag_beats_the_config_file(tmp_path):
    score = scored(tmp_path)
    (tmp_path / "bitty.toml").write_text('[output]\nformat = "wav"\n')
    result = runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "out"), "--ogg"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "two_part.ogg").exists()
    assert not (tmp_path / "out" / "two_part.wav").exists()


def test_the_out_dir_can_come_from_config(tmp_path):
    score = scored(tmp_path)
    (tmp_path / "bitty.toml").write_text(f'[output]\ndir = "{tmp_path / "built"}"\n')
    result = runner.invoke(app, ["convert", str(score)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "built" / "two_part.ogg").exists()


def test_a_config_file_can_choose_the_target(tmp_path):
    """generic writes no fragment, so the directory never grows a manifest."""
    score = scored(tmp_path)
    out = tmp_path / "out"
    (tmp_path / "bitty.toml").write_text('[output]\ntarget = "generic"\n')
    result = runner.invoke(app, ["convert", str(score), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "two_part.ogg").exists()
    assert not (out / "music.ron").exists()
    assert not list(out.glob("*.bevy.ron"))


def test_a_bad_config_aborts_before_anything_is_written(tmp_path):
    score = scored(tmp_path)
    out = tmp_path / "out"
    (tmp_path / "bitty.toml").write_text("[echo]\nlevl = 0.5\n")
    result = runner.invoke(app, ["convert", str(score), "-o", str(out)])
    assert result.exit_code != 0
    assert "echo.levl" in result.output
    assert not out.exists(), "nothing is written before the config resolves"


def test_an_unknown_target_in_config_is_reported(tmp_path):
    score = scored(tmp_path)
    (tmp_path / "bitty.toml").write_text('[output]\ntarget = "nintendo"\n')
    result = runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "out")])
    assert result.exit_code != 0
    assert "nintendo" in result.output


def test_a_preset_changes_the_arrangement(tmp_path):
    score = scored(tmp_path)
    runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "plain")])
    runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "nes"), "--preset", "nes-tight"])
    plain = Arrangement.from_json((tmp_path / "plain" / "two_part.arrangement.json").read_text())
    nes = Arrangement.from_json((tmp_path / "nes" / "two_part.arrangement.json").read_text())
    assert any(c.echo is not None for c in plain.channels)
    assert all(c.echo is None for c in nes.channels), "nes-tight turns the echo off"


def test_an_unknown_preset_lists_the_ones_that_exist(tmp_path):
    score = scored(tmp_path)
    result = runner.invoke(app, ["convert", str(score), "--preset", "chunky"])
    assert result.exit_code != 0
    assert "nes-tight" in result.output


def test_an_explicit_config_path_is_used(tmp_path):
    score = scored(tmp_path)
    elsewhere = tmp_path / "shared.toml"
    elsewhere.write_text('[output]\nformat = "wav"\n')
    result = runner.invoke(
        app, ["convert", str(score), "-o", str(tmp_path / "out"), "--config", str(elsewhere)]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "two_part.wav").exists()


def test_render_reads_the_config_beside_the_arrangement(tmp_path):
    score = scored(tmp_path)
    runner.invoke(app, ["convert", str(score), "-o", str(tmp_path)])
    (tmp_path / "bitty.toml").write_text('[output]\nformat = "wav"\n')
    result = runner.invoke(
        app, ["render", str(tmp_path / "two_part.arrangement.json"), "-o", str(tmp_path / "out")]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "two_part.wav").exists()


def test_sections_takes_a_preset_without_complaint(tmp_path):
    score = scored(tmp_path, "minuet")
    shutil.copy(MINUET, score)
    result = runner.invoke(app, ["sections", str(score), "--preset", "lush"])
    assert result.exit_code == 0, result.output


def test_a_configured_sample_rate_reaches_the_written_file(tmp_path):
    score = scored(tmp_path)
    (tmp_path / "bitty.toml").write_text('[output]\nformat = "wav"\nsample_rate = 22050\n')
    runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "out")])
    _, rate = sf.read(tmp_path / "out" / "two_part.wav")
    assert rate == 22050
```

Note `test_sections_takes_a_preset_without_complaint` copies the minuet over
the `.musicxml` name; use `shutil.copy(MINUET, tmp_path / "minuet.mxl")` and
pass that path instead if `music21` objects to the extension.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — `No such option: --config`.

- [ ] **Step 3: Add the settings resolution to `cli.py`**

Replace the header and helpers of `src/bitty/cli.py`:

```python
"""Command-line entry point."""

from dataclasses import replace
from pathlib import Path
from typing import Optional

import typer

from bitty import config as config_module
from bitty import loop as loop_stage
from bitty import targets
from bitty.analyze import analyze
from bitty.arrange import arrange
from bitty.arrangement import Arrangement
from bitty.config import Config
from bitty.ingest import ingest
from bitty.synth import Render
from bitty.synth import render as render_audio

app = typer.Typer(help="Turn classical scores into chiptune audio.")

ARRANGEMENT_SUFFIX = ".arrangement.json"
TARGET_HELP = f"{', '.join(sorted(targets.TARGETS))}."
PRESET_HELP = f"{', '.join(config_module.preset_names())}."


def _settings(
    directory: Path,
    stem: str,
    preset: str | None,
    explicit: Path | None,
    out_dir: Path | None,
    wav: bool | None,
    target: str | None,
) -> Config:
    """Files first, then flags.

    Every config-backed flag defaults to None, which is how the CLI tells "not
    given" from "given the value that happens to be the default". Without that
    a config file could never set a value a flag also names.
    """
    _check_preset(preset)
    try:
        resolved = config_module.resolve(directory, stem, preset=preset, explicit=explicit)
    except config_module.ConfigError as error:
        raise typer.BadParameter(str(error), param_hint="--config") from error

    output = resolved.output
    if out_dir is not None:
        output = replace(output, dir=out_dir)
    if wav is not None:
        output = replace(output, format="wav" if wav else "ogg")
    if target is not None:
        output = replace(output, target=target)

    _check_target(output.target)
    return replace(resolved, output=output)


def _check_preset(name: str | None) -> None:
    if name is not None and name not in config_module.preset_names():
        raise typer.BadParameter(
            f"unknown preset {name!r}; try one of {', '.join(config_module.preset_names())}",
            param_hint="--preset",
        )


def _emit(arrangement: Arrangement, audio, stem: str, settings: Config) -> None:
    """One path for every write. Targets own the file layout; config owns the flags."""
    render = Render.of(arrangement, audio, settings.output.sample_rate)
    targets.TARGETS[settings.output.target](
        render, settings.output.dir, stem, audio_format=settings.output.format
    )
    targets.assemble(settings.output.dir, settings.output.target)
```

Keep `_check_target` as it is. `DEFAULT_TARGET` and the `SAMPLE_RATE` import
are no longer used — delete both.

- [ ] **Step 4: Rewrite `convert`**

```python
@app.command()
def convert(
    score: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Optional[Path] = typer.Option(None, "-o", "--out-dir"),
    wav: Optional[bool] = typer.Option(
        None, "--wav/--ogg", help="Write uncompressed WAV instead of Ogg."
    ),
    bars: str = typer.Option(None, "--bars", help="Printed bar range to keep, e.g. 9-16."),
    loop_from: int = typer.Option(
        None, "--loop-from", help="Printed bar the loop starts at. Overrides the cascade."
    ),
    target: Optional[str] = typer.Option(None, "--target", help=TARGET_HELP),
    preset: Optional[str] = typer.Option(None, "--preset", help=PRESET_HELP),
    config_path: Optional[Path] = typer.Option(
        None, "--config", exists=True, dir_okay=False, readable=True
    ),
) -> None:
    """Convert a score to audio and its arrangement JSON."""
    settings = _settings(
        score.parent, score.stem, preset, config_path, out_dir, wav, target
    )

    parsed = ingest(score)
    if bars:
        first, last = _bar_range(bars)
        try:
            parsed = loop_stage.trim(parsed, first, last)
        except ValueError as error:
            raise typer.BadParameter(str(error), param_hint="--bars") from error

    try:
        candidates = loop_stage.candidates(
            parsed, analyze(parsed), loop_from, min_bars=settings.loop.min_bars
        )
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--loop-from") from error

    arrangement = arrange(parsed, settings)
    audio = render_audio(arrangement, settings.output.sample_rate)
    chosen = loop_stage.choose(
        candidates,
        audio,
        arrangement,
        settings.output.sample_rate,
        seam_ratio=settings.loop.seam_ratio,
    )
    arrangement = replace(arrangement, loop=chosen.loop if chosen else None)

    _report(chosen)
    _emit(arrangement, audio, score.stem, settings)

    json_path = settings.output.dir / f"{score.stem}{ARRANGEMENT_SUFFIX}"
    json_path.write_text(arrangement.to_json())
    typer.echo(f"{json_path}")
```

`_settings` runs before `ingest`, so a bad config aborts before any parsing
or writing. `_emit` creates the output directory, so a failed run leaves none.

- [ ] **Step 5: Rewrite `render` and `sections`**

```python
@app.command()
def render(
    arrangement: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Optional[Path] = typer.Option(None, "-o", "--out-dir"),
    wav: Optional[bool] = typer.Option(
        None, "--wav/--ogg", help="Write uncompressed WAV instead of Ogg."
    ),
    target: Optional[str] = typer.Option(None, "--target", help=TARGET_HELP),
    preset: Optional[str] = typer.Option(None, "--preset", help=PRESET_HELP),
    config_path: Optional[Path] = typer.Option(
        None, "--config", exists=True, dir_okay=False, readable=True
    ),
) -> None:
    """Re-render a hand-edited arrangement, skipping analysis entirely.

    Only the [output] half of the config can matter here: everything musical
    was decided when the JSON was written, and this command obeys the file.
    """
    stem = _stem(arrangement)
    settings = _settings(
        arrangement.parent, stem, preset, config_path, out_dir, wav, target
    )
    loaded = Arrangement.from_json(arrangement.read_text())
    audio = render_audio(loaded, settings.output.sample_rate)
    _emit(loaded, audio, stem, settings)
```

In `sections`, add the same `preset` and `config_path` options plus:

```python
    settings = _settings(score.parent, score.stem, preset, config_path, None, None, None)
```

as its first statement, then change its three pipeline calls to
`arrange(parsed, settings)`,
`loop_stage.candidates(parsed, found, min_bars=settings.loop.min_bars)`, and

```python
    chosen = loop_stage.choose(
        loop_stage.candidates(parsed, found, min_bars=settings.loop.min_bars),
        render_audio(arrangement, settings.output.sample_rate),
        arrangement,
        settings.output.sample_rate,
        seam_ratio=settings.loop.seam_ratio,
    )
```

- [ ] **Step 6: Run the CLI tests**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS. If Typer rejects the `Optional[bool]` flag pair, check its
version with `.venv/bin/pip show typer` — the `--wav/--ogg` form needs
`Optional[bool]` rather than `bool | None` on older releases, which is why the
import of `Optional` is there.

- [ ] **Step 7: Check the flags by hand**

```bash
.venv/bin/bitty convert --help
.venv/bin/bitty convert tests/fixtures/minuet.mxl -o "${TMPDIR:-/tmp}/bitty-check" --preset lush --wav
```

Expected: the help lists `--preset`, `--config`, and `--wav / --ogg`; the run
writes WAV files and reports a loop.

- [ ] **Step 8: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/bitty/cli.py tests/test_cli.py
git commit -m "feat: resolve config in the CLI, with flags on top"
```

---

### Task 11: Documentation and the audition

**Files:**
- Modify: `README.md` (targets section, new config section, `## Status:345-354`)
- No test changes.

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code reads.

- [ ] **Step 1: Document the config layer in `README.md`**

Add a `## Configuration` section before `## Status`, covering: the precedence
table from the spec; the file names (`bitty.toml`, `<stem>.bitty.toml`) and
the first-hit-wins upward walk; a complete annotated example of every key with
its default; the `[voices.<role>]` table and the five role names; the rule
that TOML is milliseconds and the code is seconds; the two presets and what
each is for; and the fact that an unknown key is an error rather than a
warning, with an example message.

State plainly that `nes-tight` changes timbre only — it cannot drop to four
channels, because there is no `count` key yet.

- [ ] **Step 2: Fill the `bevy-kira` documentation gap carried over from 5a**

The README documents the Rust struct for the `bevy` and `generic` targets but
describes `bevy-kira` in prose only, and that is the target the spec flags as
"most likely to be wrong in a way nothing catches". Add the struct definition
alongside the others, reading the real shape off the emitter:

```bash
rg -n -A25 'def _kira|"bevy-kira"' src/bitty/targets.py
.venv/bin/bitty convert tests/fixtures/minuet.mxl -o "${TMPDIR:-/tmp}/kira" --target bevy-kira
cat "${TMPDIR:-/tmp}/kira/music.ron"
```

Write the struct to match what `music.ron` actually contains, not what the
prose claims.

- [ ] **Step 3: Update the Status section**

Replace the paragraph at `README.md:345-354` so it reads that Phase 5 is
complete — 5a's targets and 5b's config — and names what is deliberately
still ahead: `[transform]`, `voices.count`, and the tail-wrapping question
deferred since 4b.

- [ ] **Step 4: Audition the presets**

Render the minuet three ways as WAV. Ogg plays back as static through
`aplay`, so WAV is not a preference here — it is the only format that works.

```bash
AUD="${TMPDIR:-/tmp}/bitty-audition"
for preset in "" nes-tight lush; do
  name="${preset:-default}"
  .venv/bin/bitty convert tests/fixtures/minuet.mxl -o "$AUD/$name" --wav \
    ${preset:+--preset "$preset"}
done
ls -R "$AUD"
```

Then play each and listen for: the echo present by default and absent under
`nes-tight`; the image collapsing to centre under `nes-tight` and widening
under `lush`; vibrato arriving later and shallower under `nes-tight`.

```bash
aplay "$AUD/default/minuet_loop.wav"
aplay "$AUD/nes-tight/minuet_loop.wav"
aplay "$AUD/lush/minuet_loop.wav"
```

Report what the three sound like before committing. If a preset is
indistinguishable from the default, that is a finding — say so rather than
shipping a name that means nothing.

- [ ] **Step 5: Run the full suite and commit**

```bash
.venv/bin/pytest
git add README.md
git commit -m "docs: document config, presets, and the bevy-kira manifest"
```

- [ ] **Step 6: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to decide how this
integrates, and `superpowers:requesting-code-review` before merging.
