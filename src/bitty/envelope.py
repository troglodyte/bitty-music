"""Tracker-style step envelopes: a list of levels, one per 60th of a second.

Not ADSR, on purpose. Step sequences are the native chiptune idiom, they match
the 16 dynamic levels the spec quantizes to, and they read as plain numbers in
`arrangement.json` where someone can edit them.
"""

import numpy as np

ENV_RATE_HZ = 60.0


def step_values(steps: tuple[int, ...], length: int, sample_rate: int) -> np.ndarray:
    """Expand a step sequence to one value per sample, sustaining the last step."""
    if not steps:
        return np.ones(length, dtype=np.float64)

    samples_per_step = sample_rate / ENV_RATE_HZ
    index = (np.arange(length, dtype=np.float64) / samples_per_step).astype(np.int64)
    index = np.minimum(index, len(steps) - 1)
    return np.asarray(steps, dtype=np.float64)[index]
