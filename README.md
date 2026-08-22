# bitty-music

Turns classical scores into chiptune.

Hand it a MusicXML or MIDI file and it gives you back audio plus a plain-JSON
arrangement you can edit by hand and re-render. The interesting part is not the
synthesis — it is the **reduction**: deciding which of five monophonic chip
channels plays each note of a four-part chorale without the melody turning into
note soup.

## Install

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

This puts a `bitty` command on the path.

## Commands

### `bitty sections` — what's in the score

```bash
bitty sections score.mxl
```

Prints the structure the score's own marks describe, so you can see what
there is before choosing any of it:

```
minuet  ·  q=120  ·  16 bars  ·  24.0s

  A   bars   1-8    3/4   G major    0:00.0    12.0s   repeat
  B   bars   9-16   3/4   D major    0:12.0    12.0s   repeat
```

Boundaries come only from notation — repeat marks, final and double bars,
and key or time signature changes — so every one can be traced to something
a composer wrote. A piece with none of those marks reports as one section,
which for an eight-bar hymn is the honest answer rather than a failure.

Section names are positional. `A` and `B` mean first and second, not "these
two are related" — telling repeated material apart needs analysis this
command deliberately does not do.

The key is detected, not read off the key signature, which is how the minuet
above shows its second half modulating to the dominant.

### `bitty convert` — score in, audio out

```bash
bitty convert score.mxl                    # -> out/score.ogg + out/score.arrangement.json
bitty convert score.mxl -o out/takes --wav # WAV instead of Ogg, in a directory you choose
```

Accepts MusicXML (`.musicxml`), compressed MusicXML (`.mxl`), and MIDI. Writes
two files: the audio, and the arrangement JSON that produced it.

| Option | Meaning |
|--------|---------|
| `-o`, `--out-dir` | Where to write. Default `out`. |
| `--wav` | Uncompressed WAV instead of Ogg Vorbis. |
| `--bars N-M` | Keep only printed bars N through M. Times rebase to zero; bar numbers do not. |
| `--loop-from N` | Start the loop at printed bar N. Overrides the cascade, seam check included. |
| `--target NAME` | `bevy` (default), `bevy-kira`, or `generic`. See Targets below. |

### `bitty render` — edited JSON in, audio out

```bash
bitty render out/score.arrangement.json --wav
```

Re-renders an arrangement, skipping score analysis entirely. This is the loop
you want when you are tuning a passage: convert once, then edit the JSON and
render as often as you like. `foo.arrangement.json` renders to `foo.ogg`, not
`foo.arrangement.ogg`.

Same `-o`, `--wav`, and `--target` options as `convert`.

## Looping

A loop track needs a splice point where the audio comes back around, and
`convert` finds one on its own. `bitty sections` prints what it would pick
without writing anything, so you can check before you commit to it:

```
minuet  ·  q=120  ·  16 bars  ·  24.0s

  A   bars   1-8    3/4   G major    0:00.0    12.0s   repeat
  B   bars   9-16   3/4   D major    0:12.0    12.0s   repeat

  auto-loop pick: bars 1-8  (repeat marks, seam ok)
```

**The cascade** tries candidates cheapest and most trustworthy first: repeat
marks (`:||:` in the notation), longest span first — a loop wants the
substantial repeated body, not an incidental four-bar echo — then section
boundaries, section *k* through the last section with *k* ascending, so the
whole piece is offered before any suffix of it. If nothing in either tier
survives the seam check, there is no loop, and `sections` says so rather than
guessing. `--loop-from` skips the cascade (and its eight-bar floor) entirely:
the candidate is bar N to the end, checked but never overruled.

**A candidate is rejected** when the audio's jump across the splice is large
against how large a jump this piece ordinarily makes — measured, not an
absolute threshold, so a chip square wave's full-amplitude edges do not read
as a click — or when the splice severs a dry note, cutting off a note that
has not finished sounding when the loop restarts.

**The one thing that does not reject is the final note's echo.** The lead
voice carries an echo tap, and on nearly every candidate across the fixtures
that tap is still ringing when the loop end arrives — rejecting on it would
leave two of three fixtures with no loop at all. It is measured, counted, and
reported instead ("echo tail cut" in the pick line), because whether it's
audible enough to matter is a call for a person, not a threshold.

A chosen loop lands in `arrangement.json` as two seconds, matching everything
else in the file:

