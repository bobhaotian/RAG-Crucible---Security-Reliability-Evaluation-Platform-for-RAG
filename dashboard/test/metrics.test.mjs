// The dashboard's rules for metrics that were not measured, tested on the pure
// selectors in src/metrics.ts (compiled by `npm test`; see tsconfig.test.json).
// Every panel renders from these, so each rule here is one a panel relies on:
// a null is never drawn as 0, never inverted to 1, and never feeds a delta.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  breakdown,
  contamination,
  defenseGroups,
  diffRows,
  formatReading,
  groupUnmeasured,
  judgeGap,
  kpis,
  read,
  rerankLift,
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
    assert.equal(worstOf([["a", read(nm("s", "a", "", "inapplicable"))]]), undefined);
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
