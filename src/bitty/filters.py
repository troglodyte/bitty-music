"""Two IIR filters: the tone control and the safety net.

`lowpass` is the single biggest "make it warmer" control in the synth —
roughly the difference between NES harshness and SID-style warmth. It is off
by default (`Instrument.cutoff_hz is None`), because the spec's fidelity
target is chiptune, not chiptune-with-the-treble-off.
"""

import numpy as np
from scipy.signal import lfilter

DC_BLOCKER_POLE = 0.995
NYQUIST_MARGIN = 0.45  # keep the cutoff below this fraction of the sample rate


def lowpass(
    signal: np.ndarray, cutoff_hz: float, resonance: float, sample_rate: int
) -> np.ndarray:
    """Resonant second-order lowpass (RBJ biquad)."""
    w0 = 2.0 * np.pi * min(cutoff_hz, NYQUIST_MARGIN * sample_rate) / sample_rate
    alpha = np.sin(w0) / (2.0 * resonance)
    cos_w0 = np.cos(w0)

    b = np.array([(1.0 - cos_w0) / 2.0, 1.0 - cos_w0, (1.0 - cos_w0) / 2.0])
    a = np.array([1.0 + alpha, -2.0 * cos_w0, 1.0 - alpha])

    return lfilter(b / a[0], a / a[0], signal, axis=0)


def dc_block(signal: np.ndarray) -> np.ndarray:
    """Strip the constant offset that asymmetric pulse duties leave behind.

    A 12.5% duty pulse spends most of its cycle at -1, so its mean is well
    below zero. Summed across voices that offset eats headroom and, on some
    hardware, thumps the speaker.
    """
    return lfilter([1.0, -1.0], [1.0, -DC_BLOCKER_POLE], signal, axis=0)
