from pathlib import Path

import numpy as np
import pytest

from bitty import loop
from bitty.analyze import analyze
from bitty.arrange import arrange
from bitty.arrangement import Arrangement, Channel, Echo, Event, Instrument, Loop
from bitty.ingest import ingest
from bitty.model import Bar, Note, Score
from bitty.synth import SAMPLE_RATE, render

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


def test_a_one_bar_repeat_under_the_floor_yields_no_candidate():
    """`|: bar :|` is the only mark pattern that puts both marks on one bar.

    `ingest.py` maps `starts_repeat` to a measure's left barline and
    `ends_repeat` to its right one, so a `:||:` written *between* two
    sections is always two bars — the first section's close on bar N's right
    barline, the second's open on bar N+1's left one. It can never be one bar
    carrying both marks.

    Bar 12 here stands for a written `|: bar 12 :|`: a single measure whose
    left barline starts a repeat and whose own right barline ends it,
    self-contained. Opening before closing pairs it with itself, a one-bar
    span that the 8-bar floor then drops — correctly, since the composer
    never wrote a twelve-bar repeat. Closing before opening (the ordering
    this test replaces) mistook bar 1 for the still-open start and produced
    a spurious (1, 12) span the composer never marked, which is exactly the
    regression this test guards against.
    """
    score = synthetic(timeline(16, starts_repeat={12}, ends_repeat={12}))
    assert all(s[2] != "repeat" for s in spans(loop.candidates(score, analyze(score))))


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


