"""A delayed vibrato LFO: the sustain-time counterpart to the attack blip.

Separate from `envelope` on purpose. That module is tracker-style step
sequences and says so as a stylistic commitment; this is a continuous sine,
which is exactly the thing that commitment excludes.

Chip voices have no natural decay, so a held note is dead air. The delay is
what keeps the cure from sounding seasick: vibrato present from the instant of
attack is the characteristic way this effect goes wrong.
"""

import numpy as np

from bitty.arrangement import VIBRATO_CENTS, VIBRATO_DELAY, VIBRATO_RATE_HZ

MIN_NOTE_SEC = 0.5  # the spec's [vibrato] min_note_ms; the arranger's threshold
FADE_SEC = 0.15  # a step change in pitch would click


def vibrato_cents(
    length: int,
    sample_rate: int,
    depth_cents: float = VIBRATO_CENTS,
    delay_sec: float = VIBRATO_DELAY,
    rate_hz: float = VIBRATO_RATE_HZ,
) -> np.ndarray:
    """Per-sample pitch offset in cents: silent, then fading in to full depth.

    The shape comes from the instrument now. The defaults are here so a caller
    that has no instrument — a test, a probe — still gets the house sound.
    """
    if length <= 0:
        return np.zeros(0, dtype=np.float64)

    t = np.arange(length, dtype=np.float64) / sample_rate
    depth = np.clip((t - delay_sec) / FADE_SEC, 0.0, 1.0) * depth_cents
    return depth * np.sin(2.0 * np.pi * rate_hz * t)
