# Phase 2: Synth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Phase 1 placeholder synthesizer with the real one — bandlimited oscillators, tracker-style envelopes, a per-instrument lowpass, stereo, echo, and Ogg output — so that Phase 3's arranging decisions can actually be judged by ear.

**Architecture:** `synth.py` stops being one file and becomes a mixer over three
small DSP modules: `osc.py` (waveform generation), `envelope.py` (step
sequences), and `filters.py` (biquad lowpass and DC blocker). `synth.py` itself
only walks the `Arrangement`, renders each channel to mono, filters it, pans it,
taps an echo, sums, and soft-clips. The `Arrangement` contract grows the fields
those stages read — flat, optional, and defaulted, so every Phase 1 arrangement
still loads.

**Tech Stack:** Python 3.11+, numpy (DSP), scipy (`lfilter` for the biquad
recursions), soundfile (Ogg Vorbis via libsndfile), typer (CLI), pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-bitty-music-design.md`

## Global Constraints

- Python 3.11+.
- Phase 2 adds exactly one dependency: `scipy`. `librosa`, `mutagen`, and
  `sounddevice` belong to later phases — do not add them.
- Do not hand-roll audio encoding, metadata tag writing, key detection,
  structural segmentation, or score parsing. Libraries own those.
- MIDI note numbers for pitch. Seconds for time. Velocity 0–15 inside an
  `Arrangement`, 0–127 in a `Score`.
- Synthesis is deterministic: identical input renders identical output bytes.
  The noise LFSR is seeded; nothing calls `random` or `Math.random`-alikes.
- Envelopes are tracker-style step sequences at **60 steps per second**, not
  ADSR. The last step sustains for the rest of the note.
- Source layout is `src/bitty/`, tests in `tests/`.
- No golden audio blobs in tests. Synth tests are property tests — FFT peak
  location, aliasing energy, clipping bounds, byte-identical re-renders.

## Design decisions settled before planning

These were decided in dialog on 2026-08-20 and are not open for
re-litigation mid-execution:

- **Oscillators stay a dict of plain functions** keyed by wave name. PolyBLEP
  changes the signature, not the shape. No class hierarchy, no registry object.
- **`Instrument` grows flat optional fields**, not nested `envelope: {...}` /
  `filter: {...}` sub-objects and not a free-form `params` dict.
  `arrangement.json` is the hand-edit surface; flat and readable wins.
- **Echo and pan are JSON contract fields on `Channel`**, not renderer policy.
  Echo is per-channel and hand-editable.
- **The lowpass filter ships off by default.** `cutoff_hz=None` means no
  filtering, so the default output stays true to the spec's chiptune fidelity
  target. The filter is the "make it warmer" lever, available when wanted.

## Deliberately deferred to later phases

Do not build these now, and do not add fields for them: voice-leading
assignment, arpeggio overflow, vibrato, more than two channels, tempo maps,
repeat marks, key detection, section analysis, loop points, config files,
presets-by-name, engine targets, `bitty render`, `bitty sections`, `--play`.

Phase 2 ends when the same Bach chorale from Phase 1 comes out sounding like
chiptune rather than like a buzzer.

## File Structure

| File | Responsibility |
|------|----------------|
| `pyproject.toml` | Adds `scipy` to dependencies |
| `src/bitty/arrangement.py` | **Modify** — `Echo`; new `Instrument` and `Channel` fields; tolerant `from_json` |
| `src/bitty/osc.py` | **Create** — PolyBLEP pulse and saw, triangle, seeded-LFSR noise |
| `src/bitty/envelope.py` | **Create** — step-sequence sampling at 60 steps/sec |
| `src/bitty/filters.py` | **Create** — resonant biquad lowpass, DC blocker |
| `src/bitty/synth.py` | **Rewrite** — per-channel render, filter, pan, echo, mix, soft clip |
| `src/bitty/arrange.py` | **Modify** — chiptune instrument presets, pan, echo |
| `src/bitty/cli.py` | **Modify** — Ogg output by default, `--wav` escape hatch |
| `tests/test_osc.py` | **Create** — pitch, aliasing energy, determinism |
| `tests/test_envelope.py` | **Create** — step timing, sustain, empty case |
| `tests/test_filters.py` | **Create** — passband, stopband, resonance, DC null |
| `tests/test_synth.py` | **Rewrite** — stereo, pan, echo, clipping, determinism |
| `tests/test_arrangement.py` | **Modify** — new fields round-trip, old files still load |
| `tests/test_arrange.py` | **Modify** — presets present |
| `tests/test_cli.py` | **Modify** — `.ogg` default, `--wav` |

The three DSP modules are separate from `synth.py` on purpose. Each is a pure
function of arrays with no knowledge of `Arrangement`, which is what makes them
testable as properties rather than through a whole render.

**Natural split point:** if this session gets tight, Tasks 1–4 (the contract
and the three DSP modules) and Tasks 5–7 (the mixer and everything audible) are
a clean break. Tasks 1–4 leave the suite green with the old synth still in
place.

---

### Task 1: Arrangement contract extensions

**Files:**
- Modify: `src/bitty/arrangement.py`
- Test: `tests/test_arrangement.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Echo(delay_sec: float, level: float)` — frozen dataclass.
  - `Instrument(wave: str, duty: float = 0.5, volume_env: tuple[int, ...] = (), pitch_env: tuple[int, ...] = (), cutoff_hz: float | None = None, resonance: float = 0.7071, quantize: int | None = None)`
  - `Channel(role: str, instrument: Instrument, events: tuple[Event, ...], pan: float = 0.0, echo: Echo | None = None)`
  - `Arrangement.from_json` ignores unknown `instrument` keys instead of raising.

`volume_env` holds levels 0–15. `pitch_env` holds semitone offsets, signed.
`pan` is −1.0 (hard left) to +1.0 (hard right). `quantize` is the number of
amplitude steps a triangle is crushed to, or `None` for smooth.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_arrangement.py`:

```python
def test_instrument_defaults_are_phase_one_compatible():
    instrument = Instrument(wave="pulse")
    assert instrument.duty == 0.5
    assert instrument.volume_env == ()
    assert instrument.pitch_env == ()
    assert instrument.cutoff_hz is None
    assert instrument.quantize is None


def test_channel_defaults_to_centre_with_no_echo():
    channel = Channel(role="lead", instrument=Instrument(wave="pulse"), events=())
    assert channel.pan == 0.0
    assert channel.echo is None


def test_new_fields_survive_the_json_round_trip():
    original = Arrangement(
        meta={"title": "t", "bpm": 120.0},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(
                    wave="pulse",
                    duty=0.25,
                    volume_env=(15, 13, 11),
                    pitch_env=(2, 1, 0),
                    cutoff_hz=2400.0,
                    resonance=1.5,
                    quantize=16,
                ),
                events=(Event(t=0.0, pitch=60, dur=1.0, vel=15),),
                pan=-0.3,
                echo=Echo(delay_sec=0.375, level=0.4),
            ),
        ),
    )
    reloaded = Arrangement.from_json(original.to_json())
    assert reloaded == original


def test_envelopes_reload_as_tuples_not_lists():
    channel = Channel(
        role="lead",
        instrument=Instrument(wave="pulse", volume_env=(15, 12)),
        events=(),
    )
    arrangement = Arrangement(meta={}, channels=(channel,))
    reloaded = Arrangement.from_json(arrangement.to_json())
    assert reloaded.channels[0].instrument.volume_env == (15, 12)


def test_unknown_instrument_fields_are_ignored():
    """A newer bitty writes a field this build has never heard of."""
    text = json.dumps(
        {
            "meta": {},
            "channels": [
                {
                    "role": "lead",
                    "instrument": {"wave": "pulse", "duty": 0.5, "wobble": 7},
                    "events": [],
                }
            ],
        }
    )
    arrangement = Arrangement.from_json(text)
    assert arrangement.channels[0].instrument.wave == "pulse"
```

Add `Echo` to the existing import line at the top of the file, and `import
json` if it is not already there.

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_arrangement.py -v`
Expected: FAIL — `ImportError: cannot import name 'Echo'`

- [x] **Step 3: Extend the contract**

Replace the dataclasses and `from_json` in `src/bitty/arrangement.py`:

```python
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
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_arrangement.py -v`
Expected: PASS

- [x] **Step 5: Run the whole suite — nothing else may break**

Run: `.venv/bin/pytest -q`
Expected: all pass. Every new field is defaulted, so Phase 1 call sites are
untouched.

- [x] **Step 6: Commit**

```bash
git add src/bitty/arrangement.py tests/test_arrangement.py
git commit -m "feat: extend the Arrangement contract with envelopes, filter, pan, and echo"
```

---

### Task 2: Bandlimited oscillators

**Files:**
- Create: `src/bitty/osc.py`
- Test: `tests/test_osc.py`

**Interfaces:**
- Consumes: `Instrument` from Task 1.
- Produces: `oscillator(name: str) -> Callable[[np.ndarray, np.ndarray, Instrument], np.ndarray]`.
  Every oscillator takes `(phase, inc, instrument)` and returns float64 in
  roughly [−1, 1] of the same length.
  - `phase` is **unwrapped** cumulative phase in cycles (0.0, 0.011, 0.022, …),
    not wrapped to [0, 1). Unwrapped is what lets `noise` index its LFSR by
    `floor(phase)` and what makes pitch envelopes just a varying `inc`.
  - `inc` is the per-sample phase increment, `freq / sample_rate`, one value per
    sample. PolyBLEP needs it to know how wide a correction to apply.
- Also produces `NOISE_SEED = 1` and `poly_blep(t, dt)` for tests to reach.

- [x] **Step 1: Write the failing tests**

`tests/test_osc.py`:

```python
import numpy as np

from bitty.arrangement import Instrument
from bitty.osc import oscillator

SAMPLE_RATE = 44100


def phase_for(freq: float, seconds: float = 1.0, sample_rate: int = SAMPLE_RATE):
    n = int(seconds * sample_rate)
    inc = np.full(n, freq / sample_rate)
    phase = np.concatenate(([0.0], np.cumsum(inc)[:-1]))
    return phase, inc


def dominant_frequency(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    spectrum = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1 / sample_rate)
    return float(freqs[int(np.argmax(spectrum))])


def alias_fraction(audio: np.ndarray, f0: float, sample_rate: int = SAMPLE_RATE) -> float:
    """Share of spectral energy sitting on bins that are not harmonics of f0.

    Aliased partials fold back to arbitrary frequencies, so energy off the
    harmonic grid is the direct measure of how badly an oscillator aliases.
    """
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
    freqs = np.fft.rfftfreq(len(audio), 1 / sample_rate)
    harmonic = np.zeros(len(freqs), dtype=bool)
    k = 1
    while f0 * k < sample_rate / 2:
        harmonic |= np.abs(freqs - f0 * k) < 30.0
        k += 1
    return float(np.sum(spectrum[~harmonic] ** 2) / np.sum(spectrum**2))


def test_every_wave_sounds_at_its_written_pitch():
    phase, inc = phase_for(440.0)
    for wave in ("pulse", "triangle", "saw"):
        audio = oscillator(wave)(phase, inc, Instrument(wave=wave))
        assert abs(dominant_frequency(audio) - 440.0) < 2.0, wave


def test_polyblep_pulse_aliases_far_less_than_a_naive_square():
    """The spec's stated reason for PolyBLEP: classical melodies live above 1 kHz."""
    phase, inc = phase_for(3520.0)
    naive = np.where(phase % 1.0 < 0.5, 1.0, -1.0)
    blep = oscillator("pulse")(phase, inc, Instrument(wave="pulse"))
    assert alias_fraction(blep, 3520.0) < alias_fraction(naive, 3520.0) / 10.0


def test_polyblep_saw_aliases_far_less_than_a_naive_ramp():
    phase, inc = phase_for(3520.0)
    naive = 2.0 * (phase % 1.0) - 1.0
    blep = oscillator("saw")(phase, inc, Instrument(wave="saw"))
    assert alias_fraction(blep, 3520.0) < alias_fraction(naive, 3520.0) / 10.0


