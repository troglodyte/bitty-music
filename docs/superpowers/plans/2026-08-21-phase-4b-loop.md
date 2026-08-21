# Phase 4b — Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Choose where the music loops, trim the score to the part worth looping, verify the seam does not click or sever a phrase, and record the decision in the arrangement.

**Architecture:** One new module, `loop.py`, owning selection and trim. Selection splits in two because its halves need different inputs: `candidates()` is symbolic and runs before `arrange`, `choose()` needs rendered audio and runs after `render`. Every candidate is a pair of offsets into the *same* rendered buffer, so falling through the cascade costs metric evaluation, not re-synthesis. `Arrangement` gains a `loop` field; `cli` gains `--bars`, `--loop-from`, `--split`, and an auto-loop line on `sections`.

**Tech Stack:** Python 3.11+, music21 10.5, numpy, typer, soundfile, pytest. Run tests with `.venv/bin/pytest`.

**Spec:** `docs/superpowers/specs/2026-08-21-phase-4b-loop-design.md`

## Global Constraints

- **The cascade never modifies audio.** No crossfade, no tail wrapping, no fades. `choose` reads the buffer and returns offsets. Tail-wrapping is explicitly deferred to a later phase pending an audition.
- **The echo tail is reported, never rejected.** Only *dry* events reject a candidate. Rejecting on the echo tail kills every candidate on two of three fixtures — this was measured, not guessed.
- **A note ending exactly at `loop_end` does not cross.** Compare `e.t + e.dur > loop_end + EPSILON` with `EPSILON = 1e-6`. Written the other way it counts every final note as severed.
- **`SEAM_RATIO = 1.0`, `MIN_LOOP_BARS = 8`.** Module constants. No config file this phase — Phase 5 brings TOML.
- **Bar numbers are as printed.** `--bars` and `--loop-from` take printed numbers. Trimming moves seconds, never numbers.
- **Manual overrides everything.** `--loop-from` returns its candidate even when both seam tests fail. The measured seam is still printed.
- **`--split` with no loop is a hard error**, exit code 1. Never degrade to a single file with a warning.
- **Determinism is unchanged.** Nothing calls `random`. Identical input still renders identical bytes.
- **Out of scope:** librosa / self-similarity, per-bar feature vectors, `--expand-repeats`, `--play`, the target registry, `music.ron`, TOML config, tail wrapping.
- Source layout is `src/bitty/`, tests in `tests/`. 160 tests pass before this phase starts.

### Verified facts this plan is built on

Measured against the fixtures on 2026-08-21, before the plan was written. Do not re-derive.

| Fact | Value |
|---|---|
| Fixture bar counts | two_part 1, ornaments 1, late_signature 2, chorale 8, minuet 16, ragtime 16 |
| Fixture durations | chorale 16.0 s (audio 16.38 s), minuet 24.0 s (audio 24.38 s), ragtime 19.2 s (audio 19.35 s) |
| Rendered audio exceeds score end | by the echo delay: 0.38 s (chorale, minuet), 0.15 s (ragtime) |
| Sections | chorale `[(1,8)]`, minuet `[(1,8),(9,16)]`, ragtime `[(1,16)]` |
| Repeat spans | minuet `(1,8)` and `(9,16)`; ragtime `(1,16)`; chorale none |
| `ordinary` (99.9th pct adjacent-sample step) | chorale 0.266, minuet 0.420, ragtime 0.455 |
| Seam ratio, bar-aligned candidates | 0.02 – 0.38 across all fixtures and tiers |
| Seam ratio, 400 random splices/fixture | median 0.54–0.80, p90 1.07–1.67, max 2.97; 15–40% exceed 1.0 |
| Dry crossings, bar-aligned candidates | **zero**, every fixture, every tier |
| Echo-tail crossings | present on chorale `(1,8)`, ragtime `(1,16)`, minuet `(9,16)`; absent on minuet `(1,8)` |
| Echo tail level | −11 to −14 dB vs body RMS |
| Expected picks | chorale bars 1–8 (section), minuet bars 1–8 (repeat), ragtime bars 1–16 (repeat) |
| Pipeline cost | ingest 0.02–0.03 s, analyze 0.01 s, arrange <0.01 s, render 0.08–0.12 s |
| `ECHO_BEATS` / `ECHO_LEVEL` | 0.75 / 0.35, in `voices.py`; `delay_sec = 0.75 * 60 / bpm` |

---

### Task 1: `Loop` on the arrangement contract

The contract change, on its own, so the golden diff is reviewable in isolation.

**Files:**
- Modify: `src/bitty/arrangement.py`
- Modify: `src/bitty/arrange.py:75`
- Test: `tests/test_arrangement.py`, `tests/goldens/*.arrangement.json`

**Interfaces:**
- Consumes: nothing.
- Produces: `arrangement.Loop(start_sec: float, end_sec: float)`; `Arrangement.loop: Loop | None = None`; `meta["bars"] = [first, last]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_arrangement.py`:

```python
def test_a_loop_round_trips_through_json():
    original = Arrangement(meta={"title": "t", "bpm": 120}, channels=(),
                           loop=Loop(start_sec=1.5, end_sec=12.0))
    restored = Arrangement.from_json(original.to_json())
    assert restored.loop == Loop(start_sec=1.5, end_sec=12.0)


def test_an_arrangement_without_a_loop_serializes_it_as_null():
    text = Arrangement(meta={}, channels=()).to_json()
    assert '"loop": null' in text
    assert Arrangement.from_json(text).loop is None


def test_a_loop_field_this_build_does_not_know_is_dropped():
    """The same forgiving-load contract Instrument and Event already keep."""
    text = '{"meta": {}, "channels": [], "loop": {"start_sec": 0.0, "end_sec": 4.0, "curve": "s"}}'
    assert Arrangement.from_json(text).loop == Loop(start_sec=0.0, end_sec=4.0)


def test_meta_records_the_printed_bar_range():
    from bitty.arrange import arrange
    from bitty.ingest import ingest
    arrangement = arrange(ingest(Path(__file__).parent / "fixtures" / "minuet.mxl"))
    assert arrangement.meta["bars"] == [1, 16]
```

