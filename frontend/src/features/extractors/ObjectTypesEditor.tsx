import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { type CatalogField, FIELD_LABELS, type ObjectType } from "@/features/prompts/api";
import { cn } from "@/lib/utils";

const typeLabel = (f: CatalogField) => {
  const t = Array.isArray(f.type) ? f.type.find((x) => x !== "null") ?? "string" : f.type;
  return f.format === "date" ? "date" : t;
};

/**
 * Object-typed extractor editor (alignment §6.1, #95): pick 1..n object types from
 * the catalog and, optionally, add extraction-technique guidance per type. The
 * fields are the catalog's — synced from promop, not authored — and the prompt is
 * composed from them, so there is no free-form prompt here.
 */
export function ObjectTypesEditor({
  catalog,
  definitions,
  selected,
  guidance,
  editable,
  onSelectedChange,
  onGuidanceChange,
}: {
  catalog: ObjectType[] | undefined; // the live catalog (for selection)
  definitions: Record<string, ObjectType>; // what the version extracts against (snapshot or live)
  selected: string[];
  guidance: Record<string, string>;
  editable: boolean;
  onSelectedChange: (keys: string[]) => void;
  onGuidanceChange: (key: string, text: string) => void;
}) {
  const toggle = (key: string, on: boolean) =>
    onSelectedChange(on ? [...selected, key] : selected.filter((k) => k !== key));

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label>Object types to extract</Label>
        <p className="text-xs text-muted-foreground">
          Each object type is a kind of fact promop stores. Pick one or several: several types share one pass over the
          document.
        </p>
        {!catalog ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {catalog.map((o) => {
              const on = selected.includes(o.key);
              return (
                <label
                  key={o.key}
                  className={cn(
                    "flex items-start gap-2.5 rounded-md border p-2.5 text-sm",
                    on ? "border-primary/50 bg-primary/5" : "bg-card",
                    editable ? "cursor-pointer" : "cursor-default opacity-90",
                  )}
                >
                  <Checkbox
                    className="mt-0.5"
                    checked={on}
                    disabled={!editable}
                    onCheckedChange={(c) => toggle(o.key, c === true)}
                  />
                  <span className="min-w-0">
                    <span className="font-medium">{o.label}</span>{" "}
                    <span className="font-mono text-xs text-muted-foreground">{o.key}</span>
                    <span className="block text-xs text-muted-foreground">{o.description}</span>
                  </span>
                </label>
              );
            })}
          </div>
        )}
        {selected.length === 0 && <p className="text-xs text-destructive">Select at least one object type.</p>}
      </div>

      {selected.map((key) => {
        const def = definitions[key];
        if (!def) {
          return (
            <p key={key} className="text-sm text-destructive">
              Unknown object type <span className="font-mono">{key}</span> — it is not in the catalog.
            </p>
          );
        }
        const required = new Set(def.source_schema.required);
        const commit = new Set(def.commit_required);
        const extraOnly = new Set(def.extraction_only);
        return (
          <div key={key} className="space-y-2 rounded-lg border p-3">
            <div className="flex flex-wrap items-baseline gap-2">
              <h3 className="text-sm font-semibold">{def.label}</h3>
              <span className="font-mono text-xs text-muted-foreground">{def.key}</span>
              <span className="text-xs text-muted-foreground">
                {def.omop_targets?.length
                  ? `→ promop ${def.omop_targets.join(" + ")}`
                  : def.omop_target
                    ? `→ promop ${def.omop_target}`
                    : "→ stays in CDEW"}
              </span>
            </div>
            {def.commit_hold && (
              <p className="rounded-md bg-muted px-2 py-1.5 text-xs text-muted-foreground">
                Not committable yet: {def.commit_hold}
              </p>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-56">Field</TableHead>
                  <TableHead className="w-20">Type</TableHead>
                  <TableHead>How it is extracted</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(def.source_schema.properties).map(([name, f]) => (
                  <TableRow key={name} className="align-top">
                    <TableCell className="font-mono text-xs">
                      {name}
                      {FIELD_LABELS[name] && (
                        <span className="block font-sans text-muted-foreground">{FIELD_LABELS[name]}</span>
                      )}
                      <div className="mt-1 flex flex-wrap gap-1 font-sans">
                        {required.has(name) && <Badge variant="secondary">required</Badge>}
                        {!required.has(name) && commit.has(name) && (
                          <Badge variant="outline" title="promop needs it to commit; review asks for it if missing">
                            needed to commit
                          </Badge>
                        )}
                        {extraOnly.has(name) && (
                          <Badge variant="outline" title="Kept in CDEW (and, for specimen, sent to promop's code lookup as context); never written to promop">
                            not committed
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{typeLabel(f)}</TableCell>
                    <TableCell className="whitespace-normal text-xs">{def.field_guide[name] ?? f.description ?? ""}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="space-y-1">
              <Label className="text-xs">Extraction technique (optional)</Label>
              <p className="text-xs text-muted-foreground">
                Always applied: <span className="italic">{def.default_guidance}</span> Add how to extract this kind of
                fact from these documents — not which facts matter.
              </p>
              <Textarea
                className="min-h-16 text-sm"
                value={guidance[key] ?? ""}
                disabled={!editable}
                placeholder="e.g. include supportive medications; one fact per course"
                onChange={(e) => onGuidanceChange(key, e.target.value)}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