def test_duty_cycle_changes_the_pulse_width():
    phase, inc = phase_for(440.0)
    narrow = oscillator("pulse")(phase, inc, Instrument(wave="pulse", duty=0.125))
    wide = oscillator("pulse")(phase, inc, Instrument(wave="pulse", duty=0.5))
    assert narrow.mean() < wide.mean() - 0.5


def test_oscillators_stay_within_range():
    phase, inc = phase_for(440.0)
    for wave in ("pulse", "triangle", "saw", "noise"):
        audio = oscillator(wave)(phase, inc, Instrument(wave=wave))
        assert np.max(np.abs(audio)) <= 1.35, wave


def test_triangle_quantization_crushes_to_discrete_levels():
    phase, inc = phase_for(440.0)
    crushed = oscillator("triangle")(phase, inc, Instrument(wave="triangle", quantize=16))
    assert len(np.unique(np.round(crushed, 6))) <= 17


def test_noise_is_seeded_and_therefore_deterministic():
    phase, inc = phase_for(440.0)
    first = oscillator("noise")(phase, inc, Instrument(wave="noise"))
    second = oscillator("noise")(phase, inc, Instrument(wave="noise"))
    assert np.array_equal(first, second)


def test_noise_is_actually_noisy():
    phase, inc = phase_for(440.0)
    audio = oscillator("noise")(phase, inc, Instrument(wave="noise"))
    assert alias_fraction(audio, 440.0) > 0.5


def test_unknown_wave_fails_loudly():
    phase, inc = phase_for(440.0)
    try:
        oscillator("bagpipe")
    except ValueError as error:
        assert "bagpipe" in str(error)
    else:
        raise AssertionError("expected ValueError")
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_osc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bitty.osc'`

- [x] **Step 3: Write the oscillators**

`src/bitty/osc.py`:

```python
"""Waveform generation. Pure numpy, no knowledge of arrangements or time.

Every oscillator has the same signature: unwrapped cumulative `phase` in
cycles, the per-sample increment `inc` that produced it, and the `Instrument`
carrying the timbre knobs. Returning to `inc` rather than a scalar frequency is
what lets pitch envelopes work — a note that bends is just a varying increment.
"""

from collections.abc import Callable

import numpy as np

from bitty.arrangement import Instrument

NOISE_SEED = 1
LFSR_WIDTH = 15


def oscillator(name: str) -> Callable[[np.ndarray, np.ndarray, Instrument], np.ndarray]:
    try:
        return _OSCILLATORS[name]
    except KeyError:
        raise ValueError(f"unknown wave {name!r}") from None


def poly_blep(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """The correction that turns a sampled step into a bandlimited one.

    A naive square jumps between two samples, which is an infinitely sharp
    edge and therefore infinite bandwidth — everything above Nyquist folds
    back down as inharmonic junk. This adds a two-sample polynomial ramp
    around each discontinuity, which is the cheapest good approximation of
    the bandlimited step. Roughly twenty lines for most of the defined sound.
    """
    out = np.zeros_like(t)

    rising = t < dt
    x = t[rising] / dt[rising]
    out[rising] = x + x - x * x - 1.0

    falling = t > 1.0 - dt
    x = (t[falling] - 1.0) / dt[falling]
    out[falling] = x * x + x + x + 1.0

    return out


def _pulse(phase: np.ndarray, inc: np.ndarray, instrument: Instrument) -> np.ndarray:
    duty = instrument.duty
    wrapped = phase % 1.0
    out = np.where(wrapped < duty, 1.0, -1.0)
    out = out + poly_blep(wrapped, inc)
    out = out - poly_blep((wrapped - duty) % 1.0, inc)
    return out


def _saw(phase: np.ndarray, inc: np.ndarray, instrument: Instrument) -> np.ndarray:
    wrapped = phase % 1.0
    return 2.0 * wrapped - 1.0 - poly_blep(wrapped, inc)


def _triangle(phase: np.ndarray, inc: np.ndarray, instrument: Instrument) -> np.ndarray:
    """No PolyBLEP here, deliberately.

    A triangle is continuous — only its slope jumps — so its harmonics fall
    off as 1/n^2 instead of 1/n and the aliasing is far below the noise floor
    of everything else in the mix. The spec asks for bandlimiting on pulse and
    saw specifically.
    """
    out = 4.0 * np.abs((phase + 0.25) % 1.0 - 0.5) - 1.0
    if instrument.quantize:
        steps = instrument.quantize
        out = np.round(out * (steps / 2)) / (steps / 2)
    return out


def _noise(phase: np.ndarray, inc: np.ndarray, instrument: Instrument) -> np.ndarray:
    """Seeded 15-bit LFSR, clocked once per phase cycle — the NES noise channel."""
    step = np.floor(phase).astype(np.int64)
    bits = _lfsr_bits(int(step[-1]) + 1 if len(step) else 0)
    return bits[step]


def _lfsr_bits(count: int) -> np.ndarray:
    register = NOISE_SEED
    bits = np.empty(count, dtype=np.float64)
    for i in range(count):
        bits[i] = 1.0 if register & 1 else -1.0
        feedback = (register ^ (register >> 1)) & 1
        register = (register >> 1) | (feedback << (LFSR_WIDTH - 1))
    return bits


_OSCILLATORS = {
    "pulse": _pulse,
    "triangle": _triangle,
    "saw": _saw,
    "noise": _noise,
}
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_osc.py -v`
Expected: PASS, 9 tests

If `test_oscillators_stay_within_range` fails on pulse, that is expected
physics, not a bug — PolyBLEP overshoots slightly at the corrected edges,
which is why the bound is 1.35 rather than 1.0. The mixer's soft clipper is
what keeps the final output in range.

- [x] **Step 5: Commit**

```bash
git add src/bitty/osc.py tests/test_osc.py
git commit -m "feat: add bandlimited PolyBLEP oscillators and seeded noise"
```

---

### Task 3: Step-sequence envelopes

**Files:**
- Create: `src/bitty/envelope.py`
- Test: `tests/test_envelope.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ENV_RATE_HZ = 60.0` and
  `step_values(steps: tuple[int, ...], length: int, sample_rate: int) -> np.ndarray`
  returning a float64 array of `length` samples holding the raw step values,
  with the final step sustained to the end. An empty `steps` returns an array
  of ones, which is the "no envelope" identity for both volume and — after the
  caller's own handling — pitch.

