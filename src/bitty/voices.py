"""The chiptune roster: who plays, with what timbre, and where in the image.

Five voices declared, three to five active — `[voices] count` narrows it.

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

VOICES = (LEAD, COUNTER, INNER_A, INNER_B, BASS)

MIN_VOICES = 3  # below this there is no middle voice to carry the arpeggio


@dataclass(frozen=True)
class Roster:
    """Who plays, and how many of them.

    Truncation is a view rather than a deletion: `voices` always holds the
    full five and only `active` narrows. That is what lets a config file
    override `inner_b` whether or not some other layer set `count = 3` —
    the voice is still there to override, it just does not play.

    The 3-5 bound is the config validator's job, not this type's. Every
    other range in the pipeline is checked there, and one place beats two.
    """

    voices: tuple[Voice, ...] = VOICES
    count: int = len(VOICES)

    def __iter__(self):
        return iter(self.active)

    def __len__(self):
        return len(self.active)

    @property
    def active(self) -> tuple[Voice, ...]:
        return (self.voices[0], *self._middles, self.voices[-1])

    @property
    def lead(self) -> str:
        return self.voices[0].role

    @property
    def bass(self) -> str:
        return self.voices[-1].role

    @property
    def middles(self) -> tuple[str, ...]:
        return tuple(voice.role for voice in self._middles)

    @property
    def arp(self) -> str:
        """The narrowest surviving middle carries the overflow."""
        return self.middles[-1]

    @property
    def _middles(self) -> tuple[Voice, ...]:
        # Middles fall from the narrowest end: inner_b (duty 0.125) goes
        # before inner_a (0.25), so the widest, most present middle voice
        # survives longest. Width is the rule; that it coincides with
        # reverse declaration order is what makes the slice cheap.
        #
        # max(..., 0) matters below the legal range: a bare `count - 2`
        # goes negative for count < 2, and Python reads a negative slice
        # bound from the right rather than as "stop at zero" — silently
        # handing back voices instead of the empty tuple `.arp` needs to
        # fail loudly on. The 3-5 bound itself still lives in the config
        # validator only; this is just keeping the slice honest at the
        # values the validator does not let through.
        return self.voices[1:-1][: max(self.count - 2, 0)]


ROSTER = Roster()

ECHO_BEATS = 0.75  # the spec's [echo] delay = "3/16" of a whole note
ECHO_LEVEL = 0.35
