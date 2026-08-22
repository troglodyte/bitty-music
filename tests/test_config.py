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
