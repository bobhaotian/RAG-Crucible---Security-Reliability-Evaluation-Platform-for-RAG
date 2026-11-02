// The dashboard's rules for metrics that were not measured, tested on the pure
// selectors in src/metrics.ts (compiled by `npm test`; see tsconfig.test.json).
// Every panel renders from these, so each rule here is one a panel relies on:
// a null is never drawn as 0, never inverted to 1, and never feeds a delta.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  PROBE_STYLE_HEADING,
  breakdown,
  canariesRedactedAtIngest,
  contamination,
  defenseGroups,
  diffRows,
  formatMetric,
  formatReading,
  groupSubsets,
  groupUnmeasured,
  isCount,
  judgeGap,
  kpis,
  read,
  rerankLift,
  subsetLine,
  subsetShort,
  subsettedOf,
  suiteNotices,
  suitesLine,
  summaryMarkdown,
  tradeoffRadar,
  unmeasuredOf,
  worstOf,
} from "../.test-build/metrics.js";

const m = (suite, name, variant, value) => ({
  suite,
  name,
  variant,
  value,
  state: "measured",
  reason: null,
});
const nm = (suite, name, variant, state = "unsupported", reason = `why ${name}`) => ({
  suite,
  name,
  variant,
  value: null,
  state,
  reason,
});
// A measured metric scored over `n` units with `excluded` left out.
const sub = (suite, name, variant, value, n, excluded) => ({
  ...m(suite, name, variant, value),
  n,
  n_excluded: excluded,
});
const suite = (name, status, error = null) => ({
  suite: name,
  status,
  error,
  metric_count: 0,
  record_count: 0,
});
const run = (...metrics) => ({
  run: {
    id: "01TEST",
    name: "t",
    spec_hash: "0123456789abcdef",
    status: "succeeded",
    error: null,
    claimed_by: null,
    created_at: "2026-10-18T00:00:00Z",
    started_at: null,
    finished_at: null,
  },
  suites: [],
  metrics,
  stage_stats: [],
});

describe("read and formatReading", () => {
  test("a measured zero is a number; a null is its state; absent is a dash", () => {
    assert.equal(formatReading(read(m("s", "a", "", 0))), "0.000");
    assert.equal(formatReading(read(nm("s", "a", "", "error"))), "— (error)");
    assert.equal(formatReading(undefined), "—");
  });

  test("a response from before states existed reads as measured", () => {
    const old = { suite: "s", name: "a", variant: "", value: 0.5 };
    assert.deepEqual(read(old), { measured: true, value: 0.5 });
  });

  test("contract breaks are named, not passed off as known states", () => {
    assert.deepEqual(read(nm("s", "a", "", "skipped", null)), {
      measured: false,
      state: "skipped",
      reason: "no reason given",
    });
    const unknown = read(nm("s", "a", "", "bogus", "x"));
    assert.equal(unknown.state, "unrecognised");
    assert.match(unknown.reason, /unrecognised state "bogus": x/);
    const empty = read({ ...m("s", "a", "", 0), value: null });
    assert.equal(empty.state, "invalid");
    assert.doesNotMatch(read(nm("s", "a", "", "error", null)).reason, /measured/);
  });
});

describe("rerank lift", () => {
  test("a missing rerank-on side is not a zero lift and does not borrow the off value", () => {
    const { rows, hasOn } = rerankLift(
      run(
        m("retrieval", "mrr", "rerank=off", 0.5),
        m("retrieval", "recall@1", "rerank=off", 0.4),
        m("retrieval", "recall@1", "rerank=on", 0.6),
      ),
    );
    const mrr = rows.find((r) => r.name === "mrr");
    assert.equal(mrr.on, undefined);
    assert.equal(mrr.delta, undefined);
    assert.equal(hasOn, true);
  });

  test("an unmeasured side gives no delta", () => {
    const { rows } = rerankLift(
      run(m("retrieval", "mrr", "rerank=off", 0.5), nm("retrieval", "mrr", "rerank=on", "error")),
    );
    assert.equal(rows[0].on.measured, false);
    assert.equal(rows[0].delta, undefined);
  });

  test("a run with no rerank-on figures says so; one with nothing measured has no axis", () => {
    const offOnly = rerankLift(run(m("retrieval", "mrr", "rerank=off", 0.5)));
    assert.equal(offOnly.hasOn, false);
    assert.notEqual(offOnly.axis, undefined);
    const nothing = rerankLift(
      run(nm("retrieval", "mrr", "rerank=off"), nm("retrieval", "mrr", "rerank=on")),
    );
    assert.equal(nothing.axis, undefined);
  });

  test("rows with no lift sort after rows that moved", () => {
    const { rows } = rerankLift(
      run(
        m("retrieval", "ndcg@3", "rerank=off", 0.5),
        nm("retrieval", "ndcg@3", "rerank=on", "error"),
        m("retrieval", "ndcg@7", "rerank=off", 0.5),
        m("retrieval", "ndcg@7", "rerank=on", 0.51),
      ),
    );
    assert.deepEqual(
      rows.map((r) => r.name),
      ["ndcg@7", "ndcg@3"],
    );
  });
});

