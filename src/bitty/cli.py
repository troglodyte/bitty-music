"""Command-line entry point."""

from dataclasses import replace
from pathlib import Path

import typer

from bitty import loop as loop_stage
from bitty import targets
from bitty.analyze import analyze
from bitty.arrange import arrange
from bitty.arrangement import Arrangement
from bitty.ingest import ingest
from bitty.synth import SAMPLE_RATE, Render
from bitty.synth import render as render_audio

app = typer.Typer(help="Turn classical scores into chiptune audio.")

ARRANGEMENT_SUFFIX = ".arrangement.json"
DEFAULT_TARGET = "bevy"
TARGET_HELP = f"{', '.join(sorted(targets.TARGETS))}."


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

    arrangement = arrange(parsed)
    chosen = loop_stage.choose(
        loop_stage.candidates(parsed, found),
        render_audio(arrangement),
        arrangement,
        SAMPLE_RATE,
    )
    typer.echo("")
    if chosen is None:
        typer.echo("  no loop found — try convert --loop-from BAR")
    else:
        typer.echo(
            f"  auto-loop pick: bars {chosen.candidate.first_bar}-{chosen.candidate.last_bar}"
            f"  ({chosen.describe()})"
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
    target: str = typer.Option(DEFAULT_TARGET, "--target", help=TARGET_HELP),
) -> None:
    """Convert a score to audio and its arrangement JSON."""
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
    target: str = typer.Option(DEFAULT_TARGET, "--target", help=TARGET_HELP),
) -> None:
    """Re-render a hand-edited arrangement, skipping analysis entirely."""
    _check_target(target)
    loaded = Arrangement.from_json(arrangement.read_text())
    audio = render_audio(loaded)
    _emit(loaded, audio, out_dir, _stem(arrangement), target, wav)


def _stem(path: Path) -> str:
    """`foo.arrangement.json` re-renders to `foo.ogg`, not `foo.arrangement.ogg`."""
    if path.name.endswith(ARRANGEMENT_SUFFIX):
        return path.name[: -len(ARRANGEMENT_SUFFIX)]
    return path.stem
