# Phase 5a — Targets — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a rendered buffer and a loop decision into the files a game engine actually loads, through a `Render` contract and a registry of emitter functions.

**Architecture:** `Render` joins audio, sample rate, meta, and loop offsets in samples, and lives in `synth.py` because that module already owns the sample-rate boundary. One new module `targets.py` holds a plain dict of emitter functions plus RON fragment writing and manifest assembly. `cli.py` stops knowing about file formats: it gains `--target`, loses `--split`, and delegates every write.

**Tech Stack:** Python 3.11+, numpy, soundfile, mutagen (new), typer, pytest. Run tests with `.venv/bin/pytest`.

**Spec:** `docs/superpowers/specs/2026-08-21-phase-5a-targets-design.md`

## Global Constraints

- **No config.** Every constant this phase touches stays a module constant. Phase 5b brings TOML.
- **The audio bytes do not change.** This phase changes which files get written, never what the synth produces. `tests/goldens/*.arrangement.json` must be untouched at the end of the phase.
- **`targets.py` uses `typer.echo` for progress lines,** exactly as `cli.py` does today. `_write_audio` moves over with its echo intact so existing output assertions keep working.
- **A missing `meta` key must never crash an emit.** `arrange` writes `bars` only when the score had bars (`src/bitty/arrange.py:76`), and `bitty render` accepts hand-edited arrangements. Fall back: `title` → the file stem, `bpm` → `0.0`, `bars` → omit the field entirely.
- **`loop_` not `loop`** in RON — `loop` is a reserved word in Rust.
- **Manifest entries are sorted by key** so `music.ron` is byte-stable across runs.
- **`generic` writes no fragment and no `music.ron`.** Its loop lives in the Vorbis comments and the sidecar.

## File Structure

| File | Responsibility |
|---|---|
| `src/bitty/synth.py` (modify) | Gains `Render` and `Render.of`. `render()` keeps returning a bare array. |
| `src/bitty/targets.py` (create) | Audio writing, the `TARGETS` registry, three emitters, RON fragments, `assemble()`. |
| `src/bitty/cli.py` (modify) | Gains `--target`, loses `--split`, `_write_audio`, `_write_split`. |
| `tests/test_targets.py` (create) | Registry, all three emitters, assembly, RON golden. |
| `tests/test_synth.py` (modify) | `Render.of` conversion and the both-or-neither invariant. |
| `tests/test_cli.py` (modify) | `--split` tests become `--target` tests. |
| `pyproject.toml` (modify) | Adds `mutagen`. |
| `README.md` (modify) | `--target` table, the RON shape, the Rust structs. |

---

## Task 1: The `Render` contract

**Files:**
- Modify: `src/bitty/synth.py`
- Test: `tests/test_synth.py`

**Interfaces:**
- Consumes: `Arrangement` and `Loop` from `bitty.arrangement`; `SAMPLE_RATE` from `bitty.synth`.
- Produces: `Render` — a frozen dataclass with fields `audio: np.ndarray`, `sample_rate: int`, `meta: dict`, `loop_start_sample: int | None`, `loop_end_sample: int | None`; and the classmethod `Render.of(arrangement: Arrangement, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Render`. Every later task depends on these exact names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_synth.py`:

```python
def test_render_of_converts_loop_seconds_to_samples():
    arrangement = Arrangement(
        meta={"title": "t", "bpm": 120.0},
        channels=(),
        loop=Loop(start_sec=1.0, end_sec=2.0),
    )
    audio = np.zeros((44100 * 3, 2), dtype=np.float32)

    result = Render.of(arrangement, audio)

    assert result.loop_start_sample == 44100
    assert result.loop_end_sample == 88200
    assert result.sample_rate == 44100


def test_render_of_clamps_the_loop_end_to_the_buffer():
    """A loop end past the rendered tail is the echo being cut, not a bug."""
    arrangement = Arrangement(
        meta={}, channels=(), loop=Loop(start_sec=0.0, end_sec=99.0)
    )
    audio = np.zeros((44100, 2), dtype=np.float32)

    result = Render.of(arrangement, audio)

    assert result.loop_end_sample == 44100


def test_render_of_carries_no_loop_through_as_none():
    arrangement = Arrangement(meta={}, channels=(), loop=None)

    result = Render.of(arrangement, np.zeros((10, 2), dtype=np.float32))

    assert result.loop_start_sample is None
    assert result.loop_end_sample is None


def test_render_of_copies_meta_rather_than_aliasing_it():
    meta = {"title": "t"}
    result = Render.of(Arrangement(meta=meta, channels=()), np.zeros((10, 2)))

    result.meta["title"] = "changed"

    assert meta["title"] == "t"


def test_a_half_specified_loop_is_rejected_at_construction():
    """One set and one None is a bug. Catch it here, not in an emitter."""
    audio = np.zeros((10, 2), dtype=np.float32)

    with pytest.raises(ValueError):
        Render(audio=audio, sample_rate=44100, meta={}, loop_start_sample=0)

    with pytest.raises(ValueError):
        Render(audio=audio, sample_rate=44100, meta={}, loop_end_sample=10)
