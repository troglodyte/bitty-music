from dataclasses import replace
from pathlib import Path

import pytest

from bitty.arrange import arrange
from bitty.config import Transform
from bitty.ingest import ingest
from bitty.model import Bar, Note, Score
from bitty.transform import MAX_PITCH, apply

FIXTURES = Path(__file__).parent / "fixtures"
NAMES = ["chorale", "minuet", "ragtime"]


def a_score(*notes, bpm=120.0, bars=()):
    """A Score with no file behind it: `apply` is pure, so tests can be too."""
    return Score(
        notes=tuple(notes),
        bpm=bpm,
        time_signature=(4, 4),
        title="probe",
        bars=tuple(bars),
    )


def a_note(pitch=60, start=0.0, dur=1.0, velocity=80):
    return Note(pitch=pitch, start=start, dur=dur, velocity=velocity, part=0)


def test_the_defaults_return_the_very_same_score():
    """Identity, not an arithmetic round trip that happens to land back home.

    `is` rather than `==`: the goldens are valid because the default path does
    nothing at all, and a rebuild that currently compares equal is one float
    away from not.
    """
    score = a_score(a_note(), a_note(pitch=64, start=1.0))
    assert apply(score, Transform()) is score


def test_transpose_shifts_every_pitch():
    score = a_score(a_note(pitch=60), a_note(pitch=64, start=1.0))
    result = apply(score, Transform(transpose=7))
    assert [n.pitch for n in result.notes] == [67, 71]


def test_transpose_moves_nothing_but_pitch():
    """Everything that is not a pitch survives the shift untouched."""
    bar = Bar(number=1, start=0.0, dur=2.0, time_signature=(4, 4), sharps=1)
    score = a_score(a_note(pitch=60, start=0.5, dur=0.25, velocity=99), bars=[bar])
    result = apply(score, Transform(transpose=-5))
    assert result.bpm == score.bpm
    assert result.bars == score.bars
    assert result.title == score.title and result.time_signature == score.time_signature
    before, after = score.notes[0], result.notes[0]
    assert after == replace(before, pitch=before.pitch - 5)


@pytest.mark.parametrize("name", NAMES)
def test_the_whole_arrangement_shifts_with_the_transpose(name):
    """The load-bearing transpose test, and the reason transpose is cheap.

    The arranger has no absolute pitch logic anywhere — top and bottom pinning,
    nearest-last-pitch assignment, the reduction's pitch-class comparison, and
    the arpeggio's octave folding are all relative or uniformly shifted — so
    arranging a transposed score must give back exactly the untransposed
    arrangement with every pitch moved by n.

    Asserted event by whole event rather than over a pitch list: an
    implementation that shifts pitches correctly while dropping arp offsets or
    losing a vibrato flag would pass the coarser check.
    """
    score = ingest(FIXTURES / f"{name}.mxl")
    plain = arrange(score)
    shifted = arrange(apply(score, Transform(transpose=5)))

    assert shifted.meta == plain.meta
    assert len(shifted.channels) == len(plain.channels)
    for was, now in zip(plain.channels, shifted.channels):
        assert now.role == was.role
        assert now.pan == was.pan
        assert now.echo == was.echo
        assert now.instrument == was.instrument
        assert len(now.events) == len(was.events)
        for before, after in zip(was.events, now.events):
            assert after == replace(before, pitch=before.pitch + 5)


def test_the_invariant_fixtures_actually_contain_an_arpeggio():
    """Keeps the test above from guarding arp offsets vacuously.

    Phase 8's reduction left the minuet and the chorale with no arpeggio at
    all at the count-5 default; ragtime is the only fixture whose overflow
    still cycles, so it is the only one carrying the arp half of the
    invariant. If this ever reaches zero, the invariant has quietly stopped
    covering `Event.arp` and needs a fixture that does.
    """
    arranged = arrange(ingest(FIXTURES / "ragtime.mxl"))
    assert sum(1 for c in arranged.channels for e in c.events if e.arp) >= 1


def test_tempo_scale_moves_the_tempo_and_the_notes_together():
    """Faster tempo, shorter times. Scaling bpm alone would relabel and lie."""
    score = a_score(a_note(start=2.0, dur=1.0), bpm=120.0)
    result = apply(score, Transform(tempo_scale=1.5))
    assert result.bpm == 180.0
    assert result.notes[0].start == pytest.approx(2.0 / 1.5)
    assert result.notes[0].dur == pytest.approx(1.0 / 1.5)


def test_tempo_scale_moves_the_bars_with_the_notes():
    """`analyze` reads bars and notes against each other; they cannot drift."""
    bar = Bar(number=1, start=4.0, dur=2.0, time_signature=(3, 4), sharps=1)
    score = a_score(a_note(start=4.0), bars=[bar])
    result = apply(score, Transform(tempo_scale=2.0))
    assert result.bars[0].start == pytest.approx(2.0)
    assert result.bars[0].dur == pytest.approx(1.0)
    assert result.bars[0].number == 1, "a printed bar number is not a time"
    assert result.bars[0].sharps == 1


def test_tempo_scale_leaves_pitch_and_velocity_alone():
    score = a_score(a_note(pitch=71, velocity=99))
    result = apply(score, Transform(tempo_scale=0.5))
    assert result.notes[0].pitch == 71 and result.notes[0].velocity == 99


