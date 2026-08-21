# Phase 3b — Articulation — Design

**Date:** 2026-08-21
**Status:** Approved, ready for implementation planning

## Goal

Make the arranged notes *behave* like performed notes. Phase 3a settled who
plays what; nothing since decides how a note is struck or held. Three strands,
in the order they matter audibly:

- **Dynamics.** Every event in every golden is `vel: 8`. The 16-level quantizer
  works, but nothing ever feeds it anything but the ingest default, so the
  output is uniformly loud from first note to last.
- **Vibrato.** Chip voices have no natural decay, so a held note is dead air.
  The spec calls delayed vibrato the largest single contributor to sounding
  like chiptune rather than a MIDI dump.
- **Ornaments.** Grace notes currently sound *simultaneously* with the note
  they decorate, as a 32 ms cluster. Trills and mordents are dropped entirely
  and render as plain held notes.

Phase 3b does not change who plays what. The channel assignment 3a's
acceptance listen approved is a fixed point, and the design below is measured
against it rather than trusted to preserve it.

## What the fixtures actually contain

Measured on the checked-in goldens and fixtures, 2026-08-21. These numbers
scoped the phase and belong in the record:

| | chorale | minuet | ragtime |
|---|---|---|---|
| events | 144 | 156 | 407 |
| velocity histogram | all `8` | all `8` | all `8` |
| events ≥ 500 ms | 96 | 128 | 6 |
| written dynamics | none | 14 (`f`, `fp`, `p`) | 2 (`f`, `mf`) |
| grace notes | 0 | 2 | 0 |
| trills / mordents / turns | 0 | 0 | 0 |
| other expressions | 5 fermatas | — | — |

Three consequences:

- Vibrato at the spec's 500 ms threshold has real reach on the two slow
  fixtures and almost none on the ragtime. That is the correct behaviour, not
  a threshold to tune around.
- **Written dynamics alone are not enough.** The chorale carries no markings at
  all, so a faithful-only implementation would leave 96 sustained notes as flat
  as they are today. Metric accent is what gives every fixture variation.
- **Ornaments have almost no fixture surface.** Two grace notes, no trills. The
  ornament work is therefore justified by correctness, not by what these three
  excerpts will demonstrate, and needs a purpose-made fixture to be testable.

## Decisions settled in dialog (2026-08-21)

Not open for re-litigation mid-execution.

- **Ornaments resolve at ingest, not at arrange.** Trills, mordents, turns and
  grace notes become ordinary notes with real durations before the arranger
  sees them.
- **Dynamics come from written markings *and* metric accent.** Faithful-only
  was considered and rejected because it leaves the chorale flat. The accent is
  acknowledged as synthesized: the composer did not write it.
- **Vibrato is a flat `bool` on `Event`.** The spec's contract example shows a
  nested `"effects": {"vibrato": true}`; this is a deliberate divergence, see
  below.
- **Fermatas, hairpins, and every config knob are out of scope.** Depth, delay
  and threshold stay module constants until Phase 5.

### Why ornaments resolve at ingest

The alternative — an ornament pass in `arrange.py` — keeps `ingest` a plain
transcriber, and was rejected on two grounds.

First, it puts performance-practice knowledge in the wrong file. That a grace
note borrows time from the note it decorates is a fact about how the score is
read, not a decision about chiptune. `ingest` owns what the score says;
`arrange` owns what chiptune does with it.

Second, and decisively: every ornament workaround in the 3a arranger exists
*only* because music21 hands over grace notes with `dur == 0.0`. Resolving them
upstream deletes all of it —

- the `pending` / `graces` split in `_assign`
- the `GRACE_SEC` floor in `_place`
- the `ornament` flag on `_Take`
- the ornament skip in `_last_pitch`

— and returns the arranger to a single rule: place notes by voice leading. A
grace becomes a short note sounding just before its principal, usually landing
on the same channel, which is exactly the spec's "ornaments render as fast
notes."

**The risk this carries.** Those four workarounds were not speculative; two of
them were written during the 3a acceptance listen to fix audible defects, and
the recorded gains are large (minuet lead purity 93.2% → 97.4%, ragtime 82.5% →
96.6%, ragtime octave-plus leaps 15 → 0). Deleting them on the argument that
their cause is gone is sound but unproven. The verification section below
measures it rather than assuming it.

### Why vibrato is a flat field

`Instrument` documents the house rule: *"Flat rather than nested because this
is the hand-edit surface: a person fixing a passage in `arrangement.json`
should not have to navigate a tree."* A nested `effects` dict contradicts that,
invites unvalidated keys, and buys extensibility that Phase 3a explicitly
deferred when it ruled per-note effects out of scope. The spec's JSON block is
an illustration, not a schema; this design overrules it and says so.

## Stage: ingest

Three additions to `src/bitty/ingest.py`.

**Written dynamics.** Each part's `Dynamic` markings resolve in offset order;
`Dynamic.volumeScalar` scaled to 0–127 sets the velocity of every following
note in that part until the next mark. Notes before the first mark, and notes
in parts with no marks, keep `DEFAULT_VELOCITY`. Markings are per-part in all
three fixtures and are treated that way.

**Beat strength.** `Note` gains `beat_strength: float`, taken from music21's
`beatStrength`. This is a score fact derived from the time signature — it
handles compound meter correctly and is not something to hand-roll from
`offset % bar_length`. The minuet spreads across three levels (1.0 / 0.5 /
0.25), which is enough resolution to accent with.

