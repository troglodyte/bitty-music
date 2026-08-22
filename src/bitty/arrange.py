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
from bitty.lfo import MIN_NOTE_SEC
from bitty.model import Note, Score
from bitty.voices import (
    ARP_ROLE,
    BASS_ROLE,
    ECHO_BEATS,
    ECHO_LEVEL,
    LEAD_ROLE,
    MIDDLE_ROLES,
    ROSTER,
)

EPSILON = 1e-6  # onset times are floats; anything closer than this is one moment
ARP_STEP_SEC = 0.016  # the spec's [arp] rate_ms = 16

DOWNBEAT_STRENGTH = 1.0
SECONDARY_STRENGTH = 0.5
DOWNBEAT_ACCENT = 2
WEAK_BEAT_TRIM = -1


@dataclass
class _Take:
    """A note as placed on one channel. Mutable: a later note truncates it."""

    t: float
    pitch: int
    dur: float
    vel: int


Tracks = dict[str, list[_Take]]


def arrange(score: Score) -> Arrangement:
    tracks, leftovers = _assign(score)
    tracks[ARP_ROLE] = _arpeggiate(leftovers, tracks[ARP_ROLE])

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

    meta = {"title": score.title, "bpm": score.bpm}
    if score.bars:
        meta["bars"] = [score.bars[0].number, score.bars[-1].number]

    return Arrangement(meta=meta, channels=tuple(channels))


def _echo(bpm: float) -> Echo:
    return Echo(delay_sec=ECHO_BEATS * 60.0 / bpm, level=ECHO_LEVEL)


def _assign(score: Score) -> tuple[Tracks, list[tuple[float, list[Note]]]]:
    tracks: Tracks = {voice.role: [] for voice in ROSTER}
    leftovers: list[tuple[float, list[Note]]] = []

    for onset, group in _by_onset(score.notes):
        used: set[str] = set()
        pending = list(group)
        above = _texture(tracks, onset, without=LEAD_ROLE)
        if not above or pending[0].pitch >= max(above):
            _place(tracks[LEAD_ROLE], pending.pop(0))
            used.add(LEAD_ROLE)

        below = _texture(tracks, onset, without=BASS_ROLE)
        if pending and (not below or pending[-1].pitch <= min(below)):
            _place(tracks[BASS_ROLE], pending.pop())
            used.add(BASS_ROLE)

        spare: list[Note] = []
        for note in pending:
            role = _pick_middle(tracks, onset, note, used)
            if role is None:
                spare.append(note)
                continue
            _place(tracks[role], note)
            used.add(role)

        if spare:
            leftovers.append((onset, spare))

    return tracks, leftovers


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
            dur=note.dur,
            vel=_velocity(note),
        )
    )


def _texture(tracks: Tracks, onset: float, *, without: str) -> list[int]:
    """The standing texture a candidate for `without`'s pin is measured against.

    Every channel counts, at what it is holding or — once silent — at what it
    played last. Judging a pin against only the notes still ringing means a
    fragment of the texture restriking alone gets pinned by its own extremes:
    ragtime's left hand strides on while the melody rests, and the top of the
    stride is crowned the tune.

    The pinned channel is the exception, and counts only while it rings. A
    ringing lead cannot be displaced by a passing inner voice; a silent one has
    no claim on a line it is no longer playing, so a soprano descending in a
    chorale need only top the rest of the texture to keep the lead.
    """
    standing: list[int] = []
    for voice in ROSTER:
        takes = tracks[voice.role]
        held = _sounding(takes, onset)
        pitch = held if held is not None else (None if voice.role == without else _last_pitch(takes))
        if pitch is not None:
            standing.append(pitch)
    return standing


def _sounding(takes: list[_Take], t: float) -> int | None:
    """The pitch this channel is still holding at t, or None if it is free."""
    if takes and takes[-1].t + takes[-1].dur > t + EPSILON:
        return takes[-1].pitch
    return None


def _last_pitch(takes: list[_Take]) -> int | None:
    """The last pitch this channel actually sang."""
    return takes[-1].pitch if takes else None


