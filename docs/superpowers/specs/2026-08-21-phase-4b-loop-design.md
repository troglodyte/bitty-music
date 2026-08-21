# Phase 4b — Loop: selection, trim, and the intro/loop split

**Date:** 2026-08-21
**Status:** Approved, ready for implementation planning
**Parent spec:** `2026-08-20-bitty-music-design.md`
**Predecessor:** `2026-08-21-phase-4a-structure-design.md`

## Goal

Choose where the music loops, cut the score down to the part worth
looping, and record the decision where the rest of the pipeline can read
it.

4a read the structure the composer wrote and reported it. 4b acts on that
report: it turns repeat marks and section boundaries into a loop, verifies
the loop does not click or sever a phrase, and writes `loop` into the
arrangement. This is the second and final half of Phase 4.

| | Delivers |
|---|---|
| **4a** | Bar timeline at ingest, `analyze`, `bitty sections` |
| **4b** (this spec) | `loop.py`, the cascade, `--bars` / `--loop-from` / `--split`, the arrangement's `loop` field |

Where 4a changed nothing downstream of `Score`, 4b is where output
artifacts change: the golden arrangements gain fields and `convert` can
emit a second and third file.

## Non-goals

- **Self-similarity search.** The parent spec's third cascade tier —
  `librosa.segment.recurrence_matrix` over rendered audio — is excluded.
  It buys automatic loop finding on pieces with no marks at all, at the
  cost of a large dependency and an analysis step that only works on
  audio. Pieces that resolve to nothing get no loop and a message saying
  so; `--loop-from` is the answer for those.
- **Per-bar feature vectors.** Deferred with the tier that needed them.
- **`--expand-repeats`.** Playing repeats out changes ingest's note
  timeline and every golden file, and forces `--bars` to disambiguate
  printed from played numbering. Its own change, later.
- **`--play`.** Auditioning goes through a written WAV and `aplay`. No
  runtime audio-output dependency.
- **Target-specific file layout.** `convert --split` writes
  `stem_intro` / `stem_loop`. Which engine wants which artifacts, and the
  `music.ron` manifest, belong to Phase 5's target registry.
- **Config precedence.** `MIN_LOOP_BARS` and the seam threshold are
  module constants until Phase 5 brings TOML.

## The stage

The parent spec names the stage "loop start/end selection, trim", and
`loop.py` owns both halves. It is the only new module.

```
ingest -> analyze -> [trim] -> arrange -> render -> [choose] -> artifacts
             |          |                              |
             +----------+-- loop.candidates() ---------+
```

Selection splits in two because its two halves need different things.
Candidate generation is symbolic and runs before `arrange`. Verification
needs rendered audio, so it runs after `render`. The parent spec's diagram
puts `loop` wholly before `synth`; this is the one place 4b departs from
it, and the reason is that a click is an audio property and cannot be
measured anywhere else.

The cost of that departure is one render, not N. Every candidate is a pair
of offsets into the *same* trimmed, arranged, rendered buffer, so falling
through the cascade costs metric evaluation only.

## Data contracts

### `LoopCandidate` — in `loop.py`

```python
@dataclass(frozen=True)
class LoopCandidate:
    first_bar: int   # printed numbers, inclusive
    last_bar: int
    start: float     # seconds, rebased to the trimmed score
    end: float
    source: str      # "repeat" | "section" | "manual"
```

`source` exists to be printed. It is what makes `(repeat marks, seam ok)`
in the `sections` output an explanation rather than an assertion.

### `Loop` — in `arrangement.py`

```python
@dataclass(frozen=True)
class Loop:
    start_sec: float
    end_sec: float
```

Two floats, matching the parent spec's JSON exactly. `source` and the
measured seam do not serialize: they explain a decision already made, and
the arrangement is the hand-edit surface, where an extra field invites
someone to change it and expect something to happen.

### `Arrangement` gains one field

