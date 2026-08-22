from pathlib import Path

from bitty.analyze import UNKNOWN_KEY, _key_of, analyze
from bitty.ingest import ingest
from bitty.model import Bar, Score

CHORALE = Path(__file__).parent / "fixtures" / "chorale.mxl"
MINUET = Path(__file__).parent / "fixtures" / "minuet.mxl"
RAGTIME = Path(__file__).parent / "fixtures" / "ragtime.mxl"
LATE_SIGNATURE = Path(__file__).parent / "fixtures" / "late_signature.musicxml"


def test_detects_each_half_of_the_minuet_separately():
    """A minuet modulates to the dominant; detection has to see both halves."""
    score = ingest(MINUET)
    assert _key_of(score, 0.0, 12.0) == "G major"
    assert _key_of(score, 12.0, 24.0) == "D major"


def test_detects_the_key_of_a_whole_score():
    assert _key_of(ingest(CHORALE), 0.0, 16.0) == "f# minor"
    assert _key_of(ingest(RAGTIME), 0.0, 19.2) == "A- major"


def test_a_window_with_no_notes_has_no_key():
    assert _key_of(ingest(CHORALE), 100.0, 200.0) == UNKNOWN_KEY


def test_a_signature_stated_late_does_not_open_a_phantom_section():
    """The fixture's only signature statement is on bar 2, not bar 1.

    Nothing in this score ever changes meter or key — it's 3/4 with 2 sharps
    throughout. A boundary here would come from a hardcoded seed disagreeing
    with the score, not from any mark the composer wrote, which is exactly
    what this phase promises never happens.
    """
    sections = analyze(ingest(LATE_SIGNATURE))
    assert ranges(sections) == [(1, 2)]


def timeline(count: int, **marks) -> tuple[Bar, ...]:
    """`count` one-second bars numbered from 1, with marks by bar number.

    timeline(4, ends_repeat={2}) puts an end repeat on bar 2.
    timeline(4, sharps={3: 2, 4: 2}) changes key at bar 3.
    """
    return tuple(
        Bar(
            number=n,
            start=float(n - 1),
            dur=1.0,
            time_signature=marks.get("time_signature", {}).get(n, (4, 4)),
            sharps=marks.get("sharps", {}).get(n, 0),
            starts_repeat=n in marks.get("starts_repeat", set()),
            ends_repeat=n in marks.get("ends_repeat", set()),
            ends_span=n in marks.get("ends_span", set()),
        )
        for n in range(1, count + 1)
    )


def synthetic(bars: tuple[Bar, ...]) -> Score:
    return Score(
        notes=(), bpm=60.0, time_signature=(4, 4), title="synthetic", bars=bars
    )


def ranges(sections) -> list[tuple[int, int]]:
    return [(s.first_bar, s.last_bar) for s in sections]


def test_a_score_with_no_marks_is_one_section():
    sections = analyze(synthetic(timeline(4)))
    assert ranges(sections) == [(1, 4)]


def test_a_start_repeat_opens_a_section():
    assert ranges(analyze(synthetic(timeline(4, starts_repeat={3})))) == [(1, 2), (3, 4)]


def test_an_end_repeat_closes_a_section():
    assert ranges(analyze(synthetic(timeline(4, ends_repeat={2})))) == [(1, 2), (3, 4)]


def test_a_final_barline_closes_a_section():
    assert ranges(analyze(synthetic(timeline(4, ends_span={2})))) == [(1, 2), (3, 4)]


def test_a_time_signature_change_opens_a_section():
    bars = timeline(4, time_signature={3: (3, 4), 4: (3, 4)})
    assert ranges(analyze(synthetic(bars))) == [(1, 2), (3, 4)]


def test_a_key_change_opens_a_section():
    bars = timeline(4, sharps={3: 2, 4: 2})
    assert ranges(analyze(synthetic(bars))) == [(1, 2), (3, 4)]


def test_marks_landing_together_open_one_section_not_two():
    """A minuet's bar 8 ends a repeat with a final barline, and bar 9 starts one."""
    bars = timeline(4, ends_repeat={2}, ends_span={2}, starts_repeat={3})
    assert ranges(analyze(synthetic(bars))) == [(1, 2), (3, 4)]


def test_sections_are_named_by_position():
    sections = analyze(synthetic(timeline(3, ends_repeat={1, 2})))
    assert [s.name for s in sections] == ["A", "B", "C"]


def test_names_continue_past_z():
    """Not expected in real music; specified so the behaviour is not accidental."""
    bars = timeline(30, ends_repeat=set(range(1, 30)))
    names = [s.name for s in analyze(synthetic(bars))]
    assert names[:2] == ["A", "B"]
    assert names[25:28] == ["Z", "AA", "AB"]


def test_a_section_repeats_when_either_end_says_so():
    first, second = analyze(synthetic(timeline(4, ends_repeat={2})))
    assert first.repeats
    assert not second.repeats


def test_sections_span_their_bars_in_seconds():
    first, second = analyze(synthetic(timeline(4, ends_repeat={2})))
    assert (first.start, first.end) == (0.0, 2.0)
    assert (second.start, second.end) == (2.0, 4.0)


def test_a_section_with_no_notes_has_no_key():
    assert analyze(synthetic(timeline(2)))[0].key == UNKNOWN_KEY


def test_a_score_with_no_bars_has_no_sections():
    assert analyze(Score(notes=(), bpm=120.0, time_signature=(4, 4), title="")) == ()


def summary(sections):
    return [(s.name, s.first_bar, s.last_bar, s.key, s.repeats) for s in sections]


def test_the_minuet_is_two_repeated_halves():
    assert summary(analyze(ingest(MINUET))) == [
        ("A", 1, 8, "G major", True),
        ("B", 9, 16, "D major", True),
    ]


def test_the_ragtime_is_one_repeated_strain():
    assert summary(analyze(ingest(RAGTIME))) == [("A", 1, 16, "A- major", True)]


def test_the_chorale_has_no_interior_structure():
    """A hymn of eight bars has nothing to divide; one section is the truth."""
    assert summary(analyze(ingest(CHORALE))) == [("A", 1, 8, "f# minor", False)]
