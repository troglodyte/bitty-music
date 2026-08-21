# Phase 4a — Structure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read the structure the composer wrote — bar numbers, repeat marks, barlines, signature changes — and report it as a table a person can read to choose a section.

**Architecture:** `ingest` gains a bar timeline on `Score`, carrying notation facts only. A new `analyze.py` turns that timeline into `Section`s by a rule whose every clause names a mark in the score, and labels each with a detected key. `cli` prints them. Nothing downstream of `Score` changes, so the golden arrangements stay byte-identical — that is the regression check for this whole phase.

**Tech Stack:** Python 3.11+, music21 10.5, numpy, pytest. Run tests with `.venv/bin/pytest`.

**Spec:** `docs/superpowers/specs/2026-08-21-phase-4a-structure-design.md`

## Global Constraints

- **Notation only.** Section boundaries come from marks in the score and nothing else. No texture heuristics, no similarity, no tunable thresholds. Every boundary must be justifiable by pointing at notation.
- **Section names are positional.** `A`, `B`, `C` mean first, second, third. Never emit `A'` — notation-only evidence cannot support a similarity claim.
- **Key detection is the one analysed step**, and it affects only a section's *label*. It never moves a boundary.
- **Krumhansl-Schmuckler comes from music21.** Do not hand-roll key detection; the parent spec lists it among the things deliberately not reimplemented.
- **Bar numbers are as printed.** Whatever music21 reports. Never renumber — 4b's `--bars` refers to these same numbers.
- **No tempo map this phase.** `Score.bpm` stays a single value and bar times derive from it.
- **`Note` is not modified.** A note's bar is recoverable from its start time.
- **The goldens must not move.** `tests/goldens/*.arrangement.json` stay byte-identical, and all 128 existing tests keep passing with no assertion altered. A golden diff means the ingest change disturbed note timing — that is a failure to investigate, not something to regenerate.
- **Out of scope:** the loop cascade, `--bars` / `--loop-from`, the intro/loop split, the arrangement's `loop` field, `--json` output. All 4b.
- Source layout is `src/bitty/`, tests in `tests/`.

### Verified facts this plan is built on

Confirmed against music21 before the plan was written. Do not re-derive.

| Fact | Value |
|---|---|
| Fixture tempos | chorale 120 (no mark, default), minuet 120 (no mark, default), ragtime 100 |
| Fixture titles | `"chorale"`, `"minuet"`, `"ragtime"` — no metadata title, so ingest falls back to the filename |
| Bar durations | chorale 4/4 → 2.0 s; minuet 3/4 → 1.5 s; ragtime 2/4 → 1.2 s |
| Total durations | chorale 16.0 s; minuet 24.0 s; ragtime 19.2 s |
| Minuet marks | bar 8 `rightBarline` is `Repeat direction=end`, `.type == "final"`; bar 9 `leftBarline` is `Repeat direction=start`, `.type == "heavy-light"` |
| Ragtime marks | bar 1 `leftBarline` is `Repeat direction=start`; bar 16 `rightBarline` is `Repeat direction=end` |
| Chorale marks | none — every `leftBarline` and `rightBarline` is `None` |
| Signature carry-forward | `measure.timeSignature` and `measure.keySignature` are `None` on every measure after the one that states them. **Both must carry forward.** |
| Key detection | rebuilt-stream detection matches the parsed score exactly: minuet 1–8 `G major`, minuet 9–16 `D major`, chorale `f# minor`, ragtime `A- major` |

Note the music21 spelling `A- major` — a hyphen, not `♭`. Assert that string.

**Reading a flattened score is misleading here.** It reports barlines duplicated once per part, at offsets that do not identify a bar. Always read `measure.leftBarline` / `measure.rightBarline` off `part.getElementsByClass(stream.Measure)`.

## File Structure

| File | Responsibility |
|------|----------------|
| `src/bitty/model.py` | **Modify** — add `Bar`; `Score` gains `bars` |
| `src/bitty/ingest.py` | **Modify** — build the bar timeline from measures |
| `src/bitty/analyze.py` | **Create** — `Section`, the boundary rule, key detection |
| `src/bitty/cli.py` | **Modify** — the `sections` command |
| `tests/test_ingest.py` | **Modify** — the bar timeline against real scores |
| `tests/test_analyze.py` | **Create** — synthetic boundary cases, then the three fixtures |
| `tests/test_cli.py` | **Modify** — `bitty sections` runs and prints rows |
| `README.md` | **Modify** — document the command; update Status |

