from dataclasses import replace

from bitty.voices import MIN_VOICES, ROSTER, VOICES, Roster


def test_the_roster_is_the_spec_s_five_voices_in_score_order():
    assert [v.role for v in ROSTER] == ["lead", "counter", "inner_a", "inner_b", "bass"]


def test_waves_and_duties_match_the_spec_table():
    by_role = {v.role: v.instrument for v in ROSTER}
    assert by_role["lead"].wave == "pulse" and by_role["lead"].duty == 0.5
    assert by_role["counter"].wave == "pulse" and by_role["counter"].duty == 0.25
    assert by_role["inner_a"].wave == "pulse" and by_role["inner_a"].duty == 0.25
    assert by_role["inner_b"].wave == "pulse" and by_role["inner_b"].duty == 0.125
    assert by_role["bass"].wave == "triangle"


def test_every_voice_has_a_volume_envelope():
    """A chip voice with no envelope is a buzzer; Phase 2 exists to avoid that."""
    assert all(v.instrument.volume_env for v in ROSTER)


def test_the_voices_occupy_distinct_places_in_the_image():
    pans = [v.pan for v in ROSTER]
    assert len(set(pans)) == len(pans)
    assert all(-1.0 <= p <= 1.0 for p in pans)


def test_the_filter_ships_off():
    """Warmth is a lever, not the default. See the Phase 2 warmth listen."""
    assert all(v.instrument.cutoff_hz is None for v in ROSTER)


def test_the_default_roster_plays_all_five_voices():
    assert [v.role for v in ROSTER] == ["lead", "counter", "inner_a", "inner_b", "bass"]
    assert ROSTER.count == len(VOICES) == 5


def test_the_pins_survive_every_legal_count():
    """Lead and bass are structural, not preferences: without both there
    is no reduction, only a pile."""
    for count in range(MIN_VOICES, len(VOICES) + 1):
        roster = replace(ROSTER, count=count)
        roles = [v.role for v in roster]
        assert roles[0] == roster.lead == "lead"
        assert roles[-1] == roster.bass == "bass"
        assert len(roles) == count


def test_middles_fall_from_the_narrowest_end():
    assert replace(ROSTER, count=5).middles == ("counter", "inner_a", "inner_b")
    assert replace(ROSTER, count=4).middles == ("counter", "inner_a")
    assert replace(ROSTER, count=3).middles == ("counter",)


def test_the_arp_carrier_is_the_narrowest_surviving_middle():
    assert replace(ROSTER, count=5).arp == "inner_b"
    assert replace(ROSTER, count=4).arp == "inner_a"
    assert replace(ROSTER, count=3).arp == "counter"


def test_the_arp_carrier_is_always_a_voice_that_plays():
    """The invariant the floor of 3 exists to protect."""
    for count in range(MIN_VOICES, len(VOICES) + 1):
        roster = replace(ROSTER, count=count)
        assert roster.arp in {v.role for v in roster}
        assert roster.middles, "an empty middles has no one to carry the overflow"


def test_truncation_is_a_view_not_a_deletion():
    """Dropped voices stay addressable so any layer can override them."""
    roster = replace(ROSTER, count=3)
    assert [v.role for v in roster.voices] == [v.role for v in VOICES]
    assert "inner_b" not in {v.role for v in roster}
