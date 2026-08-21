"""Score files to the internal Score model, via music21."""

from pathlib import Path

from music21 import chord, converter, dynamics, meter, note, tempo

from bitty.model import Note, Score

DEFAULT_BPM = 120.0
DEFAULT_VELOCITY = 64
NEUTRAL_BEAT_STRENGTH = 0.5


def ingest(path: str | Path) -> Score:
    """Parse a MusicXML, compressed MusicXML, or MIDI file into a Score."""
    path = Path(path)
    parsed = converter.parse(str(path))

    bpm = _first_tempo(parsed)
    seconds_per_quarter = 60.0 / bpm

    notes: list[Note] = []
    for part_index, part in enumerate(parsed.parts):
        marks = _dynamic_marks(part)
        for element in part.flatten().notes:
            start = float(element.offset) * seconds_per_quarter
            dur = float(element.duration.quarterLength) * seconds_per_quarter
            velocity = _velocity_of(element, _velocity_at(marks, float(element.offset)))
            beat_strength = _beat_strength_of(element)
            for pitch in _pitches_of(element):
                notes.append(
                    Note(
                        pitch=pitch,
                        start=start,
                        dur=dur,
                        velocity=velocity,
                        part=part_index,
                        beat_strength=beat_strength,
                    )
                )

    notes.sort(key=lambda n: (n.start, -n.pitch))
    return Score(
        notes=tuple(notes),
        bpm=bpm,
        time_signature=_first_time_signature(parsed),
        title=_title_of(parsed, path),
    )


def _pitches_of(element) -> list[int]:
    if isinstance(element, chord.Chord):
        return [int(p.midi) for p in element.pitches]
    if isinstance(element, note.Note):
        return [int(element.pitch.midi)]
    return []


def _dynamic_marks(part) -> list[tuple[float, int]]:
    """(offset, velocity) for each written dynamic in this part, in order."""
    marks = [
        (float(mark.offset), max(1, min(127, round(mark.volumeScalar * 127))))
        for mark in part.flatten().getElementsByClass(dynamics.Dynamic)
    ]
    marks.sort(key=lambda pair: pair[0])
    return marks


def _velocity_at(marks: list[tuple[float, int]], offset: float) -> int | None:
    """The dynamic governing this offset: the last mark at or before it."""
    governing = None
    for mark_offset, velocity in marks:
        if mark_offset > offset + 1e-9:
            break
        governing = velocity
    return governing


def _velocity_of(element, written: int | None) -> int:
    """An explicit per-note velocity wins; a MIDI source carries one, a score does not."""
    velocity = getattr(element.volume, "velocity", None)
    if velocity is not None:
        return int(velocity)
    return written if written is not None else DEFAULT_VELOCITY


def _beat_strength_of(element) -> float:
    """Where in the bar this note falls, per music21's metric hierarchy.

    Compound meter makes this more than `offset % bar_length`, and a note with
    no time-signature context has no metric position at all — such a note takes
    the neutral value so it is neither accented nor trimmed.
    """
    try:
        strength = element.beatStrength
    except Exception:
        return NEUTRAL_BEAT_STRENGTH
    return NEUTRAL_BEAT_STRENGTH if strength is None else float(strength)


def _first_tempo(parsed) -> float:
    marks = parsed.flatten().getElementsByClass(tempo.MetronomeMark)
    for mark in marks:
        if mark.number:
            return float(mark.number)
    return DEFAULT_BPM


def _first_time_signature(parsed) -> tuple[int, int]:
    signatures = parsed.flatten().getElementsByClass(meter.TimeSignature)
    for signature in signatures:
        return (int(signature.numerator), int(signature.denominator))
    return (4, 4)


def _title_of(parsed, path: Path) -> str:
    metadata = parsed.metadata
    if metadata is not None and metadata.title:
        return str(metadata.title)
    return path.stem
