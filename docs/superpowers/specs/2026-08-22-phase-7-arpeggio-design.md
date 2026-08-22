# Phase 7: the arpeggio plays in tune

Phase 6's audition rejected `count = 3` as harsh. The investigation found
the harshness was not the amount of arpeggiation. It was the arpeggio
itself, and the defect predates Phase 6 and ships on `main` today.

## The bug

`_arpeggiate` emits one `Event` per cycle step, each `arp.step_sec` long —
16 ms by default. The envelope step is 1/60 s, about 16.7 ms. So every step
is a fresh note that restarts its instrument's envelopes and never advances
past index 0:

```
volume_env indices reached in one arp step: [13.0]   # attack peak, never decays
pitch_env  values reached in one arp step: [2.0]     # +2 semitones, never resolves
```

An arpeggio step therefore does not sound at the pitch it names. Measured
on `counter`, whose `pitch_env` is `(2, 1, 0)`:

```
sustained 1.0s note ->  440.0 Hz
single 0.016s step  ->  499.7 Hz
440 * 2^(2/12)      =  493.9 Hz   (a whole tone sharp)
```

Every arpeggiated note on any instrument with a `pitch_env` plays a whole
tone sharp, at constant attack volume, with the oscillator phase reset every
16 ms — 62 attack transients per second. That is not a busy texture. It is
out of tune and it clicks.

**This is audible in shipped output.** Ragtime carries 178 arpeggio-carrier
events at the *default* preset on `main`. Phase 6 did not create the bug; by
making the arpeggio the primary texture at `count = 3` (819 carrier events on
the minuet, 80.6% of the piece) it made a latent defect impossible to miss.

## The fix, in one sentence

A chip arpeggio is one note whose pitch register is rewritten each frame
while its envelope keeps running. Ours restarts the note 62 times a second.
Make it one note.

## Scope

**The mechanism only.** What the arranger chooses to arpeggiate does not
change: the same notes overflow, at the same onsets. Only their
representation and their sound change.

The reduction policy at `count = 3` — whether a sustained inner voice should
be arpeggiated at all, versus dropped, versus chosen by harmonic priority —
is deliberately deferred. Fixing the mechanism may make `count = 3`
acceptable on its own, and bundling a correctness fix with a taste decision
would leave a bad audition ambiguous about which half was wrong. Re-audition
first, decide after.

## Contract

Two new fields, both optional. `_event_from` and `_instrument_from` already
drop unknown keys, so older files load and newer files degrade rather than
fail.

```python
@dataclass(frozen=True)
class Event:
    ...
    arp: tuple[int, ...] = ()  # semitone offsets from `pitch`, cycling
```

`arp` is offsets rather than absolute pitches, matching how trackers write
arpeggio and keeping `pitch` the single anchor: transposing a passage by hand
is one edit, not one per member. `()` means no arpeggio, which is every event
the arranger emits today except the overflow ones.

`_event_from` must convert `arp` from a JSON list to a tuple, the way
`_instrument_from` already does for `volume_env` and `pitch_env`. `Event` is
frozen, and a list field breaks hashing and equality.

```python
ARP_RATE_SEC = 0.016  # beside VIBRATO_CENTS and friends

@dataclass(frozen=True)
class Instrument:
    ...
    arp_rate_sec: float = ARP_RATE_SEC
```

**The rate has to travel in the arrangement.** Today the synth never sees it
— the arranger bakes it into the event durations, one step per event. With a
single event the synth must know how fast to cycle, and this module's
docstring already commits to the reason: vibrato's shape lives here "so a
hand-edited file renders the same with no config anywhere." The arp rate is
the same kind of value and gets the same treatment.

`[arp] rate_ms` therefore spreads onto instruments the way `[vibrato]` keys
do, rather than being read at arrange time. `Config.arp` remains the config
surface — it is what the TOML key resolves into — but its value now reaches
the pipeline by being pushed onto each `Instrument` during `merge`, not by
`arrange` reading it directly. One value, one owner.

`arrange.ARP_STEP_SEC` exists today only because "tests and goldens read this
name". Those readers are rewritten by this phase, so the alias goes with them.

## Arranger

`_arpeggiate` stops building cycles. Per overflow onset it emits **one**
take:

- `t` — the onset, unchanged.
- `pitch` — the lowest member of the cycle.
- `arp` — the sorted semitone offsets of every member from that lowest
  pitch, starting at 0. The carrier's own absorbed note still joins, as
  today.
- `dur` — the span. Still `min` of the members' durations, for the reason
  the current comment gives: a note that has ended must not keep sounding
  because the cycle is still running. But extended to at least
  `len(offsets) * arp_rate_sec`, preserving the existing rule that a short
  dense chord still sounds every note it was handed.
