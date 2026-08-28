"""The groove: a pattern per meter, placed on the score's own barlines."""

from dataclasses import replace
from pathlib import Path

import pytest

from bitty import loop as loop_stage
from bitty import percussion, synth
from bitty.analyze import analyze
from bitty.arrange import arrange
from bitty.config import DEFAULTS, Transform, load, preset_names
from bitty.ingest import ingest
from bitty.model import Bar
from bitty.transform import apply

FIXTURES = Path(__file__).parent / "fixtures"
NAMES = ["chorale", "minuet", "ragtime"]

EPSILON = 1e-6


def bars(count, signature=(4, 4), bpm=120.0, quarters=None):
    """A run of uniform bars, timed the way ingest times them."""
    if quarters is None:
        quarters = signature[0] * 4 / signature[1]
    dur = quarters * 60.0 / bpm
    return tuple(
        Bar(
            number=i + 1,
            start=i * dur,
            dur=dur,
            time_signature=signature,
            sharps=0,
        )
        for i in range(count)
    )


def times(events, pitch=None):
    return [
        round(e.t, 6) for e in events if pitch is None or e.pitch == pitch
    ]


def test_a_four_four_bar_places_its_kicks_on_one_and_three():
    events = percussion.groove(bars(1), 120.0, 1.0)
    assert times(events, percussion.PITCH[percussion.KICK]) == [0.0, 1.0]


def test_placement_converts_through_bpm():
    """At 60 bpm a quarter is a full second; at 120 it is half of one."""
    slow = percussion.groove(bars(1, bpm=60.0), 60.0, 1.0)
    assert times(slow, percussion.PITCH[percussion.KICK]) == [0.0, 2.0]


def test_the_second_bar_starts_where_the_first_ends():
    events = percussion.groove(bars(2), 120.0, 1.0)
    assert times(events, percussion.PITCH[percussion.KICK]) == [0.0, 1.0, 2.0, 3.0]


def test_three_four_has_no_backbeat():
    """A waltz that gets a backbeat stops being a waltz."""
    events = percussion.groove(bars(1, signature=(3, 4)), 120.0, 1.0)
    assert times(events, percussion.PITCH[percussion.SNARE]) == []
    assert times(events, percussion.PITCH[percussion.KICK]) == [0.0]


def test_six_eight_is_three_quarters_long():
    """Positions are quarters, so 6/8's snare at 1.5 lands mid-bar."""
    events = percussion.groove(bars(1, signature=(6, 8)), 120.0, 1.0)
    assert times(events, percussion.PITCH[percussion.SNARE]) == [0.75]


def test_a_pickup_bar_keeps_only_the_hits_that_fit():
    """A short bar is not a licence to spill hits past its own barline."""
    pickup = bars(1, quarters=1.0)  # one quarter of a 4/4 bar
    events = percussion.groove(pickup, 120.0, 1.0)
    assert all(e.t < pickup[0].dur - EPSILON for e in events)
    assert times(events, percussion.PITCH[percussion.KICK]) == [0.0]


def test_each_bar_uses_its_own_signature():
    """analyze splits sections on a meter change; a groove must follow it."""
    first = bars(1, signature=(4, 4))[0]
    second = Bar(
        number=2,
        start=first.dur,
        dur=1.5,
        time_signature=(3, 4),
        sharps=0,
    )
    events = percussion.groove((first, second), 120.0, 1.0)
    late = [e for e in events if e.t >= first.dur - EPSILON]
    assert percussion.PITCH[percussion.SNARE] not in {e.pitch for e in late}


def test_an_unlisted_meter_refuses_by_name():
    with pytest.raises(ValueError) as error:
        percussion.groove(bars(1, signature=(5, 4), quarters=5.0), 120.0, 1.0)
    message = str(error.value)
    assert "bar 1" in message
    assert "5/4" in message


def test_level_scales_velocity():
    full = percussion.groove(bars(1), 120.0, 1.0)
    half = percussion.groove(bars(1), 120.0, 0.5)
    assert max(e.vel for e in half) < max(e.vel for e in full)
    assert max(e.vel for e in full) <= 15


def test_no_bars_is_no_groove():
    assert percussion.groove((), 120.0, 1.0) == ()


def test_a_hat_on_a_downbeat_loses_to_the_kick():
    """Priority resolves the collision in the musical direction."""
    events = percussion.groove(bars(1), 120.0, 1.0)
    at_zero = [e for e in events if abs(e.t) < EPSILON]
    assert len(at_zero) == 1
    assert at_zero[0].pitch == percussion.PITCH[percussion.KICK]