def test_a_faster_tempo_costs_a_long_note_its_vibrato():
    """The phase's most visible behaviour, and the test that matters most.

    A 520 ms note clears `vibrato.min_note_sec` (500 ms) and wavers. At
    tempo_scale = 1.5 it lasts 347 ms and does not, because the threshold is a
    fact about the ear and stays where it is while the music moves past it.
    That is a re-arrangement, which is the point of taking tempo_scale as an
    arranger input rather than as a playback speed.

    The bpm-only implementation passes every other test here and fails this
    one: its note is still 520 ms long, so it still wavers.
    """
    score = a_score(a_note(dur=0.52))
    assert arrange(score).channels[0].events[0].vibrato is True

    faster = arrange(apply(score, Transform(tempo_scale=1.5)))
    assert faster.channels[0].events[0].dur == pytest.approx(0.52 / 1.5)
    assert faster.channels[0].events[0].vibrato is False


def test_a_slower_tempo_earns_a_short_note_its_vibrato():
    """The same threshold from the other side, so the test cannot pass by
    an implementation that simply drops vibrato whenever a transform ran."""
    score = a_score(a_note(dur=0.4))
    assert arrange(score).channels[0].events[0].vibrato is False

    slower = arrange(apply(score, Transform(tempo_scale=0.5)))
    assert slower.channels[0].events[0].vibrato is True


def test_the_echo_follows_the_tempo_but_the_ear_s_own_constants_do_not():
    """The split between what follows the music and what is absolute.

    The left column of the design's table is derived from bpm and moves; the
    right column is seconds in config, derived from nothing, and must not.
    Scaling `arp_rate_sec` with tempo would undo Phase 7's finding that 48 ms
    is a property of the ear rather than of the music.

    The left-hand assertion is not, by itself, a guard against this phase's
    central decision — that `tempo_scale` re-derives the arrangement rather
    than replaying it faster. `_echo` derives `delay_sec` from `bpm` alone,
    so the bpm-only implementation — the wrong one this phase exists to rule
    out, which halves `bpm` without moving a single note — satisfies
    `now_echo.delay_sec == was_echo.delay_sec / 2.0` unchanged. This test's
    real job is the right-hand column: guarding that `arp_rate_sec`,
    `vibrato_rate_hz`, and `vibrato_delay` stay absolute rather than being
    scaled along with the tempo, a distinct bug none of the other
    `tempo_scale` tests check for. The bpm-only implementation itself is
    caught four times over regardless — by the two vibrato tests, by
    `test_tempo_scale_moves_the_tempo_and_the_notes_together`, and by
    `test_convert_obeys_the_tempo_scale` in `test_cli.py` — so do not mistake
    this test for that guard and conclude the vibrato pair is redundant.
    """
    score = ingest(FIXTURES / "ragtime.mxl")
    plain = arrange(score)
    faster = arrange(apply(score, Transform(tempo_scale=2.0)))

    was_echo = next(c.echo for c in plain.channels if c.echo)
    now_echo = next(c.echo for c in faster.channels if c.echo)
    assert now_echo.delay_sec == pytest.approx(was_echo.delay_sec / 2.0)
    assert now_echo.level == was_echo.level

    for was, now in zip(plain.channels, faster.channels):
        assert now.instrument.arp_rate_sec == was.instrument.arp_rate_sec
        assert now.instrument.vibrato_rate_hz == was.instrument.vibrato_rate_hz
        assert now.instrument.vibrato_delay == was.instrument.vibrato_delay


def test_a_transpose_past_the_ceiling_names_the_arithmetic():
    """A refusal that says which note, where it lands, and what would fit.

    'out of range' would leave the reader to find the offending note and do
    the subtraction themselves, on a knob whose whole purpose is being swept.
    """
    score = a_score(a_note(pitch=60), a_note(pitch=108, start=1.0))
    with pytest.raises(ValueError) as error:
        apply(score, Transform(transpose=7))
    message = str(error.value)
    assert "transform.transpose = +7" in message
    assert "C8 (MIDI 108)" in message
    assert "MIDI 115" in message
    assert "ceiling of 108" in message
    assert "at most +0" in message


def test_a_transpose_under_the_floor_names_the_arithmetic():
    score = a_score(a_note(pitch=36), a_note(pitch=30, start=1.0))
    with pytest.raises(ValueError) as error:
        apply(score, Transform(transpose=-12))
    message = str(error.value)
    assert "transform.transpose = -12" in message
    assert "F#1 (MIDI 30)" in message
    assert "MIDI 18" in message
    assert "floor of 24" in message
    assert "at least -6" in message


def test_the_largest_transpose_that_fits_is_accepted():
    """The bound is the edge of the band, not one short of it."""
    score = a_score(a_note(pitch=101))
    assert apply(score, Transform(transpose=7)).notes[0].pitch == MAX_PITCH


def test_the_range_is_judged_after_the_shift_not_before():
    """A score already sitting on the ceiling may still be transposed down."""
    score = a_score(a_note(pitch=108))
    assert apply(score, Transform(transpose=-12)).notes[0].pitch == 96


def test_a_score_with_no_notes_refuses_nothing():
    assert apply(a_score(), Transform(transpose=48)).notes == ()
