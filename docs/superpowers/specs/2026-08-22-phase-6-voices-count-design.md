# Phase 6: voices.count

Phase 5b shipped `nes-tight` with a name it could not honour. Its own
header comment says so: "the name overclaims slightly — without
`[voices] count` this cannot drop to four channels, so it changes timbre
only." This phase adds that key, and makes the roster a variable-length
thing the arranger reads rather than a fixed five the arranger assumes.

## Scope

One config key, `[voices] count`, and the seam it needs to be safe.

The key is small. The reason it is a phase and not an afternoon is that
`arrange.py` imports `LEAD_ROLE`, `BASS_ROLE`, `MIDDLE_ROLES`, and
`ARP_ROLE` as module constants pinned to specific voices. `ARP_ROLE =
INNER_B.role` is simply wrong once `inner_b` can be absent — the
arpeggio would be folded onto a channel that does not exist. Making
membership variable means making those four names derived rather than
declared.

**This phase changes the reduction, not the sound.** No new oscillator,
no new instrument field, no change to the `Arrangement` contract. A
three-voice arrangement is the same JSON with fewer channels.

## The count

`[voices] count = N` — an integer, 3 to 5, default 5.

Five is today's behaviour exactly. **At the default, this phase must be
inaudible and the golden files byte-identical.**

Lead and bass are structural pins, not preferences. `_assign` reads the
top of each onset group against the standing texture and the bottom
against it too; without both pins there is no reduction, only a pile.
So the count shrinks the middles, from the narrowest end:

| count | active voices | dropped | arp carrier |
|-------|---------------|---------|-------------|
| 5 | lead, counter, inner_a, inner_b, bass | — | `inner_b` |
| 4 | lead, counter, inner_a, bass | `inner_b` | `inner_a` |
| 3 | lead, counter, bass | `inner_b`, `inner_a` | `counter` |

The drop order follows duty width: `inner_b` is the 0.125 pulse,
`inner_a` the 0.25. Dropping the narrowest first keeps the widest,
most present middle voice longest. It happens to coincide with reverse
declaration order, which makes the rule cheap to state and cheap to
test — but width is the reason, and a future roster reordering should
preserve the width rule rather than the index rule.

### Why the floor is 3

At `count = 2` there are no middles. `_pick_middle` would return `None`
for every note, every unplaced note would become a leftover, and
`_arpeggiate` would fold the entire inner texture onto a carrier that
does not exist. The alternatives — arpeggiating onto the lead, or
discarding the overflow — both break a promise the arranger currently
makes. Folding onto the lead makes the melody cycle chord tones, which
is precisely the "note soup" the module docstring says voice-leading
exists to prevent. Discarding contradicts `_arpeggiate`'s own comment
that the cycle "carries the whole chord and not just the part that
would otherwise have been lost."

A floor of 3 keeps `middles` non-empty, so `.arp` always names a real
channel. The invariant is structural, not a runtime check.

A two-voice lead-and-bass outline is Phase 1's walking skeleton. It is
reachable by writing a roster, not by turning a supported dial.

## `Roster`

A frozen dataclass in `voices.py`, holding every voice and the count.

The bare five-voice tuple is renamed `VOICES`; `ROSTER` becomes the
default `Roster` instance, so `config.py`'s existing `ROSTER` import and
the tests' `for v in ROSTER` keep meaning what they mean today.

```python
@dataclass(frozen=True)
class Roster:
    voices: tuple[Voice, ...] = VOICES   # always all five
    count: int = len(VOICES)
```

It exposes `.active`, `.lead`, `.bass`, `.middles`, and `.arp`, and
iterates as its active voices. `.shrink(count)` is the setter — it
returns a new `Roster` over the same voices with a different count, and
is where the 3-5 bound is enforced.

**Truncation is a view, not a deletion.** The dropped voices stay in
`.voices` and only `.active` narrows. This is what lets `count` merge
like any other scalar: every layer validates `[voices.inner_b]` against
the full roster whether or not some other layer set `count = 3`, and no
layer ever has to grow the roster back.

Iteration yields actives, so `config.voices` remains the single answer
to "who plays" — the count is not a second field callers must remember
to consult. `arrange()`'s `for voice in config.voices` loop is unchanged.

`.arp` is `.middles[-1]`: the narrowest surviving middle. It is a
derived property rather than a stored role, so it cannot fall out of
step with membership.

## Config

`count` is the one scalar key in the `[voices]` table; every other key
there is a role sub-table, as today. `merge` reads `count` off the
table before iterating roles, so an unknown role name still errors with
the roster listing it errors with now.

