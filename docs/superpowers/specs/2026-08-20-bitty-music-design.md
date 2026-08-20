# bitty-music — Design

**Date:** 2026-08-20
**Status:** Approved, ready for implementation planning

## Goal

An offline command-line tool that converts public-domain classical scores
(MusicXML, MIDI) into looping chiptune audio for a Bevy game.

The tool transcribes faithfully — same notes, same tempo — and renders them
with chiptune voices. It does not compose. Its one liberty is finding or
accepting a loop point so the result is usable as game music.

## Non-goals for v1

- Optical music recognition. Sources are structured files only.
- Added drum grooves, tempo manipulation, or reharmonization.
- Tracker module export. The JSON intermediate keeps that option open.
- Any GUI.
- A runtime synthesizer. All audio is rendered ahead of time.

## Sources

Public-domain MusicXML and MIDI from IMSLP, Mutopia, and KernScores. All
tooling is open source.

The pipeline suits music with clear voice structure and sectional form —
hymns, dances, chorales, minuets, character pieces. It degrades on dense
romantic piano writing, where eight simultaneous notes reduce poorly and
loop points are rare. This is a sourcing constraint, not a bug to fix in
the arranger.

## Fidelity target

Chiptune timbres without strict hardware channel limits. Five sounding
voices plus an echo, bandlimited oscillators, 44.1 kHz stereo. Recognizably
8-bit, but cleaner and more defined than real hardware.

## Pipeline

Six stages, one module each:

```
score.musicxml / .mxl / .mid
   |
   +- ingest    music21 -> Score: notes, tempo map, time sig, repeat marks
   +- analyze   key detection, phrase and section boundaries
   +- arrange   voice reduction -> Arrangement        <-- JSON intermediate
   +- loop      loop start/end selection, trim
   +- synth     Arrangement -> float32 audio
   +- targets   engine-specific artifacts
   |
   +-> out/piece_intro.ogg, out/piece_loop.ogg, out/piece.arrangement.json
```

Everything upstream of `Arrangement` is musical analysis. Everything
downstream is signal processing. The boundary is a plain JSON document,
which makes it the hand-edit surface, the test-fixture surface, and the
future tracker-export surface.

## Data contracts

### Score (internal, post-ingest)

Normalized note list with absolute times in seconds and in beats, a tempo
map, time signatures, key, and the score's written bar numbering including
repeat marks.

### Arrangement (JSON, the spine)

```json
{
  "meta": {"title": "...", "source": "...", "bpm": 88, "bars": [33, 64]},
  "channels": [
    {
      "role": "lead",
      "instrument": {"wave": "pulse", "duty": 0.5,
                     "volume_env": [15, 14, 13, 12, 12, 11],
                     "pitch_env": [2, 1, 0]},
      "events": [
        {"t": 0.0, "pitch": 74, "dur": 0.25, "vel": 13, "effects": {"vibrato": true}}
      ]
    }
  ],
  "loop": {"start_sec": 0.0, "end_sec": 62.5}
}
```

Times are seconds; pitch is MIDI note number; velocity is 0-15. The
arrangement is sample-rate-agnostic — loop points become sample offsets
only in `Render`.

### Render (in-memory, pre-target)

```
Render {
  audio: float32 [n_samples, 2]
  sample_rate: int
  loop_start_sample: int
  loop_end_sample: int
  meta: dict
}
```

This contract, not the dispatch mechanism, is what makes targets swappable.

## Stage: ingest

music21 parses MusicXML, compressed MusicXML, and MIDI into the Score
model. Preserves written bar numbers, repeat marks, double bars, key
signatures, and tempo markings.

## Stage: analyze

- Key detection (Krumhansl-Schmuckler, via music21).
- Section boundaries from double bars, key changes, repeat marks, and
  texture changes (voice-count and rhythmic-density shifts).
- Per-bar feature vectors — pitch-class histogram plus onset pattern — used
  later by the loop finder.

## Stage: arrange

Voice budget: five sounding channels plus one echo.

| Role    | Wave     | Duty  |
|---------|----------|-------|
| lead    | pulse    | 0.5   |
| counter | pulse    | 0.25  |
| inner A | pulse    | 0.25  |
| inner B | pulse    | 0.125 |
| bass    | triangle | —     |
| echo    | copy of lead, delayed and attenuated |

Noise is implemented but off by default, since v1 is faithful transcription.

### Voice-leading assignment

Each channel has an identity and a last-sounded pitch. Each new onset goes
to the channel whose previous pitch is nearest, with lead pinned to the top
line and bass to the bottom.

The naive alternative — re-sort each chord top-to-bottom and hand slot one
the highest note — produces a melody that teleports whenever an inner voice
briefly rises above it. Voice-leading assignment is the difference between
a recognizable tune and note soup.

### Arpeggio overflow

