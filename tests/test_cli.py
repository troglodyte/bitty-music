import json
import shutil
from pathlib import Path

import numpy as np

import soundfile as sf
from typer.testing import CliRunner

from bitty.arrangement import Arrangement
from bitty.cli import app

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"
CHORALE = Path(__file__).parent / "fixtures" / "chorale.mxl"
MINUET = Path(__file__).parent / "fixtures" / "minuet.mxl"
runner = CliRunner()


def test_convert_writes_ogg_and_arrangement(tmp_path):
    result = runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "two_part.ogg").exists()
    assert (tmp_path / "two_part.arrangement.json").exists()


def test_converted_audio_is_stereo_at_the_expected_duration(tmp_path):
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    audio, sample_rate = sf.read(tmp_path / "two_part.ogg")
    assert sample_rate == 44100
    assert audio.ndim == 2 and audio.shape[1] == 2
    assert abs(len(audio) / sample_rate - 2.375) < 0.1


def test_wav_flag_writes_uncompressed_instead(tmp_path):
    result = runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path), "--wav"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "two_part.wav").exists()
    assert not (tmp_path / "two_part.ogg").exists()


def test_the_written_ogg_is_audible(tmp_path):
    """Guards the whole chain: a silent file passes every shape assertion."""
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    audio, _ = sf.read(tmp_path / "two_part.ogg")
    assert 0.01 < float(np.max(np.abs(audio))) <= 1.0


def test_written_arrangement_reloads(tmp_path):
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    text = (tmp_path / "two_part.arrangement.json").read_text()
    arrangement = Arrangement.from_json(text)
    assert [c.role for c in arrangement.channels] == ["lead", "bass"]
    assert json.loads(text)["meta"]["bpm"] == 120.0


def test_missing_input_file_fails_loudly(tmp_path):
    result = runner.invoke(app, ["convert", str(tmp_path / "nope.musicxml"), "-o", str(tmp_path)])
    assert result.exit_code != 0


def test_render_reproduces_the_audio_from_an_arrangement(tmp_path):
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path), "--wav"])
    before, _ = sf.read(tmp_path / "two_part.wav")
    (tmp_path / "two_part.wav").unlink()

    result = runner.invoke(
        app, ["render", str(tmp_path / "two_part.arrangement.json"), "-o", str(tmp_path), "--wav"]
    )

    assert result.exit_code == 0, result.output
    after, _ = sf.read(tmp_path / "two_part.wav")
    assert np.array_equal(before, after)


def test_render_names_the_output_after_the_piece(tmp_path):
    """`foo.arrangement.json` re-renders to `foo.wav`, not `foo.arrangement.wav`."""
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    runner.invoke(
        app, ["render", str(tmp_path / "two_part.arrangement.json"), "-o", str(tmp_path), "--wav"]
    )
    assert (tmp_path / "two_part.wav").exists()
    assert not (tmp_path / "two_part.arrangement.wav").exists()


def test_a_hand_edited_arrangement_renders_without_reanalysis(tmp_path):
    """The whole point of the split: the JSON overrules the arranger."""
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    path = tmp_path / "two_part.arrangement.json"
    data = json.loads(path.read_text())
    data["channels"] = data["channels"][:1]
    path.write_text(json.dumps(data))

    result = runner.invoke(app, ["render", str(path), "-o", str(tmp_path), "--wav"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "two_part.wav").exists()


def test_render_rejects_a_missing_arrangement(tmp_path):
    result = runner.invoke(
        app, ["render", str(tmp_path / "nope.arrangement.json"), "-o", str(tmp_path)]
    )
    assert result.exit_code != 0


def test_sections_reports_the_two_halves_of_the_minuet():
    result = runner.invoke(app, ["sections", str(MINUET)])
    assert result.exit_code == 0, result.output
    assert "bars   1-8" in result.output
    assert "bars   9-16" in result.output
    assert "G major" in result.output
    assert "D major" in result.output
    assert result.output.count("repeat") == 3


def test_sections_header_carries_the_tempo_and_length():
    result = runner.invoke(app, ["sections", str(MINUET)])
    assert "q=120" in result.output
    assert "16 bars" in result.output
    assert "24.0s" in result.output


def test_sections_reports_an_unmarked_score_as_one_section():
    """A hymn with no repeat marks has no interior structure to find."""
    result = runner.invoke(app, ["sections", str(CHORALE)])
    assert result.exit_code == 0, result.output
    assert "bars   1-8" in result.output
    assert "repeat" not in result.output


RAGTIME = Path(__file__).parent / "fixtures" / "ragtime.mxl"


def loaded(tmp_path, stem):
    return Arrangement.from_json((tmp_path / f"{stem}.arrangement.json").read_text())


def test_convert_records_the_loop_it_found(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path)])
    arrangement = loaded(tmp_path, "minuet")
    assert arrangement.loop is not None
    assert (arrangement.loop.start_sec, arrangement.loop.end_sec) == (0.0, 12.0)


