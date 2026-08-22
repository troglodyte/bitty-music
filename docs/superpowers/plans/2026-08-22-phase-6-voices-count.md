# Phase 6: voices.count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `[voices] count = 3..5`, so `nes-tight` can be an honest
three-voice NES reduction instead of a timbre-only preset.

**Architecture:** A frozen `Roster` type in `voices.py` holds all five
voices plus a count and derives `.lead`, `.bass`, `.middles`, and `.arp`
from that count. `arrange.py` asks the roster instead of importing four
module constants, so the arpeggio carrier cannot name a channel that is
not there. Truncation is a view, never a deletion: dropped voices stay
in `.voices` and only `.active` narrows.

**Tech Stack:** Python 3.14, stdlib `dataclasses` and `tomllib`, pytest.
Run everything with `.venv/bin/`.

**Spec:** `docs/superpowers/specs/2026-08-22-phase-6-voices-count-design.md`

## Global Constraints

- **`count` is an integer, 3 to 5, default 5.** The floor is 3 because
  `.middles` must never be empty — see the spec's "Why the floor is 3".
- **At the default, this phase must be inaudible.** Count 5 is today's
  behaviour exactly. `tests/goldens/*.arrangement.json` must come out
  byte-identical. A golden diff is a bug in the seam, not churn to
  accept — never run `BITTY_UPDATE_GOLDENS=1` in this phase.
- **The 3–5 bound lives in the config validator only.** `Roster` does
  not re-check it. Do not add a `__post_init__` guard; do not add a
  `.shrink()` method.
- **Every test is proven by breaking the implementation.** After a test
  passes, deliberately break the code it covers, re-run, confirm it
  fails, then restore. A test that still passes when `count` is ignored
  is testing the default, not the feature.
- **The reduction changes; the contract does not.** No new instrument
  field, no `Arrangement` schema change.

---

### Task 1: The `Roster` type

**Files:**
- Modify: `src/bitty/voices.py`
- Test: `tests/test_voices.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `VOICES: tuple[Voice, ...]` (the bare five), `MIN_VOICES: int
  = 3`, `Roster(voices=VOICES, count=5)` with `.active -> tuple[Voice,
  ...]`, `.lead -> str`, `.bass -> str`, `.middles -> tuple[str, ...]`,
  `.arp -> str`, iteration yielding active voices, and `ROSTER: Roster`
  as the default instance.

This task adds the type and renames the tuple. It deliberately leaves
`LEAD_ROLE`, `BASS_ROLE`, `MIDDLE_ROLES`, and `ARP_ROLE` in place so
`arrange.py` keeps working; Task 4 removes them.

- [ ] **Step 1: Write the failing tests**

Replace `test_the_role_constants_point_into_the_roster` at the bottom of
`tests/test_voices.py` with these, and update the import line at the top
to `from bitty.voices import MIN_VOICES, ROSTER, VOICES, Roster`:

```python
def test_the_default_roster_plays_all_five_voices():
    assert [v.role for v in ROSTER] == ["lead", "counter", "inner_a", "inner_b", "bass"]
    assert ROSTER.count == len(VOICES) == 5


def test_the_pins_survive_every_legal_count():
    """Lead and bass are structural, not preferences: without both there
    is no reduction, only a pile."""
    for count in range(MIN_VOICES, len(VOICES) + 1):
        roster = replace(ROSTER, count=count)
        roles = [v.role for v in roster]
        assert roles[0] == roster.lead == "lead"
        assert roles[-1] == roster.bass == "bass"
        assert len(roles) == count


def test_middles_fall_from_the_narrowest_end():
    assert replace(ROSTER, count=5).middles == ("counter", "inner_a", "inner_b")
    assert replace(ROSTER, count=4).middles == ("counter", "inner_a")
    assert replace(ROSTER, count=3).middles == ("counter",)


def test_the_arp_carrier_is_the_narrowest_surviving_middle():
    assert replace(ROSTER, count=5).arp == "inner_b"
    assert replace(ROSTER, count=4).arp == "inner_a"
    assert replace(ROSTER, count=3).arp == "counter"


def test_the_arp_carrier_is_always_a_voice_that_plays():
    """The invariant the floor of 3 exists to protect."""
    for count in range(MIN_VOICES, len(VOICES) + 1):
        roster = replace(ROSTER, count=count)
        assert roster.arp in {v.role for v in roster}
        assert roster.middles, "an empty middles has no one to carry the overflow"