`Score.bars` **must** default to `()`. `tests/test_arrange.py:25` constructs `Score` without it, and that test may not be modified.

---

### Task 1: The bar timeline

Times in seconds, numbers as printed. No notation marks yet — Task 2 adds those.

**Files:**
- Modify: `src/bitty/model.py`
- Modify: `src/bitty/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `model.Bar(number: int, start: float, dur: float, time_signature: tuple[int, int], sharps: int)`, and `Score.bars: tuple[Bar, ...] = ()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ingest.py`. The file already defines `MINUET`; add the two other fixture paths beside it:

```python
CHORALE = Path(__file__).parent / "fixtures" / "chorale.mxl"
RAGTIME = Path(__file__).parent / "fixtures" / "ragtime.mxl"
```

```python
def test_ingest_builds_a_bar_timeline():
    score = ingest(MINUET)
    assert len(score.bars) == 16
    assert [b.number for b in score.bars[:3]] == [1, 2, 3]


def test_bar_times_follow_the_tempo():
    """Minuet is 3/4 with no tempo mark, so 120 bpm: three quarters = 1.5 s."""
    score = ingest(MINUET)
    assert score.bars[0].start == 0.0
    assert score.bars[0].dur == 1.5
    assert score.bars[1].start == 1.5
    assert score.bars[-1].start == pytest.approx(22.5)


def test_bars_carry_the_signatures_forward():
    """A score states its signatures once; every later bar still has them."""
    score = ingest(MINUET)
    assert all(b.time_signature == (3, 4) for b in score.bars)
    assert all(b.sharps == 1 for b in score.bars)


def test_bar_durations_track_the_meter():
    assert ingest(CHORALE).bars[0].dur == 2.0    # 4/4 at 120
    assert ingest(RAGTIME).bars[0].dur == 1.2    # 2/4 at 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ingest.py -k bar -v`
Expected: FAIL — `AttributeError: 'Score' object has no attribute 'bars'`

- [ ] **Step 3: Add `Bar` to the model**

In `src/bitty/model.py`, above `Score`:

```python
@dataclass(frozen=True)
class Bar:
    """One measure as the score prints it, with times resolved to seconds."""

    number: int  # as printed in the score, not renumbered
    start: float  # seconds from the start of the score
    dur: float  # seconds
    time_signature: tuple[int, int]
    sharps: int  # key signature, -7..7
```

Then give `Score` the field. It must have a default — existing callers construct `Score` without it:

```python
@dataclass(frozen=True)
class Score:
    notes: tuple[Note, ...]
    bpm: float
    time_signature: tuple[int, int]
    title: str
    bars: tuple[Bar, ...] = ()
```

- [ ] **Step 4: Build the timeline in ingest**

In `src/bitty/ingest.py`, add `stream` to the music21 import and `Bar` to the model import:

```python
from music21 import chord, converter, dynamics, expressions, key, meter, note, stream, tempo

from bitty.model import Bar, Note, Score
```

Add the builder:

```python
def _bars(parsed, seconds_per_quarter: float) -> tuple[Bar, ...]:
    """The bar timeline, read from the first part.

    A score states a time or key signature once, on the measure where it
    changes, so both carry forward. Reading measures rather than a flattened
    score matters: flattening reports each signature once per part, at
    offsets that do not identify a bar.
    """
    if not parsed.parts:
        return ()

    time_signature = (4, 4)
    sharps = 0
    bars: list[Bar] = []
    for measure in parsed.parts[0].getElementsByClass(stream.Measure):
        if measure.timeSignature is not None:
            time_signature = (
                int(measure.timeSignature.numerator),
                int(measure.timeSignature.denominator),
            )
        if measure.keySignature is not None:
            sharps = int(measure.keySignature.sharps)
        bars.append(
            Bar(
                number=int(measure.number),
                start=float(measure.offset) * seconds_per_quarter,
                dur=float(measure.quarterLength) * seconds_per_quarter,
                time_signature=time_signature,
                sharps=sharps,
            )
        )
    return tuple(bars)
```