Add `Loop` to the existing `from bitty.arrangement import ...` line and `from pathlib import Path` if absent.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_arrangement.py -v`
Expected: FAIL — `ImportError: cannot import name 'Loop'`

- [ ] **Step 3: Add the contract**

In `src/bitty/arrangement.py`, after `Echo`:

```python
@dataclass(frozen=True)
class Loop:
    """Where the audio comes back around. Seconds, like every other time here.

    Two floats and no more. `source` and the measured seam explain a decision
    already made; this file is the hand-edit surface, where an extra field
    invites someone to change it and expect something to happen.
    """

    start_sec: float
    end_sec: float
```

Change `Arrangement` and `from_json`:

```python
@dataclass(frozen=True)
class Arrangement:
    meta: dict
    channels: tuple[Channel, ...]
    loop: Loop | None = None

    ...

    @classmethod
    def from_json(cls, text: str) -> Arrangement:
        raw = json.loads(text)
        return cls(
            meta=raw["meta"],
            channels=tuple(_channel_from(c) for c in raw["channels"]),
            loop=_loop_from(raw.get("loop")),
        )
```

And the loader, beside the others:

```python
def _loop_from(raw: dict | None) -> Loop | None:
    """Same drop-unknown-fields contract the other loaders keep."""
    if not raw:
        return None
    known = {f.name for f in fields(Loop)}
    return Loop(**{k: v for k, v in raw.items() if k in known})
```

In `src/bitty/arrange.py`, replace the `return Arrangement(...)` meta:

```python
    meta = {"title": score.title, "bpm": score.bpm}
    if score.bars:
        meta["bars"] = [score.bars[0].number, score.bars[-1].number]

    return Arrangement(meta=meta, channels=tuple(channels))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_arrangement.py -v`
Expected: PASS

- [ ] **Step 5: Regenerate the goldens and read the diff**

Run:
```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
git diff tests/goldens/
```

Expected: exactly two kinds of change per file — a `"bars": [1, N]` entry added inside `meta`, and `"loop": null` added at the end. `N` is 8 for chorale, 16 for minuet and ragtime. **No event, instrument, or channel line may move.** Anything else means the `meta` change disturbed arranging — stop and investigate rather than accepting the diff.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS, 164 tests.

- [ ] **Step 7: Commit**

```bash
git add src/bitty/arrangement.py src/bitty/arrange.py tests/test_arrangement.py tests/goldens/
git commit -m "feat: give the arrangement a loop field and a printed bar range"
```

---

### Task 2: `trim` — cutting the score to a bar range

**Files:**
- Create: `src/bitty/loop.py`
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `model.Score`, `model.Bar`, `model.Note`.
- Produces: `loop.trim(score: Score, first_bar: int, last_bar: int) -> Score`; `loop.EPSILON = 1e-6`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_loop.py`:

```python
from dataclasses import replace
from pathlib import Path

import pytest

from bitty import loop
from bitty.ingest import ingest
from bitty.model import Bar, Note, Score

MINUET = Path(__file__).parent / "fixtures" / "minuet.mxl"


def timeline(count: int, **marks) -> tuple[Bar, ...]:
    """`count` one-second bars numbered from 1, with marks by bar number.

    Deliberately the same helper shape as tests/test_analyze.py — the two
    modules read the same timeline, so their fixtures should look alike.
    """
    return tuple(
        Bar(
            number=n,
            start=float(n - 1),
            dur=1.0,
            time_signature=(4, 4),
            sharps=0,
            starts_repeat=n in marks.get("starts_repeat", set()),
            ends_repeat=n in marks.get("ends_repeat", set()),
            ends_span=n in marks.get("ends_span", set()),
        )
        for n in range(1, count + 1)
    )


def synthetic(bars: tuple[Bar, ...], notes: tuple[Note, ...] = ()) -> Score:
    return Score(
        notes=notes, bpm=60.0, time_signature=(4, 4), title="synthetic", bars=bars
    )


def note(start: float, dur: float = 0.5, pitch: int = 60) -> Note:
    return Note(pitch=pitch, start=start, dur=dur, velocity=64, part=0)


def test_trim_keeps_only_the_requested_bars():
    trimmed = loop.trim(synthetic(timeline(8)), 3, 5)
    assert [b.number for b in trimmed.bars] == [3, 4, 5]


def test_trim_rebases_times_to_zero_without_renumbering():
    trimmed = loop.trim(synthetic(timeline(8)), 3, 5)
    assert trimmed.bars[0].start == 0.0
    assert trimmed.bars[0].number == 3  # printed numbers never move


def test_trim_drops_notes_outside_the_range_and_rebases_the_rest():
    notes = (note(1.0), note(2.5), note(4.5), note(6.0))
    trimmed = loop.trim(synthetic(timeline(8), notes), 3, 5)
    assert [n.start for n in trimmed.notes] == [0.5, 2.5]


def test_a_note_beginning_before_the_range_is_excluded_even_if_it_sustains_in():
    """The same 'begins in' rule analyze.py uses for key detection."""
    trimmed = loop.trim(synthetic(timeline(8), (note(1.5, dur=3.0),)), 3, 5)
    assert trimmed.notes == ()


def test_trimming_to_bars_that_do_not_exist_is_an_error():
    with pytest.raises(ValueError, match="no bars"):
        loop.trim(synthetic(timeline(8)), 20, 30)


def test_trimming_a_real_score_preserves_its_other_fields():
    trimmed = loop.trim(ingest(MINUET), 9, 16)
    assert trimmed.title == "minuet"
    assert trimmed.bpm == 120
    assert trimmed.bars[0].number == 9 and trimmed.bars[0].start == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bitty.loop'`

