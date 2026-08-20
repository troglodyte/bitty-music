"""Command-line entry point."""

from pathlib import Path

import soundfile as sf
import typer

from bitty.arrange import arrange
from bitty.arrangement import Arrangement
from bitty.ingest import ingest
from bitty.synth import SAMPLE_RATE
from bitty.synth import render as render_audio

app = typer.Typer(help="Turn classical scores into chiptune audio.")

ARRANGEMENT_SUFFIX = ".arrangement.json"


@app.callback()
def main() -> None:
    """Keep subcommand dispatch rather than folding a lone command into the root."""


@app.command()
def convert(
    score: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(Path("out"), "-o", "--out-dir"),
    wav: bool = typer.Option(False, "--wav", help="Write uncompressed WAV instead of Ogg."),
) -> None:
    """Convert a score to audio and its arrangement JSON."""
    arrangement = arrange(ingest(score))
    _write_audio(arrangement, out_dir, score.stem, wav)

    json_path = out_dir / f"{score.stem}{ARRANGEMENT_SUFFIX}"
    json_path.write_text(arrangement.to_json())
    typer.echo(f"{json_path}")


@app.command()
def render(
    arrangement: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(Path("out"), "-o", "--out-dir"),
    wav: bool = typer.Option(False, "--wav", help="Write uncompressed WAV instead of Ogg."),
) -> None:
    """Re-render a hand-edited arrangement, skipping analysis entirely."""
    _write_audio(
        Arrangement.from_json(arrangement.read_text()),
        out_dir,
        _stem(arrangement),
        wav,
    )


def _write_audio(arrangement: Arrangement, out_dir: Path, stem: str, wav: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    audio = render_audio(arrangement)
    path = out_dir / f"{stem}{'.wav' if wav else '.ogg'}"

    if wav:
        sf.write(path, audio, SAMPLE_RATE)
    else:
        sf.write(path, audio, SAMPLE_RATE, format="OGG", subtype="VORBIS")

    typer.echo(f"{path}  ({len(audio) / SAMPLE_RATE:.1f}s)")
    return path


def _stem(path: Path) -> str:
    """`foo.arrangement.json` re-renders to `foo.ogg`, not `foo.arrangement.ogg`."""
    if path.name.endswith(ARRANGEMENT_SUFFIX):
        return path.name[: -len(ARRANGEMENT_SUFFIX)]
    return path.stem