Then pass it in the existing `return Score(...)` at the end of `ingest`:

```python
    return Score(
        notes=tuple(notes),
        bpm=bpm,
        time_signature=_first_time_signature(parsed),
        title=_title_of(parsed, path),
        bars=_bars(parsed, seconds_per_quarter),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ingest.py -k bar -v`
Expected: PASS, 4 tests.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest`
Expected: 132 passed. The goldens must be untouched — confirm with `git diff --stat tests/goldens/` printing nothing.

- [ ] **Step 7: Commit**

```bash
git add src/bitty/model.py src/bitty/ingest.py tests/test_ingest.py
git commit -m "feat: record the score's bar timeline at ingest"
```

---

### Task 2: Repeat marks and barlines

**Files:**
- Modify: `src/bitty/model.py`
- Modify: `src/bitty/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `model.Bar` from Task 1.
- Produces: `Bar.starts_repeat: bool`, `Bar.ends_repeat: bool`, `Bar.ends_span: bool`, all defaulting to `False`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ingest.py`:

```python
def test_bars_record_the_repeat_marks():
    bars = {b.number: b for b in ingest(MINUET).bars}
    assert bars[8].ends_repeat
    assert bars[9].starts_repeat
    assert not bars[1].starts_repeat


def test_an_end_repeat_also_reads_as_a_span_end():
    """music21 gives an end repeat the barline type "final"; both flags set."""
    assert {b.number: b for b in ingest(MINUET).bars}[8].ends_span


def test_ragtime_repeats_bracket_the_whole_strain():
    bars = {b.number: b for b in ingest(RAGTIME).bars}
    assert bars[1].starts_repeat
    assert bars[16].ends_repeat


def test_a_score_without_repeat_marks_has_none():
    assert not any(b.starts_repeat or b.ends_repeat for b in ingest(CHORALE).bars)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ingest.py -k repeat -v`
Expected: FAIL — `AttributeError: 'Bar' object has no attribute 'ends_repeat'`

- [ ] **Step 3: Add the fields**

In `src/bitty/model.py`, append to `Bar`:

```python
    starts_repeat: bool = False  # left barline is a start repeat
    ends_repeat: bool = False  # right barline is an end repeat
    ends_span: bool = False  # right barline is final or double
```

- [ ] **Step 4: Populate them in ingest**

Add `bar` to the music21 import in `src/bitty/ingest.py`:

```python
from music21 import bar, chord, converter, dynamics, expressions, key, meter, note, stream, tempo
```

Add the constant beside the other module constants at the top:

```python
SPAN_BARLINES = frozenset({"final", "double", "light-light"})
```

Add the two readers:

```python
def _is_repeat(barline, direction: str) -> bool:
    return isinstance(barline, bar.Repeat) and barline.direction == direction


def _ends_span(barline) -> bool:
    """A final or double bar closes a span.

    A repeat barline carries an ordinary type as well — an end repeat's is
    "final" — so a bar can both end a repeat and end a span. That overlap is
    harmless: the two boundary rules collapse to one boundary.
    """
    return barline is not None and barline.type in SPAN_BARLINES
```

In `_bars`, extend the `Bar(...)` construction with the three flags:

```python
                starts_repeat=_is_repeat(measure.leftBarline, "start"),
                ends_repeat=_is_repeat(measure.rightBarline, "end"),
                ends_span=_ends_span(measure.rightBarline),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ingest.py -k "repeat or span" -v`
Expected: PASS, 4 tests.

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv/bin/pytest`
Expected: 136 passed, goldens untouched.

```bash
git add src/bitty/model.py src/bitty/ingest.py tests/test_ingest.py
git commit -m "feat: read repeat marks and barlines onto the bar timeline"
```

---

### Task 3: Key detection

A pure function of our own `Score`, using music21 only as the K-S implementation.

**Files:**
- Create: `src/bitty/analyze.py`
- Test: `tests/test_analyze.py` (create)

