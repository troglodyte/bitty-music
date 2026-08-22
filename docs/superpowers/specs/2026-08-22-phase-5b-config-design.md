# Phase 5b: config

Phase 5a built the targets half of Phase 5 and left the config half
untouched. Every constant the pipeline owns is still a module constant.
This phase gives them a TOML layer, a precedence order, and two named
presets, and changes no musical behaviour that is not asked for by a
config key.

## Scope

Phase 5 split in two because its halves share nothing but the CLI:

| Half | Delivers |
|------|----------|
| **5a** | `Render`, the target registry, the `bevy` / `bevy-kira` / `generic` emitters, `music.ron` — **complete** |
| **5b** | TOML precedence, named presets, and the constants that want configuring |

**5b wires existing knobs. It does not add musical behaviour.** The
parent spec's `[transform]` table — `transpose` and `tempo_scale` — is
new behaviour rather than an exposed constant, and it belongs to its own
phase with its own auditions. `tempo_scale` in particular reaches into
echo timing, arpeggio steps, and loop seams at once.

The parent spec's config table is illustrative, and does not map onto the
code one-for-one. Where it diverges, this document is the authority; each
divergence is named below.

## The layer stack

Resolved lowest to highest, each layer overriding the one beneath it:

| Layer | Source |
|-------|--------|
| defaults | `Config()` field defaults — today's module constants, exactly |
| preset | `--preset nes-tight`, a TOML file shipped inside the package |
| project | the nearest `bitty.toml`, searching upward from the score's directory |
| per-piece | `minuet.bitty.toml`, beside `minuet.mxl` |
| explicit | `--config PATH` |
| flags | `--target`, `-o`, `--wav` / `--ogg` |

Three rules make this predictable rather than clever:

- **Project config is first-hit-wins,** not merged across directory
  levels. A `bitty.toml` two directories up either applies whole or does
  not apply at all. Merging across levels means the value in front of you
  is never the whole story.
- **`--config` sits above discovery.** An explicit path is a deliberate
  act, so it beats a file that happened to be found.
- **The per-piece file is `<stem>.bitty.toml`,** following the existing
  `.arrangement.json` suffix convention. A bare `minuet.toml` would
  collide with whatever else in the directory wants that name.

Presets sit just above the defaults and below every file, so a project's
`bitty.toml` overrides the preset it started from.

## `bitty/config.py`

Three pieces, separable so each can be tested alone:

```python
def discover(score: Path) -> list[Path]: ...      # pure path logic
def load(paths: list[Path], preset: str | None) -> Config: ...
class ConfigError(Exception): ...                 # file, key path, message
```

`discover` walks upward for `bitty.toml` and checks for the sibling
per-piece file; it touches the filesystem only to ask whether a path
exists. It returns only the discovered layers, in order. The CLI appends
the `--config` path to that list, which is what puts explicit above
discovered without `discover` needing to know the flag exists. `load` parses with `tomllib` from the standard library,
validates, merges, and converts units. `Config` is a frozen dataclass
tree — `output`, `echo`, `arp`, `vibrato`, `loop`, `voices` — and the
`voices` field is the resolved `tuple[Voice, ...]` roster, not raw TOML.

Validation is a walk over the parsed tables against the dataclass fields,
plus a small per-field range table. No new dependency. An unknown key, an
unknown voice role, or an out-of-range value aborts before anything is
written, naming the file, the key path, and what was expected.

Failing loudly is the point. This is a tuning tool: you turn a knob and
listen for the difference. A typo'd key that silently does nothing is the
one outcome that wastes an afternoon, so it is the one outcome the loader
refuses to produce. This deliberately differs from the arrangement
loader, which drops unknown fields — that file is a hand-edit surface
that must survive a version skew, and this one is a set of instructions
that must be obeyed or refused.

### The keys

```toml
[output]  target = "bevy"    format = "ogg"   dir = "out"   sample_rate = 44100
[echo]    on = true          delay_beats = 0.75             level = 0.35
[arp]     rate_ms = 16
[vibrato] depth_cents = 25.0 delay_ms = 300   rate_hz = 5.5 min_note_ms = 500
[loop]    min_bars = 8       seam_ratio = 1.0

[voices.lead]
duty = 0.5
pan = -0.2
vibrato_cents = 40
```

Every value shown is the built-in default except `voices.lead.vibrato_cents`,
which illustrates an override.

`[voices.<role>]` accepts any field of `Voice` or of its `Instrument` —
`wave`, `duty`, `volume_env`, `pitch_env`, `quantize`, `cutoff_hz`,
`resonance`, the three vibrato fields, and `pan` — merged over the
built-in roster. The five role keys are `lead`, `counter`, `inner_a`,
`inner_b`, and `bass`; any other key is an error. Config can reshape a
voice but cannot add or remove one.

`[echo] on = false` means the lead channel is emitted with no `Echo`
attached, exactly as the other four channels already are. It does not
zero the level; a channel with a silent echo is not the same object as a
channel with none, and the arrangement should say which one it is.

`[vibrato]` sets the default that every roster voice inherits;
`[voices.lead] vibrato_cents` overrides that one voice. `min_note_ms`
stays global, because it decides *which* notes get vibrato at all — that
is arranger policy, not timbre.

