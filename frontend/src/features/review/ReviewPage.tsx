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

/** Review (design §6): processed documents ready to review. Open one to see the
 * parsed document + extracted facts on its view page. */
export function ReviewPage() {
  const docs = useDocuments();
  // "Processed" = the document has been parsed (has extractable text).
  const rows = (docs.data?.results ?? []).filter((d) => d.has_text);

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Review</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Processed documents ready to review. Open one to verify facts on the document (text or image
          with bounding boxes) and approve/correct/reject.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Processed documents</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>File</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Classification</TableHead>
                <TableHead>Verified</TableHead>
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
                    <Link to={`/review/${d.id}`} className="text-primary hover:underline">
                      {d.original_filename || `doc#${d.id}`}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusVariant(d.status)}>{statusLabel(d.status)}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{classificationText(d)}</TableCell>
                  <TableCell>
                    {d.verified ? <Badge variant="secondary">✓ verified</Badge> : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                </TableRow>
              ))}
              {!docs.isPending && rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                    No processed documents yet.
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
