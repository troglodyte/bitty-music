from bitty.arrangement import Arrangement, Channel, Event, Instrument


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
