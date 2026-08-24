# Phase 9: transform — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `[transform]` config table — `transpose` and `tempo_scale` — as a pure stage between `ingest` and everything downstream, so a piece can be re-keyed and re-arranged at a new tempo without any other stage knowing a transform happened.

**Architecture:** One new module, `src/bitty/transform.py`, with one pure function `apply(score, settings) -> Score`. It runs immediately after `ingest` at exactly two call sites (`cli.sections` and `cli.convert`) and nowhere else — `render` deliberately does not transform, so convert-then-render cannot double-apply. `tempo_scale` is an *arranger input*, not a playback trick: it scales `bpm` up and every note and bar time down together, so duration-sensitive decisions (vibrato's 500 ms threshold, echo's beat-derived delay, bar boundaries, loop seams) re-derive at the new tempo. `transpose` is a uniform integer semitone shift whose load-bearing property is an invariant: `arrange(transform(score, n))` equals `arrange(score)` with every pitch shifted by `n`.

**Tech Stack:** Python 3.11+, frozen dataclasses, `tomllib`, Typer, pytest, numpy/soundfile in tests only.

**Spec:** `docs/superpowers/specs/2026-08-23-phase-9-transform-design.md` — read it before Task 1. Every design decision below is argued there.

## Global Constraints

- **Branch:** work on `phase-9-transform`, cut from `main`. The repo convention is `git merge --no-ff` per completed phase (`Merge Phase 8: reduction policy`). Do not merge until the audition (Task 8) has been accepted by ear.
- **Test runner:** `.venv/bin/pytest`. Never `pytest` bare.
- **Every test must be proven against a deliberate regression.** Each task below names the exact edit to make, the test that must then fail, and the restore. A test that passes both before and after the named break is a broken test, not a passing implementation — fix the test before moving on. This rule exists because a review once found a test that had cleared this gate at face value while not actually failing under the regression it claimed to guard.
- **Goldens must not churn.** `transpose = 0, tempo_scale = 1.0` is the identity and `tests/goldens/*.arrangement.json` stay exactly as they are. If a task makes `tests/test_goldens.py` fail, the implementation is wrong — do not regenerate.
- **Absolute values stay absolute.** `arp.step_sec` (48 ms), `vibrato.rate_hz`, `vibrato.delay_sec`, and `vibrato.min_note_sec` are seconds in config and must never be scaled by `tempo_scale`. Phase 7's audition established 48 ms as a fact about the ear, not about the music.
- **Bounds, exact values:** config-time `transpose` is `_whole(low=-48, high=48)`; `tempo_scale` is `_ranged(low=0.25, high=4.0)`. Score-time playable band is `MIN_PITCH = 24` (C1) and `MAX_PITCH = 108` (C8), module constants in `transform.py`, not config keys.
- **No CLI flags for either knob.** Config only. `--config` is how an audition sweeps.
- **No automatic range fitting.** An out-of-range transpose refuses; it never folds notes back into the band.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/bitty/transform.py` (create) | `apply()`, the playable-band constants, the refusal message. Imports only `bitty.config.Transform` and `bitty.model` — no music21, no I/O. |
| `src/bitty/config.py` (modify) | `Transform` dataclass, `Config.transform` field, the `[transform]` row in `_TABLES`. Config-time validation only: well-formed and sanely bounded. |
| `src/bitty/cli.py` (modify) | Two call sites (`sections`, `convert`), plus the `ValueError` → `typer.BadParameter` wrap that adds config provenance. `render` untouched. |
| `tests/test_transform.py` (create) | The pure-function tests, the transpose invariant, the re-arrangement tests, the refusal. |
| `tests/test_config.py` (modify) | The `[transform]` config surface and its bounds. |
| `tests/test_cli.py` (modify) | Wiring, the transposed-key report, and the render-does-not-transform contract. |
| `README.md` (modify) | `[transform]` in the complete example, its own subsection, and the Status paragraph. |
| `audition/transform/` (create) | WAV clips, `NOTES.md`, the sweep configs. |

---

### Task 1: The `[transform]` config surface

Config-time validation only — is the value well-formed and sanely bounded *at all*. Whether a particular transpose fits a particular score is Task 4's job and cannot happen here, because config has never seen a note.

**Files:**
- Modify: `src/bitty/config.py` (add `Transform` dataclass near `LoopSettings`; add field to `Config`; add row to `_TABLES`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `bitty.config.Transform(transpose: int = 0, tempo_scale: float = 1.0)`, frozen; `Config.transform: Transform`. Task 2 imports `Transform`; Task 5 reads `settings.transform`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`, next to the other table tests (after `test_a_whole_number_field_refuses_a_fraction` is a good home):

```python
def test_the_transform_table_reaches_the_config():
    result = merge(DEFAULTS, "[transform]\ntranspose = -12\ntempo_scale = 0.75\n", "test")
    assert result.transform.transpose == -12
    assert result.transform.tempo_scale == 0.75


def test_the_transform_defaults_are_the_identity():
    """Everything downstream assumes an untouched score unless a file says otherwise."""
    assert DEFAULTS.transform.transpose == 0
    assert DEFAULTS.transform.tempo_scale == 1.0


def test_a_transpose_past_four_octaves_is_refused():
    with pytest.raises(ConfigError) as error:
        merge(DEFAULTS, "[transform]\ntranspose = 49\n", "test")
    assert "transform.transpose" in str(error.value)
    assert "at most 48" in str(error.value)


def test_a_fractional_transpose_is_refused():
    """Semitones only: the pitch pipeline is integer MIDI throughout."""
    with pytest.raises(ConfigError) as error:
        merge(DEFAULTS, "[transform]\ntranspose = 1.5\n", "test")
    assert "whole number" in str(error.value)


def test_a_tempo_scale_of_zero_is_refused():
    """Zero is not a slow tempo; it is a division by zero two stages later."""
    with pytest.raises(ConfigError) as error:
        merge(DEFAULTS, "[transform]\ntempo_scale = 0.0\n", "test")
    assert "transform.tempo_scale" in str(error.value)
    assert "at least 0.25" in str(error.value)


def test_a_tempo_scale_past_quadruple_is_refused():
    with pytest.raises(ConfigError) as error:
        merge(DEFAULTS, "[transform]\ntempo_scale = 4.5\n", "test")
    assert "at most 4.0" in str(error.value)


def test_an_unknown_transform_key_lists_the_two_that_exist():
    with pytest.raises(ConfigError) as error:
        merge(DEFAULTS, "[transform]\ntranspose_cents = 50\n", "test")
    assert "transform.transpose_cents" in str(error.value)
    assert "tempo_scale" in str(error.value) and "transpose" in str(error.value)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -k transform -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'transform'` on the first two, and `ConfigError: test: transform: unknown table` on the rest.

