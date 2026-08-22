import os
from pathlib import Path

import pytest

from bitty.arrange import arrange
from bitty.ingest import ingest

FIXTURES = Path(__file__).parent / "fixtures"
GOLDENS = Path(__file__).parent / "goldens"
NAMES = ["chorale", "minuet", "ragtime"]
EPSILON = 1e-6


def arranged(name):
    return arrange(ingest(FIXTURES / f"{name}.mxl"))


@pytest.mark.parametrize("name", NAMES)
def test_arrangement_matches_its_golden(name):
    """A reduction regression reads as a JSON diff, not as changed audio."""
    actual = arranged(name).to_json()
    golden = GOLDENS / f"{name}.arrangement.json"
    if os.environ.get("BITTY_UPDATE_GOLDENS"):
        golden.write_text(actual)
    assert actual == golden.read_text(), (
        f"the {name} arrangement changed. If that is intended, regenerate with "
        "BITTY_UPDATE_GOLDENS=1 .venv/bin/pytest tests/test_goldens.py and read the diff."
    )


@pytest.mark.parametrize("name", NAMES)
def test_no_channel_plays_two_notes_at_once(name):
    """A chip channel is monophonic; overlapping events would be a lie."""
    for channel in arranged(name).channels:
        for earlier, later in zip(channel.events, channel.events[1:]):
            assert earlier.t + earlier.dur <= later.t + EPSILON


@pytest.mark.parametrize("name", NAMES)
def test_every_source_note_is_heard(name):
    """Nothing vanishes: overflow arpeggiates, and grace notes get a floor.

    A note counts as heard only if some event starts at its own onset, or if an
    arpeggio step of its pitch falls inside its span. Merely finding the same
    pitch somewhere in the window would let a dropped note be excused by an
    unrelated voice that happens to be playing it.
    """
    score = ingest(FIXTURES / f"{name}.mxl")
    events = [e for c in arranged(name).channels for e in c.events]
    for note in score.notes:
        assert any(
            (e.pitch == note.pitch and abs(e.t - note.start) <= EPSILON)
            or (
                e.arp
                and note.pitch - e.pitch in e.arp
                and note.start - EPSILON <= e.t <= note.start + note.dur + EPSILON
            )
            for e in events
        ), f"{note} never sounds"


@pytest.mark.parametrize("name", NAMES)
def test_events_are_playable(name):
    for channel in arranged(name).channels:
        assert channel.events
        for event in channel.events:
            assert event.dur > 0.0
            assert 0 <= event.vel <= 15


def test_dense_writing_arpeggiates_and_sparse_writing_does_not():
    ragtime = {c.role: c.events for c in arranged("ragtime").channels}
    chorale = {c.role: c.events for c in arranged("chorale").channels}
    assert len([e for e in ragtime["inner_b"] if e.arp]) == 8, (
        "ragtime overflows on eight onsets; a count, not a bool, because "
        "arpeggiating only the first one would satisfy 'some event has arp'"
    )
    assert not [e for e in chorale["inner_b"] if e.arp]
