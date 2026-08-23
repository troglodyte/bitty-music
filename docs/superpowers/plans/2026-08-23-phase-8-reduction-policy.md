# Phase 8: Reduction Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make silence a legitimate outcome of reduction, so the arpeggio stops
consuming 92.2% of the chorale at `count = 3`.

**Architecture:** A new `src/bitty/reduce.py` owns the *policy* — which overflow
notes survive — and returns one of three decisions (`Drop`, `Cycle`,
`Displace`). `arrange._arpeggiate` keeps the *mechanics* of building a cycle and
becomes a `match` over that decision. No pattern, no registry: the three rules
are categorical and the spec explicitly rejects tuning them.

**Tech Stack:** Python 3.11+, pytest, frozen dataclasses. Run everything with
`.venv/bin/python` and `.venv/bin/pytest` — there is no `uv` or bare `python` on
this machine.

**Spec:** `docs/superpowers/specs/2026-08-23-phase-8-reduction-policy-design.md`

## Global Constraints

- Python 3.11+ (`X | Y` unions and `match` are both used).
- No new dependencies.
- `reduce.py` must not import from `arrange.py` — `arrange` imports `reduce`.
  `reduce` may import `bitty.model`. A `_Take` must never cross the seam.
- Every new test is proven by deliberately breaking the implementation, watching
  it fail, then restoring. A test that passes the coarser implementation is not
  a test. This is a standing rule in this repo, not advice.
- `MIN_MEMBERS = 3` is a module constant in `reduce.py`, never config. The spec
  names it the only negotiable number and deliberately keeps it out of TOML.
- Metric definition: **arp share** is arpeggiated duration as a fraction of the
  carrier channel's total sounding duration.

---

### Task 1: Quality metrics for arp share and hollow chords

Build the measurement before the change, so Task 5's diff is verifiable against
the spec's table rather than trusted.

**Files:**
- Modify: `tests/test_quality.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_arp_share(arrangement, roster) -> float`,
  `_hollow(score, arrangement, roster) -> tuple[int, int]` returning
  `(hollow, chords)`, and the `REDUCTION` baseline dict keyed by
  `(fixture_name, count)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_quality.py`:

```python
from dataclasses import replace

from bitty.arrange import _assign
from bitty.config import DEFAULTS
from bitty.voices import Roster

THIRDS = (3, 4)  # minor and major; a tenth is a third folded into the octave

# (fixture, count): (max arp share %, max hollow chords)
# Anchored to `main` before Phase 8. Nothing is dropped today, so nothing can
# go hollow — every hollow ceiling here is 0 by construction, not by luck.
REDUCTION = {
    ("chorale", 3): (92.3, 0),
    ("chorale", 4): (0.1, 0),
    ("chorale", 5): (0.1, 0),
    ("minuet", 3): (66.8, 0),
    ("minuet", 4): (0.1, 0),
    ("minuet", 5): (0.1, 0),
    ("ragtime", 3): (59.9, 0),
    ("ragtime", 4): (41.6, 0),
    ("ragtime", 5): (15.7, 0),
}


def _sounding(takes, onset):
    """The takes on one channel still ringing at `onset`."""
    return [t for t in takes if t.t <= onset + EPSILON and t.t + t.dur > onset + EPSILON]


def _arp_share(arrangement, roster):
    """Arpeggiated duration as a fraction of the carrier's sounding duration."""
    events = next(
        (c.events for c in arrangement.channels if c.role == roster.arp), ()
    )
    total = sum(e.dur for e in events)
    arped = sum(e.dur for e in events if e.arp)
    return 100.0 * arped / total if total else 0.0


def _hollow(score, arrangement, roster):
    """Overflow chords that had a third and end up without one.

    Measured at the onsets where reduction actually had a decision to make,
    which is what the policy is answerable for. The bass reference is the
    arrangement's own bass channel: a third is a third above what is heard
    underneath it, not above a note that was itself reduced away.
    """
    tracks, leftovers = _assign(score, roster)
    played = {c.role: c.events for c in arrangement.channels}

    def pitch_classes(onset):
        out = set()
        for events in played.values():
            for event in _sounding(events, onset):
                for offset in event.arp or (0,):
                    out.add((event.pitch + offset) % OCTAVE)
        return out

    hollow = chords = 0
    for onset, notes in leftovers:
        bass = _sounding(played.get(roster.bass, ()), onset)
        if not bass:
            continue
        root = bass[0].pitch
        before = {n.pitch % OCTAVE for n in notes} | {
            t.pitch % OCTAVE
            for takes in tracks.values()
            for t in _sounding(takes, onset)
        }
        if not any((p - root) % OCTAVE in THIRDS for p in before):
            continue  # the chord never had a third to lose
        chords += 1
        if not any((p - root) % OCTAVE in THIRDS for p in pitch_classes(onset)):
            hollow += 1
    return hollow, chords


@pytest.mark.parametrize("name,count", sorted(REDUCTION))
def test_the_reduction_stays_within_its_arp_and_hollow_ceilings(name, count):
    """The arpeggio's share of the piece, and the harmony it costs to shrink it.

    Phase 7's re-audition named this share as the defect. A ceiling rather than
    an equality: the numbers may improve without editing this table, but a
    silent regression back toward a carrier that trills through the whole piece
    fails here.
    """
    max_share, max_hollow = REDUCTION[(name, count)]
    roster = Roster(count=count)
    score = ingest(FIXTURES / f"{name}.mxl")
    arrangement = arrange(score, replace(DEFAULTS, voices=roster))

    share = _arp_share(arrangement, roster)
    hollow, _ = _hollow(score, arrangement, roster)

    assert share <= max_share, f"{name} count={count} arp share {share:.1f}%"
    assert hollow <= max_hollow, f"{name} count={count} hollow chords {hollow}"
```

