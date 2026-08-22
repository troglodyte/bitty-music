"""Command-line entry point."""

from dataclasses import replace
from pathlib import Path
from typing import Optional

import typer

from bitty import config as config_module
from bitty import loop as loop_stage
from bitty import targets
from bitty.analyze import analyze
from bitty.arrange import arrange
from bitty.arrangement import Arrangement
from bitty.config import Config
from bitty.ingest import ingest
from bitty.synth import Render
from bitty.synth import render as render_audio

app = typer.Typer(help="Turn classical scores into chiptune audio.")

ARRANGEMENT_SUFFIX = ".arrangement.json"
TARGET_HELP = f"{', '.join(sorted(targets.TARGETS))}."
PRESET_HELP = f"{', '.join(config_module.preset_names())}."


def _settings(
    directory: Path,
    stem: str,
    preset: str | None,
    explicit: Path | None,
    out_dir: Path | None,
    wav: bool | None,
    target: str | None,
) -> Config:
    """Files first, then flags.

    Every config-backed flag defaults to None, which is how the CLI tells "not
    given" from "given the value that happens to be the default". Without that
    a config file could never set a value a flag also names.
    """
    _check_preset(preset)
    try:
        resolved = config_module.resolve(directory, stem, preset=preset, explicit=explicit)
    except config_module.ConfigError as error:
        raise typer.BadParameter(str(error), param_hint="--config") from error

    output = resolved.output
    if out_dir is not None:
        output = replace(output, dir=out_dir)
    if wav is not None:
        output = replace(output, format="wav" if wav else "ogg")
    if target is not None:
        output = replace(output, target=target)

    _check_target(output.target)
    return replace(resolved, output=output)


def _check_preset(name: str | None) -> None:
    if name is not None and name not in config_module.preset_names():
        raise typer.BadParameter(
            f"unknown preset {name!r}; try one of {', '.join(config_module.preset_names())}",
            param_hint="--preset",
        )


def _emit(arrangement: Arrangement, audio, stem: str, settings: Config) -> None:
    """One path for every write. Targets own the file layout; config owns the flags."""
    render = Render.of(arrangement, audio, settings.output.sample_rate)
    targets.TARGETS[settings.output.target](
        render, settings.output.dir, stem, audio_format=settings.output.format
    )
    targets.assemble(settings.output.dir, settings.output.target)


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
    preset: Optional[str] = typer.Option(None, "--preset", help=PRESET_HELP),
    config_path: Optional[Path] = typer.Option(
        None, "--config", exists=True, dir_okay=False, readable=True
    ),
) -> None:
    """Print the structure the score's own marks describe."""
    settings = _settings(score.parent, score.stem, preset, config_path, None, None, None)

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

    arrangement = arrange(parsed, settings)
    chosen = loop_stage.choose(
        loop_stage.candidates(parsed, found, min_bars=settings.loop.min_bars),
        render_audio(arrangement, settings.output.sample_rate),
        arrangement,
        settings.output.sample_rate,
        seam_ratio=settings.loop.seam_ratio,
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
    out_dir: Optional[Path] = typer.Option(None, "-o", "--out-dir"),
    wav: Optional[bool] = typer.Option(
        None, "--wav/--ogg", help="Write uncompressed WAV instead of Ogg."
    ),
    bars: str = typer.Option(None, "--bars", help="Printed bar range to keep, e.g. 9-16."),
    loop_from: int = typer.Option(
        None, "--loop-from", help="Printed bar the loop starts at. Overrides the cascade."
    ),
    target: Optional[str] = typer.Option(None, "--target", help=TARGET_HELP),
    preset: Optional[str] = typer.Option(None, "--preset", help=PRESET_HELP),
    config_path: Optional[Path] = typer.Option(
        None, "--config", exists=True, dir_okay=False, readable=True
    ),
) -> None:
    """Convert a score to audio and its arrangement JSON."""
    settings = _settings(
        score.parent, score.stem, preset, config_path, out_dir, wav, target
    )

    parsed = ingest(score)
    if bars:
        first, last = _bar_range(bars)
        try:
            parsed = loop_stage.trim(parsed, first, last)
        except ValueError as error:
            raise typer.BadParameter(str(error), param_hint="--bars") from error

    try:
        candidates = loop_stage.candidates(
            parsed, analyze(parsed), loop_from, min_bars=settings.loop.min_bars
        )
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--loop-from") from error

    arrangement = arrange(parsed, settings)
    audio = render_audio(arrangement, settings.output.sample_rate)
    chosen = loop_stage.choose(
        candidates,
        audio,
        arrangement,
        settings.output.sample_rate,
        seam_ratio=settings.loop.seam_ratio,
    )
    arrangement = replace(arrangement, loop=chosen.loop if chosen else None)

    _report(chosen)
    _emit(arrangement, audio, score.stem, settings)

    json_path = settings.output.dir / f"{score.stem}{ARRANGEMENT_SUFFIX}"
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
    out_dir: Optional[Path] = typer.Option(None, "-o", "--out-dir"),
    wav: Optional[bool] = typer.Option(
        None, "--wav/--ogg", help="Write uncompressed WAV instead of Ogg."
    ),
    target: Optional[str] = typer.Option(None, "--target", help=TARGET_HELP),
    preset: Optional[str] = typer.Option(None, "--preset", help=PRESET_HELP),
    config_path: Optional[Path] = typer.Option(
        None, "--config", exists=True, dir_okay=False, readable=True
    ),
) -> None:
    """Re-render a hand-edited arrangement, skipping analysis entirely.

    Only the [output] half of the config can matter here: everything musical
    was decided when the JSON was written, and this command obeys the file.
    """
    stem = _stem(arrangement)
    settings = _settings(
        arrangement.parent, stem, preset, config_path, out_dir, wav, target
    )
    loaded = Arrangement.from_json(arrangement.read_text())
    audio = render_audio(loaded, settings.output.sample_rate)
    _emit(loaded, audio, stem, settings)


def _stem(path: Path) -> str:
    """`foo.arrangement.json` re-renders to `foo.ogg`, not `foo.arrangement.ogg`."""
    if path.name.endswith(ARRANGEMENT_SUFFIX):
        return path.name[: -len(ARRANGEMENT_SUFFIX)]
    return path.stem
