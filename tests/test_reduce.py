"""The reduction policy: which overflow notes survive, and as what."""

from bitty.model import Note
from bitty.reduce import Cycle, Displace, Drop, decide


def note(pitch, start=0.0, dur=1.0, velocity=80):
    return Note(pitch=pitch, start=start, dur=dur, velocity=velocity,
                part=0, beat_strength=1.0)


def test_a_note_already_sounding_is_dropped():
    """It adds nothing the ear can hear, so it does not earn a channel."""
    # E4 (64) overflows, but an E is already sounding: pitch class 4.
    result = decide(
        notes=(note(64),),
        carrier=(60,),
        sounding=frozenset({0, 4, 7}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert result == Drop()


def test_redundancy_is_judged_by_pitch_class_not_pitch():
    """An E5 is as redundant as an E4 when an E is already ringing."""
    result = decide(
        notes=(note(76),),  # E5
        carrier=(60,),
        sounding=frozenset({0, 4, 7}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert result == Drop()


def test_a_new_pitch_class_survives_as_a_cycle():
    """Three distinct pitches after the fold is a chord worth arpeggiating."""
    # Carrier holds C4 (60); B-flat4 (70) and D5 (74) overflow. Neither is
    # sounding, so both survive: {60, 70, 74} folds to C4, D4, B-flat4.
    result = decide(
        notes=(note(70), note(74)),
        carrier=(60,),
        sounding=frozenset({0}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert isinstance(result, Cycle)
    assert result.pitches == (60, 62, 70)
    assert tuple(n.pitch for n in result.keep) == (70, 74)


def test_two_pitches_are_a_trill_not_an_arpeggio():
    """Phase 7 fixed how these cycles sound; this decides they should not exist.

    A chip arpeggio names a chord by cycling its members. Two notes name
    nothing, and every point of the chorale's 92.2% was one of these.
    """
    result = decide(
        notes=(note(67),),           # G4 overflows
        carrier=(60,),               # carrier holds C4
        sounding=frozenset({0}),
        others=frozenset({0, 4}),    # a third is already present elsewhere
        bass=48,
    )
    assert result == Drop()


def test_a_lone_pitch_is_not_a_cycle_either():
    """The minuet carried a one-member `arp`, a plain note with its vibrato
    suppressed for no reason. The same rule removes it."""
    result = decide(
        notes=(note(72),),           # C5 folds onto the carrier's C4
        carrier=(60,),
        sounding=frozenset(),
        others=frozenset({0, 4}),
        bass=48,
    )
    assert result == Drop()


def test_three_pitches_still_survive():
    """The rule removes trills, not arpeggios."""
    result = decide(
        notes=(note(70), note(74)),
        carrier=(60,),
        sounding=frozenset({0}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert isinstance(result, Cycle)
    assert len(result.pitches) == 3


def test_the_only_third_displaces_a_redundant_doubling():
    """Rules 1 and 2 choose by pitch height and never by harmonic function, so
    the third is lost whenever the inner part below happens to hold it."""
    # Bass C3 (48). Carrier holds G4 (67) — a fifth, already doubled in
    # `others`. E4 (64) overflows and is the chord's only third.
    result = decide(
        notes=(note(64),),
        carrier=(67,),
        sounding=frozenset({0, 7}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert result == Displace(pitch=64)


def test_no_rescue_when_a_third_already_sounds():
    """Nothing is at risk, so nothing is worth disturbing the line for."""
    result = decide(
        notes=(note(64),),
        carrier=(67,),
        sounding=frozenset({0, 7}),
        others=frozenset({0, 4, 7}),  # E already present elsewhere
        bass=48,
    )
    assert result == Drop()


def test_no_rescue_when_the_carrier_note_is_not_redundant():
    """Swapping would trade one loss for another, so the line wins."""
    # Carrier holds A4 (69), pitch class 9, which nothing else is playing.
    result = decide(
        notes=(note(64),),
        carrier=(69,),
        sounding=frozenset({0, 7, 9}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert result == Drop()


def test_a_tenth_counts_as_a_third():
    """A third an octave up is the same harmonic fact."""
    result = decide(
        notes=(note(76),),  # E5, a tenth above C3
        carrier=(67,),
        sounding=frozenset({0, 7}),
        others=frozenset({0, 7}),
        bass=48,
    )
    assert result == Displace(pitch=76)