- [ ] **Step 3: Write `loop.py` with `trim`**

Create `src/bitty/loop.py`:

```python
"""Where the music comes back around, and what to keep of it.

The parent spec calls this stage "loop start/end selection, trim", and both
halves live here. Selection itself splits in two: `candidates` is symbolic and
runs before arranging, `choose` needs rendered audio and runs after. That
departure from the stage diagram is deliberate — a click is an audio property
and cannot be measured anywhere else.

Every candidate is a pair of offsets into the same rendered buffer, so falling
through the cascade costs metric evaluation, not re-synthesis.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from bitty.model import Score

EPSILON = 1e-6  # onset times are floats; matches arrange.EPSILON


def trim(score: Score, first_bar: int, last_bar: int) -> Score:
    """Cut `score` to the printed bar range, rebasing seconds to zero.

    Bar *numbers* are untouched: 4a promises they are as printed, and
    `--bars 9-16` has to keep meaning bars 9-16 in the output.

    A note counts as inside the range when it *begins* there, matching the rule
    analyze.py uses for key detection — a note held across the cut cannot
    colour a range it never articulated in.
    """
    kept = [bar for bar in score.bars if first_bar <= bar.number <= last_bar]
    if not kept:
        raise ValueError(f"no bars in the range {first_bar}-{last_bar}")

    offset = kept[0].start
    end = kept[-1].start + kept[-1].dur
    return replace(
        score,
        notes=tuple(
            replace(n, start=n.start - offset)
            for n in score.notes
            if offset - EPSILON <= n.start < end - EPSILON
        ),
        bars=tuple(replace(bar, start=bar.start - offset) for bar in kept),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_loop.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add src/bitty/loop.py tests/test_loop.py
git commit -m "feat: trim a score to a printed bar range"
```

---

### Task 3: the candidate cascade

**Files:**
- Modify: `src/bitty/loop.py`
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `loop.trim`, `analyze.Section`, `model.Score`.
- Produces: `loop.LoopCandidate(first_bar, last_bar, start, end, source)`; `loop.candidates(score, sections, loop_from=None) -> tuple[LoopCandidate, ...]`; `loop.MIN_LOOP_BARS = 8`.

- [ ] **Step 1: Write the failing tests**

Add `from bitty.analyze import analyze` to the import block at the top of
`tests/test_loop.py`, then append the rest:

```python
RAGTIME = Path(__file__).parent / "fixtures" / "ragtime.mxl"
CHORALE = Path(__file__).parent / "fixtures" / "chorale.mxl"


def spans(cands) -> list[tuple[int, int, str]]:
    return [(c.first_bar, c.last_bar, c.source) for c in cands]


def test_a_repeat_pair_becomes_the_first_candidate():
    score = synthetic(timeline(16, starts_repeat={1}, ends_repeat={16}))
    assert spans(loop.candidates(score, analyze(score)))[0] == (1, 16, "repeat")


def test_an_end_repeat_with_no_start_repeats_from_bar_one():
    score = synthetic(timeline(16, ends_repeat={12}))
    assert (1, 12, "repeat") in spans(loop.candidates(score, analyze(score)))


def test_repeat_spans_are_ordered_longest_first():
    score = synthetic(timeline(30, starts_repeat={1, 11}, ends_repeat={10, 30}))
    repeats = [s for s in spans(loop.candidates(score, analyze(score))) if s[2] == "repeat"]
    assert repeats == [(11, 30, "repeat"), (1, 10, "repeat")]


def test_a_repeat_span_under_the_floor_is_dropped():
    score = synthetic(timeline(16, starts_repeat={1}, ends_repeat={4}))
    assert all(s[2] != "repeat" for s in spans(loop.candidates(score, analyze(score))))


def test_sections_fall_through_as_suffixes_whole_piece_first():
    score = synthetic(timeline(24, ends_span={8, 16}))
    sections = [s for s in spans(loop.candidates(score, analyze(score))) if s[2] == "section"]
    assert sections == [(1, 24, "section"), (9, 24, "section"), (17, 24, "section")]


def test_a_score_with_no_marks_yields_the_whole_piece():
    score = synthetic(timeline(12))
    assert spans(loop.candidates(score, analyze(score))) == [(1, 12, "section")]


def test_a_score_shorter_than_the_floor_yields_nothing():
    score = synthetic(timeline(4))
    assert loop.candidates(score, analyze(score)) == ()


def test_loop_from_yields_exactly_one_manual_candidate_to_the_end():
    score = synthetic(timeline(16, starts_repeat={1}, ends_repeat={16}))
    assert spans(loop.candidates(score, analyze(score), loop_from=5)) == [(5, 16, "manual")]


def test_a_manual_start_below_the_floor_is_still_honoured():
    """Manual overrides the cascade entirely, floor included."""
    score = synthetic(timeline(16))
    assert spans(loop.candidates(score, analyze(score), loop_from=14)) == [(14, 16, "manual")]


def test_a_manual_start_on_a_bar_that_does_not_exist_is_an_error():
    score = synthetic(timeline(16))
    with pytest.raises(ValueError, match="no bar 99"):
        loop.candidates(score, analyze(score), loop_from=99)


def test_candidate_times_come_from_the_bar_timeline():
    score = synthetic(timeline(16, starts_repeat={9}))
    section = [c for c in loop.candidates(score, analyze(score)) if c.first_bar == 9][0]
    assert (section.start, section.end) == (8.0, 16.0)


def test_the_fixtures_generate_the_candidates_measured_in_the_plan():
    for path, expected in (
        (MINUET, [(1, 8, "repeat"), (9, 16, "repeat"), (1, 16, "section"), (9, 16, "section")]),
        (RAGTIME, [(1, 16, "repeat"), (1, 16, "section")]),
        (CHORALE, [(1, 8, "section")]),
    ):
        score = ingest(path)
        assert spans(loop.candidates(score, analyze(score))) == expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_loop.py -v`