def _pick_middle(tracks: Tracks, onset: float, note: Note, used: set[str]) -> str | None:
    """Nearest last pitch, but only among channels that are not mid-note.

    Stealing is the fallback rather than the rule. A held inner voice cut short
    leaves a hole in the harmony, which the ear reads as the texture breaking;
    a note landing on a further-away channel is only a change of colour.
    """
    options = [role for role in MIDDLE_ROLES if role not in used]
    if not options:
        return None
    free = [role for role in options if _sounding(tracks[role], onset) is None]
    return min(
        free or options,
        key=lambda role: _distance(_last_pitch(tracks[role]), note.pitch),
    )


def _distance(last_pitch: int | None, pitch: int) -> int:
    """An untouched channel wins ties: it has no line to lead away from yet."""
    return 0 if last_pitch is None else abs(last_pitch - pitch)


def _events(takes: list[_Take]) -> tuple[Event, ...]:
    """Takes as contract events, flagging the ones long enough to waver.

    The flag is applied here rather than in `_place` because a take's duration
    is not final until every later note has had its chance to truncate it.
    """
    return tuple(
        Event(
            t=take.t,
            pitch=take.pitch,
            dur=take.dur,
            vel=take.vel,
            vibrato=take.dur >= MIN_NOTE_SEC,
        )
        for take in takes
        if take.dur > EPSILON
    )


def _velocity(note: Note) -> int:
    """The written dynamic, quantized, then lifted or trimmed by metric position.

    Quantize first and accent second: the 16 levels are the texture, and an
    accent that vanished into rounding would not be an accent. The clamp keeps
    a trim from silencing a note outright.
    """
    level = round(note.velocity / 127 * MAX_VELOCITY)
    return max(1, min(MAX_VELOCITY, level + _accent(note.beat_strength)))


def _accent(beat_strength: float) -> int:
    if beat_strength >= DOWNBEAT_STRENGTH:
        return DOWNBEAT_ACCENT
    if beat_strength >= SECONDARY_STRENGTH:
        return 0
    return WEAK_BEAT_TRIM


def _arpeggiate(
    leftovers: list[tuple[float, list[Note]]], takes: list[_Take]
) -> list[_Take]:
    """Fold notes that found no channel into one fast-cycling line.

    The channel's own note at that moment joins the cycle rather than being
    replaced by it, so the arpeggio carries the whole chord and not just the
    part that would otherwise have been lost.
    """
    out = list(takes)

    for onset, notes in leftovers:
        # Partition rather than remove-by-value: `_Take` is a mutable dataclass
        # with structural equality, so `list.remove` would match any take that
        # merely looks the same.
        absorbed = [take for take in out if abs(take.t - onset) <= EPSILON]
        out = [take for take in out if abs(take.t - onset) > EPSILON]

        pitches = sorted({n.pitch for n in notes} | {take.pitch for take in absorbed})
        # The cycle lasts only as long as its shortest member: a note that has
        # ended must not keep sounding just because the arpeggio is still running.
        span = min([n.dur for n in notes] + [take.dur for take in absorbed])
        vel = max(
            [_velocity(n) for n in notes] + [take.vel for take in absorbed]
        )
        out.extend(_arp_cycle(onset, span, pitches, vel))

    return _clip_overlaps(sorted(out, key=lambda take: take.t))


def _arp_cycle(onset: float, span: float, pitches: list[int], vel: int) -> list[_Take]:
    # At least one step per pitch. A short dense chord — an ornament, or a
    # staccato stab — must still sound every note it was handed, even if the
    # cycle then runs slightly past where the chord ended.
    steps = max(len(pitches), int(span / ARP_STEP_SEC))
    return [
        _Take(
            t=onset + step * ARP_STEP_SEC,
            pitch=pitches[step % len(pitches)],
            dur=ARP_STEP_SEC,
            vel=vel,
        )
        for step in range(steps)
    ]


def _clip_overlaps(takes: list[_Take]) -> list[_Take]:
    """One channel, one note — including where a cycle runs into a held note."""
    for earlier, later in zip(takes, takes[1:]):
        if earlier.t + earlier.dur > later.t + EPSILON:
            earlier.dur = later.t - earlier.t
    return [take for take in takes if take.dur > EPSILON]
