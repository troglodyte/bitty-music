from pathlib import Path

from bitty.arrange import arrange
from bitty.ingest import ingest
from bitty.model import Note, Score

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"


def channel(arrangement, role):
    return next(c for c in arrangement.channels if c.role == role)


def test_multi_part_score_splits_highest_and_lowest_parts():
    arrangement = arrange(ingest(FIXTURE))
    assert [c.role for c in arrangement.channels] == ["lead", "bass"]
    assert [e.pitch for e in channel(arrangement, "lead").events] == [72, 74, 76, 77]
    assert [e.pitch for e in channel(arrangement, "bass").events] == [48]


def test_lead_is_a_pulse_and_bass_is_a_triangle():
    arrangement = arrange(ingest(FIXTURE))
    assert channel(arrangement, "lead").instrument.wave == "pulse"
    assert channel(arrangement, "bass").instrument.wave == "triangle"


def test_velocity_is_quantized_to_sixteen_levels():
    arrangement = arrange(ingest(FIXTURE))
    for chan in arrangement.channels:
        for event in chan.events:
            assert 0 <= event.vel <= 15


def test_single_part_score_splits_top_and_bottom_note_of_each_onset():
    score = Score(
        notes=(
            Note(pitch=72, start=0.0, dur=1.0, velocity=64, part=0),
            Note(pitch=64, start=0.0, dur=1.0, velocity=64, part=0),
            Note(pitch=48, start=0.0, dur=1.0, velocity=64, part=0),
        ),
        bpm=120.0,
        time_signature=(4, 4),
        title="chord",
    )
    arrangement = arrange(score)
    assert [e.pitch for e in channel(arrangement, "lead").events] == [72]
    assert [e.pitch for e in channel(arrangement, "bass").events] == [48]


def test_arrangement_meta_carries_title_and_tempo():
    arrangement = arrange(ingest(FIXTURE))
    assert arrangement.meta["bpm"] == 120.0
    # music21 may synthesize a title from work or movement metadata, so assert
    # only that one is present. Output filenames come from the file stem, not
    # from this field.
    assert isinstance(arrangement.meta["title"], str)
    assert arrangement.meta["title"]
