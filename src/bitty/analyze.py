"""What the score's own marks say about its structure.

Boundaries come only from notation — repeat marks, barlines, and signature
changes — so every one can be justified by pointing at the score. Key
labelling is the single analysed step here, and it never moves a boundary.
"""

from dataclasses import dataclass

from music21 import note as m21note
from music21 import stream

from bitty.model import Bar, Score

UNKNOWN_KEY = "unknown"
MIN_QUARTER_LENGTH = 1 / 32  # a grace note still has to occupy something


@dataclass(frozen=True)
class Section:
    """A span of bars the notation marks off, and what it sounds like.

    `name` is positional — "A", "B", "C" mean first, second, third. It is not
    a similarity claim: notation alone cannot say that a later section is a
    variant of an earlier one, so there is no "A'" here.
    """

    name: str
    first_bar: int  # printed numbers, inclusive
    last_bar: int
    start: float  # seconds
    end: float
    key: str
    time_signature: tuple[int, int]
    repeats: bool


def _key_of(score: Score, start: float, end: float) -> str:
    """The detected key of the notes *beginning* in [start, end).

    Krumhansl-Schmuckler via music21, run on a scratch stream rebuilt from our
    own notes. K-S correlates a duration-weighted pitch-class histogram against
    24 profiles, so a rebuilt stream gives the same answer as the parsed score
    — verified on every fixture.

    A note counts toward the section it begins in, so one held across a
    boundary cannot colour a section it never articulated in.
    """
    seconds_per_quarter = 60.0 / score.bpm
    sounding = [n for n in score.notes if start - 1e-9 <= n.start < end - 1e-9]
    if not sounding:
        return UNKNOWN_KEY

    scratch = stream.Stream()
    for source in sounding:
        element = m21note.Note(source.pitch)
        element.quarterLength = max(source.dur / seconds_per_quarter, MIN_QUARTER_LENGTH)
        scratch.insert(source.start / seconds_per_quarter, element)
    return str(scratch.analyze("key"))


def analyze(score: Score) -> tuple[Section, ...]:
    """Group the bar timeline into the sections its marks describe."""
    if not score.bars:
        return ()
    return tuple(
        _section(_name(index), group, score)
        for index, group in enumerate(_group(score.bars))
    )


def _group(bars: tuple[Bar, ...]) -> list[list[Bar]]:
    groups = [[bars[0]]]
    for previous, current in zip(bars, bars[1:]):
        if _opens_section(previous, current):
            groups.append([current])
        else:
            groups[-1].append(current)
    return groups


def _opens_section(previous: Bar, current: Bar) -> bool:
    """Whether a section starts at `current`. Every clause names a mark.

    Several clauses firing at the same bar produce one boundary, not several:
    an end repeat written as a final barline sets two of them at once.
    """
    return (
        current.starts_repeat
        or previous.ends_repeat
        or previous.ends_span
        or current.time_signature != previous.time_signature
        or current.sharps != previous.sharps
    )


def _section(name: str, group: list[Bar], score: Score) -> Section:
    start = group[0].start
    end = group[-1].start + group[-1].dur
    return Section(
        name=name,
        first_bar=group[0].number,
        last_bar=group[-1].number,
        start=start,
        end=end,
        key=_key_of(score, start, end),
        time_signature=group[0].time_signature,
        repeats=group[0].starts_repeat or group[-1].ends_repeat,
    )


def _name(index: int) -> str:
    """A, B, ... Z, AA, AB. Positional names, not similarity claims."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters
