# Phase 5a — Targets: the Render contract and the emitter registry

**Date:** 2026-08-21
**Status:** Approved, ready for implementation planning
**Parent spec:** `2026-08-20-bitty-music-design.md`
**Predecessor:** `2026-08-21-phase-4b-loop-design.md`

## Goal

Turn a rendered buffer and a loop decision into the files a game engine
actually loads.

Phase 4 ended with the loop recorded in the arrangement and a `--split`
flag that writes an intro/loop pair. That flag is the shape of one
engine's needs hard-coded into the CLI. 5a replaces it with a contract and
a registry: `Render` carries audio plus loop offsets, and a plain dict of
functions turns that into per-engine artifacts.

Phase 5 splits in two because its halves share nothing but the CLI.

| | Delivers |
|---|---|
| **5a** (this spec) | `Render`, the `TARGETS` registry, `bevy` / `bevy-kira` / `generic` emitters, `music.ron` assembly, `--target` |
| **5b** | TOML precedence, named presets, and the scattered constants that want configuring |

## Non-goals

- **Config.** Every constant this phase touches stays a module constant.
  5b brings TOML.
- **The `unity` and `godot` targets** from the parent spec's table. Neither
  has a consumer to shape it, so the `.import` snippet and the tag
  conventions would be guesses. `generic` already writes the
  `LOOPSTART`/`LOOPLENGTH` comments both engines read, which is most of
  what they would be.
- **Verifying the RON compiles against real Rust.** See Risks.
- **Tail-wrapping.** Still deferred from 4b, still pending an audition.
- **Changing what the synth produces.** The audio bytes this phase writes
  are the bytes 4b wrote.

## The consumer

There is a real Bevy project on the other side of this, using
`bevy_audio` — the rodio-backed built-in. rodio can only loop a whole
file. That fact decides three things:

- `bevy` is the **default target**. The intro/loop pair is not one option
  among several; it is how the actual game loops music.
- The pair must be two complete files. No offsets, no seeking.
- `bevy-kira` is still built, because the parent spec commits to trying
  both, and because once the registry exists it is a thirty-line emitter.
  It is not the default and nothing depends on it yet.

## Data contracts

### `Render` — in `synth.py`

```python
@dataclass(frozen=True)
class Render:
    audio: np.ndarray            # float32 [n_samples, 2]
    sample_rate: int
    meta: dict                   # arrangement.meta, verbatim
    loop_start_sample: int | None = None
    loop_end_sample: int | None = None
```

Field names are the parent spec's. Two changes from it:

**The loop is optional.** The parent spec assumes every render has one.
A piece whose cascade found nothing is still worth emitting as a one-shot
cue, so both fields default to `None`. `__post_init__` rejects one-set-
one-`None`: a half-specified loop is a bug, and catching it at
construction beats catching it in an emitter.

**It lives in `synth.py`, not its own module.** `synth.py` is the one file
that legitimately owns the sample-rate boundary — `SAMPLE_RATE` is already
there, and seconds-to-samples is the conversion `Render` exists to
perform. A `render.py` would also read confusingly beside both
`synth.render()` and the `bitty render` command.

### `Render.of` — the only constructor

```python
@classmethod
def of(cls, arrangement: Arrangement, audio: np.ndarray,
       sample_rate: int = SAMPLE_RATE) -> Render: ...
```

Converts `arrangement.loop` from seconds to samples, clamping the end to
`len(audio)`, and copies `arrangement.meta` through. This is where the
arithmetic `cli._write_split` currently does inline moves to.

`synth.render()` keeps returning a bare array. It is a pure function of
an arrangement and a sample rate, its property tests depend on that, and
wrapping its return would buy nothing.

## The registry

```python
Emitter = Callable[..., list[Path]]

TARGETS: dict[str, Emitter] = {
    "bevy": _emit_bevy,
    "bevy-kira": _emit_bevy_kira,
    "generic": _emit_generic,
}
```

A plain dict of function values, as the parent spec specifies: no base
class, no factory. `TARGETS` is the single source of truth for what
`--target` accepts — the CLI validates against its keys rather than
against a parallel enum.

### One deviation from the specified signature

The parent spec writes `emit(render, out_dir, name) -> list[Path]`. The
actual signature is:

```python
def emit(render: Render, out_dir: Path, name: str, *,
         audio_format: str = "ogg") -> list[Path]: ...
```

`--wav` is orthogonal to target choice — it exists so a converted piece
can be auditioned through `aplay`, which renders Ogg as static — and every
emitter has to honour it. Threading it through `Render.meta` or a module
global would hide a parameter that is genuinely a parameter.

