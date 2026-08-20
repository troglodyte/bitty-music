import numpy as np

from bitty.filters import dc_block, lowpass

SAMPLE_RATE = 44100


def sine(freq: float, seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return np.sin(2.0 * np.pi * freq * t)


def rms(signal: np.ndarray) -> float:
    return float(np.sqrt(np.mean(signal**2)))


def gain(freq: float, cutoff: float, resonance: float = 0.7071) -> float:
    signal = sine(freq)
    return rms(lowpass(signal, cutoff, resonance, SAMPLE_RATE)) / rms(signal)


def test_the_passband_is_left_alone():
    assert gain(200.0, 1000.0) > 0.95


def test_the_cutoff_sits_at_minus_three_decibels():
    assert abs(gain(1000.0, 1000.0) - 0.7071) < 0.02


def test_the_stopband_is_strongly_attenuated():
    """Two octaves up should be down more than 20 dB — this is the warmth lever."""
    assert gain(4000.0, 1000.0) < 0.1


def test_resonance_peaks_the_cutoff():
    assert gain(1000.0, 1000.0, resonance=4.0) > gain(1000.0, 1000.0, resonance=0.7071) * 3


def test_the_filter_is_stable_on_a_very_high_cutoff():
    """Nyquist must not produce NaNs when someone hand-edits cutoff_hz upward."""
    out = lowpass(sine(440.0), 40000.0, 0.7071, SAMPLE_RATE)
    assert np.all(np.isfinite(out))


def test_the_filter_handles_stereo():
    stereo = np.stack([sine(200.0), sine(4000.0)], axis=1)
    out = lowpass(stereo, 1000.0, 0.7071, SAMPLE_RATE)
    assert out.shape == stereo.shape
    assert rms(out[:, 0]) > rms(out[:, 1]) * 5


def test_dc_blocker_removes_a_constant_offset():
    signal = 0.5 + 0.1 * sine(200.0)
    out = dc_block(signal)
    assert abs(np.mean(out[SAMPLE_RATE // 2:])) < 1e-4


def test_dc_blocker_keeps_the_audible_signal():
    signal = 0.5 + 0.1 * sine(200.0)
    out = dc_block(signal)
    assert rms(out - np.mean(out)) > 0.06
