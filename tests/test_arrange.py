from dataclasses import replace
from pathlib import Path

import pytest

from bitty import voices
from bitty.arrange import _velocity, arrange
from bitty.config import DEFAULTS, merge
from bitty.ingest import ingest
from bitty.model import Note, Score

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"


def note(pitch, start, dur=1.0, velocity=64, part=0, beat_strength=0.5):
    return Note(
        pitch=pitch,
        start=start,
        dur=dur,
        velocity=velocity,
        part=part,
        beat_strength=beat_strength,
    )


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



def test_the_melody_keeps_the_lead_while_the_accompaniment_strides_alone():
    """Ragtime's left hand restrikes on the offbeat while the melody rests, and
    its notes abut the previous chord exactly, so nothing is ringing and no rest
    separates them. Pinning that fragment by its own extremes crowns the stride
    bass's top note as the melody, and the tune teleports down a tenth and back
    every other beat."""
    arrangement = arrange(
        score_of(
            note(75, 0.0, dur=1.0),
            note(60, 0.0, dur=1.0),
            note(48, 0.0, dur=1.0),
            note(56, 1.0, dur=1.0),  # the left hand alone, abutting the chord
            note(44, 1.0, dur=1.0),
            note(75, 2.0, dur=1.0),  # the melody returns
        )
    )
    assert pitches(arrangement, "lead") == [75, 75]



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


def test_a_six_note_chord_drops_the_overflow_that_cant_form_a_chord():
    """The leftover note (62) folds with the carrier's own note (64) to just
    two pitches -- 62 and 64 are a tone apart, and no fold widens that. Two
    pitches is a trill, not a chord, so rule 2 drops the leftover rather than
    cycling it. Nothing rescues it either: 62 is not the chord's third above
    the bass. The carrier keeps its own note, untouched."""
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
    inner_b = channels(arrangement)["inner_b"].events
    assert len(inner_b) == 1
    assert inner_b[0].pitch == 64
    assert inner_b[0].dur == 1.0
    assert inner_b[0].arp == (), "two pitches can't cycle; the carrier stays plain"
    heard = {
        e.pitch + offset
        for c in arrangement.channels
        for e in c.events
        for offset in (e.arp or (0,))
    }
    assert 62 not in heard, "the dropped note must not sneak back in anywhere"


def test_a_doubled_pitch_class_and_an_unrescuable_pair_are_dropped():
    """One note wider than the six-note case above. 60 duplicates a pitch
    class already sounding (72 and 48 are both C), so rule 1 drops it before
    the fold even runs. That leaves 62 alone against the carrier's own note
    (64) -- the same two-pitch, no-third situation as above -- so rule 2
    drops it too. Every other pitch, including the carrier's own, still
    sounds at its own value: the overflow that survives fits inside one
    octave already, so exact pitch is the strongest thing assertable here.
    Once the overflow no longer fits, the fold trades register for
    closeness and only pitch class survives -- that is what
    `test_the_arpeggio_stays_inside_one_octave` covers."""
    arrangement = arrange(
        score_of(*[note(p, 0.0, dur=1.0) for p in (72, 69, 67, 64, 62, 60, 48)])
    )
    heard = {
        e.pitch + offset
        for c in arrangement.channels
        for e in c.events
        for offset in (e.arp or (0,))
    }
    assert {72, 69, 67, 64, 48} <= heard
    assert 60 not in heard, "60 doubles a pitch class already sounding (rule 1)"
    assert 62 not in heard, "62 can't form a cycle and isn't the chord's third (rule 2)"



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


def test_drop_decisions_dont_depend_on_note_duration():
    """Same seven-note overflow as
    `test_a_doubled_pitch_class_and_an_unrescuable_pair_are_dropped`, at 32ms
    a note instead of a full second. `decide()` never looks at duration, only
    pitch class, so the same two notes (60, 62) are dropped and the same five
    survive, regardless of how long any of them last.

    This scenario used to guard the span floor
    (`max(span, len(pitches) * rate_sec)`) that keeps a short dense cycle from
    skipping members -- that guard is still asserted live, on a chord that
    actually cycles, by `test_a_short_dense_chord_still_sounds_every_member`
    (roster_of(3))."""
    arrangement = arrange(
        score_of(*[note(p, 0.0, dur=0.032) for p in (72, 69, 67, 64, 62, 60, 48)])
    )
    heard = {
        e.pitch + offset
        for c in arrangement.channels
        for e in c.events
        for offset in (e.arp or (0,))
    }
    assert {72, 69, 67, 64, 48} <= heard
    assert 60 not in heard
    assert 62 not in heard


