from pathlib import Path

import pytest

from bitty.ingest import ingest

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"
MINUET = Path(__file__).parent / "fixtures" / "minuet.mxl"
ORNAMENTS = Path(__file__).parent / "fixtures" / "ornaments.musicxml"


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