```json
"loop": { "start_sec": 0.0, "end_sec": 12.0 }
```

No source, no ratio — those are printed at the moment they're decided. The
hand-edit surface only carries what someone might actually want to change.

## Targets

`--target` picks what gets written alongside the audio, and it is chosen for
the engine that will load the result, not for the piece.

**`bevy`** is the default. It writes an intro and a loop as two separate
files, because `bevy_audio` (the rodio-backed built-in) has no seek and no
loop region — it can only loop a whole file, so the intro has to live
outside the part that repeats. A loop that starts at 0:00 needs no intro, so
none is written. A piece with no loop at all is not an error: it comes out
as a single one-shot file, a `full` entry rather than `intro`/`loop_`.

**`bevy-kira`** writes one whole file plus `loop_start`/`loop_end` in
seconds, for the `kira` audio backend, which has real loop regions and does
not need the file split.

`bevy` and `bevy-kira` each write a `name.<target>.ron` fragment — one map
entry — next to the audio. After every conversion, the fragments in the
output directory are assembled into `music.ron`. This is a glob, a sort, and
a concatenation, not a read-modify-write of a shared file, so converting one
piece can never drop another's entry: nothing ever loads `music.ron` to
rewrite it.

**`generic`** embeds the loop as `LOOPSTART`/`LOOPLENGTH` Vorbis comments —
in samples — directly in the Ogg file, the convention Unity and Godot both
read. It writes no fragment and no `music.ron`; the loop lives entirely in
the audio file's own tags.

`--wav` is orthogonal to all three targets — it swaps Ogg for uncompressed
WAV so you can audition through `aplay`, which renders Ogg as static. A WAV
carries no Vorbis comments, so `generic --wav` writes audio with the loop
information only in the arrangement JSON sidecar, not in the file itself.

### `music.ron`

```ron
#![enable(implicit_some)]
(
    tracks: {
        "minuet": (
            title: "Minuet in G",
            intro: "minuet_intro.ogg",
            loop_: "minuet_loop.ogg",
            bpm: 88.0,
            bars: (1, 32),
        ),
        "fanfare": (
            title: "Fanfare",
            full: "fanfare.ogg",
            bpm: 120.0,
            bars: (1, 8),
        ),
    },
)
```

The `implicit_some` header is what lets `intro`, `loop_`, `full` and
`bars` be written as bare values rather than `Some(...)`; without it `ron`
rejects the file with `ExpectedOption`.

`loop_` because `loop` is a reserved word in Rust. `bars` is the printed
range the arrangement covers; it is omitted when the source arrangement
didn't have one, rather than invented. `title` falls back to the file stem
and `bpm` to `0.0` when `meta` is missing them — a hand-edited arrangement
can be missing any key, and a missing one must not crash an emit.

The matching Rust side, to paste straight into the game:

```rust
#[derive(serde::Deserialize)]
pub struct MusicManifest {
    pub tracks: std::collections::HashMap<String, Track>,
}

#[derive(serde::Deserialize)]
pub struct Track {
    pub title: String,
    #[serde(default)] pub intro: Option<String>,
    #[serde(default)] pub loop_: Option<String>,
    #[serde(default)] pub full: Option<String>,
    pub bpm: f32,
    #[serde(default)] pub bars: Option<(u32, u32)>,
}
```

## How it works

Four stages, each a separate module that does one thing:

```
score file → ingest → arrange → synth → audio
                        ↓
                 arrangement.json  ←── you can edit this and re-render
```

**`ingest`** reads the score into a flat list of notes with times in seconds. It
resolves what the notation *means*: written dynamics (`f`, `p`) become
velocities, trills and mordents and turns expand into the fast notes they stand
for, and a grace note is moved to sound *before* the note it decorates rather
than on top of it. Every note also carries its metric position — where in the
bar it falls.

**`arrange`** is the reduction. Notes are grouped by onset; the top of the
sounding texture is pinned to the lead channel and the bottom to the bass, and
everything in between goes to whichever channel's last pitch is nearest. A
channel is monophonic, so a note landing on a busy channel truncates what it was
holding. Anything that finds no channel at all is folded into a fast-cycling
arpeggio rather than dropped.

The naive alternative — re-sort each chord top-to-bottom and hand slot one the
highest note — produces a melody that teleports whenever an inner voice briefly
rises above it. Voice-leading assignment is the difference between a
recognizable tune and note soup.

