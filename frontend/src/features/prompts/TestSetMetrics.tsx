import { useState } from "react";
import { ChevronRight } from "lucide-react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  type ClassifierMetrics,
  type Counts,
  type ExtractorMetrics,
  f1,
  precision,
  rate,
  recall,
} from "./testMetrics";

const pct = (x: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);

/** Extractor tooltips — what each number means. */
const TIP = {
  exact:
    "Exact match, i.e. accuracy at document level: samples whose facts match the expected exactly ÷ samples that have expected facts. This is the pass rate.",
  prf: "Precision / Recall / F1, micro-averaged over every fact in the set. A fact counts as correct only when it is identical to an expected fact. Precision means no invented facts; recall means no missed facts.",
  fields:
    "Field accuracy: for extracted facts paired with an expected fact (identical, or nearly so), the share of fields that match. This shows “right fact, wrong unit/date” separately from missed facts.",
  grounded: "Grounded: the share of extracted facts whose source snippet was found in the document.",
  breakdown: "Breakdowns: precision/recall/F1 per object type, and accuracy per field (worst first).",
};

/** One headline number, with what it means on hover. */
function Stat({ label, value, detail, tip }: { label: string; value: number | null; detail: string; tip: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <div className="min-w-24 rounded-md border bg-card px-3 py-2">
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className="text-xl font-semibold tabular-nums">{pct(value)}</div>
            <div className="text-[11px] text-muted-foreground tabular-nums">{detail}</div>
          </div>
        }
      />
      <TooltipContent className="max-w-72">{tip}</TooltipContent>
    </Tooltip>
  );
}

/** Precision/recall/F1 per type, with the counts they come from. */
function CountsTable({ head, rows }: { head: string; rows: [string, Counts][] }) {
  return (
    <Table className="text-xs">
      <TableHeader>
        <TableRow>
          <TableHead className="h-8">{head}</TableHead>
          <TableHead className="h-8 text-right" title="Right (identical to an expected one)">
            Right
          </TableHead>
          <TableHead className="h-8 text-right" title="Predicted but wrong or not expected">
            Wrong
          </TableHead>
          <TableHead className="h-8 text-right" title="Expected but not found">
            Missed
          </TableHead>
          <TableHead className="h-8 text-right">Precision</TableHead>
          <TableHead className="h-8 text-right">Recall</TableHead>
          <TableHead className="h-8 text-right">F1</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map(([k, c]) => (
          <TableRow key={k}>
            <TableCell className="py-1 font-mono">{k}</TableCell>
            <TableCell className="py-1 text-right tabular-nums">{c.tp}</TableCell>
            <TableCell className="py-1 text-right tabular-nums">{c.fp}</TableCell>
            <TableCell className="py-1 text-right tabular-nums">{c.fn}</TableCell>
            <TableCell className="py-1 text-right tabular-nums">{pct(precision(c))}</TableCell>
            <TableCell className="py-1 text-right tabular-nums">{pct(recall(c))}</TableCell>
            <TableCell className="py-1 text-right font-medium tabular-nums">{pct(f1(c))}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * Test-set scorecard (design §8.3): exact match plus precision / recall / F1, and a
 * per-type / per-field breakdown. Computed from the saved results vs Expected, so it
 * covers the samples that have both.
 */
export function TestSetMetrics(
  props: { kind: "extractor"; metrics: ExtractorMetrics } | { kind: "classifier"; metrics: ClassifierMetrics },
) {
  const [open, setOpen] = useState(false);
  const m = props.metrics;
  if (m.scored === 0) {
    return (
      <p className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
        Metrics appear once a document has both a result and an Expected value — Extract, then set Expected.
      </p>
    );
  }
  const unit = props.kind === "extractor" ? "facts" : "labels";
  const c = m.counts;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Stat
          label="Exact match"
          value={rate(m.exact)}
          detail={`${m.exact.right} / ${m.exact.total} docs`}
          tip={
            props.kind === "extractor"
              ? TIP.exact
              : "Documents routed to exactly the expected set of types (subset accuracy). The pass rate."
          }
        />
        {props.kind === "classifier" && (
          <Stat
            label="Label accuracy"
            value={rate(props.metrics.labels)}
            detail={`${props.metrics.labels.right} / ${props.metrics.labels.total} decisions`}
            tip="Each document × each type is one yes/no decision; the share decided right (1 − Hamming loss). Gives partial credit where exact match doesn't."
          />
        )}
        <Stat
          label="Precision"
          value={precision(c)}
          detail={`${c.tp} / ${c.tp + c.fp} ${unit}`}
          tip={
            props.kind === "extractor"
              ? TIP.prf
              : "Of the types routed to, the share that were expected. Low precision = documents sent to extractors they don't need."
          }
        />
        <Stat
          label="Recall"
          value={recall(c)}
          detail={`${c.tp} / ${c.tp + c.fn} ${unit}`}
          tip={
            props.kind === "extractor"
              ? TIP.prf
              : "Of the expected types, the share the classifier routed to. Low recall = documents that skip an extractor they need."
          }
        />
        <Stat
          label="F1"
          value={f1(c)}
          detail={`${c.fp} wrong · ${c.fn} missed`}
          tip={
            props.kind === "extractor"
              ? TIP.prf
              : "The harmonic mean of precision and recall — one number to compare versions by."
          }
        />
        {props.kind === "extractor" && (
          <>
            <Stat
              label="Field accuracy"
              value={rate(props.metrics.fields)}
              detail={`${props.metrics.fields.right} / ${props.metrics.fields.total} fields`}
              tip={TIP.fields}
            />
            <Stat
              label="Grounded"
              value={rate(props.metrics.grounded)}
              detail={`${props.metrics.grounded.right} / ${props.metrics.grounded.total} facts`}
              tip={TIP.grounded}
            />
          </>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <Tooltip>
          <TooltipTrigger
            render={
              <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1 hover:text-foreground">
                <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
                {props.kind === "extractor" ? "By object type and field" : "By type"}
              </button>
            }
          />
          <TooltipContent className="max-w-72">
            {props.kind === "extractor" ? TIP.breakdown : "Precision/recall/F1 per taxonomy type."}
          </TooltipContent>
        </Tooltip>
        <span>
          Over {m.scored} document{m.scored === 1 ? "" : "s"} with a result and Expected; micro-averaged.
        </span>
        {m.stale > 0 && (
          <span className="text-warning">
            {m.stale} result{m.stale === 1 ? " is" : "s are"} from another version — Extract to re-score.
          </span>
        )}
      </div>

      {open && (
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-md border">
            <CountsTable head={props.kind === "extractor" ? "Object type" : "Type"} rows={m.byType} />
          </div>
          {props.kind === "extractor" && (
            <div className="rounded-md border">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow>
                    <TableHead className="h-8">Field (worst first)</TableHead>
                    <TableHead className="h-8 text-right">Right</TableHead>
                    <TableHead className="h-8 text-right">Accuracy</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {props.metrics.byField.map(([k, t]) => (
                    <TableRow key={k}>
                      <TableCell className="py-1 font-mono">{k}</TableCell>
                      <TableCell className="py-1 text-right tabular-nums">
                        {t.right} / {t.total}
                      </TableCell>
                      <TableCell
                        className={cn("py-1 text-right font-medium tabular-nums", t.right < t.total && "text-destructive")}
                      >
                        {pct(rate(t))}
                      </TableCell>
                    </TableRow>
                  ))}
                  {props.metrics.byField.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={3} className="py-2 text-center text-muted-foreground">
                        No facts paired with an expected fact.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