def test_sparse_writing_produces_no_arpeggio():
    """`dur == 1.0` alone stopped meaning anything once the arpeggio became one
    note instead of many: a spuriously arpeggiated sparse chord now keeps the
    chord's own duration too. Absence of `arp` is what the name claims."""
    arrangement = arrange(
        score_of(note(72, 0.0, dur=1.0), note(64, 0.0, dur=1.0), note(48, 0.0, dur=1.0))
    )
    assert all(
        e.dur == 1.0 and not e.arp for c in arrangement.channels for e in c.events
    )


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


def test_a_downbeat_is_louder_than_a_weak_beat():
    downbeat = _velocity(note(60, 0.0, beat_strength=1.0))
    secondary = _velocity(note(60, 0.0, beat_strength=0.5))
    weak = _velocity(note(60, 0.0, beat_strength=0.25))
    assert downbeat == secondary + 2
    assert weak == secondary - 1


def test_accent_never_silences_a_note_or_exceeds_the_ceiling():
    loudest = note(60, 0.0, velocity=127, beat_strength=1.0)
    quietest = note(60, 0.0, velocity=1, beat_strength=0.25)
    assert _velocity(loudest) == 15
    assert _velocity(quietest) >= 1


def test_sustained_notes_get_vibrato_and_short_ones_do_not():
    arrangement = arrange(score_of(note(72, 0.0, dur=2.0), note(74, 2.0, dur=0.1)))
    events = [e for c in arrangement.channels for e in c.events]
    assert [e.vibrato for e in events] == [True, False]


def test_a_note_truncated_below_the_threshold_loses_its_vibrato():
    """The final duration decides, not the length the note was written at.

    A note cut short by a re-entering voice should not waver on the strength of
    a length it never got to play. Here the held note is written as a whole bar
    and stolen after a tenth of a second.
    """
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=2.0),
            note(72, 0.1, dur=2.0),  # same channel, so the first is truncated
        )
    )
    lead = channels(arrangement)["lead"].events
    assert lead[0].dur == pytest.approx(0.1)
    assert not lead[0].vibrato, "a note cut to 100 ms must not claim a 2-second vibrato"
    assert lead[1].vibrato


def test_echo_off_leaves_the_lead_with_no_echo_object():
    """Not a silent echo — none. The arrangement should say which it is."""
    score = ingest(FIXTURE)
    settings = replace(DEFAULTS, echo=replace(DEFAULTS.echo, on=False))
    for channel in arrange(score, settings).channels:
        assert channel.echo is None


def test_the_echo_level_and_delay_come_from_config():
    score = ingest(FIXTURE)
    settings = replace(DEFAULTS, echo=replace(DEFAULTS.echo, level=0.6, delay_beats=1.5))
    lead = next(c for c in arrange(score, settings).channels if c.echo is not None)
    assert lead.echo.level == 0.6
    assert lead.echo.delay_sec == 1.5 * 60.0 / score.bpm


def test_a_reshaped_voice_reaches_the_channel_it_names():
    score = ingest(FIXTURE)
    reshaped = tuple(
        replace(v, instrument=replace(v.instrument, duty=0.125)) if v.role == "lead" else v
        for v in DEFAULTS.voices.voices
    )
    roster = replace(DEFAULTS.voices, voices=reshaped)
    lead = next(c for c in arrange(score, replace(DEFAULTS, voices=roster)).channels if c.role == "lead")
    assert lead.instrument.duty == 0.125


def test_the_vibrato_threshold_decides_which_notes_get_it():
    score = ingest(FIXTURE)
    never = replace(DEFAULTS, vibrato=replace(DEFAULTS.vibrato, min_note_sec=999.0))
    always = replace(DEFAULTS, vibrato=replace(DEFAULTS.vibrato, min_note_sec=0.0))
    assert not any(e.vibrato for c in arrange(score, never).channels for e in c.events)
    assert all(e.vibrato for c in arrange(score, always).channels for e in c.events)


