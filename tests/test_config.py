from pathlib import Path

from bitty import arrangement, lfo, synth, voices
from bitty.arrange import ARP_STEP_SEC
from bitty.config import DEFAULTS
from bitty.loop import MIN_LOOP_BARS, SEAM_RATIO


def test_defaults_match_the_constants_they_replace():
    """The guard that lets every other test in the suite stay untouched.

    Most of these module constants (`arrange.ARP_STEP_SEC`, `loop.MIN_LOOP_BARS`,
    `loop.SEAM_RATIO`) are now derived from `DEFAULTS`, so the assertions
    against them are tautologies that can never fail — they document the
    relationship rather than guard it. `output.sample_rate` is the one real
    cross-check left: `synth.SAMPLE_RATE` is an independent literal, and this
    assertion is the seam that keeps that pair honest.
    """
    assert DEFAULTS.echo.delay_beats == voices.ECHO_BEATS
    assert DEFAULTS.echo.level == voices.ECHO_LEVEL
    assert DEFAULTS.vibrato.depth_cents == arrangement.VIBRATO_CENTS
    assert DEFAULTS.vibrato.delay_sec == arrangement.VIBRATO_DELAY
    assert DEFAULTS.vibrato.rate_hz == arrangement.VIBRATO_RATE_HZ
    assert DEFAULTS.vibrato.min_note_sec == lfo.MIN_NOTE_SEC
    assert DEFAULTS.arp.step_sec == ARP_STEP_SEC
    assert DEFAULTS.loop.min_bars == MIN_LOOP_BARS
    assert DEFAULTS.loop.seam_ratio == SEAM_RATIO
    assert DEFAULTS.output.sample_rate == synth.SAMPLE_RATE
    assert DEFAULTS.voices == voices.ROSTER


def test_the_defaults_describe_the_shipped_behaviour():
    assert DEFAULTS.echo.on is True
    assert DEFAULTS.output.target == "bevy"
    assert DEFAULTS.output.format == "ogg"
    assert DEFAULTS.output.dir == Path("out")


import pytest

from bitty.config import ConfigError, merge
from dataclasses import replace


def test_the_roster_survives_a_merge_as_a_roster():
    """A merged config still answers .arp, or the arranger loses its carrier."""
    result = merge(DEFAULTS, '[voices.lead]\nduty = 0.25\n', "test")
    assert isinstance(result.voices, voices.Roster)
    assert result.voices.arp == "inner_b"


def test_a_vibrato_spread_reaches_voices_that_are_not_playing():
    """A dropped voice must still be spread: if a later layer raises the
    count it would otherwise come back without the vibrato."""
    result = merge(
        replace(DEFAULTS, voices=replace(DEFAULTS.voices, count=3)),
        "[vibrato]\ndepth_cents = 40.0\n",
        "test",
    )
    by_role = {v.role: v for v in result.voices.voices}
    assert by_role["inner_b"].instrument.vibrato_cents == 40.0


def test_a_value_from_a_file_beats_the_default():
    result = merge(DEFAULTS, "[echo]\nlevel = 0.9\n", "bitty.toml")
    assert result.echo.level == 0.9
    assert result.echo.delay_beats == DEFAULTS.echo.delay_beats, "untouched keys survive"


def test_milliseconds_become_seconds():
    text = "[vibrato]\ndelay_ms = 300\nmin_note_ms = 750\n\n[arp]\nrate_ms = 20\n"
    result = merge(DEFAULTS, text, "bitty.toml")
    assert result.vibrato.delay_sec == 0.3
    assert result.vibrato.min_note_sec == 0.75
    assert result.arp.step_sec == 0.02


def test_an_unknown_key_names_the_file_the_key_and_the_alternatives():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[echo]\nlevl = 0.5\n", "bitty.toml")
    message = str(caught.value)
    assert "bitty.toml" in message
    assert "echo.levl" in message
    assert "level" in message, "a typo should be told what it nearly was"


def test_an_unknown_table_is_refused():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[reverb]\non = true\n", "bitty.toml")
    assert "reverb" in str(caught.value)


def test_a_value_over_its_range_is_refused():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[echo]\nlevel = 3.0\n", "bitty.toml")
    assert "echo.level" in str(caught.value)
    assert "at most 1.0" in str(caught.value)


def test_a_value_of_the_wrong_type_is_refused():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, '[echo]\nlevel = "loud"\n', "bitty.toml")
    assert "expected a number" in str(caught.value)


def test_true_is_not_a_number():
    """bool is an int in Python; a config file should not get away with it."""
    with pytest.raises(ConfigError):
        merge(DEFAULTS, "[echo]\nlevel = true\n", "bitty.toml")


def test_a_whole_number_field_refuses_a_fraction():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[loop]\nmin_bars = 8.5\n", "bitty.toml")
    assert "whole number" in str(caught.value)