```python
@dataclass(frozen=True)
class Arrangement:
    meta: dict
    channels: tuple[Channel, ...]
    loop: Loop | None = None
```

`None` means no loop was found, and serializes as `"loop": null`. `meta`
also gains `"bars": [first, last]` — the printed range the arrangement
covers — which the parent spec's example already shows.

`from_json` keeps the existing drop-unknown-fields discipline, so an
arrangement from an older build loads with `loop` absent rather than
failing.

Both additions change all three golden files. One regeneration, read as a
diff per the README rule.

## The cascade

In preference order. Each tier is a generator of candidates, not a
decision; the seam check decides.

### Manual

`--loop-from N` produces exactly one candidate, `source="manual"`,
spanning bar N through the last bar of the selection. The parent spec:
manual selection overrides the cascade entirely. That includes rejection —
a manual loop is returned even when both seam tests fail. The measured
seam is still printed, so the tool reports what it thinks without
overruling the person who typed the number.

### Tier 1 — repeat marks

Each start-repeat / end-repeat pair in `Score.bars` becomes a span. An
unpaired mark closes at the nearest edge, in both directions: an end
repeat with no preceding start repeats from bar one, and a start repeat
with no following end repeats to the last bar. Both are the notational
reading — the minuet fixture is exactly the second case, `|:` at bar 9
under a final barline at bar 16 with no `:|` written, which every player
reads as repeating to the end.

Ordered longest first: a loop wants the substantial repeated body, not an
incidental four-bar echo. Ties break earlier-first.

This is the tier most sourced pieces resolve at, and the most trustworthy,
because it is the composer stating where the music comes back around.

### Tier 2 — section suffixes

For each section index k, the candidate spanning section k through the
**last** section. k ascending.

Two decisions are packed in there. **Suffixes, not arbitrary spans:** a
loop ending before the piece does means the tail material never plays
again once the loop starts, which is a strange thing to choose on a
listener's behalf. **k=0 first:** the preferred answer is that the piece
loops cleanly on itself, with no intro at all. An intro appears only when
the head of the piece is what breaks the seam, which is exactly when an
intro is the right description of it.

### Floor

Candidates shorter than `MIN_LOOP_BARS = 8` are dropped from both tiers.
This is the parent spec's `[loop] min_bars`, hard-coded until Phase 5.

### Nothing left

An empty candidate tuple is a legitimate outcome. No `loop` field is
written and `convert` says why. A silently bad loop shipped into a game is
worse than no loop.

## The seam check

Two tests, matching what the parent spec names: reject candidates that
click, or that cut a note mid-phrase.

### Test 1 — click, in the audio domain

The obvious metric is wrong here, and the reason is worth stating because
it is a trap specific to this project.

A pulse wave jumps between +A and −A every half period. An
instantaneous full-amplitude step is *ordinary signal*, not a defect. Any
absolute threshold on the splice step would reject every loop in a
square-wave piece, and would do so for a reason that has nothing to do
with whether the loop is audible as a join.

So the step is normalized against the piece's own behaviour:

```
ordinary = percentile(abs(diff(audio, axis=0)), 99.9)
splice   = max(abs(audio[loop_start] - audio[loop_end - 1]))
```

A candidate fails when `splice > ordinary * SEAM_RATIO` — when the join
does something the music itself never does. Self-calibrating per piece,
one free constant, no absolute dB value to guess at. `SEAM_RATIO = 1.0`;
see "Calibration" for the measurements behind it.

### Test 2 — cut phrase, in the event domain

A **dry** event whose sounding span crosses `loop_end` fails the
candidate, unless the same pitch is also sounding at `loop_start` — in
which case the splice continues the note rather than severing it.

An event ending *exactly* at `loop_end` does not cross. Onset times are
floats, so the comparison is `e.t + e.dur > loop_end + EPSILON`, matching
`arrange.EPSILON = 1e-6`. Written the other way it counts every final
note as severed, which is wrong on every bar-aligned candidate there is.

