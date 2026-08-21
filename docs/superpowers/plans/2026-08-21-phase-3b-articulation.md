# Phase 3b — Articulation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make arranged notes behave like performed notes — dynamics that vary, sustained notes that vibrate, and ornaments that sound as fast notes instead of as clusters or not at all.

**Architecture:** Ornaments and written dynamics resolve in `ingest`, which owns what the score says; accent and vibrato flagging happen in `arrange`, which owns what chiptune does with it; the vibrato waveform lives in a new `lfo.py` and is applied in `synth`. Resolving ornaments upstream lets four Phase 3a workarounds be deleted, because all four existed only to cope with grace notes arriving at zero duration.

**Tech Stack:** Python 3.11+, music21 10.5, numpy, pytest. Run tests with `.venv/bin/pytest`.

**Spec:** `docs/superpowers/specs/2026-08-21-phase-3b-articulation-design.md`

## Global Constraints

- **Arranging stays deterministic.** Identical input produces an identical `arrangement.json`, byte for byte. Nothing calls `random`.
- **Velocities quantize to 16 levels** (`MAX_VELOCITY = 15`). The coarse steps are the texture, not a loss.
- **Vibrato constants take the spec's values:** depth 25 cents, delay 300 ms, minimum note 500 ms. They stay module constants — Phase 5 makes them config.
- **Accent offsets:** `+2` on a downbeat (beat strength 1.0), `0` on a secondary strong beat (0.5), `-1` below that. Applied *after* quantization, then clamped to `1 .. MAX_VELOCITY`.
- **Grace notes take 32 ms**, capped at half the principal's duration.
- **This phase does not change who plays what.** Channel assignment is 3a's accepted result; Task 11 proves it survived.
- **Out of scope:** fermatas, hairpins, and all config surface.
- Source layout is `src/bitty/`, tests in `tests/`.

### Baseline to hold (measured on `main` at 2026-08-21, commit `2a6e1cc`)

| fixture | lead purity | bass purity | lead leaps ≥ 12 semitones |
|---------|-------------|-------------|---------------------------|
| chorale | 100.0% | 100.0% | 0 |
| minuet | 97.4% | 85.7% | 3 |
| ragtime | 96.6% | 98.1% | 3 |

The purity figures reproduce 3a's recorded table exactly. The leap counts are new: 3a's prose numbers came from a metric that was never written down, so Task 11 checks a metric in as code and anchors to the values above.

## File Structure

| File | Responsibility |
|------|----------------|
| `src/bitty/model.py` | **Modify** — `Note` gains `beat_strength` |
| `src/bitty/ingest.py` | **Modify** — written dynamics, beat strength, ornament realization, grace shaping |
| `src/bitty/arrange.py` | **Modify** — delete ornament workarounds; accent velocity; vibrato flagging |
| `src/bitty/arrangement.py` | **Modify** — `Event.vibrato`; unknown-field tolerance for events |
| `src/bitty/lfo.py` | **Create** — `vibrato_cents`, plus the three `[vibrato]` constants |
| `src/bitty/synth.py` | **Modify** — fold vibrato into the frequency increment |
| `tests/fixtures/ornaments.musicxml` | **Create** — a trill, a mordent, and a grace note |
| `tests/test_ingest.py` | **Modify** — dynamics, beat strength, ornaments, graces |
| `tests/test_arrange.py` | **Modify** — accent velocity, vibrato flagging |
| `tests/test_arrangement.py` | **Modify** — `vibrato` round-trips; unknown fields tolerated |
| `tests/test_lfo.py` | **Create** — delay, depth, boundedness |
| `tests/test_synth.py` | **Modify** — a vibrato event is not a steady tone |
| `tests/test_quality.py` | **Create** — purity and leap metrics with the baseline as floors |
| `tests/goldens/*.arrangement.json` | **Regenerate** — several times; read each diff |

---

### Task 1: Beat strength on Note

Metric position is a score fact derived from the time signature. music21's `beatStrength` handles compound meter correctly; do not hand-roll `offset % bar_length`.

**Files:**
- Modify: `src/bitty/model.py`
- Modify: `src/bitty/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Note.beat_strength: float` — 1.0 on a downbeat, 0.5 on a secondary strong beat, lower elsewhere; `0.5` when music21 cannot determine it. Task 6 reads this.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ingest.py`:

```python
def test_ingest_records_metric_position():
    """Accent needs to know where in the bar a note falls."""
    score = ingest(FIXTURE)
    downbeat = [n for n in score.notes if n.start == 0.0]
    offbeat = [n for n in score.notes if n.start == 0.5]
    assert downbeat and offbeat
    assert all(n.beat_strength == 1.0 for n in downbeat)
    assert all(n.beat_strength < 1.0 for n in offbeat)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_ingest.py::test_ingest_records_metric_position -v`
Expected: FAIL with `AttributeError: 'Note' object has no attribute 'beat_strength'`

- [ ] **Step 3: Add the field**

In `src/bitty/model.py`, add to `Note` after `part`:

```python
    beat_strength: float = 0.5  # 1.0 on a downbeat; see ingest for the source
```

It is defaulted so existing hand-built `Note`s in tests keep working.

- [ ] **Step 4: Populate it in ingest**

In `src/bitty/ingest.py`, add this helper next to `_velocity_of`:

```python
NEUTRAL_BEAT_STRENGTH = 0.5


def _beat_strength_of(element) -> float:
    """Where in the bar this note falls, per music21's metric hierarchy.

    Compound meter makes this more than `offset % bar_length`, and a note with
    no time-signature context has no metric position at all — such a note takes
    the neutral value so it is neither accented nor trimmed.
    """
    try:
        strength = element.beatStrength
    except Exception:
        return NEUTRAL_BEAT_STRENGTH
    return NEUTRAL_BEAT_STRENGTH if strength is None else float(strength)
