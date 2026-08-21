from pathlib import Path

import pytest

from bitty.ingest import ingest

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"
MINUET = Path(__file__).parent / "fixtures" / "minuet.mxl"
ORNAMENTS = Path(__file__).parent / "fixtures" / "ornaments.musicxml"
CHORALE = Path(__file__).parent / "fixtures" / "chorale.mxl"
RAGTIME = Path(__file__).parent / "fixtures" / "ragtime.mxl"


def test_ingest_reads_every_note():
    score = ingest(FIXTURE)
    assert len(score.notes) == 5


def test_ingest_defaults_to_120_bpm_when_score_has_no_tempo_mark():
    score = ingest(FIXTURE)
    assert score.bpm == 120.0
    assert score.time_signature == (4, 4)


def test_ingest_converts_offsets_to_seconds():
    score = ingest(FIXTURE)
    treble = sorted([n for n in score.notes if n.part == 0], key=lambda n: n.start)
    assert [n.pitch for n in treble] == [72, 74, 76, 77]
    assert [n.start for n in treble] == [0.0, 0.5, 1.0, 1.5]
    assert all(n.dur == 0.5 for n in treble)


def test_ingest_tags_notes_with_their_source_part():
    score = ingest(FIXTURE)
    bass = [n for n in score.notes if n.part == 1]
    assert len(bass) == 1
    assert bass[0].pitch == 48
    assert bass[0].start == 0.0
    assert bass[0].dur == 2.0


def test_ingest_records_metric_position():
    """Accent needs to know where in the bar a note falls."""
    score = ingest(FIXTURE)
    downbeat = [n for n in score.notes if n.start == 0.0]
    offbeat = [n for n in score.notes if n.start == 0.5]
    assert downbeat and offbeat
    assert all(n.beat_strength == 1.0 for n in downbeat)
    assert all(n.beat_strength < 1.0 for n in offbeat)


def test_ingest_reads_written_dynamics():
    """A score marked f then p should not come out uniformly loud."""
    score = ingest(MINUET)
    assert len({n.velocity for n in score.notes}) > 1


def test_ingest_holds_a_dynamic_until_the_next_mark():
    """A mark governs every following note in its own part, not just one."""
    score = ingest(MINUET)
    # Part 2 is marked f at offset 8.0 and p at 25.0; the p is quieter.
    part = [n for n in score.notes if n.part == 2]
    under_f = [n for n in part if 4.0 <= n.start < 12.0]
    under_p = [n for n in part if n.start >= 12.5]
    assert under_f and under_p
    assert max(n.velocity for n in under_p) < min(n.velocity for n in under_f)


def test_ingest_expands_a_trill_into_fast_notes():
    """A trill is several notes, not one held tone.

    Guards a real trap: music21's stream-level realizeOrnaments() silently
    leaves the note alone, so only a count assertion catches the regression.
    """
    score = ingest(ORNAMENTS)
    first_beat = [n for n in score.notes if n.start < 0.5]  # seconds: one quarter at 120 bpm
    assert len(first_beat) > 2
    assert len({n.pitch for n in first_beat}) == 2, "a trill alternates two pitches"


def test_ingest_expands_a_mordent_and_keeps_the_note_length():
    score = ingest(ORNAMENTS)
    second_beat = [n for n in score.notes if 0.5 <= n.start < 1.0]
    assert len(second_beat) == 3, "mordent: upper, neighbour, then the note itself"
    assert sum(n.dur for n in second_beat) == pytest.approx(0.5)


def test_ingest_gives_every_note_a_real_duration():
    """The post-condition Task 5's deletions depend on."""
    for fixture in (FIXTURE, MINUET, ORNAMENTS):
        assert all(n.dur > 0.0 for n in ingest(fixture).notes)


def test_a_grace_note_sounds_before_the_note_it_decorates():
    score = ingest(ORNAMENTS)
    grace = next(n for n in score.notes if n.pitch == 79)  # G5
    principal = next(n for n in score.notes if n.pitch == 77)  # F5
    assert grace.start < principal.start
    assert grace.start + grace.dur == pytest.approx(principal.start)
    assert grace.dur == pytest.approx(0.032)


def test_a_grace_note_borrows_from_its_principal_rather_than_shifting_it():
    """The pair occupies the principal's original span, so nothing downstream moves."""
    score = ingest(ORNAMENTS)
    grace = next(n for n in score.notes if n.pitch == 79)
    principal = next(n for n in score.notes if n.pitch == 77)
    # The principal is written as a quarter, which is 0.5 s at the default 120 bpm.
    assert grace.start + grace.dur + principal.dur == pytest.approx(grace.start + 0.5)


def test_ingest_builds_a_bar_timeline():
    score = ingest(MINUET)
    assert len(score.bars) == 16
    assert [b.number for b in score.bars[:3]] == [1, 2, 3]


def test_bar_times_follow_the_tempo():
    """Minuet is 3/4 with no tempo mark, so 120 bpm: three quarters = 1.5 s."""
    score = ingest(MINUET)
    assert score.bars[0].start == 0.0
    assert score.bars[0].dur == 1.5
    assert score.bars[1].start == 1.5
    assert score.bars[-1].start == pytest.approx(22.5)


def test_bars_carry_the_signatures_forward():
    """A score states its signatures once; every later bar still has them."""
    score = ingest(MINUET)
    assert all(b.time_signature == (3, 4) for b in score.bars)
    assert all(b.sharps == 1 for b in score.bars)


def test_bar_durations_track_the_meter():
    assert ingest(CHORALE).bars[0].dur == 2.0    # 4/4 at 120
    assert ingest(RAGTIME).bars[0].dur == 1.2    # 2/4 at 100


def test_bars_record_the_repeat_marks():
    bars = {b.number: b for b in ingest(MINUET).bars}
    assert bars[8].ends_repeat
    assert bars[9].starts_repeat
    assert not bars[1].starts_repeat


def test_an_end_repeat_also_reads_as_a_span_end():
    """music21 gives an end repeat the barline type "final"; both flags set."""
    assert {b.number: b for b in ingest(MINUET).bars}[8].ends_span


def test_ragtime_repeats_bracket_the_whole_strain():
    bars = {b.number: b for b in ingest(RAGTIME).bars}
    assert bars[1].starts_repeat
    assert bars[16].ends_repeat


def test_a_score_without_repeat_marks_has_none():
    assert not any(b.starts_repeat or b.ends_repeat for b in ingest(CHORALE).bars)
