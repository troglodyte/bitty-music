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
