import { useState } from "react";
import { toast } from "sonner";
import { Play, Square } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

/** Workflow control (design §6): start/stop the document-processing worker and
 * watch its log. The worker isn't implemented yet, so it is always stopped. */
export function WorkflowPage() {
  const [log, setLog] = useState<string[]>([
    "Workflow worker is not implemented yet — nothing is running.",
  ]);

  const append = (line: string) => setLog((l) => [...l, `${new Date().toLocaleTimeString()}  ${line}`]);

  const onStart = () => {
    append("Start requested — worker not implemented yet.");
    toast.info("The workflow worker isn't implemented yet");
  };

  return (
    <section className="flex min-h-[calc(100vh-7.5rem)] flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">Workflow</h1>
          <Badge variant="outline">Stopped</Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          Controls the document-processing worker (not implemented yet).
        </p>
      </div>

      <div className="flex items-center gap-2">
        <Button onClick={onStart}>
          <Play />
          Start
        </Button>
        <Button variant="outline" disabled>
          <Square />
          Stop
        </Button>
      </div>

      {/* log fills the rest of the page */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border bg-muted">
        <div className="border-b px-3 py-1.5 text-xs font-medium text-muted-foreground">Log</div>
        <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap p-3 font-mono text-xs">
          {log.join("\n")}
        </pre>
      </div>
    </section>
  );
}