def test_convert_reports_the_pick_and_why(tmp_path):
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path)])
    assert "bars 1-8" in result.output
    assert "repeat marks, seam ok" in result.output


def test_a_score_too_short_to_loop_gets_no_loop_and_says_so(tmp_path):
    result = runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert loaded(tmp_path, "two_part").loop is None
    assert "no loop" in result.output.lower()


def test_bars_narrows_the_arrangement_to_the_printed_range(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--bars", "9-16"])
    arrangement = loaded(tmp_path, "minuet")
    assert arrangement.meta["bars"] == [9, 16]
    assert min(e.t for c in arrangement.channels for e in c.events) < 1.0  # rebased


def test_loop_from_overrides_the_cascade(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--loop-from", "9"])
    assert loaded(tmp_path, "minuet").loop.start_sec == 12.0


def test_loop_from_is_honoured_even_when_the_seam_is_poor(tmp_path):
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--loop-from", "16"])
    assert result.exit_code == 0, result.output
    assert loaded(tmp_path, "minuet").loop.start_sec == 22.5


def test_a_malformed_bar_range_is_rejected(tmp_path):
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--bars", "nine"])
    assert result.exit_code != 0
    assert "9-16" in result.output or "N-M" in result.output


def test_a_bar_range_outside_the_score_is_rejected(tmp_path):
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--bars", "40-50"])
    assert result.exit_code != 0


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


def test_sections_prints_the_auto_loop_pick():
    result = runner.invoke(app, ["sections", str(MINUET)])
    assert result.exit_code == 0, result.output
    assert "auto-loop pick: bars 1-8" in result.output
    assert "repeat marks, seam ok" in result.output


def test_the_printed_pick_is_the_one_convert_would_write(tmp_path):
    """Rendering makes the report slow. It is worth it only if it is true."""
    printed = runner.invoke(app, ["sections", str(RAGTIME)]).output
    converted = runner.invoke(app, ["convert", str(RAGTIME), "-o", str(tmp_path)]).output
    assert "auto-loop pick: bars 1-16" in printed
    assert "loop: bars 1-16" in converted
    written = loaded(tmp_path, "ragtime").loop
    assert (written.start_sec, round(written.end_sec, 2)) == (0.0, 19.2)


def test_sections_says_so_when_nothing_can_loop():
    result = runner.invoke(app, ["sections", str(FIXTURE)])
    assert "no loop" in result.output.lower()


def scored(tmp_path, name="two_part"):
    """Copy a fixture somewhere writable so config files can sit beside it."""
    target = tmp_path / f"{name}.musicxml"
    shutil.copy(FIXTURE, target)
    return target


def test_a_config_file_beside_the_score_changes_the_output_format(tmp_path):
    score = scored(tmp_path)
    (tmp_path / "bitty.toml").write_text('[output]\nformat = "wav"\n')
    result = runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "two_part.wav").exists()


def test_a_flag_beats_the_config_file(tmp_path):
    score = scored(tmp_path)
    (tmp_path / "bitty.toml").write_text('[output]\nformat = "wav"\n')
    result = runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "out"), "--ogg"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "two_part.ogg").exists()
    assert not (tmp_path / "out" / "two_part.wav").exists()


