from pathlib import Path

from bitty.analyze import UNKNOWN_KEY, _key_of
from bitty.ingest import ingest

CHORALE = Path(__file__).parent / "fixtures" / "chorale.mxl"
MINUET = Path(__file__).parent / "fixtures" / "minuet.mxl"
RAGTIME = Path(__file__).parent / "fixtures" / "ragtime.mxl"


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