- [ ] **Step 2: Run the test to see it pass against today's code**

Run: `.venv/bin/pytest tests/test_quality.py -k ceilings -v`
Expected: 9 PASS. These ceilings describe `main` as it stands.

- [ ] **Step 3: Prove the test by breaking the implementation**

The ceilings only matter if they can fail. In `src/bitty/arrange.py`, inside
`_arpeggiate`, force every cycle to stretch by changing:

```python
        span = max(span, len(pitches) * rate_sec)
```

to:

```python
        span = max(span, len(pitches) * rate_sec * 8)  # DELIBERATE BREAK
```

- [ ] **Step 4: Run the test and watch it fail**

Run: `.venv/bin/pytest tests/test_quality.py -k ceilings -v`
Expected: FAIL on several `(name, count)` cases with "arp share" over the
ceiling. If everything still passes, the metric is not measuring what it claims
and must be fixed before proceeding.

- [ ] **Step 5: Restore the implementation**

Revert the `* 8` edit. Re-run `.venv/bin/pytest tests/test_quality.py -v` and
confirm 9 PASS again.

- [ ] **Step 6: Commit**

```bash
git add tests/test_quality.py
git commit -m "test: measure the arpeggio's share of the piece and what it costs"
```

---

### Task 2: The redundancy rule

**Files:**
- Create: `src/bitty/reduce.py`
- Test: `tests/test_reduce.py`

**Interfaces:**
- Consumes: `bitty.model.Note`.
- Produces: `Drop`, `Cycle(pitches: tuple[int, ...], keep: tuple[Note, ...])`,
  `Displace(pitch: int)`, the union alias `Decision`, and
  `decide(notes: tuple[Note, ...], carrier: tuple[int, ...], sounding:
  frozenset[int], others: frozenset[int], bass: int | None) -> Decision`.
  Tasks 3 and 4 extend `decide` without changing this signature.

- [ ] **Step 1: Write the failing test**

Create `tests/test_reduce.py`:

```python
"""The reduction policy: which overflow notes survive, and as what."""

from bitty.model import Note
from bitty.reduce import Cycle, Displace, Drop, decide


def note(pitch, start=0.0, dur=1.0, velocity=80):
    return Note(pitch=pitch, start=start, dur=dur, velocity=velocity,
                part=0, beat_strength=1.0)


def test_a_note_already_sounding_is_dropped():
    """It adds nothing the ear can hear, so it does not earn a channel."""
    # E4 (64) overflows, but an E is already sounding: pitch class 4.
    result = decide(
        notes=(note(64),),
        carrier=(60,),
        sounding=frozenset({0, 4, 7}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert result == Drop()


def test_redundancy_is_judged_by_pitch_class_not_pitch():
    """An E5 is as redundant as an E4 when an E is already ringing."""
    result = decide(
        notes=(note(76),),  # E5
        carrier=(60,),
        sounding=frozenset({0, 4, 7}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert result == Drop()


def test_a_new_pitch_class_survives_as_a_cycle():
    """Three distinct pitches after the fold is a chord worth arpeggiating."""
    # Carrier holds C4 (60); B-flat4 (70) and D5 (74) overflow. Neither is
    # sounding, so both survive: {60, 70, 74} folds to C4, D4, B-flat4.
    result = decide(
        notes=(note(70), note(74)),
        carrier=(60,),
        sounding=frozenset({0}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert isinstance(result, Cycle)
    assert result.pitches == (60, 62, 70)
    assert tuple(n.pitch for n in result.keep) == (70, 74)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_reduce.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bitty.reduce'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/bitty/reduce.py`:

```python
"""Which notes survive reduction.

The arranger places what it can; this decides the fate of what is left over.
Overflow used to be unconditional — any note without a free channel became
arpeggio, however little it contributed — and that is how the carrier came to
trill through 92.2% of the chorale.

Policy only. Building the cycle is `arrange._arpeggiate`'s job, which is why
nothing here knows what a `_Take` is.
"""

from __future__ import annotations

from dataclasses import dataclass

from bitty.model import Note

OCTAVE = 12
MIN_MEMBERS = 3  # two pitches alternating is a trill; naming a chord takes three


@dataclass(frozen=True)
class Drop:
    """The overflow is silent. The carrier keeps whatever it already held."""


@dataclass(frozen=True)
class Cycle:
    """The overflow becomes an arpeggio.

    `pitches` are absolute and already folded into one octave. `keep` is the
    surviving overflow, which the caller needs for the cycle's span and
    velocity and which this module deliberately does not decide.
    """

    pitches: tuple[int, ...]
    keep: tuple[Note, ...]


@dataclass(frozen=True)
class Displace:
    """The carrier's own note is rewritten to `pitch` and stays a plain note."""

    pitch: int


Decision = Drop | Cycle | Displace


def decide(
    notes: tuple[Note, ...],
    carrier: tuple[int, ...],
    sounding: frozenset[int],
    others: frozenset[int],
    bass: int | None,
) -> Decision:
    """The fate of one onset's overflow.

    `sounding` is every pitch class audible at this onset, the carrier
    included; `others` excludes the carrier, because a rule about replacing
    the carrier's note cannot count that note as evidence.
    """
    keep = tuple(n for n in notes if n.pitch % OCTAVE not in sounding)
    if not keep:
        return Drop()
    return Cycle(pitches=_fold({n.pitch for n in keep} | set(carrier)), keep=keep)


def _fold(members: set[int]) -> tuple[int, ...]:
    """Every member into the octave above the lowest.

    Overflow arrives in whatever register it was written in, and a cycle that
    leaps an octave and a fourth is a siren rather than a chord. A chip
    arpeggio names a chord by cycling its members close together, so pitch
    class is what is worth keeping and register is what is spent to keep it.
    Folding before the set is built also collapses members an octave apart
    into one step instead of cycling the same pitch class twice.
    """
    low = min(members)
    return tuple(sorted({low + (pitch - low) % OCTAVE for pitch in members}))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_reduce.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Prove the redundancy test by breaking the rule**

In `decide`, change `if n.pitch % OCTAVE not in sounding` to `if True`. Run
`.venv/bin/pytest tests/test_reduce.py -v` and confirm the two drop tests FAIL.
Restore, and confirm 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/reduce.py tests/test_reduce.py
git commit -m "feat: drop overflow whose pitch class is already sounding"
```

---

### Task 3: The chord rule

**Files:**
- Modify: `src/bitty/reduce.py`
- Test: `tests/test_reduce.py`

