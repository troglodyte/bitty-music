from pathlib import Path

from bitty import arrangement, lfo, synth, voices
from bitty.arrange import ARP_STEP_SEC
from bitty.config import DEFAULTS
from bitty.loop import MIN_LOOP_BARS, SEAM_RATIO


def test_defaults_match_the_constants_they_replace():
    """The guard that lets every other test in the suite stay untouched.

    Some of these values live in modules config cannot import, because those
    modules import config. This assertion is the seam that keeps the two
    copies honest.
    """
    assert DEFAULTS.echo.delay_beats == voices.ECHO_BEATS
    assert DEFAULTS.echo.level == voices.ECHO_LEVEL
    assert DEFAULTS.vibrato.depth_cents == arrangement.VIBRATO_CENTS
    assert DEFAULTS.vibrato.delay_sec == arrangement.VIBRATO_DELAY
    assert DEFAULTS.vibrato.rate_hz == arrangement.VIBRATO_RATE_HZ
    assert DEFAULTS.vibrato.min_note_sec == lfo.MIN_NOTE_SEC
    assert DEFAULTS.arp.step_sec == ARP_STEP_SEC
    assert DEFAULTS.loop.min_bars == MIN_LOOP_BARS
    assert DEFAULTS.loop.seam_ratio == SEAM_RATIO
    assert DEFAULTS.output.sample_rate == synth.SAMPLE_RATE
    assert DEFAULTS.voices == voices.ROSTER


def test_the_defaults_describe_the_shipped_behaviour():
    assert DEFAULTS.echo.on is True
    assert DEFAULTS.output.target == "bevy"
    assert DEFAULTS.output.format == "ogg"
    assert DEFAULTS.output.dir == Path("out")


import pytest

from bitty.config import ConfigError, merge


def test_a_value_from_a_file_beats_the_default():
    result = merge(DEFAULTS, "[echo]\nlevel = 0.9\n", "bitty.toml")
    assert result.echo.level == 0.9
    assert result.echo.delay_beats == DEFAULTS.echo.delay_beats, "untouched keys survive"


def test_milliseconds_become_seconds():
    text = "[vibrato]\ndelay_ms = 300\nmin_note_ms = 750\n\n[arp]\nrate_ms = 20\n"
    result = merge(DEFAULTS, text, "bitty.toml")
    assert result.vibrato.delay_sec == 0.3
    assert result.vibrato.min_note_sec == 0.75
    assert result.arp.step_sec == 0.02


def test_an_unknown_key_names_the_file_the_key_and_the_alternatives():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[echo]\nlevl = 0.5\n", "bitty.toml")
    message = str(caught.value)
    assert "bitty.toml" in message
    assert "echo.levl" in message
    assert "level" in message, "a typo should be told what it nearly was"


def test_an_unknown_table_is_refused():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[reverb]\non = true\n", "bitty.toml")
    assert "reverb" in str(caught.value)


def test_a_value_over_its_range_is_refused():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[echo]\nlevel = 3.0\n", "bitty.toml")
    assert "echo.level" in str(caught.value)
    assert "at most 1.0" in str(caught.value)


def test_a_value_of_the_wrong_type_is_refused():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, '[echo]\nlevel = "loud"\n', "bitty.toml")
    assert "expected a number" in str(caught.value)


def test_true_is_not_a_number():
    """bool is an int in Python; a config file should not get away with it."""
    with pytest.raises(ConfigError):
        merge(DEFAULTS, "[echo]\nlevel = true\n", "bitty.toml")


def test_a_whole_number_field_refuses_a_fraction():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[loop]\nmin_bars = 8.5\n", "bitty.toml")
    assert "whole number" in str(caught.value)


def test_broken_toml_names_the_file():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[echo\nlevel = 0.5\n", "bitty.toml")
    assert "bitty.toml" in str(caught.value)
    assert "not valid TOML" in str(caught.value)


def test_the_format_key_accepts_only_the_two_it_can_write():
    assert merge(DEFAULTS, '[output]\nformat = "wav"\n', "x").output.format == "wav"
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, '[output]\nformat = "flac"\n', "x")
    assert "ogg, wav" in str(caught.value)


def test_the_out_dir_becomes_a_path():
    assert merge(DEFAULTS, '[output]\ndir = "build/audio"\n', "x").output.dir == Path("build/audio")