describe("trade-off radar", () => {
  const base = [
    m("retrieval", "ndcg@10", "rerank=on", 0.8),
    m("faithfulness", "groundedness", "", 0.7),
    m("security", "knowledge_corruption_rate", "defense=none", 0.2),
    m("security", "injection_compliance_rate", "defense=none", 0.1),
  ];

  test("an unmeasured axis is left off and listed, never 0 and never inverted to 1", () => {
    const { data, unmeasured } = tradeoffRadar(
      run(...base, nm("privacy", "leakage_rate", "defense=none", "not_estimable")),
    );
    assert.deepEqual(
      data.map((d) => d.name),
      ["Retrieval", "Faithfulness", "Robustness"],
    );
    assert.deepEqual(
      unmeasured.map((u) => [u.label, u.state]),
      [["Privacy", "not_estimable"]],
    );
  });

  test("robustness is unknown when either attack rate was not measured", () => {
    const { data } = tradeoffRadar(
      run(
        ...base.slice(0, 3),
        nm("security", "injection_compliance_rate", "defense=none", "skipped"),
      ),
    );
    assert.equal(
      data.find((d) => d.name === "Robustness"),
      undefined,
    );
  });

  test("an inapplicable rerank-off nDCG gives way to a measured MRR", () => {
    const { data } = tradeoffRadar(
      run(
        nm("retrieval", "ndcg@10", "rerank=off", "inapplicable", "no cutoff of 10"),
        m("retrieval", "mrr", "rerank=off", 0.42),
        ...base.slice(1),
      ),
    );
    assert.equal(data.find((d) => d.name === "Retrieval").value, 0.42);
  });

  test("an axis whose every input is inapplicable is listed, never dropped silently", () => {
    const allOut = tradeoffRadar(
      run(
        nm("retrieval", "ndcg@10", "rerank=on", "inapplicable", "no reranker"),
        nm("retrieval", "ndcg@10", "rerank=off", "inapplicable", "no cutoff"),
        nm("faithfulness", "groundedness", "", "not_estimable"),
        nm("security", "knowledge_corruption_rate", "defense=none", "inapplicable"),
        nm("security", "injection_compliance_rate", "defense=none", "inapplicable"),
        nm("privacy", "leakage_rate", "defense=none", "not_estimable"),
      ),
    );
    assert.deepEqual(allOut.data, []);
    assert.deepEqual(
      allOut.unmeasured.map((u) => [u.label, u.state]),
      [
        ["Retrieval", "inapplicable"],
        ["Faithfulness", "not_estimable"],
        ["Robustness", "inapplicable"],
        ["Privacy", "not_estimable"],
      ],
    );
    const offOnly = tradeoffRadar(
      run(nm("retrieval", "ndcg@10", "rerank=off", "inapplicable", "no cutoff"), ...base.slice(1)),
    );
    assert.deepEqual(
      offOnly.unmeasured.map((u) => u.label),
      ["Retrieval"],
    );
  });

  test("an inapplicable rerank-on axis falls back to the measured rerank-off value", () => {
    const { data } = tradeoffRadar(
      run(
        nm("retrieval", "ndcg@10", "rerank=on", "inapplicable", "no reranker configured"),
        m("retrieval", "ndcg@10", "rerank=off", 0.6),
        ...base.slice(1),
      ),
    );
    assert.equal(data.find((d) => d.name === "Retrieval").value, 0.6);
  });
});

