# Phase 10: percussion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `[percussion]` config table that puts a meter-driven drum groove on one noise channel — off by default, so nothing that exists today moves.

**Architecture:** One new module, `src/bitty/percussion.py`, with one pure function `groove(bars, bpm, level) -> tuple[Event, ...]`. It reads a table of patterns keyed by time signature, places each bar's hits at `bar.start + quarters * 60/bpm`, and resolves them into a monophonic channel by a priority pass with a seconds floor. `arrange()` appends one more `Channel` when `config.percussion.enabled`. The `perc` voice is declared in `voices.py` but is deliberately **not** in the `VOICES` tuple: `Roster`, `count`, and the arpeggio carrier are untouched by this phase.

**Tech Stack:** Python 3.11+, frozen dataclasses, `tomllib`, Typer, pytest, numpy/soundfile in tests only. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-28-phase-10-percussion-design.md` — read it before Task 1. Every design decision below is argued there.

## Global Constraints

- **Off by default.** `Percussion.enabled = False`. Every existing golden, preset, and audition verdict must survive this phase byte-identical. This is a test (Task 4), not an intention.
- **Four meters only:** `(4,4)`, `(2,4)`, `(3,4)`, `(6,8)`. Anything else raises `ValueError` naming the bar number and the signature. No fallback pattern.
- **Positions are quarter notes, not beats.** `bpm` is quarter-note based throughout this pipeline (`analyze._key_of` divides by `60.0 / score.bpm`). A 6/8 bar is three quarters.
- **The floor is in seconds and does not scale with tempo**, for the same reason `arp_rate_sec` does not: it is a measurement of hearing, not of music.
- **The kit stays out of the TOML.** `[percussion]` has exactly two keys, `enabled` and `level`. Clock rates, envelope, `HIT_SEC`, and `MIN_HIT_SEC` are calibration set by audition, following the rule that keeps `ARP_RATE_SEC` and the C1/C8 bounds out of config.
- **No CLI flags.** Config only; `--config` covers auditioning.
- **Every test is proven by breaking the implementation and watching it fail**, then restoring. Each task names the specific regression. A test that passes under its named regression is not done — this repo has been bitten by exactly that.
- Run tests with `.venv/bin/pytest`. Commit after each task.

## File Structure

| File | Responsibility |
|---|---|
| `src/bitty/percussion.py` | **New.** The pattern table, placement on the bar timeline, and the priority/floor resolution. Pure: imports only `arrangement` and `model`, so it sits at the bottom of the import graph next to them. |
| `src/bitty/voices.py` | Gains the `PERC` voice declaration. Not added to `VOICES`. |
| `src/bitty/config.py` | Gains the `Percussion` dataclass, a `Config` field, and a `_TABLES` entry. |
| `src/bitty/arrange.py` | Gains ~6 lines after the channel loop that append the percussion channel. |
| `src/bitty/presets/arcade.toml` | **New.** Turns percussion on. |
| `tests/test_percussion.py` | **New.** Patterns, placement, refusal, floor, priority, monophony, and the loop observation. |
| `tests/test_config.py` | Gains the `[percussion]` surface tests. |
| `tests/test_goldens.py` | Unchanged — that it stays unchanged and still passes *is* the identity test. |
| `README.md` | The `[percussion]` table, the `perc` voice, and the Status section. |

**One deviation from the spec, deliberate:** the spec sketched `groove(bars, bpm, settings: Percussion)`. This plan passes `level: float` instead. Reason: `config.py` imports voices/arrangement/lfo and would have to import `percussion` if a percussion constant ever became a config default — passing a float keeps `percussion.py` below `config.py` in the import graph and leaves that door open. It also matches how `arrange` already passes `config.vibrato.min_note_sec` as a bare float to `_events`. Nothing else about the design changes.

---

### Task 1: The `[percussion]` config surface

Two keys, no behaviour. Landing the surface first means every later task can turn the feature on from a TOML string rather than by constructing dataclasses by hand.

**Files:**
- Modify: `src/bitty/config.py` (add `Percussion` after `Transform` at line ~86; add the `Config` field at line ~91; add the `_TABLES` entry at the end of the dict, line ~266)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `config.Percussion(enabled: bool = False, level: float = 0.8)`, reachable as `Config.percussion`. Tasks 4 and 5 read `config.percussion.enabled` and `config.percussion.level`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`. `merge` is already imported there; check the import line and add `Percussion` to the `bitty.config` import if the file imports names individually.

```python
def test_percussion_is_off_by_default():
    """The whole phase rests on this: nothing that exists today moves."""
    assert DEFAULTS.percussion.enabled is False
    assert DEFAULTS.percussion.level == 0.8


def test_a_file_can_turn_percussion_on():
    result = merge(DEFAULTS, "[percussion]\nenabled = true\nlevel = 0.5\n", "test")
    assert result.percussion.enabled is True
    assert result.percussion.level == 0.5


def test_a_file_silent_on_percussion_leaves_it_off():
    result = merge(DEFAULTS, "[echo]\nlevel = 0.2\n", "test")
    assert result.percussion.enabled is False


def test_an_unknown_percussion_key_names_the_alternatives():
    with pytest.raises(ConfigError) as error:
        merge(DEFAULTS, "[percussion]\nkick = 40\n", "test")
    message = str(error.value)
    assert "percussion.kick" in message
    assert "enabled" in message and "level" in message


def test_percussion_level_is_bounded():
    with pytest.raises(ConfigError):
        merge(DEFAULTS, "[percussion]\nlevel = 1.5\n", "test")
    with pytest.raises(ConfigError):
        merge(DEFAULTS, "[percussion]\nlevel = -0.1\n", "test")


def test_percussion_enabled_rejects_a_number():
    """`_flag` exists so that `enabled = 1` is an error rather than a truthy 1."""
    with pytest.raises(ConfigError):
        merge(DEFAULTS, "[percussion]\nenabled = 1\n", "test")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -k percussion -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'percussion'` on the first two, and `ConfigError: test: percussion: unknown table` on the rest.