```

Add to the imports at the top of `tests/test_synth.py` whatever of these is not already there:

```python
import pytest

from bitty.arrangement import Arrangement, Loop
from bitty.synth import Render
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_synth.py -k render_of -v`
Expected: FAIL with `ImportError: cannot import name 'Render' from 'bitty.synth'`.

- [ ] **Step 3: Add the contract**

Add to `src/bitty/synth.py`, after the constants and before `render()`:

```python
@dataclass(frozen=True, eq=False)
class Render:
    """A rendered buffer plus where it loops, in samples.

    The boundary the targets stage consumes. `eq=False` because the default
    __eq__ would compare numpy arrays and raise on the ambiguous truth value.

    The loop is optional: a piece whose cascade found nothing is still worth
    emitting as a one-shot cue.
    """

    audio: np.ndarray  # float32 [n_samples, 2]
    sample_rate: int
    meta: dict  # arrangement.meta, copied
    loop_start_sample: int | None = None
    loop_end_sample: int | None = None

    def __post_init__(self) -> None:
        if (self.loop_start_sample is None) != (self.loop_end_sample is None):
            raise ValueError(
                "loop_start_sample and loop_end_sample must both be set or both be None"
            )

    @classmethod
    def of(
        cls,
        arrangement: Arrangement,
        audio: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
    ) -> "Render":
        """Join an arrangement's loop to its rendered audio.

        The one place seconds become samples. Clamping the end to the buffer
        is the echo tail 4b measured and accepted, not an error.
        """
        start = end = None
        if arrangement.loop is not None:
            start = max(0, round(arrangement.loop.start_sec * sample_rate))
            end = min(round(arrangement.loop.end_sec * sample_rate), len(audio))
        return cls(
            audio=audio,
            sample_rate=sample_rate,
            meta=dict(arrangement.meta),
            loop_start_sample=start,
            loop_end_sample=end,
        )
```

Add `from dataclasses import dataclass` to the imports at the top of `src/bitty/synth.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_synth.py -v`
Expected: PASS, including every pre-existing synth test — `render()` was not touched.

- [ ] **Step 5: Commit**

```bash
git add src/bitty/synth.py tests/test_synth.py
git commit -m "feat: add the Render contract joining audio to its loop"
```

---

## Task 2: `targets.py`, audio writing, and the `generic` target

**Files:**
- Create: `src/bitty/targets.py`
- Modify: `src/bitty/cli.py`, `pyproject.toml`
- Test: `tests/test_targets.py`

**Interfaces:**
- Consumes: `Render` from Task 1.
- Produces: `write_audio(audio, out_dir: Path, stem: str, audio_format: str = "ogg") -> Path`; `Emitter` type alias; `TARGETS: dict[str, Emitter]` containing only `"generic"` for now; `_emit_generic(render, out_dir, name, *, audio_format="ogg") -> list[Path]`. Tasks 4 and 5 add keys to `TARGETS`; Task 6 reads it.

- [ ] **Step 1: Add the dependency**

```bash
.venv/bin/pip install 'mutagen>=1.47'
```

Then add `"mutagen>=1.47",` to the `dependencies` list in `pyproject.toml`, after the `music21` line.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_targets.py`:

```python
"""Targets: a Render in, engine artifacts out."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from mutagen.oggvorbis import OggVorbis

from bitty.synth import Render
from bitty import targets

META = {"title": "Minuet in G", "bpm": 120.0, "bars": [1, 16]}


def a_render(loop=(1.0, 2.0), meta=META, seconds=3.0, sample_rate=44100):
    """Silent stereo audio is enough: no target inspects sample values."""
    audio = np.zeros((int(sample_rate * seconds), 2), dtype=np.float32)
    start = end = None
    if loop is not None:
        start = round(loop[0] * sample_rate)
        end = round(loop[1] * sample_rate)
    return Render(
        audio=audio,
        sample_rate=sample_rate,
        meta=dict(meta),
        loop_start_sample=start,
        loop_end_sample=end,
    )


def test_write_audio_writes_an_ogg_by_default(tmp_path):
    path = targets.write_audio(a_render().audio, tmp_path, "piece")

    assert path == tmp_path / "piece.ogg"
    assert path.exists()


def test_write_audio_writes_a_wav_when_asked(tmp_path):
    path = targets.write_audio(a_render().audio, tmp_path, "piece", "wav")

    assert path == tmp_path / "piece.wav"
    audio, rate = sf.read(path)
    assert rate == 44100
    assert audio.shape[1] == 2


def test_write_audio_creates_the_output_directory(tmp_path):
    nested = tmp_path / "deep" / "deeper"

    path = targets.write_audio(a_render().audio, nested, "piece")

    assert path.exists()


def test_generic_writes_one_file_and_no_manifest(tmp_path):
    written = targets.TARGETS["generic"](a_render(), tmp_path, "piece")

    assert written == [tmp_path / "piece.ogg"]
    assert not (tmp_path / "music.ron").exists()
    assert list(tmp_path.glob("*.ron")) == []


def test_generic_tags_the_loop_in_samples(tmp_path):
    targets.TARGETS["generic"](a_render(loop=(1.0, 2.0)), tmp_path, "piece")

    tags = OggVorbis(tmp_path / "piece.ogg")
    assert tags["LOOPSTART"] == ["44100"]
    assert tags["LOOPLENGTH"] == ["44100"]


def test_generic_writes_no_loop_tags_when_there_is_no_loop(tmp_path):
    targets.TARGETS["generic"](a_render(loop=None), tmp_path, "piece")

    tags = OggVorbis(tmp_path / "piece.ogg")
    assert "LOOPSTART" not in tags


def test_generic_as_wav_skips_the_tags_rather_than_failing(tmp_path):
    """WAV has nowhere to put a Vorbis comment. The sidecar still has the loop."""
    written = targets.TARGETS["generic"](a_render(), tmp_path, "piece", audio_format="wav")

    assert written == [tmp_path / "piece.wav"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_targets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bitty.targets'`.

