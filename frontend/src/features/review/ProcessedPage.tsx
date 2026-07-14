import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type SourceDocument, useDocuments } from "@/features/documents/api";
import { statusLabel, statusVariant } from "@/features/documents/status";

function classificationText(d: SourceDocument) {
  if (!d.classification) return "—";
  return d.classification.outcome === "routed"
    ? d.classification.routed_types.join(", ")
    : `unclassified · ${d.classification.reason}`;
}

const fmt = (ts: string | null) => (ts ? new Date(ts).toLocaleString() : "—");

/** Processed (design §6): documents that have been reviewed (verified), in
 * chronological order of review. */
export function ProcessedPage() {
  const docs = useDocuments();
  const rows = (docs.data?.results ?? [])
    .filter((d) => d.verified)
    // chronological: earliest verified first.
    .sort((a, b) => (a.verified_at ?? "").localeCompare(b.verified_at ?? ""));

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Processed</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Reviewed documents, in the order they were verified.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Reviewed documents</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>File</TableHead>
                <TableHead>Reviewed at</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Classification</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {docs.isPending &&
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 4 }).map((__, j) => (
                      <TableCell key={j}>
                        <Skeleton className="h-4 w-24" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              {rows.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="font-medium">
                    <Link to={`/inbox/${d.id}`} className="text-primary hover:underline">
                      {d.original_filename || `doc#${d.id}`}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{fmt(d.verified_at)}</TableCell>
                  <TableCell>
                    <Badge variant={statusVariant(d.status)}>{statusLabel(d.status)}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{classificationText(d)}</TableCell>
                </TableRow>
              ))}
              {!docs.isPending && rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                    No reviewed documents yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  );
}