def pulse(seconds: float, hz: float = 100.0, amp: float = 0.5) -> np.ndarray:
    """A square wave: full-amplitude edges every half period, by design."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    wave = amp * np.sign(np.sin(2 * np.pi * hz * t))
    return np.stack([wave, wave], axis=1)


def bare(events=(), echo=None) -> Arrangement:
    return Arrangement(
        meta={},
        channels=(
            Channel(role="lead", instrument=Instrument(wave="pulse"),
                    events=tuple(events), echo=echo),
        ),
    )


def candidate(start: float, end: float, source: str = "section") -> loop.LoopCandidate:
    return loop.LoopCandidate(first_bar=1, last_bar=8, start=start, end=end, source=source)


def test_a_period_aligned_splice_passes_despite_full_amplitude_edges():
    """The test that would have caught an absolute threshold.

    A pulse wave steps between +A and -A every half period. That is ordinary
    signal, not a click, and a metric that cannot tell the difference would
    reject every loop in a square-wave piece.
    """
    audio = pulse(2.0, hz=100.0)  # 100 Hz: 0.5 s is a whole number of periods
    chosen = loop.choose((candidate(0.5, 1.5),), audio, bare(), SAMPLE_RATE)
    assert chosen is not None
    # The loop length is a whole number of periods, so the splice compares
    # audio[first], a zero-crossing sample at t=0.5, against audio[last - 1],
    # one sample short of realigning with it - deep in the opposite
    # half-period, clipped to the full -0.5. That pairing is definitionally
    # an ordinary sign-flip edge, the same shape as every edge in the
    # percentile population, so the ratio lands exactly at the threshold
    # rather than under it. choose() accepts on <=, matching that boundary.
    assert chosen.ratio <= loop.SEAM_RATIO


def test_a_splice_larger_than_the_piece_ever_makes_is_rejected():
    audio = pulse(2.0, hz=100.0, amp=0.2)
    audio[SAMPLE_RATE // 2] = 1.0  # loop start lands on a sample the music never reaches
    assert loop.choose((candidate(0.5, 1.5),), audio, bare(), SAMPLE_RATE) is None


def test_choose_falls_through_a_failing_candidate_to_the_next():
    audio = pulse(3.0, hz=100.0, amp=0.2)
    audio[SAMPLE_RATE // 2] = 1.0
    chosen = loop.choose(
        (candidate(0.5, 1.5), candidate(1.0, 2.0)), audio, bare(), SAMPLE_RATE
    )
    assert chosen is not None
    assert chosen.candidate.start == 1.0


def test_choose_returns_nothing_when_every_candidate_fails():
    audio = pulse(2.0, hz=100.0, amp=0.2)
    audio[SAMPLE_RATE // 2] = 1.0
    assert loop.choose((candidate(0.5, 1.5),), audio, bare(), SAMPLE_RATE) is None


def test_no_candidates_at_all_is_not_a_loop():
    assert loop.choose((), pulse(1.0), bare(), SAMPLE_RATE) is None


def test_a_dry_note_sustaining_across_the_loop_end_severs_the_candidate():
    events = (Event(t=0.9, pitch=60, dur=0.5, vel=10),)  # ends at 1.4, past 1.0
    assert loop.choose((candidate(0.0, 1.0),), pulse(2.0), bare(events), SAMPLE_RATE) is None


def test_a_note_ending_exactly_at_the_loop_end_does_not_sever():
    """Float onsets; the comparison has to be epsilon-tolerant on this side.

    Written the other way, every final note counts as severed and no
    bar-aligned candidate ever passes.
    """
    events = (Event(t=0.5, pitch=60, dur=0.5, vel=10),)
    assert loop.choose((candidate(0.0, 1.0),), pulse(2.0), bare(events), SAMPLE_RATE) is not None


def test_the_same_pitch_sounding_at_the_loop_start_continues_rather_than_severs():
    events = (
        Event(t=0.9, pitch=60, dur=0.5, vel=10),
        Event(t=0.0, pitch=60, dur=0.4, vel=10),
    )
    chosen = loop.choose((candidate(0.0, 1.0),), pulse(2.0), bare(events), SAMPLE_RATE)
    assert chosen is not None


def test_an_echo_tail_crossing_the_loop_end_is_counted_but_never_rejects():
    """Measured: rejecting on this kills every candidate on two of three fixtures."""
    events = (Event(t=0.5, pitch=60, dur=0.5, vel=10),)  # dry ends at 1.0, echo at 1.38
    arrangement = bare(events, echo=Echo(delay_sec=0.38, level=0.35))
    chosen = loop.choose((candidate(0.0, 1.0),), pulse(2.0), arrangement, SAMPLE_RATE)
    assert chosen is not None
    assert chosen.echo_tails == 1
    assert "echo tail cut" in chosen.describe()


def test_a_manual_candidate_is_returned_even_when_both_tests_fail():
    audio = pulse(2.0, hz=100.0, amp=0.2)
    audio[SAMPLE_RATE // 2] = 1.0
    events = (Event(t=0.9, pitch=60, dur=0.7, vel=10),)  # ends at 1.6, past 1.5
    chosen = loop.choose(
        (candidate(0.5, 1.5, source="manual"),), audio, bare(events), SAMPLE_RATE
    )
    assert chosen is not None
    assert chosen.loop == Loop(start_sec=0.5, end_sec=1.5)
    assert chosen.severed == 1  # measured and reported, not acted on


def test_describe_names_the_source_and_the_seam():
    audio = pulse(2.0, hz=100.0)
    chosen = loop.choose((candidate(0.5, 1.5, source="repeat"),), audio, bare(), SAMPLE_RATE)
    assert chosen.describe() == "repeat marks, seam ok"


def test_describe_reports_a_severed_note_and_an_over_threshold_ratio_together():
    """A rejected manual loop must show every problem, not just the first one found.

    `--loop-from` returns a candidate even when it fails both seam tests, and the
    whole point of still printing the seam is that a person who typed a bad bar
    number sees what's wrong with it. An if/elif between the two clauses would
    hide the ratio whenever a note is also severed -- silent on exactly the
    candidate that most needs to be loud about it.
    """
    c = loop.LoopCandidate(first_bar=1, last_bar=8, start=0.5, end=1.5, source="manual")
    chosen = loop.Choice(loop=Loop(start_sec=0.5, end_sec=1.5), candidate=c, ratio=3.0, severed=1, echo_tails=0)
    description = chosen.describe()
    assert "cuts 1 note" in description
    assert "seam ratio 3.00, over 1" in description


def test_describe_pluralizes_the_cut_note_count():
    c = loop.LoopCandidate(first_bar=1, last_bar=8, start=0.5, end=1.5, source="manual")
    one = loop.Choice(loop=Loop(start_sec=0.5, end_sec=1.5), candidate=c, ratio=0.0, severed=1, echo_tails=0)
    two = loop.Choice(loop=Loop(start_sec=0.5, end_sec=1.5), candidate=c, ratio=0.0, severed=2, echo_tails=0)
    assert "cuts 1 note" in one.describe() and "cuts 1 notes" not in one.describe()
    assert "cuts 2 notes" in two.describe()


def test_the_fixtures_pick_what_the_plan_measured():
    for path, expected in (
        (MINUET, (1, 8, "repeat marks, seam ok")),
        (RAGTIME, (1, 16, "repeat marks, seam ok, echo tail cut")),
        (CHORALE, (1, 8, "section boundaries, seam ok, echo tail cut")),
    ):
        score = ingest(path)
        arrangement = arrange(score)
        audio = render(arrangement)
        chosen = loop.choose(
            loop.candidates(score, analyze(score)), audio, arrangement, SAMPLE_RATE
        )
        assert chosen is not None, path.name
        assert (chosen.candidate.first_bar, chosen.candidate.last_bar, chosen.describe()) == expected
