from dataclasses import replace
from pathlib import Path

import pytest

from bitty.arrange import arrange
from bitty.config import Transform
from bitty.ingest import ingest
from bitty.model import Bar, Note, Score
from bitty.transform import apply

FIXTURES = Path(__file__).parent / "fixtures"
NAMES = ["chorale", "minuet", "ragtime"]


def a_score(*notes, bpm=120.0, bars=()):
    """A Score with no file behind it: `apply` is pure, so tests can be too."""
    return Score(
        notes=tuple(notes),
        bpm=bpm,
        time_signature=(4, 4),
        title="probe",
        bars=tuple(bars),
    )


def a_note(pitch=60, start=0.0, dur=1.0, velocity=80):
    return Note(pitch=pitch, start=start, dur=dur, velocity=velocity, part=0)


def test_the_defaults_return_the_very_same_score():
    """Identity, not an arithmetic round trip that happens to land back home.

    `is` rather than `==`: the goldens are valid because the default path does
    nothing at all, and a rebuild that currently compares equal is one float
    away from not.
    """
    score = a_score(a_note(), a_note(pitch=64, start=1.0))
    assert apply(score, Transform()) is score


def test_transpose_shifts_every_pitch():
    score = a_score(a_note(pitch=60), a_note(pitch=64, start=1.0))
    result = apply(score, Transform(transpose=7))
    assert [n.pitch for n in result.notes] == [67, 71]


def test_transpose_moves_nothing_but_pitch():
    """Everything that is not a pitch survives the shift untouched."""
    bar = Bar(number=1, start=0.0, dur=2.0, time_signature=(4, 4), sharps=1)
    score = a_score(a_note(pitch=60, start=0.5, dur=0.25, velocity=99), bars=[bar])
    result = apply(score, Transform(transpose=-5))
    assert result.bpm == score.bpm
    assert result.bars == score.bars
    assert result.title == score.title and result.time_signature == score.time_signature
    before, after = score.notes[0], result.notes[0]
    assert after == replace(before, pitch=before.pitch - 5)


@pytest.mark.parametrize("name", NAMES)
def test_the_whole_arrangement_shifts_with_the_transpose(name):
    """The load-bearing transpose test, and the reason transpose is cheap.

    The arranger has no absolute pitch logic anywhere — top and bottom pinning,
    nearest-last-pitch assignment, the reduction's pitch-class comparison, and
    the arpeggio's octave folding are all relative or uniformly shifted — so
    arranging a transposed score must give back exactly the untransposed
    arrangement with every pitch moved by n.

    Asserted event by whole event rather than over a pitch list: an
    implementation that shifts pitches correctly while dropping arp offsets or
    losing a vibrato flag would pass the coarser check.
    """
    score = ingest(FIXTURES / f"{name}.mxl")
    plain = arrange(score)
    shifted = arrange(apply(score, Transform(transpose=5)))

    assert shifted.meta == plain.meta
    assert len(shifted.channels) == len(plain.channels)
    for was, now in zip(plain.channels, shifted.channels):
        assert now.role == was.role
        assert now.pan == was.pan
        assert now.echo == was.echo
        assert now.instrument == was.instrument
        assert len(now.events) == len(was.events)
        for before, after in zip(was.events, now.events):
            assert after == replace(before, pitch=before.pitch + 5)


def test_the_invariant_fixtures_actually_contain_an_arpeggio():
    """Keeps the test above from guarding arp offsets vacuously.

    Phase 8's reduction left the minuet and the chorale with no arpeggio at
    all at the count-5 default; ragtime is the only fixture whose overflow
    still cycles, so it is the only one carrying the arp half of the
    invariant. If this ever reaches zero, the invariant has quietly stopped
    covering `Event.arp` and needs a fixture that does.
    """
    arranged = arrange(ingest(FIXTURES / "ragtime.mxl"))
    assert sum(1 for c in arranged.channels for e in c.events if e.arp) >= 1
