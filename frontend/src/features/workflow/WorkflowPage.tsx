import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ExternalLink, Loader2, Square } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { type Job, type JobStatus, isJobActive, useCancelJob, useConfig, useJobs } from "./api";

const pct = (p: number) => `${Math.round((p ?? 0) * 100)}%`;

// Pipeline work-stages shown on the timeline (ingest happens at upload, pre-job).
const PIPELINE = ["parse", "classify", "extract"] as const;
type StageState = "done" | "active" | "failed" | "cancelled" | "skipped" | "pending";

const STATE_DOT: Record<StageState, string> = {
  done: "bg-success",
  active: "bg-primary animate-pulse",
  failed: "bg-destructive",
  cancelled: "bg-muted-foreground",
  skipped: "bg-muted-foreground/30",
  pending: "bg-muted-foreground/30",
};

function fmtDur(ms: number | null): string {
  if (ms == null || ms < 0) return "";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function overallDur(job: Job): number | null {
  if (!job.started_at) return null;
  const end = job.finished_at ?? new Date().toISOString();
  return new Date(end).getTime() - new Date(job.started_at).getTime();
}

/** Per-stage state + duration from the job's stage_history (#28). */
function stageInfo(job: Job): { stage: string; state: StageState; dur: number | null }[] {
  const hist = job.stage_history ?? [];
  const active = isJobActive(job.status);
  const nowIso = new Date().toISOString();
  return PIPELINE.map((stage) => {
    const idx = hist.findIndex((h) => h.stage === stage);
    if (idx === -1) return { stage, state: (active ? "pending" : "skipped") as StageState, dur: null };
    const endIso = hist[idx + 1]?.at ?? job.finished_at ?? nowIso;
    const dur = new Date(endIso).getTime() - new Date(hist[idx].at).getTime();
    const laterRan = idx + 1 < hist.length; // a later stage (or the done marker) was recorded
    let state: StageState = "done";
    if (!laterRan) {
      if (job.status === "failed") state = "failed";
      else if (job.status === "cancelled") state = "cancelled";
      else if (active) state = "active";
    }
    return { stage, state, dur };
  });
}

/** Readable stage timeline: parse → classify → extract with per-stage status +
 * duration, and the PHI-safe error code on the stage that failed. */
function StageTimeline({ job }: { job: Job }) {
  const steps = stageInfo(job);
  const err = job.errors?.[0]?.code;
  return (
    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
      {steps.map((s, i) => (
        <div key={s.stage} className="flex items-center gap-1">
          <span className={cn("size-2 shrink-0 rounded-full", STATE_DOT[s.state])} />
          <span
            className={cn(
              "capitalize",
              (s.state === "skipped" || s.state === "pending") && "text-muted-foreground/50",
              s.state === "failed" && "font-medium text-destructive",
            )}
          >
            {s.stage}
          </span>
          {s.dur != null && s.state !== "skipped" && s.state !== "pending" && (
            <span className="tabular-nums text-muted-foreground">{fmtDur(s.dur)}</span>
          )}
          {s.state === "failed" && err && (
            <Badge variant="destructive" className="ml-0.5 h-4 px-1 text-[10px] font-normal">
              {err}
            </Badge>
          )}
          {i < steps.length - 1 && <span className="mx-0.5 h-px w-3 shrink-0 bg-border" />}
        </div>
      ))}
    </div>
  );
}

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
              <TableHead className="w-28">Status</TableHead>
              <TableHead>Pipeline</TableHead>
              <TableHead className="w-20">Duration</TableHead>
              <TableHead className="w-40 text-right" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {recent.map((j) => {
              const link = runLink(j);
              return (
                <TableRow key={j.id}>
                  <TableCell className="max-w-[16rem] truncate font-medium" title={j.document_filename}>
                    {j.document_filename || `doc #${j.document}`}
                  </TableCell>
                  <TableCell>{statusBadge(j.status)}</TableCell>
                  <TableCell>
                    <StageTimeline job={j} />
                  </TableCell>
                  <TableCell className="text-sm tabular-nums text-muted-foreground">{fmtDur(overallDur(j))}</TableCell>
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
