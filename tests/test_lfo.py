import numpy as np
import pytest

from bitty.lfo import DELAY_SEC, DEPTH_CENTS, vibrato_cents

SR = 44100


def test_vibrato_is_silent_until_the_delay():
    """Vibrato from the instant of attack is the characteristic way this goes wrong."""
    cents = vibrato_cents(int(1.0 * SR), SR)
    assert np.all(cents[: int(DELAY_SEC * SR)] == 0.0)


def test_vibrato_reaches_full_depth_on_a_long_note():
    cents = vibrato_cents(int(3.0 * SR), SR)
    assert np.max(np.abs(cents)) == pytest.approx(DEPTH_CENTS, rel=0.02)


def test_vibrato_never_exceeds_its_depth():
    cents = vibrato_cents(int(3.0 * SR), SR)
    assert np.all(np.abs(cents) <= DEPTH_CENTS + 1e-9)


def test_vibrato_fades_in_rather_than_switching_on():
    """A step change in pitch at the delay would click."""
    cents = vibrato_cents(int(1.0 * SR), SR)
    start = int(DELAY_SEC * SR)
    just_after = np.max(np.abs(cents[start : start + int(0.01 * SR)]))
    assert 0.0 < just_after < DEPTH_CENTS / 2.0


def test_vibrato_is_deterministic():
    assert np.array_equal(vibrato_cents(1000, SR), vibrato_cents(1000, SR))


def test_a_note_shorter_than_the_delay_gets_no_vibrato():
    assert np.all(vibrato_cents(int(0.2 * SR), SR) == 0.0)