def test_the_arpeggio_step_comes_from_config():
    """`[arp] rate_ms` only reaches the arranger by spreading onto the carrier's
    own instrument (Task 2), so this must go through `merge` rather than a bare
    `replace` — a hand-built config would leave `arp_rate_sec` at its default
    and this test would pass for the wrong reason. The chord is short and
    dense so its span is rate-dominated rather than chord-duration-dominated,
    which is what lets the rate's effect show up in `dur` at all."""
    score = score_of(
        note(72, 0.0, dur=0.01), note(69, 0.0, dur=0.01),
        note(67, 0.0, dur=0.01), note(64, 0.0, dur=0.01), note(48, 0.0, dur=0.01),
    )
    settings = merge(roster_of(3), "[arp]\nrate_ms = 32\n", "test")
    event = channels(arrange(score, settings))["counter"].events[0]
    assert event.arp
    assert event.dur == pytest.approx(len(event.arp) * 0.032)
    assert event.dur != pytest.approx(len(event.arp) * 0.016)


def test_the_arpeggio_rate_travels_in_the_instrument_not_the_config():
    """The test that excludes reading the config table.

    `merge` sets `[arp] rate_ms` on the table *and* spreads it onto every
    instrument, so the test above passes whichever of the two the arranger
    reads. Moving only the carrier's instrument, with the table left at its
    default, is what tells them apart — and it is exactly the case a
    hand-edited arrangement with no config anywhere relies on.
    """
    settings = roster_of(3)
    voices_cfg = settings.voices
    carrier = voices_cfg.voices[1]
    assert carrier.role == voices_cfg.arp, "count 3 puts the overflow on the counter"
    settings = replace(
        settings,
        voices=replace(
            voices_cfg,
            voices=(
                voices_cfg.voices[0],
                replace(carrier, instrument=replace(carrier.instrument, arp_rate_sec=0.032)),
                *voices_cfg.voices[2:],
            ),
        ),
    )
    assert settings.arp.step_sec == 0.048, "the table must stay put or this proves nothing"
    score = score_of(
        note(72, 0.0, dur=0.01), note(69, 0.0, dur=0.01),
        note(67, 0.0, dur=0.01), note(64, 0.0, dur=0.01), note(48, 0.0, dur=0.01),
    )
    event = channels(arrange(score, settings))["counter"].events[0]
    assert event.arp
    assert event.dur == pytest.approx(len(event.arp) * 0.032)


def test_the_default_argument_still_arranges():
    score = ingest(FIXTURE)
    assert arrange(score) == arrange(score, DEFAULTS)


def test_overflow_becomes_one_cycling_event_not_a_burst_of_steps():
    """The whole point of the phase: one note whose pitch cycles."""
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0)),
        roster_of(3),
    )
    carried = channels(arrangement)["counter"].events
    assert len(carried) == 1, "one event, not sixty-two"
    event = carried[0]
    assert event.pitch == 64, "the cycle is anchored on its lowest member"
    assert event.arp == (0, 3, 5), "64, 67 and 69 as offsets from 64"
    assert event.dur > 0.9, "and it lasts as long as the chord, not 16ms"


def test_an_arpeggiated_event_does_not_also_waver():
    """A pitch already stepping through a chord does not want a slow LFO too."""
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0)),
        roster_of(3),
    )
    event = channels(arrangement)["counter"].events[0]
    assert event.arp and event.vibrato is False
    lead = channels(arrangement)["lead"].events[0]
    assert not lead.arp and lead.vibrato is True, "the rule still applies elsewhere"


def test_a_short_dense_chord_still_sounds_every_member():
    """The rule the old `max(len(pitches), ...)` protected, kept."""
    arrangement = arrange(
        score_of(
            note(72, 0.0, dur=0.01), note(69, 0.0, dur=0.01),
            note(67, 0.0, dur=0.01), note(64, 0.0, dur=0.01), note(48, 0.0, dur=0.01),
        ),
        roster_of(3),
    )
    event = channels(arrangement)["counter"].events[0]
    assert event.dur >= len(event.arp) * DEFAULTS.voices.voices[1].instrument.arp_rate_sec


def roster_of(count):
    return replace(DEFAULTS, voices=replace(DEFAULTS.voices, count=count))


