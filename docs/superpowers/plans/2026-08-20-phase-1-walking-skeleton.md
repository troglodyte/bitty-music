# Phase 1: Walking Skeleton — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert a MusicXML score into a two-voice square-and-triangle WAV file, end to end, so the pipeline is proven audible before any real arranging or synthesis work begins.

**Architecture:** Five modules in a straight line — `ingest` turns a score file into a `Score` of timed notes, `arrange` reduces it to a two-channel `Arrangement`, `synth` renders that to a float array, and `cli` writes a WAV. `Arrangement` is a JSON-serializable dataclass and is the contract every later phase builds against; everything else in this phase is deliberately the dumbest thing that works.

**Tech Stack:** Python 3.11+, music21 (score parsing), numpy (DSP), soundfile (WAV output), typer (CLI), pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-bitty-music-design.md`

## Global Constraints

- Python 3.11+.
- Phase 1 dependencies are exactly: `music21`, `numpy`, `soundfile`, `typer`, and `pytest` for dev. `librosa`, `mutagen`, and `sounddevice` belong to later phases — do not add them.
- Do not hand-roll audio encoding, metadata tag writing, key detection, structural segmentation, or score parsing. Libraries own those.
- MIDI note numbers for pitch. Seconds for time. Velocity 0–15 inside an `Arrangement`, 0–127 in a `Score`.
- Synthesis is deterministic: identical input renders identical output bytes.
- Source layout is `src/bitty/`, tests in `tests/`.

## Deliberately deferred to later phases

Do not build these now, and do not add fields for them: tempo maps, repeat
marks, key detection, section analysis, loop points, config files, presets,
echo, stereo, envelopes, arpeggios, OGG output, engine targets. Phase 1
ends the moment a recognizable tune comes out of a speaker.

## File Structure

| File | Responsibility |
|------|----------------|
| `pyproject.toml` | Package metadata, dependencies, `bitty` console script |
| `src/bitty/__init__.py` | Empty package marker |
| `src/bitty/model.py` | `Note` and `Score` — the musical model produced by ingest |
| `src/bitty/ingest.py` | music21 score file → `Score` |
| `src/bitty/arrangement.py` | `Event`, `Instrument`, `Channel`, `Arrangement` + JSON round-trip. The pipeline's spine. |
| `src/bitty/arrange.py` | `Score` → `Arrangement`, trivial two-voice reduction |
| `src/bitty/synth.py` | `Arrangement` → float32 mono numpy array |
| `src/bitty/cli.py` | `bitty convert` |
| `tests/fixtures/two_part.musicxml` | Four-note treble line over one bass whole note |
| `tests/test_ingest.py` | Ingest correctness |
| `tests/test_arrangement.py` | JSON round-trip |
| `tests/test_arrange.py` | Voice split correctness |
| `tests/test_synth.py` | Frequency, amplitude, length, determinism |
| `tests/test_cli.py` | End-to-end |

`model.py` and `arrangement.py` are separate on purpose: one is the
upstream musical model that later phases will grow (tempo maps, repeats),
the other is the frozen downstream render contract. Keeping them apart is
what lets `bitty render` exist in Phase 3 without dragging music21 in.

---

### Task 1: Project scaffold, musical model, and ingest

**Files:**
- Create: `pyproject.toml`
- Create: `src/bitty/__init__.py`
- Create: `src/bitty/model.py`
- Create: `src/bitty/ingest.py`
- Create: `tests/fixtures/two_part.musicxml`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Note(pitch: int, start: float, dur: float, velocity: int, part: int)`, `Score(notes: list[Note], bpm: float, time_signature: tuple[int, int], title: str)`, and `ingest(path: str | Path) -> Score`.

