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


def apply(score: Score, settings: Transform) -> Score:
    """A transposed, re-tempo'd score. Under the defaults, the same object."""
    if settings.transpose == 0 and settings.tempo_scale == 1.0:
        return score

    shift = settings.transpose
    return replace(
        score,
        notes=tuple(replace(note, pitch=note.pitch + shift) for note in score.notes),
    )