def test_three_voices_play_only_lead_counter_and_bass():
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0)),
        roster_of(3),
    )
    assert set(channels(arrangement)) == {"lead", "counter", "bass"}
    assert pitches(arrangement, "lead") == [72]
    assert pitches(arrangement, "bass") == [48]


def test_the_notes_a_dropped_voice_would_have_taken_reach_the_arpeggio():
    """The test that excludes the coarse implementation.

    Simply deleting channels after arranging also yields three channels —
    and silently loses 69, 67, and 64. The overflow has to arrive on the
    carrier, which at count 3 is the counter.
    """
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0)),
        roster_of(3),
    )
    carried = channels(arrangement)["counter"].events
    assert len(carried) == 1, "one cycling note, not a channel per dropped voice"
    event = carried[0]
    assert {event.pitch + offset for offset in event.arp} == {69, 67, 64}


def test_four_voices_drop_a_third_when_the_carriers_own_note_isnt_a_doubling():
    """64 is the chord's only third above the bass (48) -- the usual case for
    rule 3 to displace a doubling with it. But inner_a's own note (67) is not
    a doubling of anything else sounding (lead 72 and counter 69 are neither
    of them a 67), so replacing it would trade a real note for another real
    note rather than for a redundant one. Rule 3 declines, and 64 is
    genuinely dropped rather than displacing 67."""
    arrangement = arrange(
        score_of(note(72, 0.0), note(69, 0.0), note(67, 0.0), note(64, 0.0), note(48, 0.0)),
        roster_of(4),
    )
    assert set(channels(arrangement)) == {"lead", "counter", "inner_a", "bass"}
    assert pitches(arrangement, "inner_a") == [67], "67 must survive untouched"
    heard = {
        e.pitch + offset
        for c in arrangement.channels
        for e in c.events
        for offset in (e.arp or (0,))
    }
    assert 64 not in heard, "the third is dropped, not displacing a non-doubling"


def test_the_echo_follows_the_lead_at_every_count():
    for count in (3, 4, 5):
        arrangement = arrange(score_of(note(72, 0.0), note(48, 0.0)), roster_of(count))
        with_echo = [c.role for c in arrangement.channels if c.echo is not None]
        assert with_echo == ["lead"]


def test_the_arpeggio_stays_inside_one_octave():
    """The test that excludes taking overflow pitches as they lie.

    With a three-voice roster, the counter is both the carrier and the
    dumping ground for overflow. Its own note (79) sits nearly two octaves
    above the lowest overflow member (57) -- taken as written, cycling
    between them would be a siren, not a chord. Nothing about that reads as
    a chord; it reads as a siren. A chip arpeggio names a chord by cycling
    its members close together, so every member folds into the octave above
    the lowest: 79 becomes 67, a fourth above 66 and inside the same octave
    as the other two members. Pitch class is what survives, register is not.
    """
    arrangement = arrange(
        score_of(
            note(82, 0.0, dur=0.3),  # lead
            note(79, 0.0, dur=0.3),  # counter's own note, before overflow
            note(66, 0.0, dur=0.3),
            note(57, 0.0, dur=0.3),
            note(40, 0.0, dur=0.3),  # bass
        ),
        roster_of(3),
    )
    arped = [e for c in arrangement.channels for e in c.events if e.arp]
    assert arped, "this overflow must still form a real cycle"
    for event in arped:
        assert max(event.arp) < 12, f"{event.arp} leaps out of the octave"
        members = {event.pitch + offset for offset in event.arp}
        assert 67 in members, "79 folds down into this octave as 67"
        assert 79 not in members, "the raw, unfolded pitch must not survive"


def test_the_default_arpeggio_is_slower_than_the_ear_fuses():
    """Above roughly 20 Hz a cycle stops being heard as notes and becomes a
    rough timbre — the reason the arpeggio sounded harsh even once it was in
    tune. The hardware rate of one step per frame puts a two-note cycle at
    31 Hz, squarely inside that band. The default has to clear it for the
    smallest cycle there is, which is the two-note one."""
    rate = DEFAULTS.voices.voices[1].instrument.arp_rate_sec
    assert 1.0 / (2 * rate) < 20.0, "a two-note cycle must be heard as two notes"