Two divergences from the parent spec's table, both deliberate:

- **`delay_beats = 0.75`, not `delay = "3/16"`.** The code counts quarter
  notes. A fraction-string parser buys nothing but a parser.
- **Milliseconds in TOML, seconds in code.** `delay_ms` and `min_note_ms`
  read in the spec's units and convert at load, so neither the config nor
  the code has to hold the other's convention.

## How config reaches the code

The governing rule is the parent spec's: **config tunes the policy, the
JSON overrules the result.** Config is resolved once in the CLI and
shapes the arrangement. Everything the synth needs then rides in the
arrangement itself, so `bitty render` on a hand-edited file reproduces
the same audio with no config present anywhere.

- `arrange(score, config=DEFAULTS)` reads the roster, the echo settings,
  the arpeggio rate, and the vibrato threshold. Its results are baked
  into the channels and events.
- `loop.candidates` and `loop.choose` take the `loop` slice. The chosen
  loop is already stored in `arrangement.loop`, so `bitty render` never
  re-runs selection and never needs the config that produced it.
- `Instrument` gains `vibrato_cents`, `vibrato_delay`, and
  `vibrato_rate_hz`. `lfo.vibrato_cents()` takes them as parameters
  rather than reading module constants.
- `render()` is otherwise untouched: it already accepts `sample_rate`,
  and the CLI now passes the configured one.

Vibrato moves onto `Instrument` because it is the one render-time knob
the config table names. Making it per-voice rather than global is what
`Instrument`'s flat hand-edit surface is for, and it means the lead can
sing wider than the inner parts.

This also closes 5a's known gap: `write_audio` starts reading
`render.sample_rate` instead of hard-coding 44100.

**The `config=DEFAULTS` default parameter is the regression seam.** Every
existing caller and test keeps working untouched, and a test asserting
that `Config()` equals today's module constants proves the default path
is unchanged.

## CLI

Flags that config can also set default to `None`, so "not given" is
distinguishable from "given a value that happens to match the default".
`--wav` becomes the pair `--wav` / `--ogg` for the same reason; `--wav`
alone keeps working.

`--preset` and `--config` are added to `convert`, `render`, and
`sections`. `sections` needs them because `min_bars` and `seam_ratio`
change the auto-loop pick it prints, and a preset changes the audio the
seam is measured on. `--preset` validates against the shipped set
exactly as `_check_target` validates against `TARGETS` — the registry
itself is the list of valid answers.

Two presets ship: `nes-tight` and `lush`, as TOML under
`src/bitty/presets/`, read through `importlib.resources`.

## Testing

- **Unit.** Discovery: upward walk, first hit wins, sibling file found,
  missing files are not an error. Precedence: each layer beats the one
  below it, one test per adjacency. Validation: unknown key, unknown
  role, out-of-range value — each names its file and key path. Unit
  conversion: `delay_ms = 300` resolves to `0.3`.
- **Defaults equal the constants.** A direct assertion that a bare
  `Config()` carries today's values. This is the guard that lets every
  other test in the suite stay unchanged.
- **CLI.** A flag beats a config file; a bad config aborts before
  anything is written to the output directory.
- **Goldens.** The three golden arrangements regenerate to carry the new
  `Instrument` fields. The diff must be purely additive — three fields
  per instrument, default values, nothing else — and rendered bytes must
  be identical before and after.
- **Audition.** Default, `nes-tight`, and `lush` on the minuet, as WAV.

## Deliberately out of scope

- **`[transform]`.** New behaviour, own phase.
- **`dynamics.levels`.** Baked into the arrangement's 0–15 velocity
  contract and into every volume envelope in the roster. Changing it
  changes the file format, not a setting.
- **`voices.count`.** The roster stays five roles. See the risk below.
- **A `preset =` key inside config files.** It is the natural next
  request — a project wanting a preset base without typing the flag — but
  it makes resolution two-pass, and 5b would rather have one pass that is
  obviously correct.
- **The mix calibration constants.** `MIX_HEADROOM`, `FADE_SECONDS`,
  `DC_BLOCKER_POLE`, `NOISE_SEED`, `NYQUIST_MARGIN`, and the ingest
  fallbacks are calibration, not taste. Nothing is served by letting a
  config file detune the DC blocker.

## Risks

- **`nes-tight` cannot drop to four channels.** Without `voices.count`
  the preset changes timbre only, which makes its name a slight
  overclaim. Adding `count` is the honest fix and it is real arranger
  work: it interacts with middle-voice picking and with arpeggio
  overflow, and needs its own audition to confirm a four-voice reduction
  still sounds right. Named here so the next phase can weigh it.
- **Golden churn.** Adding fields to `Instrument` rewrites all three
  golden files. The mitigation is reviewing that diff rather than
  accepting it, and confirming the rendered audio is byte-identical.
- **`--wav` becomes tri-state.** A small behaviour change to an existing
  flag. `--wav` alone is unaffected; the new `--ogg` exists so a config
  file setting `format = "wav"` can be overridden back on the command
  line.

## What a later phase inherits

- A resolved `Config` threaded to `arrange` and `loop`, with one obvious
  place for `[transform]` to land.
- `TARGETS` with its default now a config key rather than a flag default.
- The remaining module constants, now a short and deliberate list rather
  than an unreviewed one.
