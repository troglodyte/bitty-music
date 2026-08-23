# Phase 9: transform

The parent spec drew a `[transform]` table — `transpose = 0`, `tempo_scale =
1.0` — and Phase 5b deliberately left it alone: "5b wires existing knobs. It
does not add musical behaviour. The parent spec's `[transform]` table is new
behaviour rather than an exposed constant, and it belongs to its own phase
with its own auditions. `tempo_scale` in particular reaches into echo timing,
arpeggio steps, and loop seams at once."

This phase adds that behaviour. It is the last named feature phase; with
tail-wrapping closed by audition on 2026-08-23, nothing else is outstanding.

## The decision that shapes everything else

`tempo_scale` could mean two different things, and they are not variations of
each other:

- **Play the same arrangement faster.** Arrange at the score's own tempo, then
  move the synth's time base. Cheap and predictable, but the echo tap, the
  vibrato rate, and the arpeggio step are then all wrong relative to the music
  unless each is corrected by hand.
- **Re-derive the arrangement at the new tempo.** Note durations change, so the
  arranger's duration-sensitive decisions change with them.

**This phase takes the second.** `tempo_scale` is an arranger input, not a
playback trick. The consequence is deliberate and is the phase's most visible
behaviour: at double tempo, notes that used to clear `vibrato.min_note_sec`
(500 ms) no longer do, so the piece loses vibrato. A slowed piece gains it.
That is a re-arrangement, which is the point.

## Where it lives

A new module, `src/bitty/transform.py`, with one pure function:

```python
def apply(score: Score, settings: Transform) -> Score
```

It sits immediately after `ingest` at both call sites — `cli.py:102`
(`sections`) and `cli.py:164` (`convert`) — so `analyze`, `arrange`, `loop`,
`synth`, and the emitters see only the transformed score and need no knowledge
that a transform happened.

**Why a module rather than folding it into `ingest`.** Ingest's job is
resolving what the notation *means*: dynamics into velocities, trills into the
fast notes they stand for, a grace note moved to sound before the note it
decorates. Transform changes what the music *is*. Different jobs, and the
separation means `apply` is testable on a hand-built `Score` with no score
file, no music21, and no I/O.

**`render` must not apply it.** `render`'s contract is that it obeys the JSON —
everything musical was decided when the file was written. A transform applied
at render would double-apply on the ordinary convert, hand-edit, re-render
path: convert at `transpose = +3` writes an arrangement already in the new key,
and re-rendering it would land at `+6`. So `[transform]` joins the musical half
of the config that `render` deliberately ignores.

```
ingest → transform → analyze
                   → arrange → loop → synth → emit
arrangement.json ────────────→ synth → emit      (render: no transform)
```

One transform site, one direction, no way to apply it twice.

## What the two knobs do

### `tempo_scale` is two operations, not one

Because transform runs *after* ingest, note times are already in seconds
(`ingest.py:81` computes `seconds_per_quarter` and bakes it in). Scaling
`score.bpm` alone would relabel the tempo while every note kept its old timing
— a wrong implementation that passes any test looking only at tempo metadata.
`apply` does both:

```
bpm    → bpm * scale
start  → start / scale        # faster tempo, shorter times
dur    → dur / scale
```

That pair keeps everything downstream consistent without special-casing, and
the split between what follows the music and what does not falls out of the
existing code rather than being imposed:

| Follows the tempo | Stays absolute |
|---|---|
| echo delay — `delay_beats * 60/bpm` in `arrange.py:86` | `arp.step_sec` — 48 ms is a property of the ear |
| bar boundaries in `analyze` | `vibrato.rate_hz`, `vibrato.delay_sec` |
| loop seam positions, output duration | `vibrato.min_note_sec` — the 500 ms threshold |

The right-hand column is absolute because those values are seconds in config
and nothing derives them from `bpm`. That is not an accident of the plumbing
and must not be "fixed": Phase 7's audition established that 48 ms is a
psychoacoustic threshold about the ear rather than about the music, after
16 ms was found to fuse into roughness at 31 Hz instead of reading as notes.
Scaling it with tempo would undo that finding.

