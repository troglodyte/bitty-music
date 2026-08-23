"""Which notes survive reduction.

The arranger places what it can; this decides the fate of what is left over.
Overflow used to be unconditional — any note without a free channel became
arpeggio, however little it contributed — and that is how the carrier came to
trill through 92.2% of the chorale.

Policy only. Building the cycle is `arrange._arpeggiate`'s job, which is why
nothing here knows what a `_Take` is.
"""

from __future__ import annotations

from dataclasses import dataclass

from bitty.model import Note

OCTAVE = 12
MIN_MEMBERS = 3  # two pitches alternating is a trill; naming a chord takes three


@dataclass(frozen=True)
class Drop:
    """The overflow is silent. The carrier keeps whatever it already held."""


@dataclass(frozen=True)
class Cycle:
    """The overflow becomes an arpeggio.

    `pitches` are absolute and already folded into one octave. `keep` is the
    surviving overflow, which the caller needs for the cycle's span and
    velocity and which this module deliberately does not decide.
    """

    pitches: tuple[int, ...]
    keep: tuple[Note, ...]


@dataclass(frozen=True)
class Displace:
    """The carrier's own note is rewritten to `pitch` and stays a plain note."""

    pitch: int


Decision = Drop | Cycle | Displace


def decide(
    notes: tuple[Note, ...],
    carrier: tuple[int, ...],
    sounding: frozenset[int],
    others: frozenset[int],
    bass: int | None,
) -> Decision:
    """The fate of one onset's overflow.

    `sounding` is every pitch class audible at this onset, the carrier
    included; `others` excludes the carrier, because a rule about replacing
    the carrier's note cannot count that note as evidence.
    """
    keep = tuple(n for n in notes if n.pitch % OCTAVE not in sounding)
    if not keep:
        return Drop()
    pitches = _fold({n.pitch for n in keep} | set(carrier))
    if len(pitches) < MIN_MEMBERS:
        return Drop()
    return Cycle(pitches=pitches, keep=keep)


def _fold(members: set[int]) -> tuple[int, ...]:
    """Every member into the octave above the lowest.

    Overflow arrives in whatever register it was written in, and a cycle that
    leaps an octave and a fourth is a siren rather than a chord. A chip
    arpeggio names a chord by cycling its members close together, so pitch
    class is what is worth keeping and register is what is spent to keep it.
    Folding before the set is built also collapses members an octave apart
    into one step instead of cycling the same pitch class twice.
    """
    low = min(members)
    return tuple(sorted({low + (pitch - low) % OCTAVE for pitch in members}))
