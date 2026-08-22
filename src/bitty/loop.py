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

from dataclasses import dataclass, replace

import numpy as np

from bitty.arrangement import Arrangement, Loop
from bitty.model import Bar, Score

# The module's tunables, gathered here rather than left where each task that
# needed one happened to add it.
EPSILON = 1e-6  # onset times are floats; matches arrange.EPSILON
MIN_LOOP_BARS = 8  # the parent spec's [loop] min_bars, until Phase 5 brings config
SEAM_RATIO = 1.0  # see the spec's calibration table: real candidates measure 0.02-0.38
ORDINARY_PERCENTILE = 99.9

SOURCE_WORDS = {
    "repeat": "repeat marks",
    "section": "section boundaries",
    "manual": "manual",
}


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


@dataclass(frozen=True)
class LoopCandidate:
    """One span the cascade is willing to propose, and why.

    `source` exists to be printed. It is what makes "(repeat marks, seam ok)"
    an explanation rather than an assertion.
    """

    first_bar: int  # printed numbers, inclusive
    last_bar: int
    start: float  # seconds, in the trimmed score's time
    end: float
    source: str  # "repeat" | "section" | "manual"


def candidates(score: Score, sections, loop_from: int | None = None) -> tuple[LoopCandidate, ...]:
    """The cascade, cheapest and most trustworthy first.

    Manual selection overrides it entirely — the parent spec's rule — so
    `loop_from` short-circuits both tiers and the bar floor with it.
    """
    if not score.bars:
        return ()
    if loop_from is not None:
        return (_manual(score.bars, loop_from),)
    return (*_from_repeats(score.bars), *_from_sections(sections))


def _manual(bars: tuple[Bar, ...], first_bar: int) -> LoopCandidate:
    start = next((bar for bar in bars if bar.number == first_bar), None)
    if start is None:
        raise ValueError(f"no bar {first_bar} in this score")
    return LoopCandidate(
        first_bar=start.number,
        last_bar=bars[-1].number,
        start=start.start,
        end=bars[-1].start + bars[-1].dur,
        source="manual",
    )


def _from_repeats(bars: tuple[Bar, ...]) -> list[LoopCandidate]:
    """The composer stating where the music comes back around.

    An end repeat with no preceding start repeats from bar one, which is both
    music21's convention and the notational one. Symmetrically, a start
    repeat left open at the end of the piece — the second half of a two-part
    form whose closing repeat dots the engraving omits, as the minuet fixture
    does — closes at the last bar rather than vanishing. Longest first: a
    loop wants the substantial repeated body, not an incidental four-bar echo.

    Opening has to happen before closing, not after. `ingest.py` maps
    `starts_repeat` to a measure's *left* barline and `ends_repeat` to its
    *right* one, so a `:||:` written between two sections is never one bar
    carrying both marks — it is always two: the first section's close on bar
    N's right barline, the second's open on bar N+1's left one. The only bar
    that ever carries both marks at once is a genuine one-bar repeat, `|: bar
    :|`, where opening-then-closing on the same bar is exactly what pairs it
    with itself rather than leaving it open to swallow every bar that
    follows.
    """
    pairs: list[tuple[Bar, Bar]] = []
    opening: Bar | None = None
    for bar in bars:
        if bar.starts_repeat:
            opening = bar
        if bar.ends_repeat:
            pairs.append((opening or bars[0], bar))
            opening = None
    if opening is not None:
        pairs.append((opening, bars[-1]))

    pairs.sort(key=lambda pair: (-_length(pair[0], pair[1]), pair[0].number))
    return [
        LoopCandidate(
            first_bar=first.number,
            last_bar=last.number,
            start=first.start,
            end=last.start + last.dur,
            source="repeat",
        )
        for first, last in pairs
        if _length(first, last) >= MIN_LOOP_BARS
    ]