def test_no_two_events_overlap():
    """The same rule test_goldens holds every pitched channel to."""
    events = percussion.groove(bars(4), 120.0, 1.0)
    for earlier, later in zip(events, events[1:]):
        assert earlier.t + earlier.dur <= later.t + EPSILON


def test_events_come_back_in_time_order():
    events = percussion.groove(bars(4), 120.0, 1.0)
    assert list(events) == sorted(events, key=lambda e: e.t)


def test_hats_survive_at_an_ordinary_tempo():
    """The chorale's eighths are 250 ms apart at its own tempo."""
    events = percussion.groove(bars(1), 120.0, 1.0)
    assert times(events, percussion.PITCH[percussion.HAT])


def test_the_floor_drops_the_hats_when_the_bars_get_short():
    """Four times the tempo puts the chorale's eighths 62 ms apart.

    The kicks survive: at 480 bpm a 4/4 bar is half a second, so the two of
    them are still 250 ms apart. The floor thins the subdivisions and leaves
    the skeleton of the bar standing, which is the whole point of it.
    """
    fast = bars(1, bpm=480.0)
    events = percussion.groove(fast, 480.0, 1.0)
    assert times(events, percussion.PITCH[percussion.HAT]) == []
    assert times(events, percussion.PITCH[percussion.KICK]) == [0.0, 0.25]


def test_the_floor_is_seconds_and_not_beats():
    """The same bar count at half tempo keeps hats the fast one loses.

    If MIN_HIT_SEC were expressed in beats, both would behave the same and the
    machine gun would come back at speed.
    """
    slow = percussion.groove(bars(1, bpm=120.0), 120.0, 1.0)
    fast = percussion.groove(bars(1, bpm=480.0), 480.0, 1.0)
    hat = percussion.PITCH[percussion.HAT]
    assert len(times(slow, hat)) > len(times(fast, hat))


def test_a_hit_is_never_longer_than_the_gap_after_it():
    events = percussion.groove(bars(2), 120.0, 1.0)
    for earlier, later in zip(events, events[1:]):
        assert earlier.dur <= later.t - earlier.t + EPSILON
    assert all(e.dur <= percussion.HIT_SEC + EPSILON for e in events)
    assert all(e.dur > 0.0 for e in events)


def test_priority_beats_the_order_the_candidates_arrive_in():
    """The kick wins because it is a kick, not because the table lists it first.

    `groove` alone cannot prove this. PATTERNS declares the 4/4 kick ahead of
    the hats, so a stable sort by time crowns the kick at a t=0 tie whether or
    not PRIORITY exists. Feeding the candidates hat-first makes the rule do
    the work itself.
    """
    hat = percussion.Hit(0.0, percussion.HAT, 7)
    kick = percussion.Hit(0.0, percussion.KICK, 15)
    events = percussion._resolve([(0.0, hat), (0.0, kick)], 1.0)
    assert [e.pitch for e in events] == [percussion.PITCH[percussion.KICK]]


def test_a_gap_shorter_than_a_hit_shortens_the_hit():
    """The tempo where the clip actually bites, which 120 bpm never reaches.

    At 120 bpm the surviving hits are 250 ms apart, twice HIT_SEC, so
    `min(HIT_SEC, gap)` is inert and a hit fixed at HIT_SEC would look
    correct. At 280 bpm the floor lets hits through 107 ms apart — above
    MIN_HIT_SEC, below HIT_SEC — and the clip is the only thing keeping the
    channel monophonic.
    """
    events = percussion.groove(bars(1, bpm=280.0), 280.0, 1.0)
    gaps = [later.t - earlier.t for earlier, later in zip(events, events[1:])]
    assert gaps and max(gaps) < percussion.HIT_SEC, "this tempo must exercise the clip"
    for earlier, later in zip(events, events[1:]):
        assert earlier.t + earlier.dur <= later.t + EPSILON


def on(level=0.8, **rest):
    return replace(
        DEFAULTS,
        percussion=replace(DEFAULTS.percussion, enabled=True, level=level),
        **rest,
    )


def test_percussion_off_changes_nothing():
    """The whole phase rests on this. If it fails, nothing else matters."""
    score = ingest(FIXTURES / "chorale.mxl")
    assert arrange(score) == arrange(score, DEFAULTS)
    assert all(c.role != "perc" for c in arrange(score).channels)


def test_percussion_on_appends_one_noise_channel():
    score = ingest(FIXTURES / "chorale.mxl")
    plain = arrange(score)
    drummed = arrange(score, on())
    assert len(drummed.channels) == len(plain.channels) + 1
    assert drummed.channels[:-1] == plain.channels, "the pitched channels are untouched"
    perc = drummed.channels[-1]
    assert perc.role == "perc"
    assert perc.instrument.wave == "noise"
    assert perc.echo is None
    assert perc.events


