# Phase 10: percussion

The parent spec listed "drum grooves and tempo manipulation for a gamified
mode" under future work. Phase 9 took the tempo half. This phase takes the
drums.

Classical scores have no percussion, so unlike every phase before it this one
does not reduce something the score contains — it generates something the
score implies. That is the whole risk, and it is why the feature ships off by
default.

Phases 1 through 9 are done and auditioned, with nothing outstanding. The
material is already here: `osc.py` has a working 15-bit LFSR noise oscillator
that no voice currently uses, and `analyze.py` produces a bar timeline whose
bars each carry their own time signature.

## The decision that shapes everything else

A groove can come from the meter or from the music:

- **From the meter.** A pattern per time signature, placed on the bar timeline
  the score's own barlines define. Every hit can be justified by pointing at a
  barline, which is the same standard `analyze` holds itself to.
- **From the music.** Hits derived from onset density, `beat_strength`, or
  where the reduction dropped notes — percussion that articulates what the
  piece is actually doing.

**This phase takes the meter.** The second is more musical in principle and
unexplainable in practice: on a chorale it produces hits nobody can account
for, and "why is there a drum there" has no answer that points at the score.
The meter grid is also what "gamified mode" means to the ear it is aimed at.

The cost is stated plainly: a meter grid does not know what the music is
doing, so it can sit on top of a piece rather than in it. Whether that is
acceptable is the audition's central question, and the honest possible verdict
is "only on ragtime".

## Where it lives

A new module, `src/bitty/percussion.py`, with one pure function from bars to
events:

```python
def groove(bars: tuple[Bar, ...], bpm: float, settings: Percussion) -> tuple[Event, ...]
```

`arrange()` appends one more `Channel` when `settings.enabled`. Three
placements were considered:

- **Inside `arrange`, outside `Roster`** — the choice. `arrange` already takes
  `(score, config)` and decides which chip channel plays what, which is
  exactly what this is.
- **As a sixth `Voice` in the roster.** It would inherit the `[voices.<role>]`
  override machinery free. But `Roster.active` is `(first, *middles, last)`
  and `.arp` is "the narrowest surviving middle" — every property on that type
  assumes pitched voice-leading, and `count` would have to mean something
  different depending on whether drums are on. That is a load-bearing type;
  ten lines of plumbing is the cheaper side of the trade.
- **A separate stage, like `transform`.** `transform` earns its own stage
  because it changes *the music* before any chiptune decision. Percussion *is*
  a chiptune decision. The stage would also need `score.bars`, which the
  arrangement does not carry — only bar numbers in `meta` — so it would take
  the same two inputs `arrange` already has and gain nothing.

`PERC` is declared in `voices.py` as a `Voice`, so the timbre table stays in
one place, but it is deliberately **not** in the `VOICES` tuple. `Roster` is
untouched by this phase.

## The pattern table

`PATTERNS` maps a time signature to a tuple of hits:

```python
@dataclass(frozen=True)
class Hit:
    quarters: float  # from the barline
    drum: str        # "kick", "snare", or "hat"
    vel: int         # 0-15, before `level` scales it
```

Positions are in **quarter notes**, not beats. `bpm` is quarter-note based
everywhere in this codebase (`analyze._key_of` divides by `60.0 / score.bpm`),
so quarters convert to seconds with no per-meter reasoning, and a 6/8 bar is
three quarters rather than six ambiguous "beats".

Four meters, which cover all three fixtures:

| Meter | Kick | Snare | Hat |
|---|---|---|---|
| 4/4 (chorale) | 0, 2 | 1, 3 | every 0.5 |
| 2/4 (ragtime) | 0 | 1 | every 0.5 |
| 3/4 (minuet) | 0 | — | 1, 2 |
| 6/8 | 0 | 1.5 | every 0.5 |

3/4 has no backbeat on purpose. A waltz that gets one stops being a waltz, and
that exception is the reason this is a table of musical decisions rather than
a formula: a generic rule would have to special-case it anyway, at which point
it is a table wearing a rule's clothes.

**Anything else refuses**, naming the bar number and the signature, in the
same shape as Phase 9's transpose refusal. Percussion is opt-in, so a refusal
only ever reaches someone who asked for drums; silently playing 5/4 as though
it were something else is the outcome this project consistently rejects.

Each bar is looked up by *its own* signature, so a piece that changes meter
mid-way is handled by construction rather than by a special case.

## Generation

`groove` walks the bars, and for each one converts its pattern's hits to
absolute seconds at `bar.start + quarters * 60.0 / bpm`.

**Hits past the bar's own duration are dropped.** This is what makes pickup
bars and short final bars correct for free: a 1-quarter pickup in 4/4 keeps
the downbeat kick and discards the rest, rather than spilling three hits into
a bar that does not exist.

Candidates are then resolved into a monophonic channel by one greedy pass:

1. Sort by priority — kick, then snare, then hat — and by time within each.
2. Accept a hit only if no already-accepted hit falls within `MIN_HIT_SEC`.
3. `dur` is `min(HIT_SEC, gap to the next accepted hit)`, so events never
   overlap on a channel the synth sums into one buffer.

Priority resolves collisions in the musical direction: a hat landing on beat 1
is dropped rather than truncating the kick. This is deliberately *not* the
mutable-truncation path `_assign` uses for pitched voices — that path exists
to preserve voice-leading, and there is no voice-leading here.

## The seconds floor

`MIN_HIT_SEC` is a module constant in the same category as `ARP_RATE_SEC`: a
fact about the ear, expressed in seconds, set by an audition rather than
guessed. Step 2 above is its only consumer.

Its effect is that density is a property of the pattern meeting the tempo. At
a moderate tempo the eighth-note hats clear the floor and all of them sound;
as the tempo rises the hats fall inside the floor and drop out one class at a
time, leaving the backbeat. `tempo_scale` feeds this for free, because Phase 9
rewrites bar times before `arrange` ever runs — a `tempo_scale = 4.0` minuet
thins itself with no extra code.

The floor is in seconds and does not scale with tempo, for the same reason
`arp_rate_sec` does not: 48 ms was a measurement of hearing, not of music, and
so is this.

The fixtures say where it will bite. At their own tempos the hat spacing is
250 ms on the chorale (4/4 at 120 bpm), 300 ms on ragtime (2/4 at 100 bpm),
and 500 ms on the minuet, whose hats fall on quarters. So a floor anywhere
below 250 ms leaves all three untouched at `tempo_scale = 1.0`, and the
crossing arrives between 2.0 and 4.0 — at 4.0 the chorale's hats are 62 ms
apart, which is inside any plausible floor. That is the span the audition
sweeps, and it is why the floor cannot be set by staring at the default
render: nothing there exercises it.

## The kit on one channel

One noise channel, which is what the NES has. `Instrument` is per-channel, so
the three drums share one `volume_env` and one `pitch_env` and can differ only
in pitch, duration, and velocity — which is also exactly what the real noise
channel offers, since a MIDI pitch here sets the LFSR clock rate rather than a
frequency the ear hears as a note. Low is a rumble, high is a hiss.

Starting values, all of which the audition exists to move:

```python
KICK, SNARE, HAT = 36, 52, 76      # LFSR clock rates, not pitches
HIT_SEC = 0.12
PERC = Voice(
    role="perc",
    instrument=Instrument(wave="noise", volume_env=(15, 12, 8, 5, 3, 1, 0)),
    pan=0.0,
)
```

The envelope ending at 0 matters: the last step sustains, so a drum that ends
on a nonzero level is a drum that never stops. The shared `pitch_env` is the
real compromise — a kick wants a downward sweep that a hat does not — and it
may end up empty. That is a verdict for the audition, not a guess for this
document.

## Surface

Config only, via a new `[percussion]` table:

```python
@dataclass(frozen=True)
class Percussion:
    enabled: bool = False
    level: float = 0.8
```

Added to `Config` and to `_KEYS` with validators that already exist: `_flag`
and `_ranged(low=0.0, high=1.0)`. No new validator machinery. `level` scales
each hit's pattern velocity into the existing 0-15 range.

A preset, `arcade.toml`, turns it on, so hearing the feature is one flag.

`enabled = false` by default is the load-bearing decision, not a timid one:
every existing golden, preset, and audition verdict stays exactly as it is,
and the phase's own audition gets a control that is byte-identical to today's
output by construction rather than by care.

No CLI flag, following Phase 9: `--config` already covers auditioning, and the
flag surface stays small.

## What does not change

- **`render`.** Percussion is baked into the arrangement JSON as an ordinary
  channel with `wave = "noise"`, so a re-render reproduces it from the file
  with no re-derivation. Phase 9 needed an explicit "render does not
  transform" contract because transform would double-apply; nothing here can.
- **The targets stage and `music.ron`.** A channel is a channel.
- **`Roster`, `count`, and the arpeggio carrier.** Percussion is not a voice
  in the reduction's sense and does not participate in overflow.
- **The goldens**, at the default. That is a test, listed below.

One thing does change even when the drums are musically absent from a
listener's attention: `synth` mixes at `MIX_HEADROOM / sqrt(len(channels))`,
so a sixth channel drops every other voice by about 0.8 dB. Real, small, and
worth knowing before the audition reports that the drums made the piece
quieter.

## Testing

Every test below names how to break the implementation and watch it fail. This
repo's rule is that a test is not trusted until it has been proven against a
deliberate regression — a rule that exists because a review once found a test
that had passed this gate at face value while not actually failing under the
regression it claimed to guard.

