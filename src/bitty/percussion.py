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

# Strongest first. A hat that lands on a downbeat is dropped rather than
# allowed to truncate the kick — which is deliberately *not* the mutable
# truncation `arrange._assign` performs on pitched channels. That path exists
# to preserve voice-leading, and there is no voice-leading here.
PRIORITY = (KICK, SNARE, HAT)

# The shortest gap between two audible hits, and the phase's counterpart to
# ARP_RATE_SEC: a fact about the ear expressed in seconds, set by audition
# rather than guessed. It deliberately does not scale with tempo, so density
# is a property of the pattern meeting the tempo — a fast piece loses its
# subdivisions and keeps its backbeat, and `tempo_scale` feeds this for free
# because Phase 9 rewrites bar times before `arrange` ever runs.
#
# Where it bites, measured on the fixtures at their own tempos: hat spacing is
# 250 ms on the chorale, 300 ms on ragtime, 500 ms on the minuet. So anything
# below 250 ms is inert at tempo_scale = 1.0, and the crossing arrives between
# 2.0 and 4.0 for the chorale and ragtime. The minuet never crosses: 500 ms at
# the 4.0 ceiling is still 125 ms, so a waltz keeps its full groove at any
# tempo this pipeline can ask for.
MIN_HIT_SEC = 0.10

# How long one hit rings before the envelope has finished with it. Clipped to
# the gap that follows, so the channel stays monophonic. Also calibration.
HIT_SEC = 0.12


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
    return _resolve(placed, level)


def _resolve(placed: list[tuple[float, Hit]], level: float) -> tuple[Event, ...]:
    """Candidates to a monophonic channel: priority, then the floor, then durs.

    Greedy and strongest-first across the whole piece, which makes the rule
    sayable in one sentence: place the loudest drums, then drop anything that
    would land too soon after something already placed.
    """
    kept: list[tuple[float, Hit]] = []
    for drum in PRIORITY:
        for when, hit in sorted(
            (pair for pair in placed if pair[1].drum == drum),
            key=lambda pair: pair[0],
        ):
            if any(abs(when - other) < MIN_HIT_SEC for other, _ in kept):
                continue
            kept.append((when, hit))

    kept.sort(key=lambda pair: pair[0])
    events = []
    for index, (when, hit) in enumerate(kept):
        gap = kept[index + 1][0] - when if index + 1 < len(kept) else HIT_SEC
        events.append(_event(when, hit, level, min(HIT_SEC, gap)))
    return tuple(events)


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


def _event(when: float, hit: Hit, level: float, dur: float) -> Event:
    return Event(
        t=when,
        pitch=PITCH[hit.drum],
        dur=dur,
        vel=min(MAX_VELOCITY, round(hit.vel * level)),
    )