### `transpose` is a uniform shift with an invariant

An integer semitone offset applied to every note. The arranger has no absolute
pitch logic anywhere — top and bottom pinning, nearest-last-pitch assignment,
pitch-class comparison in the reduction policy, and the arpeggio's octave
folding are all relative or uniformly shifted. Therefore:

> `arrange(transpose(score, n))` is exactly `arrange(score)` with every pitch
> shifted by `n`.

This is a real invariant rather than a happy-path assertion, and it is the
load-bearing test for transpose. It also means transpose costs no golden
churn: the goldens stay at `transpose = 0`.

Key detection needs no special-casing — `analyze` sees the transposed pitches,
so `bitty sections` reports the new key on its own.

### The bounds

Two limits for two reasons, and only one of them is technical:

- The technical ceiling is nearly irrelevant. A fundamental below
  `0.45 x 44100` is around MIDI 135, which no real score reaches, and PolyBLEP
  bandlimits the harmonics above it. `NYQUIST_MARGIN` in `filters.py` clamps
  filter cutoffs, not oscillator pitch; there is no existing pitch bound.
- The binding limit is audibility, which is taste. **MIDI 24 (C1, 32.7 Hz)** as
  the floor, below which the quantized triangle bass stops reading as pitch on
  small speakers, and **MIDI 108 (C8, 4186 Hz)** as the ceiling.

Both are provisional. This phase's audition sets them, the way Phase 7 set
`arp_rate_sec` by ear rather than by theory. They live in `transform.py` as
module constants, not config keys, following 5b's precedent that calibration
stays out of the TOML.

## Surface

Config only, via `[transform]`, exactly as the parent spec drew it. No
`--transpose` or `--tempo-scale` flags: transposition is a property of one
piece rather than a project-wide taste, so a per-score `<stem>.bitty.toml` is
its natural home, and the flag surface stays small.

Auditioning a sweep does not need flags — `--config` already exists, so each
variant is a scratch TOML and one `convert` invocation.

## Structure

In `config.py`, alongside the existing dataclasses:

```python
@dataclass(frozen=True)
class Transform:
    transpose: int = 0        # semitones
    tempo_scale: float = 1.0
```

Added to `Config`, and to the `_KEYS` table with validators that already
exist: `_whole(low=-48, high=48)` and `_ranged(low=0.25, high=4.0)`. No new
validator machinery. Four octaves and a quarter-to-quadruple tempo are past
where either knob is a sane request.

## Refusing a transpose that does not fit

Validation happens in two places, because neither alone can do the job:

1. **Config-time**, inside `merge`. Is the value well-formed and sanely
   bounded at all? `tempo_scale = 0` or `transpose = "up a bit"` dies here,
   with `ConfigError` naming the source file and the key path exactly like
   every other key. It is a row in `_KEYS` and nothing more.
2. **Score-time**, inside `transform.apply`. Does *this* transpose fit *this*
   score? It needs the pitch range, so it can only happen after ingest. It
   raises `ValueError`, which the CLI wraps as
   `typer.BadParameter(..., param_hint="--config")`.

The split is honest about what each stage knows: config-time can name the file
but has never seen a note, score-time has the notes but not the provenance —
`load` folds every layer into a plain frozen `Config` and retains no source.
The CLI has both and composes the message.

Raising `ValueError` from the stage module and wrapping it in the CLI is the
established pattern here, not a new one: `loop_stage.trim` does it for
`--bars` and `loop_stage.candidates` for `--loop-from`.

The refusal names the arithmetic rather than complaining:

```
transform.transpose = +7: C8 (MIDI 108) becomes MIDI 115, past the
playable ceiling of 108. This score allows at most +0.
Config read from: minuet.bitty.toml
```

## Identity

`apply` under the defaults — `transpose = 0`, `tempo_scale = 1.0` — returns
the score unchanged. That is what keeps all three golden files valid, and it
makes the default case provably a no-op rather than an arithmetic round trip
that happens to land back where it started.

## Testing