- [x] **Step 1: Write the failing tests**

`tests/test_envelope.py`:

```python
import numpy as np

from bitty.envelope import ENV_RATE_HZ, step_values

SAMPLE_RATE = 44100
SAMPLES_PER_STEP = int(SAMPLE_RATE / ENV_RATE_HZ)


def test_envelope_runs_at_sixty_steps_per_second():
    assert ENV_RATE_HZ == 60.0


def test_each_step_holds_for_one_sixtieth_of_a_second():
    values = step_values((15, 10, 5), SAMPLE_RATE, SAMPLE_RATE)
    assert values[0] == 15.0
    assert values[SAMPLES_PER_STEP - 1] == 15.0
    assert values[SAMPLES_PER_STEP] == 10.0
    assert values[2 * SAMPLES_PER_STEP] == 5.0


def test_the_last_step_sustains_for_the_rest_of_the_note():
    """Chip voices have no natural decay; a short envelope must not cut a long note."""
    values = step_values((15, 10, 5), SAMPLE_RATE, SAMPLE_RATE)
    assert values[-1] == 5.0
    assert np.all(values[3 * SAMPLES_PER_STEP:] == 5.0)


def test_an_empty_envelope_is_the_identity():
    values = step_values((), 1000, SAMPLE_RATE)
    assert np.array_equal(values, np.ones(1000))


def test_a_note_shorter_than_one_step_still_renders():
    values = step_values((15, 10), 10, SAMPLE_RATE)
    assert len(values) == 10
    assert np.all(values == 15.0)


def test_negative_steps_are_preserved_for_pitch_envelopes():
    values = step_values((-2, 0), SAMPLES_PER_STEP * 2, SAMPLE_RATE)
    assert values[0] == -2.0
    assert values[-1] == 0.0
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_envelope.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bitty.envelope'`

- [x] **Step 3: Write the envelope sampler**

`src/bitty/envelope.py`:

```python
"""Tracker-style step envelopes: a list of levels, one per 60th of a second.

Not ADSR, on purpose. Step sequences are the native chiptune idiom, they match
the 16 dynamic levels the spec quantizes to, and they read as plain numbers in
`arrangement.json` where someone can edit them.
"""

import numpy as np

ENV_RATE_HZ = 60.0


def step_values(steps: tuple[int, ...], length: int, sample_rate: int) -> np.ndarray:
    """Expand a step sequence to one value per sample, sustaining the last step."""
    if not steps:
        return np.ones(length, dtype=np.float64)

    samples_per_step = sample_rate / ENV_RATE_HZ
    index = (np.arange(length, dtype=np.float64) / samples_per_step).astype(np.int64)
    index = np.minimum(index, len(steps) - 1)
    return np.asarray(steps, dtype=np.float64)[index]
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_envelope.py -v`
Expected: PASS, 6 tests

- [x] **Step 5: Commit**

```bash
git add src/bitty/envelope.py tests/test_envelope.py
git commit -m "feat: add tracker-style step envelopes at 60 steps per second"
```

---

### Task 4: Resonant lowpass and DC blocker

**Files:**
- Modify: `pyproject.toml`
- Create: `src/bitty/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `lowpass(signal: np.ndarray, cutoff_hz: float, resonance: float, sample_rate: int) -> np.ndarray`
  - `dc_block(signal: np.ndarray) -> np.ndarray`

Both accept mono `(n,)` or stereo `(n, 2)` and filter along axis 0.

**Why scipy:** these are recursive IIR filters — each output sample depends on
the previous two. A Python loop over 2.6 million samples is the wrong tool, and
`scipy.signal.lfilter` is the maintained implementation of exactly this
recursion. scipy also arrives in Phase 4 regardless as a librosa dependency.

- [x] **Step 1: Add scipy and install it**

In `pyproject.toml`, extend `dependencies`:

```toml
dependencies = [
    "music21>=9.1",
    "numpy>=1.26",
    "scipy>=1.11",
    "soundfile>=0.12",
    "typer>=0.12",
]
```

Run: `.venv/bin/pip install -e '.[dev]'`
Expected: scipy installs.

- [x] **Step 2: Write the failing tests**

`tests/test_filters.py`:

```python
import numpy as np

from bitty.filters import dc_block, lowpass

SAMPLE_RATE = 44100