def test_the_out_dir_can_come_from_config(tmp_path, monkeypatch):
    """A relative [output] dir resolves against the CWD, not the config file's own directory.

    The config lives two directories above the score, and the run happens
    from a third directory unrelated to either — so a wrong implementation
    that resolved `dir` relative to the config file (or the score) would
    write nowhere near where this test looks.
    """
    project = tmp_path / "project"
    scores_dir = project / "assets" / "scores"
    scores_dir.mkdir(parents=True)
    score = scores_dir / "two_part.musicxml"
    shutil.copy(FIXTURE, score)
    (project / "bitty.toml").write_text('[output]\ndir = "built"\n')

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    result = runner.invoke(app, ["convert", str(score)])
    assert result.exit_code == 0, result.output
    assert (workspace / "built" / "two_part.ogg").exists()
    assert not (project / "built").exists()


def test_a_config_file_can_choose_the_target(tmp_path):
    """generic writes no fragment, so the directory never grows a manifest."""
    score = scored(tmp_path)
    out = tmp_path / "out"
    (tmp_path / "bitty.toml").write_text('[output]\ntarget = "generic"\n')
    result = runner.invoke(app, ["convert", str(score), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "two_part.ogg").exists()
    assert not (out / "music.ron").exists()
    assert not list(out.glob("*.bevy.ron"))


def test_a_bad_config_aborts_before_anything_is_written(tmp_path):
    score = scored(tmp_path)
    out = tmp_path / "out"
    (tmp_path / "bitty.toml").write_text("[echo]\nlevl = 0.5\n")
    result = runner.invoke(app, ["convert", str(score), "-o", str(out)])
    assert result.exit_code != 0
    assert "echo.levl" in result.output
    assert not out.exists(), "nothing is written before the config resolves"


def test_an_unknown_target_in_config_is_reported(tmp_path):
    score = scored(tmp_path)
    (tmp_path / "bitty.toml").write_text('[output]\ntarget = "nintendo"\n')
    result = runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "out")])
    assert result.exit_code != 0
    assert "nintendo" in result.output


def test_a_preset_changes_the_arrangement(tmp_path):
    score = scored(tmp_path)
    runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "plain")])
    runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "nes"), "--preset", "nes-tight"])
    plain = Arrangement.from_json((tmp_path / "plain" / "two_part.arrangement.json").read_text())
    nes = Arrangement.from_json((tmp_path / "nes" / "two_part.arrangement.json").read_text())
    assert any(c.echo is not None for c in plain.channels)
    assert all(c.echo is None for c in nes.channels), "nes-tight turns the echo off"


def test_an_unknown_preset_lists_the_ones_that_exist(tmp_path):
    score = scored(tmp_path)
    result = runner.invoke(app, ["convert", str(score), "--preset", "chunky"])
    assert result.exit_code != 0
    assert "nes-tight" in result.output


def test_an_explicit_config_path_is_used(tmp_path):
    score = scored(tmp_path)
    elsewhere = tmp_path / "shared.toml"
    elsewhere.write_text('[output]\nformat = "wav"\n')
    result = runner.invoke(
        app, ["convert", str(score), "-o", str(tmp_path / "out"), "--config", str(elsewhere)]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "two_part.wav").exists()


def test_render_reads_the_config_beside_the_arrangement(tmp_path):
    score = scored(tmp_path)
    runner.invoke(app, ["convert", str(score), "-o", str(tmp_path)])
    (tmp_path / "bitty.toml").write_text('[output]\nformat = "wav"\n')
    result = runner.invoke(
        app, ["render", str(tmp_path / "two_part.arrangement.json"), "-o", str(tmp_path / "out")]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "two_part.wav").exists()


def test_sections_takes_a_preset_without_complaint(tmp_path):
    score = tmp_path / "minuet.mxl"
    shutil.copy(MINUET, score)
    result = runner.invoke(app, ["sections", str(score), "--preset", "lush"])
    assert result.exit_code == 0, result.output


def test_a_configured_sample_rate_reaches_the_written_file(tmp_path):
    score = scored(tmp_path)
    (tmp_path / "bitty.toml").write_text('[output]\nformat = "wav"\nsample_rate = 22050\n')
    runner.invoke(app, ["convert", str(score), "-o", str(tmp_path / "out")])
    _, rate = sf.read(tmp_path / "out" / "two_part.wav")
    assert rate == 22050