Every test below names how to break the implementation and watch it fail. This
repo's rule is that a test is not trusted until it has been proven against a
deliberate regression — a rule that exists because a review once found a test
that had passed this gate at face value while not actually failing under the
regression it claimed to guard.

| Test | Prove it by |
|---|---|
| Identity under defaults — goldens and rendered bytes unchanged | making `apply` always rebuild the score |
| Transpose invariant — the *whole* arrangement equals the untransposed one shifted by `n`: event times, velocities, vibrato flags, arp tuples, channel roles, pans, echo, not only pitches | giving `arrange` any absolute pitch threshold |
| `tempo_scale` re-arranges — a 520 ms note loses vibrato at `scale = 1.5` | implementing `tempo_scale` as bpm-only, with no time scaling |
| `arp_rate_sec` does not scale with tempo | scaling it, and watching Phase 7's guarantee break |
| Range refusal names the offending pitch and the largest allowed transpose | removing the check |
| Render does not transform — convert at `+3`, render that JSON under the same config, assert byte-identical audio | wiring transform into `render` and watching it land at `+6` |

The third is the one that matters most. The obvious wrong implementation —
scale `bpm` and stop — passes every test that only inspects tempo metadata and
fails only this one. The transpose invariant must assert the whole arrangement
rather than the pitch list, or it will pass an implementation that shifts
pitches correctly while dropping arp offsets; Phase 5b's lesson was that a test
guarding a subset rule has to fail the coarser implementation, not merely the
happy path.

## Audition

The audition **sets** the two bounds rather than confirming them.

- `transpose` at −12, −5, 0, +5, +12 on a fixture, and deliberately past C1
  and C8 to hear where it actually stops working.
- `tempo_scale` at 0.75, 1.0, and 1.5 on the minuet, listening for whether the
  re-arrangement reads as musical: the echo following the tempo, and vibrato
  appearing and disappearing across the 500 ms threshold.
- Push against `tempo_scale = 4.0` rather than staying safe, to hear the
  envelope-frame risk below.

Two rules carried from the tail-wrap audition on 2026-08-23:

- **`transpose = 0, tempo_scale = 1.0` is the control**, byte-identical to the
  current default render by construction. It is simultaneously a unit test and
  the audition's calibration check. In the tail-wrap A/B it was exactly this —
  a reported difference on a pair that was identical by construction — that
  exposed an artifact in the harness rather than in the audio.
- **Clips stay continuous.** No separators, no inserted silence, no
  concatenation joins that fake a seam, and a probe asserting no near-zero
  window before anything is handed over. WAV only; `aplay` renders Ogg as
  static.

## Risks

- **Notes below one envelope frame.** At `tempo_scale = 4.0` a short note can
  fall under 16.7 ms (volume envelopes run at 60 steps/sec) and articulate as
  a click rather than a note. The 4.0 cap is the mitigation; the audition
  should find where it actually starts.
- **Loops can change.** `tempo_scale` moves seam positions in the audio, so the
  seam check may newly accept or reject a candidate and a transformed piece can
  loop differently from the same piece untransformed. Not a defect, but it
  should be observed here rather than discovered later.
- **The C1/C8 bounds are taste, not measurement.** If the audition disagrees,
  the constants move and this document's numbers are wrong rather than its
  design.
- **`tempo_scale` compounds with the reduction.** Fewer vibrato notes and
  shorter arpeggiated notes both change the texture at once, so a bad result at
  an extreme scale may be hard to attribute. Audition one knob at a time.

## Scope

Deliberately out:

- **CLI flags for either knob.** Config only; `--config` covers auditioning.
- **Transform at `render`.** It would double-apply. This is a contract, not an
  omission.
- **Automatic range fitting.** No octave-folding of out-of-range notes back
  into the playable band. Folding would let a melody leap an octave mid-phrase,
  which is the note-soup failure that voice-leading assignment exists to
  prevent. Out-of-range refuses instead.
- **Non-integer transpose.** Semitones only; there is no cents knob and the
  pitch pipeline is integer MIDI throughout.
- **Making the playable bounds configurable.** They are calibration, and 5b
  settled that calibration stays out of the TOML.
