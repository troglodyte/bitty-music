from pathlib import Path

import pytest

from bitty import loop
from bitty.ingest import ingest
from bitty.model import Bar, Note, Score

MINUET = Path(__file__).parent / "fixtures" / "minuet.mxl"


def timeline(count: int, **marks) -> tuple[Bar, ...]:
    """`count` one-second bars numbered from 1, with marks by bar number.

    Deliberately the same helper shape as tests/test_analyze.py — the two
    modules read the same timeline, so their fixtures should look alike.
    """
    return tuple(
        Bar(
            number=n,
            start=float(n - 1),
            dur=1.0,
            time_signature=(4, 4),
            sharps=0,
            starts_repeat=n in marks.get("starts_repeat", set()),
            ends_repeat=n in marks.get("ends_repeat", set()),
            ends_span=n in marks.get("ends_span", set()),
        )
        for n in range(1, count + 1)
    )


def synthetic(bars: tuple[Bar, ...], notes: tuple[Note, ...] = ()) -> Score:
    return Score(
        notes=notes, bpm=60.0, time_signature=(4, 4), title="synthetic", bars=bars
    )


def note(start: float, dur: float = 0.5, pitch: int = 60) -> Note:
    return Note(pitch=pitch, start=start, dur=dur, velocity=64, part=0)


def test_trim_keeps_only_the_requested_bars():
    trimmed = loop.trim(synthetic(timeline(8)), 3, 5)
    assert [b.number for b in trimmed.bars] == [3, 4, 5]


def test_trim_rebases_times_to_zero_without_renumbering():
    trimmed = loop.trim(synthetic(timeline(8)), 3, 5)
    assert trimmed.bars[0].start == 0.0
    assert trimmed.bars[0].number == 3  # printed numbers never move


def test_trim_drops_notes_outside_the_range_and_rebases_the_rest():
    notes = (note(1.0), note(2.5), note(4.5), note(6.0))
    trimmed = loop.trim(synthetic(timeline(8), notes), 3, 5)
    assert [n.start for n in trimmed.notes] == [0.5, 2.5]


def test_a_note_beginning_before_the_range_is_excluded_even_if_it_sustains_in():
    """The same 'begins in' rule analyze.py uses for key detection."""
    trimmed = loop.trim(synthetic(timeline(8), (note(1.5, dur=3.0),)), 3, 5)
    assert trimmed.notes == ()


def test_trimming_to_bars_that_do_not_exist_is_an_error():
    with pytest.raises(ValueError, match="no bars"):
        loop.trim(synthetic(timeline(8)), 20, 30)


def test_trimming_a_real_score_preserves_its_other_fields():
    trimmed = loop.trim(ingest(MINUET), 9, 16)
    assert trimmed.title == "minuet"
    assert trimmed.bpm == 120
    assert trimmed.bars[0].number == 9 and trimmed.bars[0].start == 0.0
