import numpy as np

from bitty.arrangement import Instrument
from bitty.osc import oscillator

SAMPLE_RATE = 44100


def phase_for(freq: float, seconds: float = 1.0, sample_rate: int = SAMPLE_RATE):
    n = int(seconds * sample_rate)
    inc = np.full(n, freq / sample_rate)
    phase = np.concatenate(([0.0], np.cumsum(inc)[:-1]))
    return phase, inc


def dominant_frequency(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    spectrum = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1 / sample_rate)
    return float(freqs[int(np.argmax(spectrum))])


def alias_fraction(audio: np.ndarray, f0: float, sample_rate: int = SAMPLE_RATE) -> float:
    """Share of spectral energy sitting on bins that are not harmonics of f0.

    Aliased partials fold back to arbitrary frequencies, so energy off the
    harmonic grid is the direct measure of how badly an oscillator aliases.
    """
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
    freqs = np.fft.rfftfreq(len(audio), 1 / sample_rate)
    harmonic = np.zeros(len(freqs), dtype=bool)
    k = 1
    while f0 * k < sample_rate / 2:
        harmonic |= np.abs(freqs - f0 * k) < 30.0
        k += 1
    return float(np.sum(spectrum[~harmonic] ** 2) / np.sum(spectrum**2))


def test_every_wave_sounds_at_its_written_pitch():
    phase, inc = phase_for(440.0)
    for wave in ("pulse", "triangle", "saw"):
        audio = oscillator(wave)(phase, inc, Instrument(wave=wave))
        assert abs(dominant_frequency(audio) - 440.0) < 2.0, wave


def test_polyblep_pulse_aliases_far_less_than_a_naive_square():
    """The spec's stated reason for PolyBLEP: classical melodies live above 1 kHz."""
    phase, inc = phase_for(3520.0)
    naive = np.where(phase % 1.0 < 0.5, 1.0, -1.0)
    blep = oscillator("pulse")(phase, inc, Instrument(wave="pulse"))
    assert alias_fraction(blep, 3520.0) < alias_fraction(naive, 3520.0) / 10.0


def test_polyblep_saw_aliases_far_less_than_a_naive_ramp():
    phase, inc = phase_for(3520.0)
    naive = 2.0 * (phase % 1.0) - 1.0
    blep = oscillator("saw")(phase, inc, Instrument(wave="saw"))
    assert alias_fraction(blep, 3520.0) < alias_fraction(naive, 3520.0) / 10.0


def test_duty_cycle_changes_the_pulse_width():
    phase, inc = phase_for(440.0)
    narrow = oscillator("pulse")(phase, inc, Instrument(wave="pulse", duty=0.125))
    wide = oscillator("pulse")(phase, inc, Instrument(wave="pulse", duty=0.5))
    assert narrow.mean() < wide.mean() - 0.5


def test_oscillators_stay_within_range():
    phase, inc = phase_for(440.0)
    for wave in ("pulse", "triangle", "saw", "noise"):
        audio = oscillator(wave)(phase, inc, Instrument(wave=wave))
        assert np.max(np.abs(audio)) <= 1.35, wave


def test_triangle_quantization_crushes_to_discrete_levels():
    phase, inc = phase_for(440.0)
    crushed = oscillator("triangle")(phase, inc, Instrument(wave="triangle", quantize=16))
    assert len(np.unique(np.round(crushed, 6))) <= 17


def test_noise_is_seeded_and_therefore_deterministic():
    phase, inc = phase_for(440.0)
    first = oscillator("noise")(phase, inc, Instrument(wave="noise"))
    second = oscillator("noise")(phase, inc, Instrument(wave="noise"))
    assert np.array_equal(first, second)


def test_noise_is_actually_noisy():
    phase, inc = phase_for(440.0)
    audio = oscillator("noise")(phase, inc, Instrument(wave="noise"))
    assert alias_fraction(audio, 440.0) > 0.5


def test_unknown_wave_fails_loudly():
    phase, inc = phase_for(440.0)
    try:
        oscillator("bagpipe")
    except ValueError as error:
        assert "bagpipe" in str(error)
    else:
        raise AssertionError("expected ValueError")