Expected: FAIL — `AttributeError: module 'bitty.loop' has no attribute 'candidates'`

- [ ] **Step 3: Implement the cascade**

Append to `src/bitty/loop.py` (and add `from bitty.model import Bar, Score` to the imports):

```python
MIN_LOOP_BARS = 8  # the parent spec's [loop] min_bars, until Phase 5 brings config


@dataclass(frozen=True)
class LoopCandidate:
    """One span the cascade is willing to propose, and why.

    `source` exists to be printed. It is what makes "(repeat marks, seam ok)"
    an explanation rather than an assertion.
    """

    first_bar: int  # printed numbers, inclusive
    last_bar: int
    start: float  # seconds, in the trimmed score's time
    end: float
    source: str  # "repeat" | "section" | "manual"


def candidates(score: Score, sections, loop_from: int | None = None) -> tuple[LoopCandidate, ...]:
    """The cascade, cheapest and most trustworthy first.

    Manual selection overrides it entirely — the parent spec's rule — so
    `loop_from` short-circuits both tiers and the bar floor with it.
    """
    if not score.bars:
        return ()
    if loop_from is not None:
        return (_manual(score.bars, loop_from),)
    return (*_from_repeats(score.bars), *_from_sections(sections))


def _manual(bars: tuple[Bar, ...], first_bar: int) -> LoopCandidate:
    start = next((bar for bar in bars if bar.number == first_bar), None)
    if start is None:
        raise ValueError(f"no bar {first_bar} in this score")
    return LoopCandidate(
        first_bar=start.number,
        last_bar=bars[-1].number,
        start=start.start,
        end=bars[-1].start + bars[-1].dur,
        source="manual",
    )


def _from_repeats(bars: tuple[Bar, ...]) -> list[LoopCandidate]:
    """The composer stating where the music comes back around.

    An end repeat with no preceding start repeats from bar one, which is both
    music21's convention and the notational one. Longest first: a loop wants
    the substantial repeated body, not an incidental four-bar echo.
    """
    pairs: list[tuple[Bar, Bar]] = []
    opening: Bar | None = None
    for bar in bars:
        if bar.starts_repeat:
            opening = bar
        if bar.ends_repeat:
            pairs.append((opening or bars[0], bar))
            opening = None

    pairs.sort(key=lambda pair: (-_length(pair[0], pair[1]), pair[0].number))
    return [
        LoopCandidate(
            first_bar=first.number,
            last_bar=last.number,
            start=first.start,
            end=last.start + last.dur,
            source="repeat",
        )
        for first, last in pairs
        if _length(first, last) >= MIN_LOOP_BARS
    ]


def _from_sections(sections) -> list[LoopCandidate]:
    """Section k through the *last* section, k ascending.

    Suffixes rather than arbitrary spans: a loop ending before the piece does
    means the tail never plays again once the loop starts. And k=0 first, so
    the preferred answer is that the piece loops cleanly on itself — an intro
    appears only when the head is what breaks the seam, which is exactly when
    "intro" is the right word for it.
    """
    if not sections:
        return []
    last = sections[-1]
    return [
        LoopCandidate(
            first_bar=first.first_bar,
            last_bar=last.last_bar,
            start=first.start,
            end=last.end,
            source="section",
        )
        for first in sections
        if last.last_bar - first.first_bar + 1 >= MIN_LOOP_BARS
    ]


def _length(first: Bar, last: Bar) -> int:
    return last.number - first.number + 1
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_loop.py -v`
Expected: PASS, 18 tests. The last one is the load-bearing check — it asserts the exact candidate lists measured on the fixtures.

- [ ] **Step 5: Commit**

```bash
git add src/bitty/loop.py tests/test_loop.py
git commit -m "feat: propose loop candidates from repeat marks and sections"
```

---

### Task 4: the seam check

**Files:**
- Modify: `src/bitty/loop.py`
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `loop.LoopCandidate`, `arrangement.Arrangement`, `arrangement.Loop`, numpy.
- Produces: `loop.Choice(loop, candidate, ratio, severed, echo_tails)` with `.describe() -> str`; `loop.choose(candidates, audio, arrangement, sample_rate) -> Choice | None`; `loop.SEAM_RATIO = 1.0`.

- [ ] **Step 1: Write the failing tests**

Add these to the import block at the top of `tests/test_loop.py`:

```python
import numpy as np

from bitty.arrange import arrange
from bitty.arrangement import Arrangement, Channel, Echo, Event, Instrument, Loop
from bitty.synth import SAMPLE_RATE, render
```

Then append the tests:

```python


def pulse(seconds: float, hz: float = 100.0, amp: float = 0.5) -> np.ndarray:
    """A square wave: full-amplitude edges every half period, by design."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    wave = amp * np.sign(np.sin(2 * np.pi * hz * t))
    return np.stack([wave, wave], axis=1)


def bare(events=(), echo=None) -> Arrangement:
    return Arrangement(
        meta={},
        channels=(
            Channel(role="lead", instrument=Instrument(wave="pulse"),
                    events=tuple(events), echo=echo),
        ),
    )


def candidate(start: float, end: float, source: str = "section") -> loop.LoopCandidate:
    return loop.LoopCandidate(first_bar=1, last_bar=8, start=start, end=end, source=source)


def test_a_period_aligned_splice_passes_despite_full_amplitude_edges():
    """The test that would have caught an absolute threshold.

    A pulse wave steps between +A and -A every half period. That is ordinary
    signal, not a click, and a metric that cannot tell the difference would
    reject every loop in a square-wave piece.
    """
    audio = pulse(2.0, hz=100.0)  # 100 Hz: 0.5 s is a whole number of periods
    chosen = loop.choose((candidate(0.5, 1.5),), audio, bare(), SAMPLE_RATE)
    assert chosen is not None
    assert chosen.ratio < loop.SEAM_RATIO


def test_a_splice_larger_than_the_piece_ever_makes_is_rejected():
    audio = pulse(2.0, hz=100.0, amp=0.2)
    audio[SAMPLE_RATE // 2] = 1.0  # loop start lands on a sample the music never reaches
    assert loop.choose((candidate(0.5, 1.5),), audio, bare(), SAMPLE_RATE) is None


def test_choose_falls_through_a_failing_candidate_to_the_next():
    audio = pulse(3.0, hz=100.0, amp=0.2)
    audio[SAMPLE_RATE // 2] = 1.0
    chosen = loop.choose(
        (candidate(0.5, 1.5), candidate(1.0, 2.0)), audio, bare(), SAMPLE_RATE
    )
    assert chosen is not None
    assert chosen.candidate.start == 1.0


def test_choose_returns_nothing_when_every_candidate_fails():
    audio = pulse(2.0, hz=100.0, amp=0.2)
    audio[SAMPLE_RATE // 2] = 1.0
    assert loop.choose((candidate(0.5, 1.5),), audio, bare(), SAMPLE_RATE) is None


def test_no_candidates_at_all_is_not_a_loop():
    assert loop.choose((), pulse(1.0), bare(), SAMPLE_RATE) is None


def test_a_dry_note_sustaining_across_the_loop_end_severs_the_candidate():
    events = (Event(t=0.9, pitch=60, dur=0.5, vel=10),)  # ends at 1.4, past 1.0
    assert loop.choose((candidate(0.0, 1.0),), pulse(2.0), bare(events), SAMPLE_RATE) is None


def test_a_note_ending_exactly_at_the_loop_end_does_not_sever():
    """Float onsets; the comparison has to be epsilon-tolerant on this side.

    Written the other way, every final note counts as severed and no
    bar-aligned candidate ever passes.
    """
    events = (Event(t=0.5, pitch=60, dur=0.5, vel=10),)
    assert loop.choose((candidate(0.0, 1.0),), pulse(2.0), bare(events), SAMPLE_RATE) is not None


def test_the_same_pitch_sounding_at_the_loop_start_continues_rather_than_severs():
    events = (
        Event(t=0.9, pitch=60, dur=0.5, vel=10),
        Event(t=0.0, pitch=60, dur=0.4, vel=10),
    )
    chosen = loop.choose((candidate(0.0, 1.0),), pulse(2.0), bare(events), SAMPLE_RATE)
    assert chosen is not None


def test_an_echo_tail_crossing_the_loop_end_is_counted_but_never_rejects():
    """Measured: rejecting on this kills every candidate on two of three fixtures."""
    events = (Event(t=0.5, pitch=60, dur=0.5, vel=10),)  # dry ends at 1.0, echo at 1.38
    arrangement = bare(events, echo=Echo(delay_sec=0.38, level=0.35))
    chosen = loop.choose((candidate(0.0, 1.0),), pulse(2.0), arrangement, SAMPLE_RATE)
    assert chosen is not None
    assert chosen.echo_tails == 1
    assert "echo tail cut" in chosen.describe()


def test_a_manual_candidate_is_returned_even_when_both_tests_fail():
    audio = pulse(2.0, hz=100.0, amp=0.2)
    audio[SAMPLE_RATE // 2] = 1.0
    events = (Event(t=0.9, pitch=60, dur=0.5, vel=10),)
    chosen = loop.choose(
        (candidate(0.5, 1.5, source="manual"),), audio, bare(events), SAMPLE_RATE
    )
    assert chosen is not None
    assert chosen.loop == Loop(start_sec=0.5, end_sec=1.5)
    assert chosen.severed == 1  # measured and reported, not acted on


def test_describe_names_the_source_and_the_seam():
    audio = pulse(2.0, hz=100.0)
    chosen = loop.choose((candidate(0.5, 1.5, source="repeat"),), audio, bare(), SAMPLE_RATE)
    assert chosen.describe() == "repeat marks, seam ok"


def test_the_fixtures_pick_what_the_plan_measured():
    for path, expected in (
        (MINUET, (1, 8, "repeat marks, seam ok")),
        (RAGTIME, (1, 16, "repeat marks, seam ok, echo tail cut")),
        (CHORALE, (1, 8, "section boundaries, seam ok, echo tail cut")),
    ):
        score = ingest(path)
        arrangement = arrange(score)
        audio = render(arrangement)
        chosen = loop.choose(
            loop.candidates(score, analyze(score)), audio, arrangement, SAMPLE_RATE
        )
        assert chosen is not None, path.name
        assert (chosen.candidate.first_bar, chosen.candidate.last_bar, chosen.describe()) == expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_loop.py -v`
Expected: FAIL — `AttributeError: module 'bitty.loop' has no attribute 'choose'`

- [ ] **Step 3: Implement the seam check**

Append to `src/bitty/loop.py`, and add `import numpy as np` plus `from bitty.arrangement import Arrangement, Loop` to the imports:

```python
SEAM_RATIO = 1.0  # see the spec's calibration table: real candidates measure 0.02-0.38
ORDINARY_PERCENTILE = 99.9

SOURCE_WORDS = {
    "repeat": "repeat marks",
    "section": "section boundaries",
    "manual": "manual",
}


@dataclass(frozen=True)
class Choice:
    """The picked loop and the evidence for it, so the tool can say why."""

    loop: Loop
    candidate: LoopCandidate
    ratio: float  # splice step over what this piece ordinarily steps
    severed: int  # dry notes cut by the splice
    echo_tails: int  # echo tails cut; reported, never rejected

    def describe(self) -> str:
        parts = [SOURCE_WORDS.get(self.candidate.source, self.candidate.source)]
        if self.severed:
            parts.append(f"cuts {self.severed} notes")
        elif self.ratio > SEAM_RATIO:
            parts.append(f"seam ratio {self.ratio:.2f}, over {SEAM_RATIO:g}")
        else:
            parts.append("seam ok")
        if self.echo_tails:
            parts.append("echo tail cut")
        return ", ".join(parts)


def choose(
    candidates: tuple[LoopCandidate, ...],
    audio: np.ndarray,
    arrangement: Arrangement,
    sample_rate: int,
) -> Choice | None:
    """The first candidate whose seam holds, or None.

    Manual candidates return regardless: the person typed a bar number, and the
    tool reports what it thinks without overruling them.
    """
    if not candidates or len(audio) < 2:
        return None

    ordinary = float(np.percentile(np.abs(np.diff(audio, axis=0)), ORDINARY_PERCENTILE))
    for candidate in candidates:
        verdict = _measure(candidate, audio, arrangement, sample_rate, ordinary)
        if candidate.source == "manual" or (
            verdict.ratio <= SEAM_RATIO and not verdict.severed
        ):
            return verdict
    return None


def _measure(
    candidate: LoopCandidate,
    audio: np.ndarray,
    arrangement: Arrangement,
    sample_rate: int,
    ordinary: float,
) -> Choice:
    first = min(round(candidate.start * sample_rate), len(audio) - 1)
    last = min(round(candidate.end * sample_rate), len(audio))
    splice = float(np.max(np.abs(audio[first] - audio[last - 1])))
    severed, echo_tails = _crossings(arrangement, candidate)
    return Choice(
        loop=Loop(start_sec=candidate.start, end_sec=candidate.end),
        candidate=candidate,
        ratio=splice / ordinary if ordinary else 0.0,
        severed=severed,
        echo_tails=echo_tails,
    )


def _crossings(arrangement: Arrangement, candidate: LoopCandidate) -> tuple[int, int]:
    """Dry notes and echo tails cut by the splice, counted separately.

    Separately because only the first one rejects. Measured across the
    fixtures, the lead's final note echoes past the loop end on nearly every
    candidate there is — rejecting on that leaves two of three fixtures with no
    loop at all, which is the feature shipping dead.
    """
    severed = tails = 0
    for channel in arrangement.channels:
        delay = channel.echo.delay_sec if channel.echo else 0.0
        held = {
            event.pitch
            for event in channel.events
            if event.t <= candidate.start + EPSILON < event.t + event.dur - EPSILON
        }
        for event in channel.events:
            if event.t >= candidate.end - EPSILON or event.pitch in held:
                continue
            if event.t + event.dur > candidate.end + EPSILON:
                severed += 1
            elif delay and event.t + event.dur + delay > candidate.end + EPSILON:
                tails += 1
    return severed, tails
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_loop.py -v`
Expected: PASS, 30 tests. `test_the_fixtures_pick_what_the_plan_measured` is the one that matters most — it pins the whole cascade to the measured behaviour.

- [ ] **Step 5: Commit**

```bash
git add src/bitty/loop.py tests/test_loop.py
git commit -m "feat: verify a loop candidate's seam against the rendered audio"
```

---

### Task 5: `convert --bars` and `--loop-from`

**Files:**
- Modify: `src/bitty/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `loop.trim`, `loop.candidates`, `loop.choose`, `analyze`, `arrange`, `render`.
- Produces: `cli._bar_range(text) -> tuple[int, int]`; `_write_audio(audio, out_dir, stem, wav) -> Path` (now takes rendered audio, not an arrangement).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
RAGTIME = Path(__file__).parent / "fixtures" / "ragtime.mxl"


def loaded(tmp_path, stem):
    return Arrangement.from_json((tmp_path / f"{stem}.arrangement.json").read_text())


def test_convert_records_the_loop_it_found(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path)])
    arrangement = loaded(tmp_path, "minuet")
    assert arrangement.loop is not None
    assert (arrangement.loop.start_sec, arrangement.loop.end_sec) == (0.0, 12.0)


def test_convert_reports_the_pick_and_why(tmp_path):
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path)])
    assert "bars 1-8" in result.output
    assert "repeat marks, seam ok" in result.output


def test_a_score_too_short_to_loop_gets_no_loop_and_says_so(tmp_path):
    result = runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert loaded(tmp_path, "two_part").loop is None
    assert "no loop" in result.output.lower()


def test_bars_narrows_the_arrangement_to_the_printed_range(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--bars", "9-16"])
    arrangement = loaded(tmp_path, "minuet")
    assert arrangement.meta["bars"] == [9, 16]
    assert min(e.t for c in arrangement.channels for e in c.events) < 1.0  # rebased


def test_loop_from_overrides_the_cascade(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--loop-from", "9"])
    assert loaded(tmp_path, "minuet").loop.start_sec == 12.0


def test_loop_from_is_honoured_even_when_the_seam_is_poor(tmp_path):
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--loop-from", "16"])
    assert result.exit_code == 0, result.output
    assert loaded(tmp_path, "minuet").loop.start_sec == 22.5


def test_a_malformed_bar_range_is_rejected(tmp_path):
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--bars", "nine"])
    assert result.exit_code != 0
    assert "9-16" in result.output or "N-M" in result.output


def test_a_bar_range_outside_the_score_is_rejected(tmp_path):
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--bars", "40-50"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — `AssertionError` on `arrangement.loop is not None` (no flags exist yet).

- [ ] **Step 3: Wire the stage into `convert`**

In `src/bitty/cli.py`, add imports:

```python
from dataclasses import replace

