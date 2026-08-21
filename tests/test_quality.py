"""Arrangement quality as numbers, so a regression in the reduction is caught.

Phase 3a recorded its purity percentages in prose and they reproduce exactly.
Its octave-leap counts do not, because the metric behind them was never written
down — so the thresholds here are anchored to `main` at 2026-08-21, measured
before Phase 3b began.
"""

import statistics
from pathlib import Path

import pytest

from bitty.arrange import arrange
from bitty.ingest import ingest

FIXTURES = Path(__file__).parent / "fixtures"
EPSILON = 1e-6
OCTAVE = 12

# fixture: (min lead purity %, min bass purity %, max lead leaps)
BASELINE = {
    "chorale": (100.0, 100.0, 0),
    "minuet": (97.4, 85.7, 3),
    "ragtime": (96.6, 98.1, 3),
}


def _measured(name):
    score = ingest(FIXTURES / f"{name}.mxl")
    arrangement = arrange(score)

    pitches: dict[int, list[int]] = {}
    for note in score.notes:
        pitches.setdefault(note.part, []).append(note.pitch)
    top = max(pitches, key=lambda p: statistics.mean(pitches[p]))
    bottom = min(pitches, key=lambda p: statistics.mean(pitches[p]))

    events = {c.role: c.events for c in arrangement.channels}

    def purity(role, part):
        matched = hits = 0
        for event in events.get(role, ()):
            sources = [
                n
                for n in score.notes
                if n.pitch == event.pitch and abs(n.start - event.t) <= EPSILON
            ]
            if not sources:
                continue  # an arpeggio step, which belongs to no single part
            matched += 1
            hits += any(n.part == part for n in sources)
        return 100.0 * hits / matched if matched else 0.0

    lead = events.get("lead", ())
    leaps = sum(1 for a, b in zip(lead, lead[1:]) if abs(a.pitch - b.pitch) >= OCTAVE)
    return purity("lead", top), purity("bass", bottom), leaps


@pytest.mark.parametrize("name", sorted(BASELINE))
def test_the_reduction_holds_its_baseline(name):
    """The melody stays put and the bass stays down, measured rather than heard.

    A failure here means the articulation work cost the voice leading that
    Phase 3a's acceptance listen approved. That is a reason to stop, not to
    lower the numbers.
    """
    min_lead, min_bass, max_leaps = BASELINE[name]
    lead, bass, leaps = _measured(name)
    assert lead >= min_lead - 0.05, f"lead purity fell to {lead:.1f}%"
    assert bass >= min_bass - 0.05, f"bass purity fell to {bass:.1f}%"
    assert leaps <= max_leaps, f"{leaps} octave-plus leaps on the lead"


@pytest.mark.parametrize("name", sorted(BASELINE))
def test_dynamics_are_not_flat(name):
    """The defect this phase exists to fix: every event was vel 8."""
    arrangement = arrange(ingest(FIXTURES / f"{name}.mxl"))
    levels = {e.vel for c in arrangement.channels for e in c.events}
    assert len(levels) > 1, f"{name} renders at a single dynamic level"
