"""The five-voice roster: who plays, with what timbre, and where in the image.

Data, not policy. This is the table Phase 5's config work overrides, so the
arranger reads it and never hard-codes an instrument or a pan.
"""

from dataclasses import dataclass

from bitty.arrangement import Instrument


@dataclass(frozen=True)
class Voice:
    role: str
    instrument: Instrument
    pan: float


# Volume envelopes are levels 0-15 at 60 steps per second; the last step
# sustains. The pitch envelope is the attack blip that makes a chip lead read
# as percussive rather than as a held tone.
LEAD = Voice(
    role="lead",
    instrument=Instrument(
        wave="pulse",
        duty=0.5,
        volume_env=(15, 15, 14, 13, 12, 12, 11),
        pitch_env=(2, 1, 0),
    ),
    pan=-0.2,
)
COUNTER = Voice(
    role="counter",
    instrument=Instrument(
        wave="pulse",
        duty=0.25,
        volume_env=(13, 13, 12, 11, 10, 10, 9),
        pitch_env=(2, 1, 0),
    ),
    pan=0.45,
)
INNER_A = Voice(
    role="inner_a",
    instrument=Instrument(wave="pulse", duty=0.25, volume_env=(12, 11, 10, 10, 9)),
    pan=-0.45,
)
INNER_B = Voice(
    role="inner_b",
    instrument=Instrument(wave="pulse", duty=0.125, volume_env=(12, 11, 10, 10, 9)),
    pan=0.2,
)
BASS = Voice(
    role="bass",
    instrument=Instrument(wave="triangle", volume_env=(15, 14, 13, 12), quantize=16),
    pan=0.0,
)

ROSTER = (LEAD, COUNTER, INNER_A, INNER_B, BASS)

LEAD_ROLE = LEAD.role
BASS_ROLE = BASS.role
MIDDLE_ROLES = (COUNTER.role, INNER_A.role, INNER_B.role)
ARP_ROLE = INNER_B.role  # the narrowest pulse carries the overflow

ECHO_BEATS = 0.75  # the spec's [echo] delay = "3/16" of a whole note
ECHO_LEVEL = 0.35