**Interfaces:**
- Consumes: `Score` with `bars` from Tasks 1–2.
- Produces: `analyze._key_of(score: Score, start: float, end: float) -> str`, and the constant `analyze.UNKNOWN_KEY == "unknown"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_analyze.py`:

```python
from pathlib import Path

from bitty.analyze import UNKNOWN_KEY, _key_of
from bitty.ingest import ingest

CHORALE = Path(__file__).parent / "fixtures" / "chorale.mxl"
MINUET = Path(__file__).parent / "fixtures" / "minuet.mxl"
RAGTIME = Path(__file__).parent / "fixtures" / "ragtime.mxl"


def test_detects_each_half_of_the_minuet_separately():
    """A minuet modulates to the dominant; detection has to see both halves."""
    score = ingest(MINUET)
    assert _key_of(score, 0.0, 12.0) == "G major"
    assert _key_of(score, 12.0, 24.0) == "D major"


def test_detects_the_key_of_a_whole_score():
    assert _key_of(ingest(CHORALE), 0.0, 16.0) == "f# minor"
    assert _key_of(ingest(RAGTIME), 0.0, 19.2) == "A- major"


def test_a_window_with_no_notes_has_no_key():
    assert _key_of(ingest(CHORALE), 100.0, 200.0) == UNKNOWN_KEY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_analyze.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bitty.analyze'`

- [ ] **Step 3: Implement**

Create `src/bitty/analyze.py`:

```python
"""What the score's own marks say about its structure.

Boundaries come only from notation — repeat marks, barlines, and signature
changes — so every one can be justified by pointing at the score. Key
labelling is the single analysed step here, and it never moves a boundary.
"""

from music21 import note as m21note
from music21 import stream

from bitty.model import Score

UNKNOWN_KEY = "unknown"
MIN_QUARTER_LENGTH = 1 / 32  # a grace note still has to occupy something


def _key_of(score: Score, start: float, end: float) -> str:
    """The detected key of the notes *beginning* in [start, end).

    Krumhansl-Schmuckler via music21, run on a scratch stream rebuilt from our
    own notes. K-S correlates a duration-weighted pitch-class histogram against
    24 profiles, so a rebuilt stream gives the same answer as the parsed score
    — verified on every fixture.

    A note counts toward the section it begins in, so one held across a
    boundary cannot colour a section it never articulated in.
    """
    seconds_per_quarter = 60.0 / score.bpm
    sounding = [n for n in score.notes if start - 1e-9 <= n.start < end - 1e-9]
    if not sounding:
        return UNKNOWN_KEY

    scratch = stream.Stream()
    for source in sounding:
        element = m21note.Note(source.pitch)
        element.quarterLength = max(source.dur / seconds_per_quarter, MIN_QUARTER_LENGTH)
        scratch.insert(source.start / seconds_per_quarter, element)
    return str(scratch.analyze("key"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_analyze.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/bin/pytest`
Expected: 139 passed.

```bash
git add src/bitty/analyze.py tests/test_analyze.py
git commit -m "feat: detect a section's key from its own notes"
```

---

### Task 4: The boundary rule

**Files:**
- Modify: `src/bitty/analyze.py`
- Test: `tests/test_analyze.py`

**Interfaces:**
- Consumes: `_key_of`, `UNKNOWN_KEY` from Task 3; `model.Bar`, `Score.bars` from Tasks 1–2.
- Produces: `analyze.Section(name: str, first_bar: int, last_bar: int, start: float, end: float, key: str, time_signature: tuple[int, int], repeats: bool)` and `analyze.analyze(score: Score) -> tuple[Section, ...]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_analyze.py`. Extend the imports first:

```python
from bitty.analyze import UNKNOWN_KEY, _key_of, analyze
from bitty.model import Bar, Score
```

The synthetic helpers — `analyze` consumes our own dataclasses, so these
boundary cases need no score file at all, which is what makes it practical to
cover the two predicates no fixture exercises:

```python
def timeline(count: int, **marks) -> tuple[Bar, ...]:
    """`count` one-second bars numbered from 1, with marks by bar number.

    timeline(4, ends_repeat={2}) puts an end repeat on bar 2.
    timeline(4, sharps={3: 2, 4: 2}) changes key at bar 3.
    """
    return tuple(
        Bar(
            number=n,
            start=float(n - 1),
            dur=1.0,
            time_signature=marks.get("time_signature", {}).get(n, (4, 4)),
            sharps=marks.get("sharps", {}).get(n, 0),
            starts_repeat=n in marks.get("starts_repeat", set()),
            ends_repeat=n in marks.get("ends_repeat", set()),
            ends_span=n in marks.get("ends_span", set()),
        )
        for n in range(1, count + 1)
    )


def synthetic(bars: tuple[Bar, ...]) -> Score:
    return Score(
        notes=(), bpm=60.0, time_signature=(4, 4), title="synthetic", bars=bars
    )


def ranges(sections) -> list[tuple[int, int]]:
    return [(s.first_bar, s.last_bar) for s in sections]
```

One test per clause of the rule:

```python
def test_a_score_with_no_marks_is_one_section():
    sections = analyze(synthetic(timeline(4)))
    assert ranges(sections) == [(1, 4)]


def test_a_start_repeat_opens_a_section():
    assert ranges(analyze(synthetic(timeline(4, starts_repeat={3})))) == [(1, 2), (3, 4)]


def test_an_end_repeat_closes_a_section():
    assert ranges(analyze(synthetic(timeline(4, ends_repeat={2})))) == [(1, 2), (3, 4)]


def test_a_final_barline_closes_a_section():
    assert ranges(analyze(synthetic(timeline(4, ends_span={2})))) == [(1, 2), (3, 4)]


def test_a_time_signature_change_opens_a_section():
    bars = timeline(4, time_signature={3: (3, 4), 4: (3, 4)})
    assert ranges(analyze(synthetic(bars))) == [(1, 2), (3, 4)]


def test_a_key_change_opens_a_section():
    bars = timeline(4, sharps={3: 2, 4: 2})
    assert ranges(analyze(synthetic(bars))) == [(1, 2), (3, 4)]


def test_marks_landing_together_open_one_section_not_two():
    """A minuet's bar 8 ends a repeat with a final barline, and bar 9 starts one."""
    bars = timeline(4, ends_repeat={2}, ends_span={2}, starts_repeat={3})
    assert ranges(analyze(synthetic(bars))) == [(1, 2), (3, 4)]


def test_sections_are_named_by_position():
    sections = analyze(synthetic(timeline(3, ends_repeat={1, 2})))
    assert [s.name for s in sections] == ["A", "B", "C"]


def test_names_continue_past_z():
    """Not expected in real music; specified so the behaviour is not accidental."""
    bars = timeline(30, ends_repeat=set(range(1, 30)))
    names = [s.name for s in analyze(synthetic(bars))]
    assert names[:2] == ["A", "B"]
    assert names[25:28] == ["Z", "AA", "AB"]


def test_a_section_repeats_when_either_end_says_so():
    first, second = analyze(synthetic(timeline(4, ends_repeat={2})))
    assert first.repeats
    assert not second.repeats


def test_sections_span_their_bars_in_seconds():
    first, second = analyze(synthetic(timeline(4, ends_repeat={2})))
    assert (first.start, first.end) == (0.0, 2.0)
    assert (second.start, second.end) == (2.0, 4.0)


def test_a_section_with_no_notes_has_no_key():
    assert analyze(synthetic(timeline(2)))[0].key == UNKNOWN_KEY


def test_a_score_with_no_bars_has_no_sections():
    assert analyze(Score(notes=(), bpm=120.0, time_signature=(4, 4), title="")) == ()
```

Then the three real scores, end to end:

```python
def summary(sections):
    return [(s.name, s.first_bar, s.last_bar, s.key, s.repeats) for s in sections]


def test_the_minuet_is_two_repeated_halves():
    assert summary(analyze(ingest(MINUET))) == [
        ("A", 1, 8, "G major", True),
        ("B", 9, 16, "D major", True),
    ]


def test_the_ragtime_is_one_repeated_strain():
    assert summary(analyze(ingest(RAGTIME))) == [("A", 1, 16, "A- major", True)]


def test_the_chorale_has_no_interior_structure():
    """A hymn of eight bars has nothing to divide; one section is the truth."""
    assert summary(analyze(ingest(CHORALE))) == [("A", 1, 8, "f# minor", False)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_analyze.py -v`