- [ ] **Step 3: Implement**

In `src/bitty/config.py`, after the `LoopSettings` dataclass:

```python
@dataclass(frozen=True)
class Transform:
    """What the music *is*, changed before any chiptune decision is made.

    `tempo_scale` is an arranger input rather than a playback speed: it is
    applied to the score, so every duration-sensitive decision downstream —
    which notes are long enough to waver, where the bars fall, how long the
    echo's beat is — re-derives at the new tempo. See `transform.py`.
    """

    transpose: int = 0  # semitones
    tempo_scale: float = 1.0
```

Add the field to `Config` (after `loop`, before `voices`):

```python
    transform: Transform = Transform()
```

Add the row to `_TABLES`, after `"loop"`:

```python
    "transform": {
        "transpose": ("transpose", _whole(low=-48, high=48)),
        "tempo_scale": ("tempo_scale", _ranged(low=0.25, high=4.0)),
    },
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS, all of them — including the pre-existing ones, since `Transform()` is inert until Task 5 wires it.

- [ ] **Step 5: Prove the bounds tests**

Break: change the row to `"transpose": ("transpose", _whole())` and `"tempo_scale": ("tempo_scale", _ranged())`.
Run: `.venv/bin/pytest tests/test_config.py -k transform -v`
Expected: FAIL on `test_a_transpose_past_four_octaves_is_refused`, `test_a_tempo_scale_of_zero_is_refused`, and `test_a_tempo_scale_past_quadruple_is_refused` — a test that still passes here is not guarding its bound.
Restore the validators and re-run: PASS.

- [ ] **Step 6: Verify nothing else moved**

Run: `.venv/bin/pytest`
Expected: PASS, goldens included. A new frozen field with a default changes no existing behaviour.

- [ ] **Step 7: Commit**

```bash
git add src/bitty/config.py tests/test_config.py
git commit -m "feat: add the [transform] config table"
```

---

### Task 2: `transform.apply` — identity and transpose

The module and its cheapest half. Identity is what keeps the goldens valid; transpose is a uniform shift over pitches and nothing else.

**Files:**
- Create: `src/bitty/transform.py`
- Test: `tests/test_transform.py` (create)

**Interfaces:**
- Consumes: `bitty.config.Transform` (Task 1).
- Produces: `bitty.transform.apply(score: Score, settings: Transform) -> Score`, pure; `MIN_PITCH = 24`, `MAX_PITCH = 108` module constants. Tasks 3 and 4 extend the same function; Task 5 calls it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_transform.py`:

```python
from dataclasses import replace
from pathlib import Path

import pytest

from bitty.arrange import arrange
from bitty.config import Transform
from bitty.ingest import ingest
from bitty.model import Bar, Note, Score
from bitty.transform import apply

FIXTURES = Path(__file__).parent / "fixtures"
NAMES = ["chorale", "minuet", "ragtime"]


def a_score(*notes, bpm=120.0, bars=()):
    """A Score with no file behind it: `apply` is pure, so tests can be too."""
    return Score(
        notes=tuple(notes),
        bpm=bpm,
        time_signature=(4, 4),
        title="probe",
        bars=tuple(bars),
    )


def a_note(pitch=60, start=0.0, dur=1.0, velocity=80):
    return Note(pitch=pitch, start=start, dur=dur, velocity=velocity, part=0)


def test_the_defaults_return_the_very_same_score():
    """Identity, not an arithmetic round trip that happens to land back home.

    `is` rather than `==`: the goldens are valid because the default path does
    nothing at all, and a rebuild that currently compares equal is one float
    away from not.
    """
    score = a_score(a_note(), a_note(pitch=64, start=1.0))
    assert apply(score, Transform()) is score


def test_transpose_shifts_every_pitch():
    score = a_score(a_note(pitch=60), a_note(pitch=64, start=1.0))
    result = apply(score, Transform(transpose=7))
    assert [n.pitch for n in result.notes] == [67, 71]


def test_transpose_moves_nothing_but_pitch():
    """Everything that is not a pitch survives the shift untouched."""
    bar = Bar(number=1, start=0.0, dur=2.0, time_signature=(4, 4), sharps=1)
    score = a_score(a_note(pitch=60, start=0.5, dur=0.25, velocity=99), bars=[bar])
    result = apply(score, Transform(transpose=-5))
    assert result.bpm == score.bpm
    assert result.bars == score.bars
    assert result.title == score.title and result.time_signature == score.time_signature
    before, after = score.notes[0], result.notes[0]
    assert after == replace(before, pitch=before.pitch - 5)


@pytest.mark.parametrize("name", NAMES)
def test_the_whole_arrangement_shifts_with_the_transpose(name):
    """The load-bearing transpose test, and the reason transpose is cheap.

    The arranger has no absolute pitch logic anywhere — top and bottom pinning,
    nearest-last-pitch assignment, the reduction's pitch-class comparison, and
    the arpeggio's octave folding are all relative or uniformly shifted — so
    arranging a transposed score must give back exactly the untransposed
    arrangement with every pitch moved by n.

    Asserted event by whole event rather than over a pitch list: an
    implementation that shifts pitches correctly while dropping arp offsets or
    losing a vibrato flag would pass the coarser check.
    """
    score = ingest(FIXTURES / f"{name}.mxl")
    plain = arrange(score)
    shifted = arrange(apply(score, Transform(transpose=5)))

    assert shifted.meta == plain.meta
    assert len(shifted.channels) == len(plain.channels)
    for was, now in zip(plain.channels, shifted.channels):
        assert now.role == was.role
        assert now.pan == was.pan
        assert now.echo == was.echo
        assert now.instrument == was.instrument
        assert len(now.events) == len(was.events)
        for before, after in zip(was.events, now.events):
            assert after == replace(before, pitch=before.pitch + 5)


def test_the_invariant_fixtures_actually_contain_an_arpeggio():
    """Keeps the test above from guarding arp offsets vacuously.

    Phase 8's reduction left the minuet and the chorale with no arpeggio at
    all at the count-5 default; ragtime is the only fixture whose overflow
    still cycles, so it is the only one carrying the arp half of the
    invariant. If this ever reaches zero, the invariant has quietly stopped
    covering `Event.arp` and needs a fixture that does.
    """
    arranged = arrange(ingest(FIXTURES / "ragtime.mxl"))
    assert sum(1 for c in arranged.channels for e in c.events if e.arp) >= 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_transform.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bitty.transform'`.

