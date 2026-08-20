import json
from pathlib import Path

import numpy as np

import soundfile as sf
from typer.testing import CliRunner

from bitty.arrangement import Arrangement
from bitty.cli import app

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"
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
