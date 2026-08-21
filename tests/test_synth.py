import numpy as np

from bitty.arrangement import Arrangement, Channel, Echo, Event, Instrument
from bitty.synth import SAMPLE_RATE, render


def one_note(
    pitch=69, dur=1.0, wave="pulse", vel=15, vibrato=False, **instrument_kwargs
) -> Arrangement:
    return Arrangement(
        meta={"title": "test", "bpm": 120.0},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(wave=wave, **instrument_kwargs),
                events=(Event(t=0.0, pitch=pitch, dur=dur, vel=vel, vibrato=vibrato),),
            ),
        ),
    )


def mono(audio: np.ndarray) -> np.ndarray:
    return audio.sum(axis=1)


def dominant_frequency(audio: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(mono(audio)))
    freqs = np.fft.rfftfreq(len(audio), 1 / SAMPLE_RATE)
    return float(freqs[int(np.argmax(spectrum))])


def test_output_is_stereo_float32():
    audio = render(one_note())
    assert audio.ndim == 2
    assert audio.shape[1] == 2
    assert audio.dtype == np.float32


def test_a_note_sounds_at_its_written_pitch():
    assert abs(dominant_frequency(render(one_note(pitch=69))) - 440.0) < 2.0


def test_render_length_matches_the_arrangement_duration():
    audio = render(one_note(dur=1.0))
    assert abs(len(audio) - SAMPLE_RATE) < SAMPLE_RATE * 0.05


def test_a_volume_envelope_shapes_the_note():
    """A decaying envelope must actually decay — this is what kills the MIDI-dump sound."""
    audio = mono(render(one_note(dur=1.0, volume_env=(15, 12, 9, 6, 3, 0))))
    head = np.sqrt(np.mean(audio[: SAMPLE_RATE // 20] ** 2))
    tail = np.sqrt(np.mean(audio[-SAMPLE_RATE // 20 :] ** 2))
    assert tail < head / 10.0


def test_a_pitch_envelope_bends_the_attack():
    """The percussive 'pew' of a chip lead: start sharp, settle to pitch.

    Do not compare the tails sample-by-sample. A pitch envelope permanently
    shifts accumulated phase, so a bent note and a plain one stay out of phase
    forever even once they agree on frequency. Compare spectra instead.
    """
    plain = mono(render(one_note(pitch=69, dur=0.5)))
    blipped = mono(render(one_note(pitch=69, dur=0.5, pitch_env=(12, 7, 3, 0))))
    assert not np.allclose(plain[:2000], blipped[:2000])

    def peak(audio):
        spectrum = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1 / SAMPLE_RATE)
        return float(freqs[int(np.argmax(spectrum))])

    # The envelope's last step is 0 semitones, so the note settles on pitch.
    assert abs(peak(blipped[SAMPLE_RATE // 4 :]) - 440.0) < 5.0


def test_the_filter_removes_high_harmonics():
    bright = mono(render(one_note(pitch=60, dur=1.0)))
    warm = mono(render(one_note(pitch=60, dur=1.0, cutoff_hz=800.0)))

    def high_energy(audio):
        spectrum = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1 / SAMPLE_RATE)
        return float(np.sum(spectrum[freqs > 3000.0] ** 2))

    assert high_energy(warm) < high_energy(bright) / 10.0


def test_the_filter_is_off_by_default():
    """Default output stays on the spec's chiptune target, not a warmer one."""
    assert np.array_equal(render(one_note()), render(one_note(cutoff_hz=None)))


def test_pan_moves_the_voice_across_the_image():
    left = Arrangement(
        meta={},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(wave="pulse"),
                events=(Event(t=0.0, pitch=69, dur=1.0, vel=15),),
                pan=-1.0,
            ),
        ),
    )
    audio = render(left)
    assert np.max(np.abs(audio[:, 0])) > np.max(np.abs(audio[:, 1])) * 5


def test_echo_adds_a_delayed_copy_after_the_note_ends():
    note = (Event(t=0.0, pitch=69, dur=0.25, vel=15),)
    dry = Arrangement(
        meta={},
        channels=(Channel(role="lead", instrument=Instrument(wave="pulse"), events=note),),
    )
    wet = Arrangement(
        meta={},
        channels=(
            Channel(
                role="lead",
                instrument=Instrument(wave="pulse"),
                events=note,
                echo=Echo(delay_sec=0.5, level=0.5),
            ),
        ),
    )
    dry_audio, wet_audio = render(dry), render(wet)

    # The tail lengthens the render by exactly the delay. Do not index the dry
    # render past its end — it is genuinely shorter, and numpy returns an empty
    # slice rather than silence.
    assert abs(len(wet_audio) - len(dry_audio) - 0.5 * SAMPLE_RATE) < 2
    after = slice(int(0.5 * SAMPLE_RATE), int(0.7 * SAMPLE_RATE))
    assert np.max(np.abs(mono(wet_audio)[after])) > 0.05


def test_output_never_clips_even_with_five_voices_at_full_velocity():
    arrangement = Arrangement(
        meta={},
        channels=tuple(
            Channel(
                role=f"v{i}",
                instrument=Instrument(wave="pulse", duty=0.5),
                events=(Event(t=0.0, pitch=60 + i, dur=1.0, vel=15),),
                pan=0.0,
            )
            for i in range(5)
        ),
    )
    assert np.max(np.abs(render(arrangement))) <= 1.0


def test_silent_velocity_produces_silence():
    assert np.max(np.abs(render(one_note(vel=0)))) == 0.0


def test_render_is_deterministic():
    assert np.array_equal(render(one_note()), render(one_note()))


def test_noise_render_is_deterministic_too():
    assert np.array_equal(render(one_note(wave="noise")), render(one_note(wave="noise")))


def test_an_empty_arrangement_renders_silence_not_a_crash():
    audio = render(Arrangement(meta={}, channels=()))
    assert audio.shape[1] == 2
    assert np.max(np.abs(audio), initial=0.0) == 0.0


def test_a_vibrato_event_wavers_and_a_plain_one_does_not():
    """Vibrato is a pitch effect, so measure it as pitch: zero-crossing spacing.

    A steady tone crosses zero at even intervals; a wavering one does not. The
    tail is measured because the first 300 ms are silent by design.
    """

    def crossing_spread(vibrato):
        audio = mono(render(one_note(dur=2.0, vibrato=vibrato)))
        tail = audio[int(0.8 * SAMPLE_RATE) :]
        rising = np.flatnonzero(np.diff(np.signbit(tail)))
        # Interpolate to sub-sample resolution and measure whole periods. A
        # crossing rounded to the nearest sample wobbles by half a sample on
        # its own, which is the same order as a 25-cent vibrato; and a pulse
        # wave's two half-periods differ by duty cycle, not by pitch.
        fraction = tail[rising] / (tail[rising] - tail[rising + 1])
        return np.std(np.diff((rising + fraction)[::2]))

    assert crossing_spread(vibrato=True) > crossing_spread(vibrato=False) * 3


def test_vibrato_changes_only_the_notes_that_ask_for_it():
    assert not np.array_equal(
        render(one_note(dur=2.0, vibrato=True)),
        render(one_note(dur=2.0, vibrato=False)),
    )