def test_broken_toml_names_the_file():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[echo\nlevel = 0.5\n", "bitty.toml")
    assert "bitty.toml" in str(caught.value)
    assert "not valid TOML" in str(caught.value)


def test_the_format_key_accepts_only_the_two_it_can_write():
    assert merge(DEFAULTS, '[output]\nformat = "wav"\n', "x").output.format == "wav"
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, '[output]\nformat = "flac"\n', "x")
    assert "ogg, wav" in str(caught.value)


def test_the_out_dir_becomes_a_path():
    assert merge(DEFAULTS, '[output]\ndir = "build/audio"\n', "x").output.dir == Path("build/audio")


def roles(config):
    return {voice.role: voice for voice in config.voices}


def test_a_voice_override_reshapes_only_that_voice():
    result = merge(DEFAULTS, '[voices.lead]\nduty = 0.125\npan = 0.0\n', "bitty.toml")
    assert roles(result)["lead"].instrument.duty == 0.125
    assert roles(result)["lead"].pan == 0.0
    assert roles(result)["counter"] == roles(DEFAULTS)["counter"]


def test_the_roster_keeps_its_order_and_its_size():
    result = merge(DEFAULTS, "[voices.bass]\nquantize = 8\n", "bitty.toml")
    assert [v.role for v in result.voices] == [v.role for v in DEFAULTS.voices]


def test_an_unknown_voice_is_refused_and_lists_the_roster():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[voices.strings]\npan = 0.0\n", "bitty.toml")
    assert "voices.strings" in str(caught.value)
    assert "lead" in str(caught.value) and "bass" in str(caught.value)


def test_an_unknown_voice_key_is_refused():
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[voices.lead]\nreverb = 0.5\n", "bitty.toml")
    assert "voices.lead.reverb" in str(caught.value)


def test_an_envelope_must_be_levels_in_range():
    result = merge(DEFAULTS, "[voices.lead]\nvolume_env = [15, 12, 9]\n", "x")
    assert roles(result)["lead"].instrument.volume_env == (15, 12, 9)
    with pytest.raises(ConfigError) as caught:
        merge(DEFAULTS, "[voices.lead]\nvolume_env = [15, 99]\n", "x")
    assert "volume_env[1]" in str(caught.value)


def test_the_global_vibrato_table_spreads_onto_every_voice():
    result = merge(DEFAULTS, "[vibrato]\ndepth_cents = 40.0\n", "bitty.toml")
    for voice in result.voices:
        assert voice.instrument.vibrato_cents == 40.0
    assert result.vibrato.depth_cents == 40.0, "the write-only staging copy moves too"


def test_a_per_voice_vibrato_beats_the_global_one_in_the_same_file():
    text = "[vibrato]\ndepth_cents = 40.0\n\n[voices.lead]\nvibrato_cents = 10.0\n"
    result = merge(DEFAULTS, text, "bitty.toml")
    assert roles(result)["lead"].instrument.vibrato_cents == 10.0
    assert roles(result)["bass"].instrument.vibrato_cents == 40.0


def test_a_file_with_no_vibrato_table_leaves_per_voice_overrides_alone():
    """Spreading only the keys a file names is what keeps layering honest."""
    first = merge(DEFAULTS, "[voices.lead]\nvibrato_cents = 10.0\n", "a.toml")
    second = merge(first, "[echo]\nlevel = 0.5\n", "b.toml")
    assert roles(second)["lead"].instrument.vibrato_cents == 10.0


def test_an_unrelated_vibrato_key_does_not_reset_a_per_voice_override():
    """The spread pushes exactly the keys a file names, not all three.

    A coarser implementation that spread the whole table whenever [vibrato]
    appeared would silently reset the lead back to the default depth here.
    """
    first = merge(DEFAULTS, "[voices.lead]\nvibrato_cents = 10.0\n", "a.toml")
    second = merge(first, "[vibrato]\nrate_hz = 6.0\n", "b.toml")
    assert roles(second)["lead"].instrument.vibrato_cents == 10.0
    assert roles(second)["lead"].instrument.vibrato_rate_hz == 6.0


def test_per_voice_vibrato_delay_is_milliseconds_like_every_other_delay():
    result = merge(DEFAULTS, "[voices.lead]\nvibrato_delay_ms = 500\n", "x")
    assert roles(result)["lead"].instrument.vibrato_delay == 0.5


from bitty.config import load, preset_names


def test_a_later_file_beats_an_earlier_one(tmp_path):
    first = tmp_path / "a.toml"
    second = tmp_path / "b.toml"
    first.write_text("[echo]\nlevel = 0.1\ndelay_beats = 0.5\n")
    second.write_text("[echo]\nlevel = 0.9\n")
    result = load([first, second])
    assert result.echo.level == 0.9, "the later file wins the key it sets"
    assert result.echo.delay_beats == 0.5, "and leaves the rest of the earlier one"