- [ ] **Step 3: Add the dataclass and the field**

In `src/bitty/config.py`, after the `Transform` dataclass:

```python
@dataclass(frozen=True)
class Percussion:
    """Drums the score does not contain. Off unless asked for.

    Two keys, and deliberately only two. The kit itself — the noise channel's
    clock rates, its envelope, the hit length, and the floor that thins the
    subdivisions at speed — is calibration set by audition, and 5b settled that
    calibration stays out of the TOML. The same rule keeps `ARP_RATE_SEC` and
    the playable-pitch bounds out of it.
    """

    enabled: bool = False
    level: float = 0.8
```

Then add the field to `Config`, after `transform`:

```python
    transform: Transform = Transform()
    percussion: Percussion = Percussion()
    voices: Roster = ROSTER
```

- [ ] **Step 4: Add the `_TABLES` entry**

At the end of the `_TABLES` dict, after `"transform"`:

```python
    "percussion": {
        "enabled": ("enabled", _flag),
        "level": ("level", _ranged(low=0.0, high=1.0)),
    },
```

Both validators already exist. No new validator machinery, and the "unknown table" message built from `sorted([*_TABLES, "voices"])` picks up the new name for free.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS, including the pre-existing `test_an_unknown_table_is_refused`.

- [ ] **Step 6: Prove the tests by breaking the implementation**

Two regressions, one at a time, restoring after each:

1. Change the default to `enabled: bool = True`. Expected: `test_percussion_is_off_by_default` and `test_a_file_silent_on_percussion_leaves_it_off` FAIL.
2. Drop the bounds from the validator — `("level", _ranged())`. Expected: `test_percussion_level_is_bounded` FAILS on both halves.
3. Swap `_flag` for `_ranged(low=0.0, high=1.0)` on `enabled`. Expected: `test_percussion_enabled_rejects_a_number` FAILS, because `enabled = 1` becomes an accepted truthy number instead of an error.

Restore both. If either test passed under its regression, the test is wrong, not the implementation.

- [ ] **Step 7: Commit**

```bash
git add src/bitty/config.py tests/test_config.py
git commit -m "feat: add the [percussion] config table"
```

---

### Task 2: The pattern table and placement on the bar timeline

The table is data and the placement is arithmetic. No priority, no floor, no channel yet — this task's `groove` returns every candidate hit in bar order, and Task 3 narrows it.

**Files:**
- Create: `src/bitty/percussion.py`
- Create: `tests/test_percussion.py`

**Interfaces:**
- Consumes: `bitty.model.Bar` (fields `number`, `start`, `dur`, `time_signature`), `bitty.arrangement.Event`.
- Produces: `percussion.Hit(quarters: float, drum: str, vel: int)`; `percussion.PATTERNS: dict[tuple[int, int], tuple[Hit, ...]]`; `percussion.KICK/SNARE/HAT` (the strings `"kick"`, `"snare"`, `"hat"`); `percussion.PITCH: dict[str, int]`; `percussion.groove(bars, bpm, level) -> tuple[Event, ...]`. Task 3 replaces `groove`'s body; Task 4 calls it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_percussion.py`:

```python
"""The groove: a pattern per meter, placed on the score's own barlines."""

import pytest

from bitty import percussion
from bitty.model import Bar

EPSILON = 1e-6


def bars(count, signature=(4, 4), bpm=120.0, quarters=None):
    """A run of uniform bars, timed the way ingest times them."""
    if quarters is None:
        quarters = signature[0] * 4 / signature[1]
    dur = quarters * 60.0 / bpm
    return tuple(
        Bar(
            number=i + 1,
            start=i * dur,
            dur=dur,
            time_signature=signature,
            sharps=0,
        )
        for i in range(count)
    )


def times(events, pitch=None):
    return [
        round(e.t, 6) for e in events if pitch is None or e.pitch == pitch
    ]


def test_a_four_four_bar_places_its_kicks_on_one_and_three():
    events = percussion.groove(bars(1), 120.0, 1.0)
    assert times(events, percussion.PITCH[percussion.KICK]) == [0.0, 1.0]


def test_placement_converts_through_bpm():
    """At 60 bpm a quarter is a full second; at 120 it is half of one."""
    slow = percussion.groove(bars(1, bpm=60.0), 60.0, 1.0)
    assert times(slow, percussion.PITCH[percussion.KICK]) == [0.0, 2.0]


def test_the_second_bar_starts_where_the_first_ends():
    events = percussion.groove(bars(2), 120.0, 1.0)
    assert times(events, percussion.PITCH[percussion.KICK]) == [0.0, 1.0, 2.0, 3.0]


def test_three_four_has_no_backbeat():
    """A waltz that gets a backbeat stops being a waltz."""
    events = percussion.groove(bars(1, signature=(3, 4)), 120.0, 1.0)
    assert times(events, percussion.PITCH[percussion.SNARE]) == []
    assert times(events, percussion.PITCH[percussion.KICK]) == [0.0]


def test_six_eight_is_three_quarters_long():
    """Positions are quarters, so 6/8's snare at 1.5 lands mid-bar."""
    events = percussion.groove(bars(1, signature=(6, 8)), 120.0, 1.0)
    assert times(events, percussion.PITCH[percussion.SNARE]) == [0.75]


def test_a_pickup_bar_keeps_only_the_hits_that_fit():
    """A short bar is not a licence to spill hits past its own barline."""
    pickup = bars(1, quarters=1.0)  # one quarter of a 4/4 bar
    events = percussion.groove(pickup, 120.0, 1.0)
    assert all(e.t < pickup[0].dur - EPSILON for e in events)
    assert times(events, percussion.PITCH[percussion.KICK]) == [0.0]


def test_each_bar_uses_its_own_signature():
    """analyze splits sections on a meter change; a groove must follow it."""
    first = bars(1, signature=(4, 4))[0]
    second = Bar(
        number=2,
        start=first.dur,
        dur=1.5,
        time_signature=(3, 4),
        sharps=0,
    )
    events = percussion.groove((first, second), 120.0, 1.0)
    late = [e for e in events if e.t >= first.dur - EPSILON]
    assert percussion.PITCH[percussion.SNARE] not in {e.pitch for e in late}


def test_an_unlisted_meter_refuses_by_name():
    with pytest.raises(ValueError) as error:
        percussion.groove(bars(1, signature=(5, 4), quarters=5.0), 120.0, 1.0)
    message = str(error.value)
    assert "bar 1" in message
    assert "5/4" in message


def test_level_scales_velocity():
    full = percussion.groove(bars(1), 120.0, 1.0)
    half = percussion.groove(bars(1), 120.0, 0.5)
    assert max(e.vel for e in half) < max(e.vel for e in full)
    assert max(e.vel for e in full) <= 15


def test_no_bars_is_no_groove():
    assert percussion.groove((), 120.0, 1.0) == ()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_percussion.py -v`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'bitty.percussion'`.

- [ ] **Step 3: Write the module**

Create `src/bitty/percussion.py`:

```python
"""Drums the score does not contain, placed on the barlines it does.

The groove comes from the meter rather than from the music. Every hit can be
justified by pointing at a barline, which is the standard `analyze` holds
itself to; a pattern derived from onset density would put hits on a chorale
that nobody could account for afterwards.

Positions are in **quarter notes**, not beats. `bpm` is quarter-note based
everywhere in this pipeline, so quarters convert to seconds with no per-meter
reasoning, and a 6/8 bar is three quarters rather than six ambiguous "beats".

This module sits at the bottom of the import graph beside `arrangement` and
`model`, and takes `level` as a float rather than importing `config`.
"""

from __future__ import annotations

from dataclasses import dataclass

from bitty.arrangement import MAX_VELOCITY, Event
from bitty.model import Bar

EPSILON = 1e-6

KICK, SNARE, HAT = "kick", "snare", "hat"

# Not pitches. The noise oscillator clocks a 15-bit LFSR once per phase cycle,
# so this number is a clock rate: low is a rumble, high is a hiss, and neither
# reads to the ear as a note. Calibration, set by the phase's audition.
PITCH = {KICK: 36, SNARE: 52, HAT: 76}


@dataclass(frozen=True)
class Hit:
    quarters: float  # from the barline
    drum: str  # KICK, SNARE, or HAT
    vel: int  # 0-15, before `level` scales it


def _hats(count: int, spacing: float, vel: int) -> tuple[Hit, ...]:
    return tuple(Hit(step * spacing, HAT, vel) for step in range(count))


# One entry per supported meter. These are musical decisions a person made and
# can be judged by ear, not a formula's output — which is the point. 3/4 has no
# backbeat because a waltz that gets one stops being a waltz, and encoding that
# exception into a general rule would turn the rule back into this table.
PATTERNS: dict[tuple[int, int], tuple[Hit, ...]] = {
    (4, 4): (
        Hit(0.0, KICK, 15),
        Hit(2.0, KICK, 12),
        Hit(1.0, SNARE, 13),
        Hit(3.0, SNARE, 13),
        *_hats(8, 0.5, 7),
    ),
    (2, 4): (
        Hit(0.0, KICK, 15),
        Hit(1.0, SNARE, 13),
        *_hats(4, 0.5, 7),
    ),
    (3, 4): (
        Hit(0.0, KICK, 15),
        Hit(1.0, HAT, 8),
        Hit(2.0, HAT, 8),
    ),
    (6, 8): (
        Hit(0.0, KICK, 15),
        Hit(1.5, SNARE, 13),
        *_hats(6, 0.5, 7),
    ),
}


def groove(bars: tuple[Bar, ...], bpm: float, level: float) -> tuple[Event, ...]:
    """The percussion channel's events, or () when there are no bars."""
    if not bars:
        return ()
    seconds_per_quarter = 60.0 / bpm
    placed: list[tuple[float, Hit]] = []
    for bar in bars:
        for hit in _pattern(bar):
            offset = hit.quarters * seconds_per_quarter
            # A pickup or a short final bar keeps only what fits inside it.
            # Without this, three hits of a 4/4 pattern spill into a bar that
            # does not exist.
            if offset >= bar.dur - EPSILON:
                continue
            placed.append((bar.start + offset, hit))
    placed.sort(key=lambda pair: pair[0])
    return tuple(_event(when, hit, level) for when, hit in placed)