- `vel` — the max of the members, as today.

The rate comes from the carrier voice's `instrument.arp_rate_sec`, so
exactly one value is in play.

`_Take` gains an `arp: tuple[int, ...] = ()` field to carry the offsets from
`_arpeggiate` through to `_events`, which is where takes become contract
events.

`_clip_overlaps` is unchanged and still applies. On the minuet, `counter`'s
819 events become roughly 26.

## Synth

`_add_event` folds `event.arp` into `inc` the same way `pitch_env` already
does, and composes with it rather than replacing it:

```python
if event.arp:
    steps = (np.arange(length) / (instrument.arp_rate_sec * sample_rate)).astype(int)
    offsets = np.asarray(event.arp)[steps % len(event.arp)]
    inc = inc * 2.0 ** (offsets / 12.0)
```

Cycling — `% len` — is what distinguishes it from `step_values`, which
clamps to the last step and sustains. Everything else follows: one
`_edge_fade` for the whole event rather than one per 16 ms, one phase ramp
with no resets, and envelopes that run once across the note.

## Vibrato is suppressed on arpeggiated events

An arp event is now long enough to trip `_events`' `dur >= min_note_sec`
vibrato flag. A pitch already stepping through a chord does not also want a
slow waver; composed, the two read as mush rather than as either effect. So
`_events` sets `vibrato=False` when `arp` is non-empty.

## The goldens move, and that is the point

Every phase so far has held `tests/goldens/*.arrangement.json` byte-identical
and treated any diff as a bug. This phase inverts that: the arrangement
changes shape — far fewer events, some now carrying `arp` — and the rendered
audio changes, because it was wrong.

The diff must be **reviewed, not accepted**. What replaces "byte-identical"
as the safety net:

- Event counts per channel, before and after, on all three fixtures.
- The pitch measurement below, which is the real guard.
- No event outside an overflow onset gains an `arp` field.

This is the one phase where `BITTY_UPDATE_GOLDENS=1` is the correct command
rather than a forbidden one. Every previous plan banned it; this plan requires
it, once, with the resulting diff read line by line before it is committed.

## Testing

- **An arp step sounds at the pitch it names.** The measurement that found
  this bug, inverted: render a one-note arpeggio on an instrument with a
  `pitch_env` and assert the dominant frequency is the named pitch, not a
  whole tone above it. This is the load-bearing test.
- **Envelopes advance across an arp event.** Assert the volume envelope
  reaches a later index than 0 — today it never does. Prove it by reverting
  to per-step events and watching the test fail.
- **Cycling, not clamping.** An arp of three offsets over a long event
  returns to offset 0; `step_values` would have stuck on the last.
- **Round-trip.** An `Event` with `arp` survives `to_json`/`from_json` as a
  tuple, and an arrangement written by a newer build still loads when `arp`
  is unknown.
- **Vibrato off on arp events**, on by the same rule elsewhere.

## Audition

Two listens, and the first is not about `count = 3`:

- **Ragtime at the default preset**, before and after. 178 carrier events
  change from out-of-tune buzz to in-tune shimmer. This is existing output
  that people already have, so it is the change most likely to surprise.
- **The minuet at `count = 3`**, against the Phase 6 render that was
  rejected. The question is whether the mechanism fix alone makes three
  voices acceptable.

WAV only — `aplay` renders Ogg as static.

## Deliberately out of scope

- **The reduction policy at `count = 3`.** See Scope.
- **Arpeggio as an expressive device.** It stays an overflow fallback; there
  is no way to ask for one deliberately. That is a feature request, not this
  bug.
- **The default rate.** 16 ms is the classic hardware rate and it was never
  the problem.

## Risks

- **First contract change.** The master spec sells hand-editability as the
  reason `arrangement.json` exists. An `arp` array is one more thing to
  understand — though far less than 62 identical events per second, so the
  file gets more readable, not less.
- **Changing audio people have.** Anyone who rendered ragtime has a version
  with the sharp arpeggio. There is no migration; the old output was wrong.
  Named so the audition is treated as a real gate.
- **The fix may not rescue `count = 3`.** 26 sustained inner voices become
  in-tune shimmer, which may still be the wrong texture for a chorale. That
  is what the second audition decides, and the reduction-policy phase is
  still available behind it.

## What a later phase inherits

- A correct arpeggio, so a reduction-policy phase can judge `count = 3` on
  its musical merits rather than through a broken effect.
- A per-event pitch sequence, which is the shape a deliberate arpeggio
  effect would want.
- `[transform]` and tail-wrapping, both still ahead.