def test_truncation_is_a_view_not_a_deletion():
    """Dropped voices stay addressable so any layer can override them."""
    roster = replace(ROSTER, count=3)
    assert [v.role for v in roster.voices] == [v.role for v in VOICES]
    assert "inner_b" not in {v.role for v in roster}
```

Add `from dataclasses import replace` to the top of the file.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/test_voices.py -v
```

Expected: FAIL at import — `cannot import name 'MIN_VOICES' from 'bitty.voices'`.

- [ ] **Step 3: Implement `Roster`**

In `src/bitty/voices.py`, rename the tuple and add the type. Replace the
line `ROSTER = (LEAD, COUNTER, INNER_A, INNER_B, BASS)` with:

```python
VOICES = (LEAD, COUNTER, INNER_A, INNER_B, BASS)

MIN_VOICES = 3  # below this there is no middle voice to carry the arpeggio


@dataclass(frozen=True)
class Roster:
    """Who plays, and how many of them.

    Truncation is a view rather than a deletion: `voices` always holds the
    full five and only `active` narrows. That is what lets a config file
    override `inner_b` whether or not some other layer set `count = 3` —
    the voice is still there to override, it just does not play.

    The 3-5 bound is the config validator's job, not this type's. Every
    other range in the pipeline is checked there, and one place beats two.
    """

    voices: tuple[Voice, ...] = VOICES
    count: int = len(VOICES)

    def __iter__(self):
        return iter(self.active)

    def __len__(self):
        return len(self.active)

    @property
    def active(self) -> tuple[Voice, ...]:
        return (self.voices[0], *self._middles, self.voices[-1])

    @property
    def lead(self) -> str:
        return self.voices[0].role

    @property
    def bass(self) -> str:
        return self.voices[-1].role

    @property
    def middles(self) -> tuple[str, ...]:
        return tuple(voice.role for voice in self._middles)

    @property
    def arp(self) -> str:
        """The narrowest surviving middle carries the overflow."""
        return self.middles[-1]

    @property
    def _middles(self) -> tuple[Voice, ...]:
        # Middles fall from the narrowest end: inner_b (duty 0.125) goes
        # before inner_a (0.25), so the widest, most present middle voice
        # survives longest. Width is the rule; that it coincides with
        # reverse declaration order is what makes the slice cheap.
        return self.voices[1:-1][: self.count - 2]


ROSTER = Roster()
```

Leave `LEAD_ROLE`, `BASS_ROLE`, `MIDDLE_ROLES`, and `ARP_ROLE` exactly as
they are — `arrange.py` still imports them until Task 4.

- [ ] **Step 4: Run the full suite**

```bash
.venv/bin/pytest
```

Expected: PASS. `ROSTER` is now a `Roster`, but it iterates as its five
active voices, so every existing `for v in ROSTER` reads the same.

- [ ] **Step 5: Prove the tests exclude the coarser implementation**

Break `_middles` to ignore the count:

```python
        return self.voices[1:-1]
```

```bash
.venv/bin/pytest tests/test_voices.py -v
```

Expected: FAIL on `test_middles_fall_from_the_narrowest_end`,
`test_the_arp_carrier_is_the_narrowest_surviving_middle`, and
`test_the_pins_survive_every_legal_count`. Restore the slice and re-run
to confirm green.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/voices.py tests/test_voices.py
git commit -m "feat: add a Roster type that derives roles from a count"
```

---

### Task 2: Config carries the roster through the cascade

**Files:**
- Modify: `src/bitty/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Roster`, `VOICES`, `ROSTER` from Task 1.
- Produces: `Config.voices: Roster` — a `Roster` at every point in the
  cascade, not just at the default.

`_spread` and `_voices` currently return bare tuples, so the first merged
file would turn `Config.voices` back into a tuple and Task 4's
`roster.arp` would fail. This task makes them roster-preserving.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_the_roster_survives_a_merge_as_a_roster():
    """A merged config still answers .arp, or the arranger loses its carrier."""
    result = merge(DEFAULTS, '[voices.lead]\nduty = 0.25\n', "test")
    assert isinstance(result.voices, voices.Roster)
    assert result.voices.arp == "inner_b"


def test_a_vibrato_spread_reaches_voices_that_are_not_playing():
    """A dropped voice must still be spread: if a later layer raises the
    count it would otherwise come back without the vibrato."""
    result = merge(
        replace(DEFAULTS, voices=replace(DEFAULTS.voices, count=3)),
        "[vibrato]\ndepth_cents = 40.0\n",
        "test",
    )
    by_role = {v.role: v for v in result.voices.voices}
    assert by_role["inner_b"].instrument.vibrato_cents == 40.0
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_config.py -v -k "roster_survives or not_playing"
```

