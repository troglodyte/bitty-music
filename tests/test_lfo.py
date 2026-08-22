import numpy as np
import pytest

from bitty.arrangement import VIBRATO_CENTS, VIBRATO_DELAY
from bitty.lfo import vibrato_cents

SR = 44100


def test_vibrato_is_silent_until_the_delay():
    """Vibrato from the instant of attack is the characteristic way this goes wrong."""
    cents = vibrato_cents(int(1.0 * SR), SR)
    assert np.all(cents[: int(VIBRATO_DELAY * SR)] == 0.0)


def test_vibrato_reaches_full_depth_on_a_long_note():
    cents = vibrato_cents(int(3.0 * SR), SR)
    assert np.max(np.abs(cents)) == pytest.approx(VIBRATO_CENTS, rel=0.02)


def test_vibrato_never_exceeds_its_depth():
    cents = vibrato_cents(int(3.0 * SR), SR)
    assert np.all(np.abs(cents) <= VIBRATO_CENTS + 1e-9)


def test_vibrato_fades_in_rather_than_switching_on():
    """A step change in pitch at the delay would click."""
    cents = vibrato_cents(int(1.0 * SR), SR)
    start = int(VIBRATO_DELAY * SR)
    just_after = np.max(np.abs(cents[start : start + int(0.01 * SR)]))
    assert 0.0 < just_after < VIBRATO_CENTS / 2.0


def test_vibrato_is_deterministic():
    assert np.array_equal(vibrato_cents(1000, SR), vibrato_cents(1000, SR))


def test_a_note_shorter_than_the_delay_gets_no_vibrato():
    assert np.all(vibrato_cents(int(0.2 * SR), SR) == 0.0)


def test_a_deeper_instrument_swings_further():
    shallow = vibrato_cents(44100, 44100, depth_cents=10.0)
    deep = vibrato_cents(44100, 44100, depth_cents=50.0)
    assert np.max(np.abs(deep)) > 4.0 * np.max(np.abs(shallow))


def test_a_longer_delay_stays_silent_longer():
    """Before the delay elapses the depth clips to zero, exactly."""
    late = vibrato_cents(44100, 44100, delay_sec=0.8)
    assert np.array_equal(late[: int(0.8 * 44100)], np.zeros(int(0.8 * 44100)))


def crossings(wave):
    return int(np.count_nonzero(np.diff(np.sign(wave))))


def test_a_faster_rate_crosses_zero_more_often():
    slow = vibrato_cents(44100, 44100, delay_sec=0.0, rate_hz=2.0)
    fast = vibrato_cents(44100, 44100, delay_sec=0.0, rate_hz=8.0)
    assert crossings(fast) > 3 * crossings(slow)
