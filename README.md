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

The matching Rust side for `bevy`, to paste straight into the game:

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

`bevy-kira` writes a different shape — one file plus loop offsets in
seconds, rather than an intro/loop/full split — so it needs its own struct
rather than reusing `Track`. This is what `music.ron` actually contains
under `--target bevy-kira`:

```ron
#![enable(implicit_some)]
(
    tracks: {
        "minuet": (
            title: "minuet",
            file: "minuet.ogg",
            loop_start: 0.0,
            loop_end: 12.0,
            bpm: 120.0,
            bars: (1, 16),
        ),
    },
)
```

```rust
#[derive(serde::Deserialize)]
pub struct KiraManifest {
    pub tracks: std::collections::HashMap<String, KiraTrack>,
}

#[derive(serde::Deserialize)]
pub struct KiraTrack {
    pub title: String,
    pub file: String,
    #[serde(default)] pub loop_start: Option<f32>,
    #[serde(default)] pub loop_end: Option<f32>,
    pub bpm: f32,
    #[serde(default)] pub bars: Option<(u32, u32)>,
}
```

`loop_start`/`loop_end` are seconds, not samples — kira takes seconds, and
this is the only target where the offsets do not become samples. They are
omitted from the RON (not written as `0.0`) when the arrangement has no
loop, which is why they are `Option<f32>` rather than plain `f32`.

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
holding. Anything that finds no channel at all goes to the reduction policy, which
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
| `arp` | Semitone offsets from `pitch`, cycled at the instrument's `arp_rate_sec`. Empty means a plain note. One event, not one per step — the envelopes run once across the whole figure, which is what keeps an arpeggiated pitch in tune. Always under 12: members are folded into the octave above the lowest, so a cycle names a chord instead of leaping. |

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
| `arp_rate_sec` | Seconds per arpeggio step; `0.048` by default. It travels here rather than in config so a hand-edited arrangement renders the same anywhere. Not the hardware's one-step-per-frame `0.016`: at that rate a two-note cycle alternates at 31 Hz, which the ear fuses into a rough timbre rather than hearing as notes. |

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

## Configuration

Every knob that isn't a per-run flag lives in TOML. Six layers stack, each
free to override anything an earlier one set, first to last:

| Layer | Source |
|-------|--------|
| 1 | Built-in defaults (`Config`/`DEFAULTS` in `config.py`) |
| 2 | `--preset NAME` |
| 3 | The nearest `bitty.toml`, walking up from the score's directory |
| 4 | `<stem>.bitty.toml`, next to the score |
| 5 | `--config PATH` |
| 6 | Flags: `--wav`/`--ogg`, `-o`/`--out-dir`, `--target` |

### File discovery

`bitty` looks for two kinds of file, and both are optional.

**`bitty.toml`** is a project-wide config. `discover` walks upward from the
score's directory through its parents and stops at the *first* `bitty.toml`
it finds — it does not keep climbing to also layer in one from two
directories further up. A config applies whole or not at all: if it merged
across levels, the file sitting in front of you would never be the whole
story — you'd also have to know what some ancestor directory contributed.

**`<stem>.bitty.toml`** is a per-piece override, e.g. `minuet.bitty.toml`
next to `minuet.mxl`. It follows the existing `.arrangement.json`
convention (`minuet.arrangement.json`) rather than being a bare
`minuet.toml`, because a bare `<stem>.toml` would collide with whatever
else in the directory already wants that name.

`discover()` resolves the score's directory to its real path before
walking upward, so a symlinked score directory searches its real ancestry,
not the symlink's apparent location.

`--config PATH` (layer 5) sits above both discovered files: naming a file
on the command line is a deliberate act, and it should beat a file that
merely happened to be found.

A relative `[output] dir` is resolved against the directory you run `bitty`
from, not against the config file that set it — the same rule a shell
applies to any relative path you hand it.

### Complete example

Every table `bitty` understands, with every key at its default value:

```toml
[output]
target = "bevy"        # bevy | bevy-kira | generic — checked by the CLI, not here
format = "ogg"          # "ogg" | "wav"
dir = "out"
sample_rate = 44100     # 8000-192000

[voices]
count = 5                # 3-5; narrows the roster — see [voices] count below

[echo]
on = true
delay_beats = 0.75      # 0.0-16.0, in beats
level = 0.35            # 0.0-1.0

[arp]
rate_ms = 48.0           # >=1.0; the overflow arpeggio's step time

[vibrato]
depth_cents = 25.0       # 0.0-1200.0
delay_ms = 300            # >=0.0; silence before the LFO fades in
rate_hz = 5.5             # 0.0-40.0
min_note_ms = 500         # >=0.0; a note shorter than this never gets vibrato

[loop]
min_bars = 8              # >=1, whole bars
seam_ratio = 1.0          # >=0.0

[transform]
transpose = 0             # -48..48 semitones; refuses if the score leaves C1-C8
tempo_scale = 1.0         # 0.25-4.0; re-arranges at the new tempo
```

`[vibrato]`'s first three keys are spread onto every voice's instrument;
`min_note_ms` stays global rather than spreading, because it is arranger
policy — it decides *which* notes get vibrato at all — not a timbre
setting like the other three.

### `[voices.<role>]`

Five tables, one per role: `lead`, `counter`, `inner_a`, `inner_b`, `bass`.
A key left out of a role's table keeps that role's built-in value (the
roster in `voices.py`); every key below is optional.

| Key | Range | Belongs to |
|-----|-------|------------|
| `pan` | -1.0 to 1.0 | the voice |
| `wave` | `pulse` \| `triangle` \| `saw` \| `noise` | the instrument |
| `duty` | 0.0-1.0 (pulse only) | the instrument |
| `volume_env` | list of whole numbers, 0-15 | the instrument |
| `pitch_env` | list of whole numbers, -48 to 48 | the instrument |
| `cutoff_hz` | >=20.0 | the instrument |
| `resonance` | 0.1-20.0 | the instrument |
| `quantize` | whole number, 2-256 | the instrument |
| `vibrato_cents` | 0.0-1200.0 | the instrument |
| `vibrato_delay_ms` | >=0.0 | the instrument |
| `vibrato_rate_hz` | 0.0-40.0 | the instrument |

Within one file, order is: the global `[vibrato]` table sets every voice
first, then a `[voices.<role>]` table overrides one role afterward. Across
files, it's simpler — the later file's value just wins, same as every
other key.

### `[voices] count`

`count` — an integer, 3 to 5, default 5 — narrows the roster. It is the one
scalar key in the `[voices]` table; every other key there is a role
sub-table, as above.

Lead and bass are structural pins: the reduction assigns against the top
and bottom of the standing texture, so both always survive. `count`
shrinks the middle voices instead, one at a time, from the narrowest
duty width — a role that has nowhere left to fold its overflow becomes
the arp carrier for whatever's left:

| count | active voices | dropped | arp carrier |
|-------|---------------|---------|-------------|
| 5 | lead, counter, inner_a, inner_b, bass | — | `inner_b` |
| 4 | lead, counter, inner_a, bass | `inner_b` | `inner_a` |
| 3 | lead, counter, bass | `inner_b`, `inner_a` | `counter` |

Three is the floor, not an arbitrary limit: below it there is no middle
voice left to carry the arpeggio overflow, and the reduction has nowhere
to put a chord tone that didn't make the cut. At the default of 5, this
key changes nothing — count 5 is the roster this project always shipped.

A dropped voice's `[voices.<role>]` overrides are still accepted; they
just have nothing to apply to unless a later config layer raises `count`
again.

**Count 3 leans on the reduction policy.** With only one middle voice,
`_pick_middle` can place at most one note per onset and everything else
overflows. Before the policy existed that overflow dominated — the chorale's
carrier arpeggiated through 92.2% of the piece, all of it two-note trills.
The policy drops what is already sounding and refuses to arpeggiate anything
that cannot name a chord, which takes the chorale and the minuet to no
arpeggio at all and ragtime to 26.1%. The cost is harmonic: a few chords per
piece lose their third where no doubling was free to displace.

### `[transform]`

Two keys that change the score itself rather than how it is rendered:
`transpose`, whole semitones from -48 to 48, default 0; and `tempo_scale`,
0.25 to 4.0, default 1.0. Both are applied by `transform.apply`, which runs
immediately after `ingest` at exactly two sites — `bitty sections` and
`bitty convert` — so the score that gets analysed, reduced, looped and
rendered is already the transformed one, and the sections `bitty sections`
prints are the sections of the piece you will actually hear.