- [ ] **Step 4: Write `targets.py`**

Create `src/bitty/targets.py`:

```python
"""Engine artifacts: a Render in, the files a game loads out.

Everything upstream of `Render` is the pipeline; this file is the one place
that knows what a particular engine wants on disk. A target is a plain
function in `TARGETS` — no base class, no factory. The dict is the single
source of truth for what `--target` accepts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf
import typer

from bitty.synth import Render

Emitter = Callable[..., list[Path]]


def write_audio(
    audio: np.ndarray, out_dir: Path, stem: str, audio_format: str = "ogg"
) -> Path:
    """Write a buffer and report it. Moved here from cli, echo intact."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.{audio_format}"

    if audio_format == "wav":
        sf.write(path, audio, 44100)
    else:
        sf.write(path, audio, 44100, format="OGG", subtype="VORBIS")

    typer.echo(f"{path}  ({len(audio) / 44100:.1f}s)")
    return path


def _emit_generic(
    render: Render, out_dir: Path, name: str, *, audio_format: str = "ogg"
) -> list[Path]:
    """One file, the loop embedded as Vorbis comments.

    LOOPSTART/LOOPLENGTH in samples is the RPG-Maker convention Unity and
    Godot both read. libsndfile writes only a fixed set of Vorbis fields, so
    the custom keys need mutagen.
    """
    path = write_audio(render.audio, out_dir, name, audio_format)

    if render.loop_start_sample is None:
        return [path]
    if audio_format != "ogg":
        typer.echo("  wav carries no Vorbis comments — the loop is in the sidecar only")
        return [path]

    from mutagen.oggvorbis import OggVorbis

    tags = OggVorbis(path)
    tags["LOOPSTART"] = str(render.loop_start_sample)
    tags["LOOPLENGTH"] = str(render.loop_end_sample - render.loop_start_sample)
    tags.save()
    return [path]


TARGETS: dict[str, Emitter] = {
    "generic": _emit_generic,
}
```

Note `write_audio` hard-codes 44100 exactly as `cli._write_audio` does today. It is not read from `render.sample_rate` because the CLI has always passed the module constant; Task 6 does not change that, and 5b's config is where a variable rate would land.

- [ ] **Step 5: Point the CLI at the moved function**

In `src/bitty/cli.py`, delete the `_write_audio` function body and replace its call sites. Change the two helpers to delegate:

```python
def _write_audio(audio, out_dir: Path, stem: str, wav: bool) -> Path:
    return targets.write_audio(audio, out_dir, stem, "wav" if wav else "ogg")
```

and add `from bitty import targets` to the imports. This is a temporary shim so the suite stays green; Task 6 deletes it.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_targets.py tests/test_cli.py -v`
Expected: PASS. The CLI tests still pass because the shim preserves the old signature and the echoed output.

- [ ] **Step 7: Commit**

```bash
git add src/bitty/targets.py src/bitty/cli.py pyproject.toml tests/test_targets.py
git commit -m "feat: add the targets registry and the generic emitter"
```

---

## Task 3: RON fragments and manifest assembly

**Files:**
- Modify: `src/bitty/targets.py`
- Test: `tests/test_targets.py`

**Interfaces:**
- Consumes: `Render` from Task 1; `targets.py` from Task 2.
- Produces: `_ron_str(value: str) -> str`; `_entry(key: str, fields: list[tuple[str, str]]) -> str`; `_write_fragment(out_dir: Path, name: str, target: str, body: str) -> Path`; `_common_fields(render: Render) -> list[tuple[str, str]]`; `_title(render: Render, name: str) -> str`; `assemble(out_dir: Path, target: str) -> Path | None`. Tasks 4 and 5 call all of these.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_targets.py`:

```python
def test_a_ron_string_escapes_quotes_and_backslashes(tmp_path):
    assert targets._ron_str('say "hi"') == '"say \\"hi\\""'
    assert targets._ron_str("back\\slash") == '"back\\\\slash"'


def test_common_fields_render_bpm_as_a_float_and_bars_as_a_tuple():
    fields = dict(targets._common_fields(a_render()))

    assert fields["bpm"] == "120.0"
    assert fields["bars"] == "(1, 16)"


def test_common_fields_omit_bars_when_the_meta_has_none():
    """arrange writes bars only when the score had them (arrange.py:76)."""
    fields = dict(targets._common_fields(a_render(meta={"title": "t", "bpm": 90.0})))

    assert "bars" not in fields
    assert fields["bpm"] == "90.0"


def test_common_fields_fall_back_to_zero_bpm_on_a_hand_edited_arrangement():
    fields = dict(targets._common_fields(a_render(meta={})))

    assert fields["bpm"] == "0.0"


def test_the_title_falls_back_to_the_file_stem():
    assert targets._title(a_render(meta={}), "piece") == "piece"
    assert targets._title(a_render(), "piece") == "Minuet in G"


def test_a_fragment_is_one_indented_entry(tmp_path):
    path = targets._write_fragment(
        tmp_path, "piece", "bevy", targets._entry("piece", [("bpm", "120.0")])
    )

    assert path == tmp_path / "piece.bevy.ron"
    assert path.read_text() == '        "piece": (\n            bpm: 120.0,\n        ),\n'


def test_assemble_wraps_every_fragment_for_that_target(tmp_path):
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets._write_fragment(tmp_path, "b", "bevy", targets._entry("b", [("bpm", "2.0")]))

    manifest = targets.assemble(tmp_path, "bevy")

    assert manifest == tmp_path / "music.ron"
    text = manifest.read_text()
    assert text.startswith("(\n    tracks: {\n")
    assert text.endswith("    },\n)\n")
    assert '"a": (' in text and '"b": (' in text


def test_assembling_one_piece_never_drops_another(tmp_path):
    """The property the whole fragment design exists to guarantee."""
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets.assemble(tmp_path, "bevy")

    targets._write_fragment(tmp_path, "b", "bevy", targets._entry("b", [("bpm", "2.0")]))
    targets.assemble(tmp_path, "bevy")

    text = (tmp_path / "music.ron").read_text()
    assert '"a": (' in text
    assert '"b": (' in text


def test_re_emitting_a_piece_replaces_only_its_own_entry(tmp_path):
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets._write_fragment(tmp_path, "b", "bevy", targets._entry("b", [("bpm", "2.0")]))
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "9.0")]))

    text = targets.assemble(tmp_path, "bevy").read_text()

    assert "bpm: 9.0" in text
    assert "bpm: 1.0" not in text
    assert "bpm: 2.0" in text


def test_the_manifest_is_byte_stable_regardless_of_write_order(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    targets._write_fragment(tmp_path, "b", "bevy", targets._entry("b", [("bpm", "2.0")]))
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets._write_fragment(other, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets._write_fragment(other, "b", "bevy", targets._entry("b", [("bpm", "2.0")]))

    assert (
        targets.assemble(tmp_path, "bevy").read_text()
        == targets.assemble(other, "bevy").read_text()
    )


def test_assemble_ignores_another_targets_fragments(tmp_path):
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets._write_fragment(tmp_path, "a", "bevy-kira", targets._entry("a", [("bpm", "9.0")]))

    text = targets.assemble(tmp_path, "bevy").read_text()

    assert "bpm: 1.0" in text
    assert "bpm: 9.0" not in text


def test_assemble_writes_nothing_when_there_are_no_fragments(tmp_path):
    assert targets.assemble(tmp_path, "generic") is None
    assert not (tmp_path / "music.ron").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_targets.py -k "ron or fragment or assemble or common_fields or title" -v`
Expected: FAIL with `AttributeError: module 'bitty.targets' has no attribute '_ron_str'`.

- [ ] **Step 3: Implement the RON layer**

Add to `src/bitty/targets.py`, after `write_audio`:

```python
MANIFEST_NAME = "music.ron"
ENTRY_INDENT = " " * 8
FIELD_INDENT = " " * 12


def _ron_str(value: str) -> str:
    """RON strings are Rust strings: backslash first, then quote."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _title(render: Render, name: str) -> str:
    """A hand-edited arrangement may carry no title at all."""
    return render.meta.get("title") or name


def _common_fields(render: Render) -> list[tuple[str, str]]:
    """The fields every target's entry ends with.

    `bars` is omitted rather than defaulted: `arrange` writes it only when the
    score had bars, and an invented range would be a lie the game can read.
    """
    fields = [("bpm", repr(float(render.meta.get("bpm") or 0.0)))]
    bars = render.meta.get("bars")
    if bars:
        fields.append(("bars", f"({bars[0]}, {bars[-1]})"))
    return fields


def _entry(key: str, fields: list[tuple[str, str]]) -> str:
    """One map entry, indented to sit inside the manifest's `tracks`."""
    lines = [f"{ENTRY_INDENT}{_ron_str(key)}: ("]
    lines += [f"{FIELD_INDENT}{name}: {value}," for name, value in fields]
    lines.append(f"{ENTRY_INDENT}),")
    return "\n".join(lines) + "\n"


def _write_fragment(out_dir: Path, name: str, target: str, body: str) -> Path:
    """One piece's entry in its own file.

    Per-target naming so two targets in one directory cannot clobber each
    other, and one file per piece so no step ever reads and rewrites a shared
    manifest — which is what makes re-converting one piece unable to drop
    another's entry.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.{target}.ron"
    path.write_text(body)
    return path


def assemble(out_dir: Path, target: str) -> Path | None:
    """Concatenate every fragment for `target` into `music.ron`.

    A glob, a sort, and a join — no RON parser on either side of the round
    trip. Returns None when the target writes no fragments, so a
    generic-only directory never grows a manifest.
    """
    fragments = sorted(out_dir.glob(f"*.{target}.ron"))
    if not fragments:
        return None

    body = "".join(fragment.read_text() for fragment in fragments)
    path = out_dir / MANIFEST_NAME
    path.write_text(f"(\n    tracks: {{\n{body}    }},\n)\n")
    typer.echo(f"{path}")
    return path
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_targets.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Commit**

```bash
git add src/bitty/targets.py tests/test_targets.py
git commit -m "feat: write per-piece RON fragments and assemble music.ron"
```

---

## Task 4: The `bevy` target

**Files:**
- Modify: `src/bitty/targets.py`
- Test: `tests/test_targets.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `_emit_bevy(render, out_dir, name, *, audio_format="ogg") -> list[Path]`, registered in `TARGETS` under `"bevy"`. Task 6 makes it the CLI default.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_targets.py`:

```python
def test_bevy_writes_an_intro_and_a_loop(tmp_path):
    written = targets.TARGETS["bevy"](a_render(loop=(1.0, 2.0)), tmp_path, "piece")

    assert (tmp_path / "piece_intro.ogg").exists()
    assert (tmp_path / "piece_loop.ogg").exists()
    assert (tmp_path / "piece.bevy.ron") in written


def test_the_bevy_pieces_have_the_durations_the_loop_names(tmp_path):
    targets.TARGETS["bevy"](a_render(loop=(1.0, 2.0), seconds=3.0), tmp_path, "piece", audio_format="wav")

    intro, _ = sf.read(tmp_path / "piece_intro.wav")
    body, _ = sf.read(tmp_path / "piece_loop.wav")
    assert abs(len(intro) / 44100 - 1.0) < 0.01
    assert abs(len(body) / 44100 - 1.0) < 0.01


def test_bevy_drops_the_audio_past_the_loop_end(tmp_path):
    """Same rule --split had: what follows the loop is never reached."""
    targets.TARGETS["bevy"](a_render(loop=(0.0, 1.0), seconds=3.0), tmp_path, "piece", audio_format="wav")

    body, _ = sf.read(tmp_path / "piece_loop.wav")
    assert abs(len(body) / 44100 - 1.0) < 0.01


def test_a_loop_starting_at_zero_writes_no_intro(tmp_path):
    written = targets.TARGETS["bevy"](a_render(loop=(0.0, 2.0)), tmp_path, "piece")

    assert not (tmp_path / "piece_intro.ogg").exists()
    assert (tmp_path / "piece_loop.ogg") in written


def test_bevy_without_a_loop_emits_a_one_shot(tmp_path):
    """A piece with no loop point is a legitimate cue, not a failure."""
    written = targets.TARGETS["bevy"](a_render(loop=None), tmp_path, "piece")

    assert (tmp_path / "piece.ogg") in written
    assert not (tmp_path / "piece_loop.ogg").exists()
    assert 'full: "piece.ogg",' in (tmp_path / "piece.bevy.ron").read_text()


def test_the_bevy_fragment_is_exactly_this(tmp_path):
    """The golden. A format change should read as a diff, not a surprise."""
    targets.TARGETS["bevy"](a_render(loop=(1.0, 2.0)), tmp_path, "minuet")

    assert (tmp_path / "minuet.bevy.ron").read_text() == (
        '        "minuet": (\n'
        '            title: "Minuet in G",\n'
        '            intro: "minuet_intro.ogg",\n'
        '            loop_: "minuet_loop.ogg",\n'
        "            bpm: 120.0,\n"
        "            bars: (1, 16),\n"
        "        ),\n"
    )


def test_the_bevy_fragment_names_wav_files_when_asked(tmp_path):
    targets.TARGETS["bevy"](a_render(loop=(1.0, 2.0)), tmp_path, "piece", audio_format="wav")

    text = (tmp_path / "piece.bevy.ron").read_text()
    assert 'intro: "piece_intro.wav",' in text
    assert 'loop_: "piece_loop.wav",' in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_targets.py -k bevy -v`
Expected: FAIL with `KeyError: 'bevy'`.

- [ ] **Step 3: Implement the emitter**

Add to `src/bitty/targets.py`, before the `TARGETS` dict:

```python
def _emit_bevy(
    render: Render, out_dir: Path, name: str, *, audio_format: str = "ogg"
) -> list[Path]:
    """Two complete files, because rodio can only loop a whole file.

    bevy_audio has no seek and no loop region: the intro and the loop have to
    be separate assets. Audio past the loop end is dropped — nothing ever
    reaches it.
    """
    written: list[Path] = []
    fields = [("title", _ron_str(_title(render, name)))]

    if render.loop_start_sample is None:
        written.append(write_audio(render.audio, out_dir, name, audio_format))
        fields.append(("full", _ron_str(f"{name}.{audio_format}")))
    else:
        start, end = render.loop_start_sample, render.loop_end_sample
        if start > 0:
            written.append(
                write_audio(render.audio[:start], out_dir, f"{name}_intro", audio_format)
            )
            fields.append(("intro", _ron_str(f"{name}_intro.{audio_format}")))
        else:
            typer.echo("  loop starts at 0:00 — no intro to write")
        written.append(
            write_audio(render.audio[start:end], out_dir, f"{name}_loop", audio_format)
        )
        fields.append(("loop_", _ron_str(f"{name}_loop.{audio_format}")))

    fields += _common_fields(render)
    written.append(_write_fragment(out_dir, name, "bevy", _entry(name, fields)))
    return written
