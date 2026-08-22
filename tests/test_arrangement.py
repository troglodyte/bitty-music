import json
from pathlib import Path

from bitty.arrangement import ARP_RATE_SEC, Arrangement, Channel, Echo, Event, Instrument, Loop


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


def test_vibrato_round_trips_through_json():
    original = Arrangement(
        meta={"title": "t", "bpm": 120.0},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(wave="pulse"),
                events=(
                    Event(t=0.0, pitch=60, dur=1.0, vel=10, vibrato=True),
                    Event(t=1.0, pitch=62, dur=0.1, vel=10),
                ),
            ),
        ),
    )
    restored = Arrangement.from_json(original.to_json())
    assert [e.vibrato for e in restored.channels[0].events] == [True, False]


def test_a_loop_round_trips_through_json():
    original = Arrangement(meta={"title": "t", "bpm": 120}, channels=(),
                           loop=Loop(start_sec=1.5, end_sec=12.0))
    restored = Arrangement.from_json(original.to_json())
    assert restored.loop == Loop(start_sec=1.5, end_sec=12.0)


def test_an_arrangement_without_a_loop_serializes_it_as_null():
    text = Arrangement(meta={}, channels=()).to_json()
    assert '"loop": null' in text
    assert Arrangement.from_json(text).loop is None


def test_a_loop_field_this_build_does_not_know_is_dropped():
    """The same forgiving-load contract Instrument and Event already keep."""
    text = '{"meta": {}, "channels": [], "loop": {"start_sec": 0.0, "end_sec": 4.0, "curve": "s"}}'
    assert Arrangement.from_json(text).loop == Loop(start_sec=0.0, end_sec=4.0)


def test_meta_records_the_printed_bar_range():
    from bitty.arrange import arrange
    from bitty.ingest import ingest
    arrangement = arrange(ingest(Path(__file__).parent / "fixtures" / "minuet.mxl"))
    assert arrangement.meta["bars"] == [1, 16]


def test_an_event_field_this_build_does_not_know_is_dropped_not_fatal():
    """A newer bitty's arrangement should render with the fields we understand.

    Instrument already promises this; Event did not, so an added field turned
    every older build into a hard failure on load.
    """
    text = json.dumps(
        {
            "meta": {"title": "t", "bpm": 120.0},
            "channels": [
                {
                    "role": "lead",
                    "instrument": {"wave": "pulse"},
                    "events": [
                        {"t": 0.0, "pitch": 60, "dur": 1.0, "vel": 10, "tremolo": 0.5}
                    ],
                }
            ],
        }
    )
    restored = Arrangement.from_json(text)
    assert restored.channels[0].events[0].pitch == 60


def test_an_event_carries_no_arpeggio_by_default():
    assert Event(t=0.0, pitch=60, dur=1.0, vel=15).arp == ()


def test_an_arpeggio_survives_the_json_round_trip_as_a_tuple():
    """A list would break Event's hashing and equality; it is frozen."""
    event = Event(t=0.0, pitch=60, dur=1.0, vel=15, arp=(0, 4, 7))
    channel = Channel(role="lead", instrument=Instrument(wave="pulse"), events=(event,))
    restored = Arrangement.from_json(
        Arrangement(meta={"title": "t", "bpm": 120.0}, channels=(channel,)).to_json()
    )
    loaded = restored.channels[0].events[0]
    assert loaded.arp == (0, 4, 7)
    assert isinstance(loaded.arp, tuple)


def test_an_unknown_event_field_is_still_dropped():
    """The contract that keeps a newer bitty's file loadable in an older one."""
    raw = '''{"meta": {"title": "t", "bpm": 120.0}, "channels": [{"role": "lead",
      "instrument": {"wave": "pulse"},
      "events": [{"t": 0.0, "pitch": 60, "dur": 1.0, "vel": 15,
                  "arp": [0, 7], "glissando": 3}]}]}'''
    event = Arrangement.from_json(raw).channels[0].events[0]
    assert event.arp == (0, 7)


def test_an_instrument_carries_the_default_arp_rate():
    """The rate travels in the arrangement for the reason vibrato's does:
    a hand-edited file must render the same with no config anywhere."""
    assert Instrument(wave="pulse").arp_rate_sec == ARP_RATE_SEC
    assert ARP_RATE_SEC == 0.016