```

In the `ingest` note loop, alongside `velocity = _velocity_of(element)`:

```python
            beat_strength = _beat_strength_of(element)
```

and pass `beat_strength=beat_strength` into the `Note(...)` construction.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS. Goldens are unaffected — nothing reads `beat_strength` yet.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/model.py src/bitty/ingest.py tests/test_ingest.py
git commit -m "feat: record each note's metric position at ingest"
```

---

### Task 2: Written dynamics

Every event in every golden is currently `vel: 8`, because `ingest` never reads the score's dynamic markings. The minuet has 14 and the ragtime 2.

**Files:**
- Modify: `src/bitty/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `Note.velocity` now reflects written dynamics — an explicit per-note velocity (a MIDI source) still wins, then the governing mark, then `DEFAULT_VELOCITY`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ingest.py`:

```python
MINUET = Path(__file__).parent / "fixtures" / "minuet.mxl"


def test_ingest_reads_written_dynamics():
    """A score marked f then p should not come out uniformly loud."""
    score = ingest(MINUET)
    assert len({n.velocity for n in score.notes}) > 1


def test_ingest_holds_a_dynamic_until_the_next_mark():
    """A mark governs every following note in its own part, not just one."""
    score = ingest(MINUET)
    # Part 2 is marked f at offset 8.0 and p at 25.0; the p is quieter.
    part = [n for n in score.notes if n.part == 2]
    under_f = [n for n in part if 4.0 <= n.start < 12.0]
    under_p = [n for n in part if n.start >= 12.5]
    assert under_f and under_p
    assert max(n.velocity for n in under_p) < min(n.velocity for n in under_f)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ingest.py -k dynamic -v`
Expected: FAIL — every velocity is currently `DEFAULT_VELOCITY`, so the set has one member.

- [ ] **Step 3: Implement**

In `src/bitty/ingest.py`, add `dynamics` to the music21 import, then add:

```python
def _dynamic_marks(part) -> list[tuple[float, int]]:
    """(offset, velocity) for each written dynamic in this part, in order."""
    marks = [
        (float(mark.offset), max(1, min(127, round(mark.volumeScalar * 127))))
        for mark in part.flatten().getElementsByClass(dynamics.Dynamic)
    ]
    marks.sort(key=lambda pair: pair[0])
    return marks


def _velocity_at(marks: list[tuple[float, int]], offset: float) -> int | None:
    """The dynamic governing this offset: the last mark at or before it."""
    governing = None
    for mark_offset, velocity in marks:
        if mark_offset > offset + 1e-9:
            break
        governing = velocity
    return governing
```

Change `_velocity_of` to take the governing mark:

```python
def _velocity_of(element, written: int | None) -> int:
    """An explicit per-note velocity wins; a MIDI source carries one, a score does not."""
    velocity = getattr(element.volume, "velocity", None)
    if velocity is not None:
        return int(velocity)
    return written if written is not None else DEFAULT_VELOCITY
```

In `ingest`, hoist the marks per part and pass the governing one:

```python
    for part_index, part in enumerate(parsed.parts):
        marks = _dynamic_marks(part)
        for element in part.flatten().notes:
            ...
            velocity = _velocity_of(element, _velocity_at(marks, float(element.offset)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ingest.py -v`
Expected: PASS

- [ ] **Step 5: Regenerate the goldens and read the diff**

Run:
```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
git diff --stat tests/goldens/
```
Expected: minuet and ragtime velocities now vary; **the chorale is unchanged**, because it carries no written dynamics. That asymmetry is the point of Task 6.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/bitty/ingest.py tests/test_ingest.py tests/goldens/
git commit -m "feat: read the score's written dynamics"
```

---

### Task 3: Realize trills, mordents and turns

Today an ornament expression is dropped and the note renders as a plain held tone — silently wrong.

**Files:**
- Create: `tests/fixtures/ornaments.musicxml`
- Modify: `src/bitty/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: ornamented notes arrive as several short `Note`s whose durations sum to the original's.

> **Trap, verified on music21 10.5.0.** The stream-level `expressions.realizeOrnaments()` returns the note **unchanged** — no error, no expansion. Only the per-ornament `.realize(note, keySig=...)` works. The test below is the only thing that will catch a regression here.

- [ ] **Step 1: Create the fixture**

None of the three corpus excerpts contains a trill or a mordent, so build one:

```bash
.venv/bin/python - <<'PY'
from music21 import expressions, key, meter, note, stream

part = stream.Part()
part.append(key.KeySignature(0))
part.append(meter.TimeSignature('4/4'))

trilled = note.Note('C5', quarterLength=1.0)
trilled.expressions.append(expressions.Trill())
part.append(trilled)

mordented = note.Note('E5', quarterLength=1.0)
mordented.expressions.append(expressions.Mordent())
part.append(mordented)

grace = note.Note('G5')
grace.duration.quarterLength = 0.0
part.append(grace)
principal = note.Note('F5', quarterLength=1.0)
part.append(principal)

part.append(note.Note('C5', quarterLength=1.0))

score = stream.Score()
score.append(part)
score.write('musicxml', fp='tests/fixtures/ornaments.musicxml')
PY
```

Verify the fixture actually holds what it should before trusting it:

```bash
.venv/bin/python -c "
from music21 import converter, expressions
p = converter.parse('tests/fixtures/ornaments.musicxml')
print([type(e).__name__ for n in p.flatten().notes for e in n.expressions])
print('graces:', sum(1 for n in p.flatten().notes if n.duration.quarterLength == 0))
"
```
Expected: `['Trill', 'Mordent']` and `graces: 1`.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_ingest.py`:

```python
ORNAMENTS = Path(__file__).parent / "fixtures" / "ornaments.musicxml"


