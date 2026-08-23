import pytest
import numpy as np
from dataclasses import replace
from pathlib import Path

from bitty.arrangement import Arrangement, Channel, Echo, Event, Instrument, Loop
from bitty.synth import SAMPLE_RATE, render, Render
from bitty.ingest import ingest
from bitty.arrange import arrange
from bitty.config import DEFAULTS


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


def test_render_of_converts_loop_seconds_to_samples():
    arrangement = Arrangement(
        meta={"title": "t", "bpm": 120.0},
        channels=(),
        loop=Loop(start_sec=1.0, end_sec=2.0),
    )
    audio = np.zeros((44100 * 3, 2), dtype=np.float32)

    result = Render.of(arrangement, audio)

    assert result.loop_start_sample == 44100
    assert result.loop_end_sample == 88200
    assert result.sample_rate == 44100


def test_render_of_clamps_the_loop_end_to_the_buffer():
    """A loop end past the rendered tail is the echo being cut, not a bug."""
    arrangement = Arrangement(
        meta={}, channels=(), loop=Loop(start_sec=0.0, end_sec=99.0)
    )
    audio = np.zeros((44100, 2), dtype=np.float32)

    result = Render.of(arrangement, audio)

    assert result.loop_end_sample == 44100


def test_render_of_carries_no_loop_through_as_none():
    arrangement = Arrangement(meta={}, channels=(), loop=None)

    result = Render.of(arrangement, np.zeros((10, 2), dtype=np.float32))

    assert result.loop_start_sample is None
    assert result.loop_end_sample is None


def test_render_of_copies_meta_rather_than_aliasing_it():
    meta = {"title": "t"}
    result = Render.of(Arrangement(meta=meta, channels=()), np.zeros((10, 2)))

    result.meta["title"] = "changed"

    assert meta["title"] == "t"


def test_a_half_specified_loop_is_rejected_at_construction():
    """One set and one None is a bug. Catch it here, not in an emitter."""
    audio = np.zeros((10, 2), dtype=np.float32)

    with pytest.raises(ValueError):
        Render(audio=audio, sample_rate=44100, meta={}, loop_start_sample=0)

    with pytest.raises(ValueError):
        Render(audio=audio, sample_rate=44100, meta={}, loop_end_sample=10)


def test_instrument_vibrato_depth_reaches_the_rendered_audio():
    """The shape travels in the arrangement, so two depths must not render alike."""

    def rendered(cents):
        instrument = Instrument(wave="pulse", vibrato_cents=cents)
        event = Event(t=0.0, pitch=69, dur=1.5, vel=15, vibrato=True)
        channel = Channel(role="lead", instrument=instrument, events=(event,))
        return render(Arrangement(meta={}, channels=(channel,)))

    assert not np.array_equal(rendered(25.0), rendered(80.0))


def test_an_instrument_without_vibrato_events_ignores_its_vibrato_fields():
    """`Event.vibrato` is still the switch; the instrument only shapes it."""

    def rendered(cents):
        instrument = Instrument(wave="pulse", vibrato_cents=cents)
        event = Event(t=0.0, pitch=69, dur=1.5, vel=15, vibrato=False)
        channel = Channel(role="lead", instrument=instrument, events=(event,))
        return render(Arrangement(meta={}, channels=(channel,)))

    assert np.array_equal(rendered(25.0), rendered(80.0))


def test_incoherent_summing_stays_loud_across_voice_counts():
    """sqrt(n) gain keeps output level constant as voices change.

    N independent channels at distinct pitches sum incoherently, giving
    power proportional to N. The gain = MIX_HEADROOM / sqrt(N) compensation
    at synth.py:88 holds output level nearly constant. This guards against
    regression to a fixed divisor, which would produce output proportional to
    sqrt(N) and grow ~58% from N=2 to N=5.

    vel=4 is deliberate, not incidental: at vel=15 the mix drives deep into
    the tanh soft clipper (synth.py:105), which compresses the very spread
    this test measures and lets several wrong gain laws slip under a loose
    threshold. At vel=4 the clipper stays out of the picture and the spread
    tracks the gain law honestly. Measured spread with correct gain is
    ~1.005x; a fixed-divisor break (gain = MIX_HEADROOM, no sqrt) measures
    ~1.48x.
    """
    levels = {}
    for count in (2, 3, 4, 5):
        # Build an arrangement with `count` channels, each on a distinct pitch.
        # Distinct pitches ensure incoherent summing (the assumption sqrt(n) encodes).
        channels = tuple(
            Channel(
                role=f"v{i}",
                instrument=Instrument(wave="pulse", duty=0.5),
                events=(Event(t=0.0, pitch=60 + i, dur=1.0, vel=4),),
            )
            for i in range(count)
        )
        arrangement = Arrangement(meta={}, channels=channels)
        audio = render(arrangement)
        levels[count] = float(np.sqrt(np.mean(audio**2)))

    # With sqrt(n) compensation, the levels should stay roughly constant.
    # Correct gain measures ~1.005x; every broken divisor tried (a fixed
    # constant, /2, /sqrt(5), /5) measures 1.47x or higher at this velocity.
    # 1.2 sits with clear headroom on both sides.
    ratio = max(levels.values()) / min(levels.values())
    assert ratio < 1.2, f"levels spread {ratio:.2f}x across {sorted(levels.keys())} channels"