Arrange also decides articulation: downbeats get a velocity bump, weak beats a
trim, and notes held longer than 500 ms are flagged for vibrato.

**`synth`** is the mixer. Signal path per channel: oscillator → pitch envelope
and vibrato → volume envelope → edge fade → lowpass → constant-power pan → sum.
Then across the mix: echo taps, DC blocker, soft clip. Waveforms live in `osc`,
envelopes in `envelope`, the vibrato LFO in `lfo`, and filtering in `filters` —
each a pure function of arrays.

### The five voices

| Role | Wave | Duty | Job |
|------|------|------|-----|
| `lead` | pulse | 0.5 | The melody. Carries the echo. |
| `counter` | pulse | 0.25 | Countermelody / second voice. |
| `inner_a` | pulse | 0.25 | Inner harmony. |
| `inner_b` | pulse | 0.125 | Inner harmony, and the arpeggio overflow. |
| `bass` | triangle | — | The bottom line, amplitude-quantized to 16 steps. |

Channels with nothing to play are dropped rather than rendered silent — the
synth divides headroom by channel count, so an empty channel only costs
loudness.

## The arrangement file

`arrangement.json` is the hand-edit surface, and it is deliberately flat: fixing
a passage should not mean navigating a tree.

```json
{
  "meta": { "title": "chorale", "bpm": 120.0, "bars": [1, 8] },
  "channels": [
    {
      "role": "lead",
      "instrument": {
        "wave": "pulse",
        "duty": 0.5,
        "volume_env": [15, 15, 14, 13, 12, 12, 11],
        "pitch_env": [2, 1, 0],
        "cutoff_hz": null,
        "resonance": 0.7071,
        "quantize": null
      },
      "pan": -0.2,
      "echo": { "delay_sec": 0.375, "level": 0.35 },
      "events": [
        { "t": 0.0, "pitch": 69, "dur": 0.5, "vel": 10, "vibrato": true }
      ]
    }
  ],
  "loop": { "start_sec": 0.0, "end_sec": 12.0 }
}
```

**Event fields**

| Field | Meaning |
|-------|---------|
| `t` | Seconds from the start of the arrangement. |
| `pitch` | MIDI note number. |
| `dur` | Seconds. |
| `vel` | 0–15. Sixteen levels is what a chip channel actually has; the coarse steps are the texture, not a loss. |
| `vibrato` | A delayed pitch LFO — 25 cents at 5.5 Hz, fading in after 300 ms. |

**Instrument fields** — everything past `wave` is optional.

| Field | Meaning |
|-------|---------|
| `wave` | `pulse`, `triangle`, `saw`, or `noise`. |
| `duty` | Pulse only. |
| `volume_env` | Levels 0–15 at 60 steps/sec; the last one sustains. |
| `pitch_env` | Semitone offsets at the same rate. The attack blip that makes a chip lead read as percussive. |
| `cutoff_hz` | `null` means no filtering at all. |
| `resonance` | Biquad Q. `0.7071` is flat; higher peaks. |
| `quantize` | Triangle amplitude steps — `16` for an NES-ish bass. |

A field this build does not recognize is dropped rather than fatal, so an
arrangement written by a newer bitty still renders with what is understood.

## Development

```bash
.venv/bin/pytest
```

Golden-file tests render three fixtures (`chorale`, `minuet`, `ragtime`) and
compare the arrangement JSON byte for byte. Arranging is deterministic —
identical input produces identical output, and nothing calls `random`. When a
change to the reduction is intended, regenerate and **read the diff**:

```bash
BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py
git diff tests/goldens/
```

`tests/test_quality.py` measures the reduction rather than trusting it: what
percentage of lead events actually came from the score's top part, the same for
the bass, and how many octave-plus leaps the melody makes. Those numbers are
anchored to a measured baseline. A failure there means a change cost the voice
leading, which is a reason to stop — not to lower the threshold.

## Status

Phase 4 is done: ingest, synthesis, the reduction, articulation, structural
analysis, and looping — the loop cascade, `--bars` and `--loop-from`, and the
intro/loop split. Phase 5a is done: the `Render` contract, the `bevy`,
`bevy-kira`, and `generic` targets, and `music.ron` assembly. There is no
config yet — Phase 5b picks up TOML config and presets.

Design documents and per-phase implementation plans live in
`docs/superpowers/`.
