import json
from pathlib import Path

import soundfile as sf
from typer.testing import CliRunner

from bitty.arrangement import Arrangement
from bitty.cli import app

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"
runner = CliRunner()


def test_convert_writes_audio_and_arrangement(tmp_path):
    result = runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output

    wav = tmp_path / "two_part.wav"
    arrangement_json = tmp_path / "two_part.arrangement.json"
    assert wav.exists()
    assert arrangement_json.exists()


def test_converted_audio_has_the_expected_duration(tmp_path):
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    audio, sample_rate = sf.read(tmp_path / "two_part.wav")
    assert sample_rate == 44100
    assert abs(len(audio) / sample_rate - 2.0) < 0.01


def test_written_arrangement_reloads(tmp_path):
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    text = (tmp_path / "two_part.arrangement.json").read_text()
    arrangement = Arrangement.from_json(text)
    assert [c.role for c in arrangement.channels] == ["lead", "bass"]
    assert json.loads(text)["meta"]["bpm"] == 120.0


def test_missing_input_file_fails_loudly(tmp_path):
    result = runner.invoke(app, ["convert", str(tmp_path / "nope.musicxml"), "-o", str(tmp_path)])
    assert result.exit_code != 0