### A second deviation: the sidecar

The parent spec says all targets also write the sidecar JSON. The CLI
keeps writing it instead, exactly as it does today. Output for `convert`
is identical either way, it avoids the same six lines in three emitters,
and it keeps `emit()` about engine artifacts. `bitty render` continues not
to write one, since it was handed one.

## The module

One new flat file, `src/bitty/targets.py`, following the repo's
one-module-per-stage layout. It owns:

- `Render`-to-file writing — `cli._write_audio` moves here, so the CLI
  stops knowing about `soundfile` and file extensions.
- The three emitters and the `TARGETS` dict.
- RON fragment writing and the `music.ron` assembly function.
- Vorbis comment tagging.

`cli.py` loses `_write_audio` and `_write_split` and gains `--target`. It
calls `targets.assemble()` after the emitter returns; the function lives
in `targets.py`, the call site is the CLI.

## What each target emits

Every emitter returns the paths it wrote, which is what the CLI prints.

### `bevy` — default

| Loop state | Audio | Fragment entry |
|---|---|---|
| Loop starting after 0:00 | `name_intro.ogg`, `name_loop.ogg` | `intro` + `loop_` |
| Loop starting at 0:00 | `name_loop.ogg` | `loop_` only |
| No loop | `name.ogg` | `full` |

Audio past `loop_end_sample` is dropped, as `--split` already does. With
the suffix candidates the cascade prefers that is nothing.

### `bevy-kira`

`name.ogg` — the whole piece, untrimmed — plus a fragment carrying
`loop_start` and `loop_end` **in seconds**. Kira's loop regions are
time-based, so this target is the one place the offsets do not become
samples. With no loop, both keys are omitted.

### `generic`

`name.ogg` plus `LOOPSTART` and `LOOPLENGTH` Vorbis comments, written
with `mutagen`:

```
LOOPSTART = loop_start_sample
LOOPLENGTH = loop_end_sample - loop_start_sample
```

Samples at the file's own rate — the RPG-Maker convention that Unity and
Godot both read. libsndfile writes only a fixed set of Vorbis fields
(title, artist, comment, and friends), so custom keys need `mutagen`. It
is pure Python with no binary build.

With `--wav`, there is nowhere to put the comments. The target writes the
audio and reports that the loop lives in the sidecar only, rather than
failing.

## `music.ron`

### Fragments, then assembly

`bevy` and `bevy-kira` each write `name.<target>.ron` holding one map
entry. After the emitter returns, the CLI assembles every
`*.<target>.ron` in the output directory into `music.ron`.

`generic` writes no fragment and no manifest — its loop lives in the
Vorbis comments and the sidecar, which is the whole point of the target.
Assembly is skipped when the chosen target produces no fragments, so a
`generic`-only output directory never grows a `music.ron`.

```
out/
  minuet.bevy.ron        <- fragment, one entry
  ragtime.bevy.ron
  music.ron              <- header + sorted fragments + footer
```

Assembly is a glob, a sort by name, and a concatenation. No RON parser on
either side of the round trip, and the property that matters holds
structurally: **converting one piece cannot drop another's entry**,
because no step ever reads and rewrites a shared file.

Fragments are named per target rather than a shared `name.music.ron` so
that running two targets into one directory cannot silently clobber. If
you do run two, you get two fragment sets and a `music.ron` for whichever
target ran last — deterministic, and one output directory is meant to
serve one engine anyway.

Entries are sorted by key so the manifest is byte-stable across runs.

### The `bevy` shape

```ron
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

`loop_` because `loop` is a reserved word in Rust. `bars` is the printed
range the artifact covers, which 4b left in `meta.bars` for exactly this.

**`meta` is not guaranteed complete.** `arrange` writes `bars` only when
the score had bars (`arrange.py:76`), and `bitty render` accepts a
hand-edited arrangement that may be missing any key. The emitter therefore
omits `bars` when `meta` has none, and falls back to the file stem for
`title` and to `0.0` for `bpm`. A missing key must not crash an emit.

The matching Rust side:

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

Three `Option`s of which exactly one combination is valid is a weak type.
A `Playback` enum with `Looping { intro, loop_ }` and `OneShot { full }`
variants models it properly and RON serializes it as
`playback: Looping(intro: "...", loop_: "...")`. The flat shape is
specified here because it is what was reviewed and approved; adopting the
enum is a one-line change to the emitter's format string if the Rust side
prefers it.

### The `bevy-kira` shape

```ron
"minuet": (
    title: "Minuet in G",
    file: "minuet.ogg",
    loop_start: 12.5,
    loop_end: 62.5,
    bpm: 88.0,
    bars: (1, 32),
),
```

## CLI surface

`--split` is **removed**. Asking for an intro/loop pair is asking for the
`bevy` target, and two code paths writing the same two files would drift.

| Flag | Effect |
|---|---|
| `--target NAME` | `bevy` (default), `bevy-kira`, or `generic`. Validated against `TARGETS` keys. |
| `--wav` | Write WAV instead of Ogg, for auditioning. Orthogonal to `--target`. |

Both `convert` and `render` take `--target`. `sections` is unchanged.

```
bitty convert minuet.mxl -o out
  out/minuet_intro.ogg  (4.1s)
  out/minuet_loop.ogg  (24.0s)
  loop: bars 9-32  (repeat marks, seam ok)
  out/music.ron
  out/minuet.arrangement.json