def test_ingest_expands_a_trill_into_fast_notes():
    """A trill is several notes, not one held tone.

    Guards a real trap: music21's stream-level realizeOrnaments() silently
    leaves the note alone, so only a count assertion catches the regression.
    """
    score = ingest(ORNAMENTS)
    first_beat = [n for n in score.notes if n.start < 1.0]
    assert len(first_beat) > 2
    assert len({n.pitch for n in first_beat}) == 2, "a trill alternates two pitches"


def test_ingest_expands_a_mordent_and_keeps_the_note_length():
    score = ingest(ORNAMENTS)
    second_beat = [n for n in score.notes if 1.0 <= n.start < 2.0]
    assert len(second_beat) == 3, "mordent: upper, neighbour, then the note itself"
    assert sum(n.dur for n in second_beat) == pytest.approx(1.0)
```

Add `import pytest` to the file if it is not already there.

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ingest.py -k "trill or mordent" -v`
Expected: FAIL — one note per beat, because expressions are dropped.

- [ ] **Step 4: Implement**

In `src/bitty/ingest.py`, add `expressions` and `key` to the music21 import, then:

```python
def _realized(element, key_signature):
    """An ornamented note as the notes it actually stands for.

    music21's realize returns (before, main, after) and shortens `main` so the
    pieces sum to the original length. A Fermata is not an Ornament and so
    passes through untouched, which is what this phase wants.
    """
    for expression in element.expressions:
        if not isinstance(expression, expressions.Ornament):
            continue
        try:
            before, main, after = expression.realize(element, keySig=key_signature)
        except Exception:
            continue  # an ornament music21 cannot resolve stays a plain note
        return [*before, *([main] if main is not None else []), *after]
    return [element]
```

In `ingest`, wrap the element loop. Realized notes lay out consecutively from the original's offset, so track a running offset:

```python
    for part_index, part in enumerate(parsed.parts):
        marks = _dynamic_marks(part)
        key_signature = part.flatten().getElementsByClass(key.KeySignature).first()
        for element in part.flatten().notes:
            written = _velocity_at(marks, float(element.offset))
            cursor = float(element.offset)
            for piece in _realized(element, key_signature):
                start = cursor * seconds_per_quarter
                dur = float(piece.duration.quarterLength) * seconds_per_quarter
                cursor += float(piece.duration.quarterLength)
                velocity = _velocity_of(piece, written)
                beat_strength = _beat_strength_of(element)
                for pitch in _pitches_of(piece):
                    notes.append(
                        Note(
                            pitch=pitch,
                            start=start,
                            dur=dur,
                            velocity=velocity,
                            part=part_index,
                            beat_strength=beat_strength,
                        )
                    )
```

Note `beat_strength` comes from `element`, not `piece`: the realized pieces are detached from the stream and have no metric context, and every piece of an ornament belongs to the principal's beat anyway.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ingest.py -v`
Expected: PASS

- [ ] **Step 6: Confirm the corpus fixtures are untouched**

Run: `.venv/bin/pytest tests/test_goldens.py`
Expected: PASS with no golden regeneration — none of the three excerpts contains an ornament expression, so this task must not change their output. **If a golden fails here, stop and find out why before regenerating.**

- [ ] **Step 7: Commit**

```bash
git add src/bitty/ingest.py tests/test_ingest.py tests/fixtures/ornaments.musicxml
git commit -m "feat: realize trills, mordents and turns as fast notes"
```

---

### Task 4: Shape grace notes

A grace currently arrives at zero duration and at the same instant as the note it decorates, so 3a floors it to 32 ms and it sounds *on top of* its principal as a cluster. It should sound *before* it.

**Files:**
- Modify: `src/bitty/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: **no `Note` leaving `ingest` has `dur == 0.0`.** Task 5 deletes the arranger's grace handling on the strength of this.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ingest.py`:

```python
def test_ingest_gives_every_note_a_real_duration():
    """The post-condition Task 5's deletions depend on."""
    for fixture in (FIXTURE, MINUET, ORNAMENTS):
        assert all(n.dur > 0.0 for n in ingest(fixture).notes)


def test_a_grace_note_sounds_before_the_note_it_decorates():
    score = ingest(ORNAMENTS)
    grace = next(n for n in score.notes if n.pitch == 79)  # G5
    principal = next(n for n in score.notes if n.pitch == 77)  # F5
    assert grace.start < principal.start
    assert grace.start + grace.dur == pytest.approx(principal.start)
    assert grace.dur == pytest.approx(0.032)


def test_a_grace_note_borrows_from_its_principal_rather_than_shifting_it():
    """The pair occupies the principal's original span, so nothing downstream moves."""
    score = ingest(ORNAMENTS)
    grace = next(n for n in score.notes if n.pitch == 79)
    principal = next(n for n in score.notes if n.pitch == 77)
    assert grace.start + grace.dur + principal.dur == pytest.approx(grace.start + 1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ingest.py -k grace -v`
Expected: FAIL — the grace has `dur == 0.0` and the same `start` as its principal.

- [ ] **Step 3: Implement**

In `src/bitty/ingest.py`, add `from collections import defaultdict` and `from dataclasses import replace`, then:

```python
GRACE_SEC = 0.032


def _shape_graces(notes: list[Note]) -> list[Note]:
    """Move grace notes in front of the notes they decorate.

    music21 hands over a grace at zero duration and at its principal's onset,
    which would sound as a cluster. The grace takes 32 ms from the front of the
    principal — capped at half of it, so an ornament on an already short note
    cannot swallow it — and the pair occupies the principal's original span, so
    nothing after it moves.
    """
    graced: dict[tuple[int, float], list[Note]] = defaultdict(list)
    for note in notes:
        if note.dur == 0.0:
            graced[(note.part, note.start)].append(note)
    if not graced:
        return notes

    slots: dict[tuple[int, float], float] = {}
    for key_, group in graced.items():
        part, start = key_
        spans = [n.dur for n in notes if n.part == part and n.start == start and n.dur > 0.0]
        room = min(spans) / 2.0 if spans else GRACE_SEC * len(group)
        slots[key_] = min(GRACE_SEC * len(group), room)

    shaped: list[Note] = []
    taken: dict[tuple[int, float], int] = defaultdict(int)
    for note in notes:
        key_ = (note.part, note.start)
        if key_ not in slots:
            shaped.append(note)
            continue
        total = slots[key_]
        if note.dur == 0.0:
            each = total / len(graced[key_])
            index = taken[key_]
            taken[key_] += 1
            shaped.append(replace(note, start=note.start + index * each, dur=each))
        else:
            shaped.append(replace(note, start=note.start + total, dur=note.dur - total))
    return shaped
```

In `ingest`, apply it before the sort:

```python
    notes = _shape_graces(notes)
    notes.sort(key=lambda n: (n.start, -n.pitch))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ingest.py -v`
Expected: PASS

- [ ] **Step 5: Regenerate the goldens and read the diff**

Run:
```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
git diff tests/goldens/minuet.arrangement.json | head -40
```
Expected: only the minuet changes, at its two graces (offsets 7.0 and 8.0 quarter-notes). The chorale and ragtime have no graces and must be untouched.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/bitty/ingest.py tests/test_ingest.py tests/goldens/
git commit -m "feat: sound a grace note before the note it decorates"
```

---

### Task 5: Delete the arranger's ornament workarounds

All four exist only because grace notes used to arrive at zero duration. Task 4 established that they no longer do.

**Files:**
- Modify: `src/bitty/arrange.py`
- Test: `tests/test_arrange.py`

**Interfaces:**
- Consumes: Task 4's post-condition — no note has `dur == 0.0`.
- Produces: `_Take` no longer has an `ornament` field; `GRACE_SEC` no longer exists in `arrange`. Later tasks must not reference either.

- [ ] **Step 1: Find the tests that assert the old behaviour**

Run: `.venv/bin/rg -n "ornament|GRACE_SEC|grace" tests/test_arrange.py src/bitty/arrange.py`

Read every hit. Tests that assert a grace gets a 32 ms *floor in the arranger* are now testing a rule that lives in `ingest`; delete them, and note in the commit message that Task 4's tests cover the behaviour instead. Do not delete a test that asserts something still true.

- [ ] **Step 2: Delete the constant and the flag**

In `src/bitty/arrange.py`, remove the `GRACE_SEC` line, and remove the `ornament` field from `_Take`:

```python
@dataclass
class _Take:
    """A note as placed on one channel. Mutable: a later note truncates it."""

    t: float
    pitch: int
    dur: float
    vel: int
```

- [ ] **Step 3: Simplify `_place`**

```python
def _place(takes: list[_Take], note: Note) -> None:
    """Add a note to a channel, cutting short whatever it was holding."""
    if takes and takes[-1].t + takes[-1].dur > note.start + EPSILON:
        takes[-1].dur = note.start - takes[-1].t
    takes.append(
        _Take(
            t=note.start,
            pitch=note.pitch,
            dur=note.dur,
            vel=_quantize_velocity(note.velocity),
        )
    )
```

- [ ] **Step 4: Simplify `_last_pitch`**

The ornament skip and its docstring go; a grace is now an ordinary short note that its principal immediately follows.

```python
def _last_pitch(takes: list[_Take]) -> int | None:
    """The last pitch this channel actually sang."""
    return takes[-1].pitch if takes else None
```

- [ ] **Step 5: Simplify `_assign`'s grouping**

In `_assign`, replace the `pending` / `graces` split with the plain group:

```python
    for onset, group in _by_onset(score.notes):
        used: set[str] = set()
        pending = list(group)
        above = _texture(tracks, onset, without=LEAD_ROLE)
```

and further down, restore the plain loop:

```python
        spare: list[Note] = []
        for note in pending:
```

- [ ] **Step 6: Run the suite**

Run: `.venv/bin/pytest`
Expected: `tests/test_goldens.py` fails on the minuet — a grace now competes for a channel on equal terms. Everything else passes. **If any other fixture changes, stop:** the chorale and ragtime have no graces, so nothing about them should move.

- [ ] **Step 7: Regenerate the goldens and read the diff**

```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
git diff tests/goldens/ | head -60
.venv/bin/pytest
```

- [ ] **Step 8: Commit**

```bash
git add src/bitty/arrange.py tests/test_arrange.py tests/goldens/
git commit -m "refactor: drop the grace-note workarounds ingest made unnecessary"
```

> Task 11 is what proves these deletions cost nothing. Do not skip it.

---

### Task 6: Accent-aware velocity

The chorale carries no written dynamics at all, so Task 2 left it flat. Metric accent is what gives every fixture variation.

**Files:**
- Modify: `src/bitty/arrange.py`
- Test: `tests/test_arrange.py`

**Interfaces:**
- Consumes: `Note.beat_strength` from Task 1.
- Produces: `_velocity(note: Note) -> int` replaces `_quantize_velocity(velocity: int) -> int`. Both call sites — `_place` and `_arpeggiate` — must be updated.

- [ ] **Step 1: Extend the existing `note` helper**

`tests/test_arrange.py` already has a `note(...)` factory. Give it the new field rather than constructing `Note` by hand in the tests:

```python
def note(pitch, start, dur=1.0, velocity=64, part=0, beat_strength=0.5):
    return Note(
        pitch=pitch,
        start=start,
        dur=dur,
        velocity=velocity,
        part=part,
        beat_strength=beat_strength,
    )
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_arrange.py`. `_velocity` and `Note` come from the imports already at the top of the file:

```python
def test_a_downbeat_is_louder_than_a_weak_beat():
    downbeat = _velocity(note(60, 0.0, beat_strength=1.0))
    secondary = _velocity(note(60, 0.0, beat_strength=0.5))
    weak = _velocity(note(60, 0.0, beat_strength=0.25))
    assert downbeat == secondary + 2
    assert weak == secondary - 1


