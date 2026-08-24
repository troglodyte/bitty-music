"""Change what the music *is*, before any chiptune decision is made.

Separate from `ingest` because the jobs differ. Ingest resolves what the
notation *means*: dynamics into velocities, a trill into the fast notes it
stands for, a grace note moved to sound before what it decorates. This module
changes the music itself, and the split is what makes it testable on a
hand-built `Score` — no score file, no music21, no I/O.

`apply` runs at exactly two call sites, both immediately after `ingest`, so
`analyze`, `arrange`, `loop`, `synth`, and the emitters see only the
transformed score and need no knowledge that a transform happened. `render`
deliberately does not call it: everything musical was decided when the
arrangement JSON was written, and transforming again would land a `+3` convert
at `+6` on re-render.
"""

from __future__ import annotations

from dataclasses import replace

from bitty.config import Transform
from bitty.model import Score

# The playable band, and the binding limit is audibility rather than Nyquist:
# a fundamental past 0.45 * 44100 is around MIDI 135, which no real score
# reaches, and PolyBLEP bandlimits the harmonics above it anyway. C1 is where
# the quantized triangle bass stops reading as pitch on a small speaker; C8 is
# where the top stops being a note and starts being a whistle. Both are
# calibration set by audition, and Phase 5b settled that calibration stays
# out of the TOML: the band is a property of the synth and the speaker, not
# of any one piece, so it is not a per-score taste the way a transpose is.
MIN_PITCH = 24  # C1, 32.7 Hz
MAX_PITCH = 108  # C8, 4186 Hz

_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def apply(score: Score, settings: Transform) -> Score:
    """A transposed, re-tempo'd score. Under the defaults, the same object."""
    if settings.transpose == 0 and settings.tempo_scale == 1.0:
        return score

    shift = settings.transpose
    _check_fits(score, shift)
    scale = settings.tempo_scale
    return replace(
        score,
        bpm=score.bpm * scale,
        notes=tuple(
            replace(
                note,
                pitch=note.pitch + shift,
                start=note.start / scale,
                dur=note.dur / scale,
            )
            for note in score.notes
        ),
        # Bars carry times too, and `analyze` reads them against the notes.
        # Scaling one and not the other is a score whose barlines have slid.
        bars=tuple(
            replace(bar, start=bar.start / scale, dur=bar.dur / scale)
            for bar in score.bars
        ),
    )


def _check_fits(score: Score, shift: int) -> None:
    """Refuse a shift this score cannot take, naming the note that decides it.

    Refusing rather than folding the offender back into the band: an octave
    leap dropped into the middle of a phrase is exactly the note soup that
    voice-leading assignment exists to prevent. A transpose that does not fit
    is a config error, not something to quietly repair.

    `ValueError` rather than a CLI error because this module has never heard
    of a flag or a file — `loop.trim` and `loop.candidates` raise the same way,
    and the CLI adds the provenance it alone knows.
    """
    if not score.notes or shift == 0:
        return

    top = max(note.pitch for note in score.notes)
    if top + shift > MAX_PITCH:
        raise ValueError(
            f"transform.transpose = {shift:+d}: {_name(top)} (MIDI {top}) becomes "
            f"MIDI {top + shift}, past the playable ceiling of {MAX_PITCH}. "
            f"This score allows at most {MAX_PITCH - top:+d}."
        )

    bottom = min(note.pitch for note in score.notes)
    if bottom + shift < MIN_PITCH:
        raise ValueError(
            f"transform.transpose = {shift:+d}: {_name(bottom)} (MIDI {bottom}) becomes "
            f"MIDI {bottom + shift}, under the playable floor of {MIN_PITCH}. "
            f"This score allows at least {MIN_PITCH - bottom:+d}."
        )


def _name(pitch: int) -> str:
    """MIDI number to the name a person would say, e.g. 108 -> C8."""
    return f"{_NAMES[pitch % 12]}{pitch // 12 - 1}"
