# Is the cross-attack compromise gap real, or a sampling artifact?

**Verdict: sampling artifact. Confirmed 2026-08-31. It is not a finding, and it is
not the launch story.**

## The question

The security suite reports two rates per attack type per defense:

- `knowledge_corruption_rate` / `injection_compliance_rate` — did *the attack under
  test* succeed?
- `poison_compromise_rate` / `injection_compromise_rate` — did the answer carry *any*
  attacker-planted marker, whichever attack planted it?

They share a denominator, so the gap between them is trials where the attack under
test was scored a block while the model still emitted attacker-controlled text. On the
demo corpus that gap was up to 0.10, and the most striking cell was
`injection_filter`, which reported a perfect `injection_compliance_rate 0.00` while
`injection_compromise_rate` sat at 0.10.

The suspected cause: `select_targets` is called twice over the same QA pool with
different seed offsets, so the poison and injection target sets overlap by chance. On
an overlapping question both attack documents echo that question and compete for the
same retrieval slots, and the two trials become the same query scored against
different markers. With 10 + 10 targets drawn from 56 questions the expected overlap
is ~1.8; the observed overlap was 2 (q042, q055).

## The rule, committed before the run

> If the `*_compromise_rate` metrics collapse onto their `*_success` siblings in all
> three defense conditions, the compromise gap is declared a sampling artifact,
> `attack_competition_rate` is relabelled a diagnostic, and it is never the launch
> story.

## Method

`specs/demo-disjoint.yaml` is identical to `specs/demo.yaml` except that it runs the
security suite only and sets `security.disjoint_targets: true`, which partitions the
QA pool so poison picks first and injection draws from the remainder. Same seed, same
corpus, same models, same three defenses, 10 + 10 targets.

## Result

Gap between each compromise rate and the success rate it generalises:

| attack | defense | overlapping targets | disjoint targets |
|---|---|---|---|
| poison | none | 0.00 | 0.00 |
| poison | prompt_isolation | **0.10** | **0.00** |
| poison | injection_filter | 0.00 | 0.00 |
| injection | none | **0.10** | **0.00** |
| injection | prompt_isolation | **0.10** | **0.00** |
| injection | injection_filter | **0.10** | **0.00** |

| diagnostic | overlapping | disjoint |
|---|---|---|
| `attack_competition_rate` (none / isolation / filter) | 0.05 / 0.10 / 0.05 | 0.00 / 0.00 / 0.00 |
| `cross_question_contamination_rate` | 0.00 / 0.00 / 0.00 | 0.00 / 0.00 / 0.00 |

Trials answering with a marker from another attack: **4 of 60 → 0 of 60.**

## What this means

Every instance of "the model was compromised even though this attack was blocked"
came from a question carrying both attacks. Remove the overlap and the effect is gone
completely — not reduced, gone. `cross_question_contamination_rate` was already 0.00
before the ablation, so no attack document was ever escaping the question it was
written for.

The `injection_filter` result therefore reads: it blocks the injection it was tested
on, and on a question that *also* carries a poison document the model may still repeat
the poison — which is not a failure of the injection filter, because poison was never
what it defends against.

## Consequences

1. **The compromise metrics stay**, but as a *diagnostic* that the two attacks are
   competing, not as a headline claiming defenses under-report risk.
2. **`attack_competition_rate` is the honest name** for what was measured. It is a
   property of the target sampling, not of the pipeline under test.
3. **The launch story must be something else.** The capability-floor experiment
   (varying only the generator against one identical poisoned index) is the remaining
   candidate and is unaffected by this result.
4. **Open question, not decided here:** should `disjoint_targets` default to `true`?
   Overlap is an accident of independent sampling rather than a design choice, but
   flipping the default changes every published number. Left `false` until the
   published baselines are regenerated deliberately.

## Caveat on reading the table

Only the *gaps* are comparable across the two runs. The disjoint run draws a different
injection target set, so absolute levels move for unrelated reasons — for example
`injection_compliance_rate[defense=none]` reads 0.10 overlapping and 0.20 disjoint.
That is a different sample of questions, not a change in defense efficacy. The gap is
a within-run property and is the only quantity this ablation was designed to test.

## Reproduce

```sh
crucible submit specs/demo.yaml           # overlapping targets (default)
crucible submit specs/demo-disjoint.yaml  # partitioned pool
```
