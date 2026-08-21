"""Command-line entry point."""

from dataclasses import replace
from pathlib import Path

import soundfile as sf
import typer

from bitty import loop as loop_stage
from bitty.analyze import analyze
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
def sections(
    score: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    """Print the structure the score's own marks describe."""
    parsed = ingest(score)
    found = analyze(parsed)
    total = found[-1].end if found else 0.0

    typer.echo(
        f"\n{parsed.title}  ·  q={parsed.bpm:g}"
        f"  ·  {len(parsed.bars)} bars  ·  {total:.1f}s\n"
    )
    for section in found:
        meter = f"{section.time_signature[0]}/{section.time_signature[1]}"
        typer.echo(
            f"  {section.name:<3} "
            f"bars {section.first_bar:>3}-{section.last_bar:<4} "
            f"{meter:<5} {section.key:<10} "
            f"{_clock(section.start)}   {section.end - section.start:>5.1f}s"
            f"{'   repeat' if section.repeats else ''}"
        )


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


@app.command()
def convert(
    score: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(Path("out"), "-o", "--out-dir"),
    wav: bool = typer.Option(False, "--wav", help="Write uncompressed WAV instead of Ogg."),
    bars: str = typer.Option(None, "--bars", help="Printed bar range to keep, e.g. 9-16."),
    loop_from: int = typer.Option(
        None, "--loop-from", help="Printed bar the loop starts at. Overrides the cascade."
    ),
) -> None:
    """Convert a score to audio and its arrangement JSON."""
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

    _write_audio(audio, out_dir, score.stem, wav)
    _report(chosen)

    json_path = out_dir / f"{score.stem}{ARRANGEMENT_SUFFIX}"
    json_path.write_text(arrangement.to_json())
    typer.echo(f"{json_path}")


def _bar_range(text: str) -> tuple[int, int]:
    first, _, last = text.partition("-")
    try:
        return int(first), int(last)
    except ValueError as error:
        raise typer.BadParameter(
            f"expected a printed bar range like 9-16, got {text!r}", param_hint="--bars"
        ) from error


def _report(chosen) -> None:
    if chosen is None:
        typer.echo("  no loop found — try --loop-from BAR")
        return
    typer.echo(
        f"  loop: bars {chosen.candidate.first_bar}-{chosen.candidate.last_bar}"
        f"  ({chosen.describe()})"
    )


@app.command()
def render(
    arrangement: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(Path("out"), "-o", "--out-dir"),
    wav: bool = typer.Option(False, "--wav", help="Write uncompressed WAV instead of Ogg."),
) -> None:
    """Re-render a hand-edited arrangement, skipping analysis entirely."""
    loaded = Arrangement.from_json(arrangement.read_text())
    _write_audio(render_audio(loaded), out_dir, _stem(arrangement), wav)


def _write_audio(audio, out_dir: Path, stem: str, wav: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
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
