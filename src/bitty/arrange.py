"""Score to Arrangement: deciding which chip channel plays each note.

The reduction, not the sound. Notes are grouped by onset; the top of the
sounding texture is pinned to the lead and the bottom to the bass, and
everything between goes to the channel whose last pitch is nearest. A channel
is monophonic, so placing a note on a busy channel truncates what it was
holding.

The naive alternative — re-sort each chord top-to-bottom and hand slot one the
highest note — produces a melody that teleports whenever an inner voice briefly
rises above it. Voice-leading assignment is the difference between a
recognizable tune and note soup.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from bitty.arrangement import MAX_VELOCITY, Arrangement, Channel, Echo, Event
from bitty.model import Note, Score
from bitty.voices import (
    BASS_ROLE,
    ECHO_BEATS,
    ECHO_LEVEL,
    LEAD_ROLE,
    MIDDLE_ROLES,
    ROSTER,
)

EPSILON = 1e-6  # onset times are floats; anything closer than this is one moment
GRACE_SEC = 0.032  # music21 gives grace notes zero length; a channel needs some


@dataclass
class _Take:
    """A note as placed on one channel. Mutable: a later note truncates it."""

    t: float
    pitch: int
    dur: float
    vel: int


Tracks = dict[str, list[_Take]]


def arrange(score: Score) -> Arrangement:
    tracks = _assign(score)

    channels: list[Channel] = []
    for voice in ROSTER:
        events = _events(tracks[voice.role])
        if not events:
            continue  # a two-voice score should not carry three silent channels
        channels.append(
            Channel(
                role=voice.role,
                instrument=voice.instrument,
                events=events,
                pan=voice.pan,
                echo=_echo(score.bpm) if voice.role == LEAD_ROLE else None,
            )
        )

    return Arrangement(
        meta={"title": score.title, "bpm": score.bpm},
        channels=tuple(channels),
    )


def _echo(bpm: float) -> Echo:
    return Echo(delay_sec=ECHO_BEATS * 60.0 / bpm, level=ECHO_LEVEL)


def _assign(score: Score) -> Tracks:
    tracks: Tracks = {voice.role: [] for voice in ROSTER}

    for onset, pending in _by_onset(score.notes):
        used: set[str] = set()
        sounding = [
            pitch
            for pitch in (_sounding(tracks[voice.role], onset) for voice in ROSTER)
            if pitch is not None
        ]
        # Pinning is judged against the whole sounding texture, not just this
        # onset: a lone moving inner note must not displace a lead that is still
        # ringing. After a rest nothing rings at all, and then the comparison
        # falls back to what each channel last played — a note re-entering alone
        # belongs to the voice it continues, not automatically to the lead.
        reference = sounding or [
            pitch
            for pitch in (_last_pitch(tracks[voice.role]) for voice in ROSTER)
            if pitch is not None
        ]

        if not reference or pending[0].pitch >= max(reference):
            _place(tracks[LEAD_ROLE], pending.pop(0))
            used.add(LEAD_ROLE)

        if pending and (not reference or pending[-1].pitch <= min(reference)):
            _place(tracks[BASS_ROLE], pending.pop())
            used.add(BASS_ROLE)

        for note in pending:
            role = _pick_middle(tracks, note, used)
            if role is None:
                continue  # Task 4 turns these leftovers into an arpeggio
            _place(tracks[role], note)
            used.add(role)

    return tracks


def _by_onset(notes: tuple[Note, ...]) -> list[tuple[float, list[Note]]]:
    """Group simultaneous notes, highest pitch first within each group."""
    ordered = sorted(notes, key=lambda n: (n.start, -n.pitch))
    return [(onset, list(group)) for onset, group in groupby(ordered, key=lambda n: n.start)]


def _place(takes: list[_Take], note: Note) -> None:
    """Add a note to a channel, cutting short whatever it was holding."""
    if takes and takes[-1].t + takes[-1].dur > note.start + EPSILON:
        takes[-1].dur = note.start - takes[-1].t
    takes.append(
        _Take(
            t=note.start,
            pitch=note.pitch,
            dur=max(note.dur, GRACE_SEC),
            vel=_quantize_velocity(note.velocity),
        )
    )


def _sounding(takes: list[_Take], t: float) -> int | None:
    """The pitch this channel is still holding at t, or None if it is free."""
    if takes and takes[-1].t + takes[-1].dur > t + EPSILON:
        return takes[-1].pitch
    return None


def _last_pitch(takes: list[_Take]) -> int | None:
    return takes[-1].pitch if takes else None


def _pick_middle(tracks: Tracks, note: Note, used: set[str]) -> str | None:
    options = [role for role in MIDDLE_ROLES if role not in used]
    if not options:
        return None
    return min(options, key=lambda role: _distance(_last_pitch(tracks[role]), note.pitch))


def _distance(last_pitch: int | None, pitch: int) -> int:
    """An untouched channel wins ties: it has no line to lead away from yet."""
    return 0 if last_pitch is None else abs(last_pitch - pitch)


def _events(takes: list[_Take]) -> tuple[Event, ...]:
    return tuple(
        Event(t=take.t, pitch=take.pitch, dur=take.dur, vel=take.vel)
        for take in takes
        if take.dur > EPSILON
    )


def _quantize_velocity(velocity: int) -> int:
    """127 MIDI steps down to the 16 levels an 8-bit channel actually has."""
    return max(0, min(MAX_VELOCITY, round(velocity / 127 * MAX_VELOCITY)))