- [ ] **Step 3: Implement**

Create `src/bitty/transform.py`:

```python
"""Change what the music *is*, before any chiptune decision is made.

Separate from `ingest` because the jobs differ. Ingest resolves what the
notation *means*: dynamics into velocities, a trill into the fast notes it
stands for, a grace note moved to sound before what it decorates. This module
changes the music itself, and the split is what makes it testable on a
hand-built `Score` — no score file, no music21, no I/O.

`apply` runs at exactly two call sites, both immediately after `ingest`, so
`analyze`, `arrange`, `loop`, `synth`, and the emitters see only the
transformed score and need no knowledge that a transform happened. `render`
deliberately does not call it: everything musical was decided when the
arrangement JSON was written, and transforming again would land a `+3` convert
at `+6` on re-render.
"""

from __future__ import annotations

from dataclasses import replace

from bitty.config import Transform
from bitty.model import Score

# The playable band, and the binding limit is audibility rather than Nyquist:
# a fundamental past 0.45 * 44100 is around MIDI 135, which no real score
# reaches, and PolyBLEP bandlimits the harmonics above it anyway. C1 is where
# the quantized triangle bass stops reading as pitch on a small speaker; C8 is
# where the top stops being a note and starts being a whistle. Both are
# calibration set by audition, which is why they live here rather than in the
# TOML — the same rule that keeps `ARP_RATE_SEC` out of config.
MIN_PITCH = 24  # C1, 32.7 Hz
MAX_PITCH = 108  # C8, 4186 Hz

_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def apply(score: Score, settings: Transform) -> Score:
    """A transposed, re-tempo'd score. Under the defaults, the same object."""
    if settings.transpose == 0 and settings.tempo_scale == 1.0:
        return score

    shift = settings.transpose
    return replace(
        score,
        notes=tuple(replace(note, pitch=note.pitch + shift) for note in score.notes),
    )


def _name(pitch: int) -> str:
    """MIDI number to the name a person would say, e.g. 108 -> C8."""
    return f"{_NAMES[pitch % 12]}{pitch // 12 - 1}"
```

`_name` is unused until Task 4; write it now so the constants and their helper
land together with the docstring that explains them.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_transform.py -v`
Expected: PASS.

- [ ] **Step 5: Prove the invariant test**

Break: in `src/bitty/arrange.py`, in `_events`, give the arranger an absolute pitch threshold —

```python
            vibrato=not take.arp and take.dur >= min_note_sec and take.pitch < 84,
```

Run: `.venv/bin/pytest tests/test_transform.py -k whole_arrangement -v`
Expected: FAIL on `minuet` (its top notes cross 84 under a +5 shift) with a mismatched `vibrato` flag. If it passes, the invariant is not comparing whole events — fix the test.
Restore `_events` and re-run: PASS.

- [ ] **Step 6: Prove the identity test**

Break: in `transform.apply`, delete the short-circuit so it always rebuilds.
Run: `.venv/bin/pytest tests/test_transform.py -k defaults_return -v`
Expected: FAIL — `assert <Score object> is <Score object>`.
Restore and re-run: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS. Nothing calls `apply` yet, so the goldens cannot have moved.

- [ ] **Step 8: Commit**

```bash
git add src/bitty/transform.py tests/test_transform.py
git commit -m "feat: add transform.apply with identity and transpose"
```

---

### Task 3: `tempo_scale` re-derives the arrangement

Two operations, not one. Note times are already in seconds by the time transform runs (`ingest` bakes in `seconds_per_quarter`), so scaling `bpm` alone would relabel the tempo while every note kept its old timing — the wrong implementation that passes any test looking only at tempo metadata. Bars scale too, or `analyze`'s section boundaries and every loop candidate drift away from the notes they describe.

**Files:**
- Modify: `src/bitty/transform.py`
- Test: `tests/test_transform.py`

**Interfaces:**
- Consumes: `apply` from Task 2.
- Produces: no new names. `apply` now scales `Score.bpm`, `Note.start`, `Note.dur`, `Bar.start`, `Bar.dur`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transform.py`:

```python
def test_tempo_scale_moves_the_tempo_and_the_notes_together():
    """Faster tempo, shorter times. Scaling bpm alone would relabel and lie."""
    score = a_score(a_note(start=2.0, dur=1.0), bpm=120.0)
    result = apply(score, Transform(tempo_scale=1.5))
    assert result.bpm == 180.0
    assert result.notes[0].start == pytest.approx(2.0 / 1.5)
    assert result.notes[0].dur == pytest.approx(1.0 / 1.5)


def test_tempo_scale_moves_the_bars_with_the_notes():
    """`analyze` reads bars and notes against each other; they cannot drift."""
    bar = Bar(number=1, start=4.0, dur=2.0, time_signature=(3, 4), sharps=1)
    score = a_score(a_note(start=4.0), bars=[bar])
    result = apply(score, Transform(tempo_scale=2.0))
    assert result.bars[0].start == pytest.approx(2.0)
    assert result.bars[0].dur == pytest.approx(1.0)
    assert result.bars[0].number == 1, "a printed bar number is not a time"
    assert result.bars[0].sharps == 1


def test_tempo_scale_leaves_pitch_and_velocity_alone():
    score = a_score(a_note(pitch=71, velocity=99))
    result = apply(score, Transform(tempo_scale=0.5))
    assert result.notes[0].pitch == 71 and result.notes[0].velocity == 99


def test_a_faster_tempo_costs_a_long_note_its_vibrato():
    """The phase's most visible behaviour, and the test that matters most.

    A 520 ms note clears `vibrato.min_note_sec` (500 ms) and wavers. At
    tempo_scale = 1.5 it lasts 347 ms and does not, because the threshold is a
    fact about the ear and stays where it is while the music moves past it.
    That is a re-arrangement, which is the point of taking tempo_scale as an
    arranger input rather than as a playback speed.

    The bpm-only implementation passes every other test here and fails this
    one: its note is still 520 ms long, so it still wavers.
    """
    score = a_score(a_note(dur=0.52))
    assert arrange(score).channels[0].events[0].vibrato is True

    faster = arrange(apply(score, Transform(tempo_scale=1.5)))
    assert faster.channels[0].events[0].dur == pytest.approx(0.52 / 1.5)
    assert faster.channels[0].events[0].vibrato is False


def test_a_slower_tempo_earns_a_short_note_its_vibrato():
    """The same threshold from the other side, so the test cannot pass by
    an implementation that simply drops vibrato whenever a transform ran."""
    score = a_score(a_note(dur=0.4))
    assert arrange(score).channels[0].events[0].vibrato is False

    slower = arrange(apply(score, Transform(tempo_scale=0.5)))
    assert slower.channels[0].events[0].vibrato is True


def test_the_echo_follows_the_tempo_but_the_ear_s_own_constants_do_not():
    """The split between what follows the music and what is absolute.

    The left column of the design's table is derived from bpm and moves; the
    right column is seconds in config, derived from nothing, and must not.
    Scaling `arp_rate_sec` with tempo would undo Phase 7's finding that 48 ms
    is a property of the ear rather than of the music.
    """
    score = ingest(FIXTURES / "ragtime.mxl")
    plain = arrange(score)
    faster = arrange(apply(score, Transform(tempo_scale=2.0)))

    was_echo = next(c.echo for c in plain.channels if c.echo)
    now_echo = next(c.echo for c in faster.channels if c.echo)
    assert now_echo.delay_sec == pytest.approx(was_echo.delay_sec / 2.0)
    assert now_echo.level == was_echo.level

    for was, now in zip(plain.channels, faster.channels):
        assert now.instrument.arp_rate_sec == was.instrument.arp_rate_sec
        assert now.instrument.vibrato_rate_hz == was.instrument.vibrato_rate_hz
        assert now.instrument.vibrato_delay == was.instrument.vibrato_delay
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_transform.py -v`
Expected: FAIL — the new tests only; `result.bpm == 180.0` fails first (`apply` still returns `bpm` untouched).

- [ ] **Step 3: Implement**

Replace the body of `apply` in `src/bitty/transform.py`:

```python
def apply(score: Score, settings: Transform) -> Score:
    """A transposed, re-tempo'd score. Under the defaults, the same object."""
    if settings.transpose == 0 and settings.tempo_scale == 1.0:
        return score

    shift = settings.transpose
    scale = settings.tempo_scale
    return replace(
        score,
        bpm=score.bpm * scale,
        notes=tuple(
            replace(
                note,
                pitch=note.pitch + shift,
                start=note.start / scale,
                dur=note.dur / scale,
            )
            for note in score.notes
        ),
        # Bars carry times too, and `analyze` reads them against the notes.
        # Scaling one and not the other is a score whose barlines have slid.
        bars=tuple(
            replace(bar, start=bar.start / scale, dur=bar.dur / scale)
            for bar in score.bars
        ),
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_transform.py -v`
Expected: PASS.

- [ ] **Step 5: Prove the re-arrangement test against the bpm-only implementation**

Break: drop the two `/ scale` divisions inside the `notes` comprehension, keeping `bpm=score.bpm * scale`.
Run: `.venv/bin/pytest tests/test_transform.py -v`
Expected: FAIL on `test_a_faster_tempo_costs_a_long_note_its_vibrato`, `test_a_slower_tempo_earns_a_short_note_its_vibrato`, and `test_tempo_scale_moves_the_tempo_and_the_notes_together`. If the vibrato tests pass here, they are inspecting tempo metadata rather than the arrangement — fix them.
Restore and re-run: PASS.

- [ ] **Step 6: Prove the bars test**

Break: drop the `bars=` argument entirely, so bars keep their old times.
Run: `.venv/bin/pytest tests/test_transform.py -k bars -v`
Expected: FAIL on `test_tempo_scale_moves_the_bars_with_the_notes`.
Restore and re-run: PASS.

- [ ] **Step 7: Prove the absolutes test**

Break: in `src/bitty/arrange.py`, in `arrange`, divide the carrier rate by the tempo ratio the score now carries —

```python
    carrier = next(voice for voice in roster if voice.role == roster.arp)
    tracks[roster.arp] = _arpeggiate(
        leftovers, tracks, roster, carrier.instrument.arp_rate_sec * 100.0 / score.bpm
    )
```

and, in the same function, add `instrument=replace(voice.instrument, arp_rate_sec=voice.instrument.arp_rate_sec * 100.0 / score.bpm)` to the `Channel(...)` construction.
Run: `.venv/bin/pytest tests/test_transform.py -k ear_s_own -v`
Expected: FAIL on `arp_rate_sec`.
Restore both edits and re-run: PASS.

- [ ] **Step 8: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS, goldens unchanged — `apply` still has no caller.

- [ ] **Step 9: Commit**

```bash
git add src/bitty/transform.py tests/test_transform.py
git commit -m "feat: make tempo_scale re-derive the arrangement"
```

---

### Task 4: Refusing a transpose that does not fit