Expected: FAIL — `result.voices` is a `tuple`, not a `Roster`.

- [ ] **Step 3: Make `_spread` and `_voices` roster-preserving**

Both must iterate `roster.voices` — the full five — and not the roster
itself, which yields only actives.

In `src/bitty/config.py`, change `_spread`:

```python
def _spread(roster, vibrato, named):
    """Push the [vibrato] keys this file named onto every instrument.

    Only the keys it named: spreading all three every time would let a later
    file with an unrelated [vibrato] table silently undo an earlier
    [voices.lead] override.

    Every voice, including ones the count has dropped. A dropped voice that
    missed a spread would reappear un-spread if a later layer raised the
    count.
    """
    if not named:
        return roster
    changes = {_VIBRATO_SPREAD[field]: getattr(vibrato, field) for field in named}
    return replace(
        roster,
        voices=tuple(
            replace(voice, instrument=replace(voice.instrument, **changes))
            for voice in roster.voices
        ),
    )
```

And the head and tail of `_voices`:

```python
def _voices(roster, raw, source):
    by_role = {voice.role: voice for voice in roster.voices}
```

```python
    return replace(roster, voices=tuple(by_role[voice.role] for voice in roster.voices))
```

Update the `Config` annotation:

```python
    voices: Roster = ROSTER
```

and the import at the top of the file:

```python
from bitty.voices import ECHO_BEATS, ECHO_LEVEL, ROSTER, Roster
```

Drop `Voice` from that import if nothing else in the file uses it — check
with `rg -n 'Voice' src/bitty/config.py` first.

- [ ] **Step 4: Run the full suite**

```bash
.venv/bin/pytest
```

Expected: PASS, goldens included.

- [ ] **Step 5: Prove the spread test bites**

Change `_spread` to iterate `roster` instead of `roster.voices`:

```python
            for voice in roster
```

```bash
.venv/bin/pytest tests/test_config.py -v -k not_playing
```

Expected: FAIL — `inner_b` was not reached. Restore and re-run.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/config.py tests/test_config.py
git commit -m "refactor: keep Config.voices a Roster through the cascade"
```

---

### Task 3: The `[voices] count` key

**Files:**
- Modify: `src/bitty/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Roster`, `MIN_VOICES`, `VOICES` from Task 1; roster-preserving
  `_voices` from Task 2.
- Produces: `[voices] count = N` parsed, validated to `MIN_VOICES..len(VOICES)`,
  merging last-writer-wins.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_count_narrows_the_roster():
    result = merge(DEFAULTS, "[voices]\ncount = 3\n", "test")
    assert [v.role for v in result.voices] == ["lead", "counter", "bass"]
    assert result.voices.arp == "counter"


def test_count_is_bounded_at_both_ends():
    for bad in (2, 6, 0, -1):
        with pytest.raises(ConfigError) as caught:
            merge(DEFAULTS, f"[voices]\ncount = {bad}\n", "test")
        assert "voices.count" in str(caught.value)


def test_count_rejects_a_non_integer():
    for bad in ("3.5", "true", '"three"'):
        with pytest.raises(ConfigError) as caught:
            merge(DEFAULTS, f"[voices]\ncount = {bad}\n", "test")
        assert "voices.count" in str(caught.value)


def test_the_last_file_to_name_count_wins():
    once = merge(DEFAULTS, "[voices]\ncount = 3\n", "first")
    twice = merge(once, "[voices]\ncount = 4\n", "second")
    assert twice.voices.count == 4
    assert twice.voices.arp == "inner_a"


def test_a_file_that_is_silent_on_count_leaves_it_alone():
    once = merge(DEFAULTS, "[voices]\ncount = 3\n", "first")
    twice = merge(once, "[voices.lead]\npan = 0.0\n", "second")
    assert twice.voices.count == 3


def test_overriding_a_dropped_voice_is_accepted_and_moot():
    """Independent layers must not combine into an error. A project file
    tweaking inner_b does not break the day someone adds --preset nes-tight."""
    result = merge(DEFAULTS, "[voices]\ncount = 3\n[voices.inner_b]\nduty = 0.5\n", "test")
    assert [v.role for v in result.voices] == ["lead", "counter", "bass"]
    by_role = {v.role: v for v in result.voices.voices}
    assert by_role["inner_b"].instrument.duty == 0.5


def test_an_unknown_voice_still_errors_next_to_count():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[voices]\ncount = 3\n[voices.tuba]\nduty = 0.5\n", "test")
    assert "tuba" in str(caught.value)
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_config.py -v -k count
```