Expected: FAIL — `ImportError: cannot import name 'analyze' from 'bitty.analyze'`

- [ ] **Step 3: Implement**

In `src/bitty/analyze.py`, extend the imports:

```python
from dataclasses import dataclass

from music21 import note as m21note
from music21 import stream

from bitty.model import Bar, Score
```

Add the dataclass above `_key_of`:

```python
@dataclass(frozen=True)
class Section:
    """A span of bars the notation marks off, and what it sounds like.

    `name` is positional — "A", "B", "C" mean first, second, third. It is not
    a similarity claim: notation alone cannot say that a later section is a
    variant of an earlier one, so there is no "A'" here.
    """

    name: str
    first_bar: int  # printed numbers, inclusive
    last_bar: int
    start: float  # seconds
    end: float
    key: str
    time_signature: tuple[int, int]
    repeats: bool
```

Add the rule and its helpers below `_key_of`:

```python
def analyze(score: Score) -> tuple[Section, ...]:
    """Group the bar timeline into the sections its marks describe."""
    if not score.bars:
        return ()
    return tuple(
        _section(_name(index), group, score)
        for index, group in enumerate(_group(score.bars))
    )


def _group(bars: tuple[Bar, ...]) -> list[list[Bar]]:
    groups = [[bars[0]]]
    for previous, current in zip(bars, bars[1:]):
        if _opens_section(previous, current):
            groups.append([current])
        else:
            groups[-1].append(current)
    return groups


def _opens_section(previous: Bar, current: Bar) -> bool:
    """Whether a section starts at `current`. Every clause names a mark.

    Several clauses firing at the same bar produce one boundary, not several:
    an end repeat written as a final barline sets two of them at once.
    """
    return (
        current.starts_repeat
        or previous.ends_repeat
        or previous.ends_span
        or current.time_signature != previous.time_signature
        or current.sharps != previous.sharps
    )


def _section(name: str, group: list[Bar], score: Score) -> Section:
    start = group[0].start
    end = group[-1].start + group[-1].dur
    return Section(
        name=name,
        first_bar=group[0].number,
        last_bar=group[-1].number,
        start=start,
        end=end,
        key=_key_of(score, start, end),
        time_signature=group[0].time_signature,
        repeats=group[0].starts_repeat or group[-1].ends_repeat,
    )


def _name(index: int) -> str:
    """A, B, ... Z, AA, AB. Positional names, not similarity claims."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_analyze.py -v`
Expected: PASS, 19 tests.

If `test_the_minuet_is_two_repeated_halves` fails on the key strings, do **not**
adjust the expected values — they were verified against the parsed score. A
mismatch means the section time ranges are wrong, so check `_section`'s
`start`/`end` before anything else.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/bin/pytest`
Expected: 155 passed, goldens untouched.

```bash
git add src/bitty/analyze.py tests/test_analyze.py
git commit -m "feat: group bars into the sections the notation marks off"
```

---

### Task 5: `bitty sections`

**Files:**
- Modify: `src/bitty/cli.py`
- Modify: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `analyze.analyze`, `analyze.Section` from Task 4; `ingest.ingest`.
- Produces: the `sections` CLI command. Nothing else consumes it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`. The file already defines `FIXTURE` and `runner`; add:

```python
CHORALE = Path(__file__).parent / "fixtures" / "chorale.mxl"
MINUET = Path(__file__).parent / "fixtures" / "minuet.mxl"
```

```python
def test_sections_reports_the_two_halves_of_the_minuet():
    result = runner.invoke(app, ["sections", str(MINUET)])
    assert result.exit_code == 0, result.output
    assert "bars   1-8" in result.output
    assert "bars   9-16" in result.output
    assert "G major" in result.output
    assert "D major" in result.output
    assert result.output.count("repeat") == 2


def test_sections_header_carries_the_tempo_and_length():
    result = runner.invoke(app, ["sections", str(MINUET)])
    assert "q=120" in result.output
    assert "16 bars" in result.output
    assert "24.0s" in result.output


def test_sections_reports_an_unmarked_score_as_one_section():
    """A hymn with no repeat marks has no interior structure to find."""
    result = runner.invoke(app, ["sections", str(CHORALE)])
    assert result.exit_code == 0, result.output
    assert "bars   1-8" in result.output
    assert "repeat" not in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -k sections -v`