Neither has a CLI flag, deliberately. A transposition is a property of one
piece — this song sits too low for a pulse wave — not a taste you hold across
a project, so its natural home is a `<stem>.bitty.toml` sitting next to the
score, where it stays attached to the score it describes.

**`tempo_scale` is an arranger input, not a playback speed.** It scales `bpm`
and every note and bar time inversely, so what comes out is the same music
re-derived at the new tempo, not the old arrangement replayed faster.
Everything downstream that is measured in beats moves with it; everything
measured in seconds does not:

| Follows the tempo | Stays absolute |
|---|---|
| The echo's delay — `delay_beats` is beats, and a beat got shorter | `arp.rate_ms` |
| Bar boundaries, and the sections `bitty sections` prints | `vibrato.rate_hz` |
| Loop seam positions, and the length of what is written | `vibrato.delay_ms` |
| Which notes are long enough to waver | `vibrato.min_note_ms` |

That last row is where the difference bites. At `tempo_scale = 1.5`, notes
that used to clear `vibrato.min_note_ms`'s 500 ms no longer do, and the piece
loses vibrato it had; slow the same piece down and notes that were previously
too brief acquire it. A tape-speed control would have carried the vibrato
along unchanged. This is a re-arrangement — and that is the point: at a new
tempo, the arranger's judgements about *which* notes are long enough to
waver deserve to be made again at the tempo you asked for, not inherited from
the one you didn't.

The right-hand column stays absolute because those values are seconds in the
file and nothing derives them from `bpm` — and `arp.rate_ms` in particular is
not a musical duration at all. Phase 7 chose 48 ms by ear, after 16 ms was
found to fuse into roughness at 31 Hz rather than reading as separate notes.
That is a fact about hearing, not about the piece, and it does not become
less true when the music speeds up. Scaling it with the tempo would quietly
undo the finding at every tempo but 1.0.

**`transpose` refuses rather than folds.** It is uniform whole semitones
applied to every note, and when one of them would leave the playable band the
run stops and says which note, by how much, and what would have fit:

```
$ bitty convert minuet.mxl
Invalid value for --config: transform.transpose = +21: E6 (MIDI 88) becomes
MIDI 109, past the playable ceiling of 108. This score allows at most +20.
Config read from: /home/you/scores/minuet.bitty.toml
```

A `Config read from:` line follows for every config file the run read, because
the value that caused this came out of a file and the cascade means the file
you are looking at may not be the one that set it.

The alternative — folding the offending note back into the octave below —
would keep the run alive by silently rewriting the melody, turning a scale
step into a seventh in the other direction. The whole promise of a uniform
transpose is that the intervals survive it, so a transpose that cannot keep
that promise should say so rather than half-keep it. Naming the largest shift
that does fit turns the error into the answer: `+20` here, so try that.

The refusal is judged against the whole score, before `--bars` trims
anything, because `transform.apply` runs immediately after `ingest` and
validation belongs with the transform rather than with whichever excerpt a
later flag happens to keep. `bitty convert ragtime.mxl --bars 1-2` at
`transpose = 20` is refused naming `G#6 (MIDI 92)` and "this score allows at
most +16", even though bars 1-2 top out at MIDI 75 and would fit the shift
comfortably — the note that decides it lives in a bar the excerpt never sees.

The band is MIDI 24 (C1, 32.7 Hz) to MIDI 108 (C8, 4186 Hz), and it lives as
module constants in `transform.py` rather than as config keys. It is
calibration, not taste: it describes where this synth's oscillators and the
ear still agree that a pitch is a pitch, which is not something a piece gets
an opinion about. The current numbers are provisional — an audition may yet
find the useful band is narrower than the theoretical one, and moving a
constant is the cheaper edit.

`bitty render` deliberately does not transform. It takes an arrangement JSON
that has already been through all of this and turns events into samples;
everything musical was decided when that JSON was written. If `render`
applied `[transform]` too, a `convert` at `+3` re-rendered under the same
config would land at `+6` — the same file transposed twice by the same
config, which is exactly the surprise a rendering step must not hold.

### Milliseconds in the file, seconds in the code

Every key ending in `_ms` — `arp.rate_ms`, `vibrato.delay_ms`,
`vibrato.min_note_ms`, `voices.<role>.vibrato_delay_ms` — is milliseconds
in TOML and seconds once loaded into `Config`. The conversion happens once,
in `config.py`, so neither the file format nor the rest of the code has to
carry the other side's convention.

### Presets