**Interfaces:**
- Consumes: `decide`, `Drop`, `Cycle`, `MIN_MEMBERS` from Task 2.
- Produces: no signature change. `decide` now returns `Drop()` when the folded
  set has fewer than `MIN_MEMBERS` pitches.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reduce.py`:

```python
def test_two_pitches_are_a_trill_not_an_arpeggio():
    """Phase 7 fixed how these cycles sound; this decides they should not exist.

    A chip arpeggio names a chord by cycling its members. Two notes name
    nothing, and every point of the chorale's 92.2% was one of these.
    """
    result = decide(
        notes=(note(67),),           # G4 overflows
        carrier=(60,),               # carrier holds C4
        sounding=frozenset({0}),
        others=frozenset({0, 4}),    # a third is already present elsewhere
        bass=48,
    )
    assert result == Drop()


def test_a_lone_pitch_is_not_a_cycle_either():
    """The minuet carried a one-member `arp`, a plain note with its vibrato
    suppressed for no reason. The same rule removes it."""
    result = decide(
        notes=(note(72),),           # C5 folds onto the carrier's C4
        carrier=(60,),
        sounding=frozenset(),
        others=frozenset({0, 4}),
        bass=48,
    )
    assert result == Drop()


def test_three_pitches_still_survive():
    """The rule removes trills, not arpeggios."""
    result = decide(
        notes=(note(70), note(74)),
        carrier=(60,),
        sounding=frozenset({0}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert isinstance(result, Cycle)
    assert len(result.pitches) == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_reduce.py -v`
Expected: `test_two_pitches_are_a_trill_not_an_arpeggio` and
`test_a_lone_pitch_is_not_a_cycle_either` FAIL — both currently return a
`Cycle`. `test_three_pitches_still_survive` passes already.

- [ ] **Step 3: Write the minimal implementation**

In `src/bitty/reduce.py`, replace the return in `decide` with:

```python
    pitches = _fold({n.pitch for n in keep} | set(carrier))
    if len(pitches) < MIN_MEMBERS:
        return Drop()
    return Cycle(pitches=pitches, keep=keep)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_reduce.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Prove the rule excludes the coarser implementation**

Change `MIN_MEMBERS` to `2`. Run the tests: the two-pitch test must FAIL, which
is what proves it rejects a policy that merely bans one-member cycles. Restore
`MIN_MEMBERS = 3` and confirm 6 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/reduce.py tests/test_reduce.py
git commit -m "feat: require three pitches for a cycle to be an arpeggio"
```

---

### Task 4: The third rescue

**Files:**
- Modify: `src/bitty/reduce.py`
- Test: `tests/test_reduce.py`

**Interfaces:**
- Consumes: everything from Tasks 2-3.
- Produces: no signature change. `decide` may now return `Displace(pitch)`.
  `arrange` must handle that case in Task 5.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reduce.py`:

```python
def test_the_only_third_displaces_a_redundant_doubling():
    """Rules 1 and 2 choose by pitch height and never by harmonic function, so
    the third is lost whenever the inner part below happens to hold it."""
    # Bass C3 (48). Carrier holds G4 (67) — a fifth, already doubled in
    # `others`. E4 (64) overflows and is the chord's only third.
    result = decide(
        notes=(note(64),),
        carrier=(67,),
        sounding=frozenset({0, 7}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert result == Displace(pitch=64)


def test_no_rescue_when_a_third_already_sounds():
    """Nothing is at risk, so nothing is worth disturbing the line for."""
    result = decide(
        notes=(note(64),),
        carrier=(67,),
        sounding=frozenset({0, 7}),
        others=frozenset({0, 4, 7}),  # E already present elsewhere
        bass=48,
    )
    assert result == Drop()


def test_no_rescue_when_the_carrier_note_is_not_redundant():
    """Swapping would trade one loss for another, so the line wins."""
    # Carrier holds A4 (69), pitch class 9, which nothing else is playing.
    result = decide(
        notes=(note(64),),
        carrier=(69,),
        sounding=frozenset({0, 7, 9}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert result == Drop()


def test_a_tenth_counts_as_a_third():
    """A third an octave up is the same harmonic fact."""
    result = decide(
        notes=(note(76),),  # E5, a tenth above C3
        carrier=(67,),
        sounding=frozenset({0, 7}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert result == Displace(pitch=76)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_reduce.py -v`
Expected: `test_the_only_third_displaces_a_redundant_doubling` and
`test_a_tenth_counts_as_a_third` FAIL, returning `Drop()` instead of
`Displace`. The two negative tests already pass.

- [ ] **Step 3: Write the minimal implementation**

In `src/bitty/reduce.py`, add the constant beside `MIN_MEMBERS`:

```python
THIRDS = (3, 4)  # minor and major; a tenth is a third folded into the octave
```

Replace the `len(pitches) < MIN_MEMBERS` branch in `decide` with:

```python
    if len(pitches) < MIN_MEMBERS:
        rescued = _only_third(keep, others, bass)
        if rescued is not None and carrier and all(
            pitch % OCTAVE in others for pitch in carrier
        ):
            return Displace(pitch=rescued)
        return Drop()
```

and add:

```python
def _only_third(keep: tuple[Note, ...], others: frozenset[int], bass: int | None) -> int | None:
    """The pitch of a surviving note that is the chord's sole third.

    The third is what tells a major chord from a minor one; the fifth above a
    sounding root is the tone a three-voice reduction is supposed to spend.
    Losing the third to keep a doubling gets that backwards.
    """
    if bass is None:
        return None
    if any((pitch - bass) % OCTAVE in THIRDS for pitch in others):
        return None
    return next(
        (n.pitch for n in keep if (n.pitch - bass) % OCTAVE in THIRDS), None
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_reduce.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Prove the guards by breaking each**

Two guards, proven separately — this is the step where a rescue rule usually
turns out to be an unconditional swap:

1. Delete `and all(pitch % OCTAVE in others for pitch in carrier)`. Run the
   tests: `test_no_rescue_when_the_carrier_note_is_not_redundant` must FAIL.
   Restore it.
2. Delete the `if any(... for pitch in others): return None` guard in
   `_only_third`. Run the tests: `test_no_rescue_when_a_third_already_sounds`
   must FAIL. Restore it.

Confirm 10 PASS after both restorations.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/reduce.py tests/test_reduce.py
git commit -m "feat: let a chord's only third displace a redundant doubling"
```

---

### Task 5: Wire the policy into the arranger

This is the only task that changes audible output. Goldens and the Task 1
ceilings both move here.

**Files:**
- Modify: `src/bitty/arrange.py` (`arrange`, `_arpeggiate`)
- Modify: `tests/test_quality.py` (the `REDUCTION` table)
- Modify: `tests/goldens/ragtime.arrangement.json`

**Interfaces:**
- Consumes: `decide`, `Cycle`, `Displace`, `Drop` from Tasks 2-4.
- Produces: `_arpeggiate(leftovers, tracks, roster, rate_sec) -> list[_Take]`.
  Note the changed signature — it now takes the whole `tracks` dict and the
  roster, because the policy is judged against the full texture rather than
  against the carrier alone.

- [ ] **Step 1: Change the call site**

In `src/bitty/arrange.py`, add to the imports:

```python
from bitty.reduce import Cycle, Displace, decide
```

In `arrange`, replace:

```python
    tracks[roster.arp] = _arpeggiate(
        leftovers, tracks[roster.arp], carrier.instrument.arp_rate_sec
    )
```

with:

```python
    tracks[roster.arp] = _arpeggiate(
        leftovers, tracks, roster, carrier.instrument.arp_rate_sec
    )
```

- [ ] **Step 2: Rewrite `_arpeggiate` around the decision**

Replace the body of `_arpeggiate` with:

```python
def _arpeggiate(
    leftovers: list[tuple[float, list[Note]]],
    tracks: Tracks,
    roster: Roster,
    rate_sec: float,
) -> list[_Take]:
    """Give the overflow to the policy, then build what it asks for.

    One take per cycle, not one per step. A chip arpeggio is a single note
    whose pitch register is rewritten each frame while its envelope keeps
    running; a fresh note per step restarts the envelopes 60 times a second,
    which is how every step came to sound a whole tone sharp on an instrument
    with a pitch envelope.

    `tracks` is read, never written: the policy judges each onset against the
    texture as `_assign` left it, so an earlier cycle cannot change the verdict
    on a later one. The carrier's own notes arrive through `out`.
    """
    out = list(tracks[roster.arp])

    for onset, notes in leftovers:
        # Partition rather than remove-by-value: `_Take` is a mutable dataclass
        # with structural equality, so `list.remove` would match any take that
        # merely looks the same.
        absorbed = [take for take in out if abs(take.t - onset) <= EPSILON]
        decision = decide(
            notes=tuple(notes),
            carrier=tuple(take.pitch for take in absorbed),
            sounding=_pitch_classes(tracks, onset),
            others=_pitch_classes(tracks, onset, without=roster.arp),
            bass=_held(tracks[roster.bass], onset),
        )

        match decision:
            case Displace(pitch=pitch):
                # A plain note, not a cycle: the carrier sings the third
                # instead of the doubling, and its duration is untouched so
                # nothing can overlap what follows.
                for take in absorbed:
                    take.pitch = pitch
            case Cycle(pitches=pitches, keep=keep):
                out = [take for take in out if abs(take.t - onset) > EPSILON]
                # The cycle lasts only as long as its shortest member: a note
                # that has ended must not keep sounding just because the
                # arpeggio is still running. But it owes every member one step
                # — a short dense chord must still sound every note it was
                # handed.
                span = min([n.dur for n in keep] + [take.dur for take in absorbed])
                span = max(span, len(pitches) * rate_sec)
                vel = max([_velocity(n) for n in keep] + [take.vel for take in absorbed])
                out.append(
                    _Take(
                        t=onset,
                        pitch=pitches[0],
                        dur=span,
                        vel=vel,
                        arp=tuple(pitch - pitches[0] for pitch in pitches),
                    )
                )
            case _:  # Drop
                pass

    return _clip_overlaps(sorted(out, key=lambda take: take.t))


def _held(takes: list[_Take], onset: float) -> int | None:
    """The pitch this channel is sounding at `onset`, scanning the whole line.

    `_sounding` inspects only the last take, which is right while `_assign` is
    still appending to it and wrong once the line is complete: by the time the
    policy runs, the note at `onset` is somewhere in the middle.
    """
    for take in takes:
        if take.t <= onset + EPSILON and take.t + take.dur > onset + EPSILON:
            return take.pitch
    return None


def _pitch_classes(tracks: Tracks, onset: float, *, without: str | None = None) -> frozenset[int]:
    """Every pitch class audible at `onset`, optionally ignoring one channel."""
    return frozenset(
        take.pitch % 12
        for role, takes in tracks.items()
        if role != without
        for take in takes
        if take.t <= onset + EPSILON and take.t + take.dur > onset + EPSILON
    )
```

Add `Roster` to the `bitty.voices` import line if it is not already there.

- [ ] **Step 3: Run the full suite and expect goldens and ceilings to fail**

Run: `.venv/bin/pytest tests/ -v`
Expected: `tests/test_reduce.py` all PASS; `test_arrangement_matches_its_golden[ragtime]`
FAILS; several `test_the_reduction_stays_within_its_arp_and_hollow_ceilings`
cases FAIL because the hollow ceilings are still 0. Chorale and minuet goldens
must still PASS — neither overflows at `count = 5`, so a failure there means
the rewrite changed something it had no business touching. Stop and diagnose if
they fail.

- [ ] **Step 4: Update the ceilings to the spec's measured numbers**

In `tests/test_quality.py`, replace the `REDUCTION` table with:

```python
# (fixture, count): (max arp share %, max hollow chords)
# Phase 8. The arp shares come from the spec's measured-outcome table; the
# hollow counts are the harmony that shrinking them costs, which rule 3
# reduces but does not eliminate.
REDUCTION = {
    ("chorale", 3): (0.1, 7),
    ("chorale", 4): (0.1, 0),
    ("chorale", 5): (0.1, 0),
    ("minuet", 3): (0.1, 0),
    ("minuet", 4): (0.1, 0),
    ("minuet", 5): (0.1, 0),
    ("ragtime", 3): (26.2, 4),
    ("ragtime", 4): (2.2, 5),
    ("ragtime", 5): (2.2, 0),
}
```

- [ ] **Step 5: Run the ceilings and reconcile against the spec**

Run: `.venv/bin/pytest tests/test_quality.py -k ceilings -v`
Expected: 9 PASS.

If any case fails, do **not** widen the ceiling to make it pass. The spec's
table is the prediction this phase is accountable to; a mismatch means the
implementation diverges from what was prototyped, and the divergence is the
finding. Report it rather than absorbing it.

- [ ] **Step 6: Regenerate the ragtime golden and read the diff**

```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
git diff --stat tests/goldens/
```

Only `ragtime.arrangement.json` may change. Read the diff and confirm it shows
what the spec predicts: `inner_b` loses seven two-member `arp` events, seven
events gain a rewritten pitch from the rescue, and one three-member cycle
survives. A changed chorale or minuet golden is a bug, not a result.

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/bitty/arrange.py tests/test_quality.py tests/goldens/ragtime.arrangement.json
git commit -m "feat: apply the reduction policy to overflow"
```

---

### Task 6: Document the policy

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-23-phase-8-reduction-policy-design.md`

**Interfaces:**
- Consumes: the finished behaviour from Task 5.
- Produces: nothing code depends on.

- [ ] **Step 1: Correct the two README passages this phase falsifies**

Both currently state the opposite of what the code will do.

First, in the **How it works** section, the `arrange` paragraph ends:

```
Anything that finds no channel at all is folded into a fast-cycling
arpeggio rather than dropped.
```

Replace that sentence with:

```
Anything that finds no channel at all goes to the reduction policy, which
drops it, folds it into an arpeggio, or lets it displace a doubling:

1. A leftover whose pitch class is already sounding is dropped — it adds
   nothing the ear can hear.
2. What survives becomes an arpeggio only if it makes a cycle of three or
   more distinct pitches. Two notes alternating is a trill, not a chord, so
   the leftover is dropped and the channel keeps its own note.
3. If that would cost the chord its only third, and the channel's own note
   is a doubling of something already sounding, the third takes its place.

Silence is a real outcome. Reducing four-part writing to three voices means
a part goes, and a piece that arpeggiates everything it cannot fit spends
its whole texture on the overflow.
```

Second, in the **`[voices] count`** section, the paragraph beginning
`**Count 3 is legal but not yet musical for a dense score.**` is stale in
three ways: its 819-event and 16 ms figures predate Phase 7's 48 ms step, and
its closing "not yet done" is what this phase does. Replace the whole
paragraph with:

```
**Count 3 leans on the reduction policy.** With only one middle voice,
`_pick_middle` can place at most one note per onset and everything else
overflows. Before the policy existed that overflow dominated — the chorale's
carrier arpeggiated through 92.2% of the piece, all of it two-note trills.
The policy drops what is already sounding and refuses to arpeggiate anything
that cannot name a chord, which takes the chorale and the minuet to no
arpeggio at all and ragtime to 26.1%. The cost is harmonic: a few chords per
piece lose their third where no doubling was free to displace.
```

Leave `nes-tight` at `count = 4`. Whether the policy earns it a move back to
3 is the audition's call, not this task's.

- [ ] **Step 2: Record the outcome in the spec**

Append an "Outcome" section to the spec giving the arp shares and hollow counts
the suite now enforces, matching the shape of the audition records that close
the Phase 6 and Phase 7 specs. Leave the audition itself unrecorded — it has
not happened yet.

- [ ] **Step 3: Verify the docs build and nothing else moved**

Run: `.venv/bin/pytest tests/ -v && git status --short`
Expected: all PASS; only `README.md` and the spec modified.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-08-23-phase-8-reduction-policy-design.md
git commit -m "docs: document the reduction policy"
```

---

## After the plan

The spec names an **audition** as this phase's real gate, and it is not one of
the tasks above because it needs ears, not a test run. Two things must be
listened to, not just measured:

1. `count = 3` on the chorale and the minuet, which now arpeggiate not at all.
   The question the numbers cannot answer is whether a three-voice chorale
   sounds reduced or sounds thin.
2. The `nes-tight` preset on ragtime, where the arpeggio falls from 41.5% to
   2.1%, and `DEFAULTS`, where it falls from 15.6% to 2.1%. Phase 7
   auditioned and accepted both; this phase changes them. If
   the stride idiom wants its arpeggios back, `MIN_MEMBERS` is the one number
   to negotiate.

Render WAV, never Ogg — `aplay` renders Ogg as static.

Record the verdict in the spec the way Phases 6 and 7 did, including what was
rejected. `nes-tight`'s `count` may need revisiting once the policy is in.