def a_config(tmp_path, body):
    path = tmp_path / "sweep.toml"
    path.write_text(body)
    return str(path)


def test_convert_obeys_the_transform_table(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path)])
    plain = Arrangement.from_json((tmp_path / "minuet.arrangement.json").read_text())

    shifted_dir = tmp_path / "up"
    result = runner.invoke(
        app,
        [
            "convert", str(MINUET), "-o", str(shifted_dir),
            "--config", a_config(tmp_path, "[transform]\ntranspose = 3\n"),
        ],
    )
    assert result.exit_code == 0, result.output
    shifted = Arrangement.from_json((shifted_dir / "minuet.arrangement.json").read_text())

    def pitches(arrangement):
        return [e.pitch for c in arrangement.channels for e in c.events]

    assert pitches(shifted) == [pitch + 3 for pitch in pitches(plain)]


def test_convert_obeys_the_tempo_scale(tmp_path):
    """`--target generic` so the audio lands in one file whatever the loop did.

    The bevy default names its output after the loop it found
    (`minuet_loop.wav`), and `tempo_scale` is allowed to change which
    candidate wins — see the loop risk in the design. Asserting on a filename
    that depends on the thing under test is how a test starts failing for the
    wrong reason.
    """
    result = runner.invoke(
        app,
        [
            "convert", str(MINUET), "-o", str(tmp_path), "--wav", "--target", "generic",
            "--config", a_config(tmp_path, "[transform]\ntempo_scale = 2.0\n"),
        ],
    )
    assert result.exit_code == 0, result.output
    written = Arrangement.from_json((tmp_path / "minuet.arrangement.json").read_text())
    assert written.meta["bpm"] == 240.0

    audio, sample_rate = sf.read(tmp_path / "minuet.wav")
    # The untransformed generic render is 24.4s; halving the tempo halves the
    # music and the echo with it, so anything near 24s means bpm moved alone.
    assert 10.0 < len(audio) / sample_rate < 15.0


def test_sections_reports_the_key_it_was_transposed_into(tmp_path):
    """Key detection needs no special-casing: `analyze` sees the new pitches."""
    plain = runner.invoke(app, ["sections", str(MINUET)])
    assert "G major" in plain.output and "D major" in plain.output

    result = runner.invoke(
        app,
        ["sections", str(MINUET), "--config", a_config(tmp_path, "[transform]\ntranspose = 2\n")],
    )
    assert result.exit_code == 0, result.output
    assert "A major" in result.output and "E major" in result.output


def test_a_transpose_that_does_not_fit_is_refused_by_name(tmp_path):
    result = runner.invoke(
        app,
        [
            "convert", str(MINUET), "-o", str(tmp_path),
            "--config", a_config(tmp_path, "[transform]\ntranspose = 21\n"),
        ],
        # Click wraps BadParameter into a rich box at the terminal width, and a
        # pytest tmp_path is long enough that the config path splits mid-token
        # at the default 80 columns. A wide terminal keeps it one piece.
        env={"COLUMNS": "200"},
    )
    assert result.exit_code != 0
    assert "past the playable ceiling" in result.output
    assert "at most +20" in result.output
    assert "sweep.toml" in result.output, "the CLI knows the provenance; say it"


def test_render_does_not_transform(tmp_path):
    """The contract that makes one transform site safe.

    Everything musical was decided when the JSON was written. If `render`
    applied `[transform]` too, this convert-at-+3 would re-render at +6 and the
    two files would differ.
    """
    config = a_config(tmp_path, "[transform]\ntranspose = 3\ntempo_scale = 1.25\n")
    runner.invoke(
        app,
        [
            "convert", str(MINUET), "-o", str(tmp_path), "--wav",
            "--target", "generic", "--config", config,
        ],
    )
    before = (tmp_path / "minuet.wav").read_bytes()
    (tmp_path / "minuet.wav").unlink()

    result = runner.invoke(
        app,
        [
            "render", str(tmp_path / "minuet.arrangement.json"),
            "-o", str(tmp_path), "--wav", "--target", "generic", "--config", config,
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "minuet.wav").read_bytes() == before
