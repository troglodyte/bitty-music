import json

from bitty.arrangement import Arrangement, Channel, Echo, Event, Instrument


def sample_arrangement() -> Arrangement:
    return Arrangement(
        meta={"title": "Test", "bpm": 120.0},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(wave="pulse", duty=0.5),
                events=(
                    Event(t=0.0, pitch=72, dur=0.5, vel=15),
                    Event(t=0.5, pitch=74, dur=0.5, vel=12),
                ),
            ),
            Channel(
                role="bass",
                instrument=Instrument(wave="triangle", duty=0.5),
                events=(Event(t=0.0, pitch=48, dur=2.0, vel=15),),
            ),
        ),
    )


def test_arrangement_survives_a_json_round_trip():
    original = sample_arrangement()
    restored = Arrangement.from_json(original.to_json())
    assert restored == original


def test_arrangement_json_is_human_editable():
    text = sample_arrangement().to_json()
    assert '"role": "lead"' in text
    assert text.count("\n") > 5, "should be indented, not one dense line"


def test_instrument_defaults_are_phase_one_compatible():
    instrument = Instrument(wave="pulse")
    assert instrument.duty == 0.5
    assert instrument.volume_env == ()
    assert instrument.pitch_env == ()
    assert instrument.cutoff_hz is None
    assert instrument.quantize is None


def test_channel_defaults_to_centre_with_no_echo():
    channel = Channel(role="lead", instrument=Instrument(wave="pulse"), events=())
    assert channel.pan == 0.0
    assert channel.echo is None


def test_new_fields_survive_the_json_round_trip():
    original = Arrangement(
        meta={"title": "t", "bpm": 120.0},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(
                    wave="pulse",
                    duty=0.25,
                    volume_env=(15, 13, 11),
                    pitch_env=(2, 1, 0),
                    cutoff_hz=2400.0,
                    resonance=1.5,
                    quantize=16,
                ),
                events=(Event(t=0.0, pitch=60, dur=1.0, vel=15),),
                pan=-0.3,
                echo=Echo(delay_sec=0.375, level=0.4),
            ),
        ),
    )
    reloaded = Arrangement.from_json(original.to_json())
    assert reloaded == original


def test_envelopes_reload_as_tuples_not_lists():
    channel = Channel(
        role="lead",
        instrument=Instrument(wave="pulse", volume_env=(15, 12)),
        events=(),
    )
    arrangement = Arrangement(meta={}, channels=(channel,))
    reloaded = Arrangement.from_json(arrangement.to_json())
    assert reloaded.channels[0].instrument.volume_env == (15, 12)


def test_unknown_instrument_fields_are_ignored():
    """A newer bitty writes a field this build has never heard of."""
    text = json.dumps(
        {
            "meta": {},
            "channels": [
                {
                    "role": "lead",
                    "instrument": {"wave": "pulse", "duty": 0.5, "wobble": 7},
                    "events": [],
                }
            ],
        }
    )
    arrangement = Arrangement.from_json(text)
    assert arrangement.channels[0].instrument.wave == "pulse"