Validation is `_whole(low=3, high=5)`, and the message names the range.
`count` resolves through the layer stack like any scalar: last writer
wins, flags over explicit over per-piece over project over preset over
defaults.

An override of a dropped voice is accepted and moot. `[voices.inner_b]`
in a project file does not become an error the day someone adds
`--preset nes-tight`; the override applies to a voice that is simply not
active. Making it an error would couple layers that are independently
valid, and the fix would mean editing a file the user did not change.

## Arranger

Four call sites lose their constants:

- `_assign` builds tracks for active roles only, and pins against
  `roster.lead` / `roster.bass`.
- `_pick_middle` reads `roster.middles` instead of `MIDDLE_ROLES`.
- `_arpeggiate` folds onto `roster.arp`.
- `arrange` compares against `roster.lead` when attaching the echo.

`MIDDLE_ROLES` and `ARP_ROLE` are deleted. They are the wrong shape once
membership varies, and leaving them would leave two answers to the same
question. Their uses are confined to `arrange.py` and `tests/test_voices.py`.

## Presets

`nes-tight` gains `count = 3`, loses its apologetic header comment, and
loses its `[voices.inner_a]` and `[voices.inner_b]` blocks, which can no
longer apply. It already sets `counter` to duty 0.125, so the single
surviving middle is genuinely the narrow pulse.

Three is the honest NES melodic roster: two pulses and a triangle. The
console's remaining channels are noise and DPCM, which this roster has
no voice for. Four would leave three pulses sounding at once, which no
NES can do — a smaller overclaim, but still one.

`lush` is untouched and stays at five.

## Testing

- **`Roster`.** Drop order and `.arp` identity at 3, 4, and 5.
  `.middles` never empty. `.shrink` outside 3–5 rejected.
- **Config.** `count` parsed; out-of-range and non-integer rejected with
  the range named; last-writer-wins across two files; an override of a
  dropped voice accepted and moot.
- **Arranger.** At `count = 3`, no events on `inner_a` or `inner_b`, the
  lead and bass pins still hold, and the notes those voices would have
  taken appear in the arp cycle on `counter`.
- **Targets.** `music.ron` and the Bevy manifests still assemble from a
  three-channel arrangement. Verify the RON parses with the scratch
  `ron` crate rather than by eye.

**Every test above is proven by breaking the implementation.** A test
that still passes when `count` is ignored entirely is testing the
default, not the feature. The specific trap here is asserting only the
channel count: an arrangement can have three channels because the score
was thin. Assert where the displaced notes *went*.

**Golden files must not change.** Count 5 is today's behaviour, so a
diff in the goldens is a bug in the seam, not churn to accept.

## Audition

The minuet three ways, as WAV — `aplay` renders Ogg as static, so WAV is
the only format that works here. Default, `nes-tight`, and a bare
`count = 4` with no other preset keys, so the count's effect is
separable from `nes-tight`'s timbre changes.

Measure before listening: leap counts and part purity per arrangement,
so the numbers sit next to the impression. Listen for whether the tune
survives at three voices, whether the arpeggio on `counter` is too busy,
and whether the harmony still reads.

## Deliberately out of scope

- **`count` below 3.** See the floor argument above.
- **A noise voice.** The honest fourth NES channel, and a real
  instrument-and-arranger question of its own.
- **Automatic pan re-spreading.** See the risk below; per-voice `pan`
  already overrides.
- **`[transform]`.** Still its own phase.

## Risks

- **Arpeggio pressure at three voices.** Every note the two dropped
  middles would have taken now falls through to the overflow, and lands
  on `counter` — a prominent voice with a pitch-envelope attack blip.
  It may simply sound busy. This is the audition's main question, and
  the honest fallback is `nes-tight` at 4 rather than 3.
- **A right-heavy image at count 3.** The surviving pans are −0.2,
  +0.45, and 0.0. `nes-tight` centres everything, so the preset masks
  it; a bare `count = 3` does not. Named rather than corrected, because
  silently rewriting pans the user did not set is worse than a lopsided
  default they can fix.
- **`Roster` versus `ROSTER`.** A type and a default instance differing
  only in case. Idiomatic Python, and the rename keeps every existing
  import working, but a misread of the two at a call site is a plausible
  mistake that the type checker will not always catch.

## What a later phase inherits

- A roster whose membership is data, which is what a noise voice would
  need.
- `.arp` as a derived property, so an overflow policy change has one
  place to live.
- `[transform]` and tail-wrapping, both still ahead.