Expected: FAIL — `count` is read as a role name, so the error is
"unknown voice; the roster is lead, counter, ...".

- [ ] **Step 3: Handle `count` in `_voices`**

`count` is the one scalar key in `[voices]`; every other key is a role
table. Read it off before iterating roles. In `src/bitty/config.py`:

```python
def _voices(roster, raw, source):
    if not isinstance(raw, dict):
        raise ConfigError(source, "voices", "expected tables like [voices.lead]")

    bodies = dict(raw)
    count = bodies.pop("count", None)
    if count is not None:
        count = _whole(low=MIN_VOICES, high=len(VOICES))(count, source, "voices.count")

    by_role = {voice.role: voice for voice in roster.voices}

    for role, body in bodies.items():
        ...  # unchanged
```

and the return:

```python
    narrowed = {"count": count} if count is not None else {}
    return replace(
        roster,
        voices=tuple(by_role[voice.role] for voice in roster.voices),
        **narrowed,
    )
```

Extend the import:

```python
from bitty.voices import ECHO_BEATS, ECHO_LEVEL, MIN_VOICES, ROSTER, VOICES, Roster
```

- [ ] **Step 4: Run the full suite**

```bash
.venv/bin/pytest
```

Expected: PASS. Goldens unchanged — nothing sets `count` yet.

- [ ] **Step 5: Prove the bound is real**

Widen the validator to `_whole(low=1)`:

```bash
.venv/bin/pytest tests/test_config.py -v -k bounded
```

Expected: FAIL on `count = 2` and `count = 0`. Restore and re-run.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/config.py tests/test_config.py
git commit -m "feat: parse and validate [voices] count"
```

---

### Task 4: The arranger reads the roster

**Files:**
- Modify: `src/bitty/arrange.py`, `src/bitty/voices.py`
- Test: `tests/test_arrange.py`

**Interfaces:**
- Consumes: `Roster` and a `count`-aware `Config.voices` from Tasks 1–3.
- Produces: `arrange(score, config)` honouring `config.voices.count`.
  `LEAD_ROLE`, `BASS_ROLE`, `MIDDLE_ROLES`, and `ARP_ROLE` no longer exist.

This is the task where `count` becomes audible.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_arrange.py`:

```python
def roster_of(count):
    return replace(DEFAULTS, voices=replace(DEFAULTS.voices, count=count))


def test_three_voices_play_only_lead_counter_and_bass():
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0)),
        roster_of(3),
    )
    assert set(channels(arrangement)) == {"lead", "counter", "bass"}
    assert pitches(arrangement, "lead") == [72]
    assert pitches(arrangement, "bass") == [48]


def test_the_notes_a_dropped_voice_would_have_taken_reach_the_arpeggio():
    """The test that excludes the coarse implementation.

    Simply deleting channels after arranging also yields three channels —
    and silently loses 69, 67, and 64. The overflow has to arrive on the
    carrier, which at count 3 is the counter.
    """
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0)),
        roster_of(3),
    )
    carried = pitches(arrangement, "counter")
    assert set(carried) == {69, 67, 64}
    assert len(carried) > 3, "a cycle, not one note that happened to fit"


def test_four_voices_drop_only_inner_b_and_carry_on_inner_a():
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0)),
        roster_of(4),
    )
    assert set(channels(arrangement)) == {"lead", "counter", "inner_a", "bass"}
    assert 64 in pitches(arrangement, "inner_a")


def test_the_echo_follows_the_lead_at_every_count():
    for count in (3, 4, 5):
        arrangement = arrange(score_of(note(72, 0.0), note(48, 0.0)), roster_of(count))
        with_echo = [c.role for c in arrangement.channels if c.echo is not None]
        assert with_echo == ["lead"]
```

