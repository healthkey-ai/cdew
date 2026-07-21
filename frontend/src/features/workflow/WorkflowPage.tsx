import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ExternalLink, Loader2, Square } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { type Job, type JobStatus, isJobActive, useCancelJob, useConfig, useJobs } from "./api";

const pct = (p: number) => `${Math.round((p ?? 0) * 100)}%`;

function statusBadge(s: JobStatus) {
  const map: Record<JobStatus, { variant: "default" | "secondary" | "destructive" | "outline"; cls?: string }> = {
    running: { variant: "default" },
    queued: { variant: "outline" },
    completed: { variant: "secondary", cls: "text-success" },
    failed: { variant: "destructive" },
    cancelled: { variant: "outline", cls: "text-muted-foreground" },
  };
  const { variant, cls } = map[s];
  return (
    <Badge variant={variant} className={cn("capitalize", cls)}>
      {s}
    </Badge>
  );
}

/** Workflow monitor (design §6, #57): a live view of pipeline runs — status, stage,
 * per-job Stop (cancels the Prefect flow run), a link to the Prefect run, and a
 * PHI-safe activity log derived from polling. */
export function WorkflowPage() {
  const jobs = useJobs();
  const config = useConfig();
  const cancel = useCancelJob();

  // PHI-safe activity feed derived from polling: emit a line whenever a job's
  // status/stage/progress changes. Ids/stages/codes only — never filenames/PHI.
  const seen = useRef<Map<number, string>>(new Map());
  const seeded = useRef(false);
  const [log, setLog] = useState<string[]>([]);
  useEffect(() => {
    if (!jobs.data) return;
    const lines: string[] = [];
    for (const j of jobs.data) {
      const sig = `${j.status}/${j.stage}/${pct(j.progress)}`;
      if (seen.current.get(j.id) !== sig) {
        if (seeded.current) {
          const err = j.errors?.[0]?.code ? ` error=${j.errors[0].code}` : "";
          lines.push(`job#${j.id} doc#${j.document} ${j.status}/${j.stage} ${pct(j.progress)}${err}`);
        }
        seen.current.set(j.id, sig);
      }
    }
    seeded.current = true;
    if (lines.length) {
      const ts = new Date().toLocaleTimeString();
      setLog((l) => [...lines.map((x) => `${ts}  ${x}`).reverse(), ...l].slice(0, 300));
    }
  }, [jobs.data]);

  const recent = (jobs.data ?? []).slice(0, 50);
  const activeCount = (jobs.data ?? []).filter((j) => isJobActive(j.status)).length;

  const stop = (j: Job) =>
    cancel.mutate(j.id, {
      onError: () => toast.error("Couldn't cancel the run"),
      onSuccess: () => toast.success(`Cancelled job #${j.id}`),
    });

  const runLink = (j: Job) =>
    j.prefect_flow_run_id && config.data?.prefect_ui_url
      ? `${config.data.prefect_ui_url}/runs/flow-run/${j.prefect_flow_run_id}`
      : null;

  return (
    <section className="flex min-h-[calc(100vh-7.5rem)] flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">Workflow</h1>
          {activeCount > 0 ? (
            <Badge variant="default" className="gap-1">
              <Loader2 className="size-3 animate-spin" />
              {activeCount} running
            </Badge>
          ) : (
            <Badge variant="outline">Idle</Badge>
          )}
        </div>
        <p className="text-sm text-muted-foreground">Live pipeline runs — uploads start jobs; Stop cancels a run.</p>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Document</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Stage</TableHead>
              <TableHead className="w-24">Progress</TableHead>
              <TableHead className="w-40 text-right" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {recent.map((j) => {
              const link = runLink(j);
              return (
                <TableRow key={j.id}>
                  <TableCell className="max-w-[18rem] truncate font-medium" title={j.document_filename}>
                    {j.document_filename || `doc #${j.document}`}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5">
                      {statusBadge(j.status)}
                      {j.errors?.[0]?.code && <span className="text-xs text-destructive">{j.errors[0].code}</span>}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm capitalize text-muted-foreground">{j.stage}</TableCell>
                  <TableCell className="text-sm tabular-nums text-muted-foreground">{pct(j.progress)}</TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      {link && (
                        <a
                          href={link}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline"
                        >
                          Prefect
                          <ExternalLink className="size-3" />
                        </a>
                      )}
                      {isJobActive(j.status) && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-destructive"
                          disabled={cancel.isPending}
                          onClick={() => stop(j)}
                        >
                          <Square className="size-3.5" />
                          Stop
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
            {jobs.isLoading && (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {!jobs.isLoading && recent.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  No runs yet — upload a document from the Inbox to start one.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {/* activity log fills the rest of the page */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border bg-muted">
        <div className="border-b px-3 py-1.5 text-xs font-medium text-muted-foreground">Activity log</div>
        <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap p-3 font-mono text-xs">
          {log.length ? log.join("\n") : "Watching for pipeline activity…"}
        </pre>
      </div>
    </section>
  );
}
