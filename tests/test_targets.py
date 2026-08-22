"""Targets: a Render in, engine artifacts out."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from mutagen.oggvorbis import OggVorbis

from bitty.synth import Render
from bitty import targets

META = {"title": "Minuet in G", "bpm": 120.0, "bars": [1, 16]}


def a_render(loop=(1.0, 2.0), meta=META, seconds=3.0, sample_rate=44100):
    """Silent stereo audio is enough: no target inspects sample values."""
    audio = np.zeros((int(sample_rate * seconds), 2), dtype=np.float32)
    start = end = None
    if loop is not None:
        start = round(loop[0] * sample_rate)
        end = round(loop[1] * sample_rate)
    return Render(
        audio=audio,
        sample_rate=sample_rate,
        meta=dict(meta),
        loop_start_sample=start,
        loop_end_sample=end,
    )


def test_write_audio_writes_an_ogg_by_default(tmp_path):
    path = targets.write_audio(a_render().audio, tmp_path, "piece")

    assert path == tmp_path / "piece.ogg"
    assert path.exists()


def test_write_audio_writes_a_wav_when_asked(tmp_path):
    path = targets.write_audio(a_render().audio, tmp_path, "piece", "wav")

    assert path == tmp_path / "piece.wav"
    audio, rate = sf.read(path)
    assert rate == 44100
    assert audio.shape[1] == 2


def test_write_audio_creates_the_output_directory(tmp_path):
    nested = tmp_path / "deep" / "deeper"

    path = targets.write_audio(a_render().audio, nested, "piece")

    assert path.exists()


def test_generic_writes_one_file_and_no_manifest(tmp_path):
    written = targets.TARGETS["generic"](a_render(), tmp_path, "piece")

    assert written == [tmp_path / "piece.ogg"]
    assert not (tmp_path / "music.ron").exists()
    assert list(tmp_path.glob("*.ron")) == []


def test_generic_tags_the_loop_in_samples(tmp_path):
    targets.TARGETS["generic"](a_render(loop=(1.0, 2.0)), tmp_path, "piece")

    tags = OggVorbis(tmp_path / "piece.ogg")
    assert tags["LOOPSTART"] == ["44100"]
    assert tags["LOOPLENGTH"] == ["44100"]


def test_generic_writes_no_loop_tags_when_there_is_no_loop(tmp_path):
    targets.TARGETS["generic"](a_render(loop=None), tmp_path, "piece")

    tags = OggVorbis(tmp_path / "piece.ogg")
    assert "LOOPSTART" not in tags


def test_generic_as_wav_skips_the_tags_rather_than_failing(tmp_path):
    """WAV has nowhere to put a Vorbis comment. The sidecar still has the loop."""
    written = targets.TARGETS["generic"](a_render(), tmp_path, "piece", audio_format="wav")

    assert written == [tmp_path / "piece.wav"]
