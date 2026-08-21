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

### `bitty render` — edited JSON in, audio out

```bash
bitty render out/score.arrangement.json --wav
```

Re-renders an arrangement, skipping score analysis entirely. This is the loop
you want when you are tuning a passage: convert once, then edit the JSON and
render as often as you like. `foo.arrangement.json` renders to `foo.ogg`, not
`foo.arrangement.ogg`.

Same `-o` and `--wav` options as `convert`.

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
  "meta": { "title": "chorale", "bpm": 120.0 },
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
  ]
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

Phases 1–3b are done: ingest, synthesis, the reduction, and articulation.
Phase 4 picks up structure — section analysis and looping.

Design documents and per-phase implementation plans live in
`docs/superpowers/`.