Expected: FAIL — exit code 2, `No such command 'sections'`

- [ ] **Step 3: Implement**

In `src/bitty/cli.py`, add the import beside the existing ones:

```python
from bitty.analyze import analyze
```

Add the command (put it above `convert`, since reading a score precedes converting it):

```python
@app.command()
def sections(
    score: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    """Print the structure the score's own marks describe."""
    parsed = ingest(score)
    found = analyze(parsed)
    total = found[-1].end if found else 0.0

    typer.echo(
        f"\n{parsed.title}  ·  q={parsed.bpm:g}"
        f"  ·  {len(parsed.bars)} bars  ·  {total:.1f}s\n"
    )
    for section in found:
        meter = f"{section.time_signature[0]}/{section.time_signature[1]}"
        typer.echo(
            f"  {section.name:<3} "
            f"bars {section.first_bar:>3}-{section.last_bar:<4} "
            f"{meter:<5} {section.key:<10} "
            f"{_clock(section.start)}   {section.end - section.start:>5.1f}s"
            f"{'   repeat' if section.repeats else ''}"
        )


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -k sections -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Look at the output**

Run: `.venv/bin/bitty sections tests/fixtures/minuet.mxl`

Expected, and read it rather than glancing at it — this command exists to be
read by a person:

```
minuet  ·  q=120  ·  16 bars  ·  24.0s

  A   bars   1-8    3/4   G major     0:00.0    12.0s   repeat
  B   bars   9-16   3/4   D major     0:12.0    12.0s   repeat
```

Also run it on the other two, and confirm the chorale reports a single
eight-bar section — that is correct under notation-only rules, not a bug:

```bash
.venv/bin/bitty sections tests/fixtures/chorale.mxl
.venv/bin/bitty sections tests/fixtures/ragtime.mxl
```

- [ ] **Step 6: Document it**

In `README.md`, add a subsection under `## Commands`, before `### bitty convert`:

````markdown
### `bitty sections` — what's in the score

```bash
bitty sections score.mxl
```

Prints the structure the score's own marks describe, so you can see what
there is before choosing any of it:

```
minuet  ·  q=120  ·  16 bars  ·  24.0s

  A   bars   1-8    3/4   G major     0:00.0    12.0s   repeat
  B   bars   9-16   3/4   D major     0:12.0    12.0s   repeat
```

Boundaries come only from notation — repeat marks, final and double bars,
and key or time signature changes — so every one can be traced to something
a composer wrote. A piece with none of those marks reports as one section,
which for an eight-bar hymn is the honest answer rather than a failure.

Section names are positional. `A` and `B` mean first and second, not "these
two are related" — telling repeated material apart needs analysis this
command deliberately does not do.

The key is detected, not read off the key signature, which is how the minuet
above shows its second half modulating to the dominant.
````

Then replace the `## Status` section's first paragraph with:

```markdown
Phases 1–4a are done: ingest, synthesis, the reduction, articulation, and
structural analysis. Phase 4b picks up looping — the loop cascade, `--bars`
and `--loop-from`, and the intro/loop split.
```

- [ ] **Step 7: Run the full suite and confirm nothing downstream moved**

Run: `.venv/bin/pytest`
Expected: 158 passed.

```bash
git diff --stat tests/goldens/
```

Expected: no output. The goldens are the check that a phase which only *reads*
the score changed nothing about how it *sounds*. If they moved, stop and find
out why rather than regenerating them.

- [ ] **Step 8: Commit**

```bash
git add src/bitty/cli.py tests/test_cli.py README.md
git commit -m "feat: add bitty sections"
```

---

## Done when

- `bitty sections` prints the table above for all three fixtures.
- `.venv/bin/pytest` is green, and the 128 pre-existing tests have no altered assertions.
- `git diff --stat tests/goldens/` prints nothing.
- Every section boundary in the output can be traced to a mark in the score.