def _pattern(bar: Bar) -> tuple[Hit, ...]:
    """This bar's pattern, by its own signature.

    Per bar rather than per score, so a piece that changes meter part-way is
    handled by construction — `analyze` already splits a section at exactly
    that point.
    """
    try:
        return PATTERNS[bar.time_signature]
    except KeyError:
        top, bottom = bar.time_signature
        supported = ", ".join(f"{t}/{b}" for t, b in sorted(PATTERNS))
        raise ValueError(
            f"bar {bar.number} is in {top}/{bottom}, which has no percussion "
            f"pattern; [percussion] supports {supported}. Turn percussion off "
            f"to convert this score."
        ) from None


def _event(when: float, hit: Hit, level: float) -> Event:
    return Event(
        t=when,
        pitch=PITCH[hit.drum],
        dur=0.0,  # Task 3 sets this from the gap to the next hit
        vel=min(MAX_VELOCITY, round(hit.vel * level)),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_percussion.py -v`
Expected: PASS, all eleven.

- [ ] **Step 5: Prove the tests by breaking the implementation**

Four regressions, one at a time, restoring after each:

1. Drop the bpm conversion — `offset = hit.quarters`. Expected: `test_placement_converts_through_bpm` and `test_a_four_four_bar_places_its_kicks_on_one_and_three` FAIL.
2. Drop the bar-duration clip — delete the `if offset >= bar.dur - EPSILON: continue`. Expected: `test_a_pickup_bar_keeps_only_the_hits_that_fit` FAILS.
3. Look the pattern up once from the first bar instead of per bar — hoist `pattern = _pattern(bars[0])` above the loop. Expected: `test_each_bar_uses_its_own_signature` FAILS.
4. Make `_pattern` fall back to `PATTERNS[(4, 4)]` instead of raising. Expected: `test_an_unlisted_meter_refuses_by_name` FAILS.

Restore all four.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/percussion.py tests/test_percussion.py
git commit -m "feat: add the percussion pattern table and bar placement"
```

---

### Task 3: Priority, the floor, and monophony

A chip channel is monophonic, so the candidates from Task 2 have to become a sequence that never overlaps. Three rules do it: strongest drum first, nothing within `MIN_HIT_SEC` of something already placed, and a duration clipped to the gap that follows.

**Files:**
- Modify: `src/bitty/percussion.py` (add `MIN_HIT_SEC`, `HIT_SEC`, `PRIORITY`, `_resolve`; rewrite the tail of `groove`)
- Test: `tests/test_percussion.py`

**Interfaces:**
- Consumes: everything Task 2 produced.
- Produces: `percussion.MIN_HIT_SEC: float`, `percussion.HIT_SEC: float`, `percussion.PRIORITY: tuple[str, ...]`. Task 5 reads `MIN_HIT_SEC` to compute where the tempo crossing falls; the audition moves both constants.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_percussion.py`:

```python
def test_a_hat_on_a_downbeat_loses_to_the_kick():
    """Priority resolves the collision in the musical direction."""
    events = percussion.groove(bars(1), 120.0, 1.0)
    at_zero = [e for e in events if abs(e.t) < EPSILON]
    assert len(at_zero) == 1
    assert at_zero[0].pitch == percussion.PITCH[percussion.KICK]


def test_no_two_events_overlap():
    """The same rule test_goldens holds every pitched channel to."""
    events = percussion.groove(bars(4), 120.0, 1.0)
    for earlier, later in zip(events, events[1:]):
        assert earlier.t + earlier.dur <= later.t + EPSILON


def test_events_come_back_in_time_order():
    events = percussion.groove(bars(4), 120.0, 1.0)
    assert list(events) == sorted(events, key=lambda e: e.t)


def test_hats_survive_at_an_ordinary_tempo():
    """The chorale's eighths are 250 ms apart at its own tempo."""
    events = percussion.groove(bars(1), 120.0, 1.0)
    assert times(events, percussion.PITCH[percussion.HAT])


def test_the_floor_drops_the_hats_when_the_bars_get_short():
    """Four times the tempo puts the chorale's eighths 62 ms apart."""
    fast = bars(1, bpm=480.0)
    events = percussion.groove(fast, 480.0, 1.0)
    assert times(events, percussion.PITCH[percussion.HAT]) == []
    assert times(events, percussion.PITCH[percussion.KICK]) == [0.0]


def test_the_floor_is_seconds_and_not_beats():
    """The same bar count at half tempo keeps hats the fast one loses.

    If MIN_HIT_SEC were expressed in beats, both would behave the same and the
    machine gun would come back at speed.
    """
    slow = percussion.groove(bars(1, bpm=120.0), 120.0, 1.0)
    fast = percussion.groove(bars(1, bpm=480.0), 480.0, 1.0)
    hat = percussion.PITCH[percussion.HAT]
    assert len(times(slow, hat)) > len(times(fast, hat))


def test_a_hit_is_never_longer_than_the_gap_after_it():
    events = percussion.groove(bars(2), 120.0, 1.0)
    for earlier, later in zip(events, events[1:]):
        assert earlier.dur <= later.t - earlier.t + EPSILON
    assert all(e.dur <= percussion.HIT_SEC + EPSILON for e in events)
    assert all(e.dur > 0.0 for e in events)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_percussion.py -v`
Expected: FAIL — `test_a_hat_on_a_downbeat_loses_to_the_kick` finds two events at t=0, the overlap and duration tests fail on `dur = 0.0`, and both floor tests fail because nothing thins.

- [ ] **Step 3: Add the constants and the resolution pass**

In `src/bitty/percussion.py`, below `PITCH`:

```python
# Strongest first. A hat that lands on a downbeat is dropped rather than
# allowed to truncate the kick — which is deliberately *not* the mutable
# truncation `arrange._assign` performs on pitched channels. That path exists
# to preserve voice-leading, and there is no voice-leading here.
PRIORITY = (KICK, SNARE, HAT)

# The shortest gap between two audible hits, and the phase's counterpart to
# ARP_RATE_SEC: a fact about the ear expressed in seconds, set by audition
# rather than guessed. It deliberately does not scale with tempo, so density
# is a property of the pattern meeting the tempo — a fast piece loses its
# subdivisions and keeps its backbeat, and `tempo_scale` feeds this for free
# because Phase 9 rewrites bar times before `arrange` ever runs.
#
# Where it bites, measured on the fixtures at their own tempos: hat spacing is
# 250 ms on the chorale, 300 ms on ragtime, 500 ms on the minuet. So anything
# below 250 ms is inert at tempo_scale = 1.0, and the crossing arrives between
# 2.0 and 4.0.
MIN_HIT_SEC = 0.10

# How long one hit rings before the envelope has finished with it. Clipped to
# the gap that follows, so the channel stays monophonic. Also calibration.
HIT_SEC = 0.12
```

Replace the tail of `groove` — everything from `placed.sort(...)` — with:

```python
    return _resolve(placed, level)


def _resolve(placed: list[tuple[float, Hit]], level: float) -> tuple[Event, ...]:
    """Candidates to a monophonic channel: priority, then the floor, then durs.

    Greedy and strongest-first across the whole piece, which makes the rule
    sayable in one sentence: place the loudest drums, then drop anything that
    would land too soon after something already placed.
    """
    kept: list[tuple[float, Hit]] = []
    for drum in PRIORITY:
        for when, hit in sorted(
            (pair for pair in placed if pair[1].drum == drum),
            key=lambda pair: pair[0],
        ):
            if any(abs(when - other) < MIN_HIT_SEC for other, _ in kept):
                continue
            kept.append((when, hit))

    kept.sort(key=lambda pair: pair[0])
    events = []
    for index, (when, hit) in enumerate(kept):
        gap = kept[index + 1][0] - when if index + 1 < len(kept) else HIT_SEC
        events.append(_event(when, hit, level, min(HIT_SEC, gap)))
    return tuple(events)
```

The `any(...)` scan is quadratic in the number of kept hits. A 16-bar fixture produces a few hundred candidates, so this is thousands of float comparisons — below noticing, and worth the readability.

Update `_event` to take the duration:

```python
def _event(when: float, hit: Hit, level: float, dur: float) -> Event:
    return Event(
        t=when,
        pitch=PITCH[hit.drum],
        dur=dur,
        vel=min(MAX_VELOCITY, round(hit.vel * level)),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_percussion.py -v`
Expected: PASS, all eighteen.

- [ ] **Step 5: Prove the tests by breaking the implementation**

Four regressions, one at a time, restoring after each:

1. Sort candidates by time alone — replace the `for drum in PRIORITY` loop with a single pass over `sorted(placed)`. Expected: `test_a_hat_on_a_downbeat_loses_to_the_kick` FAILS (the hat at 0.0 is placed first and the kick is dropped).
2. Delete the floor check — drop the `if any(...)` line. Expected: both floor tests FAIL, and `test_no_two_events_overlap` may too.
3. Make the floor scale with tempo — pass `seconds_per_quarter` into `_resolve` and compare against `MIN_HIT_SEC * seconds_per_quarter * 2`. Expected: `test_the_floor_is_seconds_and_not_beats` FAILS. This is the regression that matters most: it is the plausible-looking mistake that reintroduces the machine gun at speed.
4. Fix `dur` at `HIT_SEC` regardless of the gap. Expected: `test_a_hit_is_never_longer_than_the_gap_after_it` FAILS, and `test_no_two_events_overlap` FAILS at any tempo where hits are closer together than 0.12 s.

Restore all four.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/percussion.py tests/test_percussion.py
git commit -m "feat: resolve percussion hits by priority, floor, and gap"
```

---

### Task 4: The `perc` voice and the wiring into `arrange`

The identity test lives here, and it is the load-bearing one for the whole phase.

**Files:**
- Modify: `src/bitty/voices.py` (add `PERC` after `BASS`, before the `VOICES` tuple)
- Modify: `src/bitty/arrange.py` (import; append the channel after the loop that ends at line 69, before `meta` is built at line 71)
- Test: `tests/test_percussion.py`, and `tests/test_goldens.py` must still pass untouched

**Interfaces:**
- Consumes: `percussion.groove`, `config.Percussion`.
- Produces: `voices.PERC: Voice` with `role="perc"`. Task 5 and the README refer to that role name.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_percussion.py`. Add these imports at the top of the file:

```python
from dataclasses import replace
from pathlib import Path

from bitty.arrange import arrange
from bitty.config import DEFAULTS
from bitty.ingest import ingest

FIXTURES = Path(__file__).parent / "fixtures"
```

That is the same line `tests/test_goldens.py` uses.

```python
def on(level=0.8, **rest):
    return replace(DEFAULTS, percussion=replace(DEFAULTS.percussion, enabled=True, level=level), **rest)


def test_percussion_off_changes_nothing():
    """The whole phase rests on this. If it fails, nothing else matters."""
    score = ingest(FIXTURES / "chorale.mxl")
    assert arrange(score) == arrange(score, DEFAULTS)
    assert all(c.role != "perc" for c in arrange(score).channels)


def test_percussion_on_appends_one_noise_channel():
    score = ingest(FIXTURES / "chorale.mxl")
    plain = arrange(score)
    drummed = arrange(score, on())
    assert len(drummed.channels) == len(plain.channels) + 1
    assert drummed.channels[:-1] == plain.channels, "the pitched channels are untouched"
    perc = drummed.channels[-1]
    assert perc.role == "perc"
    assert perc.instrument.wave == "noise"
    assert perc.echo is None
    assert perc.events


def test_percussion_is_not_a_voice_in_the_roster():
    """count narrows the pitched reduction and has no opinion about drums."""
    from bitty import voices

    assert voices.PERC not in voices.VOICES
    assert len(voices.VOICES) == 5
    score = ingest(FIXTURES / "chorale.mxl")
    narrow = on(voices=replace(DEFAULTS.voices, count=3))
    roles = [c.role for c in arrange(score, narrow).channels]
    assert roles[-1] == "perc"
    assert len(roles) == 4, "three pitched voices plus the drums"


def test_the_arrangement_round_trips_through_json():
    """A hand-edited file must render the drums back without re-deriving them."""
    from bitty.arrangement import Arrangement

    score = ingest(FIXTURES / "chorale.mxl")
    drummed = arrange(score, on())
    assert Arrangement.from_json(drummed.to_json()) == drummed
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_percussion.py -k "percussion_off or appends or roster or round_trips" -v`
Expected: FAIL — `AttributeError: module 'bitty.voices' has no attribute 'PERC'`, and the channel count assertions fail because nothing is appended.

- [ ] **Step 3: Declare the voice**

In `src/bitty/voices.py`, after `BASS` and before the `VOICES` tuple:

```python
# Deliberately not in VOICES. Percussion is not part of the pitched reduction:
# it takes no slot in the roster, `count` does not narrow it, and it never
# carries the arpeggio overflow. It is declared here anyway because this file
# is where a timbre lives, and the arranger should no more hard-code a drum
# than it hard-codes a lead.
#
# One channel, so one envelope for all three drums — which is also what the
# real noise channel offers. The last step is 0 because the last step sustains,
# and a drum that ends on a nonzero level is a drum that never stops.
PERC = Voice(
    role="perc",
    instrument=Instrument(wave="noise", volume_env=(15, 12, 8, 5, 3, 1, 0)),
    pan=0.0,
)

VOICES = (LEAD, COUNTER, INNER_A, INNER_B, BASS)
```

- [ ] **Step 4: Wire it into `arrange`**

In `src/bitty/arrange.py`, add to the imports:

```python
from bitty.percussion import groove
from bitty.voices import PERC, Roster
```

Then, after the `for voice in roster:` loop ends (line 69) and before `meta` is built (line 71):

```python
    if config.percussion.enabled:
        hits = groove(score.bars, score.bpm, config.percussion.level)
        if hits:
            channels.append(
                Channel(
                    role=PERC.role,
                    instrument=PERC.instrument,
                    events=hits,
                    pan=PERC.pan,
                )
            )
```

Appended last, so the pitched channels keep their positions and a JSON diff of a drummed arrangement against a plain one is one added block rather than a reshuffle. No echo: only `lead` carries a tap, and a delayed drum is a different feature.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS, all of it — including `tests/test_goldens.py` **unmodified**. If a golden moved, the wiring is not conditional and the bug is in this task, not in the golden. Do not regenerate goldens in this phase; there is no legitimate reason for one to move.

- [ ] **Step 6: Prove the tests by breaking the implementation**

Three regressions, one at a time, restoring after each:

1. Append the channel unconditionally — delete the `if config.percussion.enabled:` guard. Expected: `test_percussion_off_changes_nothing` FAILS **and all three golden tests FAIL**. That second half is the point: the goldens are the phase's real identity guard.
2. Add `PERC` to the `VOICES` tuple. Expected: `test_percussion_is_not_a_voice_in_the_roster` FAILS, and expect collateral failures in `tests/test_config.py` and `tests/test_voices.py` — which is exactly why it is not in the tuple.
3. Insert the channel first instead of appending — `channels.insert(0, ...)`. Expected: `test_percussion_on_appends_one_noise_channel` FAILS on the `channels[:-1] == plain.channels` assertion.

Restore all three.

- [ ] **Step 7: Commit**

```bash
git add src/bitty/voices.py src/bitty/arrange.py tests/test_percussion.py
git commit -m "feat: append the percussion channel when it is enabled"
```

---

### Task 5: The `arcade` preset, the real fixtures, and the loop observation

Everything so far is hand-built bars. This task points the feature at the three fixtures through the whole pipeline, and answers the spec's one open empirical question: whether drums move the loop.

**Files:**
- Create: `src/bitty/presets/arcade.toml`
- Test: `tests/test_percussion.py`

**Interfaces:**
- Consumes: everything above, plus `bitty.transform.apply`, `bitty.synth.render`, `bitty.analyze.analyze`, `bitty.loop.candidates`/`choose`.
- Produces: the preset name `"arcade"`, which `config.preset_names()` picks up from the directory automatically.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_percussion.py`. `pytest` is already imported from Task 2; add only the new names:

```python
from bitty import loop as loop_stage
from bitty import synth
from bitty.analyze import analyze
from bitty.config import Transform, load, preset_names
from bitty.transform import apply

NAMES = ["chorale", "minuet", "ragtime"]


def test_the_arcade_preset_exists_and_turns_percussion_on():
    assert "arcade" in preset_names()
    config = load([], preset="arcade")
    assert config.percussion.enabled is True


def test_every_fixture_grooves():
    """The three fixtures are 4/4, 3/4, and 2/4 — one per pattern that has one."""
    for name in NAMES:
        score = ingest(FIXTURES / f"{name}.mxl")
        drummed = arrange(score, on())
        assert drummed.channels[-1].role == "perc"
        assert drummed.channels[-1].events, name


@pytest.mark.parametrize("name", NAMES)
def test_the_drums_run_the_length_of_the_piece(name):
    score = ingest(FIXTURES / f"{name}.mxl")
    perc = arrange(score, on()).channels[-1]
    last_bar = score.bars[-1]
    assert perc.events[0].t < 1e-6
    assert perc.events[-1].t < last_bar.start + last_bar.dur


@pytest.mark.parametrize("name", NAMES)
def test_four_times_tempo_thins_the_groove(name):
    """Phase 9 rewrites bar times before arrange runs, so the floor gets it free."""
    score = ingest(FIXTURES / f"{name}.mxl")
    plain = arrange(score, on()).channels[-1].events
    fast = arrange(apply(score, Transform(tempo_scale=4.0)), on()).channels[-1].events
    assert len(fast) < len(plain), name


@pytest.mark.parametrize("name", NAMES)
def test_the_drums_do_not_move_the_loop(name):
    """An observation, not a requirement. If it fails, that is a README finding."""
    score = ingest(FIXTURES / f"{name}.mxl")
    sections = analyze(score)
    picks = []
    for config in (DEFAULTS, on()):
        arrangement = arrange(score, config)
        audio = synth.render(arrangement)
        chosen = loop_stage.choose(
            loop_stage.candidates(score, sections, min_bars=config.loop.min_bars),
            audio,
            arrangement,
            DEFAULTS.output.sample_rate,
        )
        picks.append(
            None
            if chosen is None
            else (chosen.candidate.first_bar, chosen.candidate.last_bar)
        )
    assert picks[0] == picks[1], f"{name}: drums changed the loop to {picks[1]}"
```

`Choice` holds the span on `.candidate` (a `LoopCandidate` with `first_bar` / `last_bar`), not on itself — verified against `src/bitty/loop.py:180`.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_percussion.py -k "arcade or fixture or tempo or loop" -v`
Expected: FAIL — `ConfigError: preset arcade: unknown preset` on the first, the rest passing or failing on their own merits.

- [ ] **Step 3: Write the preset**

Create `src/bitty/presets/arcade.toml`:

```toml
# The gamified mode: a drum groove the score does not contain.
#
# One key, and that is the honest size of it. The kit — the noise channel's
# clock rates, its shared envelope, and the floor that thins the subdivisions
# at speed — is calibration in percussion.py and voices.py, set by audition
# rather than by the config file, the same rule that keeps ARP_RATE_SEC out.
#
# The groove is a pattern per time signature placed on the score's own
# barlines, so every hit can be justified by pointing at one. It supports 4/4,
# 2/4, 3/4, and 6/8; a score in any other meter refuses rather than being
# played as though it were in one of those.

[percussion]
enabled = true
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_percussion.py -v`
Expected: PASS.

If `test_the_drums_do_not_move_the_loop` fails, **do not change the code to make it pass.** It is an observation test. Record which fixture moved and to which bars, change the assertion to document the real behaviour, and carry the finding into Task 6's README text and Task 7's audition. A drum that moves a loop is exactly the kind of thing this phase exists to notice.

- [ ] **Step 5: Prove the tests by breaking the implementation**

Two regressions, one at a time:

1. Set `enabled = false` in `arcade.toml`. Expected: `test_the_arcade_preset_exists_and_turns_percussion_on` FAILS.
2. Make `MIN_HIT_SEC = 0.0` in `percussion.py`. Expected: `test_four_times_tempo_thins_the_groove` FAILS on all three fixtures — nothing thins, and the machine gun is back.

Restore both.

- [ ] **Step 6: Run the whole suite and commit**

Run: `.venv/bin/pytest`
Expected: PASS.

```bash
git add src/bitty/presets/arcade.toml tests/test_percussion.py
git commit -m "feat: add the arcade preset and cover the fixtures end to end"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md` — the voices table (line ~308), a new `### [percussion]` config subsection after `### [transform]` (which ends around line 637), the presets list (line ~646), and the Status section (line ~680)

**Interfaces:**
- Consumes: the finished behaviour, including whatever Task 5's loop observation actually found.
- Produces: nothing code reads.

- [ ] **Step 1: Add the voice to the roster prose**

After the five-voices table and the paragraph about dropped channels, add:

```markdown
A sixth channel, `perc`, plays only when `[percussion]` turns it on. It is not
part of that roster: `[voices] count` does not narrow it, it never carries the
arpeggio overflow, and it holds no pitched material — its `pitch` field is a
noise clock rate rather than a note. See [`[percussion]`](#percussion) below.
```

- [ ] **Step 2: Add the config subsection**

After the `### [transform]` subsection, add a `### [percussion]` subsection covering, in this order:

1. The two keys, with defaults, in the same shape the other subsections use.
2. That it is off by default and why: drums are generated rather than reduced, so they are opt-in.
3. The pattern table — the four meters and what each plays — as a markdown table copied from the spec.
4. That 3/4 has no backbeat, and why.
5. That an unlisted meter refuses by name rather than falling back.
6. The floor: hits closer than `MIN_HIT_SEC` to one already placed are dropped, strongest drum first, so a fast piece loses its hats and keeps its backbeat — and that this is why `tempo_scale = 4.0` does not produce a machine gun.
7. That the kit is calibration in `percussion.py` and `voices.py`, not config, for the same reason `ARP_RATE_SEC` is not.
8. The `arcade` preset.
9. That a sixth channel costs about 0.8 dB across the whole mix, because `synth` divides headroom by `sqrt(len(channels))`.

- [ ] **Step 3: Add `arcade` to the presets list**

The `### Presets` subsection lists the shipped presets. Add `arcade` with a one-line description matching the tone of the `lush` and `nes-tight` entries.

- [ ] **Step 4: Add the Status paragraph**

Append to the Status section, after the Phase 9 paragraphs. State what shipped, the decision that shapes it (meter grid over score-driven, and why), that it is off by default, the four supported meters and the refusal, the floor and where it bites on the fixtures (250/300/500 ms, crossing between `tempo_scale` 2.0 and 4.0), whatever Task 5 found about the loop, and that the audition is still owed. Phase 8 and 9 both merged with the audition outstanding and said so plainly rather than claiming a verdict; follow that.

- [ ] **Step 5: Verify every claim**

Read the new prose against the code. Every number in it — the hat spacings, the 0.8 dB, the meter list, the two config keys and their defaults — must be checkable in the source or the tests. Phase 9's final review found five false statements in this file; the cost of a wrong number here is that someone later trusts it.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: document [percussion]"
```

---

### Task 7: The audition

The kit and the floor are calibration, which means they are guesses until someone listens. This task sets them.

**Files:**
- Create: `audition/percussion/` (gitignored — findings must reach the README to survive)
- Modify: `src/bitty/percussion.py` and `src/bitty/voices.py`, if the audition moves the constants
- Modify: `README.md` Status section with the verdict

- [ ] **Step 1: Build the clips**

Scratch TOMLs in the scratchpad, one `bitty convert --wav` each. Required set:

- **The control:** percussion off, one per fixture. Byte-identical to a plain convert by construction — this is simultaneously a unit test and the harness's calibration check. In the tail-wrap audition it was exactly this, a reported difference on a pair identical by construction, that exposed an artifact in the harness rather than in the audio.
- **All three fixtures with drums**, at `level = 0.8`. The three meters are the three patterns, and the chorale is where a backbeat is most likely to be wrong.
- **`level` at 0.5 and 1.0** on one fixture, to find whether volume is what makes the grid feel imposed.
- **Two or three kit variants** — the clock rates in `PITCH` and the `volume_env` on `PERC` — as code edits, since the kit is deliberately not configurable. Not a matrix; two or three considered alternatives.
- **The floor crossing:** the chorale at `tempo_scale` 1.0, 2.0, and 4.0. Hats are 250 ms apart at 1.0, 125 ms at 2.0, and 62 ms at 4.0, so with `MIN_HIT_SEC = 0.10` the crossing sits between 2.0 and 4.0. Count the seconds actually on each side before handing anything over — a clip that does not exercise the variable cannot answer the question, which is the lesson from the `+20` transpose clips that only spent 0.5 s of 24 s near the ceiling.

- [ ] **Step 2: Verify the clips before listening**

- WAV only. `aplay` renders Ogg as static.
- Clips stay continuous: no separators, no inserted silence, no concatenation joins that fake a seam. The count-3 audition's 0.6 s separator was heard as a gap in the music.
- Run a probe asserting no near-zero window in any clip before handing it over.
- Assert the control is byte-identical to a plain `convert` of the same fixture.

- [ ] **Step 3: Hand them over and listen**

The questions, in order of what they can change:

1. **Does a meter grid belong on a chorale at all?** This is the phase's real question and the honest possible answer is no. If it is no, `arcade` documents itself as a ragtime-and-ragtime-like preset, and that is a finding rather than a failure.
2. **Where does the floor belong?** Somewhere between 2.0 and 4.0 the hats should stop; if they should stop sooner or later, `MIN_HIT_SEC` moves.
3. **The kit:** which clock rates read as kick, snare, and hat rather than as three hisses.
4. **The shared envelope:** whether one decay across all three drums is audibly a compromise. If it is, the fix is a second channel — a scope increase to record, not to build in this phase.
5. **`level`:** whether 0.8 is right as the default.

- [ ] **Step 4: Apply the verdict**

Move `MIN_HIT_SEC`, `PITCH`, `HIT_SEC`, `PERC.volume_env`, or the `level` default as the audition says. Re-run the full suite — the floor tests in Task 3 and 5 are written against behaviour rather than exact numbers, so they should survive a moved constant. If one does not, it was testing the guess rather than the rule; fix the test.

- [ ] **Step 5: Write the verdict into the README**

`audition/` is gitignored, so a finding that does not reach the Status section did not happen. Record what was heard, what moved and what did not, and the honest scope of the verdict — including which playback the floor was judged on, the way the C1 verdict names full-range monitors as both its strength and its narrowness.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: close Phase 10 with the percussion audition"
```

---

## Notes for the executor

- **The goldens must not move in this phase.** If `BITTY_UPDATE_GOLDENS` looks tempting, the wiring in Task 4 is unconditional. Fix that instead.
- **`arrange` is called with a bare `score` in several tests** (`tests/test_goldens.py`, `tests/test_quality.py`), which picks up `DEFAULTS`. Since the default is off, those callers need no change — that is by design and not an oversight.
- **The refusal is a `ValueError`,** matching `transform.apply` and `loop.trim`. No new exception type.
- **Do not add `[voices.perc]`.** The kit is calibration. If the audition wants it configurable, that is a later phase with its own argument.
- **`Bar` requires `number`, `start`, `dur`, `time_signature`, and `sharps`** — the repeat flags default to `False`. The test helper in Task 2 relies on that.