def test_accent_never_silences_a_note_or_exceeds_the_ceiling():
    loudest = note(60, 0.0, velocity=127, beat_strength=1.0)
    quietest = note(60, 0.0, velocity=1, beat_strength=0.25)
    assert _velocity(loudest) == 15
    assert _velocity(quietest) >= 1
```

Add `_velocity` to the `from bitty.arrange import ...` line at the top of the file.

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_arrange.py -k "downbeat or silences" -v`
Expected: FAIL with `ImportError: cannot import name '_velocity'`

- [ ] **Step 4: Implement**

In `src/bitty/arrange.py`, replace `_quantize_velocity` with:

```python
DOWNBEAT_STRENGTH = 1.0
SECONDARY_STRENGTH = 0.5
DOWNBEAT_ACCENT = 2
WEAK_BEAT_TRIM = -1


def _velocity(note: Note) -> int:
    """The written dynamic, quantized, then lifted or trimmed by metric position.

    Quantize first and accent second: the 16 levels are the texture, and an
    accent that vanished into rounding would not be an accent. The clamp keeps
    a trim from silencing a note outright.
    """
    level = round(note.velocity / 127 * MAX_VELOCITY)
    return max(1, min(MAX_VELOCITY, level + _accent(note.beat_strength)))


def _accent(beat_strength: float) -> int:
    if beat_strength >= DOWNBEAT_STRENGTH:
        return DOWNBEAT_ACCENT
    if beat_strength >= SECONDARY_STRENGTH:
        return 0
    return WEAK_BEAT_TRIM
```

- [ ] **Step 5: Update both call sites**

In `_place` (Task 5 already touched it): `vel=_velocity(note),`

In `_arpeggiate`, change:

```python
        vel = max(
            [_velocity(n) for n in notes] + [take.vel for take in absorbed]
        )
```

Run `.venv/bin/rg -n "_quantize_velocity" src/ tests/` and confirm there are no remaining references.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_arrange.py -v`
Expected: PASS

- [ ] **Step 7: Regenerate the goldens and check the histogram**

```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
.venv/bin/python -c "
import json, collections
for name in ('chorale','minuet','ragtime'):
    d = json.load(open(f'tests/goldens/{name}.arrangement.json'))
    vels = collections.Counter(e['vel'] for c in d['channels'] for e in c['events'])
    print(name, dict(sorted(vels.items())))
"
```
Expected: **no fixture is a single spike any more, the chorale included.** That is the cheapest signal the dynamics work landed. If the chorale still shows one value, Task 1 is not feeding `beat_strength` through.

- [ ] **Step 8: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/bitty/arrange.py tests/test_arrange.py tests/goldens/
git commit -m "feat: accent the downbeat and trim the weak beat"
```

---

### Task 7: Put vibrato on the contract

**Files:**
- Modify: `src/bitty/arrangement.py`
- Test: `tests/test_arrangement.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Event.vibrato: bool = False`. Task 9 reads it; Task 10 writes it.

The spec's JSON illustration shows a nested `"effects": {"vibrato": true}`. This is a deliberate divergence: `Instrument` documents the house rule that this is the hand-edit surface and should stay flat.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_arrangement.py`:

```python
def test_vibrato_round_trips_through_json():
    original = Arrangement(
        meta={"title": "t", "bpm": 120.0},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(wave="pulse"),
                events=(
                    Event(t=0.0, pitch=60, dur=1.0, vel=10, vibrato=True),
                    Event(t=1.0, pitch=62, dur=0.1, vel=10),
                ),
            ),
        ),
    )
    restored = Arrangement.from_json(original.to_json())
    assert [e.vibrato for e in restored.channels[0].events] == [True, False]


def test_an_event_field_this_build_does_not_know_is_dropped_not_fatal():
    """A newer bitty's arrangement should render with the fields we understand.

    Instrument already promises this; Event did not, so an added field turned
    every older build into a hard failure on load.
    """
    text = json.dumps(
        {
            "meta": {"title": "t", "bpm": 120.0},
            "channels": [
                {
                    "role": "lead",
                    "instrument": {"wave": "pulse"},
                    "events": [
                        {"t": 0.0, "pitch": 60, "dur": 1.0, "vel": 10, "tremolo": 0.5}
                    ],
                }
            ],
        }
    )
    restored = Arrangement.from_json(text)
    assert restored.channels[0].events[0].pitch == 60
```

Add `import json` to the test file if it is not already imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_arrangement.py -k "vibrato or does_not_know" -v`
Expected: FAIL — `Event.__init__() got an unexpected keyword argument 'vibrato'`, then `... 'tremolo'`.

- [ ] **Step 3: Add the field**

In `src/bitty/arrangement.py`:

```python
@dataclass(frozen=True)
class Event:
    t: float  # seconds from the start of the arrangement
    pitch: int  # MIDI note number
    dur: float  # seconds
    vel: int  # 0-15
    vibrato: bool = False  # a delayed LFO on the pitch; see lfo.py
