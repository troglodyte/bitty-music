from pathlib import Path

from bitty import voices
from bitty.arrange import arrange
from bitty.ingest import ingest
from bitty.model import Note, Score

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"


def note(pitch, start, dur=1.0, velocity=64, part=0):
    return Note(pitch=pitch, start=start, dur=dur, velocity=velocity, part=part)


def score_of(*notes, bpm=120.0, title="test"):
    return Score(notes=tuple(notes), bpm=bpm, time_signature=(4, 4), title=title)


def channels(arrangement):
    return {c.role: c for c in arrangement.channels}


def pitches(arrangement, role):
    return [e.pitch for e in channels(arrangement)[role].events]


def test_a_five_note_chord_fills_all_five_channels():
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0))
    )
    assert set(channels(arrangement)) == {v.role for v in voices.ROSTER}
    assert pitches(arrangement, "lead") == [72]
    assert pitches(arrangement, "bass") == [48]


def test_the_lead_keeps_the_top_line_when_an_inner_voice_moves():
    """The naive reduction hands slot one to whatever is highest right now, so
    the melody teleports the moment an inner voice moves alone. It must not."""
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=2.0),
            note(60, 0.0, dur=2.0),
            note(48, 0.0, dur=2.0),
            note(62, 1.0, dur=1.0),
        )
    )
    assert pitches(arrangement, "lead") == [72]
    assert pitches(arrangement, "bass") == [48]
    assert 62 in [e.pitch for c in arrangement.channels for e in c.events]


def test_a_channel_plays_one_note_at_a_time():
    arrangement = arrange(score_of(note(72, 0.0, dur=4.0), note(74, 1.0, dur=1.0)))
    lead = channels(arrangement)["lead"].events
    assert [e.pitch for e in lead] == [72, 74]
    assert lead[0].dur == 1.0  # cut where the next note begins


def test_silent_channels_are_left_out():
    """A two-voice score should not carry three empty channels: the synth
    divides headroom by channel count, so silent ones only cost loudness."""
    arrangement = arrange(score_of(note(72, 0.0), note(48, 0.0)))
    assert [c.role for c in arrangement.channels] == ["lead", "bass"]


def test_grace_notes_survive_as_short_notes():
    """music21 gives grace notes zero quarter-length. A chip channel cannot
    play zero seconds, so they get a floor instead of disappearing."""
    arrangement = arrange(score_of(note(72, 0.0, dur=1.0), note(79, 0.0, dur=0.0)))
    lead = channels(arrangement)["lead"].events
    assert lead[0].pitch == 79
    assert lead[0].dur == 0.032


def test_a_moving_inner_note_does_not_steal_the_bass():
    """The mirror of the lead case: the bottom of the texture is pinned too."""
    arrangement = arrange(
        score_of(note(72, 0.0, dur=2.0), note(48, 0.0, dur=2.0), note(60, 1.0, dur=1.0))
    )
    assert pitches(arrangement, "bass") == [48]


def test_a_low_note_re_entering_after_a_rest_goes_to_the_bass():
    """With nothing ringing, pinning falls back to what each channel last played.
    Otherwise the melody channel picks up the bass line after every rest, and the
    50%-duty lead pulse ends up playing notes two octaves below the tune."""
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=1.0),
            note(40, 0.0, dur=1.0),
            note(38, 2.0, dur=1.0),  # the bass returns alone after a beat of silence
        )
    )
    assert pitches(arrangement, "bass") == [40, 38]
    assert pitches(arrangement, "lead") == [72]


def test_velocity_is_quantized_to_sixteen_levels():
    arrangement = arrange(ingest(FIXTURE))
    for channel in arrangement.channels:
        for event in channel.events:
            assert 0 <= event.vel <= 15


def test_multi_part_score_keeps_the_top_and_bottom_parts():
    arrangement = arrange(ingest(FIXTURE))
    assert pitches(arrangement, "lead") == [72, 74, 76, 77]
    assert pitches(arrangement, "bass") == [48]


def test_the_roster_supplies_the_timbre_and_the_image():
    arrangement = arrange(ingest(FIXTURE))
    lead = channels(arrangement)["lead"]
    assert lead.instrument == voices.LEAD.instrument
    assert lead.pan == voices.LEAD.pan


def test_only_the_lead_echoes():
    """A delayed bass turns into mud; the tail belongs on the tune."""
    arrangement = arrange(ingest(FIXTURE))
    assert channels(arrangement)["lead"].echo is not None
    assert all(c.echo is None for c in arrangement.channels if c.role != "lead")


def test_echo_delay_tracks_the_tempo():
    """Three sixteenths of a whole note is 0.75 beats — 0.375s at 120 bpm."""
    arrangement = arrange(ingest(FIXTURE))
    assert abs(channels(arrangement)["lead"].echo.delay_sec - 0.375) < 1e-9


def test_arrangement_meta_carries_title_and_tempo():
    arrangement = arrange(ingest(FIXTURE))
    assert arrangement.meta["bpm"] == 120.0
    assert isinstance(arrangement.meta["title"], str)
    assert arrangement.meta["title"]


def test_the_filter_stays_off_by_default():
    arrangement = arrange(ingest(FIXTURE))
    assert all(c.instrument.cutoff_hz is None for c in arrangement.channels)


def test_a_sustained_inner_voice_is_not_cut_short_for_a_nearby_note():
    """Prefer-free: a hole in the harmony costs more than a timbre jump."""
    arrangement = arrange(
        score_of(
            # every middle channel takes a note, so none is attractive merely
            # for being untouched
            note(72, 0.0, dur=0.5),
            note(67, 0.0, dur=0.5),
            note(64, 0.0, dur=0.5),
            note(62, 0.0, dur=0.5),
            note(48, 0.0, dur=0.5),
            # the counter voice then holds 67 for four seconds
            note(72, 0.5, dur=4.0),
            note(67, 0.5, dur=4.0),
            note(48, 0.5, dur=4.0),
            # 66 is nearest to the counter's 67 — but the counter is mid-note
            note(66, 1.0, dur=1.0),
        )
    )
    counter = channels(arrangement)["counter"].events
    assert [e.pitch for e in counter] == [67, 67]
    assert counter[1].dur == 4.0, "the held 67 must survive intact"
    assert 66 in pitches(arrangement, "inner_a")


def test_when_every_channel_is_busy_the_nearest_one_is_stolen():
    """Stealing is the fallback, not the rule — but it is still the fallback."""
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=4.0),
            note(67, 0.0, dur=4.0),
            note(64, 0.0, dur=4.0),
            note(62, 0.0, dur=4.0),
            note(48, 0.0, dur=4.0),
            note(65, 1.0, dur=1.0),  # nearest last pitch is inner_a's 64
        )
    )
    inner_a = channels(arrangement)["inner_a"].events
    assert [e.pitch for e in inner_a] == [64, 65]
    assert inner_a[0].dur == 1.0