Two ship in `presets/`, selected with `--preset NAME`:

- **`nes-tight`** — closer to the hardware: `count = 3`, no echo, a mono
  image (every voice's pan pinned to `0.0`), and vibrato that arrives
  later and shallower. Three channels: the NES's true
  two-pulses-and-a-triangle melodic roster. This preset sat at `count = 4`
  until the reduction policy made three voices musical — before it, the
  lone middle voice arpeggiated through most of the piece. The honest
  roster is not free: at three voices a few chords lose a third they used
  to have. See `[voices] count` below.
- **`lush`** — the other direction: a longer, louder echo, a wide stereo
  image, and vibrato that arrives early enough to sing on ordinary
  phrase-length notes.

### Unknown keys are an error, not a warning

A typo'd key stops the run instead of silently doing nothing — a tuning
tool's worst failure mode is a config that looks like it worked and
didn't. For example, `[echo]` with `onn = true` instead of `on = true`
produces:

```
$ bitty convert minuet.mxl --config bad.bitty.toml
Invalid value for --config: bad.bitty.toml: echo.onn: unknown key; [echo]
accepts delay_beats, level, on
```

The same happens for an unknown table (`unknown table; bitty config accepts
arp, echo, loop, output, transform, vibrato, voices`) and an unknown `[voices.<role>]`
role (`unknown voice; the roster is lead, counter, inner_a, inner_b, bass`)
or key.

## Status

Phase 4 is done: ingest, synthesis, the reduction, articulation, structural
analysis, and looping — the loop cascade, `--bars` and `--loop-from`, and the
intro/loop split. Phase 5 is done, both halves: 5a's `Render` contract, the
`bevy`, `bevy-kira`, and `generic` targets, and `music.ron` assembly; 5b's
TOML config, the precedence cascade, and the two shipped presets. Phase 6 is
done: `[voices] count`, narrowing the roster down to as few as three
voices, and `nes-tight` — which shipped at `count = 4` because an audition
found `count = 3` overflows into a near-continuous arpeggio on a dense
score, and which Phase 8's audition has since moved to `count = 3`, the
NES's true two-pulses-and-a-triangle roster. Phase 7 is done: that arpeggio
now plays in tune, and sounds like an arpeggio. Three things changed, and
the audition needed all three. An overflowing chord emits one event
carrying its semitone offsets instead of one 16 ms event per step, so the
envelopes run once across the figure rather than restarting sixty-two
times a second — before this, every step sounded a whole tone sharp on any
instrument with a `pitch_env`. That fixed the pitch and left the texture:
at one step per frame a two-note cycle alternates at 31 Hz, which the ear
hears as roughness rather than as notes, so the default step went to
48 ms. And members now fold into the octave above the lowest — ragtime's
widest overflow had been alternating F3 with A-flat4, an octave and a
fourth, nine times inside one event.

Folding costs something real: an overflowed note keeps its pitch class but
not its register. `test_every_source_note_is_heard` says so: a note excuses
itself only when its pitch class is genuinely sounding in the arrangement at
that moment, on any channel, arpeggio members included — not by checking the
source score, which would let two notes that both got dropped excuse each
other while the pitch class vanished from the output with nothing to catch
it.

Phase 8 is done: overflow is no longer folded into an arpeggio
unconditionally. Three rules judge it first. A leftover whose pitch class is
already sounding is dropped — it adds nothing the ear can hear. What
survives becomes an arpeggio only if it names a cycle of three or more
distinct pitches; two notes alternating is a trill, not a chord, so the
leftover is dropped instead and the channel keeps its own note. And where
that would cost a chord its only third, and the channel's own note is a
doubling of something already sounding, the third takes that note's place
rather than being lost. The measured effect is large: the chorale's carrier
arpeggiated through 92.2% of the piece before this and 0.0% after; the
minuet goes from 66.7% to 0.0%; ragtime falls from 59.8% to 26.1% at
`count = 3` — which is what `nes-tight` now ships — from 41.5% to 2.1% at
`count = 4`, and from 15.6% to 2.1% at the `count = 5` default. None of
that is free: dropping notes loses harmony the previous implementation
never lost, since it kept every note. A handful of chords per fixture now
sound without a third that used to be there — seven on the chorale and four
on ragtime at `count = 3`, five on ragtime at `count = 4`, none on the
minuet or on ragtime at `count = 5`.

Auditioned 2026-08-23 and accepted, which finishes the phase: the
`count = 5` default, `count = 4`, and `count = 3` on all three fixtures,
plus `nes-tight` at its own settings. The question Phase 8 left open —
whether a reduced texture sounds reduced or merely thin — came back
reduced. So `nes-tight` moves from `count = 4` to `count = 3` and is now
the honest two-pulses-and-a-triangle roster; the reason it sat at 4 was
that `count = 3` was not musical, and that is no longer true. One thing
the numbers did not predict: at `count = 3` the arp carrier moves from
`inner_a` to `counter`, so the preset's own `duty = 0.125` override is
what ragtime's remaining arpeggio sounds like.

Tail-wrapping is closed, not deferred. It had been carried since Phase 4b
pending an audition, on the rule that the loop cascade never modifies audio:
the echo still ringing when the loop end arrives is cut, reported as "echo tail
cut" rather than rejected, because whether it is audible is a call for a
person. Auditioned 2026-08-23 and the answer is no. The tail was isolated by
rendering only the events that begin before the loop end, untruncated, so
whatever sounds past `end_sec` is exactly what the loop discards: 0.38s at
-14.3 dB on the chorale, 0.15s at -11.6 dB on ragtime, and nothing at all on
the minuet, whose loop ends where nothing is ringing. That matches what 4b
measured, so nothing in Phases 5 through 8 moved it. Only `lead` carries an
echo tap, so in both cases the loss is a single repeat of the loop's last lead
note. Against an A/B that summed the discarded tail back onto the loop's own
head — what implementing tail-wrapping would sound like — the seam is not
audibly different, and neither version has an audible hole. The cascade keeps
its rule and the audio stays untouched.

One thing that fell out of the measurement: a wrap would not have clashed
either. The chorale's last lead F#4 is already in its opening chord and
ragtime's G#4 is an octave over its opening lead, which is what a loop that
comes around tends to do. So the null result is about audibility, not about
having dodged a harmonic problem.

Phase 9 is implemented: `[transform]`, with `transpose` and `tempo_scale`.
The decision that shapes the rest of it is that `tempo_scale` re-derives the
arrangement rather than replaying it faster. It scales `bpm` and every note
and bar time inversely, before the arranger sees the score, so the
duration-sensitive decisions move with it — the echo's beat, where the bars
fall, and which notes are long enough to waver. That last one is the visible
cost and it is deliberate: at `1.5` a note that used to clear the 500 ms
vibrato threshold no longer does, so the piece loses vibrato, and a slowed
piece gains it. What does not move is what was never derived from the tempo:
`arp.rate_ms`, `vibrato.rate_hz`, `vibrato.delay_ms`, and the threshold
itself are seconds in the file, and 48 ms in particular is a fact about the
ear that Phase 7 measured rather than a fact about the music.

`transpose` costs almost nothing by comparison, because the arranger has no
absolute pitch logic anywhere: top and bottom pinning, nearest-last-pitch
assignment, the reduction's pitch-class comparison, and the arpeggio's
octave folding are all relative or uniformly shifted. So arranging a
transposed score gives back the untransposed arrangement with every pitch
moved, and that invariant — asserted over whole events, not a pitch list —
is the load-bearing test. It also means the goldens never moved. A shift
that would push a note outside the playable band is refused rather than
folded back into it, naming the note, where it lands, and the largest shift
that would fit; folding would let a melody leap an octave mid-phrase, which
is the note soup voice-leading assignment exists to prevent. `render`
deliberately does not transform, so a convert at `+3` re-rendered under the
same config cannot land at `+6`.

**The audition is still owed, and it is what sets the two bounds.** C1 and
C8 are provisional taste rather than measurement — the same way Phase 7's
48 ms was set by ear — so the clips exist and the numbers are recorded in
`audition/transform/NOTES.md` but nothing has been listened to. What the
measurements do say: the control is byte-identical to a plain convert, no
clip contains a quiet window, the loop picked bars 1-8 in every variant
including all three tempo scales, and the envelope-frame risk is real but
narrow — at `tempo_scale = 4.0` two of the minuet's 156 events fall under
one 16.7 ms envelope frame, while at `1.5` none do. If the audition
disagrees with C1 or C8, the constants move and this paragraph's numbers
are wrong rather than its design.

Design documents and per-phase implementation plans live in
`docs/superpowers/`.
