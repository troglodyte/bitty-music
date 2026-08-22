# Phase 7: The Arpeggio Plays In Tune — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an arpeggio one note whose pitch cycles, instead of 62 fresh
notes a second, so arpeggiated pitches sound in tune.

**Architecture:** `Event` gains `arp` — semitone offsets from its own pitch —
and `Instrument` gains `arp_rate_sec`, because the synth must know the rate
and a hand-edited file has to render without config. The synth cycles those
offsets into the pitch increment the way `pitch_env` already folds in its
own; the arranger emits one take per overflow onset instead of a cycle.

**Tech Stack:** Python 3.14, stdlib `dataclasses`/`json`, numpy, pytest.
Run everything with `.venv/bin/`.

**Spec:** `docs/superpowers/specs/2026-08-22-phase-7-arpeggio-design.md`

## Global Constraints

- **The bug, stated exactly.** Each arp step is a separate `Event` of
  `arp.step_sec` (16 ms). The envelope step is 1/60 s ≈ 16.7 ms, so every
  step restarts its instrument's envelopes and never advances past index 0.
  On `counter` (`pitch_env = (2, 1, 0)`) a step naming A4/440 Hz sounds at
  499.7 Hz — a whole tone sharp — at constant attack volume, with the
  oscillator phase reset every 16 ms.
- **Scope is the mechanism only.** The same notes overflow at the same
  onsets. Do NOT change which notes are arpeggiated, do NOT add a way to
  request an arpeggio, and do NOT touch the `count = 3` reduction policy.
- **The goldens move, and that is correct.** Every previous phase forbade
  `BITTY_UPDATE_GOLDENS=1`. This phase requires it — twice, in Tasks 1 and
  4 — and each regenerated diff must be **read line by line** before it is
  committed. Never regenerate to make a red suite green without reading why
  it went red.
- **`arp` must be a tuple, not a list.** `Event` is frozen; a list field
  breaks hashing and equality. `_event_from` must convert on load, the way
  `_instrument_from` already does for `volume_env` and `pitch_env`.
- **Backward compatibility is already handled.** `_event_from` and
  `_instrument_from` drop unknown keys, so older files load. Do not add
  version checks.
- **Every test is proven by breaking the implementation.** After a test
  passes, break the code it covers, re-run, confirm it fails, restore. This
  project has a standing history of shipping tests that pass broken code —
  and a phase where a ratio test could not detect a constant, and a
  saturated signal masked the spread being measured. Prefer breaking the
  code in the *plausible wrong way*, not merely some way.

---

### Task 1: The contract gains `arp` and `arp_rate_sec`

**Files:**
- Modify: `src/bitty/arrangement.py`
- Test: `tests/test_arrangement.py`
- Regenerate: `tests/goldens/*.arrangement.json`