def test_count_path_smoke_check_three_voices():
    """Smoke test: verify count path works and produces audible output.

    This test loads a real score and arranges it with 3 and 5 voices,
    confirming both produce audible output comparable in level. It is not a
    gain-law guard — constant gains cancel in ratios — but rather verifies the
    count feature integrates end-to-end without regression to silence.
    """
    score = ingest(Path(__file__).parent / "fixtures" / "minuet.mxl")
    levels = {}
    for count in (3, 5):
        config = replace(DEFAULTS, voices=replace(DEFAULTS.voices, count=count))
        audio = render(arrange(score, config))
        levels[count] = float(np.sqrt(np.mean(audio**2)))

    assert levels[3] > 0.0 and levels[5] > 0.0
    ratio = levels[3] / levels[5]
    assert 0.5 < ratio < 2.0, f"three voices mixed at {ratio:.2f}x five voices"


def arp_arrangement(instrument, pitch=69, dur=1.0, arp=()):
    return Arrangement(
        meta={"title": "t", "bpm": 120.0},
        channels=(
            Channel(
                role="lead",
                instrument=instrument,
                events=(Event(t=0.0, pitch=pitch, dur=dur, vel=15, arp=arp),),
            ),
        ),
    )


def dominant_hz(audio, lo=0, hi=None):
    """The loudest frequency in a slice of the render."""
    mono = audio[lo:hi].mean(axis=1)
    windowed = mono * np.hanning(len(mono))
    spectrum = np.abs(np.fft.rfft(windowed))
    return float(np.fft.rfftfreq(len(mono), 1 / SAMPLE_RATE)[np.argmax(spectrum)])


def test_an_arpeggio_step_sounds_at_the_pitch_it_names():
    """The bug this phase exists to fix.

    Every step used to be its own 16 ms event, so it restarted the instrument's
    pitch envelope and froze at index 0. A step naming A4 sounded at 499.7 Hz —
    a whole tone sharp, `pitch_env`'s first value.
    """
    instrument = Instrument(
        wave="pulse", duty=0.5, pitch_env=(2, 1, 0), volume_env=(15, 15, 15, 15)
    )
    plain = dominant_hz(render(arp_arrangement(instrument)))
    arped = dominant_hz(render(arp_arrangement(instrument, arp=(0,))))
    assert abs(plain - 440.0) < 6.0, "a plain A4 is the baseline"
    assert abs(arped - plain) < 6.0, "a single-member arpeggio is just the note"


def test_envelopes_run_once_across_an_arpeggio():
    """Per-step events restarted the volume envelope 62 times a second."""
    instrument = Instrument(wave="pulse", duty=0.5, volume_env=(15, 0))
    audio = render(arp_arrangement(instrument, dur=0.5, arp=(0, 4, 7)))
    head = float(np.abs(audio[:400]).max())
    tail = float(np.abs(audio[-400:]).max())
    assert head > 0.05, "the attack should sound"
    assert tail < head * 0.2, "the envelope must decay across the event, not restart"

def test_the_pitch_envelope_settles_instead_of_repeating_every_step():
    """The measured defect, asserted directly.

    At the default 16 ms rate a per-step implementation never advances the
    1/60 s pitch envelope past index 0, so an A4 sounded at 499.7 Hz forever
    instead of resolving to 440. This is the test that would have caught it.
    """
    instrument = Instrument(wave="pulse", duty=0.5, pitch_env=(2, 1, 0))
    audio = render(arp_arrangement(instrument, dur=1.0, arp=(0,)))
    late = dominant_hz(audio, lo=int(0.4 * SAMPLE_RATE))
    assert abs(late - 440.0) < 10.0, f"the blip must resolve; got {late:.1f} Hz"
    assert abs(late - 493.9) > 30.0, "not stuck a whole tone sharp"


def test_the_arpeggio_cycles_rather_than_sustaining_its_last_offset():
    """`step_values` clamps to its last step; an arpeggio comes back around."""
    instrument = Instrument(wave="pulse", duty=0.5, arp_rate_sec=0.05)
    step = int(0.05 * SAMPLE_RATE)
    audio = render(arp_arrangement(instrument, dur=0.4, arp=(0, 12)))
    # Sample the middle half of steps 0, 1, 2, 3 to avoid the edge fades.
    pitches = [
        dominant_hz(audio, lo=i * step + step // 4, hi=i * step + 3 * step // 4)
        for i in range(4)
    ]
    assert abs(pitches[0] - 440.0) < 25.0
    assert abs(pitches[1] - 880.0) < 40.0
    assert abs(pitches[2] - 440.0) < 25.0, "step 2 must return to the first offset"
    assert abs(pitches[3] - 880.0) < 40.0


def test_the_arp_rate_comes_from_the_instrument():
    """A hand-edited file renders the same with no config anywhere."""
    slow = Instrument(wave="pulse", duty=0.5, arp_rate_sec=0.2)
    audio = render(arp_arrangement(slow, dur=0.4, arp=(0, 12)))
    early = dominant_hz(audio, lo=int(0.05 * SAMPLE_RATE), hi=int(0.15 * SAMPLE_RATE))
    late = dominant_hz(audio, lo=int(0.25 * SAMPLE_RATE), hi=int(0.35 * SAMPLE_RATE))
    assert abs(early - 440.0) < 25.0
    assert abs(late - 880.0) < 40.0, "a 0.2s rate holds each offset far longer"
