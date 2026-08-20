"""Phase 1 synthesizer: naive square and triangle, summed to mono.

No bandlimiting, no envelopes, no stereo — Phase 2 adds all three. The
2 ms edge fade is the exception, and exists only so note onsets do not
click loudly enough to drown out the thing this phase is meant to check.
"""

import numpy as np

from bitty.arrangement import MAX_VELOCITY, Arrangement, Event, Instrument

SAMPLE_RATE = 44100
FADE_SECONDS = 0.002
A4_MIDI = 69
A4_HZ = 440.0


def render(arrangement: Arrangement, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Render an arrangement to a mono float32 buffer in [-1.0, 1.0]."""
    total_seconds = _duration_of(arrangement)
    buffer = np.zeros(int(round(total_seconds * sample_rate)), dtype=np.float64)
    if not arrangement.channels:
        return buffer.astype(np.float32)

    gain = 1.0 / len(arrangement.channels)
    for channel in arrangement.channels:
        for event in channel.events:
            _mix_event(buffer, event, channel.instrument, gain, sample_rate)

    return np.clip(buffer, -1.0, 1.0).astype(np.float32)


def _duration_of(arrangement: Arrangement) -> float:
    ends = [
        event.t + event.dur
        for channel in arrangement.channels
        for event in channel.events
    ]
    return max(ends, default=0.0)


def _mix_event(
    buffer: np.ndarray,
    event: Event,
    instrument: Instrument,
    gain: float,
    sample_rate: int,
) -> None:
    start = int(round(event.t * sample_rate))
    length = int(round(event.dur * sample_rate))
    if length <= 0:
        return

    phase = np.arange(length, dtype=np.float64) * (_hz(event.pitch) / sample_rate)
    wave = _oscillator(instrument.wave)(phase, instrument.duty)
    wave *= (event.vel / MAX_VELOCITY) * gain
    wave *= _edge_fade(length, sample_rate)

    end = min(start + length, len(buffer))
    buffer[start:end] += wave[: end - start]


def _oscillator(name: str):
    try:
        return {"pulse": _pulse, "triangle": _triangle}[name]
    except KeyError:
        raise ValueError(f"unknown wave {name!r}") from None


def _pulse(phase: np.ndarray, duty: float) -> np.ndarray:
    return np.where((phase % 1.0) < duty, 1.0, -1.0)


def _triangle(phase: np.ndarray, duty: float) -> np.ndarray:
    return 4.0 * np.abs((phase + 0.25) % 1.0 - 0.5) - 1.0


def _edge_fade(length: int, sample_rate: int) -> np.ndarray:
    fade = min(int(FADE_SECONDS * sample_rate), length // 2)
    envelope = np.ones(length, dtype=np.float64)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float64)
        envelope[:fade] = ramp
        envelope[-fade:] = ramp[::-1]
    return envelope


def _hz(midi_pitch: int) -> float:
    return A4_HZ * 2.0 ** ((midi_pitch - A4_MIDI) / 12.0)