```

### Error handling

- **Unknown `--target`** — `typer.BadParameter` listing the valid names,
  raised before ingest so nothing is parsed or written.
- **No loop, `bevy`** — a one-shot entry. Not an error. A piece with no
  loop point is a legitimate cue, and the manifest can say so.
- **No loop, `generic` / `bevy-kira`** — the file is written and the loop
  keys are omitted. Same reasoning.

The one hard failure `--split` had — refusing to write without a loop — is
deliberately dropped, because the manifest can now express the absence.

## Testing

### `tests/test_targets.py`

- **Registry:** every name in `TARGETS` emits a non-empty path list for a
  fixture `Render`, and every path it names exists on disk. This is the
  test that catches a new target wired in wrong.
- **`bevy` across three loop states:** loop after zero (intro + loop),
  loop at zero (no intro written), no loop (single file, `full` entry).
- **Assembly, the load-bearing one:** emit piece A, emit piece B, assert
  `music.ron` contains both entries and that A's survived B's write.
  Then re-emit A and assert B still survives.
- **Sorted and stable:** emitting in either order produces byte-identical
  `music.ron`.
- **`generic`:** `LOOPSTART`/`LOOPLENGTH` read back out through `mutagen`
  and match the `Render`'s samples. `--wav` writes audio and no tags.
- **`bevy-kira`:** `loop_start`/`loop_end` are the arrangement's seconds,
  not samples.
- **RON text** against a golden fixture, so a format change is a readable
  diff rather than a silent one.
- **Incomplete `meta`:** a `Render` whose meta lacks `bars`, `title`, and
  `bpm` still emits, omitting `bars` and falling back for the other two.
- **`generic` writes no `music.ron`** into a directory that contains none.

### `tests/test_synth.py` additions

- `Render.of` converts seconds to samples and clamps the end to the
  buffer length.
- `__post_init__` rejects one-set-one-`None` in either direction.
- A loop of `None` survives the round trip as `None`.

### `tests/test_cli.py` changes

- The `--split` tests are rewritten as `--target bevy` tests.
- Unknown `--target` exits non-zero and names the valid targets.
- `--wav` with each target.

### Goldens

`tests/goldens/*.arrangement.json` are untouched. This phase does not
change what `arrange` produces or what `synth` renders.

## Risks

- **Nothing here proves the RON parses in Rust.** The test suite is
  Python; it can only check the text matches what we intended to write.
  Mitigated by a golden fixture and by putting the exact `serde` structs
  in the README so they can be pasted into the game and compiled. The
  phase's audition step is therefore "build the real project against the
  generated manifest", not "listen".
- **Removing `--split` is a breaking CLI change.** Accepted: the tool has
  one user, the replacement is a default rather than a flag, and leaving
  both would guarantee they drift.
- **`mutagen` is a new dependency for one target's metadata.** Small,
  pure Python, and the parent spec already named it. If `generic` were
  cut, the dependency would go with it.
- **The flat `Track` shape lets an invalid combination be written.**
  Nothing in the emitter can produce one, but a hand-edited manifest can.
  The `Playback` enum closes it; see above.
- **`bevy-kira` has no consumer.** It is built on the parent spec's
  commitment to trying both, and is the target most likely to be wrong in
  a way nothing catches. Its tests assert our own format, not kira's.

## What 5b inherits

- A CLI where every write goes through one mechanism, so a config-
  resolved output setting has one place to land.
- `MIN_LOOP_BARS`, `SEAM_RATIO`, `ECHO_LEVEL`, `ARP_STEP_SEC`, the
  `lfo` constants, and the `voices` roster — still module constants, now
  the whole remaining list.
- `TARGETS`, whose default may become a `[targets]` config key rather
  than a flag default.
