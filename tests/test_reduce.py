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