def test_a_file_beats_the_preset_it_started_from(tmp_path):
    override = tmp_path / "bitty.toml"
    override.write_text("[echo]\non = true\n")
    assert load([override], preset="nes-tight").echo.on is True


def test_both_presets_ship_and_load():
    assert set(preset_names()) == {"lush", "nes-tight"}
    for name in preset_names():
        load([], preset=name)


def test_nes_tight_turns_the_echo_off_and_centres_the_image():
    result = load([], preset="nes-tight")
    assert result.echo.on is False
    assert all(voice.pan == 0.0 for voice in result.voices), "mono hardware, mono image"
    assert result.vibrato.depth_cents == 12.0, "shallower than the default 25.0"
    assert result.vibrato.delay_sec == 0.42, "later than the default 0.3"
    for voice in result.voices:
        assert voice.instrument.vibrato_cents == 12.0
        assert voice.instrument.vibrato_delay == 0.42


def test_lush_widens_the_image_and_deepens_the_vibrato():
    result = load([], preset="lush")
    assert result.echo.on is True
    assert max(abs(voice.pan) for voice in result.voices) > 0.5
    assert result.vibrato.depth_cents > DEFAULTS.vibrato.depth_cents


def test_the_two_presets_actually_differ():
    assert load([], preset="lush") != load([], preset="nes-tight")


def test_an_unknown_preset_lists_the_ones_that_exist():
    with pytest.raises(ConfigError) as caught:
        load([], preset="chunky")
    assert "chunky" in str(caught.value)
    assert "nes-tight" in str(caught.value)


def test_loading_nothing_is_the_defaults():
    assert load([]) == DEFAULTS


from bitty.config import discover, resolve


def test_nothing_found_is_not_an_error(tmp_path):
    assert discover(tmp_path, "minuet") == []


def test_the_project_file_is_found_in_the_score_s_own_directory(tmp_path):
    (tmp_path / "bitty.toml").write_text("[echo]\nlevel = 0.5\n")
    assert discover(tmp_path, "minuet") == [tmp_path / "bitty.toml"]


def test_the_project_file_is_found_by_walking_upward(tmp_path):
    scores = tmp_path / "assets" / "scores"
    scores.mkdir(parents=True)
    (tmp_path / "bitty.toml").write_text("[echo]\nlevel = 0.5\n")
    assert discover(scores, "minuet") == [tmp_path / "bitty.toml"]


def test_the_nearest_project_file_wins_outright(tmp_path):
    """First hit, not merged across levels: a config either applies whole or not."""
    scores = tmp_path / "scores"
    scores.mkdir()
    (tmp_path / "bitty.toml").write_text("[echo]\nlevel = 0.1\n")
    (scores / "bitty.toml").write_text("[echo]\nlevel = 0.9\n")
    assert discover(scores, "minuet") == [scores / "bitty.toml"]


def test_the_per_piece_file_sits_above_the_project_file(tmp_path):
    (tmp_path / "bitty.toml").write_text("[echo]\nlevel = 0.1\n")
    (tmp_path / "minuet.bitty.toml").write_text("[echo]\nlevel = 0.9\n")
    assert discover(tmp_path, "minuet") == [
        tmp_path / "bitty.toml",
        tmp_path / "minuet.bitty.toml",
    ]
    assert resolve(tmp_path, "minuet").echo.level == 0.9


def test_a_per_piece_file_belongs_to_its_own_piece_only(tmp_path):
    (tmp_path / "minuet.bitty.toml").write_text("[echo]\nlevel = 0.9\n")
    assert discover(tmp_path, "ragtime") == []


def test_an_explicit_config_beats_everything_discovered(tmp_path):
    """Explicit is appended to the discovered layers, not substituted for them.

    Each layer sets a field the others leave alone, so an implementation that
    replaced the discovered paths would lose the first two. All three also set
    echo.level, so the contested key proves the explicit file goes last.
    """
    (tmp_path / "bitty.toml").write_text("[echo]\nlevel = 0.1\n\n[loop]\nmin_bars = 3\n")
    (tmp_path / "minuet.bitty.toml").write_text("[echo]\nlevel = 0.2\n\n[arp]\nrate_ms = 20\n")
    explicit = tmp_path / "elsewhere.toml"
    explicit.write_text("[echo]\nlevel = 0.9\n")

    result = resolve(tmp_path, "minuet", explicit=explicit)
    assert result.echo.level == 0.9, "the explicit file wins the contested key"
    assert result.loop.min_bars == 3, "the project file still applied"
    assert result.arp.step_sec == 0.02, "the per-piece file still applied"


def test_a_discovered_file_beats_the_preset(tmp_path):
    (tmp_path / "bitty.toml").write_text("[echo]\non = true\n")
    assert resolve(tmp_path, "minuet", preset="nes-tight").echo.on is True


def test_resolve_with_nothing_around_is_the_defaults(tmp_path):
    assert resolve(tmp_path, "minuet") == DEFAULTS
