"""Waveform generation. Pure numpy, no knowledge of arrangements or time.

Every oscillator has the same signature: unwrapped cumulative `phase` in
cycles, the per-sample increment `inc` that produced it, and the `Instrument`
carrying the timbre knobs. Returning to `inc` rather than a scalar frequency is
what lets pitch envelopes work — a note that bends is just a varying increment.
"""

from collections.abc import Callable

import numpy as np

from bitty.arrangement import Instrument

NOISE_SEED = 1
LFSR_WIDTH = 15


def oscillator(name: str) -> Callable[[np.ndarray, np.ndarray, Instrument], np.ndarray]:
    try:
        return _OSCILLATORS[name]
    except KeyError:
        raise ValueError(f"unknown wave {name!r}") from None


def poly_blep(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """The correction that turns a sampled step into a bandlimited one.

    A naive square jumps between two samples, which is an infinitely sharp
    edge and therefore infinite bandwidth — everything above Nyquist folds
    back down as inharmonic junk. This adds a two-sample polynomial ramp
    around each discontinuity, which is the cheapest good approximation of
    the bandlimited step. Roughly twenty lines for most of the defined sound.
    """
    out = np.zeros_like(t)

    rising = t < dt
    x = t[rising] / dt[rising]
    out[rising] = x + x - x * x - 1.0

    falling = t > 1.0 - dt
    x = (t[falling] - 1.0) / dt[falling]
    out[falling] = x * x + x + x + 1.0

    return out


def _pulse(phase: np.ndarray, inc: np.ndarray, instrument: Instrument) -> np.ndarray:
    duty = instrument.duty
    wrapped = phase % 1.0
    out = np.where(wrapped < duty, 1.0, -1.0)
    out = out + poly_blep(wrapped, inc)
    out = out - poly_blep((wrapped - duty) % 1.0, inc)
    return out


def _saw(phase: np.ndarray, inc: np.ndarray, instrument: Instrument) -> np.ndarray:
    wrapped = phase % 1.0
    return 2.0 * wrapped - 1.0 - poly_blep(wrapped, inc)


def _triangle(phase: np.ndarray, inc: np.ndarray, instrument: Instrument) -> np.ndarray:
    """No PolyBLEP here, deliberately.

    A triangle is continuous — only its slope jumps — so its harmonics fall
    off as 1/n^2 instead of 1/n and the aliasing is far below the noise floor
    of everything else in the mix. The spec asks for bandlimiting on pulse and
    saw specifically.
    """
    out = 4.0 * np.abs((phase + 0.25) % 1.0 - 0.5) - 1.0
    if instrument.quantize:
        steps = instrument.quantize
        out = np.round(out * (steps / 2)) / (steps / 2)
    return out


def _noise(phase: np.ndarray, inc: np.ndarray, instrument: Instrument) -> np.ndarray:
    """Seeded 15-bit LFSR, clocked once per phase cycle — the NES noise channel."""
    step = np.floor(phase).astype(np.int64)
    bits = _lfsr_bits(int(step[-1]) + 1 if len(step) else 0)
    return bits[step]


def _lfsr_bits(count: int) -> np.ndarray:
    register = NOISE_SEED
    bits = np.empty(count, dtype=np.float64)
    for i in range(count):
        bits[i] = 1.0 if register & 1 else -1.0
        feedback = (register ^ (register >> 1)) & 1
        register = (register >> 1) | (feedback << (LFSR_WIDTH - 1))
    return bits


_OSCILLATORS = {
    "pulse": _pulse,
    "triangle": _triangle,
    "saw": _saw,
    "noise": _noise,
}