### The echo tail is reported, not rejected

An earlier draft of this spec folded the echo tail into Test 2: effective
end `e.t + e.dur + echo.delay_sec`. Measurement killed it. The lead's
final note echoes 0.38–0.45 s past the loop end on chorale, on ragtime,
and on the minuet's second half — so that clause rejects every candidate
on two of the three fixtures, and the feature ships dead.

The clause was pointing at something real. The tail measures −11 to
−14 dB against the body RMS, which is audible: each loop cycle drops the
final note's echo. But every loop in a piece with echo has one, so
rejection is the wrong response. The seam report prints the tail level;
the cascade ignores it.

The alternative — wrapping the tail, adding `audio[loop_end:loop_end+tail]`
into the head of the loop region so the echo sounds over the loop start as
it would on a real repeat — is musically the better answer and is
deliberately deferred. It modifies rendered audio, which this phase does
not do. Revisit it after auditioning what the unwrapped loop sounds like.

The two tests are complementary by domain: the first sees what the
synthesizer did, the second sees what the music meant.

### Selection

`choose(candidates, audio, arrangement, sample_rate) -> Loop | None`
walks the candidates in order and returns the first that passes both
tests, or `None`. Manual candidates return regardless.

## CLI surface

```
bitty convert score.musicxml --bars 25-64 --loop-from 33 --split
```

| Flag | Effect |
|------|--------|
| `--bars N-M` | Trim to printed bar numbers. Notes and bars outside are dropped, times rebase to zero, bar numbers stay as printed. |
| `--loop-from N` | Manual loop start. Loop end is the last bar of the selection. Bypasses rejection. |
| `--split` | Also write `stem_intro.*` and `stem_loop.*`. |

`--split` with no loop found is a hard error, not a degraded single file.
Asking for a split is asking for a loop; getting one file back and a
warning is the kind of thing that gets missed in a build script.

When `loop_start == 0` there is no intro, so only `stem_loop.*` is
written, and the output says so rather than leaving a missing file to be
noticed later.

`--split` discards audio past `loop_end`. With suffix candidates that is
nothing. A tier-1 repeat span in the middle of a piece leaves a tail that
survives in the single file and not in the split pair. Documented
behaviour, not a defect to fix here.

`bitty render` honours `--split` too: an arrangement carrying a loop can
be split without re-analysing anything. It falls out of the same helper.

### `bitty sections` gains the auto-loop line

```
bitty sections tests/fixtures/minuet.mxl

minuet  ·  q=120  ·  16 bars  ·  24.0s

  A   bars   1-8    3/4   G major    0:00.0    12.0s   repeat
  B   bars   9-16   3/4   D major    0:12.0    12.0s   repeat

  auto-loop pick: bars 1-8  (repeat marks, seam ok)
```

One blank line, then the pick, at the same indent as the rows. On this
fixture both repeat spans are exactly at the 8-bar floor, so the
longest-first ordering ties and the earlier span wins.

Printing a verified seam means `sections` must arrange and render, which
turns a structural report into a full pipeline run. Measured on the
fixtures: ingest 0.02–0.03s, arrange under 0.01s, render 0.08–0.12s for
16–24 seconds of audio — roughly 5 ms per second of audio, so a
five-minute score adds about 1.5s.

That is worth paying. A printed pick that differs from what `convert`
would actually choose is a worse failure than a slow report. If a real
score proves slow, a `--quick` flag printing the unverified symbolic pick
can be added later.

## Testing

### `tests/test_loop.py`

**`trim`** — notes and bars outside the range dropped; times rebased to
zero; printed bar numbers unchanged; a note beginning before the range and
sustaining into it excluded, matching the "begins in" rule 4a's key
detection already uses.

