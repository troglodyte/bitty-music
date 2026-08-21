"""A delayed vibrato LFO: the sustain-time counterpart to the attack blip.

Separate from `envelope` on purpose. That module is tracker-style step
sequences and says so as a stylistic commitment; this is a continuous sine,
which is exactly the thing that commitment excludes.

Chip voices have no natural decay, so a held note is dead air. The delay is
what keeps the cure from sounding seasick: vibrato present from the instant of
attack is the characteristic way this effect goes wrong.
"""

import numpy as np

DEPTH_CENTS = 25.0  # the spec's [vibrato] depth_cents
DELAY_SEC = 0.3  # the spec's [vibrato] delay_ms
MIN_NOTE_SEC = 0.5  # the spec's [vibrato] min_note_ms; the arranger's threshold
RATE_HZ = 5.5  # not in the spec's config table; a conventional musical rate
FADE_SEC = 0.15  # a step change in pitch would click


def vibrato_cents(length: int, sample_rate: int) -> np.ndarray:
    """Per-sample pitch offset in cents: silent, then fading in to full depth."""
    if length <= 0:
        return np.zeros(0, dtype=np.float64)

    t = np.arange(length, dtype=np.float64) / sample_rate
    depth = np.clip((t - DELAY_SEC) / FADE_SEC, 0.0, 1.0) * DEPTH_CENTS
    return depth * np.sin(2.0 * np.pi * RATE_HZ * t)
