# Phase 4a — Structure: analysis and `bitty sections`

**Date:** 2026-08-21
**Status:** Approved, ready for implementation planning
**Parent spec:** `2026-08-20-bitty-music-design.md`

## Goal

Read the structure the composer wrote — bar numbers, repeat marks,
barlines, key and time signatures — and report it as a table a person can
read to choose a section.

Phase 4 in the parent spec covers analysis, `bitty sections`, the loop
cascade, `--bars` / `--loop-from`, and the intro/loop split. That is more
than one session holds, and the parent spec says to split a phase that
outgrows one. This is the first half.

| | Delivers |
|---|---|
| **4a** (this spec) | Bar timeline at ingest, `analyze`, `bitty sections` |
| **4b** | Loop cascade, `--bars` / `--loop-from`, intro/loop split, the arrangement's `loop` field |

The split falls where it does because 4a changes nothing downstream of
`Score`: no audio changes, no `arrangement.json` change, and the golden
files stay byte-identical. 4b is where output artifacts change.

## Non-goals

- **Texture analysis.** The parent spec lists voice-count and
  rhythmic-density shifts as boundary evidence. Excluded here — see
  "Notation only" below.
- **Similarity labelling.** No `A'`. Sections are named by position, not
  by resemblance. Per-bar feature vectors are 4b's business or later.
- **A tempo map.** Deferred; see "Deferred: the tempo map".
- **Loop selection.** No auto-loop pick in the `sections` output. 4b.
- **`--bars` filtering.** Reporting only. 4b acts on the report.

## Notation only

Section boundaries come from marks in the score and nothing else. Every
boundary can be justified by pointing at the notation that produced it.

The rejected alternative was to add texture heuristics — voice-count and
rhythmic-density shifts — which find structure in pieces that carry no
repeat marks. It was rejected for this phase because it introduces
tunable thresholds and boundaries that cannot be traced to anything the
composer wrote, in a command whose entire purpose is to be trusted enough
to pick a loop from.

The cost is real and accepted: a piece with no repeat marks and no double
bars reports as a single section. On the chorale fixture that is the
honest answer — a hymn of eight bars has no interior structure to find.

Key *labelling* is a separate matter from boundary *evidence*, and does
use analysis. See "Key detection".

## Data contracts

### `Bar` — in `model.py`

`Bar` joins `Note` and `Score` because it is part of the musical model
ingest produces: notation facts, not interpretation.

```python
@dataclass(frozen=True)
class Bar:
    number: int                      # as printed in the score
    start: float                     # seconds
    dur: float                       # seconds
    time_signature: tuple[int, int]
    sharps: int                      # key signature, -7..7
    starts_repeat: bool              # left barline is a start repeat
    ends_repeat: bool                # right barline is an end repeat
    ends_span: bool                  # right barline is final or double
```

`Score` gains `bars: tuple[Bar, ...]`.

`Note` is unchanged. A note's bar is recoverable from its start time
against the bar timeline, and denormalising a `bar` field onto every note
buys nothing 4b needs.

Bar numbers are whatever music21 reports, which is what the score prints.
A pickup bar is therefore numbered as the score numbers it. `--bars` in
4b refers to these same printed numbers.

### `Section` — in `analyze.py`

`Section` lives with the function that produces it, because it is
interpretation rather than notation.

```python
@dataclass(frozen=True)
class Section:
    name: str                        # "A", "B", "C" — positional
    first_bar: int                   # printed numbers, inclusive
    last_bar: int
    start: float                     # seconds
    end: float
    key: str                         # "G major", detected
    time_signature: tuple[int, int]
    repeats: bool
```

`analyze(score: Score) -> tuple[Section, ...]`. A pure function of the
`Score` model, importing music21 only to build a scratch stream for key
detection.

**Names are positional, not similarity claims.** `A`, `B`, `C` mean
first, second, third. The parent spec's example output shows `A'`, which
asserts that a later section is a variant of an earlier one — a claim
notation-only evidence cannot support. When similarity labelling is
built, `A'` becomes honest; until then it would be a guess wearing the
costume of a fact.

Sections beyond `Z` continue `AA`, `AB`. Not expected; specified so the
behaviour is not accidental.

## The boundary rule

Bar 1 always opens a section. A new section opens at bar N when any of:

1. N starts a repeat
2. N−1 ends a repeat
3. N−1 has a final or double barline
4. N's time signature differs from N−1's
5. N's key signature differs from N−1's

Each predicate is independent and idempotent, so several firing at the
same bar produce one boundary, not several. Minuet bar 8 carries both a
final barline and an end repeat; rules 2 and 3 both fire at bar 9 and
yield a single boundary.

A section `repeats` when its first bar starts a repeat or its last bar
ends one.

### Expected output on the fixtures

Verified against music21 before this spec was written, by reading
`Measure.leftBarline` and `Measure.rightBarline`.

| Fixture | Sections |
|---|---|
| chorale | `A` bars 1–8, f# minor, no repeat |
| minuet | `A` bars 1–8 G major repeat; `B` bars 9–16 D major repeat |
| ragtime | `A` bars 1–16, A♭ major, repeat |

The minuet resolving to two eight-bar halves modulating from tonic to
dominant is the expected shape of a minuet, and is the strongest
available evidence that the rule is reading the notation correctly.

Reading a *flattened* score is misleading here: it reports barlines
duplicated once per part and at offsets that do not identify a bar. The
implementation reads measure-level barlines.

### Reading the barlines

Pinned so the implementation does not have to guess at music21's
vocabulary:

| `Bar` field | Source |
|---|---|
| `starts_repeat` | left barline is a `Repeat` with `direction == "start"` |
| `ends_repeat` | right barline is a `Repeat` with `direction == "end"` |
| `ends_span` | right barline `type` in `{"final", "double"}` |

A repeat barline carries an ordinary `type` as well — an end repeat's is
`final`, a start repeat's is `heavy-light` — so minuet bar 8 sets both
`ends_repeat` and `ends_span`. That overlap is deliberate and harmless:
rules 2 and 3 both fire at bar 9 and collapse to one boundary.

Barlines are read from the first part. A barline in one part and not
another is a malformed score, not a structure to reconcile.

## Key detection

Krumhansl-Schmuckler via music21, per section, as the parent spec
specifies. The parent spec also lists key detection among the things
deliberately not hand-rolled.

`analyze` consumes our `Score`, which holds no music21 objects, so it
builds a scratch `stream.Stream` of `note.Note` from the section's notes
and calls `.analyze('key')` on it.

A note belongs to the section its **onset** falls in — `section.start <=
note.start < section.end`. A note sustaining across a boundary counts
once, toward the section it began in. Weighting it into both would let a
single held bass note colour a section it never articulated in.

This was verified to be equivalent to analysing the real parsed score,
on every fixture:

| Score | From the file | From a rebuilt stream |
|---|---|---|
| minuet bars 1–8 | G major | G major |
| minuet bars 9–16 | D major | D major |
| chorale | f# minor | f# minor |
| ragtime | A♭ major | A♭ major |

The equivalence is expected rather than lucky: Krumhansl-Schmuckler
correlates a duration-weighted pitch-class histogram against 24 key
profiles, and a rebuilt stream preserves both pitch class and duration.

Key detection is the one analysis step in a phase that is otherwise
notation-only. It is confined to a section's *label*; it never moves a
boundary.

## Deferred: the tempo map

The parent spec's `Score` contract calls for a tempo map. `Score` keeps
its single `bpm` instead, and bar start times derive from it.

No available fixture has more than one tempo — the chorale and minuet
carry no tempo mark at all, and the ragtime carries a single `q=100`. A
tempo map would change how every note's start time is computed,
regenerating all three golden files, in service of a code path nothing
exercises.

The bar timeline is where a tempo map belongs when a fixture with a
tempo change arrives: bar start times become the integration points, and
`Bar` already carries the per-bar duration that would vary.

## The `sections` command

```
$ bitty sections tests/fixtures/minuet.mxl

Minuet in G  ·  q=120  ·  16 bars  ·  24.0s

  A   bars  1-8    3/4   G major   0:00.0   12.0s   repeat
  B   bars  9-16   3/4   D major   0:12.0   12.0s   repeat
```

Signature: `bitty sections SCORE`. No options.

Columns are fixed rather than conditional, so output is predictable to
read and to assert on. Both start time and duration appear because
choosing a loop needs both: one to seek to, one to judge whether the
section is long enough not to feel repetitive.

Two columns from the parent spec's sketch are absent. Texture, because
there is no texture analysis. The `auto-loop pick` line, because loop
selection is 4b.

Per-row tempo is absent because there is one tempo; it sits in the
header. When the tempo map arrives it becomes a column.

No `--json`. 4b imports `analyze` directly rather than shelling out, so
a machine-readable flag would ship with no caller.

## Testing

Three layers. The middle one needs no score file, which is a consequence
of `analyze` consuming our own dataclasses rather than music21's.

**`tests/test_analyze.py`, synthetic** — `Score`/`Bar` objects built in
the test, one case per boundary predicate: start repeat, end repeat,
final barline, time-signature change, key-signature change, no
boundaries at all, and label sequencing. This is what covers predicates
4 and 5, which no current fixture exercises. Shipping untested branches
in a rule engine is how a rule engine becomes untrustworthy.

**`tests/test_analyze.py`, fixtures** — the three real scores through to
the exact sections in the table above: bar ranges, keys, repeat flags.
Measured, not trusted.

**`tests/test_ingest.py`, additions** — the bar timeline against real
files: bar count and printed numbers, start times consistent with the
BPM, and repeat/barline flags landing on minuet bars 8 and 9 and ragtime
bars 1 and 16.

**`tests/test_cli.py`** — `bitty sections` on a fixture exits 0 and
prints the expected rows.

**The existing suite, unchanged.** All 128 existing tests must keep
passing with none of their assertions altered, and the three golden
arrangements must stay byte-identical. This phase touches nothing downstream of `Score`, so any
golden diff means the ingest extension disturbed note timing — a
failure, not something to regenerate.

## Risks

- **A piece with no marks reports as one section.** Accepted, and the
  reason texture analysis exists in the parent spec. The mitigation is
  4b's manual `--bars`, which the parent spec already expects to be the
  path for a meaningful share of tracks.
- **music21 bar numbering varies with source quality.** Pickup bars and
  inconsistent numbering are contributor-dependent. Bar numbers are
  reported as printed rather than renumbered, so `bitty sections` and
  `--bars` at least agree with each other and with the printed score.
- **Key detection on a short section is unreliable.** An eight-bar
  section gives Krumhansl-Schmuckler little to work with, and a
  chromatic passage less. The label is advisory; no decision in 4a or
  4b depends on it.

## What 4b inherits

- `Score.bars` — the bar timeline, so `--bars N-M` maps to seconds in
  one place.
- `analyze()` — sections with time ranges, the second tier of the loop
  cascade.
- `Bar.starts_repeat` / `ends_repeat` — the first and most trustworthy
  tier of the loop cascade, already parsed.