**Interfaces:**
- Consumes: nothing.
- Produces: `ARP_RATE_SEC = 0.016`; `Event.arp: tuple[int, ...] = ()`
  (semitone offsets from the event's own `pitch`, cycling);
  `Instrument.arp_rate_sec: float = ARP_RATE_SEC`.

- [ ] **Step 1: Capture the "before" audio — do this FIRST, before any edit**

This task is the contract, but the audition in Task 5 needs a recording of
what the arpeggio sounds like *today*, and today is only available before
you change anything. Two renders, WAV only (`aplay` renders Ogg as static):

```bash
mkdir -p /tmp/bitty-phase7/before
.venv/bin/bitty convert tests/fixtures/ragtime.mxl -o /tmp/bitty-phase7/before/ragtime --wav
printf '[voices]\ncount = 3\n' > /tmp/bitty-phase7/count3.toml
.venv/bin/bitty convert tests/fixtures/minuet.mxl -o /tmp/bitty-phase7/before/minuet-count3 \
  --wav --config /tmp/bitty-phase7/count3.toml
ls -R /tmp/bitty-phase7/before
```

Confirm both WAV files exist before continuing. If you skip this step the
audition has nothing to compare against and cannot be redone later in the
branch.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_arrangement.py`, following that file's existing style:

```python
def test_an_event_carries_no_arpeggio_by_default():
    assert Event(t=0.0, pitch=60, dur=1.0, vel=15).arp == ()


def test_an_arpeggio_survives_the_json_round_trip_as_a_tuple():
    """A list would break Event's hashing and equality; it is frozen."""
    event = Event(t=0.0, pitch=60, dur=1.0, vel=15, arp=(0, 4, 7))
    channel = Channel(role="lead", instrument=Instrument(wave="pulse"), events=(event,))
    restored = Arrangement.from_json(
        Arrangement(meta={"title": "t", "bpm": 120.0}, channels=(channel,)).to_json()
    )
    loaded = restored.channels[0].events[0]
    assert loaded.arp == (0, 4, 7)
    assert isinstance(loaded.arp, tuple)


def test_an_unknown_event_field_is_still_dropped():
    """The contract that keeps a newer bitty's file loadable in an older one."""
    raw = '''{"meta": {"title": "t", "bpm": 120.0}, "channels": [{"role": "lead",
      "instrument": {"wave": "pulse"},
      "events": [{"t": 0.0, "pitch": 60, "dur": 1.0, "vel": 15,
                  "arp": [0, 7], "glissando": 3}]}]}'''
    event = Arrangement.from_json(raw).channels[0].events[0]
    assert event.arp == (0, 7)


def test_an_instrument_carries_the_default_arp_rate():
    """The rate travels in the arrangement for the reason vibrato's does:
    a hand-edited file must render the same with no config anywhere."""
    assert Instrument(wave="pulse").arp_rate_sec == ARP_RATE_SEC
    assert ARP_RATE_SEC == 0.016
```

Check the top of `tests/test_arrangement.py` and add whichever of `Event`,
`Channel`, `Instrument`, `Arrangement`, and `ARP_RATE_SEC` it does not
already import.

- [ ] **Step 3: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_arrangement.py -v -k "arp"
```

Expected: FAIL at import — `cannot import name 'ARP_RATE_SEC'`.

- [ ] **Step 4: Add the fields**

In `src/bitty/arrangement.py`, add the constant beside the vibrato ones,
which already live there for exactly this reason:

```python
VIBRATO_RATE_HZ = 5.5
ARP_RATE_SEC = 0.016  # seconds per cycle step; the classic hardware rate
```

Add the field to `Event`:

```python
@dataclass(frozen=True)
class Event:
    t: float  # seconds from the start of the arrangement
    pitch: int  # MIDI note number
    dur: float  # seconds
    vel: int  # 0-15
    vibrato: bool = False  # a delayed LFO on the pitch; see lfo.py
    arp: tuple[int, ...] = ()  # semitone offsets from `pitch`, cycling; () is none
```

Add the field to `Instrument`, after the vibrato fields:

```python
    arp_rate_sec: float = ARP_RATE_SEC  # seconds per arpeggio step
```

And teach `_event_from` the tuple conversion `_instrument_from` already does:

```python
def _event_from(raw: dict) -> Event:
    """Build an Event, dropping any field this build does not know.

    The same contract `_instrument_from` keeps, for the same reason: adding a
    field should not turn every older build into a hard failure on load.
    """
    known = {f.name for f in fields(Event)}
    kwargs = {k: v for k, v in raw.items() if k in known}
    if "arp" in kwargs:
        kwargs["arp"] = tuple(kwargs["arp"])
    return Event(**kwargs)
```

- [ ] **Step 5: Run the new tests**

```bash
.venv/bin/pytest tests/test_arrangement.py -v -k "arp"
```

Expected: PASS.

- [ ] **Step 6: Regenerate the goldens and READ the diff**

`asdict` serialises every field, so each event now emits `"arp": []` and
each instrument `"arp_rate_sec": 0.016`. That is a purely additive change.

```bash
.venv/bin/pytest tests/test_goldens.py 2>&1 | tail -5
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
git diff --stat tests/goldens/
git diff tests/goldens/ | head -40
```

**Read the diff and confirm it is only additions of `"arp": []` and
`"arp_rate_sec": 0.016`.** If any existing value changed — a pitch, a
duration, a velocity — stop and report it: adding an unused field must not
move anything.

Verify mechanically as well:

```bash
git diff -U0 tests/goldens/ | grep '^[-+]' | grep -v '^[-+][-+]' | grep '^-' | head
```

Expected: no output. A purely additive diff removes no lines.

- [ ] **Step 7: Run the full suite**

```bash
.venv/bin/pytest
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/bitty/arrangement.py tests/test_arrangement.py tests/goldens/
git commit -m "feat: add Event.arp and Instrument.arp_rate_sec to the contract"
```

---

### Task 2: `[arp] rate_ms` spreads onto instruments

**Files:**
- Modify: `src/bitty/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `ARP_RATE_SEC`, `Instrument.arp_rate_sec` from Task 1.
- Produces: a resolved `Config` whose every `Instrument` carries the
  `arp_rate_sec` the TOML asked for. `Config.arp.step_sec` remains the
  config surface and is unchanged.

Today `[arp] rate_ms` reaches the pipeline by `arrange` reading
`config.arp.step_sec`. The synth cannot see that, and from Task 4 the synth
is what needs the rate. So it travels the way `[vibrato]` already does.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`, after the mid-file import block (around lines
39-42) so `merge` and `pytest` are in scope:

```python
def test_the_arp_rate_reaches_every_instrument():
    """The synth reads the rate off the instrument, so the TOML must land there."""
    result = merge(DEFAULTS, "[arp]\nrate_ms = 20\n", "test")
    assert result.arp.step_sec == 0.02, "the config surface still resolves"
    for voice in result.voices.voices:
        assert voice.instrument.arp_rate_sec == 0.02


def test_a_file_silent_on_the_arp_rate_leaves_instruments_alone():
    """Spreading unconditionally would let an unrelated file undo a per-voice edit."""
    once = merge(DEFAULTS, "[arp]\nrate_ms = 20\n", "first")
    twice = merge(once, "[echo]\nlevel = 0.5\n", "second")
    for voice in twice.voices.voices:
        assert voice.instrument.arp_rate_sec == 0.02
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_config.py -v -k arp_rate
```

Expected: FAIL — `arp_rate_sec` is still the default 0.016.

- [ ] **Step 3: Generalise the spread**

`_spread` is vibrato-specific today. Make it take its mapping, then drive it
once per table. In `src/bitty/config.py`, replace `_spread` with:

```python
def _spread(roster, settings, named, mapping):
    """Push the keys this file named onto every instrument.

    Only the keys it named: spreading all of them every time would let a later
    file with an unrelated table silently undo an earlier [voices.lead]
    override.

    Every voice, including ones the count has dropped. A dropped voice that
    missed a spread would reappear un-spread if a later layer raised the count.
    """
    if not named:
        return roster
    changes = {mapping[field]: getattr(settings, field) for field in named}
    return replace(
        roster,
        voices=tuple(
            replace(voice, instrument=replace(voice.instrument, **changes))
            for voice in roster.voices
        ),
    )
```

Add the arp mapping beside `_VIBRATO_SPREAD`:

```python
# Which [arp] keys land on an instrument, and under what name there. The rate
# travels in the arrangement for the reason vibrato's shape does: a hand-edited
# file renders the same with no config anywhere.
_ARP_SPREAD = {"step_sec": "arp_rate_sec"}
```

Then in `merge`, replace the single vibrato spread with a loop over both:

```python
    # Order within one file: a global table sets every voice, then
    # [voices.<role>] overrides one. Across files the later file wins.
    roster = config.voices
    for table, mapping in (("vibrato", _VIBRATO_SPREAD), ("arp", _ARP_SPREAD)):
        named = [
            _TABLES[table][key][0]
            for key in raw.get(table, {})
            if _TABLES[table][key][0] in mapping
        ]
        roster = _spread(roster, getattr(config, table), named, mapping)
    if "voices" in raw:
        roster = _voices(roster, raw["voices"], source)
    return replace(config, voices=roster)
```

- [ ] **Step 4: Run the full suite**

```bash
.venv/bin/pytest
```

Expected: PASS, goldens unchanged — the default rate is the same value the
instrument already defaults to, so nothing moves.

- [ ] **Step 5: Prove the spread is conditional**

Make the loop spread unconditionally by replacing the `named` computation
with every key in the mapping:

```python
        named = list(mapping)
```

```bash
.venv/bin/pytest tests/test_config.py -v -k "spread or arp_rate or voices"
```

Expected: FAIL — the existing vibrato tests catch an unrelated file undoing
a per-voice override. Restore and re-run.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/config.py tests/test_config.py
git commit -m "feat: spread the arp rate onto instruments like vibrato's keys"
```

---

### Task 3: The synth cycles the offsets

**Files:**
- Modify: `src/bitty/synth.py`
- Test: `tests/test_synth.py`

**Interfaces:**
- Consumes: `Event.arp`, `Instrument.arp_rate_sec` from Task 1.
- Produces: `render()` honouring `event.arp` — one continuous note whose
  pitch steps through the offsets, envelopes running once.

The synth comes before the arranger deliberately: nothing emits `arp` yet, so
this task can be tested against hand-built arrangements and no intermediate
commit renders wrong audio.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_synth.py`. Add `Path`, `numpy as np`, and whichever of
`Arrangement`, `Channel`, `Event`, `Instrument`, `render`, `SAMPLE_RATE` the
file does not already import.

```python
def arp_arrangement(instrument, pitch=69, dur=1.0, arp=()):
    return Arrangement(
        meta={"title": "t", "bpm": 120.0},
        channels=(
            Channel(
                role="lead",
                instrument=instrument,
                events=(Event(t=0.0, pitch=pitch, dur=dur, vel=15, arp=arp),),
            ),
        ),
    )


def dominant_hz(audio, lo=0, hi=None):
    """The loudest frequency in a slice of the render."""
    mono = audio[lo:hi].mean(axis=1)
    windowed = mono * np.hanning(len(mono))
    spectrum = np.abs(np.fft.rfft(windowed))
    return float(np.fft.rfftfreq(len(mono), 1 / SAMPLE_RATE)[np.argmax(spectrum)])


def test_an_arpeggio_step_sounds_at_the_pitch_it_names():
    """The bug this phase exists to fix.

    Every step used to be its own 16 ms event, so it restarted the instrument's
    pitch envelope and froze at index 0. A step naming A4 sounded at 499.7 Hz —
    a whole tone sharp, `pitch_env`'s first value.
    """
    instrument = Instrument(
        wave="pulse", duty=0.5, pitch_env=(2, 1, 0), volume_env=(15, 15, 15, 15)
    )
    plain = dominant_hz(render(arp_arrangement(instrument)))
    arped = dominant_hz(render(arp_arrangement(instrument, arp=(0,))))
    assert abs(plain - 440.0) < 6.0, "a plain A4 is the baseline"
    assert abs(arped - plain) < 6.0, "a single-member arpeggio is just the note"


def test_envelopes_run_once_across_an_arpeggio():
    """Per-step events restarted the volume envelope 62 times a second."""
    instrument = Instrument(wave="pulse", duty=0.5, volume_env=(15, 0))
    audio = render(arp_arrangement(instrument, dur=0.5, arp=(0, 4, 7)))
    head = float(np.abs(audio[:400]).max())
    tail = float(np.abs(audio[-400:]).max())
    assert head > 0.05, "the attack should sound"
    assert tail < head * 0.2, "the envelope must decay across the event, not restart"

def test_the_pitch_envelope_settles_instead_of_repeating_every_step():
    """The measured defect, asserted directly.

    At the default 16 ms rate a per-step implementation never advances the
    1/60 s pitch envelope past index 0, so an A4 sounded at 499.7 Hz forever
    instead of resolving to 440. This is the test that would have caught it.
    """
    instrument = Instrument(wave="pulse", duty=0.5, pitch_env=(2, 1, 0))
    audio = render(arp_arrangement(instrument, dur=1.0, arp=(0,)))
    late = dominant_hz(audio, lo=int(0.4 * SAMPLE_RATE))
    assert abs(late - 440.0) < 10.0, f"the blip must resolve; got {late:.1f} Hz"
    assert abs(late - 493.9) > 30.0, "not stuck a whole tone sharp"


def test_the_arpeggio_cycles_rather_than_sustaining_its_last_offset():
    """`step_values` clamps to its last step; an arpeggio comes back around."""
    instrument = Instrument(wave="pulse", duty=0.5, arp_rate_sec=0.05)
    step = int(0.05 * SAMPLE_RATE)
    audio = render(arp_arrangement(instrument, dur=0.4, arp=(0, 12)))
    # Sample the middle half of steps 0, 1, 2, 3 to avoid the edge fades.
    pitches = [
        dominant_hz(audio, lo=i * step + step // 4, hi=i * step + 3 * step // 4)
        for i in range(4)
    ]
    assert abs(pitches[0] - 440.0) < 25.0
    assert abs(pitches[1] - 880.0) < 40.0
    assert abs(pitches[2] - 440.0) < 25.0, "step 2 must return to the first offset"
    assert abs(pitches[3] - 880.0) < 40.0


def test_the_arp_rate_comes_from_the_instrument():
    """A hand-edited file renders the same with no config anywhere."""
    slow = Instrument(wave="pulse", duty=0.5, arp_rate_sec=0.2)
    audio = render(arp_arrangement(slow, dur=0.4, arp=(0, 12)))
    early = dominant_hz(audio, lo=int(0.05 * SAMPLE_RATE), hi=int(0.15 * SAMPLE_RATE))
    late = dominant_hz(audio, lo=int(0.25 * SAMPLE_RATE), hi=int(0.35 * SAMPLE_RATE))
    assert abs(early - 440.0) < 25.0
    assert abs(late - 880.0) < 40.0, "a 0.2s rate holds each offset far longer"
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_synth.py -v -k "arp"
```

Expected: FAIL. `test_the_arpeggio_cycles_rather_than_sustaining_its_last_offset`
and `test_the_arp_rate_comes_from_the_instrument` fail because every window
reads 440 Hz — `arp` is ignored entirely.

**Which of these tests actually carry weight, stated honestly.** The cycling
test, the rate test, and `test_the_pitch_envelope_settles_instead_of_repeating_every_step`
each fail against a specific plausible wrong implementation, and Step 5 proves
two of them. `test_an_arpeggio_step_sounds_at_the_pitch_it_names` and
`test_envelopes_run_once_across_an_arpeggio` document properties that the
arranger's one-event test and the regenerated goldens are what really enforce
— a single-member arpeggio is nearly a plain note, so it cannot fail against
much. Keep them for what they record; do not mistake them for the guard.

- [ ] **Step 3: Fold the offsets into the pitch increment**

In `src/bitty/synth.py`, in `_add_event`, add this immediately after the
`pitch_env` block and before the vibrato block:

```python
    if event.arp:
        # Cycling, not clamping. `step_values` sustains its last step, which is
        # what an envelope does; an arpeggio comes back around. This is one note
        # whose pitch register is rewritten each step, which is how the hardware
        # does it — and why the envelopes above run once instead of restarting.
        per_step = max(1, int(round(instrument.arp_rate_sec * sample_rate)))
        offsets = np.asarray(event.arp, dtype=np.float64)
        semitones = offsets[(np.arange(length) // per_step) % len(offsets)]
        inc = inc * 2.0 ** (semitones / 12.0)
```

Composing multiplicatively, like `pitch_env` and vibrato, means a hand-edited
file that sets both still renders sensibly.

- [ ] **Step 4: Run the new tests, then the suite**

```bash
.venv/bin/pytest tests/test_synth.py -v -k "arp"
.venv/bin/pytest
```

Expected: PASS, and the goldens do not move — nothing emits `arp` yet.

- [ ] **Step 5: Prove the tests exclude the plausible wrong implementations**

Two breaks, each the mistake someone would actually make. Run the arp tests
after each, then restore.

Clamping instead of cycling — drop the `%`:

```python
        semitones = offsets[np.minimum(np.arange(length) // per_step, len(offsets) - 1)]
```

Expected: FAIL on `test_the_arpeggio_cycles_rather_than_sustaining_its_last_offset`
at step 2.

Reading the rate from the wrong place — hardcode the default:

```python
        per_step = max(1, int(round(0.016 * sample_rate)))
```

Expected: FAIL on `test_the_arp_rate_comes_from_the_instrument`.

Restore both and confirm green.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/synth.py tests/test_synth.py
git commit -m "feat: render Event.arp as one note whose pitch cycles"
```

---

### Task 4: The arranger emits one event per cycle

**Files:**
- Modify: `src/bitty/arrange.py`
- Test: `tests/test_arrange.py`, `tests/test_goldens.py`, `tests/test_config.py`
- Regenerate: `tests/goldens/*.arrangement.json`

**Interfaces:**
- Consumes: everything above.
- Produces: arrangements whose overflow is one event carrying `arp`.
  `arrange.ARP_STEP_SEC` no longer exists.

This is where the audio changes.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_arrange.py`:

```python
def test_overflow_becomes_one_cycling_event_not_a_burst_of_steps():
    """The whole point of the phase: one note whose pitch cycles."""
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0)),
        roster_of(3),
    )
    carried = channels(arrangement)["counter"].events
    assert len(carried) == 1, "one event, not sixty-two"
    event = carried[0]
    assert event.pitch == 64, "the cycle is anchored on its lowest member"
    assert event.arp == (0, 3, 5), "64, 67 and 69 as offsets from 64"
    assert event.dur > 0.9, "and it lasts as long as the chord, not 16ms"


def test_an_arpeggiated_event_does_not_also_waver():
    """A pitch already stepping through a chord does not want a slow LFO too."""
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0)),
        roster_of(3),
    )
    event = channels(arrangement)["counter"].events[0]
    assert event.arp and event.vibrato is False
    lead = channels(arrangement)["lead"].events[0]
    assert not lead.arp and lead.vibrato is True, "the rule still applies elsewhere"


def test_a_short_dense_chord_still_sounds_every_member():
    """The rule the old `max(len(pitches), ...)` protected, kept."""
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=0.01), note(69, 0.0, dur=0.01),
            note(67, 0.0, dur=0.01), note(64, 0.0, dur=0.01), note(48, 0.0, dur=0.01),
        ),
        roster_of(3),
    )
    event = channels(arrangement)["counter"].events[0]
    assert event.dur >= len(event.arp) * DEFAULTS.voices.voices[1].instrument.arp_rate_sec
```

`roster_of`, `score_of`, `note`, `channels`, and `DEFAULTS` already exist in
this file from Phase 6.

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_arrange.py -v -k "cycling or waver or dense_chord"
```

Expected: FAIL — `counter` still holds dozens of 16 ms events.

- [ ] **Step 3: Rewrite `_arpeggiate` and delete `_arp_cycle`**

In `src/bitty/arrange.py`, give `_Take` the field:

```python
@dataclass
class _Take:
    """A note as placed on one channel. Mutable: a later note truncates it."""

    t: float
    pitch: int
    dur: float
    vel: int
    arp: tuple[int, ...] = ()  # semitone offsets from `pitch`; () is a plain note
```

Replace `_arpeggiate` and delete `_arp_cycle` entirely:

```python
def _arpeggiate(
    leftovers: list[tuple[float, list[Note]]], takes: list[_Take], rate_sec: float
) -> list[_Take]:
    """Fold notes that found no channel into one cycling note.

    One take, not one per step. A chip arpeggio is a single note whose pitch
    register is rewritten each frame while its envelope keeps running; a fresh
    note per step restarts the envelopes 60 times a second, which is how every
    step came to sound a whole tone sharp on an instrument with a pitch
    envelope.

    The channel's own note at that moment joins the cycle rather than being
    replaced by it, so the arpeggio carries the whole chord and not just the
    part that would otherwise have been lost.
    """
    out = list(takes)

    for onset, notes in leftovers:
        # Partition rather than remove-by-value: `_Take` is a mutable dataclass
        # with structural equality, so `list.remove` would match any take that
        # merely looks the same.
        absorbed = [take for take in out if abs(take.t - onset) <= EPSILON]
        out = [take for take in out if abs(take.t - onset) > EPSILON]

        pitches = sorted({n.pitch for n in notes} | {take.pitch for take in absorbed})
        # The cycle lasts only as long as its shortest member: a note that has
        # ended must not keep sounding just because the arpeggio is still
        # running. But it owes every member one step — a short dense chord, an
        # ornament or a staccato stab, must still sound every note it was handed.
        span = min([n.dur for n in notes] + [take.dur for take in absorbed])
        span = max(span, len(pitches) * rate_sec)
        vel = max([_velocity(n) for n in notes] + [take.vel for take in absorbed])
        out.append(
            _Take(
                t=onset,
                pitch=pitches[0],
                dur=span,
                vel=vel,
                arp=tuple(pitch - pitches[0] for pitch in pitches),
            )
        )

    return _clip_overlaps(sorted(out, key=lambda take: take.t))
```

In `_events`, carry the offsets and suppress the waver:

```python
    return tuple(
        Event(
            t=take.t,
            pitch=take.pitch,
            dur=take.dur,
            vel=take.vel,
            # A pitch already stepping through a chord does not also want a slow
            # LFO; composed, the two read as mush rather than as either effect.
            vibrato=not take.arp and take.dur >= min_note_sec,
            arp=take.arp,
        )
        for take in takes
        if take.dur > EPSILON
    )
```

In `arrange`, take the rate from the carrier's own instrument so exactly one
value is in play, and delete the `ARP_STEP_SEC` alias near the top of the file:

```python
def arrange(score: Score, config: Config = DEFAULTS) -> Arrangement:
    roster = config.voices
    tracks, leftovers = _assign(score, roster)
    carrier = next(voice for voice in roster if voice.role == roster.arp)
    tracks[roster.arp] = _arpeggiate(
        leftovers, tracks[roster.arp], carrier.instrument.arp_rate_sec
    )
```

- [ ] **Step 4: Update the three tests that identified arpeggios by duration**

`ARP_STEP_SEC` existed only because "tests and goldens read this name". Those
readers change now.

In `tests/test_goldens.py`, drop `ARP_STEP_SEC` from the import and rewrite
the arpeggio clause of `test_every_source_note_is_heard`:

```python
        assert any(
            (e.pitch == note.pitch and abs(e.t - note.start) <= EPSILON)
            or (
                e.arp
                and note.pitch - e.pitch in e.arp
                and note.start - EPSILON <= e.t <= note.start + note.dur + EPSILON
            )
            for e in events
        ), f"{note} never sounds"
```

And rewrite the dense-writing test in the same file, which gets simpler:

```python
def test_dense_writing_arpeggiates_and_sparse_writing_does_not():
    ragtime = {c.role: c.events for c in arranged("ragtime").channels}
    chorale = {c.role: c.events for c in arranged("chorale").channels}
    assert [e for e in ragtime["inner_b"] if e.arp], (
        "six-note ragtime chords should overflow into an arpeggio"
    )
    assert not [e for e in chorale["inner_b"] if e.arp]
```

In `tests/test_config.py`, the cross-check at line 25 loses its constant.
Point it at the contract's default instead, which makes it a real assertion
rather than a tautology:

```python
    assert DEFAULTS.arp.step_sec == arrangement.ARP_RATE_SEC
```

`arrangement` is already imported at the top of that file. Also update the
docstring above it, which names `arrange.ARP_STEP_SEC` as a derived constant.

- [ ] **Step 5: Run everything except the goldens**

```bash
.venv/bin/pytest --ignore=tests/test_goldens.py
```

Expected: PASS. Fix anything else that referenced the old shape before
touching the goldens — a golden regenerated over a real bug is a bug frozen
into the repo.

- [ ] **Step 6: Regenerate the goldens and READ the diff**

```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
git diff --stat tests/goldens/
```

Then read it properly. What you must confirm:

- Event counts fall sharply on arpeggio carriers and are unchanged elsewhere.
  Ragtime's `inner_b` had 178 events; the minuet and chorale carriers had
  none at the default count.
- Every event that gained a non-empty `arp` sits at a chord onset.
- No event outside an overflow onset gained an `arp`.
- `t`, `vel`, and `pitch` of non-arpeggiated events are untouched.

```bash
.venv/bin/python - <<'EOF'
import json, pathlib
for name in ("minuet", "ragtime", "chorale"):
    d = json.loads(pathlib.Path(f"tests/goldens/{name}.arrangement.json").read_text())
    for c in d["channels"]:
        arped = [e for e in c["events"] if e["arp"]]
        print(f"{name:8} {c['role']:8} events={len(c['events']):4d} arpeggiated={len(arped):3d}")
EOF
```

If anything looks wrong, stop and report it rather than committing the diff.

- [ ] **Step 7: Run the full suite**

```bash
.venv/bin/pytest
```

Expected: PASS.

- [ ] **Step 8: Prove the new tests bite**

Restore the per-step behaviour by emitting the old cycle — the plausible
regression — by replacing the single `out.append(...)` with:

```python
        steps = max(len(pitches), int(span / rate_sec))
        out.extend(
            _Take(t=onset + i * rate_sec, pitch=pitches[i % len(pitches)],
                  dur=rate_sec, vel=vel)
            for i in range(steps)
        )
```

```bash
.venv/bin/pytest tests/test_arrange.py -v -k "cycling or waver"
```

Expected: FAIL on both. Restore and re-run.

- [ ] **Step 9: Commit**

```bash
git add src/bitty/arrange.py tests/ 
git commit -m "feat: emit one cycling event per overflow instead of 62 a second"
```

---

### Task 5: Documentation and the audition

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: documented fields, and audition material for a human to judge.

- [ ] **Step 1: Document the two fields**

In `README.md`, the Event fields table is around line 340 and the Instrument
fields table follows it. Add:

| Field | Meaning |
|---|---|
| `arp` | Semitone offsets from `pitch`, cycled at `arp_rate_sec`. Empty means a plain note. One event, not one per step — the envelopes run once across it, which is what keeps an arpeggiated pitch in tune. |

and to the Instrument table:

| `arp_rate_sec` | Seconds per arpeggio step. Travels here, not in config, so a hand-edited file renders the same anywhere. |

Match the surrounding table's voice: these entries explain why, not just what.

- [ ] **Step 2: Update the Status section**

Near `README.md:557`, record that Phase 7 fixed the arpeggio. Note that
`nes-tight` remains at `count = 4` and that the `count = 3` reduction policy
is still open, pending the audition below.

- [ ] **Step 3: Measure what changed**

```bash
.venv/bin/python - <<'EOF'
from pathlib import Path
from dataclasses import replace
from bitty.arrange import arrange
from bitty.config import DEFAULTS
from bitty.ingest import ingest
for name in ("minuet", "ragtime", "chorale"):
    score = ingest(Path(f"tests/fixtures/{name}.mxl"))
    for n in (5, 3):
        cfg = replace(DEFAULTS, voices=replace(DEFAULTS.voices, count=n))
        arr = arrange(score, cfg)
        ev = sum(len(c.events) for c in arr.channels)
        arped = sum(1 for c in arr.channels for e in c.events if e.arp)
        print(f"{name:8} count={n}  events={ev:5d}  arpeggiated={arped:3d}")
EOF
```

Report the table.

- [ ] **Step 4: Render the "after" audio**

The "before" renders were captured in Task 1 Step 1 at
`/tmp/bitty-phase7/before/`.

```bash
.venv/bin/bitty convert tests/fixtures/ragtime.mxl -o /tmp/bitty-phase7/after/ragtime --wav
.venv/bin/bitty convert tests/fixtures/minuet.mxl -o /tmp/bitty-phase7/after/minuet-count3 \
  --wav --config /tmp/bitty-phase7/count3.toml
ls -R /tmp/bitty-phase7
```

- [ ] **Step 5: Hand over the audition and STOP**

Give the user both pairs and ask them to compare:

```bash
aplay /tmp/bitty-phase7/before/ragtime/ragtime_loop.wav        # 178 sharp arp events
aplay /tmp/bitty-phase7/after/ragtime/ragtime_loop.wav         # the same, in tune
aplay /tmp/bitty-phase7/before/minuet-count3/minuet_loop.wav   # rejected in Phase 6
aplay /tmp/bitty-phase7/after/minuet-count3/minuet_loop.wav    # the question
```

Ask for two judgements, in this order:

1. **Ragtime at the default** — this is existing output that changed. Is the
   arpeggio now in tune, and is the change an improvement rather than merely
   a difference? This is the one most likely to surprise.
2. **The minuet at count 3** — is it acceptable now, or does it still sound
   wrong? A "still wrong" is a real result: it means the reduction policy
   needs its own phase, exactly as the spec predicted it might.

**Do not judge how they sound yourself, and do not claim the phase is
finished before this listening happens.**

- [ ] **Step 6: Commit the docs**

```bash
git add README.md
git commit -m "docs: document Event.arp and Instrument.arp_rate_sec"
```