def sine(freq: float, seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return np.sin(2.0 * np.pi * freq * t)


def rms(signal: np.ndarray) -> float:
    return float(np.sqrt(np.mean(signal**2)))


def gain(freq: float, cutoff: float, resonance: float = 0.7071) -> float:
    signal = sine(freq)
    return rms(lowpass(signal, cutoff, resonance, SAMPLE_RATE)) / rms(signal)


def test_the_passband_is_left_alone():
    assert gain(200.0, 1000.0) > 0.95


def test_the_cutoff_sits_at_minus_three_decibels():
    assert abs(gain(1000.0, 1000.0) - 0.7071) < 0.02


def test_the_stopband_is_strongly_attenuated():
    """Two octaves up should be down more than 20 dB — this is the warmth lever."""
    assert gain(4000.0, 1000.0) < 0.1


def test_resonance_peaks_the_cutoff():
    assert gain(1000.0, 1000.0, resonance=4.0) > gain(1000.0, 1000.0, resonance=0.7071) * 3


def test_the_filter_is_stable_on_a_very_high_cutoff():
    """Nyquist must not produce NaNs when someone hand-edits cutoff_hz upward."""
    out = lowpass(sine(440.0), 40000.0, 0.7071, SAMPLE_RATE)
    assert np.all(np.isfinite(out))


def test_the_filter_handles_stereo():
    stereo = np.stack([sine(200.0), sine(4000.0)], axis=1)
    out = lowpass(stereo, 1000.0, 0.7071, SAMPLE_RATE)
    assert out.shape == stereo.shape
    assert rms(out[:, 0]) > rms(out[:, 1]) * 5


def test_dc_blocker_removes_a_constant_offset():
    signal = 0.5 + 0.1 * sine(200.0)
    out = dc_block(signal)
    assert abs(np.mean(out[SAMPLE_RATE // 2:])) < 1e-4


def test_dc_blocker_keeps_the_audible_signal():
    signal = 0.5 + 0.1 * sine(200.0)
    out = dc_block(signal)
    assert rms(out - np.mean(out)) > 0.06
```

- [x] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_filters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bitty.filters'`

- [x] **Step 4: Write the filters**

`src/bitty/filters.py`:

```python
"""Two IIR filters: the tone control and the safety net.

`lowpass` is the single biggest "make it warmer" control in the synth —
roughly the difference between NES harshness and SID-style warmth. It is off
by default (`Instrument.cutoff_hz is None`), because the spec's fidelity
target is chiptune, not chiptune-with-the-treble-off.
"""

import numpy as np
from scipy.signal import lfilter

DC_BLOCKER_POLE = 0.995
NYQUIST_MARGIN = 0.45  # keep the cutoff below this fraction of the sample rate


def lowpass(
    signal: np.ndarray, cutoff_hz: float, resonance: float, sample_rate: int
) -> np.ndarray:
    """Resonant second-order lowpass (RBJ biquad)."""
    w0 = 2.0 * np.pi * min(cutoff_hz, NYQUIST_MARGIN * sample_rate) / sample_rate
    alpha = np.sin(w0) / (2.0 * resonance)
    cos_w0 = np.cos(w0)

    b = np.array([(1.0 - cos_w0) / 2.0, 1.0 - cos_w0, (1.0 - cos_w0) / 2.0])
    a = np.array([1.0 + alpha, -2.0 * cos_w0, 1.0 - alpha])

    return lfilter(b / a[0], a / a[0], signal, axis=0)


def dc_block(signal: np.ndarray) -> np.ndarray:
    """Strip the constant offset that asymmetric pulse duties leave behind.

    A 12.5% duty pulse spends most of its cycle at -1, so its mean is well
    below zero. Summed across voices that offset eats headroom and, on some
    hardware, thumps the speaker.
    """
    return lfilter([1.0, -1.0], [1.0, -DC_BLOCKER_POLE], signal, axis=0)
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_filters.py -v`
Expected: PASS, 8 tests

- [x] **Step 6: Commit**

```bash
git add pyproject.toml src/bitty/filters.py tests/test_filters.py
git commit -m "feat: add a resonant lowpass and a DC blocker"
```

---

### Task 5: The mixer — per-channel render, stereo, echo, soft clip

**Files:**
- Modify: `src/bitty/synth.py` (full rewrite)
- Test: `tests/test_synth.py` (full rewrite)

**Interfaces:**
- Consumes: `oscillator` (Task 2), `step_values`/`ENV_RATE_HZ` (Task 3),
  `lowpass`/`dc_block` (Task 4), the extended contract (Task 1).
- Produces: `SAMPLE_RATE = 44100` and
  `render(arrangement: Arrangement, sample_rate: int = SAMPLE_RATE) -> np.ndarray`
  returning float32 of shape `(n_samples, 2)`.

**The signature change that matters:** `render` returned mono `(n,)` in Phase 1
and returns stereo `(n, 2)` now. `cli.py` passes it straight to `sf.write`,
which handles both, so nothing else needs touching — but the synth tests do.

- [x] **Step 1: Write the failing tests**

Replace `tests/test_synth.py` entirely:

```python
import numpy as np

from bitty.arrangement import Arrangement, Channel, Echo, Event, Instrument
from bitty.synth import SAMPLE_RATE, render


def one_note(pitch=69, dur=1.0, wave="pulse", vel=15, **instrument_kwargs) -> Arrangement:
    return Arrangement(
        meta={"title": "test", "bpm": 120.0},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(wave=wave, **instrument_kwargs),
                events=(Event(t=0.0, pitch=pitch, dur=dur, vel=vel),),
            ),
        ),
    )


def mono(audio: np.ndarray) -> np.ndarray:
    return audio.sum(axis=1)


def dominant_frequency(audio: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(mono(audio)))
    freqs = np.fft.rfftfreq(len(audio), 1 / SAMPLE_RATE)
    return float(freqs[int(np.argmax(spectrum))])


def test_output_is_stereo_float32():
    audio = render(one_note())
    assert audio.ndim == 2
    assert audio.shape[1] == 2
    assert audio.dtype == np.float32


def test_a_note_sounds_at_its_written_pitch():
    assert abs(dominant_frequency(render(one_note(pitch=69))) - 440.0) < 2.0


def test_render_length_matches_the_arrangement_duration():
    audio = render(one_note(dur=1.0))
    assert abs(len(audio) - SAMPLE_RATE) < SAMPLE_RATE * 0.05


def test_a_volume_envelope_shapes_the_note():
    """A decaying envelope must actually decay — this is what kills the MIDI-dump sound."""
    audio = mono(render(one_note(dur=1.0, volume_env=(15, 12, 9, 6, 3, 0))))
    head = np.sqrt(np.mean(audio[: SAMPLE_RATE // 20] ** 2))
    tail = np.sqrt(np.mean(audio[-SAMPLE_RATE // 20 :] ** 2))
    assert tail < head / 10.0


def test_a_pitch_envelope_bends_the_attack():
    """The percussive 'pew' of a chip lead: start sharp, settle to pitch.

    Do not compare the tails sample-by-sample. A pitch envelope permanently
    shifts accumulated phase, so a bent note and a plain one stay out of phase
    forever even once they agree on frequency. Compare spectra instead.
    """
    plain = mono(render(one_note(pitch=69, dur=0.5)))
    blipped = mono(render(one_note(pitch=69, dur=0.5, pitch_env=(12, 7, 3, 0))))
    assert not np.allclose(plain[:2000], blipped[:2000])

    def peak(audio):
        spectrum = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1 / SAMPLE_RATE)
        return float(freqs[int(np.argmax(spectrum))])

    # The envelope's last step is 0 semitones, so the note settles on pitch.
    assert abs(peak(blipped[SAMPLE_RATE // 4 :]) - 440.0) < 5.0


def test_the_filter_removes_high_harmonics():
    bright = mono(render(one_note(pitch=60, dur=1.0)))
    warm = mono(render(one_note(pitch=60, dur=1.0, cutoff_hz=800.0)))

    def high_energy(audio):
        spectrum = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1 / SAMPLE_RATE)
        return float(np.sum(spectrum[freqs > 3000.0] ** 2))

    assert high_energy(warm) < high_energy(bright) / 10.0


def test_the_filter_is_off_by_default():
    """Default output stays on the spec's chiptune target, not a warmer one."""
    assert np.array_equal(render(one_note()), render(one_note(cutoff_hz=None)))


def test_pan_moves_the_voice_across_the_image():
    left = Arrangement(
        meta={},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(wave="pulse"),
                events=(Event(t=0.0, pitch=69, dur=1.0, vel=15),),
                pan=-1.0,
            ),
        ),
    )
    audio = render(left)
    assert np.max(np.abs(audio[:, 0])) > np.max(np.abs(audio[:, 1])) * 5


def test_echo_adds_a_delayed_copy_after_the_note_ends():
    note = (Event(t=0.0, pitch=69, dur=0.25, vel=15),)
    dry = Arrangement(
        meta={},
        channels=(Channel(role="lead", instrument=Instrument(wave="pulse"), events=note),),
    )
    wet = Arrangement(
        meta={},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(wave="pulse"),
                events=note,
                echo=Echo(delay_sec=0.5, level=0.5),
            ),
        ),
    )
    dry_audio, wet_audio = render(dry), render(wet)

    # The tail lengthens the render by exactly the delay. Do not index the dry
    # render past its end — it is genuinely shorter, and numpy returns an empty
    # slice rather than silence.
    assert abs(len(wet_audio) - len(dry_audio) - 0.5 * SAMPLE_RATE) < 2
    after = slice(int(0.5 * SAMPLE_RATE), int(0.7 * SAMPLE_RATE))
    assert np.max(np.abs(mono(wet_audio)[after])) > 0.05


def test_output_never_clips_even_with_five_voices_at_full_velocity():
    arrangement = Arrangement(
        meta={},
        channels=tuple(
            Channel(
                role=f"v{i}",
                instrument=Instrument(wave="pulse", duty=0.5),
                events=(Event(t=0.0, pitch=60 + i, dur=1.0, vel=15),),
                pan=0.0,
            )
            for i in range(5)
        ),
    )
    assert np.max(np.abs(render(arrangement))) <= 1.0


def test_silent_velocity_produces_silence():
    assert np.max(np.abs(render(one_note(vel=0)))) == 0.0


def test_render_is_deterministic():
    assert np.array_equal(render(one_note()), render(one_note()))


def test_noise_render_is_deterministic_too():
    assert np.array_equal(render(one_note(wave="noise")), render(one_note(wave="noise")))


def test_an_empty_arrangement_renders_silence_not_a_crash():
    audio = render(Arrangement(meta={}, channels=()))
    assert audio.shape[1] == 2
    assert np.max(np.abs(audio), initial=0.0) == 0.0
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_synth.py -v`
Expected: FAIL — `ImportError: cannot import name 'Echo'` from the old module,
or shape assertions failing against the Phase 1 mono renderer.

- [x] **Step 3: Rewrite the synthesizer**

Replace `src/bitty/synth.py` entirely:

```python
"""The mixer: an Arrangement in, a stereo float32 buffer out.

This file owns routing and gain staging only. Waveforms live in `osc`,
envelopes in `envelope`, and filtering in `filters` — each a pure function of
arrays, which is what makes them testable as properties instead of by ear.

Signal path per channel: oscillator -> pitch and volume envelopes -> edge fade
-> lowpass -> constant-power pan -> sum. Then, across the mix: echo taps, DC
blocker, soft clip.
"""

import math

import numpy as np

from bitty.arrangement import MAX_VELOCITY, Arrangement, Channel, Event, Instrument
from bitty.envelope import step_values
from bitty.filters import dc_block, lowpass
from bitty.osc import oscillator

SAMPLE_RATE = 44100
FADE_SECONDS = 0.002
MIX_HEADROOM = 0.9
A4_MIDI = 69
A4_HZ = 440.0


def render(arrangement: Arrangement, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Render an arrangement to stereo float32 in [-1.0, 1.0]."""
    length = _length_of(arrangement, sample_rate)
    mix = np.zeros((length, 2), dtype=np.float64)
    if not arrangement.channels:
        return mix.astype(np.float32)

    # Voices sum incoherently far more often than they line up, so sqrt(n)
    # keeps a five-voice mix as loud as a two-voice one without leaving the
    # soft clipper to do all the work.
    gain = MIX_HEADROOM / math.sqrt(len(arrangement.channels))

    for channel in arrangement.channels:
        voice = _render_channel(channel, length, sample_rate) * gain
        _add_panned(mix, voice, channel.pan, level=1.0, offset=0)
        if channel.echo:
            # The repeat sits on the opposite side of the image. Mono hardware
            # never did this; it is the cheapest width available and the spec
            # buys stereo spread deliberately.
            _add_panned(
                mix,
                voice,
                -channel.pan,
                level=channel.echo.level,
                offset=int(round(channel.echo.delay_sec * sample_rate)),
            )

    return np.tanh(dc_block(mix)).astype(np.float32)


def _length_of(arrangement: Arrangement, sample_rate: int) -> int:
    ends = [
        event.t + event.dur + (channel.echo.delay_sec if channel.echo else 0.0)
        for channel in arrangement.channels
        for event in channel.events
    ]
    return int(round(max(ends, default=0.0) * sample_rate))


def _render_channel(channel: Channel, length: int, sample_rate: int) -> np.ndarray:
    voice = np.zeros(length, dtype=np.float64)
    for event in channel.events:
        _add_event(voice, event, channel.instrument, sample_rate)

    if channel.instrument.cutoff_hz:
        voice = lowpass(
            voice,
            channel.instrument.cutoff_hz,
            channel.instrument.resonance,
            sample_rate,
        )
    return voice


def _add_event(
    voice: np.ndarray, event: Event, instrument: Instrument, sample_rate: int
) -> None:
    length = int(round(event.dur * sample_rate))
    if length <= 0:
        return

    inc = np.full(length, _hz(event.pitch) / sample_rate, dtype=np.float64)
    if instrument.pitch_env:
        semitones = step_values(instrument.pitch_env, length, sample_rate)
        inc = inc * 2.0 ** (semitones / 12.0)

    phase = np.concatenate(([0.0], np.cumsum(inc)[:-1]))
    wave = oscillator(instrument.wave)(phase, inc, instrument)

    amplitude = event.vel / MAX_VELOCITY
    if instrument.volume_env:
        amplitude = amplitude * (
            step_values(instrument.volume_env, length, sample_rate) / MAX_VELOCITY
        )
    wave = wave * amplitude * _edge_fade(length, sample_rate)

    start = int(round(event.t * sample_rate))
    end = min(start + length, len(voice))
    if end > start:
        voice[start:end] += wave[: end - start]


def _add_panned(
    mix: np.ndarray, voice: np.ndarray, pan: float, level: float, offset: int
) -> None:
    if level == 0.0 or offset >= len(mix):
        return

    end = min(offset + len(voice), len(mix))
    segment = voice[: end - offset] * level
    left, right = _pan_gains(pan)
    mix[offset:end, 0] += segment * left
    mix[offset:end, 1] += segment * right


def _pan_gains(pan: float) -> tuple[float, float]:
    """Constant-power pan: a voice keeps its loudness as it crosses the image."""
    angle = (max(-1.0, min(1.0, pan)) + 1.0) * math.pi / 4.0
    return math.cos(angle), math.sin(angle)


def _edge_fade(length: int, sample_rate: int) -> np.ndarray:
    """Two milliseconds in and out, so note boundaries do not click."""
    fade = min(int(FADE_SECONDS * sample_rate), length // 2)
    envelope = np.ones(length, dtype=np.float64)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float64)
        envelope[:fade] = ramp
        envelope[-fade:] = ramp[::-1]
    return envelope


def _hz(midi_pitch: int) -> float:
    return A4_HZ * 2.0 ** ((midi_pitch - A4_MIDI) / 12.0)
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_synth.py -v`
Expected: PASS, 14 tests

- [x] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: all pass. `test_cli.py` uses `len(audio)`, which still reads the
frame count on a stereo array.

- [x] **Step 6: Commit**

```bash
git add src/bitty/synth.py tests/test_synth.py
git commit -m "feat: rewrite the synth with envelopes, filtering, stereo, and echo"
```

---

### Task 6: Chiptune presets in the arranger

**Files:**
- Modify: `src/bitty/arrange.py`
- Test: `tests/test_arrange.py`

**Interfaces:**
- Consumes: the extended contract (Task 1).
- Produces: `arrange(score: Score) -> Arrangement` unchanged in signature, but
  its two channels now carry envelopes, pan, and — on the lead — echo.

**Scope discipline:** this is *not* the Phase 3 arranger. The voice-splitting
logic is untouched. The only change is that the two channels it already emits
now describe a chiptune instrument instead of a bare waveform, because a
synthesizer nobody feeds envelopes to is a synthesizer nobody can hear.

Echo delay comes from the spec's `[echo] delay = "3/16"` — three sixteenths of
a whole note, which is 0.75 of a beat.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_arrange.py`:

```python
def test_the_lead_gets_a_chip_voice_not_a_bare_square():
    arrangement = arrange(ingest(FIXTURE))
    lead = arrangement.channels[0]
    assert lead.instrument.volume_env != ()
    assert lead.instrument.pitch_env != ()


def test_the_filter_stays_off_by_default():
    """Warmth is a lever, not the default. The spec's target is chiptune."""
    arrangement = arrange(ingest(FIXTURE))
    assert all(c.instrument.cutoff_hz is None for c in arrangement.channels)


def test_the_voices_are_spread_across_the_stereo_image():
    arrangement = arrange(ingest(FIXTURE))
    pans = [c.pan for c in arrangement.channels]
    assert pans[0] != pans[1]
    assert all(abs(p) <= 0.5 for p in pans)


def test_the_lead_echoes_and_the_bass_does_not():
    """A delayed bass turns into mud; the tail belongs on the tune."""
    arrangement = arrange(ingest(FIXTURE))
    lead, bass = arrangement.channels
    assert lead.echo is not None
    assert bass.echo is None


def test_echo_delay_tracks_the_tempo():
    """Three sixteenths of a whole note is 0.75 beats — 0.375s at 120 bpm."""
    arrangement = arrange(ingest(FIXTURE))
    assert abs(arrangement.channels[0].echo.delay_sec - 0.375) < 1e-9
```

`FIXTURE` and `ingest` are already imported at the top of that file; check
before adding duplicates. Add `arrange` if it is not imported.

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_arrange.py -v`
Expected: FAIL — `assert () != ()`

- [x] **Step 3: Give the channels a voice**

In `src/bitty/arrange.py`, replace the `LEAD`/`BASS` constants and the
`arrange` function:

```python
from bitty.arrangement import (
    MAX_VELOCITY,
    Arrangement,
    Channel,
    Echo,
    Event,
    Instrument,
)

# A short decay plus an upward pitch blip on the attack: the two things that
# separate a chip lead from a sine tone. Levels are 0-15, one per 60th second.
LEAD = Instrument(
    wave="pulse",
    duty=0.5,
    volume_env=(15, 15, 14, 13, 12, 12, 11),
    pitch_env=(2, 1, 0),
)
BASS = Instrument(
    wave="triangle",
    volume_env=(15, 14, 13, 12),
    quantize=16,  # the NES triangle's 16 amplitude steps, and its bite
)

LEAD_PAN = -0.25
BASS_PAN = 0.25
ECHO_BEATS = 0.75  # the spec's [echo] delay = "3/16" of a whole note
ECHO_LEVEL = 0.35


def arrange(score: Score) -> Arrangement:
    lead_notes, bass_notes = _split_voices(score.notes)
    return Arrangement(
        meta={"title": score.title, "bpm": score.bpm},
        channels=(
            Channel(
                role="lead",
                instrument=LEAD,
                events=_to_events(lead_notes),
                pan=LEAD_PAN,
                echo=Echo(delay_sec=_echo_delay(score.bpm), level=ECHO_LEVEL),
            ),
            Channel(
                role="bass",
                instrument=BASS,
                events=_to_events(bass_notes),
                pan=BASS_PAN,
            ),
        ),
    )


def _echo_delay(bpm: float) -> float:
    return ECHO_BEATS * 60.0 / bpm
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_arrange.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/bitty/arrange.py tests/test_arrange.py
git commit -m "feat: give the arranger's two channels real chip voices"
```

---

### Task 7: Ogg output, and the acceptance listen

**Files:**
- Modify: `src/bitty/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `render` (Task 5), `arrange` (Task 6).
- Produces: `bitty convert SCORE -o DIR [--wav]`, writing `<stem>.ogg` by
  default and `<stem>.wav` when `--wav` is passed. The arrangement JSON is
  written either way.

Ogg Vorbis comes from libsndfile through soundfile — no ffmpeg subprocess.
Verified available in this environment: libsndfile 1.2.2 lists `OGG` with a
`VORBIS` subtype.

Vorbis is lossy, so **determinism is asserted on the float array, never on the
encoded file.**

- [x] **Step 1: Write the failing tests**

In `tests/test_cli.py`, replace `test_convert_writes_audio_and_arrangement` and
`test_converted_audio_has_the_expected_duration`, and add the rest:

```python
def test_convert_writes_ogg_and_arrangement(tmp_path):
    result = runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "two_part.ogg").exists()
    assert (tmp_path / "two_part.arrangement.json").exists()


def test_converted_audio_is_stereo_at_the_expected_duration(tmp_path):
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    audio, sample_rate = sf.read(tmp_path / "two_part.ogg")
    assert sample_rate == 44100
    assert audio.ndim == 2 and audio.shape[1] == 2
    assert abs(len(audio) / sample_rate - 2.375) < 0.1


def test_wav_flag_writes_uncompressed_instead(tmp_path):
    result = runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path), "--wav"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "two_part.wav").exists()
    assert not (tmp_path / "two_part.ogg").exists()


def test_the_written_ogg_is_audible(tmp_path):
    """Guards the whole chain: a silent file passes every shape assertion."""
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    audio, _ = sf.read(tmp_path / "two_part.ogg")
    assert 0.01 < float(np.max(np.abs(audio))) <= 1.0
```

Add `import numpy as np` at the top of the file. The 2.375s duration is the
fixture's 2.0s of music plus the 0.375s echo tail at 120 bpm.

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — no `two_part.ogg`; the CLI still writes WAV.

- [x] **Step 3: Switch the CLI to Ogg**

In `src/bitty/cli.py`, replace the body of `convert`:

```python
@app.command()
def convert(
    score: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(Path("out"), "-o", "--out-dir"),
    wav: bool = typer.Option(False, "--wav", help="Write uncompressed WAV instead of Ogg."),
) -> None:
    """Convert a score to audio and its arrangement JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)

    arrangement = arrange(ingest(score))
    audio = render(arrangement)

    audio_path = out_dir / f"{score.stem}{'.wav' if wav else '.ogg'}"
    json_path = out_dir / f"{score.stem}.arrangement.json"

    if wav:
        sf.write(audio_path, audio, SAMPLE_RATE)
    else:
        sf.write(audio_path, audio, SAMPLE_RATE, format="OGG", subtype="VORBIS")
    json_path.write_text(arrangement.to_json())

    typer.echo(f"{audio_path}  ({len(audio) / SAMPLE_RATE:.1f}s)")
    typer.echo(f"{json_path}")
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS

- [x] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: all pass — roughly 60 tests.

- [ ] **Step 6: Acceptance — render the Phase 1 piece again and listen**

Render the same Bach chorale Phase 1 was accepted on, so the comparison is
like for like:

```bash
.venv/bin/python -c "
from music21 import corpus
corpus.parse('bach/bwv66.6').write('musicxml', fp='/tmp/bwv66_6.musicxml')
"
.venv/bin/bitty convert /tmp/bwv66_6.musicxml -o out/
```

Play `out/bwv66_6.ogg` against Phase 1's `out/bwv66_6.wav`. The bar to clear:

- Notes **decay** instead of sitting flat — the volume envelope is audible.
- The lead has a percussive attack, not a pure tone onset.
- High melody notes are **clean**, not fizzy. That is PolyBLEP working.
- The image is **wide** — lead and bass are separable, and the lead's echo
  answers on the opposite side.
- No clicks at note boundaries, no clipping, no DC thump at the start.

It should now sound like chiptune. If it sounds thin or wrong, read
`out/bwv66_6.arrangement.json` before touching code — Phase 1's two-voice
reduction is still what feeds this, and Phase 3 is what fixes reduction.

**Then the warmth check, which is the question Phase 2 exists to answer:**

```bash
.venv/bin/python -c "
import soundfile as sf
from bitty.arrangement import Arrangement
from bitty.synth import SAMPLE_RATE, render
from dataclasses import replace

a = Arrangement.from_json(open('out/bwv66_6.arrangement.json').read())
warm = replace(a, channels=tuple(
    replace(c, instrument=replace(c.instrument, cutoff_hz=2000.0, resonance=1.2))
    for c in a.channels))
sf.write('out/bwv66_6_warm.ogg', render(warm), SAMPLE_RATE, format='OGG', subtype='VORBIS')
print('out/bwv66_6_warm.ogg')
"
```

Compare `bwv66_6.ogg` against `bwv66_6_warm.ogg`. This is the "can it be less
8-bit" question made audible. Whichever you prefer decides whether Phase 5's
config ships a filtered preset — it does not need deciding now.

- [x] **Step 7: Commit**

```bash
git add src/bitty/cli.py tests/test_cli.py
git commit -m "feat: write Ogg Vorbis by default, with a --wav escape hatch"
```

---

## Phase 2 exit criteria

- `.venv/bin/pytest` passes.
- `bitty convert` writes a stereo Ogg that sounds like chiptune, not like a
  buzzer: envelopes audible, attacks percussive, high notes clean, image wide.
- Aliasing, clipping, determinism, and filter response are each covered by a
  property test rather than by a golden audio blob.
- `arrangement.json` carries envelopes, pan, and echo, and a Phase 1
  arrangement still loads without them.
- The warmth question has been heard both ways.

Phase 3 replaces `arrange.py` — voice-leading assignment, arpeggio overflow,
and articulation rules — against the contract this phase extended. It adds
channels and events; it does not change what `synth.py` does with them.
