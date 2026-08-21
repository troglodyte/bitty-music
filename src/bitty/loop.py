"""Where the music comes back around, and what to keep of it.

The parent spec calls this stage "loop start/end selection, trim", and both
halves live here. Selection itself splits in two: `candidates` is symbolic and
runs before arranging, `choose` needs rendered audio and runs after. That
departure from the stage diagram is deliberate — a click is an audio property
and cannot be measured anywhere else.

Every candidate is a pair of offsets into the same rendered buffer, so falling
through the cascade costs metric evaluation, not re-synthesis.
"""

from __future__ import annotations

from dataclasses import replace

from bitty.model import Score

EPSILON = 1e-6  # onset times are floats; matches arrange.EPSILON


def trim(score: Score, first_bar: int, last_bar: int) -> Score:
    """Cut `score` to the printed bar range, rebasing seconds to zero.

    Bar *numbers* are untouched: 4a promises they are as printed, and
    `--bars 9-16` has to keep meaning bars 9-16 in the output.

    A note counts as inside the range when it *begins* there, matching the rule
    analyze.py uses for key detection — a note held across the cut cannot
    colour a range it never articulated in.
    """
    kept = [bar for bar in score.bars if first_bar <= bar.number <= last_bar]
    if not kept:
        raise ValueError(f"no bars in the range {first_bar}-{last_bar}")

    offset = kept[0].start
    end = kept[-1].start + kept[-1].dur
    return replace(
        score,
        notes=tuple(
            replace(n, start=n.start - offset)
            for n in score.notes
            if offset - EPSILON <= n.start < end - EPSILON
        ),
        bars=tuple(replace(bar, start=bar.start - offset) for bar in kept),
    )