```

- [ ] **Step 4: Give events the tolerance instruments already have**

Replace the `events=` line in `_channel_from` with `events=tuple(_event_from(e) for e in raw["events"])`, and add:

```python
def _event_from(raw: dict) -> Event:
    """Build an Event, dropping any field this build does not know.

    The same contract `_instrument_from` keeps, for the same reason: adding a
    field should not turn every older build into a hard failure on load.
    """
    known = {f.name for f in fields(Event)}
    return Event(**{k: v for k, v in raw.items() if k in known})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_arrangement.py -v`
Expected: PASS

- [ ] **Step 6: Regenerate the goldens**

Every event gains `"vibrato": false`, which is a large but entirely mechanical diff.

```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
git diff tests/goldens/ | rg -v '^\+.*"vibrato": false' | head -30
```
Expected: the filtered diff shows only context lines — nothing but added `vibrato` keys changed.

- [ ] **Step 7: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/bitty/arrangement.py tests/test_arrangement.py tests/goldens/
git commit -m "feat: add vibrato to the event contract"
```

---

### Task 8: The vibrato LFO

Settled in the design-patterns dialog: the direct version — a pure function of arrays, like `osc`, `envelope` and `filters` — in its own module. Not in `envelope.py`, whose docstring commits specifically to step sequences.

**Files:**
- Create: `src/bitty/lfo.py`
- Test: `tests/test_lfo.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `vibrato_cents(length: int, sample_rate: int) -> np.ndarray` of shape `(length,)`, and the constants `DEPTH_CENTS = 25.0`, `DELAY_SEC = 0.3`, `MIN_NOTE_SEC = 0.5`. Task 9 imports the function; Task 10 imports `MIN_NOTE_SEC`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lfo.py`:

```python
import numpy as np

from bitty.lfo import DELAY_SEC, DEPTH_CENTS, vibrato_cents

SR = 44100


def test_vibrato_is_silent_until_the_delay():
    """Vibrato from the instant of attack is the characteristic way this goes wrong."""
    cents = vibrato_cents(int(1.0 * SR), SR)
    assert np.all(cents[: int(DELAY_SEC * SR)] == 0.0)


def test_vibrato_reaches_full_depth_on_a_long_note():
    cents = vibrato_cents(int(3.0 * SR), SR)
    assert np.max(np.abs(cents)) == pytest.approx(DEPTH_CENTS, rel=0.02)


def test_vibrato_never_exceeds_its_depth():
    cents = vibrato_cents(int(3.0 * SR), SR)
    assert np.all(np.abs(cents) <= DEPTH_CENTS + 1e-9)


def test_vibrato_fades_in_rather_than_switching_on():
    """A step change in pitch at the delay would click."""
    cents = vibrato_cents(int(1.0 * SR), SR)
    start = int(DELAY_SEC * SR)
    just_after = np.max(np.abs(cents[start : start + int(0.01 * SR)]))
    assert 0.0 < just_after < DEPTH_CENTS / 2.0


def test_vibrato_is_deterministic():
    assert np.array_equal(vibrato_cents(1000, SR), vibrato_cents(1000, SR))


def test_a_note_shorter_than_the_delay_gets_no_vibrato():
    assert np.all(vibrato_cents(int(0.2 * SR), SR) == 0.0)
```

Add `import pytest` at the top.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_lfo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bitty.lfo'`

- [ ] **Step 3: Implement**

Create `src/bitty/lfo.py`:

```python
"""A delayed vibrato LFO: the sustain-time counterpart to the attack blip.

Separate from `envelope` on purpose. That module is tracker-style step
sequences and says so as a stylistic commitment; this is a continuous sine,
which is exactly the thing that commitment excludes.

Chip voices have no natural decay, so a held note is dead air. The delay is
what keeps the cure from sounding seasick: vibrato present from the instant of
attack is the characteristic way this effect goes wrong.
"""

import numpy as np

DEPTH_CENTS = 25.0  # the spec's [vibrato] depth_cents
DELAY_SEC = 0.3  # the spec's [vibrato] delay_ms
MIN_NOTE_SEC = 0.5  # the spec's [vibrato] min_note_ms; the arranger's threshold
RATE_HZ = 5.5  # not in the spec's config table; a conventional musical rate
FADE_SEC = 0.15  # a step change in pitch would click


def vibrato_cents(length: int, sample_rate: int) -> np.ndarray:
    """Per-sample pitch offset in cents: silent, then fading in to full depth."""
    if length <= 0:
        return np.zeros(0, dtype=np.float64)

    t = np.arange(length, dtype=np.float64) / sample_rate
    depth = np.clip((t - DELAY_SEC) / FADE_SEC, 0.0, 1.0) * DEPTH_CENTS
    return depth * np.sin(2.0 * np.pi * RATE_HZ * t)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_lfo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bitty/lfo.py tests/test_lfo.py
git commit -m "feat: add a delayed vibrato LFO"
```

---

### Task 9: Apply vibrato in the synth

**Files:**
- Modify: `src/bitty/synth.py`
- Test: `tests/test_synth.py`

**Interfaces:**
- Consumes: `vibrato_cents` from Task 8; `Event.vibrato` from Task 7.
- Produces: nothing new. `render` output changes only for events carrying the flag.

- [ ] **Step 1: Extend the existing `one_note` helper**

`tests/test_synth.py` already builds one-channel arrangements with `one_note(...)`. Give it the flag instead of hand-rolling an `Arrangement` in the tests:

```python
def one_note(pitch=69, dur=1.0, wave="pulse", vel=15, vibrato=False, **instrument_kwargs) -> Arrangement:
    return Arrangement(
        meta={"title": "test", "bpm": 120.0},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(wave=wave, **instrument_kwargs),
                events=(Event(t=0.0, pitch=pitch, dur=dur, vel=vel, vibrato=vibrato),),
            ),
        ),
    )
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_synth.py`:

```python
def test_a_vibrato_event_wavers_and_a_plain_one_does_not():
    """Vibrato is a pitch effect, so measure it as pitch: zero-crossing spacing.

    A steady tone crosses zero at even intervals; a wavering one does not. The
    tail is measured because the first 300 ms are silent by design.
    """
    def crossing_spread(vibrato):
        audio = mono(render(one_note(dur=2.0, vibrato=vibrato)))
        tail = audio[int(0.8 * SAMPLE_RATE) :]
        crossings = np.flatnonzero(np.diff(np.signbit(tail)))
        return np.std(np.diff(crossings))

    assert crossing_spread(vibrato=True) > crossing_spread(vibrato=False) * 3


def test_vibrato_changes_only_the_notes_that_ask_for_it():
    assert not np.array_equal(
        render(one_note(dur=2.0, vibrato=True)),
        render(one_note(dur=2.0, vibrato=False)),
    )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_synth.py -k vibrato -v`
Expected: FAIL — the flag is ignored, so both renders are identical.

- [ ] **Step 4: Implement**

In `src/bitty/synth.py`, add `from bitty.lfo import vibrato_cents` to the imports. In `_add_event`, after the `pitch_env` block and before `phase` is computed:

```python
    if event.vibrato:
        # Composed with the pitch envelope, not replacing it: the blip is the
        # attack, the vibrato is the sustain.
        inc = inc * 2.0 ** (vibrato_cents(length, sample_rate) / 1200.0)
```

Update the module docstring's signal path line to mention it:

```
Signal path per channel: oscillator -> pitch envelope and vibrato -> volume
envelope -> edge fade -> lowpass -> constant-power pan -> sum.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_synth.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/bitty/synth.py tests/test_synth.py
git commit -m "feat: waver the pitch of events that ask for vibrato"
```

---

### Task 10: Flag sustained notes for vibrato

**Files:**
- Modify: `src/bitty/arrange.py`
- Test: `tests/test_arrange.py`

**Interfaces:**
- Consumes: `MIN_NOTE_SEC` from Task 8; `Event.vibrato` from Task 7.
- Produces: goldens in which long events carry `"vibrato": true`.

The duration tested is the event's **final** duration, after `_place` has truncated it for a stolen channel — which is why the flag is applied in `_events`, not in `_place`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_arrange.py`:

```python
def test_sustained_notes_get_vibrato_and_short_ones_do_not():
    arrangement = arrange(score_of(note(72, 0.0, dur=2.0), note(74, 2.0, dur=0.1)))
    events = [e for c in arrangement.channels for e in c.events]
    assert [e.vibrato for e in events] == [True, False]


def test_a_note_truncated_below_the_threshold_loses_its_vibrato():
    """The final duration decides, not the length the note was written at.

    A note cut short by a re-entering voice should not waver on the strength of
    a length it never got to play. Here the held note is written as a whole bar
    and stolen after a tenth of a second.
    """
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=2.0),
            note(72, 0.1, dur=2.0),  # same channel, so the first is truncated
        )
    )
    lead = channels(arrangement)["lead"].events
    assert lead[0].dur == pytest.approx(0.1)
    assert not lead[0].vibrato, "a note cut to 100 ms must not claim a 2-second vibrato"
    assert lead[1].vibrato
```

