import json
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


def test_split_writes_an_intro_and_a_loop(tmp_path):
    result = runner.invoke(
        app, ["convert", str(MINUET), "-o", str(tmp_path), "--wav", "--split", "--loop-from", "9"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "minuet_intro.wav").exists()
    assert (tmp_path / "minuet_loop.wav").exists()


def test_the_split_pieces_have_the_durations_the_loop_names(tmp_path):
    runner.invoke(
        app, ["convert", str(MINUET), "-o", str(tmp_path), "--wav", "--split", "--loop-from", "9"]
    )
    intro, _ = sf.read(tmp_path / "minuet_intro.wav")
    body, _ = sf.read(tmp_path / "minuet_loop.wav")
    assert abs(len(intro) / 44100 - 12.0) < 0.01
    assert abs(len(body) / 44100 - 12.0) < 0.01


def test_a_loop_starting_at_zero_writes_no_intro(tmp_path):
    result = runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--wav", "--split"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "minuet_intro.wav").exists()
    assert (tmp_path / "minuet_loop.wav").exists()
    assert "no intro" in result.output.lower()


def test_split_without_a_loop_is_a_hard_error(tmp_path):
    """Asking for a split is asking for a loop. A warning here gets missed.

    Checked before any output is written, so a failed --split leaves nothing
    behind — not a stray .ogg with no .arrangement.json beside it.
    """
    result = runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path), "--split"])
    assert result.exit_code == 1
    assert "--loop-from" in result.output
    assert list(tmp_path.iterdir()) == []


def test_render_can_split_a_hand_edited_arrangement(tmp_path):
    runner.invoke(app, ["convert", str(MINUET), "-o", str(tmp_path), "--loop-from", "9"])
    result = runner.invoke(
        app,
        ["render", str(tmp_path / "minuet.arrangement.json"), "-o", str(tmp_path),
         "--wav", "--split"],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "minuet_loop.wav").exists()


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