`replace` and `DEFAULTS` are already imported at the top of the file.

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/test_arrange.py -v -k "three_voices or dropped_voice or four_voices"
```

Expected: FAIL — five channels, because `_assign` still builds tracks from
`MIDDLE_ROLES`.

- [ ] **Step 3: Switch the arranger onto the roster**

In `src/bitty/arrange.py`, replace the `bitty.voices` import with:

```python
from bitty.voices import Roster
```

In `arrange`, take the roster once and ask it for its roles:

```python
def arrange(score: Score, config: Config = DEFAULTS) -> Arrangement:
    roster = config.voices
    tracks, leftovers = _assign(score, roster)
    tracks[roster.arp] = _arpeggiate(leftovers, tracks[roster.arp], config.arp.step_sec)

    channels: list[Channel] = []
    for voice in roster:
        events = _events(tracks[voice.role], config.vibrato.min_note_sec)
        if not events:
            continue  # a two-voice score should not carry three silent channels
        channels.append(
            Channel(
                role=voice.role,
                instrument=voice.instrument,
                events=events,
                pan=voice.pan,
                echo=_echo(score.bpm, config.echo) if voice.role == roster.lead else None,
            )
        )
```

In `_assign`, change the signature and the four constant uses:

```python
def _assign(score: Score, roster: Roster) -> tuple[Tracks, list[tuple[float, list[Note]]]]:
    tracks: Tracks = {voice.role: [] for voice in roster}
    leftovers: list[tuple[float, list[Note]]] = []

    for onset, group in _by_onset(score.notes):
        used: set[str] = set()
        pending = list(group)
        above = _texture(tracks, onset, without=roster.lead)
        if not above or pending[0].pitch >= max(above):
            _place(tracks[roster.lead], pending.pop(0))
            used.add(roster.lead)

        below = _texture(tracks, onset, without=roster.bass)
        if pending and (not below or pending[-1].pitch <= min(below)):
            _place(tracks[roster.bass], pending.pop())
            used.add(roster.bass)

        spare: list[Note] = []
        for note in pending:
            role = _pick_middle(tracks, onset, note, used, roster.middles)
```

and `_pick_middle` takes the middles rather than importing them:

```python
def _pick_middle(
    tracks: Tracks, onset: float, note: Note, used: set[str], middles: tuple[str, ...]
) -> str | None:
    """Nearest last pitch, but only among channels that are not mid-note.

    Stealing is the fallback rather than the rule. A held inner voice cut short
    leaves a hole in the harmony, which the ear reads as the texture breaking;
    a note landing on a further-away channel is only a change of colour.
    """
    options = [role for role in middles if role not in used]
```

Then delete the four now-unused constants from the bottom of
`src/bitty/voices.py`:

```python
LEAD_ROLE = LEAD.role
BASS_ROLE = BASS.role
MIDDLE_ROLES = (COUNTER.role, INNER_A.role, INNER_B.role)
ARP_ROLE = INNER_B.role  # the narrowest pulse carries the overflow
```

Confirm nothing still imports them:

```bash
rg -n 'LEAD_ROLE|BASS_ROLE|MIDDLE_ROLES|ARP_ROLE' src tests
```

Expected: no matches.

- [ ] **Step 4: Run the full suite**

```bash
.venv/bin/pytest
```

Expected: PASS — **including `tests/test_goldens.py` with no diff.** If a
golden changed, stop: count 5 must reproduce today's behaviour exactly.
Read the diff and fix the seam rather than updating the golden.

- [ ] **Step 5: Prove the tests exclude the coarse implementation**

Make `arrange` ignore the count by iterating all five and filtering at the
end — the plausible wrong version:

```python
    tracks, leftovers = _assign(score, replace(roster, count=5))
```

```bash
.venv/bin/pytest tests/test_arrange.py -v -k "three_voices or dropped_voice"
```

Expected: FAIL on both — five channels, and the overflow never reaches the
counter. Restore and re-run.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/arrange.py src/bitty/voices.py tests/test_arrange.py
git commit -m "feat: arrange against the roster's count, not fixed role constants"
```

---

### Task 5: `nes-tight` becomes an honest three voices

**Files:**
- Modify: `src/bitty/presets/nes-tight.toml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: `--preset nes-tight` resolving to a three-voice roster.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`, beside the existing `nes-tight` tests:

```python
def test_nes_tight_is_two_pulses_and_a_triangle():
    """The real NES melodic roster. Its other channels are noise and DPCM,
    which this roster has no voice for."""
    result = load([], preset="nes-tight")
    assert [v.role for v in result.voices] == ["lead", "counter", "bass"]
    waves = [v.instrument.wave for v in result.voices]
    assert waves == ["pulse", "pulse", "triangle"]


def test_nes_tight_carries_its_overflow_on_the_narrow_pulse():
    result = load([], preset="nes-tight")
    by_role = {v.role: v for v in result.voices}
    assert result.voices.arp == "counter"
    assert by_role["counter"].instrument.duty == 0.125
```

Check `load`'s signature before writing the call — it is
`load(paths, preset=None)` at `src/bitty/config.py:371`.

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/test_config.py -v -k nes_tight
```

Expected: FAIL — five roles, because the preset has no `count`.

- [ ] **Step 3: Update the preset**

Rewrite the header comment and add the count at the top of
`src/bitty/presets/nes-tight.toml`:

```toml
# Close to the hardware: three channels, no echo, a mono image, shallow late
# vibrato, and envelopes that decay rather than sit. Two pulses and a triangle
# is the NES melodic roster; its remaining channels are noise and DPCM, which
# this roster has no voice for.

[voices]
count = 3

[echo]
on = false
```

Then delete the `[voices.inner_a]` and `[voices.inner_b]` blocks — at
count 3 they can never apply, and a shipped preset should not carry
settings that do nothing. Leave `[voices.lead]`, `[voices.counter]`, and
`[voices.bass]` exactly as they are.

- [ ] **Step 4: Run the full suite**

```bash
.venv/bin/pytest
```

Expected: PASS. Goldens still unchanged — they render at the default, not
under a preset.

- [ ] **Step 5: Commit**

```bash
git add src/bitty/presets/nes-tight.toml tests/test_config.py
git commit -m "feat: nes-tight drops to three voices, as its name claimed"
```

---

### Task 6: A short roster still mixes to the same loudness

**Files:**
- Test: `tests/test_synth.py`

**Interfaces:**
- Consumes: everything above.
- Produces: confidence that dropping voices does not change the mix level.

**Read this before writing the test.** The targets stage never sees a
channel — `Emitter` takes a `Render` (mixed stereo audio, sample rate,
meta, loop points), so no emitter can care how many voices played. There
is nothing to test there.

The stage that does see channels is the mix, at `src/bitty/synth.py:88`:

```python
gain = MIX_HEADROOM / math.sqrt(len(arrangement.channels))
```

That already compensates for voice count by design — the comment says
sqrt(n) "keeps a five-voice mix as loud as a two-voice one". So this task
confirms an existing property holds under the new key rather than adding
behaviour. If it passes first time, that is the expected result.

- [ ] **Step 1: Write the test**

Add to `tests/test_synth.py`, reusing that file's existing imports:

```python
def test_a_three_voice_mix_is_not_quieter_than_a_five_voice_one():
    """Dropping voices must change the texture, not the level.

    The sqrt(n) gain at synth.py:88 exists for exactly this. If someone
    later replaces it with a fixed divisor, count = 3 goes quiet and this
    is the test that says so.
    """
    score = ingest(Path(__file__).parent / "fixtures" / "minuet.mxl")
    levels = {}
    for count in (3, 5):
        config = replace(DEFAULTS, voices=replace(DEFAULTS.voices, count=count))
        audio = render(arrange(score, config))
        levels[count] = float(np.sqrt(np.mean(audio**2)))

    assert levels[3] > 0.0 and levels[5] > 0.0
    ratio = levels[3] / levels[5]
    assert 0.5 < ratio < 2.0, f"three voices mixed at {ratio:.2f}x five voices"
```

Add whichever of `replace`, `np`, `ingest`, `arrange`, `render`, `DEFAULTS`,
and `Path` that file does not already import.

- [ ] **Step 2: Run it**

```bash
.venv/bin/pytest tests/test_synth.py -v -k three_voice_mix
```

Expected: PASS.

- [ ] **Step 3: Prove the test bites**

Replace the gain line in `src/bitty/synth.py` with a fixed divisor:

```python
    gain = MIX_HEADROOM / 5.0
```

```bash
.venv/bin/pytest tests/test_synth.py -v -k three_voice_mix
```

Expected: FAIL — the three-voice mix comes out noticeably quieter.
Restore the sqrt and re-run.

- [ ] **Step 4: Commit**

```bash
git add tests/test_synth.py
git commit -m "test: a three-voice mix holds its level against a five-voice one"
```

---

### Task 7: Documentation and the audition

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a documented key and a listened-to result.

- [ ] **Step 1: Document the key**

In `README.md`, add `count` to the config reference beside the other
`[voices]` material — an integer 3 to 5, default 5, narrowing the roster
from the narrowest middle voice, with the three-row table from the spec.
Find the right section first:

```bash
rg -n 'voices|preset' README.md | head -20
```

- [ ] **Step 2: Update the Status section**

At `README.md:531-542`, move `voices.count` out of "deliberately still
ahead" and into what is done. What remains ahead: `[transform]` and
tail-wrapping.

- [ ] **Step 3: Measure the arrangements before listening**

Numbers first, so the impression has something beside it.
`tests/test_quality.py:_measured` computes lead purity, bass purity, and
leap count, but it calls `arrange(score)` with no config, so it always
measures the default. Copy its body into a scratch script that takes a
config. Write it to the scratchpad, not the repo:

```python
# measure.py - throwaway
import statistics
from dataclasses import replace
from pathlib import Path

from bitty.arrange import arrange
from bitty.config import DEFAULTS, load
from bitty.ingest import ingest

OCTAVE, EPSILON = 12, 1e-6
score = ingest(Path("tests/fixtures/minuet.mxl"))

parts: dict[int, list[int]] = {}
for n in score.notes:
    parts.setdefault(n.part, []).append(n.pitch)
top = max(parts, key=lambda p: statistics.mean(parts[p]))
bottom = min(parts, key=lambda p: statistics.mean(parts[p]))

def measure(config):
    events = {c.role: c.events for c in arrange(score, config).channels}

    def purity(role, part):
        matched = hits = 0
        for event in events.get(role, ()):
            sources = [
                n for n in score.notes
                if n.pitch == event.pitch and abs(n.start - event.t) <= EPSILON
            ]
            if not sources:
                continue  # an arpeggio step belongs to no single part
            matched += 1
            hits += any(n.part == part for n in sources)
        return 100.0 * hits / matched if matched else 0.0

    lead = events.get("lead", ())
    leaps = sum(1 for a, b in zip(lead, lead[1:]) if abs(a.pitch - b.pitch) >= OCTAVE)
    return purity("lead", top), purity("bass", bottom), leaps, len(events)

for label, config in [
    ("default", DEFAULTS),
    ("count=4", replace(DEFAULTS, voices=replace(DEFAULTS.voices, count=4))),
    ("nes-tight", load([], preset="nes-tight")),
]:
    lead, bass, leaps, channels = measure(config)
    print(f"{label:>10}  lead {lead:5.1f}%  bass {bass:5.1f}%  leaps {leaps:2d}  channels {channels}")
```

Run it and report the table. Expect lead and bass purity to hold roughly
steady - the pins do not move - and the channel count to drop. A large
purity fall at count 3 is a finding worth reporting, not a rounding
detail.

- [ ] **Step 4: Render the audition**

WAV only — `aplay` renders Ogg as static, so this is the only format that
works, not a preference.

```bash
AUD="${TMPDIR:-/tmp}/bitty-phase6"
.venv/bin/bitty convert tests/fixtures/minuet.mxl -o "$AUD/default" --wav
.venv/bin/bitty convert tests/fixtures/minuet.mxl -o "$AUD/nes-tight" --wav --preset nes-tight
printf '[voices]\ncount = 4\n' > "$AUD/four.toml"
.venv/bin/bitty convert tests/fixtures/minuet.mxl -o "$AUD/four" --wav --config "$AUD/four.toml"
ls -R "$AUD"
```

- [ ] **Step 5: Hand the audition over and stop**

Give the user the three WAV paths and ask them to listen for:

- whether the tune survives at three voices, or the reduction thins out
- whether the arpeggio on `counter` is too busy — it now carries what two
  dropped voices used to hold, on a voice with a pitch-envelope attack blip
- whether the harmony still reads at count 3
- whether the image sounds lopsided at `count = 4`, which keeps the
  default pans; `nes-tight` centres everything, so only the bare count
  exposes this

**Do not commit the phase as finished before this listening happens.** If
three voices sound too busy, the recorded fallback is `nes-tight` at
`count = 4`; that is a one-line preset change, not a redesign.

- [ ] **Step 6: Commit the docs**

```bash
git add README.md
git commit -m "docs: document [voices] count and mark Phase 6 done"
```