describe("KPI cards", () => {
  test("unmeasured cards carry their state and reason, never a value", () => {
    const cards = kpis(
      run(
        nm("retrieval", "ndcg@10", "rerank=on", "unsupported", "no labels"),
        nm("faithfulness", "answer_accuracy", "", "error", "judge failed"),
        nm("privacy", "leakage_rate", "defense=none", "not_estimable", "no canaries"),
      ),
    );
    assert.deepEqual(
      cards.map((k) => [k.key, k.reading]),
      [
        ["retrieval", { measured: false, state: "unsupported", reason: "no labels" }],
        ["faithfulness", { measured: false, state: "error", reason: "judge failed" }],
        ["privacy", { measured: false, state: "not_estimable", reason: "no canaries" }],
      ],
    );
  });

  test("the worst case is unknown when one attack was not measured", () => {
    const [card] = kpis(
      run(
        m("security", "knowledge_corruption_rate", "defense=none", 0.3),
        nm("security", "injection_compliance_rate", "defense=none", "error", "generator failed"),
      ),
    );
    assert.equal(card.reading.measured, false);
    assert.equal(card.reading.reason, "injection_compliance_rate: generator failed");
  });

  test("an inapplicable attack carries no weight in the worst case", () => {
    const [card] = kpis(
      run(
        m("security", "knowledge_corruption_rate", "defense=none", 0.3),
        nm("security", "injection_compliance_rate", "defense=none", "inapplicable", "no injection"),
      ),
    );
    assert.deepEqual(card.reading, { measured: true, value: 0.3 });
  });

  test("when every attack is inapplicable, so is the worst case: shown, not dropped", () => {
    const cards = kpis(
      run(
        nm("security", "knowledge_corruption_rate", "defense=none", "inapplicable", "no poison"),
        nm("security", "injection_compliance_rate", "defense=none", "inapplicable", "no injection"),
      ),
    );
    assert.deepEqual(
      cards.map((k) => [k.key, k.reading]),
      [
        [
          "security",
          {
            measured: false,
            state: "inapplicable",
            reason: "knowledge_corruption_rate: no poison; injection_compliance_rate: no injection",
          },
        ],
      ],
    );
    assert.equal(worstOf([["a", read(nm("s", "a", "", "inapplicable"))]]).state, "inapplicable");
  });

  test("when every retrieval figure is inapplicable, the card stays and says so", () => {
    const both = kpis(
      run(
        nm("retrieval", "ndcg@10", "rerank=on", "inapplicable", "no reranker configured"),
        nm("retrieval", "ndcg@10", "rerank=off", "inapplicable", "retrieval not run"),
      ),
    );
    assert.deepEqual(both[0].reading, {
      measured: false,
      state: "inapplicable",
      reason: "no reranker configured",
    });
    assert.equal(both[0].detail, "nDCG@10, rerank on");
    const offOnly = kpis(run(nm("retrieval", "ndcg@10", "rerank=off", "inapplicable", "x")));
    assert.equal(offOnly[0].reading.state, "inapplicable");
    assert.equal(offOnly[0].detail, "nDCG@10, rerank off");
  });

  test("an inapplicable rerank-on figure shows the measured rerank-off value, labelled as such", () => {
    const [card] = kpis(
      run(
        nm("retrieval", "ndcg@10", "rerank=on", "inapplicable", "no reranker configured"),
        m("retrieval", "ndcg@10", "rerank=off", 0.6),
      ),
    );
    assert.deepEqual(card.reading, { measured: true, value: 0.6 });
    assert.equal(card.detail, "nDCG@10, rerank off");
  });

  test("an unsupported rerank-on figure is shown as unsupported, not swapped for rerank off", () => {
    const [card] = kpis(
      run(nm("retrieval", "ndcg@10", "rerank=on"), m("retrieval", "ndcg@10", "rerank=off", 0.6)),
    );
    assert.equal(card.reading.measured, false);
  });
});

describe("defense deltas", () => {
  test("an unmeasured baseline gives no delta and no tone", () => {
    const [group] = defenseGroups(
      run(
        nm("security", "knowledge_corruption_rate", "defense=none", "error"),
        m("security", "knowledge_corruption_rate", "defense=prompt_isolation", 0.0),
      ),
      "security",
    );
    const arm = group.bars.find((b) => b.defense === "prompt_isolation");
    assert.equal(arm.delta, undefined);
    assert.equal(arm.tone, "neutral");
    assert.equal(group.bars.find((b) => b.isBaseline).reading.measured, false);
  });

  test("an unmeasured arm gives no delta against a measured baseline", () => {
    const [group] = defenseGroups(
      run(
        m("security", "knowledge_corruption_rate", "defense=none", 0.4),
        nm("security", "knowledge_corruption_rate", "defense=prompt_isolation", "error"),
      ),
      "security",
    );
    assert.equal(group.bars[1].delta, undefined);
  });
});

