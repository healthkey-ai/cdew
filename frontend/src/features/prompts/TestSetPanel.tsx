import { useMemo, useState } from "react";
import { toast } from "sonner";
import { FlaskConical, Plus, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDocuments } from "@/features/documents/api";
import { cn } from "@/lib/utils";
import {
  type DryRunRow,
  type PromptDefinition,
  type PromptVersion,
  type TestSample,
  usePromptActions,
  useTestSampleActions,
  useTestSamples,
} from "./api";

/** Labeled test set for a classifier or extractor (design §8.3): add documents,
 * label the expected gold, and dry-run the selected version for pass/fail. */
export function TestSetPanel({ def, version }: { def: PromptDefinition; version: PromptVersion | null }) {
  const samples = useTestSamples(def.id);
  const sactions = useTestSampleActions(def.id);
  const dryRun = usePromptActions(def.id).dryRun;
  const docs = useDocuments();

  const [results, setResults] = useState<Record<number, DryRunRow>>({});
  const [docId, setDocId] = useState("");
  const [label, setLabel] = useState("");

  const isClassifier = def.kind === "classifier";
  const types = useMemo(
    () => (isClassifier ? ((version?.taxonomy as { type: string }[] | undefined)?.map((t) => t.type) ?? []) : []),
    [isClassifier, version],
  );
  const parsedDocs = useMemo(() => (docs.data?.results ?? []).filter((d) => d.has_text), [docs.data]);
  // value → label map so the Select trigger shows the filename, not the id.
  const docItems = useMemo(
    () => Object.fromEntries(parsedDocs.map((d) => [String(d.id), d.original_filename || `doc#${d.id}`])),
    [parsedDocs],
  );

  const addSample = () =>
    sactions.create.mutate(
      { document: Number(docId), label },
      {
        onSuccess: () => {
          setDocId("");
          setLabel("");
          toast.success("Sample added");
        },
      },
    );

  const runAll = () => {
    if (!version) return;
    dryRun.mutate(version.id, {
      onSuccess: (d) => {
        const by: Record<number, DryRunRow> = {};
        d.results.forEach((r) => (by[r.sample_id] = r));
        setResults(by);
        const scored = d.results.filter((r) => r.passed !== undefined);
        if (scored.length) {
          const pass = scored.filter((r) => r.passed).length;
          toast[pass === scored.length ? "success" : "info"](`${pass}/${scored.length} passed`);
        } else {
          toast.info("Ran — add gold to see pass/fail");
        }
      },
    });
  };

  const toggleType = (s: TestSample, type: string) => {
    const cur = new Set((s.expected_payload as string[] | null) ?? []);
    if (cur.has(type)) cur.delete(type);
    else cur.add(type);
    sactions.update.mutate({ id: s.id, expected_payload: [...cur] });
  };

  const setExpectedFromRun = (s: TestSample) => {
    const row = results[s.id];
    if (!row?.facts) {
      toast.error("Run the test set first");
      return;
    }
    sactions.update.mutate(
      { id: s.id, expected_payload: row.facts.map((f) => f.data) },
      { onSuccess: () => toast.success("Gold set from current output") },
    );
  };

  const passBadge = (r?: DryRunRow) =>
    !r || r.passed === undefined ? null : (
      <Badge variant={r.passed ? "secondary" : "destructive"} className={r.passed ? "text-success" : ""}>
        {r.passed ? "pass" : "fail"}
      </Badge>
    );

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Test set{samples.data ? ` (${samples.data.length})` : ""}</CardTitle>
        <Button size="sm" onClick={runAll} disabled={!version || !samples.data?.length || dryRun.isPending}>
          <FlaskConical />
          Run test set
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={docId} onValueChange={(v) => setDocId(v ?? "")} items={docItems}>
            <SelectTrigger className="h-8 w-64">
              <SelectValue placeholder="Add a parsed document…" />
            </SelectTrigger>
            <SelectContent>
              {parsedDocs.map((d) => (
                <SelectItem key={d.id} value={String(d.id)}>
                  {d.original_filename || `doc#${d.id}`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            className="h-8 w-40"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="label (optional)"
          />
          <Button size="sm" variant="outline" onClick={addSample} disabled={!docId || sactions.create.isPending}>
            <Plus />
            Add
          </Button>
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Document</TableHead>
              <TableHead>Expected (gold)</TableHead>
              <TableHead>Result</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {samples.data?.map((s) => {
              const r = results[s.id];
              return (
                <TableRow key={s.id} className="align-top">
                  <TableCell className="font-medium">
                    {s.document_filename || `doc#${s.document}`}
                    {s.label && <div className="text-xs font-normal text-muted-foreground">{s.label}</div>}
                  </TableCell>
                  <TableCell>
                    {isClassifier ? (
                      <div className="flex flex-wrap gap-1">
                        {types.map((t) => {
                          const on = ((s.expected_payload as string[] | null) ?? []).includes(t);
                          return (
                            <button
                              key={t}
                              onClick={() => toggleType(s, t)}
                              className={cn(
                                "rounded border px-1.5 py-0.5 text-xs transition-colors",
                                on
                                  ? "border-primary bg-primary/10 font-medium"
                                  : "border-input text-muted-foreground hover:bg-muted",
                              )}
                            >
                              {t}
                            </button>
                          );
                        })}
                        {types.length === 0 && (
                          <span className="text-xs text-muted-foreground">no taxonomy types</span>
                        )}
                      </div>
                    ) : (
                      <div className="space-y-1">
                        <div className="text-xs text-muted-foreground">
                          {(s.expected_payload as unknown[] | null)?.length
                            ? `${(s.expected_payload as unknown[]).length} gold fact(s)`
                            : "no gold"}
                        </div>
                        <Button variant="outline" size="sm" onClick={() => setExpectedFromRun(s)}>
                          Set from run
                        </Button>
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    {!r ? (
                      <span className="text-muted-foreground">—</span>
                    ) : isClassifier ? (
                      <div className="space-y-1">
                        {passBadge(r)}
                        <div className="text-xs text-muted-foreground">routed: {r.routed_types?.join(", ") || "—"}</div>
                        {!!r.missing?.length && (
                          <div className="text-xs text-destructive">missing: {r.missing.join(", ")}</div>
                        )}
                        {!!r.extra?.length && <div className="text-xs text-warning">extra: {r.extra.join(", ")}</div>}
                      </div>
                    ) : (
                      <div className="space-y-1">
                        {passBadge(r)}
                        <div className="text-xs text-muted-foreground">{r.facts?.length ?? 0} facts extracted</div>
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8"
                      aria-label="Remove sample"
                      onClick={() => sactions.remove.mutate(s.id)}
                    >
                      <Trash2 className="text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
            {samples.data && samples.data.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="py-6 text-center text-muted-foreground">
                  No test samples yet — add a parsed document above.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>

        <p className="text-xs text-muted-foreground">
          {isClassifier
            ? "Gold = the types this document should route to. Run to compare against the classifier version above."
            : "Gold = the expected facts. Add a document, run to see the extraction, then “Set from run” and refine."}
        </p>
      </CardContent>
    </Card>
  );
}