| Test | Prove it by |
|---|---|
| Percussion off is byte-identical — goldens and rendered audio unchanged | appending the channel unconditionally |
| Each pattern lands where the table says, in seconds, at a non-60 bpm | placing hits at `quarters` without converting through bpm |
| A bar in an unlisted meter refuses, naming the bar number and the signature | falling back to 4/4 |
| A mid-piece meter change uses each bar's own signature | reading `score.time_signature` once instead of `bar.time_signature` |
| A pickup bar keeps only the hits that fit inside its own duration | dropping the bar-duration clip and watching hits spill past the barline |
| The floor drops hats at `tempo_scale = 4.0` and keeps them at 1.0 | scaling `MIN_HIT_SEC` with tempo, which restores the machine gun |
| Priority drops the hat, not the kick, when both land on a downbeat | sorting candidates by time alone |
| No two events on the channel overlap | fixing `dur` at `HIT_SEC` regardless of the next hit |
| Loop choice still picks bars 1-8 on all three fixtures with drums on | nothing — this one asserts a fact about the fixtures rather than about the code, and a failure is a finding for the README, not a bug to fix |

The first is the one that matters most, and it is cheap only because the
default is off — it is the whole reason to ship it off.

Three of these need bars that no fixture provides. Verified on 2026-08-28: the
chorale is 8 bars of 4/4 at 120 bpm, the minuet 16 of 3/4, and ragtime 16 of
2/4 at 100 bpm, all with uniform bar durations — so none of them has a pickup,
a partial bar, or a meter change. The meter-change, pickup, and refusal tests
are therefore built by hand from `Bar` values. That is the correct shape for
them anyway, since each is testing one rule rather than a piece.

Phase 5b's lesson applies to the refusal test: assert the message names the
bar and the meter, not merely that something raised, or it will pass an
implementation that refuses for the wrong reason.

## Audition

The audition **sets** the kit and the floor, the way Phase 7 set 48 ms and
Phase 9 set C1 and C8. It also answers a question no earlier audition has
had to: whether the feature should exist on anything but ragtime.

- **The control is `enabled = false`**, byte-identical to a plain convert by
  construction — simultaneously a unit test and the harness's calibration
  check. In the tail-wrap A/B it was exactly this, a reported difference on a
  pair identical by construction, that exposed an artifact in the harness
  rather than in the audio.
- **All three fixtures**, because the three meters are the three patterns and
  the chorale is where a backbeat is most likely to be wrong.
- **Kit variants** — the three clock rates and the `volume_env` — swept as
  code edits, since the kit stays out of the TOML. Two or three variants, not
  a matrix.
- **The floor**, heard by crossing it: a tempo sweep where the hats survive on
  one side and drop on the other, so the verdict is about where the floor
  belongs rather than about what is inside it.
- **`level`** at two settings, to find whether drums this loud are what makes
  the grid feel imposed.

Rules carried forward: clips stay continuous, with no separators, inserted
silence, or fake seams, and a probe asserts no near-zero window before
anything is handed over; WAV only, since `aplay` renders Ogg as static; and
each clip must actually exercise the variable — for the floor that means
counting the seconds genuinely on each side of the crossing, not merely
rendering two tempos.

Findings go to the README's Status section. `audition/` is gitignored, so
anything not written down there did not happen.

## Risks

- **The grid may simply be wrong on a chorale.** This is the phase's real
  risk and it is not mitigable by implementation. If the audition says so, the
  honest outcome is that `arcade` documents itself as a ragtime preset, and
  that is a finding rather than a failure.
- **One envelope for three drums.** The kick is the voice that most wants its
  own decay and cannot have one. If the audition says the compromise is
  audible, the fix is a second channel — a scope increase to reject here and
  reconsider with evidence, not to pre-build.
- **Loops can change.** `loop.choose` measures seams on rendered audio, so
  percussion is in a position to move which candidate wins. Bar-aligned hits
  make this unlikely; the test above turns it from a surprise into an
  observation.
- **The 0.8 dB headroom cost.** Small, and it applies to the whole mix rather
  than to the drums, so an A/B that reports "quieter" is reporting this and
  not a bug.
- **Noise generation is a Python loop.** `_lfsr_bits` builds one bit per phase
  cycle in pure Python. At the hat's clock rate over a 0.12 s hit this is tens
  of iterations per event, which is negligible — but it is the first voice to
  use that path in bulk, so convert timing is worth a glance.

## Scope

Deliberately out:

- **A second or third percussion channel.** One noise channel is what the
  hardware has. Revisit only if the audition names the shared envelope as the
  problem.
- **Fills, and any density that responds to the music.** The grid is the
  decision; a fill at a section boundary is the beginning of the score-driven
  design this phase rejected.
- **Styling the kit from TOML.** `[voices.perc]` is not a thing. The kit is
  calibration, and 5b settled that calibration stays out of the config file.
- **A subdivision knob.** The floor handles the case a knob would exist for,
  and a knob plus a floor needs a specified interaction between them.
- **Meters beyond the four in the table.** They refuse. Adding one is a table
  entry and an audition, not a redesign.
- **CLI flags.** Config only.
