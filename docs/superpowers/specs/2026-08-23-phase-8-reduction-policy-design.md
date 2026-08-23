# Phase 8: reduction policy

Phase 7's re-audition of `count = 3` ended with a verdict and a diagnosis:
"better, still not musical," because "the defect is proportion, not pitch."
It left reduction policy as real work rather than a contingency, and named
its target as the share of the piece that overflows rather than how the
overflow sounds.

This phase decides **which notes survive reduction**, and it makes silence a
legitimate outcome for the first time.

## What the overflow actually is

Measured at `count = 3` on all three fixtures, before any change:

```
fixture   notes  overflow  share  onsets  redundant pitch class
chorale     144        36  25.0%      36                 41.7%
minuet      156        26  16.7%      26                 50.0%
ragtime     289        72  24.9%      40                 26.4%
```

The chorale is the clean case. 144 notes over four parts is 36 chords, and
**all 36 overflow** — that is the gap between "25% of the notes" and "92.2%
of the piece." A quarter of the notes land on every single chord, and in a
chorale each chord is held, so the carrier arpeggiates continuously.

The middle channel is not to blame. Its part purity at `count = 3`:

```
fixture   lead    counter          bass     overflow part
chorale  100.0%   85.4% (alto)   83.3%     35/36 tenor
minuet    95.6%   76.2%          83.7%     20/26 part 2
ragtime   89.5%   65.2%          98.1%     72/72 left hand
```

At `count = 3` there is exactly one middle channel, so `_pick_middle` never
has a choice: the higher inner note is placed and the lower one always
overflows. The chorale's reduction is already a clean soprano-alto-bass; the
tenor consistently drops out. Line consistency is not the problem, and
ragtime's 65% is not a line problem either — its "parts" are hands playing
stride chords, so part purity is not a meaningful measure there.

## The defect, in one sentence

Overflow is unconditional: any note without a free channel becomes arpeggio,
however little it contributes, and one note joining the carrier's own note
makes a **two-member cycle** — a trill, not an arpeggio.

The cycle sizes say so outright:

```
fixture   arp events  members          arp share  2-member share
chorale           36  36x2                 92.2%           92.2%
minuet            26  25x2, 1x1            66.7%           64.1%
ragtime           40  20x2, 19x3, 1x4      59.8%           27.2%
```

Every point of the chorale's 92.2% is a two-member cycle. Phase 7 established
why those are wrong — a chip arpeggio names a chord by cycling its members,
and two notes name nothing. Phase 7 fixed the rate and span of these cycles.
It never asked whether they should exist.

This also exposes a latent bug: the minuet carries a **one-member** cycle, a
lone pitch flagged `arp`, which suppresses its vibrato for no reason.

## The policy

Three rules, applied to each overflow group in order.

1. **Redundancy.** An overflow note whose pitch class is already sounding is
   dropped. It adds nothing the ear can hear. "Sounding" means held or struck
   at that onset on any channel, the carrier included — a note is judged
   against the texture as it will actually be heard, not against the score.

2. **Chord.** What survives becomes a cycle only if it has **three or more
   distinct pitches**, counted after the octave fold and including the
   carrier's own note at that onset, which the cycle absorbs. One or two is a
   trill; the overflow is dropped and the carrier keeps its plain note. This
   subsumes the one-member bug.

3. **Third rescue.** Where rule 2 would discard the chord's *only* third and
   the carrier's own note is a redundant doubling, the third **displaces**
   that doubling rather than being dropped. Harmony survives; the line moves
   once. "Only third" means no other channel sounds a third or tenth above
   the bass at that onset, counting arpeggio members; "redundant doubling"
   means the carrier's own pitch class is already sounding on some other
   channel, so replacing it loses nothing.

Rule 3 exists because rules 1 and 2 choose what to keep by pitch height —
alto over tenor — and never by harmonic function, so the third is lost
whenever the tenor happens to hold it.

**Note (post-implementation):** rule 3's "counting arpeggio members" above
is aspirational, not what ships. `sounding` and `others` are computed once
per onset from the texture `_assign` left behind, before the policy runs on
any overflow group; a `Displace` or `Cycle` decided at an earlier onset is
never folded back in when a later onset is judged. This is deliberate —
`_arpeggiate`'s docstring in `arrange.py` says so — because it keeps every
onset's verdict independent of the order overflow onsets happen to be
processed in. The cost is that a third rescued by rule 3 at one onset does
not count as "already sounding" for a rule 1 or rule 3 decision at the next
onset, even though by then it audibly is.

## Measured outcome

Prototyped end to end before this spec was written, not projected:

```
fixture   count   arp share now   after
chorale       3           92.2%    0.0%
minuet        3           66.7%    0.0%
ragtime       3           59.8%   26.1%
ragtime       4           41.5%    2.1%   <- the nes-tight preset
ragtime       5           15.6%    2.1%   <- DEFAULTS, and the goldens
```

Every surviving ragtime cycle at `count = 3` is a 3- or 4-member chord: the
idiom working as intended. The chorale and the minuet stop arpeggiating
entirely, which is what a three-voice reduction of four-part writing should
do.

### What it costs

Dropping notes loses harmony, and the current implementation loses none —
it keeps every note, so this cost is entirely new. Measured as chords that
had a third and end up without one:

```
fixture   count   current   rules 1-2   + rule 3   swaps
chorale       3    0 / 34      9 / 34     7 / 34       2
minuet        3    0 / 15      3 / 15     0 / 15       3
ragtime       3    0 / 20      7 / 20     4 / 20       3
ragtime       4    0 / 16     14 / 16     5 / 16       9
ragtime       5     0 / 7       7 / 7      0 / 7       7
```

Rule 3 costs **nothing** in arp share — the figures above are unchanged by
it — and clears most of the harmonic loss for between two and nine line
movements per fixture. The residue is chords where the carrier's own note
was not redundant either, so no swap is free.

An alternative was measured and rejected: protecting every only-third by
keeping its two-member cycle. It zeroes the hollow count on every fixture,
but it does so by preserving the exact defect this phase exists to remove —
ragtime at `count = 4` lands on 28.7% arpeggio against rule 3's 2.1%, and
fourteen of those cycles are two-member trills. Rule 3 buys the same
harmonic protection and reintroduces no trills at all.

## Scope

In:

- The three rules above, in `arrange`'s overflow path.
- New quality metrics: arp duration share and hollow-chord count, per
  fixture and per count.
- Refreshed goldens and quality baselines.

Out:

- `_pick_middle` and voice assignment. The measurements show line
  consistency is not the defect; changing assignment would move every
  fixture's arrangement for no diagnosed gain.
- Any share threshold or budget. The rules are categorical — a note either
  earns its place or does not — and no tuned ceiling appears anywhere.

## Structure

`arrange.py` is 309 lines and `_arpeggiate` already carries three paragraphs
of rationale. *Which notes survive reduction* is a separable decision from
*how a cycle is built*, so the policy moves to a new `reduce.py` that
`_arpeggiate` calls. Run the `design-patterns` dialog on that boundary
before writing it.

## Testing

Metrics go in `test_quality.py` beside the existing purity and leap
baselines, which is where a regression in the reduction is already caught.

Both new metrics must be proven the same way every test in this repo is:
break the implementation deliberately, watch the test fail, restore. A test
that passes the coarser implementation is not a test. Specifically, the
chord-rule test must fail an implementation that admits two-member cycles,
and the rescue test must fail one that drops the only third.

Goldens will change on every fixture. Review the diffs against the numbers
in this spec rather than regenerating and accepting.

## Risks

**The shipped presets change.** Ragtime's arpeggios fall from 41.5% to 2.1%
at `count = 4`, the `nes-tight` preset, and from 15.6% to 2.1% at `DEFAULTS`
— sound Phase 7 auditioned and accepted. This phase needs a re-audition of
both, not only of `count = 3`. If the default
loses something the stride idiom wants, rule 2's three-member threshold is
where to negotiate; nothing else in the policy is tunable by design.

**Hollow chords are a new class of defect.** Seven on the chorale and five
on ragtime at the default survive rule 3. They have never existed in this
pipeline before, so no audition has ever judged them. The metric exists so
the cost stays visible rather than assumed.

**Metric definition.** "Arp share" here is arpeggiated duration as a
fraction of the carrier channel's sounding duration. Phase 7's re-audition
quoted 30.5% for ragtime at `count = 4` where this spec measures 41.5%; the
two are not the same measure. The metric added in this phase is the
definition that should be quoted from here on.

## Outcome (2026-08-23)

The policy is implemented and `tests/test_quality.py` enforces the numbers
below as ceilings on every fixture and count. This is a measurement record,
not an audition — nothing in this section has been listened to.

Arp share, the unconditional-overflow behaviour this phase replaces against
the three-rule policy:

| fixture | count | before | after |
|---|---|---|---|
| chorale | 3 | 92.2% | 0.0% |
| minuet | 3 | 66.7% | 0.0% |
| ragtime | 3 | 59.8% | 26.1% |
| ragtime | 4 | 41.5% | 2.1% |
| ragtime | 5 | 15.6% | 2.1% |

Hollow chords — chords that had a third and end up without one, a cost the
previous implementation never paid, because it dropped nothing:

| fixture | count | hollow |
|---|---|---|
| chorale | 3 | 7 |
| minuet | 3 | 0 |
| ragtime | 3 | 4 |
| ragtime | 4 | 5 |
| ragtime | 5 | 0 |

**The audition is outstanding.** Two renders Phase 7 already auditioned and
accepted now sound different, and a table of ceilings is not permission to
assume the change is an improvement:

- `nes-tight` (`count = 4`) on ragtime, arpeggio 41.5% to 2.1%.
- `DEFAULTS` (`count = 5`) on ragtime, arpeggio 15.6% to 2.1%.

Both need to be rendered as WAV and listened to — `aplay` renders Ogg as
static — because the sound Phase 7 signed off on is not the sound this
phase ships. Separately, `count = 3` on the chorale and the minuet, the
arrangement Phase 6 rejected and Phase 7's re-audition called "better,
still not musical," now arpeggiates not at all on both. Whether a
three-voice chorale and minuet with no arpeggio sound reduced or sound thin
is a question the share numbers cannot answer. `nes-tight` stays at
`count = 4` until an audition says otherwise; this record is measurement,
not that audition.
