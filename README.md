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

### Milliseconds in the file, seconds in the code

Every key ending in `_ms` — `arp.rate_ms`, `vibrato.delay_ms`,
`vibrato.min_note_ms`, `voices.<role>.vibrato_delay_ms` — is milliseconds
in TOML and seconds once loaded into `Config`. The conversion happens once,
in `config.py`, so neither the file format nor the rest of the code has to
carry the other side's convention.

### Presets

Two ship in `presets/`, selected with `--preset NAME`:

- **`nes-tight`** — closer to the hardware: `count = 4`, no echo, a mono
  image (every voice's pan pinned to `0.0`), and vibrato that arrives
  later and shallower. Four channels, not the NES's true
  two-pulses-and-a-triangle melodic roster — three pulses sound at once
  here, which no NES can do. `count = 3` would be the honest roster, but
  an audition found the arranger folds too much of the piece onto the
  lone middle voice's arpeggio to sound musical; see the caveat under
  `[voices] count` below.
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
arp, echo, loop, output, vibrato, voices`) and an unknown `[voices.<role>]`
role (`unknown voice; the roster is lead, counter, inner_a, inner_b, bass`)
or key.

## Status

Phase 4 is done: ingest, synthesis, the reduction, articulation, structural
analysis, and looping — the loop cascade, `--bars` and `--loop-from`, and the
intro/loop split. Phase 5 is done, both halves: 5a's `Render` contract, the
`bevy`, `bevy-kira`, and `generic` targets, and `music.ron` assembly; 5b's
TOML config, the precedence cascade, and the two shipped presets. Phase 6 is
done: `[voices] count`, narrowing the roster down to as few as three
voices, and `nes-tight` at `count = 4` — closer to the NES's true
two-pulses-and-a-triangle roster than the five-voice default, though not
that roster itself; an audition found `count = 3` overflows into a
near-continuous arpeggio on a dense score. Phase 7 is done: that arpeggio
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
not its register. `test_every_source_note_is_heard` says so, and matches
arpeggio members by pitch class rather than pitch.

`nes-tight` stays at `count = 4`. Whether `count = 3` is musical is a
question about the reduction rather than the arpeggio, and is still open.

Deliberately still ahead: `[transform]` (`transpose`, `tempo_scale`) as its
own phase with its own auditions, tail-wrapping, deferred since Phase 4b
pending an audition of its own, and a musical `count = 3` — the honest
two-pulse NES roster, blocked on arranger work to soften the overflow.

Design documents and per-phase implementation plans live in
`docs/superpowers/`.
