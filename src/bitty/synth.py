"""The mixer: an Arrangement in, a stereo float32 buffer out.

This file owns routing and gain staging only. Waveforms live in `osc`,
envelopes in `envelope`, and filtering in `filters` — each a pure function of
arrays, which is what makes them testable as properties instead of by ear.

Signal path per channel: oscillator -> pitch envelope and vibrato -> volume
envelope -> edge fade -> lowpass -> constant-power pan -> sum. Then, across the mix: echo taps, DC
blocker, soft clip.
"""

import math

import numpy as np

from bitty.arrangement import MAX_VELOCITY, Arrangement, Channel, Event, Instrument
from bitty.envelope import step_values
from bitty.filters import dc_block, lowpass
from bitty.lfo import vibrato_cents
from bitty.osc import oscillator

SAMPLE_RATE = 44100
FADE_SECONDS = 0.002
MIX_HEADROOM = 0.9
A4_MIDI = 69
A4_HZ = 440.0


def render(arrangement: Arrangement, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Render an arrangement to stereo float32 in [-1.0, 1.0]."""
    length = _length_of(arrangement, sample_rate)
    mix = np.zeros((length, 2), dtype=np.float64)
    if not arrangement.channels:
        return mix.astype(np.float32)

    # Voices sum incoherently far more often than they line up, so sqrt(n)
    # keeps a five-voice mix as loud as a two-voice one without leaving the
    # soft clipper to do all the work.
    gain = MIX_HEADROOM / math.sqrt(len(arrangement.channels))

    for channel in arrangement.channels:
        voice = _render_channel(channel, length, sample_rate) * gain
        _add_panned(mix, voice, channel.pan, level=1.0, offset=0)
        if channel.echo:
            # The repeat sits on the opposite side of the image. Mono hardware
            # never did this; it is the cheapest width available and the spec
            # buys stereo spread deliberately.
            _add_panned(
                mix,
                voice,
                -channel.pan,
                level=channel.echo.level,
                offset=int(round(channel.echo.delay_sec * sample_rate)),
            )

    return np.tanh(dc_block(mix)).astype(np.float32)


def _length_of(arrangement: Arrangement, sample_rate: int) -> int:
    ends = [
        event.t + event.dur + (channel.echo.delay_sec if channel.echo else 0.0)
        for channel in arrangement.channels
        for event in channel.events
    ]
    return int(round(max(ends, default=0.0) * sample_rate))


def _render_channel(channel: Channel, length: int, sample_rate: int) -> np.ndarray:
    voice = np.zeros(length, dtype=np.float64)
    for event in channel.events:
        _add_event(voice, event, channel.instrument, sample_rate)

    if channel.instrument.cutoff_hz:
        voice = lowpass(
            voice,
            channel.instrument.cutoff_hz,
            channel.instrument.resonance,
            sample_rate,
        )
    return voice


def _add_event(
    voice: np.ndarray, event: Event, instrument: Instrument, sample_rate: int
) -> None:
    length = int(round(event.dur * sample_rate))
    if length <= 0:
        return

    inc = np.full(length, _hz(event.pitch) / sample_rate, dtype=np.float64)
    if instrument.pitch_env:
        semitones = step_values(instrument.pitch_env, length, sample_rate)
        inc = inc * 2.0 ** (semitones / 12.0)

    if event.vibrato:
        # Composed with the pitch envelope, not replacing it: the blip is the
        # attack, the vibrato is the sustain.
        inc = inc * 2.0 ** (vibrato_cents(length, sample_rate) / 1200.0)

    phase = np.concatenate(([0.0], np.cumsum(inc)[:-1]))
    wave = oscillator(instrument.wave)(phase, inc, instrument)

    amplitude = event.vel / MAX_VELOCITY
    if instrument.volume_env:
        amplitude = amplitude * (
            step_values(instrument.volume_env, length, sample_rate) / MAX_VELOCITY
        )
    wave = wave * amplitude * _edge_fade(length, sample_rate)

    start = int(round(event.t * sample_rate))
    end = min(start + length, len(voice))
    if end > start:
        voice[start:end] += wave[: end - start]


def _add_panned(
    mix: np.ndarray, voice: np.ndarray, pan: float, level: float, offset: int
) -> None:
    if level == 0.0 or offset >= len(mix):
        return

    end = min(offset + len(voice), len(mix))
    segment = voice[: end - offset] * level
    left, right = _pan_gains(pan)
    mix[offset:end, 0] += segment * left
    mix[offset:end, 1] += segment * right


def _pan_gains(pan: float) -> tuple[float, float]:
    """Constant-power pan: a voice keeps its loudness as it crosses the image."""
    angle = (max(-1.0, min(1.0, pan)) + 1.0) * math.pi / 4.0
    return math.cos(angle), math.sin(angle)


def _edge_fade(length: int, sample_rate: int) -> np.ndarray:
    """Two milliseconds in and out, so note boundaries do not click."""
    fade = min(int(FADE_SECONDS * sample_rate), length // 2)
    envelope = np.ones(length, dtype=np.float64)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float64)
        envelope[:fade] = ramp
        envelope[-fade:] = ramp[::-1]
    return envelope


def _hz(midi_pitch: int) -> float:
    return A4_HZ * 2.0 ** ((midi_pitch - A4_MIDI) / 12.0)