from bitty import loop as loop_stage
```

Replace the `convert` command:

```python
@app.command()
def convert(
    score: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(Path("out"), "-o", "--out-dir"),
    wav: bool = typer.Option(False, "--wav", help="Write uncompressed WAV instead of Ogg."),
    bars: str = typer.Option(None, "--bars", help="Printed bar range to keep, e.g. 9-16."),
    loop_from: int = typer.Option(
        None, "--loop-from", help="Printed bar the loop starts at. Overrides the cascade."
    ),
) -> None:
    """Convert a score to audio and its arrangement JSON."""
    parsed = ingest(score)
    if bars:
        first, last = _bar_range(bars)
        try:
            parsed = loop_stage.trim(parsed, first, last)
        except ValueError as error:
            raise typer.BadParameter(str(error), param_hint="--bars") from error

    try:
        candidates = loop_stage.candidates(parsed, analyze(parsed), loop_from)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--loop-from") from error

    arrangement = arrange(parsed)
    audio = render_audio(arrangement)
    chosen = loop_stage.choose(candidates, audio, arrangement, SAMPLE_RATE)
    arrangement = replace(arrangement, loop=chosen.loop if chosen else None)

    _write_audio(audio, out_dir, score.stem, wav)
    _report(chosen)

    json_path = out_dir / f"{score.stem}{ARRANGEMENT_SUFFIX}"
    json_path.write_text(arrangement.to_json())
    typer.echo(f"{json_path}")


def _bar_range(text: str) -> tuple[int, int]:
    first, _, last = text.partition("-")
    try:
        return int(first), int(last)
    except ValueError as error:
        raise typer.BadParameter(
            f"expected a printed bar range like 9-16, got {text!r}", param_hint="--bars"
        ) from error


def _report(chosen) -> None:
    if chosen is None:
        typer.echo("  no loop found — try --loop-from BAR")
        return
    typer.echo(
        f"  loop: bars {chosen.candidate.first_bar}-{chosen.candidate.last_bar}"
        f"  ({chosen.describe()})"
    )
```

Change `_write_audio` to take rendered audio, since `convert` has already rendered it:

```python
def _write_audio(audio, out_dir: Path, stem: str, wav: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}{'.wav' if wav else '.ogg'}"

    if wav:
        sf.write(path, audio, SAMPLE_RATE)
    else:
        sf.write(path, audio, SAMPLE_RATE, format="OGG", subtype="VORBIS")

    typer.echo(f"{path}  ({len(audio) / SAMPLE_RATE:.1f}s)")
    return path
```

And update the `render` command's call site, which now renders for itself:

```python
    loaded = Arrangement.from_json(arrangement.read_text())
    _write_audio(render_audio(loaded), out_dir, _stem(arrangement), wav)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS. The goldens must be unchanged — `convert` writes the same audio it always did, plus a `loop` field the goldens already carry from Task 1.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/cli.py tests/test_cli.py
git commit -m "feat: choose and record a loop when converting"
```

---

### Task 6: `--split`

**Files:**
- Modify: `src/bitty/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Arrangement.loop`, `_write_audio`.
- Produces: `--split` on both `convert` and `render`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_split_writes_an_intro_and_a_loop(tmp_path):
    result = runner.invoke(
        app, ["convert", str(MINUET), "-o", str(tmp_path), "--wav", "--split", "--loop-from", "9"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "minuet_intro.wav").exists()
    assert (tmp_path / "minuet_loop.wav").exists()


def test_the_split_pieces_have_the_durations_the_loop_names(tmp_path):
    runner.invoke(
        app, ["convert", str(MINUET), "-o", str(tmp_path), "--wav", "--split", "--loop-from", "9"]
    )
    intro, _ = sf.read(tmp_path / "minuet_intro.wav")
    body, _ = sf.read(tmp_path / "minuet_loop.wav")
    assert abs(len(intro) / 44100 - 12.0) < 0.01
    assert abs(len(body) / 44100 - 12.0) < 0.01


def test_a_loop_starting_at_zero_writes_no_intro(tmp_path):
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--wav", "--split"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "minuet_intro.wav").exists()
    assert (tmp_path / "minuet_loop.wav").exists()
    assert "no intro" in result.output.lower()


def test_split_without_a_loop_is_a_hard_error(tmp_path):
    """Asking for a split is asking for a loop. A warning here gets missed."""
    result = runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path), "--split"])
    assert result.exit_code == 1
    assert "--loop-from" in result.output


def test_render_can_split_a_hand_edited_arrangement(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--loop-from", "9"])
    result = runner.invoke(
        app,
        ["render", str(tmp_path / "minuet.arrangement.json"), "-o", str(tmp_path),
         "--wav", "--split"],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "minuet_loop.wav").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — `No such option: --split`

- [ ] **Step 3: Implement the split**

In `src/bitty/cli.py`, add the helper:

```python
def _write_split(audio, arrangement: Arrangement, out_dir: Path, stem: str, wav: bool) -> None:
    """Write the intro and loop as separate files.

    A hard error without a loop: asking for a split is asking for a loop, and
    quietly writing one file instead is the kind of thing a build script misses.

    Audio past the loop end is dropped. With the suffix candidates the cascade
    prefers that is nothing; a repeat span in the middle of a piece leaves a
    tail that survives in the single file and not here.
    """
    if arrangement.loop is None:
        typer.echo("  --split needs a loop and none was found — try --loop-from BAR", err=True)
        raise typer.Exit(1)

    first = round(arrangement.loop.start_sec * SAMPLE_RATE)
    last = min(round(arrangement.loop.end_sec * SAMPLE_RATE), len(audio))

    if first > 0:
        _write_audio(audio[:first], out_dir, f"{stem}_intro", wav)
    else:
        typer.echo("  loop starts at 0:00 — no intro to write")
    _write_audio(audio[first:last], out_dir, f"{stem}_loop", wav)
