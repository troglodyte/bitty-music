"""Drums the score does not contain, placed on the barlines it does.

The groove comes from the meter rather than from the music. Every hit can be
justified by pointing at a barline, which is the standard `analyze` holds
itself to; a pattern derived from onset density would put hits on a chorale
that nobody could account for afterwards.

Positions are in **quarter notes**, not beats. `bpm` is quarter-note based
everywhere in this pipeline, so quarters convert to seconds with no per-meter
reasoning, and a 6/8 bar is three quarters rather than six ambiguous "beats".

This module sits at the bottom of the import graph beside `arrangement` and
`model`, and takes `level` as a float rather than importing `config`.
"""

from __future__ import annotations

from dataclasses import dataclass

from bitty.arrangement import MAX_VELOCITY, Event
from bitty.model import Bar

EPSILON = 1e-6

KICK, SNARE, HAT = "kick", "snare", "hat"

# Not pitches. The noise oscillator clocks a 15-bit LFSR once per phase cycle,
# so this number is a clock rate: low is a rumble, high is a hiss, and neither
# reads to the ear as a note. Calibration, set by the phase's audition.
PITCH = {KICK: 36, SNARE: 52, HAT: 76}


@dataclass(frozen=True)
class Hit:
    quarters: float  # from the barline
    drum: str  # KICK, SNARE, or HAT
    vel: int  # 0-15, before `level` scales it


def _hats(count: int, spacing: float, vel: int) -> tuple[Hit, ...]:
    return tuple(Hit(step * spacing, HAT, vel) for step in range(count))


# One entry per supported meter. These are musical decisions a person made and
# can be judged by ear, not a formula's output — which is the point. 3/4 has no
# backbeat because a waltz that gets one stops being a waltz, and encoding that
# exception into a general rule would turn the rule back into this table.
PATTERNS: dict[tuple[int, int], tuple[Hit, ...]] = {
    (4, 4): (
        Hit(0.0, KICK, 15),
        Hit(2.0, KICK, 12),
        Hit(1.0, SNARE, 13),
        Hit(3.0, SNARE, 13),
        *_hats(8, 0.5, 7),
    ),
    (2, 4): (
        Hit(0.0, KICK, 15),
        Hit(1.0, SNARE, 13),
        *_hats(4, 0.5, 7),
    ),
    (3, 4): (
        Hit(0.0, KICK, 15),
        Hit(1.0, HAT, 8),
        Hit(2.0, HAT, 8),
    ),
    (6, 8): (
        Hit(0.0, KICK, 15),
        Hit(1.5, SNARE, 13),
        *_hats(6, 0.5, 7),
    ),
}


def groove(bars: tuple[Bar, ...], bpm: float, level: float) -> tuple[Event, ...]:
    """The percussion channel's events, or () when there are no bars."""
    if not bars:
        return ()
    seconds_per_quarter = 60.0 / bpm
    placed: list[tuple[float, Hit]] = []
    for bar in bars:
        for hit in _pattern(bar):
            offset = hit.quarters * seconds_per_quarter
            # A pickup or a short final bar keeps only what fits inside it.
            # Without this, three hits of a 4/4 pattern spill into a bar that
            # does not exist.
            if offset >= bar.dur - EPSILON:
                continue
            placed.append((bar.start + offset, hit))
    placed.sort(key=lambda pair: pair[0])
    return tuple(_event(when, hit, level) for when, hit in placed)


def _pattern(bar: Bar) -> tuple[Hit, ...]:
    """This bar's pattern, by its own signature.

    Per bar rather than per score, so a piece that changes meter part-way is
    handled by construction — `analyze` already splits a section at exactly
    that point.
    """
    try:
        return PATTERNS[bar.time_signature]
    except KeyError:
        top, bottom = bar.time_signature
        supported = ", ".join(f"{t}/{b}" for t, b in sorted(PATTERNS))
        raise ValueError(
            f"bar {bar.number} is in {top}/{bottom}, which has no percussion "
            f"pattern; [percussion] supports {supported}. Turn percussion off "
            f"to convert this score."
        ) from None


def _event(when: float, hit: Hit, level: float) -> Event:
    return Event(
        t=when,
        pitch=PITCH[hit.drum],
        dur=0.0,  # Task 3 sets this from the gap to the next hit
        vel=min(MAX_VELOCITY, round(hit.vel * level)),
    )
