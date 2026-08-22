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