```

Add `split: bool = typer.Option(False, "--split", help="Also write STEM_intro and STEM_loop.")` to both commands. In `convert`, after `_report(chosen)`:

```python
    if split:
        _write_split(audio, arrangement, out_dir, score.stem, wav)
```

In `render`:

```python
    loaded = Arrangement.from_json(arrangement.read_text())
    audio = render_audio(loaded)
    _write_audio(audio, out_dir, _stem(arrangement), wav)
    if split:
        _write_split(audio, loaded, out_dir, _stem(arrangement), wav)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bitty/cli.py tests/test_cli.py
git commit -m "feat: split a converted score into intro and loop files"
```

---

### Task 7: the auto-loop line on `bitty sections`

**Files:**
- Modify: `src/bitty/cli.py:26-48`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `loop.candidates`, `loop.choose`, `arrange`, `render`.
- Produces: nothing downstream.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_sections_prints_the_auto_loop_pick():
    result = runner.invoke(app, ["sections", str(MINUET)])
    assert result.exit_code == 0, result.output
    assert "auto-loop pick: bars 1-8" in result.output
    assert "repeat marks, seam ok" in result.output


def test_the_printed_pick_is_the_one_convert_would_write(tmp_path):
    """Rendering makes the report slow. It is worth it only if it is true."""
    printed = runner.invoke(app, ["sections", str(RAGTIME)]).output
    converted = runner.invoke(app, ["convert", str(RAGTIME), "-o", str(tmp_path)]).output
    assert "auto-loop pick: bars 1-16" in printed
    assert "loop: bars 1-16" in converted
    written = loaded(tmp_path, "ragtime").loop
    assert (written.start_sec, round(written.end_sec, 2)) == (0.0, 19.2)


def test_sections_says_so_when_nothing_can_loop():
    result = runner.invoke(app, ["sections", str(FIXTURE)])
    assert "no loop" in result.output.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — `assert "auto-loop pick: bars 1-8" in result.output`

- [ ] **Step 3: Add the line**

In `src/bitty/cli.py`, at the end of the `sections` command body:

```python
    arrangement = arrange(parsed)
    chosen = loop_stage.choose(
        loop_stage.candidates(parsed, found),
        render_audio(arrangement),
        arrangement,
        SAMPLE_RATE,
    )
    typer.echo("")
    if chosen is None:
        typer.echo("  no loop found — try convert --loop-from BAR")
    else:
        typer.echo(
            f"  auto-loop pick: bars {chosen.candidate.first_bar}-{chosen.candidate.last_bar}"
            f"  ({chosen.describe()})"
        )
```

Rendering costs ~0.1 s on the fixtures against ingest's 0.02 s. A printed pick that disagrees with what `convert` chooses is a worse failure than a slow report.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS. The minuet report reads:

```
minuet  ·  q=120  ·  16 bars  ·  24.0s

  A   bars   1-8    3/4   G major    0:00.0    12.0s   repeat
  B   bars   9-16   3/4   D major    0:12.0    12.0s   repeat

  auto-loop pick: bars 1-8  (repeat marks, seam ok)
```

- [ ] **Step 5: Commit**

```bash
git add src/bitty/cli.py tests/test_cli.py
git commit -m "feat: print the auto-loop pick in bitty sections"
```

---

### Task 8: documentation and the audition

**Files:**
- Modify: `README.md`
- Test: the full suite, then your ears

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS, roughly 210 tests (164 after Task 1, plus 30 in test_loop.py and 16 in test_cli.py), zero failures. Confirm the goldens are unchanged since Task 1.

- [ ] **Step 2: Update the README**

Add to the CLI section:

| Flag | Effect |
|---|---|
| `--bars N-M` | Keep only printed bars N through M. Times rebase to zero; bar numbers do not. |
| `--loop-from N` | Start the loop at printed bar N. Overrides the cascade, seam check included. |
| `--split` | Also write `STEM_intro` and `STEM_loop`. Errors if no loop was found. |

Add a "Looping" section covering: the cascade order (repeat marks longest-first, then section suffixes, then nothing); that a candidate is rejected when its splice step exceeds what the piece ordinarily steps or when it severs a dry note; that the final note's echo is cut by every loop and is reported rather than rejected; and that `arrangement.json` carries `loop` as two seconds values.

Update the Status section: Phase 4 is done; Phase 5 picks up targets and config.

- [ ] **Step 3: Build the audition**

```bash
.venv/bin/python -c "
import numpy as np, soundfile as sf
from pathlib import Path
audio, sr = sf.read('out/minuet_loop.wav')
sf.write('out/minuet_audition.wav', np.concatenate([audio] * 3), sr)
print('out/minuet_audition.wav')
"
```

First run `.venv/bin/bitty convert tests/fixtures/minuet.mxl --wav --split -o out`. WAV only — Ogg renders as static through `aplay`.

- [ ] **Step 4: Listen**

```bash
aplay out/minuet_audition.wav
```

Three passes of the loop back to back. What to listen for at each seam: a click or thump, a note cut off mid-phrase, and the echo of the final note going missing as the loop restarts — the last one is known, measured at −11 to −14 dB, and is the open question this phase deliberately left. Do the same for ragtime and chorale.

If the missing echo is audible enough to bother you, that is the evidence for implementing tail-wrapping. Do not implement it in this phase.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document loop selection and the split output"
```
