"""Phase 1 arranger: keep the top line and the bottom line, drop the rest.

Placeholder by design. Phase 3 replaces this with voice-leading assignment
and arpeggio overflow; the only contract that must survive is the shape of
the Arrangement it returns.
"""

from collections import defaultdict
from itertools import groupby

from bitty.arrangement import (
    MAX_VELOCITY,
    Arrangement,
    Channel,
    Echo,
    Event,
    Instrument,
)
from bitty.model import Note, Score

# A short decay plus an upward pitch blip on the attack: the two things that
# separate a chip lead from a sine tone. Levels are 0-15, one per 60th second.
LEAD = Instrument(
    wave="pulse",
    duty=0.5,
    volume_env=(15, 15, 14, 13, 12, 12, 11),
    pitch_env=(2, 1, 0),
)
BASS = Instrument(
    wave="triangle",
    volume_env=(15, 14, 13, 12),
    quantize=16,  # the NES triangle's 16 amplitude steps, and its bite
)

LEAD_PAN = -0.25
BASS_PAN = 0.25
ECHO_BEATS = 0.75  # the spec's [echo] delay = "3/16" of a whole note
ECHO_LEVEL = 0.35


def arrange(score: Score) -> Arrangement:
    lead_notes, bass_notes = _split_voices(score.notes)
    return Arrangement(
        meta={"title": score.title, "bpm": score.bpm},
        channels=(
            Channel(
                role="lead",
                instrument=LEAD,
                events=_to_events(lead_notes),
                pan=LEAD_PAN,
                echo=Echo(delay_sec=_echo_delay(score.bpm), level=ECHO_LEVEL),
            ),
            Channel(
                role="bass",
                instrument=BASS,
                events=_to_events(bass_notes),
                pan=BASS_PAN,
            ),
        ),
    )


def _echo_delay(bpm: float) -> float:
    return ECHO_BEATS * 60.0 / bpm


def _split_voices(notes: tuple[Note, ...]) -> tuple[list[Note], list[Note]]:
    by_part: dict[int, list[Note]] = defaultdict(list)
    for note in notes:
        by_part[note.part].append(note)

    if len(by_part) >= 2:
        ranked = sorted(by_part.values(), key=_mean_pitch)
        return _top_of_each_onset(ranked[-1]), _bottom_of_each_onset(ranked[0])

    single = list(notes)
    return _top_of_each_onset(single), _bottom_of_each_onset(single)


def _mean_pitch(notes: list[Note]) -> float:
    return sum(n.pitch for n in notes) / len(notes)


def _top_of_each_onset(notes: list[Note]) -> list[Note]:
    return [max(group, key=lambda n: n.pitch) for group in _by_onset(notes)]


def _bottom_of_each_onset(notes: list[Note]) -> list[Note]:
    return [min(group, key=lambda n: n.pitch) for group in _by_onset(notes)]


def _by_onset(notes: list[Note]) -> list[list[Note]]:
    ordered = sorted(notes, key=lambda n: n.start)
    return [list(group) for _, group in groupby(ordered, key=lambda n: n.start)]


def _to_events(notes: list[Note]) -> tuple[Event, ...]:
    return tuple(
        Event(
            t=note.start,
            pitch=note.pitch,
            dur=note.dur,
            vel=_quantize_velocity(note.velocity),
        )
        for note in sorted(notes, key=lambda n: n.start)
    )


def _quantize_velocity(velocity: int) -> int:
    """127 MIDI steps down to the 16 levels an 8-bit channel actually has."""
    return max(0, min(MAX_VELOCITY, round(velocity / 127 * MAX_VELOCITY)))