- [x] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "bitty-music"
version = "0.1.0"
description = "Classical scores to chiptune audio"
requires-python = ">=3.11"
dependencies = [
    "music21>=9.1",
    "numpy>=1.26",
    "soundfile>=0.12",
    "typer>=0.12",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
bitty = "bitty.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/bitty"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [x] **Step 2: Create the virtualenv and install**

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Expected: installs cleanly. music21 pulls a fair number of transitive
dependencies and takes a minute; that is normal.

- [x] **Step 3: Create the package marker and the test fixture**

`src/bitty/__init__.py` is empty.

`tests/fixtures/two_part.musicxml` — a treble part playing C5 D5 E5 F5 as
quarter notes over a bass part holding C3 for a whole note. With no tempo
marking, music21 defaults to 120 BPM, so each quarter note lasts 0.5s.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Treble</part-name></score-part>
    <score-part id="P2"><part-name>Bass</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>5</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>F</step><octave>5</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>F</sign><line>4</line></clef>
      </attributes>
      <note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
```

- [x] **Step 4: Write the failing test**

`tests/test_ingest.py`:

```python
from pathlib import Path

from bitty.ingest import ingest

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"


def test_ingest_reads_every_note():
    score = ingest(FIXTURE)
    assert len(score.notes) == 5


def test_ingest_defaults_to_120_bpm_when_score_has_no_tempo_mark():
    score = ingest(FIXTURE)
    assert score.bpm == 120.0
    assert score.time_signature == (4, 4)


def test_ingest_converts_offsets_to_seconds():
    score = ingest(FIXTURE)
    treble = sorted([n for n in score.notes if n.part == 0], key=lambda n: n.start)
    assert [n.pitch for n in treble] == [72, 74, 76, 77]
    assert [n.start for n in treble] == [0.0, 0.5, 1.0, 1.5]
    assert all(n.dur == 0.5 for n in treble)


def test_ingest_tags_notes_with_their_source_part():
    score = ingest(FIXTURE)
    bass = [n for n in score.notes if n.part == 1]
    assert len(bass) == 1
    assert bass[0].pitch == 48
    assert bass[0].start == 0.0
    assert bass[0].dur == 2.0
```

- [x] **Step 5: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_ingest.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'bitty.ingest'`

- [x] **Step 6: Write `src/bitty/model.py`**

```python
"""The musical model produced by ingest, upstream of any chiptune decisions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Note:
    """One sounding pitch, with times already resolved to seconds."""

    pitch: int  # MIDI note number
    start: float  # seconds from the start of the score
    dur: float  # seconds
    velocity: int  # 0-127, as written in the source
    part: int  # index of the source part or staff


@dataclass(frozen=True)
class Score:
    notes: tuple[Note, ...]
    bpm: float
    time_signature: tuple[int, int]
    title: str
```

- [x] **Step 7: Write `src/bitty/ingest.py`**

```python
"""Score files to the internal Score model, via music21."""

from pathlib import Path

from music21 import chord, converter, meter, note, tempo

from bitty.model import Note, Score

DEFAULT_BPM = 120.0
DEFAULT_VELOCITY = 64


def ingest(path: str | Path) -> Score:
    """Parse a MusicXML, compressed MusicXML, or MIDI file into a Score."""
    path = Path(path)
    parsed = converter.parse(str(path))

    bpm = _first_tempo(parsed)
    seconds_per_quarter = 60.0 / bpm

    notes: list[Note] = []
    for part_index, part in enumerate(parsed.parts):
        for element in part.flatten().notes:
            start = float(element.offset) * seconds_per_quarter
            dur = float(element.duration.quarterLength) * seconds_per_quarter
            velocity = _velocity_of(element)
            for pitch in _pitches_of(element):
                notes.append(
                    Note(
                        pitch=pitch,
                        start=start,
                        dur=dur,
                        velocity=velocity,
                        part=part_index,
                    )
                )

    notes.sort(key=lambda n: (n.start, -n.pitch))
    return Score(
        notes=tuple(notes),
        bpm=bpm,
        time_signature=_first_time_signature(parsed),
        title=_title_of(parsed, path),
    )


def _pitches_of(element) -> list[int]:
    if isinstance(element, chord.Chord):
        return [int(p.midi) for p in element.pitches]
    if isinstance(element, note.Note):
        return [int(element.pitch.midi)]
    return []


def _velocity_of(element) -> int:
    velocity = getattr(element.volume, "velocity", None)
    return int(velocity) if velocity is not None else DEFAULT_VELOCITY


def _first_tempo(parsed) -> float:
    marks = parsed.flatten().getElementsByClass(tempo.MetronomeMark)
    for mark in marks:
        if mark.number:
            return float(mark.number)
    return DEFAULT_BPM


def _first_time_signature(parsed) -> tuple[int, int]:
    signatures = parsed.flatten().getElementsByClass(meter.TimeSignature)
    for signature in signatures:
        return (int(signature.numerator), int(signature.denominator))
    return (4, 4)


def _title_of(parsed, path: Path) -> str:
    metadata = parsed.metadata
    if metadata is not None and metadata.title:
        return str(metadata.title)
    return path.stem
```

- [x] **Step 8: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_ingest.py -v`
Expected: 4 passed

- [x] **Step 9: Commit**

```bash
git add pyproject.toml src/bitty tests/
git commit -m "feat: ingest MusicXML into the Score model"
```

---

### Task 2: The Arrangement contract

**Files:**
- Create: `src/bitty/arrangement.py`
- Test: `tests/test_arrangement.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Event(t: float, pitch: int, dur: float, vel: int)`, `Instrument(wave: str, duty: float)`, `Channel(role: str, instrument: Instrument, events: tuple[Event, ...])`, `Arrangement(meta: dict, channels: tuple[Channel, ...])`, `Arrangement.to_json() -> str`, `Arrangement.from_json(text: str) -> Arrangement`.

This is the file every later phase depends on. The JSON round-trip test is
not ceremony — it is what makes hand-editing an arrangement and
re-rendering it safe in Phase 3.

- [x] **Step 1: Write the failing test**

`tests/test_arrangement.py`:

```python
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
```

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_arrangement.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'bitty.arrangement'`

- [x] **Step 3: Write `src/bitty/arrangement.py`**

```python
"""The pipeline's spine: a JSON-serializable chiptune arrangement.

Everything upstream of this file is musical analysis; everything
downstream is signal processing. It is deliberately free of music21 and of
sample rates, so a hand-edited arrangement can be re-rendered on its own.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

MAX_VELOCITY = 15


@dataclass(frozen=True)
class Event:
    t: float  # seconds from the start of the arrangement
    pitch: int  # MIDI note number
    dur: float  # seconds
    vel: int  # 0-15


@dataclass(frozen=True)
class Instrument:
    wave: str  # "pulse" or "triangle"
    duty: float = 0.5


@dataclass(frozen=True)
class Channel:
    role: str
    instrument: Instrument
    events: tuple[Event, ...]


@dataclass(frozen=True)
class Arrangement:
    meta: dict
    channels: tuple[Channel, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> Arrangement:
        raw = json.loads(text)
        return cls(
            meta=raw["meta"],
            channels=tuple(
                Channel(
                    role=channel["role"],
                    instrument=Instrument(**channel["instrument"]),
                    events=tuple(Event(**event) for event in channel["events"]),
                )
                for channel in raw["channels"]
            ),
        )
```

- [x] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_arrangement.py -v`
Expected: 2 passed

- [x] **Step 5: Commit**

```bash
git add src/bitty/arrangement.py tests/test_arrangement.py
git commit -m "feat: add the Arrangement contract with JSON round-trip"
```

---

### Task 3: Trivial two-voice arranger

**Files:**
- Create: `src/bitty/arrange.py`
- Test: `tests/test_arrange.py`

**Interfaces:**
- Consumes: `Score`, `Note` from `bitty.model`; `Arrangement`, `Channel`, `Instrument`, `Event` from `bitty.arrangement`.
- Produces: `arrange(score: Score) -> Arrangement` returning exactly two channels, `role="lead"` then `role="bass"`.

The rule: rank source parts by mean pitch. The highest-mean part becomes
the lead, taking the top note of any chord; the lowest-mean part becomes
the bass, taking the bottom note. Everything else is dropped. A single-part
score splits by taking the top and bottom note at each onset instead.

This throws away most of the music, and that is the point — Phase 3
replaces it wholesale. Its only job is to prove the pipeline carries notes
from one end to the other.

- [x] **Step 1: Write the failing test**

`tests/test_arrange.py`:

```python
from pathlib import Path

from bitty.arrange import arrange
from bitty.ingest import ingest
from bitty.model import Note, Score

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"


def channel(arrangement, role):
    return next(c for c in arrangement.channels if c.role == role)


def test_multi_part_score_splits_highest_and_lowest_parts():
    arrangement = arrange(ingest(FIXTURE))
    assert [c.role for c in arrangement.channels] == ["lead", "bass"]
    assert [e.pitch for e in channel(arrangement, "lead").events] == [72, 74, 76, 77]
    assert [e.pitch for e in channel(arrangement, "bass").events] == [48]


def test_lead_is_a_pulse_and_bass_is_a_triangle():
    arrangement = arrange(ingest(FIXTURE))
    assert channel(arrangement, "lead").instrument.wave == "pulse"
    assert channel(arrangement, "bass").instrument.wave == "triangle"


def test_velocity_is_quantized_to_sixteen_levels():
    arrangement = arrange(ingest(FIXTURE))
    for chan in arrangement.channels:
        for event in chan.events:
            assert 0 <= event.vel <= 15


def test_single_part_score_splits_top_and_bottom_note_of_each_onset():
    score = Score(
        notes=(
            Note(pitch=72, start=0.0, dur=1.0, velocity=64, part=0),
            Note(pitch=64, start=0.0, dur=1.0, velocity=64, part=0),
            Note(pitch=48, start=0.0, dur=1.0, velocity=64, part=0),
        ),
        bpm=120.0,
        time_signature=(4, 4),
        title="chord",
    )
    arrangement = arrange(score)
    assert [e.pitch for e in channel(arrangement, "lead").events] == [72]
    assert [e.pitch for e in channel(arrangement, "bass").events] == [48]


def test_arrangement_meta_carries_title_and_tempo():
    arrangement = arrange(ingest(FIXTURE))
    assert arrangement.meta["bpm"] == 120.0
    # music21 may synthesize a title from work or movement metadata, so assert
    # only that one is present. Output filenames come from the file stem, not
    # from this field.
    assert isinstance(arrangement.meta["title"], str)
    assert arrangement.meta["title"]
```

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_arrange.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'bitty.arrange'`

- [x] **Step 3: Write `src/bitty/arrange.py`**

```python
"""Phase 1 arranger: keep the top line and the bottom line, drop the rest.

Placeholder by design. Phase 3 replaces this with voice-leading assignment
and arpeggio overflow; the only contract that must survive is the shape of
the Arrangement it returns.
"""

from collections import defaultdict
from itertools import groupby

from bitty.arrangement import MAX_VELOCITY, Arrangement, Channel, Event, Instrument
from bitty.model import Note, Score

LEAD = Instrument(wave="pulse", duty=0.5)
BASS = Instrument(wave="triangle")


def arrange(score: Score) -> Arrangement:
    lead_notes, bass_notes = _split_voices(score.notes)
    return Arrangement(
        meta={"title": score.title, "bpm": score.bpm},
        channels=(
            Channel(role="lead", instrument=LEAD, events=_to_events(lead_notes)),
            Channel(role="bass", instrument=BASS, events=_to_events(bass_notes)),
        ),
    )


def _split_voices(notes: tuple[Note, ...]) -> tuple[list[Note], list[Note]]:
    by_part: dict[int, list[Note]] = defaultdict(list)
    for note in notes:
        by_part[note.part].append(note)

    if len(by_part) >= 2:
        ranked = sorted(by_part.values(), key=_mean_pitch)
        return _top_of_each_onset(ranked[-1]), _bottom_of_each_onset(ranked[0])

    single = list(notes)
    return _top_of_each_onset(single), _bottom_of_each_onset(single)


def _mean_pitch(notes: list[Note]) -> float:
    return sum(n.pitch for n in notes) / len(notes)


def _top_of_each_onset(notes: list[Note]) -> list[Note]:
    return [max(group, key=lambda n: n.pitch) for group in _by_onset(notes)]


def _bottom_of_each_onset(notes: list[Note]) -> list[Note]:
    return [min(group, key=lambda n: n.pitch) for group in _by_onset(notes)]


def _by_onset(notes: list[Note]) -> list[list[Note]]:
    ordered = sorted(notes, key=lambda n: n.start)
    return [list(group) for _, group in groupby(ordered, key=lambda n: n.start)]


def _to_events(notes: list[Note]) -> tuple[Event, ...]:
    return tuple(
        Event(
            t=note.start,
            pitch=note.pitch,
            dur=note.dur,
            vel=_quantize_velocity(note.velocity),
        )
        for note in sorted(notes, key=lambda n: n.start)
    )


def _quantize_velocity(velocity: int) -> int:
    """127 MIDI steps down to the 16 levels an 8-bit channel actually has."""
    return max(0, min(MAX_VELOCITY, round(velocity / 127 * MAX_VELOCITY)))
```

- [x] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_arrange.py -v`
Expected: 5 passed

- [x] **Step 5: Commit**

```bash
git add src/bitty/arrange.py tests/test_arrange.py
git commit -m "feat: add trivial two-voice arranger"
```

---

### Task 4: Naive synthesizer

**Files:**
- Create: `src/bitty/synth.py`
- Test: `tests/test_synth.py`

**Interfaces:**
- Consumes: `Arrangement`, `Channel`, `Event`, `Instrument`, `MAX_VELOCITY` from `bitty.arrangement`.
- Produces: `render(arrangement: Arrangement, sample_rate: int = 44100) -> numpy.ndarray` returning float32 mono in [-1.0, 1.0], and `SAMPLE_RATE = 44100`.

Naive oscillators, no bandlimiting — Phase 2 adds PolyBLEP. The one
concession is a 2 ms fade at each note edge: without it every note onset
is a step discontinuity and the output is more click than music, which
would make the phase's own acceptance check impossible to judge.

- [x] **Step 1: Write the failing test**

`tests/test_synth.py`:

```python
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
```

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_synth.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'bitty.synth'`

- [x] **Step 3: Write `src/bitty/synth.py`**

```python
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
```

- [x] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_synth.py -v`
Expected: 7 passed

- [x] **Step 5: Commit**

```bash
git add src/bitty/synth.py tests/test_synth.py
git commit -m "feat: add naive square and triangle synthesizer"
```

---

### Task 5: CLI and end-to-end acceptance

**Files:**
- Create: `src/bitty/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ingest`, `arrange`, `render`, `SAMPLE_RATE`, `Arrangement`.
- Produces: `app` (a `typer.Typer` wired as the `bitty` console script) and the `bitty convert SCORE -o OUT_DIR` command, writing `<title>.wav` and `<title>.arrangement.json`.

Writing the arrangement JSON alongside the audio is not extra scope — it
is what makes Phase 3's `bitty render` a small change rather than a
restructuring, and it is the file you read when the audio sounds wrong.

- [x] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
import json
from pathlib import Path

import soundfile as sf
from typer.testing import CliRunner

from bitty.arrangement import Arrangement
from bitty.cli import app

FIXTURE = Path(__file__).parent / "fixtures" / "two_part.musicxml"
runner = CliRunner()


def test_convert_writes_audio_and_arrangement(tmp_path):
    result = runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output

    wav = tmp_path / "two_part.wav"
    arrangement_json = tmp_path / "two_part.arrangement.json"
    assert wav.exists()
    assert arrangement_json.exists()


def test_converted_audio_has_the_expected_duration(tmp_path):
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    audio, sample_rate = sf.read(tmp_path / "two_part.wav")
    assert sample_rate == 44100
    assert abs(len(audio) / sample_rate - 2.0) < 0.01


def test_written_arrangement_reloads(tmp_path):
    runner.invoke(app, ["convert", str(FIXTURE), "-o", str(tmp_path)])
    text = (tmp_path / "two_part.arrangement.json").read_text()
    arrangement = Arrangement.from_json(text)
    assert [c.role for c in arrangement.channels] == ["lead", "bass"]
    assert json.loads(text)["meta"]["bpm"] == 120.0


def test_missing_input_file_fails_loudly(tmp_path):
    result = runner.invoke(app, ["convert", str(tmp_path / "nope.musicxml"), "-o", str(tmp_path)])
    assert result.exit_code != 0
```

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'bitty.cli'`

- [x] **Step 3: Write `src/bitty/cli.py`**

```python
"""Command-line entry point."""

from pathlib import Path

import soundfile as sf
import typer

from bitty.arrange import arrange
from bitty.ingest import ingest
from bitty.synth import SAMPLE_RATE, render

app = typer.Typer(help="Turn classical scores into chiptune audio.")


@app.command()
def convert(
    score: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_dir: Path = typer.Option(Path("out"), "-o", "--out-dir"),
) -> None:
    """Convert a score to a WAV file and its arrangement JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)

    arrangement = arrange(ingest(score))
    audio = render(arrangement)

    stem = score.stem
    wav_path = out_dir / f"{stem}.wav"
    json_path = out_dir / f"{stem}.arrangement.json"

    sf.write(wav_path, audio, SAMPLE_RATE)
    json_path.write_text(arrangement.to_json())

    typer.echo(f"{wav_path}  ({len(audio) / SAMPLE_RATE:.1f}s)")
    typer.echo(f"{json_path}")
```

- [x] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: 4 passed

- [x] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest -v`
Expected: 22 passed

- [x] **Step 6: Acceptance — convert a real piece and listen to it**

Download a public-domain MusicXML score with a clear melody and bass — a
Bach chorale from the Mutopia Project or a Clementi sonatina works well.
Then:

```bash
.venv/bin/bitty convert /path/to/score.musicxml -o out/
```

Play `out/<name>.wav`. The bar to clear is *recognizability*, not beauty:
the melody should be followable and in tune, the bass should be audible
underneath it, and there should be no runaway clipping or clicking. It
will sound thin and mechanical — no envelopes, no echo, two voices out of
a possible five. That is exactly what Phases 2 and 3 fix.

If the melody is unrecognizable, the arranger picked the wrong part.
Inspect `out/<name>.arrangement.json` to see which pitches landed in which
channel before changing any code.

- [x] **Step 7: Commit**

```bash
git add src/bitty/cli.py tests/test_cli.py
git commit -m "feat: add bitty convert CLI"
```

---

## Phase 1 exit criteria

- `.venv/bin/pytest` passes.
- `bitty convert` turns a real public-domain score into an audible,
  recognizable WAV.
- `arrangement.json` is written, reloadable, and readable by a human.

Phase 2 replaces `synth.py` wholesale — PolyBLEP oscillators, duty
cycles, step-sequence envelopes, echo, stereo, and Ogg output — against
the `Arrangement` contract this phase locks in.