describe("two-run diff", () => {
  test("a delta needs both runs to have measured the metric", () => {
    const rows = diffRows(
      run(m("s", "a", "", 0.5), nm("s", "b", "", "error")),
      run(m("s", "a", "", 0.75), m("s", "b", "", 0.25)),
    );
    assert.deepEqual(
      rows.map((r) => [r.key, r.delta]),
      [
        ["s · a", 0.25],
        ["s · b", undefined],
      ],
    );
  });
});

describe("cross-question contamination callout", () => {
  const groupsOf = (...metrics) =>
    defenseGroups(run(...metrics), "security", {
      only: ["attack_competition_rate", "cross_question_contamination_rate"],
    });
  const competition = ["none", "prompt_isolation"].map((d) =>
    m("security", "attack_competition_rate", `defense=${d}`, 0.2),
  );

  test("an unmeasured contamination rate is not evidence that nothing escaped", () => {
    const groups = groupsOf(
      ...competition,
      nm("security", "cross_question_contamination_rate", "defense=none", "not_estimable"),
      nm("security", "cross_question_contamination_rate", "defense=prompt_isolation", "error"),
    );
    assert.equal(contamination(groups), undefined);
  });

  test("an absent rate, or one missing in an arm, says nothing either", () => {
    assert.equal(contamination(groupsOf(...competition)), undefined);
    const oneArm = groupsOf(
      ...competition,
      m("security", "cross_question_contamination_rate", "defense=none", 0),
    );
    assert.equal(contamination(oneArm), undefined);
  });

  test("every arm measured at zero, with competition, is contained", () => {
    const groups = groupsOf(
      ...competition,
      m("security", "cross_question_contamination_rate", "defense=none", 0),
      m("security", "cross_question_contamination_rate", "defense=prompt_isolation", 0),
    );
    assert.deepEqual(contamination(groups), { kind: "contained" });
  });

  test("every arm measured at zero, with no competition to explain, says nothing", () => {
    const quiet = ["none", "prompt_isolation"].map((d) =>
      m("security", "attack_competition_rate", `defense=${d}`, 0),
    );
    const groups = groupsOf(
      ...quiet,
      m("security", "cross_question_contamination_rate", "defense=none", 0),
      m("security", "cross_question_contamination_rate", "defense=prompt_isolation", 0),
    );
    assert.equal(contamination(groups), undefined);
  });

  test("one measured arm above zero is escaping, whatever the others are", () => {
    const groups = groupsOf(
      ...competition,
      m("security", "cross_question_contamination_rate", "defense=none", 0.25),
      nm("security", "cross_question_contamination_rate", "defense=prompt_isolation", "error"),
    );
    assert.deepEqual(contamination(groups), {
      kind: "escaping",
      arms: [{ defense: "none", value: 0.25 }],
    });
  });
});

describe("not-measured lists and the markdown summary", () => {
  test("a suite unsupported as a whole is one line, not one per metric", () => {
    const metrics = ["recall@1", "recall@5", "mrr"].flatMap((name) =>
      ["rerank=off", "rerank=on"].map((v) => nm("retrieval", name, v, "unsupported", "no labels")),
    );
    const groups = groupUnmeasured(unmeasuredOf(metrics));
    assert.equal(groups.length, 1);
    assert.equal(groups[0].labels.length, 6);
  });

  test("the copied summary gives the state and reason, with pipes escaped", () => {
    const md = summaryMarkdown(run(nm("retrieval", "mrr", "rerank=on", "error", "a | b")));
    assert.match(md, /\| retrieval \| mrr \| rerank=on \| — \(error: a \\\| b\) \|/);
  });

  test("the copied summary escapes a reason as summary.md does", () => {
    const reason = "said **no** <b>x</b> [see](http://e.x) `code` & co_op ~~gone~~ \\ end";
    const md = summaryMarkdown(run(nm("faithfulness", "groundedness", "", "error", reason)));
    assert.ok(
      md.includes(
        "— (error: said \\*\\*no\\*\\* \\<b\\>x\\</b\\> \\[see\\](http://e.x) " +
          "\\`code\\` \\& co\\_op \\~\\~gone\\~\\~ \\\\ end)",
      ),
      md,
    );
  });

  test("different reasons under one state stay on separate lines", () => {
    const groups = groupUnmeasured(
      unmeasuredOf([
        nm("retrieval", "mrr", "rerank=off", "unsupported", "no labels"),
        nm("retrieval", "mrr", "rerank=on", "unsupported", "no reranker labels"),
        nm("retrieval", "recall@1", "rerank=off", "unsupported", "no labels"),
      ]),
    );
    assert.deepEqual(
      groups.map((g) => [g.reason, g.labels]),
      [
        ["no labels", ["mrr [rerank=off]", "recall@1 [rerank=off]"]],
        ["no reranker labels", ["mrr [rerank=on]"]],
      ],
    );
  });

  test("a probe-style leakage rate that was not measured is not drawn as 0.00", () => {
    const rows = breakdown(
      run(m("privacy", "leakage_rate@direct", "", 0), nm("privacy", "leakage_rate@indirect", "")),
      "privacy",
      "leakage_rate",
    );
    assert.deepEqual(
      rows.map((r) => [r.name, r.reading.measured]),
      [
        ["direct", true],
        ["indirect", false],
      ],
    );
  });

  test("the judge gap needs both figures measured", () => {
    assert.equal(
      judgeGap(
        run(m("faithfulness", "answer_accuracy", "", 0.9), nm("faithfulness", "groundedness", "")),
      ),
      undefined,
    );
  });
});

describe("values scored over a subset", () => {
  test("a reading carries its subset only when a measured value excluded something", () => {
    assert.deepEqual(read(sub("r", "mrr", "", 0.9, 53, 3)), {
      measured: true,
      value: 0.9,
      subset: { n: 53, excluded: 3 },
    });
    assert.deepEqual(read(sub("r", "mrr", "", 0.9, 56, 0)), { measured: true, value: 0.9 });
    assert.deepEqual(read(sub("r", "mrr", "", 0.9, null, null)), { measured: true, value: 0.9 });
    assert.deepEqual(read(m("r", "mrr", "", 0.9)), { measured: true, value: 0.9 }); // older server
    const empty = read({ ...nm("r", "mrr", "", "unsupported", "no labels"), n: 0, n_excluded: 56 });
    assert.equal(empty.measured, false);
    assert.equal("subset" in empty, false);
  });

  test("an excluded count with no recorded denominator says so; nonsense counts are ignored", () => {
    const r = read(sub("r", "mrr", "", 0.9, null, 3));
    assert.deepEqual(r.subset, { n: undefined, excluded: 3 });
    assert.equal(subsetShort(r.subset), "3 excluded");
    assert.equal(subsetShort({ n: 53, excluded: 3 }), "53 of 56");
    assert.equal("subset" in read(sub("r", "mrr", "", 0.9, 53, -1)), false);
    assert.equal("subset" in read(sub("r", "mrr", "", 0.9, 53, 1.5)), false);
  });

  test("a panel's subset footnote is one line per distinct denominator", () => {
    const groups = groupSubsets(
      subsettedOf([
        sub("retrieval", "recall@1", "rerank=off", 0.5, 53, 3),
        sub("retrieval", "mrr", "rerank=off", 0.6, 53, 3),
        sub("retrieval", "mrr", "rerank=on", 0.7, 50, 6),
        m("retrieval", "ndcg@10", "rerank=off", 0.8),
      ]),
    );
    assert.deepEqual(
      groups.map((g) => [g.labels, subsetLine(g)]),
      [
        [["recall@1 [rerank=off]", "mrr [rerank=off]"], "scored over 53; 3 excluded"],
        [["mrr [rerank=on]"], "scored over 50; 6 excluded"],
      ],
    );
    assert.match(subsetLine({ n: undefined, excluded: 2 }), /not recorded/);
    // Same number excluded, different denominators: still two lines.
    const sameExcluded = groupSubsets(
      subsettedOf([sub("s", "a", "", 0.5, 53, 3), sub("s", "b", "", 0.5, 40, 3)]),
    );
    assert.equal(sameExcluded.length, 2);
  });

  test("the KPI card says a subset figure is one, and the worst case keeps its input's subset", () => {
    const cards = kpis(
      run(
        sub("retrieval", "ndcg@10", "rerank=on", 0.8, 53, 3),
        sub("security", "knowledge_corruption_rate", "defense=none", 0.4, 8, 2),
        m("security", "injection_compliance_rate", "defense=none", 0.1),
        sub("privacy", "leakage_rate", "defense=none", 0.2, 20, 7),
      ),
    );
    const detail = Object.fromEntries(cards.map((k) => [k.key, k.detail]));
    assert.equal(detail.retrieval, "nDCG@10, rerank on · 53 of 56");
    assert.equal(detail.security, "poison vs injection, no defense · 8 of 10");
    assert.equal(detail.privacy, "none arm · 20 of 27");
    const worst = worstOf([
      ["a", read(m("s", "a", "", 0.1))],
      ["b", read(sub("s", "b", "", 0.3, 9, 1))],
    ]);
    assert.deepEqual(worst, { measured: true, value: 0.3, subset: { n: 9, excluded: 1 } });
  });

  test("radar, rerank lift and defense bars carry the subset to their panels", () => {
    const radar = tradeoffRadar(
      run(
        sub("retrieval", "ndcg@10", "rerank=on", 0.8, 53, 3),
        m("faithfulness", "groundedness", "", 0.7),
        m("security", "knowledge_corruption_rate", "defense=none", 0.2),
        m("privacy", "leakage_rate", "defense=none", 0.1),
      ),
    );
    assert.deepEqual(
      radar.subsets.map((x) => x.label),
      ["Retrieval"],
    );
    // An inverted axis is still scored over its input's subset.
    const inverted = tradeoffRadar(
      run(
        m("retrieval", "ndcg@10", "rerank=on", 0.8),
        m("faithfulness", "groundedness", "", 0.7),
        sub("security", "knowledge_corruption_rate", "defense=none", 0.2, 8, 2),
        sub("privacy", "leakage_rate", "defense=none", 0.1, 20, 7),
      ),
    );
    assert.deepEqual(
      inverted.subsets.map((x) => [x.label, subsetShort(x.subset)]),
      [
        ["Robustness", "8 of 10"],
        ["Privacy", "20 of 27"],
      ],
    );
    const lift = rerankLift(
      run(sub("retrieval", "mrr", "rerank=off", 0.5, 53, 3), sub("retrieval", "mrr", "rerank=on", 0.6, 53, 3)),
    );
    assert.equal(lift.subsets.length, 2);
    const [group] = defenseGroups(
      run(sub("security", "knowledge_corruption_rate", "defense=none", 0.4, 8, 2)),
      "security",
    );
    assert.deepEqual(group.bars[0].reading.subset, { n: 8, excluded: 2 });
  });

  test("the copied summary marks a subset score", () => {
    const md = summaryMarkdown(run(sub("retrieval", "mrr", "rerank=on", 0.94339, 53, 3)));
    assert.match(md, /\| retrieval \| mrr \| rerank=on \| 0\.9434 \(53 of 56\) \|/);
    const full = summaryMarkdown(run(sub("retrieval", "mrr", "rerank=on", 0.9, 56, 0)));
    assert.match(full, /\| 0\.9000 \|/);
  });
});

describe("compare view denominators", () => {
  test("a delta over different denominators is flagged; unknown or equal ones are not", () => {
    const rows = diffRows(
      run(
        sub("s", "a", "", 0.5, 53, 3),
        sub("s", "b", "", 0.5, 56, 0),
        m("s", "c", "", 0.5),
      ),
      run(
        sub("s", "a", "", 0.6, 56, 0),
        sub("s", "b", "", 0.6, 56, 0),
        sub("s", "c", "", 0.6, 40, 0),
      ),
    );
    assert.deepEqual(
      rows.map((r) => [r.key, r.nDiffers, r.n]),
      [
        ["s · a", true, [53, 56]],
        ["s · b", false, [56, 56]],
        ["s · c", false, [undefined, 40]],
      ],
    );
  });
});

describe("suite status", () => {
  test("a failed suite is a notice with its error; a skipped one with its grouped reasons", () => {
    const results = {
      ...run(
        ...["recall@1", "mrr"].flatMap((name) =>
          ["rerank=off", "rerank=on"].map((v) => ({
            ...nm("retrieval", name, v, "unsupported", "no question carries a retrieval label"),
            n: 0,
            n_excluded: 56,
          })),
        ),
        m("security", "knowledge_corruption_rate", "defense=none", 0.2),
      ),
      suites: [
        suite("retrieval", "skipped"),
        suite("faithfulness", "failed", "ValueError: judge returned nothing"),
        suite("security", "succeeded"),
        suite("privacy", "cancelled"),
      ],
    };
    const notices = suiteNotices(results);
    assert.deepEqual(
      notices.map((n) => [n.suite, n.status, n.error, n.reasons.map((g) => [g.state, g.labels.length])]),
      [
        ["retrieval", "skipped", undefined, [["unsupported", 4]]],
        ["faithfulness", "failed", "ValueError: judge returned nothing", []],
      ],
    );
    assert.equal(
      suitesLine(results.suites),
      "retrieval (skipped) · faithfulness (failed) · security · privacy (cancelled)",
    );
    const md = summaryMarkdown(results);
    assert.match(md, /- retrieval: skipped\n/);
    assert.match(md, /- faithfulness: failed \(ValueError: judge returned nothing\)/);
  });

  test("a failed suite with a blank error is still a notice, with no error text", () => {
    const [notice] = suiteNotices({ ...run(), suites: [suite("faithfulness", "failed", "  ")] });
    assert.equal(notice.error, undefined);
  });

  test("a run whose suites all succeeded has no notices, and its header and summary are unchanged", () => {
    const results = { ...run(m("s", "a", "", 0.5)), suites: [suite("security", "succeeded")] };
    assert.deepEqual(suiteNotices(results), []);
    assert.equal(suitesLine(results.suites), "security");
    assert.doesNotMatch(summaryMarkdown(results), /- security:/);
  });
});

describe("counts", () => {
  const dropped = (value, variant = "") => m("privacy", "canary_docs_dropped_by_filter", variant, value);

  test("a count is written as an integer, a rate with its digits", () => {
    assert.equal(isCount("canary_docs_dropped_by_filter"), true);
    assert.equal(formatMetric(dropped(2)), "2");
    assert.equal(formatMetric(m("privacy", "leakage_rate", "defense=none", 0.25), 2), "0.25");
    assert.equal(formatMetric(nm("privacy", "canary_docs_dropped_by_filter", "", "error")), "— (error)");
    const md = summaryMarkdown(run(dropped(2)));
    assert.match(md, /\| privacy \| canary_docs_dropped_by_filter \| — \| 2 \|/);
  });

  test("a count is never a bar, even with a defense variant or a probe-style name", () => {
    const groups = defenseGroups(
      run(dropped(3, "defense=none"), m("privacy", "leakage_rate", "defense=none", 0.2)),
      "privacy",
    );
    assert.deepEqual(
      groups.map((g) => g.metric),
      ["leakage_rate"],
    );
    const rows = breakdown(
      run(m("privacy", "canary_docs_dropped_by_filter@direct", "", 1)),
      "privacy",
      "canary_docs_dropped_by_filter",
    );
    assert.deepEqual(rows, []);
    assert.equal(isCount("canary_docs_dropped_by_filter@direct"), true);
    assert.equal(isCount("leakage_rate@direct"), false);
  });

  test("in the compare view a count's change is neither good nor bad", () => {
    const [row] = diffRows(run(dropped(0)), run(dropped(2)));
    assert.equal(row.count, true);
    assert.equal(row.delta, 2);
  });
});

describe("privacy labels name the arm, and the pii caveat is keyed on the run", () => {
  test("the probe-style heading and the KPI no longer claim there was no redaction", () => {
    assert.doesNotMatch(PROBE_STYLE_HEADING, /no redaction/);
    assert.match(PROBE_STYLE_HEADING, /none arm/);
    const [card] = kpis(run(m("privacy", "leakage_rate", "defense=none", 0.2)));
    assert.equal(card.detail, "none arm");
  });

  test("the caveat needs this code's drop count and `pii` in the spec's ingest filters", () => {
    const withCount = run(m("privacy", "canary_docs_dropped_by_filter", "", 0));
    const pii = { ingest: { filters: ["dedup", "pii"] } };
    assert.equal(canariesRedactedAtIngest(withCount, pii), true);
    assert.equal(canariesRedactedAtIngest(withCount, { ingest: { filters: ["dedup"] } }), false);
    assert.equal(canariesRedactedAtIngest(withCount, null), false);
    // An older run whose spec lists `pii` but whose canaries skipped the filters.
    assert.equal(canariesRedactedAtIngest(run(m("privacy", "leakage_rate", "defense=none", 0.5)), pii), false);
  });
});