def test_percussion_is_not_a_voice_in_the_roster():
    """count narrows the pitched reduction and has no opinion about drums."""
    from bitty import voices

    assert voices.PERC not in voices.VOICES
    assert len(voices.VOICES) == 5
    score = ingest(FIXTURES / "chorale.mxl")
    narrow = on(voices=replace(DEFAULTS.voices, count=3))
    roles = [c.role for c in arrange(score, narrow).channels]
    assert roles[-1] == "perc"
    assert len(roles) == 4, "three pitched voices plus the drums"


def test_the_arrangement_round_trips_through_json():
    """A hand-edited file must render the drums back without re-deriving them."""
    from bitty.arrangement import Arrangement

    score = ingest(FIXTURES / "chorale.mxl")
    drummed = arrange(score, on())
    assert Arrangement.from_json(drummed.to_json()) == drummed


def test_the_arcade_preset_exists_and_turns_percussion_on():
    assert "arcade" in preset_names()
    config = load([], preset="arcade")
    assert config.percussion.enabled is True


def test_every_fixture_grooves():
    """The three fixtures are 4/4, 3/4, and 2/4 — one per pattern that has one."""
    for name in NAMES:
        score = ingest(FIXTURES / f"{name}.mxl")
        drummed = arrange(score, on())
        assert drummed.channels[-1].role == "perc"
        assert drummed.channels[-1].events, name


@pytest.mark.parametrize("name", NAMES)
def test_the_drums_run_the_length_of_the_piece(name):
    score = ingest(FIXTURES / f"{name}.mxl")
    perc = arrange(score, on()).channels[-1]
    last_bar = score.bars[-1]
    assert perc.events[0].t < 1e-6
    assert perc.events[-1].t < last_bar.start + last_bar.dur


# Which fixtures the floor can actually reach, and which it cannot. Hat
# spacing at each fixture's own tempo is 250 ms on the chorale, 300 ms on
# ragtime, and 500 ms on the minuet, against MIN_HIT_SEC = 100 ms. The
# chorale and ragtime cross between tempo_scale 2.0 and 4.0 — measured, they
# go 64 hits to 64 at 2.0 and to 32 at 4.0. The minuet cannot cross at all:
# 500 ms at the 4.0 ceiling the config validator enforces is still 125 ms, so
# a waltz keeps its whole groove at every tempo this pipeline can ask for.
# That is a property of the 3/4 pattern being sparse, not a bug, and it is
# split out here rather than papered over with a <= assertion.
THINS = ["chorale", "ragtime"]
NEVER_THINS = ["minuet"]


@pytest.mark.parametrize("name", THINS)
def test_four_times_tempo_thins_the_groove(name):
    """Phase 9 rewrites bar times before arrange runs, so the floor gets it free."""
    score = ingest(FIXTURES / f"{name}.mxl")
    plain = arrange(score, on()).channels[-1].events
    fast = arrange(apply(score, Transform(tempo_scale=4.0)), on()).channels[-1].events
    assert len(fast) < len(plain), name


@pytest.mark.parametrize("name", NEVER_THINS)
def test_a_sparse_pattern_survives_the_tempo_ceiling(name):
    """The other half of the floor's story, and the reason it is a floor.

    Density is the pattern meeting the tempo. The 3/4 pattern is sparse
    enough that the fastest score this pipeline can produce still clears
    MIN_HIT_SEC, so nothing is dropped. If this starts failing, either the
    waltz pattern gained subdivisions or MIN_HIT_SEC moved a long way up.
    """
    score = ingest(FIXTURES / f"{name}.mxl")
    plain = arrange(score, on()).channels[-1].events
    fast = arrange(apply(score, Transform(tempo_scale=4.0)), on()).channels[-1].events
    assert len(fast) == len(plain), name
    gaps = [b.t - a.t for a, b in zip(fast, fast[1:])]
    assert min(gaps) >= percussion.MIN_HIT_SEC


@pytest.mark.parametrize("name", NAMES)
def test_the_drums_do_not_move_the_loop(name):
    """An observation, not a requirement. If it fails, that is a README finding."""
    score = ingest(FIXTURES / f"{name}.mxl")
    sections = analyze(score)
    picks = []
    for config in (DEFAULTS, on()):
        arrangement = arrange(score, config)
        audio = synth.render(arrangement)
        chosen = loop_stage.choose(
            loop_stage.candidates(score, sections, min_bars=config.loop.min_bars),
            audio,
            arrangement,
            DEFAULTS.output.sample_rate,
        )
        picks.append(
            None
            if chosen is None
            else (chosen.candidate.first_bar, chosen.candidate.last_bar)
        )
    assert picks[0] == picks[1], f"{name}: drums changed the loop to {picks[1]}"