```

Then extend the registry:

```python
TARGETS: dict[str, Emitter] = {
    "bevy": _emit_bevy,
    "generic": _emit_generic,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_targets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bitty/targets.py tests/test_targets.py
git commit -m "feat: emit an intro and loop pair for bevy_audio"
```

---

## Task 5: The `bevy-kira` target and the registry contract

**Files:**
- Modify: `src/bitty/targets.py`
- Test: `tests/test_targets.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: `_emit_bevy_kira(...)` registered under `"bevy-kira"`, completing `TARGETS`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_targets.py`:

```python
def test_kira_writes_one_whole_file(tmp_path):
    written = targets.TARGETS["bevy-kira"](a_render(loop=(1.0, 2.0), seconds=3.0), tmp_path, "piece", audio_format="wav")

    assert (tmp_path / "piece.wav") in written
    audio, _ = sf.read(tmp_path / "piece.wav")
    assert abs(len(audio) / 44100 - 3.0) < 0.01


def test_kira_records_the_loop_in_seconds_not_samples(tmp_path):
    """Kira's loop regions are time-based. This is the one target that keeps seconds."""
    targets.TARGETS["bevy-kira"](a_render(loop=(1.0, 2.0)), tmp_path, "piece")

    text = (tmp_path / "piece.bevy-kira.ron").read_text()
    assert "loop_start: 1.0," in text
    assert "loop_end: 2.0," in text


def test_kira_omits_the_loop_keys_when_there_is_no_loop(tmp_path):
    targets.TARGETS["bevy-kira"](a_render(loop=None), tmp_path, "piece")

    text = (tmp_path / "piece.bevy-kira.ron").read_text()
    assert "loop_start" not in text
    assert 'file: "piece.ogg",' in text


@pytest.mark.parametrize("target", sorted(targets.TARGETS))
def test_every_target_emits_the_files_it_claims(tmp_path, target):
    """The test that catches a new target wired in wrong."""
    written = targets.TARGETS[target](a_render(), tmp_path, "piece")

    assert written, f"{target} emitted nothing"
    for path in written:
        assert path.exists(), f"{target} named {path} but did not write it"


@pytest.mark.parametrize("target", sorted(targets.TARGETS))
def test_every_target_survives_an_empty_meta(tmp_path, target):
    """bitty render accepts hand-edited arrangements missing any key."""
    written = targets.TARGETS[target](a_render(meta={}), tmp_path, "piece")

    assert all(path.exists() for path in written)


@pytest.mark.parametrize("target", sorted(targets.TARGETS))
def test_every_target_survives_having_no_loop(tmp_path, target):
    written = targets.TARGETS[target](a_render(loop=None), tmp_path, "piece")

    assert all(path.exists() for path in written)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_targets.py -k kira -v`
Expected: FAIL with `KeyError: 'bevy-kira'`.

- [ ] **Step 3: Implement the emitter**

Add to `src/bitty/targets.py`, after `_emit_bevy`:

```python
def _emit_bevy_kira(
    render: Render, out_dir: Path, name: str, *, audio_format: str = "ogg"
) -> list[Path]:
    """One whole file plus offsets, because kira has real loop regions.

    Kira takes seconds, so this is the only target where the offsets do not
    become samples.
    """
    path = write_audio(render.audio, out_dir, name, audio_format)
    fields = [
        ("title", _ron_str(_title(render, name))),
        ("file", _ron_str(path.name)),
    ]
    if render.loop_start_sample is not None:
        rate = render.sample_rate
        fields.append(("loop_start", repr(round(render.loop_start_sample / rate, 6))))
        fields.append(("loop_end", repr(round(render.loop_end_sample / rate, 6))))

    fields += _common_fields(render)
    return [path, _write_fragment(out_dir, name, "bevy-kira", _entry(name, fields))]
```

Then complete the registry:

```python
TARGETS: dict[str, Emitter] = {
    "bevy": _emit_bevy,
    "bevy-kira": _emit_bevy_kira,
    "generic": _emit_generic,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_targets.py -v`
Expected: PASS. The three parametrized tests now run once per target, nine cases.

- [ ] **Step 5: Commit**

```bash
git add src/bitty/targets.py tests/test_targets.py
git commit -m "feat: emit a whole file and loop offsets for bevy_kira_audio"
```

---

## Task 6: Wire `--target` into the CLI and retire `--split`

**Files:**
- Modify: `src/bitty/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `TARGETS` and `assemble` from Tasks 2–5; `Render.of` from Task 1.
- Produces: `bitty convert --target NAME` and `bitty render --target NAME`, defaulting to `bevy`. `--split` no longer exists.

- [ ] **Step 1: Rewrite the split tests as target tests**

In `tests/test_cli.py`, replace the five tests found by `rg -n 'split' tests/test_cli.py` (`test_split_writes_an_intro_and_a_loop`, `test_the_split_pieces_have_the_durations_the_loop_names`, `test_a_loop_starting_at_zero_writes_no_intro`, `test_split_without_a_loop_is_a_hard_error`, `test_render_can_split_a_hand_edited_arrangement`) with:

```python
def test_convert_defaults_to_the_bevy_target(tmp_path):
    """minuet auto-loops at bar 1, so the loop starts at 0:00 and there is no intro."""
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--wav"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "minuet_loop.wav").exists()
    assert (tmp_path / "music.ron").exists()
    assert (tmp_path / "minuet.arrangement.json").exists()


def test_bevy_writes_an_intro_when_the_loop_starts_late(tmp_path):
    result = runner.invoke(
        app, ["convert", str(MINUET), "-o", str(tmp_path), "--wav", "--loop-from", "9"]
    )
    assert result.exit_code == 0, result.output
    intro, _ = sf.read(tmp_path / "minuet_intro.wav")
    body, _ = sf.read(tmp_path / "minuet_loop.wav")
    assert abs(len(intro) / 44100 - 12.0) < 0.01
    assert abs(len(body) / 44100 - 12.0) < 0.01


def test_a_loop_starting_at_zero_writes_no_intro(tmp_path):
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--wav"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "minuet_intro.wav").exists()
    assert "no intro" in result.output.lower()


def test_a_piece_with_no_loop_is_emitted_as_a_one_shot(tmp_path):
    """4b made this a hard error under --split. The manifest can now say so instead."""
    result = runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path), "--wav"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "two_part.wav").exists()
    assert 'full: "two_part.wav",' in (tmp_path / "music.ron").read_text()


def test_the_generic_target_writes_one_file_and_no_manifest(tmp_path):
    result = runner.invoke(
        app, ["convert", str(MINUET), "-o", str(tmp_path), "--target", "generic"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "minuet.ogg").exists()
    assert not (tmp_path / "music.ron").exists()


def test_an_unknown_target_names_the_valid_ones(tmp_path):
    result = runner.invoke(
        app, ["convert", str(MINUET), "-o", str(tmp_path), "--target", "snes"]
    )
    assert result.exit_code != 0
    assert "bevy-kira" in result.output
    assert list(tmp_path.iterdir()) == [], "nothing should be written before the check"


def test_render_re_emits_a_hand_edited_arrangement(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--loop-from", "9"])
    result = runner.invoke(
        app,
        ["render", str(tmp_path / "minuet.arrangement.json"), "-o", str(tmp_path), "--wav"],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "minuet_loop.wav").exists()


def test_converting_a_second_piece_keeps_the_first_in_the_manifest(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--wav"])
    runner.invoke(app, ["convert", str(CHORALE), "-o", str(tmp_path), "--wav"])

    text = (tmp_path / "music.ron").read_text()
    assert '"minuet": (' in text
    assert '"chorale": (' in text
```

Also update `test_convert_writes_ogg_and_arrangement` and `test_wav_flag_writes_uncompressed_instead` and `test_converted_audio_is_stereo_at_the_expected_duration`, which assume a single `two_part.ogg`. `two_part` has no loop, so `bevy` writes exactly `two_part.ogg` — those three tests pass unchanged. Confirm rather than assume by running them.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — `--target` is not a known option, and `music.ron` is never written.

- [ ] **Step 3: Rewrite the CLI**

In `src/bitty/cli.py`: delete `_write_audio` and `_write_split` entirely, drop the now-unused `soundfile` import, and add:

```python
DEFAULT_TARGET = "bevy"


def _emit(
    arrangement: Arrangement, audio, out_dir: Path, stem: str, target: str, wav: bool
) -> None:
    """One path for every write. Targets own the file layout; the CLI owns the flags."""
    render = Render.of(arrangement, audio)
    targets.TARGETS[target](
        render, out_dir, stem, audio_format="wav" if wav else "ogg"
    )
    targets.assemble(out_dir, target)


def _check_target(target: str) -> None:
    """Validated against the registry itself, before anything is parsed or written."""
    if target not in targets.TARGETS:
        raise typer.BadParameter(
            f"unknown target {target!r}; try one of {', '.join(sorted(targets.TARGETS))}",
            param_hint="--target",
        )
```

Replace the `split` parameter on `convert` with:

```python
    target: str = typer.Option(
        DEFAULT_TARGET, "--target", help="bevy, bevy-kira, or generic."
    ),
```

and make `convert`'s body:

```python
    _check_target(target)
    parsed = ingest(score)
    if bars:
        first, last = _bar_range(bars)
        try:
            parsed = loop_stage.trim(parsed, first, last)
        except ValueError as error:
            raise typer.BadParameter(str(error), param_hint="--bars") from error

    try:
        candidates = loop_stage.candidates(parsed, analyze(parsed), loop_from)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--loop-from") from error

    arrangement = arrange(parsed)
    audio = render_audio(arrangement)
    chosen = loop_stage.choose(candidates, audio, arrangement, SAMPLE_RATE)
    arrangement = replace(arrangement, loop=chosen.loop if chosen else None)

    _report(chosen)
    _emit(arrangement, audio, out_dir, score.stem, target, wav)

    json_path = out_dir / f"{score.stem}{ARRANGEMENT_SUFFIX}"
    json_path.write_text(arrangement.to_json())
    typer.echo(f"{json_path}")
```

Note the `--split`-without-a-loop guard is gone: a missing loop is now a one-shot entry, not a failure.

Give `render` the same `--target` option in place of `split`, and make its body:

```python
    _check_target(target)
    loaded = Arrangement.from_json(arrangement.read_text())
    audio = render_audio(loaded)
    _emit(loaded, audio, out_dir, _stem(arrangement), target, wav)
```

Add `from bitty.synth import Render` to the imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS, zero failures. Confirm `git diff --stat tests/goldens/` is empty — this phase changes no arrangement.

- [ ] **Step 6: Commit**

```bash
git add src/bitty/cli.py tests/test_cli.py
git commit -m "feat: select an engine target and retire --split"
```

---

## Task 7: Documentation and the audition

**Files:**
- Modify: `README.md`
- Test: the full suite, then a real Rust build

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS, roughly 250 tests, zero failures.

- [ ] **Step 2: Update the README**

Replace the `--split` row in the CLI flag table with:

| Flag | Effect |
|---|---|
| `--target NAME` | `bevy` (default), `bevy-kira`, or `generic`. |

Add a "Targets" section covering: that `bevy` writes an intro/loop pair because rodio can only loop a whole file; that a loop starting at 0:00 writes no intro and a piece with no loop is emitted as a one-shot `full` entry; that `bevy` and `bevy-kira` write a `name.<target>.ron` fragment which is assembled into `music.ron`, so converting one piece never drops another; that `generic` embeds `LOOPSTART`/`LOOPLENGTH` Vorbis comments in samples and writes no manifest; and that `--wav` is orthogonal, for auditioning through `aplay`.

Include the manifest shape and both Rust structs verbatim from the spec's "The `bevy` shape" section, so they can be pasted into the game.

Update the Status section: Phase 5a is done; 5b picks up TOML config and presets.

- [ ] **Step 3: Commit the docs**

```bash
git add README.md
git commit -m "docs: document targets and the music.ron manifest"
```

- [ ] **Step 4: Build the audition**

```bash
.venv/bin/bitty convert tests/fixtures/minuet.mxl --wav -o out
.venv/bin/bitty convert tests/fixtures/ragtime.mxl --wav -o out
.venv/bin/bitty convert tests/fixtures/chorale.mxl --wav -o out
cat out/music.ron
```

WAV only — `aplay` renders Ogg as static.

- [ ] **Step 5: Verify against the real project**

This phase's audition is a compile, not a listen: nothing in the Python
suite proves Rust can parse the RON.

Paste the `MusicManifest` and `Track` structs from the README into the Bevy
project, point them at `out/music.ron`, and build. Confirm all three tracks
deserialize, including `two_part`'s `full` variant if you convert it.

If the three `Option`s on `Track` are unpleasant to use on the Rust side,
the `Playback` enum described in the spec is a one-line change to
`_entry`'s field list in `_emit_bevy`. Decide it here, with real code in
front of you, rather than in the abstract.

- [ ] **Step 6: Commit any format correction**

```bash
git add -A
git commit -m "fix: correct the manifest shape against the real consumer"
```

Skip this step if the build was clean.

---

## Self-Review Notes

Checked against the spec, 2026-08-21:

- **Spec coverage.** `Render` → Task 1. Registry and deviation on the `audio_format` keyword → Task 2. Sidecar staying in the CLI → Task 6. `generic` → Task 2. Fragments and assembly → Task 3. `bevy` three loop states → Task 4. `bevy-kira` → Task 5. `--target`, `--split` removal, unknown-target error → Task 6. README and Rust structs → Task 7. The RON-parses-in-Rust risk → Task 7 Step 5.
- **Type consistency.** `write_audio` takes `audio_format: str` everywhere, never a `wav: bool`; the bool stops at the CLI boundary in `_emit`. `_entry(key, fields)` takes `list[tuple[str, str]]` of already-formatted RON values in all three emitters.
- **Known gap, deliberate.** `write_audio` hard-codes 44100 rather than reading `render.sample_rate`, matching `cli._write_audio` today. Task 5's kira emitter does use `render.sample_rate` for its seconds conversion, which is correct there. Unifying them is 5b's job, alongside the rest of the constants.