When more than five notes sound simultaneously, the leftovers fold into
inner B, which cycles through them at the arp rate (default 16 ms per
step). This is how real hardware fakes a chord in one channel, and the ear
hears it as harmony. Dense passages degrade into something idiomatic rather
than something broken.

### Articulation rules

- **Sustained notes get delayed vibrato.** Chip voices have no natural
  decay, so a held whole note is dead air, and classical writing is full of
  them. Applied to notes over `vibrato.min_note_ms`, after
  `vibrato.delay_ms`. This is the largest single contributor to sounding
  like real chiptune rather than a MIDI dump.
- **Dynamics quantize to 16 levels.** The coarse steps are the 8-bit
  texture; quantization is a feature, not a loss.
- **Ornaments survive literally.** Trills, grace notes, and mordents render
  as fast notes. Chiptune already sounds like this; no translation needed.

## Stage: loop

A cascade, cheapest and most trustworthy first:

1. **Repeat marks.** The composer stating where the loop is. Most sourced
   pieces resolve here.
2. **Section boundaries** from analyze.
3. **Self-similarity.** `librosa.segment.recurrence_matrix` over the
   rendered audio, snapped to bar boundaries from the tempo map. Preferred
   over a hand-rolled symbolic comparison: structure analysis is a solved
   problem with a maintained implementation, and reimplementing it is
   effort spent on someone else's finished work.
4. **Seam check.** Render the splice, measure discontinuity, reject
   candidates that click or that cut a note mid-phrase.

Manual selection overrides the cascade entirely. Material before the loop
start is emitted as an intro that plays once.

## Stage: synth

- **Bandlimited oscillators (PolyBLEP)** for pulse and saw. Naive squares
  alias audibly above ~1 kHz, and classical melodies live there. Roughly
  twenty lines for most of the defined sound.
- **Pulse** with switchable duty; **triangle** with optional 16-step
  quantization for NES bite; **noise** via seeded LFSR.
- **Volume envelopes as tracker-style step sequences** at 60 steps/second,
  not ADSR. Native chiptune idiom, matches the 16-level dynamics, readable
  in presets.
- **Pitch-envelope blip** on attack — the percussive "pew" of chip leads.
- **Mix** to float32 at 44.1 kHz with DC blocker, soft clipping, and light
  stereo spread across voices. The spread is inauthentic to mono hardware
  and bought deliberately: it is the cheapest clarity available on dense
  passages.
- **Deterministic.** The noise LFSR is seeded; identical input renders
  identical bytes.

## Stage: targets

Each target is a module exposing a plain function:

```python
def emit(render: Render, out_dir: Path, name: str) -> list[Path]: ...
```

collected in a dict registry keyed by `--target`. No base class, no
factory — a function value is the strategy.

The axis is real in the near term, and not primarily because of
cross-engine portability: `bevy_audio` (rodio-backed) can only loop an
entire file, while `bevy_kira_audio` supports loop regions. The same
arrangement therefore has to be emittable either as two files or as one
file plus offsets, and both will be tried.

| Target        | Artifacts |
|---------------|-----------|
| `bevy` (default) | `name_intro.ogg` + `name_loop.ogg`, plus `music.ron` manifest entry |
| `bevy-kira`   | `name.ogg` + loop offsets in `music.ron` |
| `unity`       | `name.ogg` with LOOPSTART/LOOPLENGTH Vorbis comments |
| `godot`       | `name.ogg` plus a `.import` snippet |
| `generic`     | `name.ogg` with Vorbis comments plus sidecar JSON |

All targets also write the sidecar JSON.

## Tuning and section selection

### Inspecting a score

```
bitty sections score.musicxml
  bars   1-16   A   D major  q=72  repeat    homophonic
  bars  17-32   B   A major  q=72            dense, 7 voices max
  bars  33-64   A'  D major  q=88  repeat    melody + walking bass
  auto-loop pick: bars 33-64  (repeat marks, seam ok)
```

### Selecting one

```
bitty convert score.musicxml --bars 33-64 --play
bitty convert score.musicxml --bars 25-64 --loop-from 33
```

`--bars` always refers to bar numbers **as printed in the score**;
`--expand-repeats` switches to the played-out ordering. `--play` renders
straight to the speakers, so auditioning a section is a two-second loop.

### Configuration

Resolved in order: built-in defaults, project config, per-piece config,
CLI flags.

```toml
[voices]     count = 5
             duties = [0.5, 0.25, 0.25, 0.125]
[echo]       on = true
             delay = "3/16"
             level = 0.4
[arp]        rate_ms = 16
             threshold = 5
[vibrato]    depth_cents = 25
             delay_ms = 300
             min_note_ms = 500
[dynamics]   levels = 16
[loop]       min_bars = 8
[transform]  transpose = 0
             tempo_scale = 1.0
```