**`candidates`** — repeat pairs become spans, longest first; an end repeat
with no start repeats from bar one; spans under 8 bars dropped; sections
fall through as suffixes with k ascending; a score with no marks yields
the whole-piece candidate; `--loop-from` yields exactly one manual
candidate.

**Seam, click** — a buffer whose splice step exceeds its own 99.9th
percentile is rejected; a pulse train spliced at a period boundary passes
despite full-amplitude edges. The second is the test that would have
caught an absolute-threshold metric, and it exists for that reason.

**Seam, cut phrase** — an event sustaining across the loop end fails; the
same pitch also sounding at loop start passes; an event ending exactly at
the loop end passes; a channel with echo fails when only the tail crosses.

**`choose`** — falls through a failing candidate to the next; returns
`None` when all fail; returns a manual candidate that fails both tests.

### `tests/test_cli.py` additions

`--bars` narrows the arrangement; `--loop-from` overrides the cascade;
`--split` writes the two expected filenames; `--split` with no loop exits
non-zero; `loop_start == 0` writes only the loop file; `sections` prints
the auto-loop line.

### Goldens

All three fixtures regenerate for `loop` and `meta.bars`, reviewed as a
diff. Round-trip: `bitty render` on an arrangement carrying a loop
preserves it byte-identically.

### Calibration — measured, 2026-08-21

`SEAM_RATIO` is the only free number, since the percentile normalizes per
piece. It was measured before this spec was finalized, across every
candidate the cascade generates on all three fixtures.

| Population | Ratio |
|---|---|
| Bar-aligned candidates (all fixtures, every tier) | 0.02 – 0.38 |
| Arbitrary splice points, 400 random pairs per fixture | median 0.54–0.80, p90 1.07–1.67, max 2.97 |
| Fraction of arbitrary splices above 1.0 | 15% – 40% |

**`SEAM_RATIO = 1.0`** — roughly 2.6× headroom above the worst real
candidate, while still rejecting a large share of arbitrary joins. Per
fixture, `ordinary` (the 99.9th-percentile adjacent-sample step) is
chorale 0.266, minuet 0.420, ragtime 0.455.

Dry-note crossings on bar-aligned candidates: **zero**, on every fixture,
at every tier. Test 2 guards without misfiring.

### Audition

A WAV of the loop file concatenated with itself two or three times, handed
over for `aplay`. It is the only test that answers whether the loop
actually works.

## Risks

- **A piece with no usable marks gets no loop.** Accepted, and the reason
  `--loop-from` exists. The parent spec already expects manual selection
  to be the path for a meaningful share of tracks.
- **`SEAM_RATIO` is tuned on three fixtures.** Three pieces is a small
  population to draw a threshold from. Mitigated by choosing headroom
  rather than a tight fit, and by the fact that a wrong rejection is
  recoverable with `--loop-from` while a wrong acceptance is audible.
- **Test 2 rejects on any sustained dry note crossing the boundary.** A
  piece with a pedal bass under a section boundary may lose candidates it
  arguably should keep. Bar-aligned loop points usually land where notes
  end — measured zero crossings across all three fixtures — so when one
  does cross, that is a real seam problem rather than a false alarm.
- **Every loop drops the final note's echo**, at −11 to −14 dB. Accepted
  for this phase and reported rather than hidden. Tail-wrapping is the
  fix if the audition says it matters.
- **Selection sees only the trimmed score.** `--bars` narrows what the
  cascade can consider. Intentional — it is a manual instruction — but a
  too-narrow `--bars` can leave nothing above the 8-bar floor, which
  reports as no loop found.

## What Phase 5 inherits

- `Arrangement.loop` — the offsets every target needs, in the JSON.
- `meta.bars` — which printed range an artifact covers.
- `--split`'s intro/loop pair, ready to become the `bevy` target's
  artifacts while `bevy-kira` reads the same `loop` field as offsets.
- `MIN_LOOP_BARS` and `SEAM_RATIO`, the first two constants wanting
  `[loop]` in TOML.
