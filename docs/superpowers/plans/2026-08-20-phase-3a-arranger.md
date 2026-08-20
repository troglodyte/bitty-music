# Phase 3a: Arranger — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Phase 1 placeholder arranger with voice-leading assignment across five chip channels, arpeggio overflow for notes that find no channel, golden arrangement tests, and a `bitty render` command that re-renders a hand-edited `arrangement.json`.

**Architecture:** `voices.py` holds the five-voice roster as plain data — role,
instrument, pan — and `arrange.py` holds the algorithm. Notes are grouped by
onset; the top of the sounding texture is pinned to the lead and the bottom to
the bass; everything between goes to the channel whose last pitch is nearest
**among the channels that are not mid-note**. A channel is monophonic, so
placing a note on a busy channel truncates what it was holding. Notes that find
no channel at all are not dropped: a post-pass folds them into one channel as a
16 ms arpeggio.

**Tech Stack:** Python 3.11+, music21 (parsing only, already in place), numpy,
soundfile, typer, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-bitty-music-design.md`

## Global Constraints

- Python 3.11+.
- **Phase 3a adds no dependencies.** `librosa`, `mutagen`, and `sounddevice`
  belong to Phases 4 and 5 — do not add them.
- Do not hand-roll audio encoding, metadata tag writing, key detection,
  structural segmentation, or score parsing. Libraries own those.
- MIDI note numbers for pitch. Seconds for time. Velocity 0–15 inside an
  `Arrangement`, 0–127 in a `Score`.
- Arranging is deterministic: identical input produces an identical
  `arrangement.json`, byte for byte. Nothing calls `random`.
- Voice budget is five sounding channels plus an echo. Arp rate is 16 ms per
  step (the spec's `[arp] rate_ms = 16`). The spec's `[arp] threshold = 5` is
  not a separate check: overflow triggers when the channels run out, which at a
  five-voice roster *is* the threshold. Phase 5 makes both numbers config.
- Dynamics quantize to 16 levels. The coarse steps are the texture, not a loss.
- Source layout is `src/bitty/`, tests in `tests/`.
- `synth.py`, `osc.py`, `envelope.py`, and `filters.py` are **not modified by
  this phase**. Phase 3a adds channels and events; it does not change what the
  synth does with them.

## Design decisions settled before planning

Decided in dialog on 2026-08-20 and not open for re-litigation mid-execution:

- **Phase 3 is split.** This plan is Phase 3a: assignment, overflow, goldens,
  `bitty render`. Phase 3b is articulation — delayed vibrato, ornament shaping,
  and the dynamics work that goes with them. Vibrato needs a new contract field
  and a synth LFO, which is a different module and a different risk.
- **Prefer-free assignment, steal only when full.** Among middle channels not
  currently sounding, the nearest last pitch wins; only when every middle
  channel is busy does a note steal one. A hole in the harmony costs more than
  the timbre jump of a note landing on a further-away channel.
- **Overflow is a post-pass, not a strategy object.** One implementation, no
  second planned. `_arpeggiate(leftovers, takes)` is a function.
- **The roster is data in `voices.py`.** The one axis expected to vary is voice
  count, duty, and pan — Phase 5's config work overrides that table. It is
  separated as data, not behind an interface.
- **Golden fixtures are checked-in `.mxl` excerpts**, exported once from the
  music21 corpus. Compressed MusicXML keeps all three under 11 KB total, and
  the goldens stop being hostage to music21 corpus revisions.

## Findings from the spike (2026-08-20)

A throwaway five-channel arranger was built to settle the prefer-free question
by ear. Two results shape this plan:

- Prefer-free and always-steal diverge on only 1–3 notes per 40-second excerpt,
  even though 50–63 onsets were contended. Prefer-free is cheap insurance, not
  a dramatic difference — **do not spend much test surface on it.** Two tests.
- The louder problem was notes **dropped** for want of a channel: 11 in 40
  seconds of ragtime. That is what Task 4 exists to fix.
- Grace notes arrive from music21 with `dur == 0.0` and vanish silently. Task 2
  floors them at 32 ms so nothing disappears. Shaping ornaments properly is
  Phase 3b's job; not losing them is this phase's.

## Deliberately deferred to Phase 3b and later

Do not build these now, and do not add contract fields for them: vibrato,
ornament shaping, per-note effects, tempo maps, repeat marks, key detection,
section analysis, loop points, config files, presets-by-name, engine targets,
`bitty sections`, `--play`, `--bars`, `--loop-from`.

## File Structure

| File | Responsibility |
|------|----------------|
| `src/bitty/voices.py` | **Create** — the five-voice roster: role, instrument, pan, echo constants |
| `src/bitty/arrange.py` | **Rewrite** — onset grouping, assignment, truncation, arpeggio overflow, assembly |
| `src/bitty/cli.py` | **Modify** — `bitty render`, shared audio writer |
| `tests/test_voices.py` | **Create** — the roster matches the spec table |
| `tests/test_arrange.py` | **Rewrite** — assignment, truncation, prefer-free, overflow |
| `tests/test_goldens.py` | **Create** — golden JSON diff plus arrangement invariants |
| `tests/test_cli.py` | **Modify** — `render` round-trips and names files correctly |
| `tests/fixtures/{chorale,minuet,ragtime}.mxl` | **Create** — corpus excerpts |
| `tests/goldens/*.arrangement.json` | **Create** — generated, then reviewed by eye |

`src/bitty/arrangement.py` is **not** in this table on purpose. Phase 2 already
extended the contract with everything the five-voice roster needs — envelopes,
duty, pan, echo, filter fields — so Phase 3a writes richer arrangements through
an unchanged schema. If you find yourself adding a field, stop: that is either
Phase 3b's articulation work or a sign the roster is being bypassed.

## Before you start

Phase 2 is complete but still sitting on its own branch. Land it, then branch:

```bash
git checkout main
git merge --no-ff phase-2-synth -m "Merge Phase 2: synth"
git checkout -b phase-3a-arranger
.venv/bin/pytest    # green before you change anything
```

---

### Task 1: The voice roster

**Files:**
- Create: `src/bitty/voices.py`
- Test: `tests/test_voices.py`

**Interfaces:**
- Consumes: `bitty.arrangement.Instrument` (existing).
- Produces: `Voice(role: str, instrument: Instrument, pan: float)`;
  `ROSTER: tuple[Voice, ...]` in the order lead, counter, inner_a, inner_b,
  bass; `LEAD_ROLE`, `BASS_ROLE`, `ARP_ROLE: str`; `MIDDLE_ROLES: tuple[str, ...]`;
  `ECHO_BEATS: float`; `ECHO_LEVEL: float`. Task 2 imports all of these.

- [ ] **Step 1: Write the failing test**

Create `tests/test_voices.py`:

```python
from bitty.voices import ARP_ROLE, BASS_ROLE, LEAD_ROLE, MIDDLE_ROLES, ROSTER


def test_the_roster_is_the_spec_s_five_voices_in_score_order():
    assert [v.role for v in ROSTER] == ["lead", "counter", "inner_a", "inner_b", "bass"]


def test_waves_and_duties_match_the_spec_table():
    by_role = {v.role: v.instrument for v in ROSTER}
    assert by_role["lead"].wave == "pulse" and by_role["lead"].duty == 0.5
    assert by_role["counter"].wave == "pulse" and by_role["counter"].duty == 0.25
    assert by_role["inner_a"].wave == "pulse" and by_role["inner_a"].duty == 0.25
    assert by_role["inner_b"].wave == "pulse" and by_role["inner_b"].duty == 0.125
    assert by_role["bass"].wave == "triangle"


def test_every_voice_has_a_volume_envelope():
    """A chip voice with no envelope is a buzzer; Phase 2 exists to avoid that."""
    assert all(v.instrument.volume_env for v in ROSTER)


def test_the_voices_occupy_distinct_places_in_the_image():
    pans = [v.pan for v in ROSTER]
    assert len(set(pans)) == len(pans)
    assert all(-1.0 <= p <= 1.0 for p in pans)


def test_the_filter_ships_off():
    """Warmth is a lever, not the default. See the Phase 2 warmth listen."""
    assert all(v.instrument.cutoff_hz is None for v in ROSTER)


def test_the_role_constants_point_into_the_roster():
    roles = {v.role for v in ROSTER}
    assert {LEAD_ROLE, BASS_ROLE, ARP_ROLE} <= roles
    assert set(MIDDLE_ROLES) <= roles
    assert LEAD_ROLE not in MIDDLE_ROLES and BASS_ROLE not in MIDDLE_ROLES
    assert ARP_ROLE in MIDDLE_ROLES
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_voices.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bitty.voices'`

- [ ] **Step 3: Write the roster**

Create `src/bitty/voices.py`:

```python
"""The five-voice roster: who plays, with what timbre, and where in the image.

Data, not policy. This is the table Phase 5's config work overrides, so the
arranger reads it and never hard-codes an instrument or a pan.
"""

from dataclasses import dataclass

from bitty.arrangement import Instrument


@dataclass(frozen=True)
class Voice:
    role: str
    instrument: Instrument
    pan: float


# Volume envelopes are levels 0-15 at 60 steps per second; the last step
# sustains. The pitch envelope is the attack blip that makes a chip lead read
# as percussive rather than as a held tone.
LEAD = Voice(
    role="lead",
    instrument=Instrument(
        wave="pulse",
        duty=0.5,
        volume_env=(15, 15, 14, 13, 12, 12, 11),
        pitch_env=(2, 1, 0),
    ),
    pan=-0.2,
)
COUNTER = Voice(
    role="counter",
    instrument=Instrument(
        wave="pulse",
        duty=0.25,
        volume_env=(13, 13, 12, 11, 10, 10, 9),
        pitch_env=(2, 1, 0),
    ),
    pan=0.45,
)
INNER_A = Voice(
    role="inner_a",
    instrument=Instrument(wave="pulse", duty=0.25, volume_env=(12, 11, 10, 10, 9)),
    pan=-0.45,
)
INNER_B = Voice(
    role="inner_b",
    instrument=Instrument(wave="pulse", duty=0.125, volume_env=(12, 11, 10, 10, 9)),
    pan=0.2,
)
BASS = Voice(
    role="bass",
    instrument=Instrument(wave="triangle", volume_env=(15, 14, 13, 12), quantize=16),
    pan=0.0,
)

ROSTER = (LEAD, COUNTER, INNER_A, INNER_B, BASS)

LEAD_ROLE = LEAD.role
BASS_ROLE = BASS.role
MIDDLE_ROLES = (COUNTER.role, INNER_A.role, INNER_B.role)
ARP_ROLE = INNER_B.role  # the narrowest pulse carries the overflow

ECHO_BEATS = 0.75  # the spec's [echo] delay = "3/16" of a whole note
ECHO_LEVEL = 0.35
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_voices.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add src/bitty/voices.py tests/test_voices.py
git commit -m "feat: add the five-voice roster as data"
```

---

### Task 2: Five channels out of the arranger

Voice-leading assignment across the roster, with lead and bass pinned to the
edges of the sounding texture and a monophonic rule on every channel. Middle
notes go to the nearest last pitch — Task 3 adds the free-channel preference.

**Files:**
- Rewrite: `src/bitty/arrange.py`
- Rewrite: `tests/test_arrange.py`

**Interfaces:**
- Consumes: `bitty.voices` (Task 1); `bitty.model.Note`, `bitty.model.Score`;
  `bitty.arrangement.{Arrangement, Channel, Echo, Event, MAX_VELOCITY}`.
- Produces: `arrange(score: Score) -> Arrangement`, unchanged in signature from
  Phase 1. Internal helpers `_Take`, `_assign`, `_by_onset`, `_place`,
  `_sounding`, `_last_pitch`, `_pick_middle`, `_distance`, `_events`,
  `_quantize_velocity`, and the constants `EPSILON` and `GRACE_SEC`. Tasks 3
  and 4 modify `_pick_middle` and `_assign` respectively.

- [ ] **Step 1: Write the failing tests**

Replace the whole of `tests/test_arrange.py`:

```python
from pathlib import Path

from bitty import voices
from bitty.arrange import arrange
from bitty.ingest import ingest
from bitty.model import Note, Score

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"


def note(pitch, start, dur=1.0, velocity=64, part=0):
    return Note(pitch=pitch, start=start, dur=dur, velocity=velocity, part=part)


def score_of(*notes, bpm=120.0, title="test"):
    return Score(notes=tuple(notes), bpm=bpm, time_signature=(4, 4), title=title)


def channels(arrangement):
    return {c.role: c for c in arrangement.channels}


def pitches(arrangement, role):
    return [e.pitch for e in channels(arrangement)[role].events]


def test_a_five_note_chord_fills_all_five_channels():
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0))
    )
    assert set(channels(arrangement)) == {v.role for v in voices.ROSTER}
    assert pitches(arrangement, "lead") == [72]
    assert pitches(arrangement, "bass") == [48]


def test_the_lead_keeps_the_top_line_when_an_inner_voice_moves():
    """The naive reduction hands slot one to whatever is highest right now, so
    the melody teleports the moment an inner voice moves alone. It must not."""
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=2.0),
            note(60, 0.0, dur=2.0),
            note(48, 0.0, dur=2.0),
            note(62, 1.0, dur=1.0),
        )
    )
    assert pitches(arrangement, "lead") == [72]
    assert pitches(arrangement, "bass") == [48]
    assert 62 in [e.pitch for c in arrangement.channels for e in c.events]


def test_a_channel_plays_one_note_at_a_time():
    arrangement = arrange(score_of(note(72, 0.0, dur=4.0), note(74, 1.0, dur=1.0)))
    lead = channels(arrangement)["lead"].events
    assert [e.pitch for e in lead] == [72, 74]
    assert lead[0].dur == 1.0  # cut where the next note begins


def test_silent_channels_are_left_out():
    """A two-voice score should not carry three empty channels: the synth
    divides headroom by channel count, so silent ones only cost loudness."""
    arrangement = arrange(score_of(note(72, 0.0), note(48, 0.0)))
    assert [c.role for c in arrangement.channels] == ["lead", "bass"]


def test_grace_notes_survive_as_short_notes():
    """music21 gives grace notes zero quarter-length. A chip channel cannot
    play zero seconds, so they get a floor instead of disappearing."""
    arrangement = arrange(score_of(note(72, 0.0, dur=1.0), note(79, 0.0, dur=0.0)))
    lead = channels(arrangement)["lead"].events
    assert lead[0].pitch == 79
    assert lead[0].dur == 0.032


def test_velocity_is_quantized_to_sixteen_levels():
    arrangement = arrange(ingest(FIXTURE))
    for channel in arrangement.channels:
        for event in channel.events:
            assert 0 <= event.vel <= 15


def test_multi_part_score_keeps_the_top_and_bottom_parts():
    arrangement = arrange(ingest(FIXTURE))
    assert pitches(arrangement, "lead") == [72, 74, 76, 77]
    assert pitches(arrangement, "bass") == [48]


def test_the_roster_supplies_the_timbre_and_the_image():
    arrangement = arrange(ingest(FIXTURE))
    lead = channels(arrangement)["lead"]
    assert lead.instrument == voices.LEAD.instrument
    assert lead.pan == voices.LEAD.pan


def test_only_the_lead_echoes():
    """A delayed bass turns into mud; the tail belongs on the tune."""
    arrangement = arrange(ingest(FIXTURE))
    assert channels(arrangement)["lead"].echo is not None
    assert all(c.echo is None for c in arrangement.channels if c.role != "lead")


def test_echo_delay_tracks_the_tempo():
    """Three sixteenths of a whole note is 0.75 beats — 0.375s at 120 bpm."""
    arrangement = arrange(ingest(FIXTURE))
    assert abs(channels(arrangement)["lead"].echo.delay_sec - 0.375) < 1e-9


def test_arrangement_meta_carries_title_and_tempo():
    arrangement = arrange(ingest(FIXTURE))
    assert arrangement.meta["bpm"] == 120.0
    assert isinstance(arrangement.meta["title"], str)
    assert arrangement.meta["title"]


def test_the_filter_stays_off_by_default():
    arrangement = arrange(ingest(FIXTURE))
    assert all(c.instrument.cutoff_hz is None for c in arrangement.channels)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_arrange.py -v`
Expected: FAIL — `test_a_five_note_chord_fills_all_five_channels` reports two
channels, `ImportError` on `bitty.voices` is already fixed by Task 1.

- [ ] **Step 3: Rewrite the arranger**

Replace the whole of `src/bitty/arrange.py`:

```python
"""Score to Arrangement: deciding which chip channel plays each note.

The reduction, not the sound. Notes are grouped by onset; the top of the
sounding texture is pinned to the lead and the bottom to the bass, and
everything between goes to the channel whose last pitch is nearest. A channel
is monophonic, so placing a note on a busy channel truncates what it was
holding.

The naive alternative — re-sort each chord top-to-bottom and hand slot one the
highest note — produces a melody that teleports whenever an inner voice briefly
rises above it. Voice-leading assignment is the difference between a
recognizable tune and note soup.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from bitty.arrangement import MAX_VELOCITY, Arrangement, Channel, Echo, Event
from bitty.model import Note, Score
from bitty.voices import (
    BASS_ROLE,
    ECHO_BEATS,
    ECHO_LEVEL,
    LEAD_ROLE,
    MIDDLE_ROLES,
    ROSTER,
)

EPSILON = 1e-6  # onset times are floats; anything closer than this is one moment
GRACE_SEC = 0.032  # music21 gives grace notes zero length; a channel needs some


@dataclass
class _Take:
    """A note as placed on one channel. Mutable: a later note truncates it."""

    t: float
    pitch: int
    dur: float
    vel: int


Tracks = dict[str, list[_Take]]


def arrange(score: Score) -> Arrangement:
    tracks = _assign(score)

    channels: list[Channel] = []
    for voice in ROSTER:
        events = _events(tracks[voice.role])
        if not events:
            continue  # a two-voice score should not carry three silent channels
        channels.append(
            Channel(
                role=voice.role,
                instrument=voice.instrument,
                events=events,
                pan=voice.pan,
                echo=_echo(score.bpm) if voice.role == LEAD_ROLE else None,
            )
        )

    return Arrangement(
        meta={"title": score.title, "bpm": score.bpm},
        channels=tuple(channels),
    )


def _echo(bpm: float) -> Echo:
    return Echo(delay_sec=ECHO_BEATS * 60.0 / bpm, level=ECHO_LEVEL)


def _assign(score: Score) -> Tracks:
    tracks: Tracks = {voice.role: [] for voice in ROSTER}

    for onset, pending in _by_onset(score.notes):
        used: set[str] = set()
        held = [
            pitch
            for pitch in (_sounding(tracks[voice.role], onset) for voice in ROSTER)
            if pitch is not None
        ]

        # Pinning is against the whole sounding texture, not just this onset:
        # a lone moving inner note must not displace a lead that is still ringing.
        if not held or pending[0].pitch >= max(held):
            _place(tracks[LEAD_ROLE], pending.pop(0))
            used.add(LEAD_ROLE)

        if pending and (not held or pending[-1].pitch <= min(held)):
            _place(tracks[BASS_ROLE], pending.pop())
            used.add(BASS_ROLE)

        for note in pending:
            role = _pick_middle(tracks, note, used)
            if role is None:
                continue  # Task 4 turns these leftovers into an arpeggio
            _place(tracks[role], note)
            used.add(role)

    return tracks


def _by_onset(notes: tuple[Note, ...]) -> list[tuple[float, list[Note]]]:
    """Group simultaneous notes, highest pitch first within each group."""
    ordered = sorted(notes, key=lambda n: (n.start, -n.pitch))
    return [(onset, list(group)) for onset, group in groupby(ordered, key=lambda n: n.start)]


def _place(takes: list[_Take], note: Note) -> None:
    """Add a note to a channel, cutting short whatever it was holding."""
    if takes and takes[-1].t + takes[-1].dur > note.start + EPSILON:
        takes[-1].dur = note.start - takes[-1].t
    takes.append(
        _Take(
            t=note.start,
            pitch=note.pitch,
            dur=max(note.dur, GRACE_SEC),
            vel=_quantize_velocity(note.velocity),
        )
    )


def _sounding(takes: list[_Take], t: float) -> int | None:
    """The pitch this channel is still holding at t, or None if it is free."""
    if takes and takes[-1].t + takes[-1].dur > t + EPSILON:
        return takes[-1].pitch
    return None


def _last_pitch(takes: list[_Take]) -> int | None:
    return takes[-1].pitch if takes else None


def _pick_middle(tracks: Tracks, note: Note, used: set[str]) -> str | None:
    options = [role for role in MIDDLE_ROLES if role not in used]
    if not options:
        return None
    return min(options, key=lambda role: _distance(_last_pitch(tracks[role]), note.pitch))


def _distance(last_pitch: int | None, pitch: int) -> int:
    """An untouched channel wins ties: it has no line to lead away from yet."""
    return 0 if last_pitch is None else abs(last_pitch - pitch)


def _events(takes: list[_Take]) -> tuple[Event, ...]:
    return tuple(
        Event(t=take.t, pitch=take.pitch, dur=take.dur, vel=take.vel)
        for take in takes
        if take.dur > EPSILON
    )


def _quantize_velocity(velocity: int) -> int:
    """127 MIDI steps down to the 16 levels an 8-bit channel actually has."""
    return max(0, min(MAX_VELOCITY, round(velocity / 127 * MAX_VELOCITY)))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_arrange.py -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS. `tests/test_cli.py::test_written_arrangement_reloads` asserts
the roles are `["lead", "bass"]` for the two-part fixture — that still holds,
because empty channels are dropped. If it fails, the empty-channel filter in
`arrange()` is wrong; fix that rather than the test.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/arrange.py tests/test_arrange.py
git commit -m "feat: assign notes across five channels by voice leading"
```

---

### Task 3: Prefer a free channel over a nearer busy one

**Files:**
- Modify: `src/bitty/arrange.py` (`_pick_middle` and its call site in `_assign`)
- Modify: `tests/test_arrange.py` (add two tests)

**Interfaces:**
- Produces: `_pick_middle(tracks: Tracks, onset: float, note: Note, used: set[str]) -> str | None`
  — the signature gains `onset`, because "free" is a question about a moment in
  time. Task 4 calls it unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_arrange.py`:

```python
def test_a_sustained_inner_voice_is_not_cut_short_for_a_nearby_note():
    """Prefer-free: a hole in the harmony costs more than a timbre jump."""
    arrangement = arrange(
        score_of(
            # every middle channel takes a note, so none is attractive merely
            # for being untouched
            note(72, 0.0, dur=0.5),
            note(67, 0.0, dur=0.5),
            note(64, 0.0, dur=0.5),
            note(62, 0.0, dur=0.5),
            note(48, 0.0, dur=0.5),
            # the counter voice then holds 67 for four seconds
            note(72, 0.5, dur=4.0),
            note(67, 0.5, dur=4.0),
            note(48, 0.5, dur=4.0),
            # 66 is nearest to the counter's 67 — but the counter is mid-note
            note(66, 1.0, dur=1.0),
        )
    )
    counter = channels(arrangement)["counter"].events
    assert [e.pitch for e in counter] == [67, 67]
    assert counter[1].dur == 4.0, "the held 67 must survive intact"
    assert 66 in pitches(arrangement, "inner_a")


def test_when_every_channel_is_busy_the_nearest_one_is_stolen():
    """Stealing is the fallback, not the rule — but it is still the fallback."""
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=4.0),
            note(67, 0.0, dur=4.0),
            note(64, 0.0, dur=4.0),
            note(62, 0.0, dur=4.0),
            note(48, 0.0, dur=4.0),
            note(65, 1.0, dur=1.0),  # nearest last pitch is inner_a's 64
        )
    )
    inner_a = channels(arrangement)["inner_a"].events
    assert [e.pitch for e in inner_a] == [64, 65]
    assert inner_a[0].dur == 1.0
```

- [ ] **Step 2: Run the tests to verify the first one fails**

Run: `.venv/bin/pytest tests/test_arrange.py -k "sustained_inner or every_channel_is_busy" -v`
Expected: `test_a_sustained_inner_voice_is_not_cut_short_for_a_nearby_note`
FAILS (the held 67 is truncated to 0.5); `test_when_every_channel_is_busy_the_nearest_one_is_stolen`
already PASSES and must keep passing.

- [ ] **Step 3: Prefer free channels**

In `src/bitty/arrange.py`, change the call site inside `_assign`:

```python
            role = _pick_middle(tracks, onset, note, used)
```

and replace `_pick_middle` with:

```python
def _pick_middle(tracks: Tracks, onset: float, note: Note, used: set[str]) -> str | None:
    """Nearest last pitch, but only among channels that are not mid-note.

    Stealing is the fallback rather than the rule. A held inner voice cut short
    leaves a hole in the harmony, which the ear reads as the texture breaking;
    a note landing on a further-away channel is only a change of colour.
    """
    options = [role for role in MIDDLE_ROLES if role not in used]
    if not options:
        return None
    free = [role for role in options if _sounding(tracks[role], onset) is None]
    return min(
        free or options,
        key=lambda role: _distance(_last_pitch(tracks[role]), note.pitch),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_arrange.py -v`
Expected: PASS, 14 tests

- [ ] **Step 5: Commit**

```bash
git add src/bitty/arrange.py tests/test_arrange.py
git commit -m "feat: keep sustained voices alive by preferring free channels"
```

---

### Task 4: Arpeggio overflow

When more than five notes sound at once, the leftovers fold into the narrowest
pulse and cycle through at 16 ms per step. This is how real hardware faked a
chord in one channel, and the ear hears it as harmony. Dense passages degrade
into something idiomatic instead of something broken — and nothing is dropped.

**Files:**
- Modify: `src/bitty/arrange.py`
- Modify: `tests/test_arrange.py` (add four tests)

**Interfaces:**
- Produces: `_assign(score) -> tuple[Tracks, list[tuple[float, list[Note]]]]`
  — now returns leftovers alongside the tracks. New helpers `_arpeggiate`,
  `_arp_cycle`, `_clip_overlaps`, and the constant `ARP_STEP_SEC = 0.016`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_arrange.py`:

```python
def test_a_six_note_chord_arpeggiates_the_overflow():
    """One channel stepping through the leftovers fast enough to read as chord."""
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=1.0),
            note(69, 0.0, dur=1.0),
            note(67, 0.0, dur=1.0),
            note(64, 0.0, dur=1.0),
            note(62, 0.0, dur=1.0),
            note(48, 0.0, dur=1.0),
        )
    )
    arp = channels(arrangement)["inner_b"].events
    assert len(arp) == 62  # int(1.0 / 0.016)
    assert [e.dur for e in arp] == [0.016] * 62
    # the channel's own note joins the cycle rather than being replaced by it
    assert [e.pitch for e in arp[:4]] == [62, 64, 62, 64]
    assert abs(arp[1].t - 0.016) < 1e-9


def test_nothing_is_dropped_when_the_channels_run_out():
    arrangement = arrange(
        score_of(*[note(p, 0.0, dur=1.0) for p in (72, 69, 67, 64, 62, 60, 48)])
    )
    heard = {e.pitch for c in arrangement.channels for e in c.events}
    assert {72, 69, 67, 64, 62, 60, 48} <= heard


def test_sparse_writing_produces_no_arpeggio():
    arrangement = arrange(
        score_of(note(72, 0.0, dur=1.0), note(64, 0.0, dur=1.0), note(48, 0.0, dur=1.0))
    )
    assert all(e.dur == 1.0 for c in arrangement.channels for e in c.events)


def test_the_arpeggio_never_overlaps_the_channel_s_own_notes():
    arrangement = arrange(
        score_of(
            *[note(p, 0.0, dur=1.0) for p in (72, 69, 67, 64, 62, 48)],
            note(60, 0.5, dur=0.5),  # lands on the arpeggiating channel mid-cycle
        )
    )
    events = channels(arrangement)["inner_b"].events
    for earlier, later in zip(events, events[1:]):
        assert earlier.t + earlier.dur <= later.t + 1e-6
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_arrange.py -k "arpeggiate or dropped or sparse or overlaps" -v`
Expected: FAIL — the sixth note is dropped, so `inner_b` holds one long note.

- [ ] **Step 3: Fold the leftovers into a cycling line**

In `src/bitty/arrange.py`, add the constant next to `GRACE_SEC`:

```python
ARP_STEP_SEC = 0.016  # the spec's [arp] rate_ms = 16
```

Add `ARP_ROLE` to the `bitty.voices` import list. Change `arrange()` to run the
post-pass:

```python
def arrange(score: Score) -> Arrangement:
    tracks, leftovers = _assign(score)
    tracks[ARP_ROLE] = _arpeggiate(leftovers, tracks[ARP_ROLE])
```

Change `_assign` to collect leftovers instead of dropping them — its signature,
the `spare` list, and the return:

```python
def _assign(score: Score) -> tuple[Tracks, list[tuple[float, list[Note]]]]:
    tracks: Tracks = {voice.role: [] for voice in ROSTER}
    leftovers: list[tuple[float, list[Note]]] = []

    for onset, pending in _by_onset(score.notes):
        used: set[str] = set()
        held = [
            pitch
            for pitch in (_sounding(tracks[voice.role], onset) for voice in ROSTER)
            if pitch is not None
        ]

        if not held or pending[0].pitch >= max(held):
            _place(tracks[LEAD_ROLE], pending.pop(0))
            used.add(LEAD_ROLE)

        if pending and (not held or pending[-1].pitch <= min(held)):
            _place(tracks[BASS_ROLE], pending.pop())
            used.add(BASS_ROLE)

        spare: list[Note] = []
        for note in pending:
            role = _pick_middle(tracks, onset, note, used)
            if role is None:
                spare.append(note)
                continue
            _place(tracks[role], note)
            used.add(role)

        if spare:
            leftovers.append((onset, spare))

    return tracks, leftovers
```

Add the three new functions:

```python
def _arpeggiate(
    leftovers: list[tuple[float, list[Note]]], takes: list[_Take]
) -> list[_Take]:
    """Fold notes that found no channel into one fast-cycling line.

    The channel's own note at that moment joins the cycle rather than being
    replaced by it, so the arpeggio carries the whole chord and not just the
    part that would otherwise have been lost.
    """
    out = list(takes)

    for onset, notes in leftovers:
        absorbed = [take for take in out if abs(take.t - onset) <= EPSILON]
        for take in absorbed:
            out.remove(take)

        pitches = sorted({n.pitch for n in notes} | {take.pitch for take in absorbed})
        # The cycle lasts only as long as its shortest member: a note that has
        # ended must not keep sounding just because the arpeggio is still running.
        span = min([n.dur for n in notes] + [take.dur for take in absorbed])
        vel = max(
            [_quantize_velocity(n.velocity) for n in notes] + [take.vel for take in absorbed]
        )
        out.extend(_arp_cycle(onset, span, pitches, vel))

    return _clip_overlaps(sorted(out, key=lambda take: take.t))


def _arp_cycle(onset: float, span: float, pitches: list[int], vel: int) -> list[_Take]:
    steps = max(1, int(span / ARP_STEP_SEC))
    return [
        _Take(
            t=onset + step * ARP_STEP_SEC,
            pitch=pitches[step % len(pitches)],
            dur=ARP_STEP_SEC,
            vel=vel,
        )
        for step in range(steps)
    ]


def _clip_overlaps(takes: list[_Take]) -> list[_Take]:
    """One channel, one note — including where a cycle runs into a held note."""
    for earlier, later in zip(takes, takes[1:]):
        if earlier.t + earlier.dur > later.t + EPSILON:
            earlier.dur = later.t - earlier.t
    return [take for take in takes if take.dur > EPSILON]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_arrange.py -v`
Expected: PASS, 18 tests

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/bitty/arrange.py tests/test_arrange.py
git commit -m "feat: arpeggiate the notes that run out of channels"
```

---

### Task 5: Golden arrangement tests

An arranger regression should surface as a readable JSON diff, not as changed
audio. Three checked-in excerpts span easy to hard: a homophonic chorale where
every voice moves together, a minuet with four independent parts and real
sustains, and ragtime whose six-note chords force the arpeggio. The spec asks
for a fugue exposition as the hard case; music21's bundled corpus has no fugue,
and ragtime stresses overflow harder, so it takes that slot.

**Files:**
- Create: `tests/fixtures/chorale.mxl`, `tests/fixtures/minuet.mxl`, `tests/fixtures/ragtime.mxl`
- Create: `tests/goldens/chorale.arrangement.json`, `.../minuet.arrangement.json`, `.../ragtime.arrangement.json`
- Create: `tests/test_goldens.py`

**Interfaces:**
- Consumes: `arrange` and `ingest`, unchanged.
- Produces: no new source API. `BITTY_UPDATE_GOLDENS=1` regenerates the goldens.

- [ ] **Step 1: Export the fixtures**

```bash
mkdir -p tests/goldens
.venv/bin/python - <<'PY'
from music21 import corpus

for name, out, lo, hi in [
    ("bach/bwv66.6", "chorale.mxl", 1, 8),
    ("mozart/k80/movement3", "minuet.mxl", 1, 16),
    ("joplin/maple_leaf_rag", "ragtime.mxl", 1, 16),
]:
    corpus.parse(name).measures(lo, hi).write("mxl", fp=f"tests/fixtures/{out}")
    print(out)
PY
ls -l tests/fixtures/*.mxl
```

Expected: three files, roughly 2.3 KB, 3.2 KB, and 5.6 KB.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_goldens.py`:

```python
import os
from pathlib import Path

import pytest

from bitty.arrange import arrange
from bitty.ingest import ingest

FIXTURES = Path(__file__).parent / "fixtures"
GOLDENS = Path(__file__).parent / "goldens"
NAMES = ["chorale", "minuet", "ragtime"]
EPSILON = 1e-6


def arranged(name):
    return arrange(ingest(FIXTURES / f"{name}.mxl"))


@pytest.mark.parametrize("name", NAMES)
def test_arrangement_matches_its_golden(name):
    """A reduction regression reads as a JSON diff, not as changed audio."""
    actual = arranged(name).to_json()
    golden = GOLDENS / f"{name}.arrangement.json"
    if os.environ.get("BITTY_UPDATE_GOLDENS"):
        golden.write_text(actual)
    assert actual == golden.read_text(), (
        f"the {name} arrangement changed. If that is intended, regenerate with "
        "BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py and read the diff."
    )


@pytest.mark.parametrize("name", NAMES)
def test_no_channel_plays_two_notes_at_once(name):
    """A chip channel is monophonic; overlapping events would be a lie."""
    for channel in arranged(name).channels:
        for earlier, later in zip(channel.events, channel.events[1:]):
            assert earlier.t + earlier.dur <= later.t + EPSILON


@pytest.mark.parametrize("name", NAMES)
def test_every_source_note_is_heard(name):
    """Nothing vanishes: overflow arpeggiates, and grace notes get a floor."""
    score = ingest(FIXTURES / f"{name}.mxl")
    events = [e for c in arranged(name).channels for e in c.events]
    for note in score.notes:
        assert any(
            e.pitch == note.pitch
            and note.start - EPSILON <= e.t <= note.start + note.dur + EPSILON
            for e in events
        ), f"{note} never sounds"


@pytest.mark.parametrize("name", NAMES)
def test_events_are_playable(name):
    for channel in arranged(name).channels:
        assert channel.events
        for event in channel.events:
            assert event.dur > 0.0
            assert 0 <= event.vel <= 15


def test_dense_writing_arpeggiates_and_sparse_writing_does_not():
    ragtime = {c.role: c.events for c in arranged("ragtime").channels}
    chorale = {c.role: c.events for c in arranged("chorale").channels}
    steps = [e for e in ragtime["inner_b"] if abs(e.dur - 0.016) < 1e-9]
    assert len(steps) > 50, "six-note ragtime chords should overflow into an arpeggio"
    assert not [e for e in chorale["inner_b"] if abs(e.dur - 0.016) < 1e-9]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_goldens.py -v`
Expected: the three `test_arrangement_matches_its_golden` cases FAIL with
`FileNotFoundError` on the missing golden files. The invariant tests should
already PASS — if `test_every_source_note_is_heard` fails, stop and investigate
rather than loosening the assertion: a silently dropped note is the exact defect
Task 4 exists to prevent.

- [ ] **Step 4: Generate the goldens and read them**

```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py -q
head -40 tests/goldens/chorale.arrangement.json
.venv/bin/python -c "
import json
for name in ['chorale', 'minuet', 'ragtime']:
    data = json.load(open(f'tests/goldens/{name}.arrangement.json'))
    print(name, {c['role']: len(c['events']) for c in data['channels']})
"
```

Expected roughly: chorale `{lead: 31, counter: 30, inner_a: 31, inner_b: 16, bass: 36}`,
minuet `{lead: 44, counter: 31, inner_a: 1, inner_b: 35, bass: 45}`, ragtime
`{lead: 104, counter: 44, inner_a: 38, inner_b: 169, bass: 53}`. The minuet's
near-empty `inner_a` is expected, not a bug: the source has four parts, so the
arranger only needs two middle channels and the third picks up a single stray.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_goldens.py -v`
Expected: PASS, 13 tests

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/*.mxl tests/goldens tests/test_goldens.py
git commit -m "test: lock the reduction down with golden arrangements"
```

---

### Task 6: `bitty render`

The convert/render split is what makes hand-editing practical: fixing an
arrangement should cost a JSON edit and a one-second re-render, not a full
re-analysis.

**Files:**
- Modify: `src/bitty/cli.py`
- Modify: `tests/test_cli.py` (add four tests)

**Interfaces:**
- Consumes: `Arrangement.from_json` (existing), `bitty.synth.render`.
- Produces: the `render` CLI command; internal `_write_audio(arrangement, out_dir, stem, wav) -> Path`
  and `_stem(path) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_render_reproduces_the_audio_from_an_arrangement(tmp_path):
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path), "--wav"])
    before, _ = sf.read(tmp_path / "two_part.wav")
    (tmp_path / "two_part.wav").unlink()

    result = runner.invoke(
        app, ["render", str(tmp_path / "two_part.arrangement.json"), "-o", str(tmp_path), "--wav"]
    )

    assert result.exit_code == 0, result.output
    after, _ = sf.read(tmp_path / "two_part.wav")
    assert np.array_equal(before, after)


def test_render_names_the_output_after_the_piece(tmp_path):
    """`foo.arrangement.json` re-renders to `foo.wav`, not `foo.arrangement.wav`."""
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    runner.invoke(
        app, ["render", str(tmp_path / "two_part.arrangement.json"), "-o", str(tmp_path), "--wav"]
    )
    assert (tmp_path / "two_part.wav").exists()
    assert not (tmp_path / "two_part.arrangement.wav").exists()


def test_a_hand_edited_arrangement_renders_without_reanalysis(tmp_path):
    """The whole point of the split: the JSON overrules the arranger."""
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    path = tmp_path / "two_part.arrangement.json"
    data = json.loads(path.read_text())
    data["channels"] = data["channels"][:1]
    path.write_text(json.dumps(data))

    result = runner.invoke(app, ["render", str(path), "-o", str(tmp_path), "--wav"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "two_part.wav").exists()


def test_render_rejects_a_missing_arrangement(tmp_path):
    result = runner.invoke(
        app, ["render", str(tmp_path / "nope.arrangement.json"), "-o", str(tmp_path)]
    )
    assert result.exit_code != 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -k render -v`
Expected: FAIL — `render` is not a command, so the exit code is 2.

- [ ] **Step 3: Add the command**

Replace the whole of `src/bitty/cli.py`:

```python
"""Command-line entry point."""

from pathlib import Path

import soundfile as sf
import typer

from bitty.arrange import arrange
from bitty.arrangement import Arrangement
from bitty.ingest import ingest
from bitty.synth import SAMPLE_RATE
from bitty.synth import render as render_audio

app = typer.Typer(help="Turn classical scores into chiptune audio.")

ARRANGEMENT_SUFFIX = ".arrangement.json"


@app.callback()
def main() -> None:
    """Keep subcommand dispatch rather than folding a lone command into the root."""


@app.command()
def convert(
    score: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(Path("out"), "-o", "--out-dir"),
    wav: bool = typer.Option(False, "--wav", help="Write uncompressed WAV instead of Ogg."),
) -> None:
    """Convert a score to audio and its arrangement JSON."""
    arrangement = arrange(ingest(score))
    _write_audio(arrangement, out_dir, score.stem, wav)

    json_path = out_dir / f"{score.stem}{ARRANGEMENT_SUFFIX}"
    json_path.write_text(arrangement.to_json())
    typer.echo(f"{json_path}")


@app.command()
def render(
    arrangement: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(Path("out"), "-o", "--out-dir"),
    wav: bool = typer.Option(False, "--wav", help="Write uncompressed WAV instead of Ogg."),
) -> None:
    """Re-render a hand-edited arrangement, skipping analysis entirely."""
    _write_audio(
        Arrangement.from_json(arrangement.read_text()),
        out_dir,
        _stem(arrangement),
        wav,
    )


def _write_audio(arrangement: Arrangement, out_dir: Path, stem: str, wav: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    audio = render_audio(arrangement)
    path = out_dir / f"{stem}{'.wav' if wav else '.ogg'}"

    if wav:
        sf.write(path, audio, SAMPLE_RATE)
    else:
        sf.write(path, audio, SAMPLE_RATE, format="OGG", subtype="VORBIS")

    typer.echo(f"{path}  ({len(audio) / SAMPLE_RATE:.1f}s)")
    return path


def _stem(path: Path) -> str:
    """`foo.arrangement.json` re-renders to `foo.ogg`, not `foo.arrangement.ogg`."""
    if path.name.endswith(ARRANGEMENT_SUFFIX):
        return path.name[: -len(ARRANGEMENT_SUFFIX)]
    return path.stem
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/bitty/cli.py tests/test_cli.py
git commit -m "feat: add bitty render for hand-edited arrangements"
```

---

### Task 7: The acceptance listen

Every phase ends with something audible. Phase 3a's question is whether five
voices assigned by voice leading beat two voices taken from the top and bottom —
and whether the arpeggio reads as harmony rather than as a broken melody.

**Files:**
- Modify: `docs/superpowers/plans/2026-08-20-phase-3a-arranger.md` (outcome section)

- [ ] **Step 1: Render all three fixtures**

Audition renders must be WAV: `aplay` cannot decode Ogg and plays it as static.

```bash
.venv/bin/bitty convert tests/fixtures/chorale.mxl -o out/ --wav
.venv/bin/bitty convert tests/fixtures/minuet.mxl -o out/ --wav
.venv/bin/bitty convert tests/fixtures/ragtime.mxl -o out/ --wav
```

- [ ] **Step 2: Listen against Phase 2**

```bash
aplay out/chorale.wav
aplay out/minuet.wav
aplay out/ragtime.wav
```

The bar to clear:

- The melody stays put. It does not jump to an inner voice when one briefly
  rises above it.
- Chords sound like chords. Inner voices sustain instead of flickering.
- The ragtime's dense chords read as harmony, not as a stuck sixteenth-note
  machine gun. If the arpeggio is the thing that bothers you, `ARP_STEP_SEC` is
  the knob — that is Phase 5's preset material, and the number to record here.
- Nothing is obviously missing versus the score.

- [ ] **Step 3: Record the outcome**

Append an "Outcome of the acceptance listen" section to this plan, in the shape
of Phase 2's: what was heard, what was decided, and which knob to expose in
Phase 5 if the question is not firmly settled. Then:

```bash
git add docs/superpowers/plans/2026-08-20-phase-3a-arranger.md
git commit -m "docs: record the Phase 3a acceptance listen"
```

- [ ] **Step 4: Finish the branch**

Use the superpowers:finishing-a-development-branch skill. Phase 1 and Phase 2
each landed on `main` as a `--no-ff` merge; follow that.

---

## Phase 3a exit criteria

- `.venv/bin/pytest` passes.
- `bitty convert` fills five channels on dense sources and drops the silent ones
  on sparse sources.
- A sustained inner voice survives a moving line above it; a melody never jumps
  to an inner voice.
- No note in any fixture is silently dropped — overflow arpeggiates, grace notes
  get a floor, and `test_every_source_note_is_heard` proves it.
- No channel ever holds two notes at once.
- Golden arrangements exist for all three fixtures and diff readably.
- `bitty render` re-renders a hand-edited `arrangement.json` byte-identically to
  what `convert` produced from the same arrangement.
- The acceptance listen has happened and its outcome is recorded here.

Phase 3b adds articulation against this contract: delayed vibrato on sustained
notes, ornament shaping, and the dynamics work that goes with them. It adds
fields to `Instrument` or `Event` and teaches `synth.py` to read them; it does
not change who plays what.