Named presets (`--preset nes-tight`, `--preset lush`) provide starting
points on top of the defaults.

Beneath all of it: when no combination of knobs fixes a passage, edit
`arrangement.json` and re-render. Config tunes the policy; the JSON
overrules the result. Neither requires re-running analysis.

## CLI

| Command | Purpose |
|---------|---------|
| `bitty sections SCORE` | Print the structural map and the auto-loop pick |
| `bitty convert SCORE -o DIR` | Score to arrangement to audio |
| `bitty render ARRANGEMENT -o DIR` | Re-render after hand-editing |

The convert/render split is what makes hand-editing practical: fixing an
arrangement costs a JSON edit and a one-second re-render, not a full
re-analysis.

## Implementation phases

Each phase is sized for a single fresh session. The spec is the shared
context, so no phase needs to carry the previous one's conversation —
clear between them.

| Phase | Delivers |
|-------|----------|
| **0. Spike** | Dependency audit; buy-vs-build decision on the synth |
| **1. Walking skeleton** | ingest, trivial arrangement (top and bottom note only), plain square and triangle, WAV out — one recognizable tune |
| **2. Synth** | PolyBLEP, duty cycles, envelopes, echo, stereo, Ogg output, property tests |
| **3. Arranger** | Voice-leading assignment, arpeggio overflow, articulation rules, `arrangement.json` contract, golden tests, `bitty render` |
| **4. Structure** | analyze, `bitty sections`, loop cascade, `--bars` / `--loop-from`, intro and loop split |
| **5. Targets and config** | TOML precedence, presets, target registry, bevy / bevy-kira / generic emitters |

Ordering rationale: Phase 1 proves the pipeline while it is still small
enough to hold in one head. Phase 2 precedes the arranger because a buzzy
synth makes good and bad reductions sound identical — you cannot judge
Phase 3 without it. Phase 5 is deliberately last so the plumbing is shaped
by what the earlier phases learned.

Every phase ends with something audible, so each is a genuine stopping
point if priorities change.

**Split a phase when it grows.** If a phase is consuming more context than
a single session comfortably holds, or its plan exceeds roughly a dozen
steps, stop and split it rather than pushing through. Phase 3 is the
likeliest candidate — voice assignment, arpeggio overflow, and
articulation are three separable pieces of work sharing only the
`Arrangement` contract. Phase 2 splits along oscillators / envelopes /
mixing on the same principle. A phase that no longer fits is a planning
signal, not something to power through.

## Testing

Tests hang off the JSON intermediate.

- **Golden-file arrangement tests** for fixture scores spanning easy to
  hard: a hymn, a minuet, a fugue exposition. An arranger regression
  surfaces as a readable JSON diff rather than a changed audio hash.
- **Synth property tests:** FFT peak lands on the expected frequency,
  energy above the aliasing threshold stays low, output never clips,
  repeated renders are byte-identical.
- **Loop tests:** seam discontinuity below threshold, loop length within
  configured bounds, intro/loop split sample counts consistent.
- **Target tests:** each target emits the declared file set and its
  metadata round-trips.

No golden audio blobs. They are brittle and uninformative on failure.

## Dependencies

Python 3.11+, plus:

| Package | Role |
|---------|------|
| `music21` | Score parsing, key detection, repeat marks, section structure |
| `numpy` | Signal buffers and DSP |
| `librosa` | Structural segmentation for the loop-finder fallback |
| `soundfile` | Ogg Vorbis encoding via libsndfile — no ffmpeg subprocess |
| `mutagen` | Vorbis comment tags (LOOPSTART/LOOPLENGTH) |
| `sounddevice` | `--play` audition path |
| `typer` | CLI |

`tomllib` from the standard library reads config.

Deliberately **not** hand-rolled: audio encoding, metadata tag writing,
key detection, structural segmentation, and score parsing. Each has a
maintained library doing it better than a reimplementation would.

The synthesis stage is the one component specified as hand-written, and
that decision is provisional — Phase 0 verifies no suitable library or
headless renderer exists before any oscillator is written.

## Risks

- **The arranger is the hard part, not the synth.** Reduction quality on
  dense polyphony is the main quality risk. Mitigated by source selection,
  the arpeggio fallback, and the hand-edit path — not by expecting the
  algorithm to solve it.
- **Loop points may not exist** in freely-structured pieces. Mitigated by
  manual `--bars` selection, which is the expected path for a meaningful
  share of tracks.
- **music21 parse quality varies** across IMSLP contributors. Bad input
  should fail loudly at ingest rather than produce silent nonsense.

## Future work

Tracker export from the JSON intermediate; drum grooves and tempo
manipulation for a gamified mode; a Bevy-side crate that reads `music.ron`
and handles intro-to-loop transitions; additional engine targets.
