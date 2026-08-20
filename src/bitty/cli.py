"""Command-line entry point."""

from pathlib import Path

import soundfile as sf
import typer

from bitty.arrange import arrange
from bitty.ingest import ingest
from bitty.synth import SAMPLE_RATE, render

app = typer.Typer(help="Turn classical scores into chiptune audio.")


@app.callback()
def main() -> None:
    """Keep subcommand dispatch even while `convert` is the only command.

    Typer folds a lone command into the root app, which would make the
    invocation `bitty SCORE`. Phases 4 and 5 add `sections` and `render`
    alongside it, so the subcommand form is the one that has to hold.
    """


@app.command()
def convert(
    score: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(Path("out"), "-o", "--out-dir"),
    wav: bool = typer.Option(False, "--wav", help="Write uncompressed WAV instead of Ogg."),
) -> None:
    """Convert a score to audio and its arrangement JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)

    arrangement = arrange(ingest(score))
    audio = render(arrangement)

    audio_path = out_dir / f"{score.stem}{'.wav' if wav else '.ogg'}"
    json_path = out_dir / f"{score.stem}.arrangement.json"

    if wav:
        sf.write(audio_path, audio, SAMPLE_RATE)
    else:
        sf.write(audio_path, audio, SAMPLE_RATE, format="OGG", subtype="VORBIS")
    json_path.write_text(arrangement.to_json())

    typer.echo(f"{audio_path}  ({len(audio) / SAMPLE_RATE:.1f}s)")
    typer.echo(f"{json_path}")
