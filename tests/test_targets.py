"""Targets: a Render in, engine artifacts out."""

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


def test_a_ron_string_escapes_quotes_and_backslashes(tmp_path):
    assert targets._ron_str('say "hi"') == '"say \\"hi\\""'
    assert targets._ron_str("back\\slash") == '"back\\\\slash"'


def test_common_fields_render_bpm_as_a_float_and_bars_as_a_tuple():
    fields = dict(targets._common_fields(a_render()))

    assert fields["bpm"] == "120.0"
    assert fields["bars"] == "(1, 16)"


def test_common_fields_omit_bars_when_the_meta_has_none():
    """arrange writes bars only when the score had them (arrange.py:76)."""
    fields = dict(targets._common_fields(a_render(meta={"title": "t", "bpm": 90.0})))

    assert "bars" not in fields
    assert fields["bpm"] == "90.0"


def test_common_fields_fall_back_to_zero_bpm_on_a_hand_edited_arrangement():
    fields = dict(targets._common_fields(a_render(meta={})))

    assert fields["bpm"] == "0.0"


def test_the_title_falls_back_to_the_file_stem():
    assert targets._title(a_render(meta={}), "piece") == "piece"
    assert targets._title(a_render(), "piece") == "Minuet in G"


def test_a_fragment_is_one_indented_entry(tmp_path):
    path = targets._write_fragment(
        tmp_path, "piece", "bevy", targets._entry("piece", [("bpm", "120.0")])
    )

    assert path == tmp_path / "piece.bevy.ron"
    assert path.read_text() == '        "piece": (\n            bpm: 120.0,\n        ),\n'


def test_assemble_wraps_every_fragment_for_that_target(tmp_path):
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets._write_fragment(tmp_path, "b", "bevy", targets._entry("b", [("bpm", "2.0")]))

    manifest = targets.assemble(tmp_path, "bevy")

    assert manifest == tmp_path / "music.ron"
    text = manifest.read_text()
    assert text.startswith("(\n    tracks: {\n")
    assert text.endswith("    },\n)\n")
    assert '"a": (' in text and '"b": (' in text


def test_assembling_one_piece_never_drops_another(tmp_path):
    """The property the whole fragment design exists to guarantee."""
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets.assemble(tmp_path, "bevy")

    targets._write_fragment(tmp_path, "b", "bevy", targets._entry("b", [("bpm", "2.0")]))
    targets.assemble(tmp_path, "bevy")

    text = (tmp_path / "music.ron").read_text()
    assert '"a": (' in text
    assert '"b": (' in text


def test_re_emitting_a_piece_replaces_only_its_own_entry(tmp_path):
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets._write_fragment(tmp_path, "b", "bevy", targets._entry("b", [("bpm", "2.0")]))
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "9.0")]))

    text = targets.assemble(tmp_path, "bevy").read_text()

    assert "bpm: 9.0" in text
    assert "bpm: 1.0" not in text
    assert "bpm: 2.0" in text


def test_the_manifest_is_byte_stable_regardless_of_write_order(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    targets._write_fragment(tmp_path, "b", "bevy", targets._entry("b", [("bpm", "2.0")]))
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets._write_fragment(other, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets._write_fragment(other, "b", "bevy", targets._entry("b", [("bpm", "2.0")]))

    assert (
        targets.assemble(tmp_path, "bevy").read_text()
        == targets.assemble(other, "bevy").read_text()
    )


def test_assemble_ignores_another_targets_fragments(tmp_path):
    targets._write_fragment(tmp_path, "a", "bevy", targets._entry("a", [("bpm", "1.0")]))
    targets._write_fragment(tmp_path, "a", "bevy-kira", targets._entry("a", [("bpm", "9.0")]))

    text = targets.assemble(tmp_path, "bevy").read_text()

    assert "bpm: 1.0" in text
    assert "bpm: 9.0" not in text


def test_assemble_writes_nothing_when_there_are_no_fragments(tmp_path):
    assert targets.assemble(tmp_path, "generic") is None
    assert not (tmp_path / "music.ron").exists()
