"""The groove: a pattern per meter, placed on the score's own barlines."""

import pytest

from bitty import percussion
from bitty.model import Bar

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