Score-time validation. It needs the pitch range, so it can only happen after ingest, and it raises `ValueError` — the established pattern for a stage module that cannot name the flag that caused it (`loop_stage.trim` for `--bars`, `loop_stage.candidates` for `--loop-from`). The refusal names the arithmetic instead of complaining.

**Files:**
- Modify: `src/bitty/transform.py`
- Test: `tests/test_transform.py`

**Interfaces:**
- Consumes: `apply`, `MIN_PITCH`, `MAX_PITCH`, `_name` from Task 2.
- Produces: `apply` raises `ValueError` when the shift pushes any note outside `[MIN_PITCH, MAX_PITCH]`. Task 5 catches exactly this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transform.py`:

```python
def test_a_transpose_past_the_ceiling_names_the_arithmetic():
    """A refusal that says which note, where it lands, and what would fit.

    'out of range' would leave the reader to find the offending note and do
    the subtraction themselves, on a knob whose whole purpose is being swept.
    """
    score = a_score(a_note(pitch=60), a_note(pitch=108, start=1.0))
    with pytest.raises(ValueError) as error:
        apply(score, Transform(transpose=7))
    message = str(error.value)
    assert "transform.transpose = +7" in message
    assert "C8 (MIDI 108)" in message
    assert "MIDI 115" in message
    assert "ceiling of 108" in message
    assert "at most +0" in message


def test_a_transpose_under_the_floor_names_the_arithmetic():
    score = a_score(a_note(pitch=36), a_note(pitch=30, start=1.0))
    with pytest.raises(ValueError) as error:
        apply(score, Transform(transpose=-12))
    message = str(error.value)
    assert "transform.transpose = -12" in message
    assert "F#1 (MIDI 30)" in message
    assert "MIDI 18" in message
    assert "floor of 24" in message
    assert "at least -6" in message


def test_the_largest_transpose_that_fits_is_accepted():
    """The bound is the edge of the band, not one short of it."""
    score = a_score(a_note(pitch=101))
    assert apply(score, Transform(transpose=7)).notes[0].pitch == MAX_PITCH


def test_the_range_is_judged_after_the_shift_not_before():
    """A score already sitting on the ceiling may still be transposed down."""
    score = a_score(a_note(pitch=108))
    assert apply(score, Transform(transpose=-12)).notes[0].pitch == 96


def test_a_score_with_no_notes_refuses_nothing():
    assert apply(a_score(), Transform(transpose=48)).notes == ()
```

Add `MAX_PITCH` to the import at the top of the file:

```python
from bitty.transform import MAX_PITCH, apply
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_transform.py -k transpose_past or transpose_under -v`
Expected: FAIL — `DID NOT RAISE ValueError`.

- [ ] **Step 3: Implement**

In `src/bitty/transform.py`, call the check from `apply` before building anything, and add the function below it:

```python
def apply(score: Score, settings: Transform) -> Score:
    """A transposed, re-tempo'd score. Under the defaults, the same object."""
    if settings.transpose == 0 and settings.tempo_scale == 1.0:
        return score

    shift = settings.transpose
    _check_fits(score, shift)
    scale = settings.tempo_scale
    ...  # unchanged from Task 3
```

```python
def _check_fits(score: Score, shift: int) -> None:
    """Refuse a shift this score cannot take, naming the note that decides it.

    Refusing rather than folding the offender back into the band: an octave
    leap dropped into the middle of a phrase is exactly the note soup that
    voice-leading assignment exists to prevent. A transpose that does not fit
    is a config error, not something to quietly repair.

    `ValueError` rather than a CLI error because this module has never heard
    of a flag or a file — `loop.trim` and `loop.candidates` raise the same way,
    and the CLI adds the provenance it alone knows.
    """
    if not score.notes or shift == 0:
        return

    top = max(note.pitch for note in score.notes)
    if top + shift > MAX_PITCH:
        raise ValueError(
            f"transform.transpose = {shift:+d}: {_name(top)} (MIDI {top}) becomes "
            f"MIDI {top + shift}, past the playable ceiling of {MAX_PITCH}. "
            f"This score allows at most {MAX_PITCH - top:+d}."
        )

    bottom = min(note.pitch for note in score.notes)
    if bottom + shift < MIN_PITCH:
        raise ValueError(
            f"transform.transpose = {shift:+d}: {_name(bottom)} (MIDI {bottom}) becomes "
            f"MIDI {bottom + shift}, under the playable floor of {MIN_PITCH}. "
            f"This score allows at least {MIN_PITCH - bottom:+d}."
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_transform.py -v`
Expected: PASS. If `F#1` fails, check `_name`: MIDI 30 is `30 % 12 == 6` → `F#`, `30 // 12 - 1 == 1` → `F#1`.

- [ ] **Step 5: Prove the refusal tests**

Break: make `_check_fits` return immediately (`return` as its first statement).
Run: `.venv/bin/pytest tests/test_transform.py -v`
Expected: FAIL on both refusal tests with `DID NOT RAISE`.
Restore and re-run: PASS.

- [ ] **Step 6: Prove the boundary is the edge**

Break: change `>` to `>=` in the ceiling check.
Run: `.venv/bin/pytest tests/test_transform.py -k largest_transpose -v`
Expected: FAIL — a shift landing exactly on C8 must be accepted.
Restore and re-run: PASS.

- [ ] **Step 7: Run the whole suite and commit**

Run: `.venv/bin/pytest`
Expected: PASS.

```bash
git add src/bitty/transform.py tests/test_transform.py
git commit -m "feat: refuse a transpose that does not fit the score"
```

---

### Task 5: Wire it into the CLI — twice, and only twice

One transform site per command that ingests, and none at `render`. This is the task where the phase becomes visible, and where the double-apply contract is nailed down by a test.

**Files:**
- Modify: `src/bitty/cli.py` (import; `sections` after `parsed = ingest(score)`; `convert` after `parsed = ingest(score)`; new `_transform` helper)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `transform.apply` (Tasks 2–4), `Config.transform` (Task 1), `config_module.discover` (existing).
- Produces: no new public names. `render` is deliberately unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def a_config(tmp_path, body):
    path = tmp_path / "sweep.toml"
    path.write_text(body)
    return str(path)


def test_convert_obeys_the_transform_table(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path)])
    plain = Arrangement.from_json((tmp_path / "minuet.arrangement.json").read_text())

    shifted_dir = tmp_path / "up"
    result = runner.invoke(
        app,
        [
            "convert", str(MINUET), "-o", str(shifted_dir),
            "--config", a_config(tmp_path, "[transform]\ntranspose = 3\n"),
        ],
    )
    assert result.exit_code == 0, result.output
    shifted = Arrangement.from_json((shifted_dir / "minuet.arrangement.json").read_text())

    def pitches(arrangement):
        return [e.pitch for c in arrangement.channels for e in c.events]

    assert pitches(shifted) == [pitch + 3 for pitch in pitches(plain)]


