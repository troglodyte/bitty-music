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

    The arpeggio half of that is deliberately weaker than the onset half, and
    got weaker still when the cycle began folding into one octave: a folded
    member matches its source note by pitch class, not by pitch. That is a
    real loss and it is the price the fold was chosen for -- an overflowed
    A-flat4 now sounds as A-flat3. What the fold must not do is lose the note
    altogether, and pitch class is what still catches that.

    Phase 8 adds a third fate: a note that only doubles a pitch class already
    sounding elsewhere in the same chord may be dropped outright, or have its
    slot in the reduction handed to a different note that voices the chord's
    third instead (rule 3 displacing a doubling). Such a note is excused from
    the "must be heard" check below only when the score itself already
    contains another simultaneous note of the same pitch class -- i.e. only
    when losing it truly adds nothing new. A note that is not a doubling
    still has to be heard, exactly as before.
    """
    score = ingest(FIXTURES / f"{name}.mxl")
    events = [e for c in arranged(name).channels for e in c.events]
    for i, note in enumerate(score.notes):
        heard = any(
            (e.pitch == note.pitch and abs(e.t - note.start) <= EPSILON)
            or (
                e.arp
                and (note.pitch - e.pitch) % 12 in e.arp
                and note.start - EPSILON <= e.t <= note.start + note.dur + EPSILON
            )
            for e in events
        )
        if heard:
            continue
        doubled = any(
            j != i
            and other.pitch % 12 == note.pitch % 12
            and abs(other.start - note.start) <= EPSILON
            for j, other in enumerate(score.notes)
        )
        assert doubled, f"{note} never sounds and doubles no simultaneous note"


@pytest.mark.parametrize("name", NAMES)
def test_events_are_playable(name):
    for channel in arranged(name).channels:
        assert channel.events
        for event in channel.events:
            assert event.dur > 0.0
            assert 0 <= event.vel <= 15


def test_dense_writing_arpeggiates_and_sparse_writing_does_not():
    """A count, not a bool: 'some event has arp' would be satisfied by a
    single lucky cycle. Phase 8's drop/displace rules cut most of ragtime's
    former overflow down to plain notes or nothing at all, so the count that
    survives is small (one real chord, at t=9.6) -- but it must still be more
    than chorale's sparse writing produces, which is none."""
    ragtime = {c.role: c.events for c in arranged("ragtime").channels}
    chorale = {c.role: c.events for c in arranged("chorale").channels}
    ragtime_arps = [e for e in ragtime["inner_b"] if e.arp]
    chorale_arps = [e for e in chorale["inner_b"] if e.arp]
    assert len(ragtime_arps) > len(chorale_arps), (
        "ragtime's dense writing must still produce at least one real cycle "
        "that chorale's sparse writing does not"
    )
    assert not chorale_arps
