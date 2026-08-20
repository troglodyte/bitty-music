from pathlib import Path

from bitty.ingest import ingest

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"


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
