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


def test_the_lead_gets_a_chip_voice_not_a_bare_square():
    arrangement = arrange(ingest(FIXTURE))
    lead = arrangement.channels[0]
    assert lead.instrument.volume_env != ()
    assert lead.instrument.pitch_env != ()


def test_the_filter_stays_off_by_default():
    """Warmth is a lever, not the default. The spec's target is chiptune."""
    arrangement = arrange(ingest(FIXTURE))
    assert all(c.instrument.cutoff_hz is None for c in arrangement.channels)


def test_the_voices_are_spread_across_the_stereo_image():
    arrangement = arrange(ingest(FIXTURE))
    pans = [c.pan for c in arrangement.channels]
    assert pans[0] != pans[1]
    assert all(abs(p) <= 0.5 for p in pans)


def test_the_lead_echoes_and_the_bass_does_not():
    """A delayed bass turns into mud; the tail belongs on the tune."""
    arrangement = arrange(ingest(FIXTURE))
    lead, bass = arrangement.channels
    assert lead.echo is not None
    assert bass.echo is None


def test_echo_delay_tracks_the_tempo():
    """Three sixteenths of a whole note is 0.75 beats — 0.375s at 120 bpm."""
    arrangement = arrange(ingest(FIXTURE))
    assert abs(arrangement.channels[0].echo.delay_sec - 0.375) < 1e-9
