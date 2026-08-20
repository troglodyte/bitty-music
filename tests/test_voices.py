from bitty.voices import ARP_ROLE, BASS_ROLE, LEAD_ROLE, MIDDLE_ROLES, ROSTER


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


def test_the_role_constants_point_into_the_roster():
    roles = {v.role for v in ROSTER}
    assert {LEAD_ROLE, BASS_ROLE, ARP_ROLE} <= roles
    assert set(MIDDLE_ROLES) <= roles
    assert LEAD_ROLE not in MIDDLE_ROLES and BASS_ROLE not in MIDDLE_ROLES
    assert ARP_ROLE in MIDDLE_ROLES