def _from_sections(sections) -> list[LoopCandidate]:
    """Section k through the *last* section, k ascending.

    Suffixes rather than arbitrary spans: a loop ending before the piece does
    means the tail never plays again once the loop starts. And k=0 first, so
    the preferred answer is that the piece loops cleanly on itself — an intro
    appears only when the head is what breaks the seam, which is exactly when
    "intro" is the right word for it.
    """
    if not sections:
        return []
    last = sections[-1]
    return [
        LoopCandidate(
            first_bar=first.first_bar,
            last_bar=last.last_bar,
            start=first.start,
            end=last.end,
            source="section",
        )
        for first in sections
        if last.last_bar - first.first_bar + 1 >= MIN_LOOP_BARS
    ]


def _length(first: Bar, last: Bar) -> int:
    return last.number - first.number + 1


@dataclass(frozen=True)
class Choice:
    """The picked loop and the evidence for it, so the tool can say why."""

    loop: Loop
    candidate: LoopCandidate
    ratio: float  # splice step over what this piece ordinarily steps
    severed: int  # dry notes cut by the splice
    echo_tails: int  # echo tails cut; reported, never rejected

    def describe(self) -> str:
        """Report every problem the seam check found, not just the first.

        A manual loop can both sever a note and blow the ratio at once — the
        whole point of `--loop-from` accepting a rejected candidate is that
        the person typing the bar number gets told what's wrong with it, not
        just one of the two things. So these are independent clauses, not a
        severed/ratio if-elif: a candidate can report both.
        """
        parts = [SOURCE_WORDS.get(self.candidate.source, self.candidate.source)]
        if self.severed:
            parts.append(f"cuts {self.severed} note{'s' if self.severed != 1 else ''}")
        if self.ratio > SEAM_RATIO:
            parts.append(f"seam ratio {self.ratio:.2f}, over {SEAM_RATIO:g}")
        if not self.severed and self.ratio <= SEAM_RATIO:
            parts.append("seam ok")
        if self.echo_tails:
            parts.append("echo tail cut")
        return ", ".join(parts)


def choose(
    candidates: tuple[LoopCandidate, ...],
    audio: np.ndarray,
    arrangement: Arrangement,
    sample_rate: int,
) -> Choice | None:
    """The first candidate whose seam holds, or None.

    Manual candidates return regardless: the person typed a bar number, and the
    tool reports what it thinks without overruling them.
    """
    if not candidates or len(audio) < 2:
        return None

    ordinary = float(np.percentile(np.abs(np.diff(audio, axis=0)), ORDINARY_PERCENTILE))
    for candidate in candidates:
        verdict = _measure(candidate, audio, arrangement, sample_rate, ordinary)
        if candidate.source == "manual" or (
            verdict.ratio <= SEAM_RATIO and not verdict.severed
        ):
            return verdict
    return None


def _measure(
    candidate: LoopCandidate,
    audio: np.ndarray,
    arrangement: Arrangement,
    sample_rate: int,
    ordinary: float,
) -> Choice:
    first = min(round(candidate.start * sample_rate), len(audio) - 1)
    last = min(round(candidate.end * sample_rate), len(audio))
    splice = float(np.max(np.abs(audio[first] - audio[last - 1])))
    severed, echo_tails = _crossings(arrangement, candidate)
    return Choice(
        loop=Loop(start_sec=candidate.start, end_sec=candidate.end),
        candidate=candidate,
        ratio=splice / ordinary if ordinary else 0.0,
        severed=severed,
        echo_tails=echo_tails,
    )


def _crossings(arrangement: Arrangement, candidate: LoopCandidate) -> tuple[int, int]:
    """Dry notes and echo tails cut by the splice, counted separately.

    Separately because only the first one rejects. Measured across the
    fixtures, the lead's final note echoes past the loop end on nearly every
    candidate there is — rejecting on that leaves two of three fixtures with no
    loop at all, which is the feature shipping dead.
    """
    severed = tails = 0
    for channel in arrangement.channels:
        delay = channel.echo.delay_sec if channel.echo else 0.0
        held = {
            event.pitch
            for event in channel.events
            if event.t <= candidate.start + EPSILON < event.t + event.dur - EPSILON
        }
        for event in channel.events:
            if event.t >= candidate.end - EPSILON or event.pitch in held:
                continue
            if event.t + event.dur > candidate.end + EPSILON:
                severed += 1
            elif delay and event.t + event.dur + delay > candidate.end + EPSILON:
                tails += 1
    return severed, tails
