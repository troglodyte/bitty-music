from pathlib import Path

import pytest

from bitty import loop
from bitty.analyze import analyze
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


RAGTIME = Path(__file__).parent / "fixtures" / "ragtime.mxl"
CHORALE = Path(__file__).parent / "fixtures" / "chorale.mxl"


def spans(cands) -> list[tuple[int, int, str]]:
    return [(c.first_bar, c.last_bar, c.source) for c in cands]


def test_a_repeat_pair_becomes_the_first_candidate():
    score = synthetic(timeline(16, starts_repeat={1}, ends_repeat={16}))
    assert spans(loop.candidates(score, analyze(score)))[0] == (1, 16, "repeat")


def test_an_end_repeat_with_no_start_repeats_from_bar_one():
    score = synthetic(timeline(16, ends_repeat={12}))
    assert (1, 12, "repeat") in spans(loop.candidates(score, analyze(score)))


def test_repeat_spans_are_ordered_longest_first():
    score = synthetic(timeline(30, starts_repeat={1, 11}, ends_repeat={10, 30}))
    repeats = [s for s in spans(loop.candidates(score, analyze(score))) if s[2] == "repeat"]
    assert repeats == [(11, 30, "repeat"), (1, 10, "repeat")]


def test_a_repeat_span_under_the_floor_is_dropped():
    score = synthetic(timeline(16, starts_repeat={1}, ends_repeat={4}))
    assert all(s[2] != "repeat" for s in spans(loop.candidates(score, analyze(score))))


def test_a_bar_carrying_both_marks_closes_the_open_span_before_starting_a_new_one():
    """`:||:` between two repeated sections must not swallow the first span.

    Bar 9 both ends the first repeat and opens the second. Closing before
    opening yields two spans, (1, 9) and (9, 17); opening before closing would
    overwrite bar 1's opening with bar 9's before it is ever paired, losing
    the first span into a single spurious (1, 17).
    """
    score = synthetic(timeline(17, starts_repeat={1, 9}, ends_repeat={9, 17}))
    repeats = [s for s in spans(loop.candidates(score, analyze(score))) if s[2] == "repeat"]
    assert repeats == [(1, 9, "repeat"), (9, 17, "repeat")]


def test_sections_fall_through_as_suffixes_whole_piece_first():
    score = synthetic(timeline(24, ends_span={8, 16}))
    sections = [s for s in spans(loop.candidates(score, analyze(score))) if s[2] == "section"]
    assert sections == [(1, 24, "section"), (9, 24, "section"), (17, 24, "section")]


def test_a_score_with_no_marks_yields_the_whole_piece():
    score = synthetic(timeline(12))
    assert spans(loop.candidates(score, analyze(score))) == [(1, 12, "section")]


def test_a_score_shorter_than_the_floor_yields_nothing():
    score = synthetic(timeline(4))
    assert loop.candidates(score, analyze(score)) == ()


def test_loop_from_yields_exactly_one_manual_candidate_to_the_end():
    score = synthetic(timeline(16, starts_repeat={1}, ends_repeat={16}))
    assert spans(loop.candidates(score, analyze(score), loop_from=5)) == [(5, 16, "manual")]


def test_a_manual_start_below_the_floor_is_still_honoured():
    """Manual overrides the cascade entirely, floor included."""
    score = synthetic(timeline(16))
    assert spans(loop.candidates(score, analyze(score), loop_from=14)) == [(14, 16, "manual")]


def test_a_manual_start_on_a_bar_that_does_not_exist_is_an_error():
    score = synthetic(timeline(16))
    with pytest.raises(ValueError, match="no bar 99"):
        loop.candidates(score, analyze(score), loop_from=99)


def test_candidate_times_come_from_the_bar_timeline():
    score = synthetic(timeline(16, starts_repeat={9}))
    section = [c for c in loop.candidates(score, analyze(score)) if c.first_bar == 9][0]
    assert (section.start, section.end) == (8.0, 16.0)


def test_the_fixtures_generate_the_candidates_measured_in_the_plan():
    for path, expected in (
        (MINUET, [(1, 8, "repeat"), (9, 16, "repeat"), (1, 16, "section"), (9, 16, "section")]),
        (RAGTIME, [(1, 16, "repeat"), (1, 16, "section")]),
        (CHORALE, [(1, 8, "section")]),
    ):
        score = ingest(path)
        assert spans(loop.candidates(score, analyze(score))) == expected
