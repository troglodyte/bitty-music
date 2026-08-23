"""Arrangement quality as numbers, so a regression in the reduction is caught.

Phase 3a recorded its purity percentages in prose and they reproduce exactly.
Its octave-leap counts do not, because the metric behind them was never written
down — so the thresholds here are anchored to `main` at 2026-08-21, measured
before Phase 3b began.
"""

import statistics
from dataclasses import replace
from pathlib import Path

import pytest

from bitty.arrange import _assign, arrange
from bitty.config import DEFAULTS
from bitty.ingest import ingest
from bitty.voices import Roster

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


THIRDS = (3, 4)  # minor and major; a tenth is a third folded into the octave

# (fixture, count): (max arp share %, max hollow chords)
# Anchored to `main` before Phase 8. Nothing is dropped today, so nothing can
# go hollow — every hollow ceiling here is 0 by construction, not by luck.
#
# The hollow-chord side of this table is proven, not just asserted: with
# `_arpeggiate` in `src/bitty/arrange.py` patched to `continue` at the top of
# its `for onset, notes in leftovers:` loop -- discarding overflow instead of
# folding it into a cycle -- 5 of these 9 cases (chorale-3, minuet-3,
# ragtime-3/4/5) failed on the `hollow` assertion itself, not just `arp
# share`, confirming `_hollow` detects a real lost third under a
# drop-everything policy rather than only ever tripping on cycle duration.
REDUCTION = {
    ("chorale", 3): (92.3, 0),
    ("chorale", 4): (0.1, 0),
    ("chorale", 5): (0.1, 0),
    ("minuet", 3): (66.8, 0),
    ("minuet", 4): (0.1, 0),
    ("minuet", 5): (0.1, 0),
    ("ragtime", 3): (59.9, 0),
    ("ragtime", 4): (41.6, 0),
    ("ragtime", 5): (15.7, 0),
}


def _sounding(takes, onset):
    """The takes on one channel still ringing at `onset`."""
    return [t for t in takes if t.t <= onset + EPSILON and t.t + t.dur > onset + EPSILON]


def _arp_share(arrangement, roster):
    """Arpeggiated duration as a fraction of the carrier's sounding duration."""
    events = next(
        (c.events for c in arrangement.channels if c.role == roster.arp), ()
    )
    total = sum(e.dur for e in events)
    arped = sum(e.dur for e in events if e.arp)
    return 100.0 * arped / total if total else 0.0


def _hollow(score, arrangement, roster):
    """Overflow chords that had a third and end up without one.

    Measured at the onsets where reduction actually had a decision to make,
    which is what the policy is answerable for. The bass reference is the
    arrangement's own bass channel: a third is a third above what is heard
    underneath it, not above a note that was itself reduced away.
    """
    tracks, leftovers = _assign(score, roster)
    played = {c.role: c.events for c in arrangement.channels}

    def pitch_classes(onset):
        out = set()
        for events in played.values():
            for event in _sounding(events, onset):
                for offset in event.arp or (0,):
                    out.add((event.pitch + offset) % OCTAVE)
        return out

    hollow = chords = 0
    for onset, notes in leftovers:
        bass = _sounding(played.get(roster.bass, ()), onset)
        if not bass:
            continue
        root = bass[0].pitch
        before = {n.pitch % OCTAVE for n in notes} | {
            t.pitch % OCTAVE
            for takes in tracks.values()
            for t in _sounding(takes, onset)
        }
        if not any((p - root) % OCTAVE in THIRDS for p in before):
            continue  # the chord never had a third to lose
        chords += 1
        if not any((p - root) % OCTAVE in THIRDS for p in pitch_classes(onset)):
            hollow += 1
    return hollow, chords


@pytest.mark.parametrize("name,count", sorted(REDUCTION))
def test_the_reduction_stays_within_its_arp_and_hollow_ceilings(name, count):
    """The arpeggio's share of the piece, and the harmony it costs to shrink it.

    Phase 7's re-audition named this share as the defect. A ceiling rather than
    an equality: the numbers may improve without editing this table, but a
    silent regression back toward a carrier that trills through the whole piece
    fails here.
    """
    max_share, max_hollow = REDUCTION[(name, count)]
    roster = Roster(count=count)
    score = ingest(FIXTURES / f"{name}.mxl")
    arrangement = arrange(score, replace(DEFAULTS, voices=roster))

    share = _arp_share(arrangement, roster)
    hollow, _ = _hollow(score, arrangement, roster)

    assert share <= max_share, f"{name} count={count} arp share {share:.1f}%"
    assert hollow <= max_hollow, f"{name} count={count} hollow chords {hollow}"
