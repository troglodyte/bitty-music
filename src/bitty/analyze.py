"""What the score's own marks say about its structure.

Boundaries come only from notation — repeat marks, barlines, and signature
changes — so every one can be justified by pointing at the score. Key
labelling is the single analysed step here, and it never moves a boundary.
"""

from music21 import note as m21note
from music21 import stream

from bitty.model import Score

UNKNOWN_KEY = "unknown"
MIN_QUARTER_LENGTH = 1 / 32  # a grace note still has to occupy something


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
