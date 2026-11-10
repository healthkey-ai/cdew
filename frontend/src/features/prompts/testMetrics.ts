/** Test-set comparison + metrics (design §8.3). Pure functions over the saved
 * samples, so the numbers follow Expected edits without a re-run. Fact identity
 * matches the backend's dry-run compare (`dryrun._fact_key`). */
import { type DryRunFact, factRow, type TestSample } from "./api";

export type FactRow = Record<string, unknown>;
export type FactPair = { ex?: FactRow; exp?: FactRow; kind: "same" | "changed" | "extra" | "missing" };

/** Stable stringify (object keys sorted, null fields dropped) so equality is
 * order-of-keys independent and an unset field equals an absent one — as the
 * backend's dry-run compare does. */
export const stable = (o: unknown) =>
  JSON.stringify(o, (_k, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.keys(v as object)
          .filter((k) => (v as Record<string, unknown>)[k] != null)
          .sort()
          .reduce((a, k) => ({ ...a, [k]: (v as Record<string, unknown>)[k] }), {})
      : v,
  );

/** Align two fact bags **without any domain key** (works for every extractor):
 *  1) match byte-identical facts 1:1 (multiset intersection) → `same`,
 *  2) greedily pair leftovers by field similarity → `changed` (field-level diff),
 *  3) whatever is left is `extra` (extracted-only) or `missing` (expected-only).
 * Order never matters; duplicate copies with no counterpart surface as extra/missing. */
export function alignFacts(extracted: FactRow[], expected: FactRow[], attrs: string[]): FactPair[] {
  const pairs: FactPair[] = [];
  const expKeys = expected.map(stable);
  const usedExp = new Set<number>();
  const leftoverEx: FactRow[] = [];

  for (const e of extracted) {
    const k = stable(e);
    const j = expKeys.findIndex((ek, idx) => !usedExp.has(idx) && ek === k);
    if (j >= 0) {
      usedExp.add(j);
      pairs.push({ ex: e, exp: expected[j], kind: "same" });
    } else {
      leftoverEx.push(e);
    }
  }

  const leftoverExp = expected.filter((_, idx) => !usedExp.has(idx));
  const usedR = new Set<number>();
  const sim = (a: FactRow, b: FactRow) =>
    attrs.reduce((n, k) => n + (JSON.stringify(a[k]) === JSON.stringify(b[k]) ? 1 : 0), 0);

  for (const e of leftoverEx) {
    let best = -1;
    let bestScore = 0;
    leftoverExp.forEach((g, idx) => {
      if (usedR.has(idx)) return;
      const sc = sim(e, g);
      if (sc > bestScore) {
        bestScore = sc;
        best = idx;
      }
    });
    if (best >= 0) {
      usedR.add(best);
      pairs.push({ ex: e, exp: leftoverExp[best], kind: "changed" });
    } else {
      pairs.push({ ex: e, kind: "extra" });
    }
  }
  leftoverExp.forEach((g, idx) => {
    if (!usedR.has(idx)) pairs.push({ exp: g, kind: "missing" });
  });
  return pairs;
}

/** Two fact bags are equal iff, ignoring order, every fact pairs 1:1 (multiset). */
export const factsEqual = (a: FactRow[], b: FactRow[]) =>
  a.length === b.length && alignFacts(a, b, []).every((p) => p.kind === "same");

/** Confusion counts: tp = right, fp = predicted but wrong, fn = expected but missed. */
export interface Counts {
  tp: number;
  fp: number;
  fn: number;
}
/** A right/total tally (field accuracy, grounding, label accuracy, exact match). */
export interface Tally {
  right: number;
  total: number;
}

const ratio = (n: number, d: number) => (d ? n / d : null);
export const precision = (c: Counts) => ratio(c.tp, c.tp + c.fp);
export const recall = (c: Counts) => ratio(c.tp, c.tp + c.fn);
export const f1 = (c: Counts) => ratio(2 * c.tp, 2 * c.tp + c.fp + c.fn);
export const rate = (t: Tally) => ratio(t.right, t.total);

const zero = (): Counts => ({ tp: 0, fp: 0, fn: 0 });
const add = (into: Counts, c: Partial<Counts>) => {
  into.tp += c.tp ?? 0;
  into.fp += c.fp ?? 0;
  into.fn += c.fn ?? 0;
};
const bump = <K>(m: Map<K, Counts>, k: K, c: Partial<Counts>) => {
  if (!m.has(k)) m.set(k, zero());
  add(m.get(k)!, c);
};

/** A fact's confusion counts from its alignment: an identical fact is a hit; a
 * "changed" pair is a miss on both sides (wrong fact found, right fact missed). */
export function factCounts(pairs: FactPair[]): Counts {
  const c = zero();
  for (const p of pairs) {
    if (p.kind === "same") c.tp += 1;
    if (p.ex && p.kind !== "same") c.fp += 1;
    if (p.exp && p.kind !== "same") c.fn += 1;
  }
  return c;
}

export interface SetMetrics {
  /** Samples with both a saved result and Expected — what the metrics cover. */
  scored: number;
  /** Samples whose result exactly equals Expected (document-level accuracy). */
  exact: Tally;
  /** Micro-averaged over every fact (extractor) or type label (classifier). */
  counts: Counts;
  /** Per object type (extractor) or taxonomy type (classifier). */
  byType: [string, Counts][];
  /** Saved results produced by a version other than the one shown. */
  stale: number;
}

export interface ExtractorMetrics extends SetMetrics {
  /** Of facts paired with an expected fact, how many field values are right. */
  fields: Tally;
  byField: [string, Tally][];
  /** Extracted facts whose source snippet was located in the document. */
  grounded: Tally;
}

export interface ClassifierMetrics extends SetMetrics {
  /** Per type-decision accuracy (1 − Hamming loss): each sample × each type is
   * one yes/no decision, right when routed ⇔ expected. */
  labels: Tally;
}

const isStale = (s: TestSample, versionId?: number) =>
  versionId != null && s.extracted_version_id != null && s.extracted_version_id !== versionId;

export function extractorMetrics(samples: TestSample[], attrs: string[], versionId?: number): ExtractorMetrics {
  const m: ExtractorMetrics = {
    scored: 0,
    exact: { right: 0, total: 0 },
    counts: zero(),
    byType: [],
    stale: 0,
    fields: { right: 0, total: 0 },
    byField: [],
    grounded: { right: 0, total: 0 },
  };
  const byType = new Map<string, Counts>();
  const byField = new Map<string, Tally>();
  const typeOf = (f: FactRow) => String(f.object_type ?? "—");

  for (const s of samples) {
    const facts = s.extracted_payload as DryRunFact[] | null;
    if (!Array.isArray(facts)) continue;
    if (isStale(s, versionId)) m.stale += 1;
    m.grounded.total += facts.length;
    m.grounded.right += facts.filter((f) => f.resolved).length;

    const expected = s.expected_payload as FactRow[] | null;
    if (!Array.isArray(expected)) continue;
    m.scored += 1;
    const pairs = alignFacts(facts.map(factRow), expected, attrs);
    const c = factCounts(pairs);
    add(m.counts, c);
    m.exact.total += 1;
    if (c.fp === 0 && c.fn === 0) m.exact.right += 1;

    for (const p of pairs) {
      if (p.kind === "same") bump(byType, typeOf(p.ex!), { tp: 1 });
      else {
        if (p.ex) bump(byType, typeOf(p.ex), { fp: 1 });
        if (p.exp) bump(byType, typeOf(p.exp), { fn: 1 });
      }
      if (!p.ex || !p.exp) continue;
      // Field-level: every field set on either side of a matched pair.
      const keys = new Set([...Object.keys(p.ex), ...Object.keys(p.exp)].filter((k) => p.ex![k] != null || p.exp![k] != null));
      for (const k of keys) {
        const ok = stable(p.ex[k] ?? null) === stable(p.exp[k] ?? null);
        m.fields.total += 1;
        if (ok) m.fields.right += 1;
        const t = byField.get(k) ?? { right: 0, total: 0 };
        byField.set(k, { right: t.right + (ok ? 1 : 0), total: t.total + 1 });
      }
    }
  }
  m.byType = [...byType].sort(([a], [b]) => a.localeCompare(b));
  // Worst fields first — that's where the extraction prompt needs work.
  m.byField = [...byField].sort(([a, x], [b, y]) => (rate(x) ?? 1) - (rate(y) ?? 1) || a.localeCompare(b));
  return m;
}

export function classifierMetrics(samples: TestSample[], types: string[], versionId?: number): ClassifierMetrics {
  const m: ClassifierMetrics = {
    scored: 0,
    exact: { right: 0, total: 0 },
    counts: zero(),
    byType: [],
    stale: 0,
    labels: { right: 0, total: 0 },
  };
  const byType = new Map<string, Counts>(types.map((t) => [t, zero()]));

  for (const s of samples) {
    const result = s.extracted_payload as { routed_types?: string[] } | null;
    if (!result) continue;
    if (isStale(s, versionId)) m.stale += 1;
    if (!Array.isArray(s.expected_payload)) continue;
    m.scored += 1;
    const routed = new Set(result.routed_types ?? []);
    const exp = new Set(s.expected_payload as string[]);
    const universe = new Set([...types, ...routed, ...exp]);
    let exact = true;
    for (const t of universe) {
      const r = routed.has(t);
      const e = exp.has(t);
      const c = { tp: r && e ? 1 : 0, fp: r && !e ? 1 : 0, fn: !r && e ? 1 : 0 };
      bump(byType, t, c);
      add(m.counts, c);
      m.labels.total += 1;
      if (r === e) m.labels.right += 1;
      else exact = false;
    }
    m.exact.total += 1;
    if (exact) m.exact.right += 1;
  }
  m.byType = [...byType].sort(([a], [b]) => a.localeCompare(b));
  return m;
}
