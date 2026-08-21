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
    play zero seconds, so they get a floor instead of disappearing. Which
    channel catches the ornament is not the point here — that it still sounds,
    and sounds briefly, is."""
    arrangement = arrange(score_of(note(72, 0.0, dur=1.0), note(79, 0.0, dur=0.0)))
    grace = [e for c in arrangement.channels for e in c.events if e.pitch == 79]
    assert len(grace) == 1
    assert grace[0].dur == 0.032


def test_a_moving_inner_note_does_not_steal_the_bass():
    """The mirror of the lead case: the bottom of the texture is pinned too."""
    arrangement = arrange(
        score_of(note(72, 0.0, dur=2.0), note(48, 0.0, dur=2.0), note(60, 1.0, dur=1.0))
    )
    assert pitches(arrangement, "bass") == [48]


def test_notes_that_abut_are_not_treated_as_a_rest():
    """Homophonic writing ends every note exactly where the next begins. If that
    counted as silence, pinning would fall back to last pitches, a descending
    soprano would stop reaching the lead, and a chorale would arpeggiate."""
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=1.0),
            note(60, 0.0, dur=1.0),
            note(48, 0.0, dur=1.0),
            note(71, 1.0, dur=1.0),
            note(59, 1.0, dur=1.0),
            note(47, 1.0, dur=1.0),
        )
    )
    assert pitches(arrangement, "lead") == [72, 71]
    assert pitches(arrangement, "bass") == [48, 47]


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


def test_a_six_note_chord_arpeggiates_the_overflow():
    """One channel stepping through the leftovers fast enough to read as chord."""
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=1.0),
            note(69, 0.0, dur=1.0),
            note(67, 0.0, dur=1.0),
            note(64, 0.0, dur=1.0),
            note(62, 0.0, dur=1.0),
            note(48, 0.0, dur=1.0),
        )
    )
    arp = channels(arrangement)["inner_b"].events
    assert len(arp) == 62  # int(1.0 / 0.016)
    assert [e.dur for e in arp] == [0.016] * 62
    # the channel's own note joins the cycle rather than being replaced by it
    assert [e.pitch for e in arp[:4]] == [62, 64, 62, 64]
    assert abs(arp[1].t - 0.016) < 1e-9


def test_nothing_is_dropped_when_the_channels_run_out():
    arrangement = arrange(
        score_of(*[note(p, 0.0, dur=1.0) for p in (72, 69, 67, 64, 62, 60, 48)])
    )
    heard = {e.pitch for c in arrangement.channels for e in c.events}
    assert {72, 69, 67, 64, 62, 60, 48} <= heard


def test_a_grace_note_does_not_take_the_lead_from_the_note_it_ornaments():
    """music21 writes a grace note above the note it decorates and gives it zero
    length. Letting it contest the pin hands the lead a 32ms blip and exiles the
    melody to an inner channel — the exact teleport this phase exists to stop."""
    arrangement = arrange(
        score_of(note(86, 0.0, dur=0.5), note(88, 0.0, dur=0.0), note(60, 0.0, dur=0.5))
    )
    assert pitches(arrangement, "lead") == [86]
    assert 88 in {e.pitch for c in arrangement.channels for e in c.events}


def test_a_chord_re_entering_after_a_rest_still_reaches_lead_and_bass():
    """A lone note after a rest needs its voice inferred; a chord does not. Its
    own top and bottom define the texture, and measuring it against the previous
    phrase leaves both edge channels silent."""
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=1.0),
            note(60, 0.0, dur=1.0),
            note(48, 0.0, dur=1.0),
            note(67, 3.0, dur=1.0),
            note(62, 3.0, dur=1.0),
            note(59, 3.0, dur=1.0),
            note(50, 3.0, dur=1.0),
        )
    )
    assert pitches(arrangement, "lead") == [72, 67]
    assert pitches(arrangement, "bass") == [48, 50]


def test_a_short_dense_chord_still_sounds_every_pitch():
    """A cycle shorter than its pitch set is where voices quietly went missing:
    seven notes lasting 32ms each left room for two arpeggio steps."""
    arrangement = arrange(
        score_of(*[note(p, 0.0, dur=0.032) for p in (72, 69, 67, 64, 62, 60, 48)])
    )
    heard = {e.pitch for c in arrangement.channels for e in c.events}
    assert {72, 69, 67, 64, 62, 60, 48} <= heard


def test_sparse_writing_produces_no_arpeggio():
    arrangement = arrange(
        score_of(note(72, 0.0, dur=1.0), note(64, 0.0, dur=1.0), note(48, 0.0, dur=1.0))
    )
    assert all(e.dur == 1.0 for c in arrangement.channels for e in c.events)


def test_the_arpeggio_never_overlaps_the_channel_s_own_notes():
    arrangement = arrange(
        score_of(
            *[note(p, 0.0, dur=1.0) for p in (72, 69, 67, 64, 62, 48)],
            note(60, 0.5, dur=0.5),  # lands on the arpeggiating channel mid-cycle
        )
    )
    events = channels(arrangement)["inner_b"].events
    for earlier, later in zip(events, events[1:]):
        assert earlier.t + earlier.dur <= later.t + 1e-6