def test_convert_obeys_the_tempo_scale(tmp_path):
    """`--target generic` so the audio lands in one file whatever the loop did.

    The bevy default names its output after the loop it found
    (`minuet_loop.wav`), and `tempo_scale` is allowed to change which
    candidate wins — see the loop risk in the design. Asserting on a filename
    that depends on the thing under test is how a test starts failing for the
    wrong reason.
    """
    result = runner.invoke(
        app,
        [
            "convert", str(MINUET), "-o", str(tmp_path), "--wav", "--target", "generic",
            "--config", a_config(tmp_path, "[transform]\ntempo_scale = 2.0\n"),
        ],
    )
    assert result.exit_code == 0, result.output
    written = Arrangement.from_json((tmp_path / "minuet.arrangement.json").read_text())
    assert written.meta["bpm"] == 240.0

    audio, sample_rate = sf.read(tmp_path / "minuet.wav")
    # The untransformed generic render is 24.4s; halving the tempo halves the
    # music and the echo with it, so anything near 24s means bpm moved alone.
    assert 10.0 < len(audio) / sample_rate < 15.0


def test_sections_reports_the_key_it_was_transposed_into(tmp_path):
    """Key detection needs no special-casing: `analyze` sees the new pitches."""
    plain = runner.invoke(app, ["sections", str(MINUET)])
    assert "G major" in plain.output and "D major" in plain.output

    result = runner.invoke(
        app,
        ["sections", str(MINUET), "--config", a_config(tmp_path, "[transform]\ntranspose = 2\n")],
    )
    assert result.exit_code == 0, result.output
    assert "A major" in result.output and "E major" in result.output


def test_a_transpose_that_does_not_fit_is_refused_by_name(tmp_path):
    result = runner.invoke(
        app,
        [
            "convert", str(MINUET), "-o", str(tmp_path),
            "--config", a_config(tmp_path, "[transform]\ntranspose = 21\n"),
        ],
    )
    assert result.exit_code != 0
    assert "past the playable ceiling" in result.output
    assert "at most +20" in result.output
    assert "sweep.toml" in result.output, "the CLI knows the provenance; say it"


def test_render_does_not_transform(tmp_path):
    """The contract that makes one transform site safe.

    Everything musical was decided when the JSON was written. If `render`
    applied `[transform]` too, this convert-at-+3 would re-render at +6 and the
    two files would differ.
    """
    config = a_config(tmp_path, "[transform]\ntranspose = 3\ntempo_scale = 1.25\n")
    runner.invoke(
        app,
        [
            "convert", str(MINUET), "-o", str(tmp_path), "--wav",
            "--target", "generic", "--config", config,
        ],
    )
    before = (tmp_path / "minuet.wav").read_bytes()
    (tmp_path / "minuet.wav").unlink()

    result = runner.invoke(
        app,
        [
            "render", str(tmp_path / "minuet.arrangement.json"),
            "-o", str(tmp_path), "--wav", "--target", "generic", "--config", config,
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "minuet.wav").read_bytes() == before
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -k transform or transposed or tempo_scale -v`
Expected: FAIL — the transpose comparison fails (pitches unchanged), the bpm assertion reads `120.0`, and the refusal exits 0. `test_render_does_not_transform` will *pass* already, which is correct: it is a contract test, and Step 6 proves it.

- [ ] **Step 3: Implement**

In `src/bitty/cli.py`, add the import next to the other stage imports:

```python
from bitty import transform as transform_stage
```

Add the helper next to `_settings`:

```python
def _transform(
    parsed, settings: Config, directory: Path, stem: str, explicit: Path | None
):
    """The score's own validation, wrapped with the provenance only the CLI has.

    `transform.apply` has the notes but has never seen a file; `load` folds
    every layer into a plain `Config` and keeps no source. Neither can write
    the whole message, so the CLI composes it — the same division `loop.trim`
    and `--bars` already keep.
    """
    try:
        return transform_stage.apply(parsed, settings.transform)
    except ValueError as error:
        sources = config_module.discover(directory, stem)
        if explicit is not None:
            sources.append(explicit)
        where = "".join(f"\nConfig read from: {path}" for path in sources)
        raise typer.BadParameter(f"{error}{where}", param_hint="--config") from error
```

In `sections`, immediately after `parsed = ingest(score)`:

```python
    parsed = _transform(parsed, settings, score.parent, score.stem, config_path)
```

In `convert`, immediately after `parsed = ingest(score)` and *before* the `--bars` trim:

```python
    parsed = _transform(parsed, settings, score.parent, score.stem, config_path)
```

Leave `render` alone. Its docstring already says why.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Prove the wiring tests**

Break: comment out the `_transform` line in `convert`.
Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL on `test_convert_obeys_the_transform_table`, `test_convert_obeys_the_tempo_scale`, and `test_a_transpose_that_does_not_fit_is_refused_by_name`.
Restore, then comment out the line in `sections` and re-run: FAIL on `test_sections_reports_the_key_it_was_transposed_into`.
Restore both and re-run: PASS.

- [ ] **Step 6: Prove the render contract**

Break: in `render`, add the same transform after loading —

```python
    loaded = Arrangement.from_json(arrangement.read_text())
    from dataclasses import replace as _replace
    loaded = _replace(
        loaded,
        channels=tuple(
            _replace(c, events=tuple(_replace(e, pitch=e.pitch + settings.transform.transpose) for e in c.events))
            for c in loaded.channels
        ),
    )
```

Run: `.venv/bin/pytest tests/test_cli.py -k render_does_not -v`
Expected: FAIL — the re-rendered audio is a minor third above the converted one.
Delete the break entirely and re-run: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS, goldens unchanged. `test_goldens.py` calls `arrange(ingest(...))` directly and never touches the CLI, and every existing CLI test runs at the identity.

- [ ] **Step 8: Commit**

```bash
git add src/bitty/cli.py tests/test_cli.py
git commit -m "feat: apply [transform] after ingest, and never at render"
```

---

### Task 6: The sweep configs and a listening pass before the audition

The audition needs clips. This task produces them and *looks at the numbers first*, so Task 8's listening is spent on the questions only ears can answer rather than on catching a plumbing bug.

**Files:**
- Create: `audition/transform/*.toml`, `audition/transform/*.wav`
- Modify: none in `src/`

- [ ] **Step 1: Write the sweep configs**

```bash
mkdir -p audition/transform
cd /home/trog/code/bitty-music
for n in -12 -5 5 12; do
  printf '[transform]\ntranspose = %s\n' "$n" > "audition/transform/transpose$n.toml"
done
printf '[transform]\ntranspose = 0\n' > audition/transform/control.toml
for s in 0.75 1.5 4.0; do
  printf '[transform]\ntempo_scale = %s\n' "$s" > "audition/transform/tempo$s.toml"
done
```

- [ ] **Step 2: Render the clips as WAV**

`aplay` renders Ogg as static, so every audition file is WAV. One knob at a time: a bad result at an extreme scale is unattributable if both moved.

`--target generic` on purpose. The bevy default names its output after the loop it found — `minuet_loop.wav`, or plain `minuet.wav` when no loop survives — and `tempo_scale` is allowed to move the seam, so the clip filenames would vary with the variable under test. Generic writes one continuous `minuet.wav` per variant whatever the loop did, which is also what "clips stay continuous" wants.

```bash
.venv/bin/bitty convert tests/fixtures/minuet.mxl -o audition/transform/control \
  --wav --target generic --config audition/transform/control.toml
for n in -12 -5 5 12; do
  .venv/bin/bitty convert tests/fixtures/minuet.mxl -o "audition/transform/t$n" \
    --wav --target generic --config "audition/transform/transpose$n.toml"
done
for s in 0.75 1.5 4.0; do
  .venv/bin/bitty convert tests/fixtures/minuet.mxl -o "audition/transform/s$s" \
    --wav --target generic --config "audition/transform/tempo$s.toml"
done
```

Each variant directory gets `minuet.wav` and `minuet.arrangement.json`, and no `music.ron` — generic writes no manifest.

- [ ] **Step 3: Find where transpose actually stops working**

The bounds are provisional and the audition sets them, so the sweep must include the refusals. The minuet spans MIDI 42–88, so `+21` and `-19` are the first shifts that refuse.

```bash
printf '[transform]\ntranspose = 21\n' > audition/transform/over.toml
.venv/bin/bitty convert tests/fixtures/minuet.mxl -o /tmp/over --wav --target generic \
  --config audition/transform/over.toml   # expect a refusal naming +20
```

Then render the two edge cases that *are* allowed — `+20` (the top note lands exactly on C8) and `-18` (the bottom lands exactly on C1). These are the clips that decide whether 24 and 108 are the right constants.

```bash
printf '[transform]\ntranspose = 20\n' > audition/transform/edge-high.toml
printf '[transform]\ntranspose = -18\n' > audition/transform/edge-low.toml
for e in high low; do
  .venv/bin/bitty convert tests/fixtures/minuet.mxl -o "audition/transform/edge-$e" \
    --wav --target generic --config "audition/transform/edge-$e.toml"
done
```

- [ ] **Step 4: Assert the control is the control**

`transpose = 0, tempo_scale = 1.0` must be byte-identical to a plain convert, by construction. In the tail-wrap A/B it was exactly this check that caught an artifact in the harness rather than in the audio.

```bash
.venv/bin/bitty convert tests/fixtures/minuet.mxl -o /tmp/plain --wav --target generic
cmp audition/transform/control/minuet.wav /tmp/plain/minuet.wav && echo "control is identical"
```

Expected: `control is identical`. If it is not, stop — the identity path is broken and no listening is worth anything until it is fixed.

- [ ] **Step 5: Probe for the envelope-frame risk and for silence**

Volume envelopes run at 60 steps/sec, so a note under 16.7 ms articulates as a click rather than as a note. `tempo_scale = 4.0` is where that starts. And no clip may contain a near-zero window, because a gap reads as the artifact under test — the mistake the count-3 audition made with a 0.6 s separator.

```bash
.venv/bin/python - <<'PY'
import json, pathlib
import numpy as np, soundfile as sf

for wav in sorted(pathlib.Path("audition/transform").rglob("*.wav")):
    audio, rate = sf.read(wav)
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    window = int(0.25 * rate)
    frames = np.array([
        np.max(np.abs(mono[i:i + window])) for i in range(0, len(mono) - window, window)
    ])
    quiet = int((frames < 0.005).sum())
    print(f"{wav}  {len(mono)/rate:6.2f}s  peak {np.max(np.abs(mono)):.3f}  quiet windows {quiet}")

for js in sorted(pathlib.Path("audition/transform").rglob("*.arrangement.json")):
    data = json.loads(js.read_text())
    durs = [e["dur"] for c in data["channels"] for e in c["events"]]
    short = sum(1 for d in durs if d < 1 / 60)
    print(f"{js}  bpm {data['meta']['bpm']}  events {len(durs)}  under one frame {short}")
PY
```

Record the numbers. Any clip with a quiet window is a harness fault to fix before Task 8; the sub-frame event count at `4.0` is the measurement the risk section asks for.

- [ ] **Step 6: Note whether the loop moved**

`tempo_scale` moves seam positions, so a transformed piece may loop differently from the same piece untransformed. Not a defect, but it should be observed here rather than discovered later. Compare the `loop:` line each convert printed, and the `loop` block in each arrangement JSON, against the control's.

- [ ] **Step 7: Commit the clips**

```bash
git add audition/transform
git commit -m "audition: render the transform sweep"
```

---

### Task 7: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add `[transform]` to the complete example**

In the `### Complete example` block, after the `[loop]` table (keep the file's own table order):

```toml
[transform]
transpose = 0            # -48..48 semitones; refuses if the score leaves C1-C8
tempo_scale = 1.0        # 0.25-4.0; re-arranges at the new tempo
```

- [ ] **Step 2: Add the subsection**

After the `### [voices] count` subsection, add `### [transform]`, in prose matching the file's register, covering these five points. Include this table verbatim — it is the whole reason `tempo_scale` is not a playback speed:

```markdown
| Follows the tempo | Stays absolute |
|---|---|
| The echo's delay — `delay_beats` is beats, and a beat got shorter | `arp.rate_ms` |
| Bar boundaries, and the sections `bitty sections` prints | `vibrato.rate_hz` |
| Loop seam positions, and the length of what is written | `vibrato.delay_ms` |
| Which notes are long enough to waver | `vibrato.min_note_ms` |
```

1. `tempo_scale` re-derives the arrangement rather than playing it faster, and what that costs: at 1.5, notes that used to clear `vibrato.min_note_ms` no longer do, so the piece loses vibrato; a slowed piece gains it. That is a re-arrangement, and it is the point.
2. The right-hand column is absolute because those values are seconds in the file and nothing derives them from bpm — and 48 ms in particular is a fact about the ear that Phase 7 measured, after 16 ms was found to fuse into roughness at 31 Hz instead of reading as notes. Scaling it with the tempo would undo that finding.
3. `transpose` is integer semitones, uniform, and refuses rather than folding when a note would leave the C1–C8 playable band. Quote the real refusal message, copied from a run rather than from this plan.
4. `render` ignores `[transform]` along with the rest of the musical config: everything musical was decided when the JSON was written, and a `convert` at `+3` re-rendered under the same config would land at `+6`.
5. The playable band is calibration and lives in `transform.py`, not the TOML — the same rule that keeps the arpeggio rate out of config.

- [ ] **Step 3: Update the Status section**

Add a paragraph: Phase 9 is done — `[transform]` with `transpose` and `tempo_scale`; `tempo_scale` taken as an arranger input rather than a playback speed, and what the audition found about the C1/C8 bounds and about `tempo_scale = 4.0`. Write this **after** Task 8, so the numbers are the ones the audition actually produced rather than the ones this plan predicted.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document the [transform] table"
```

---

### Task 8: The audition

The audition **sets** the two bounds rather than confirming them, the way Phase 7 set `arp_rate_sec` by ear rather than by theory. It is the phase's acceptance gate: do not merge before it.

**Files:**
- Create: `audition/transform/NOTES.md`
- Modify: nothing in `src/`.

- [ ] **Step 1: Know how these clips are played**

`audition/play` expects the bevy layout, `audition/<set>/<fixture>_loop.wav`, which Task 6 deliberately did not produce — these are generic single files, one per variant. Play them directly:

```bash
aplay -q audition/transform/control/minuet.wav
aplay -q audition/transform/t5/minuet.wav
```

**Clips stay continuous** — no separators, no inserted silence, no concatenation joins that fake a seam. The count-3 audition put a 0.6 s separator between clips and it was heard as a gap in the music; the artifact under test must not be something the harness introduced.

- [ ] **Step 2: Write `audition/transform/NOTES.md`**

Follow `audition/tailwrap/NOTES.md`: what was measured, a table of the numbers from Task 6, which clip is the control and why it is identical by construction, and what to listen to. State the questions plainly:

1. Where does `transpose` actually stop working, in both directions? Is C1 too low, or not low enough? Is C8 too high?
2. At `tempo_scale = 1.5`, does the re-arrangement read as musical — the echo following the tempo, vibrato disappearing across the 500 ms threshold — or does it read as a piece missing something?
3. At `tempo_scale = 0.75`, does newly-appearing vibrato help or does it sound seasick?
4. At `tempo_scale = 4.0`, where do notes start clicking instead of sounding? Is 4.0 the right cap?

- [ ] **Step 3: Hand it over**

Play with `aplay` (WAV only) and ask for a verdict on each of the four questions, plus the control check: if the control sounds different from a plain render, the difference is expectation, not audio, and the harness is what needs fixing.

- [ ] **Step 4: Act on the verdict**

If the bounds move, change `MIN_PITCH`/`MAX_PITCH` in `transform.py`, update the two refusal tests in `tests/test_transform.py`, update the README, and record in `NOTES.md` what was heard and what changed. This document's numbers being wrong is an expected outcome; its design being wrong is not.

- [ ] **Step 5: Commit the verdict**

```bash
git add audition/transform src/bitty/transform.py tests/test_transform.py README.md
git commit -m "audition: set the transform bounds by ear"
```

- [ ] **Step 6: Finish the phase**

Run `.venv/bin/pytest` one last time — the whole suite, goldens included — then:

```bash
git checkout main
git merge --no-ff phase-9-transform -m "Merge Phase 9: transform"
```

---

## Notes for the executor

- **The design calls the config table registry `_KEYS`; the code calls it `_TABLES`.** Same thing — `config.py` has always used `_TABLES`. Follow the code.
- **`bitty sections` also transforms.** That is deliberate: the key it reports and the section lengths it prints are the ones `convert` will use, and a `sections` that described the untransformed score would be lying about the piece you are about to convert.
- **Order inside `convert`:** ingest → transform → `--bars` trim → loop candidates → arrange. Transform first because it belongs immediately after ingest; the trim is by *printed bar number*, which transform never changes, so the two do not interact.
- **Do not add a warning when `render` sees a non-default `[transform]`.** Every musical table is ignored there, silently, and this one is not special.
- **The `tempo_scale` division direction is the easy thing to get backwards.** `bpm * scale` and times `/ scale`. `scale = 2.0` means twice as fast: double the bpm, half the duration, a shorter WAV.
