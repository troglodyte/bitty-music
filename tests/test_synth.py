import numpy as np

from bitty.arrangement import Arrangement, Channel, Event, Instrument
from bitty.synth import SAMPLE_RATE, render


def one_note(pitch=69, dur=1.0, wave="pulse", vel=15) -> Arrangement:
    return Arrangement(
        meta={"title": "test", "bpm": 120.0},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(wave=wave, duty=0.5),
                events=(Event(t=0.0, pitch=pitch, dur=dur, vel=vel),),
            ),
        ),
    )


def dominant_frequency(audio: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1 / SAMPLE_RATE)
    return float(freqs[int(np.argmax(spectrum))])


def test_pulse_note_sounds_at_its_written_pitch():
    audio = render(one_note(pitch=69))
    assert abs(dominant_frequency(audio) - 440.0) < 2.0


def test_triangle_note_sounds_at_its_written_pitch():
    audio = render(one_note(pitch=69, wave="triangle"))
    assert abs(dominant_frequency(audio) - 440.0) < 2.0


def test_render_length_matches_the_arrangement_duration():
    audio = render(one_note(dur=1.0))
    assert len(audio) == SAMPLE_RATE


def test_output_never_clips():
    arrangement = Arrangement(
        meta={"title": "test", "bpm": 120.0},
        channels=tuple(
            Channel(
                role=f"v{i}",
                instrument=Instrument(wave="pulse", duty=0.5),
                events=(Event(t=0.0, pitch=60 + i, dur=1.0, vel=15),),
            )
            for i in range(4)
        ),
    )
    audio = render(arrangement)
    assert np.max(np.abs(audio)) <= 1.0


def test_silent_velocity_produces_silence():
    audio = render(one_note(vel=0))
    assert np.max(np.abs(audio)) == 0.0


def test_render_is_deterministic():
    assert np.array_equal(render(one_note()), render(one_note()))


def test_output_is_float32():
    assert render(one_note()).dtype == np.float32