**Ornament realization.** Trills, mordents, inverted mordents and turns expand
via `Ornament.realize(note, keySig=...)`, which returns a `(before, main,
after)` triple of real notes with real durations. `main` is `None` for a trill
or a turn, where the realization replaces the note outright, and is the
original note for a mordent; both cases are handled.

Grace notes — arriving with `quarterLength == 0` — become short notes placed
before their principal, which is shortened to make room, so the pair occupies
the principal's original span and nothing downstream shifts. The grace takes
32 ms, capped at half the principal's duration so an ornament on an already
short note cannot swallow it.

> **Trap, verified 2026-08-21.** The stream-level
> `expressions.realizeOrnaments()` silently returns the note *unchanged* on
> music21 10.5.0 — no error, no expansion. Only the per-ornament
> `.realize(note, keySig=...)` works. A test that asserts an ornament expanded
> is the only thing that will catch a regression here.

Post-condition: no `Note` leaving `ingest` has `dur == 0.0`.

## Stage: arrange

Net simpler than it is today.

**Deletions.** The four ornament workarounds listed above, now that their cause
is gone.

**Accent-aware velocity.** `_quantize_velocity` grows from a pure 127→15 scale
into the phase's one piece of dynamic policy, applied in this order: the
written velocity quantizes to the 16 levels the spec requires, *then* a metric
offset is added, *then* the result is clamped to `1 .. MAX_VELOCITY` so an
accent can neither silence a note nor exceed the ceiling.

The offset by beat strength is `+2` for a downbeat (1.0), `0` for a secondary
strong beat (0.5), and `-1` for anything weaker. On the `DEFAULT_VELOCITY` that
the chorale's unmarked notes carry, that is a 7 / 8 / 10 spread — modest and
audible, which is the intent. These three numbers are the first thing to
adjust if the acceptance listen finds the accent too strong or too subtle; they
are policy, not structure.

**Vibrato flagging.** Events whose duration clears the minimum are written with
`vibrato=True`. The duration tested is the event's *final* duration, after the
arranger has truncated it for a stolen channel — a note cut short by a
re-entering voice should not vibrate on the strength of the length it was
originally written at. The arranger decides *which* notes vibrate; the synth decides
*how*. This is what makes it hand-editable — turning off one note's vibrato is
a one-word edit to `arrangement.json`, per the spec's "the JSON overrules the
result."

## Contract change

`Event` gains `vibrato: bool = False`. Defaulted, so every existing
hand-written arrangement still loads.

While the contract is open, `_channel_from` gets the unknown-field tolerance
that `_instrument_from` already documents and implements. Today `Event(**event)`
raises on any field it does not recognize, so an arrangement written by a newer
bitty fails to load outright instead of rendering what this build understands —
the exact failure `_instrument_from` was written to avoid. Adding a field to
`Event` is what makes this reachable, so it is fixed here rather than left as a
trap for Phase 5.

## Stage: synth

A vibrato LFO modulating the per-sample frequency increment, applied only to
events carrying the flag: silent for `vibrato.delay_ms`, then fading in to
`vibrato.depth_cents`. It composes with the existing pitch-envelope blip rather
than replacing it — the blip is the attack, the vibrato is the sustain.

Constants take the spec's values: 25 cents depth, 300 ms delay, 500 ms minimum
note. The delay is what keeps this from sounding seasick; vibrato from the
instant of attack is the characteristic way this effect goes wrong.

**Open structural question, deliberately not answered here.** Whether the LFO
is a new module or belongs in `envelope.py` is a boundary decision, and
`envelope.py` is specifically about *step sequences* — a continuous LFO is a
different idea wearing a similar name. Per the repository's standing
instruction, the `design-patterns` dialog runs on this boundary before the
implementation plan fixes it. The spec deliberately describes the behaviour and
leaves the file layout to that dialog.

## Verification

The goldens change wholesale — every event gains a velocity and most gain a
vibrato flag — so a green diff proves nothing about whether the arrangement
survived. Three layers, in order:

1. **Test suite.** Including a test that asserts an ornament actually expanded
   (see the trap above), and a test that no note leaves `ingest` with zero
   duration.
2. **Measurement against 3a's recorded table.** Lead purity, bass purity, and
   octave-plus leaps on all three fixtures, compared to minuet 97.4% / ragtime
   96.6% / ragtime leaps 0. This is what proves the four deletions cost
   nothing. A regression here is a reason to stop, not to proceed to a listen.
3. **Acceptance listen.** Handed over as WAV, never Ogg. Its outcome is
   recorded in the plan, as Phases 1, 2 and 3a each did.

A velocity histogram that is no longer a single spike is the cheapest signal
that the dynamics work landed at all.

## Exit criteria

- `.venv/bin/pytest` passes.
- No event in any golden has `dur == 0.0`, and no grace note sounds
  simultaneously with the note it decorates.
- A trill in a purpose-made fixture renders as alternating fast notes.
- Velocity varies across all three fixtures, including the chorale, which
  carries no written dynamics.
- Sustained notes vibrate after a delay; notes under the minimum do not.
- Lead and bass purity hold at or above the percentages 3a's acceptance listen
  recorded, and octave-plus leaps at or below its counts.
- `bitty render` still round-trips a hand-edited arrangement, now including
  `vibrato`.
- The acceptance listen has happened and its outcome is recorded.

## Deferred

Fermatas (5 in the chorale; not in the spec's articulation rules). Hairpins —
`Crescendo` / `Diminuendo` spanners — because no fixture contains one and
interpolating an unheard effect is speculative. All config surface: `[vibrato]`
depth, delay and minimum, and `[dynamics] levels`, remain module constants
until Phase 5's config work, which is where the spec puts them.