`arrange`, `score_of`, `note` and `channels` are already defined at the top of `tests/test_arrange.py`. Add `import pytest` if the file does not have it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_arrange.py -k vibrato -v`
Expected: FAIL — `assert any(e.vibrato ...)` fails; nothing sets the flag.

- [ ] **Step 3: Implement**

In `src/bitty/arrange.py`, add `from bitty.lfo import MIN_NOTE_SEC` and rewrite `_events`:

```python
def _events(takes: list[_Take]) -> tuple[Event, ...]:
    """Takes as contract events, flagging the ones long enough to waver.

    The flag is applied here rather than in `_place` because a take's duration
    is not final until every later note has had its chance to truncate it.
    """
    return tuple(
        Event(
            t=take.t,
            pitch=take.pitch,
            dur=take.dur,
            vel=take.vel,
            vibrato=take.dur >= MIN_NOTE_SEC,
        )
        for take in takes
        if take.dur > EPSILON
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_arrange.py -v`
Expected: PASS

- [ ] **Step 5: Regenerate the goldens and sanity-check the reach**

```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
.venv/bin/python -c "
import json
for name in ('chorale','minuet','ragtime'):
    d = json.load(open(f'tests/goldens/{name}.arrangement.json'))
    ev = [e for c in d['channels'] for e in c['events']]
    print(name, sum(e['vibrato'] for e in ev), '/', len(ev))
"
```
Expected: roughly 96/144 chorale, 128/156 minuet, 6/407 ragtime. The ragtime barely qualifying is correct — it is fast — not a threshold to tune around.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/bitty/arrange.py tests/test_arrange.py tests/goldens/
git commit -m "feat: flag sustained notes for vibrato"
```

---

### Task 11: Prove the reduction survived

Task 5 deleted four workarounds, two of which were written during 3a's acceptance listen to fix audible defects. The argument that their cause is gone is sound but unproven. This task is the proof, and it makes the metric permanent so the next phase inherits a number it can re-measure.

**Files:**
- Create: `tests/test_quality.py`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing other tasks use.

- [ ] **Step 1: Write the test**

Create `tests/test_quality.py`:

```python
"""Arrangement quality as numbers, so a regression in the reduction is caught.

Phase 3a recorded its purity percentages in prose and they reproduce exactly.
Its octave-leap counts do not, because the metric behind them was never written
down — so the thresholds here are anchored to `main` at 2026-08-21, measured
before Phase 3b began.
"""

import statistics
from pathlib import Path

import pytest

from bitty.arrange import arrange
from bitty.ingest import ingest

FIXTURES = Path(__file__).parent / "fixtures"
EPSILON = 1e-6
OCTAVE = 12

# fixture: (min lead purity %, min bass purity %, max lead leaps)
BASELINE = {
    "chorale": (100.0, 100.0, 0),
    "minuet": (97.4, 85.7, 3),
    "ragtime": (96.6, 98.1, 3),
}


def _measured(name):
    score = ingest(FIXTURES / f"{name}.mxl")
    arrangement = arrange(score)

    pitches: dict[int, list[int]] = {}
    for note in score.notes:
        pitches.setdefault(note.part, []).append(note.pitch)
    top = max(pitches, key=lambda p: statistics.mean(pitches[p]))
    bottom = min(pitches, key=lambda p: statistics.mean(pitches[p]))

    events = {c.role: c.events for c in arrangement.channels}

    def purity(role, part):
        matched = hits = 0
        for event in events.get(role, ()):
            sources = [
                n
                for n in score.notes
                if n.pitch == event.pitch and abs(n.start - event.t) <= EPSILON
            ]
            if not sources:
                continue  # an arpeggio step, which belongs to no single part
            matched += 1
            hits += any(n.part == part for n in sources)
        return 100.0 * hits / matched if matched else 0.0

    lead = events.get("lead", ())
    leaps = sum(1 for a, b in zip(lead, lead[1:]) if abs(a.pitch - b.pitch) >= OCTAVE)
    return purity("lead", top), purity("bass", bottom), leaps


@pytest.mark.parametrize("name", sorted(BASELINE))
def test_the_reduction_holds_its_baseline(name):
    """The melody stays put and the bass stays down, measured rather than heard.

    A failure here means the articulation work cost the voice leading that
    Phase 3a's acceptance listen approved. That is a reason to stop, not to
    lower the numbers.
    """
    min_lead, min_bass, max_leaps = BASELINE[name]
    lead, bass, leaps = _measured(name)
    assert lead >= min_lead - 0.05, f"lead purity fell to {lead:.1f}%"
    assert bass >= min_bass - 0.05, f"bass purity fell to {bass:.1f}%"
    assert leaps <= max_leaps, f"{leaps} octave-plus leaps on the lead"


@pytest.mark.parametrize("name", sorted(BASELINE))
def test_dynamics_are_not_flat(name):
    """The defect this phase exists to fix: every event was vel 8."""
    arrangement = arrange(ingest(FIXTURES / f"{name}.mxl"))
    levels = {e.vel for c in arrangement.channels for e in c.events}
    assert len(levels) > 1, f"{name} renders at a single dynamic level"
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/pytest tests/test_quality.py -v`
Expected: PASS.

**If `test_the_reduction_holds_its_baseline` fails, stop and report it.** Do not lower a threshold to make it pass. The likely cause is Task 5: a grace note now competing for a channel on equal terms may be taking one the melody needed. The fix belongs in `_pick_middle` or in how short a shaped grace is — not in this file.

- [ ] **Step 3: Commit**

```bash
git add tests/test_quality.py
git commit -m "test: hold the reduction to its measured baseline"
```

---

### Task 12: Acceptance listen and finish the branch

**Files:**
- Modify: `docs/superpowers/plans/2026-08-21-phase-3b-articulation.md`

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS. Do not proceed to a listen on a red suite.

- [ ] **Step 2: Render all three fixtures to WAV**

```bash
for f in chorale minuet ragtime; do
  .venv/bin/bitty convert tests/fixtures/$f.mxl -o out/3b
done
ls -la out/3b
```

**WAV, never Ogg.** `aplay` renders Ogg as static on this machine.

- [ ] **Step 3: Hand them over for the listen**

Ask the user to listen, and ask specifically about the three things this phase changed:

- Do sustained notes waver, and does the vibrato arrive *late* enough not to sound seasick?
- Do dynamics vary audibly — particularly the chorale, which has no written marks and is carried entirely by the accent?
- In the minuet, do the two grace notes read as ornaments rather than as clusters?

The first knobs to reach for, in order, if the answer disappoints: `DOWNBEAT_ACCENT` / `WEAK_BEAT_TRIM` in `arrange.py` for the dynamics, and `DEPTH_CENTS` / `DELAY_SEC` / `RATE_HZ` in `lfo.py` for the vibrato.

- [ ] **Step 4: Record the outcome in this plan**

Add an "Outcome of the acceptance listen" section, following the shape Phase 3a used: what was heard, what was fixed between the last commit and the listen, and any knobs left for Phase 5. Record reservations even when the work is accepted.

- [ ] **Step 5: Finish the branch**

Use the superpowers:finishing-a-development-branch skill. Phases 1, 2 and 3a each landed on `main` as a `--no-ff` merge; follow that.

---

## Phase 3b exit criteria

- `.venv/bin/pytest` passes.
- No note leaves `ingest` with `dur == 0.0`, and no grace note sounds simultaneously with the note it decorates.
- A trill in `tests/fixtures/ornaments.musicxml` renders as alternating fast notes.
- Velocity varies across all three fixtures, including the chorale, which carries no written dynamics.
- Sustained notes carry `vibrato: true` and waver after a delay; notes under 500 ms do not.
- `tests/test_quality.py` passes at the baseline table above.
- `bitty render` still round-trips a hand-edited arrangement, now including `vibrato`.
- The acceptance listen has happened and its outcome is recorded in Task 12.

Phase 4 picks up structure — `analyze`, `bitty sections`, and the loop cascade — against this contract.
