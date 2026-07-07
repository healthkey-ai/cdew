/**
 * Bridge between the authored `data` JSON Schema (design §8, schema-lint) and a
 * flat list of attribute rows the structured editor renders. Rebuilds a
 * lint-valid schema (closed object, no disallowed keywords) from the rows.
 */

export const ATTR_TYPES = ["string", "integer", "number", "boolean", "date"] as const;
export type AttrType = (typeof ATTR_TYPES)[number];

export interface AttrRow {
  name: string;
  type: AttrType;
  description: string;
  required: boolean;
  nullable: boolean;
}

type JsonSchema = Record<string, unknown>;

export function schemaToRows(schema: JsonSchema | undefined | null): AttrRow[] {
  const props = (schema?.properties as Record<string, JsonSchema>) ?? {};
  const required = new Set((schema?.required as string[]) ?? []);
  return Object.entries(props).map(([name, def]) => {
    const rawType = def.type;
    const types = Array.isArray(rawType) ? (rawType as string[]) : [rawType as string];
    const nullable = types.includes("null");
    const base = types.find((t) => t !== "null") ?? "string";
    const type: AttrType =
      base === "string" && def.format === "date" ? "date" : (base as AttrType);
    return {
      name,
      type: ATTR_TYPES.includes(type) ? type : "string",
      description: (def.description as string) ?? "",
      required: required.has(name),
      nullable,
    };
  });
}

function buildProp(row: AttrRow): JsonSchema {
  if (row.type === "date") {
    const prop: JsonSchema = { type: row.nullable ? ["string", "null"] : "string", format: "date" };
    if (row.description) prop.description = row.description;
    return prop;
  }
  const prop: JsonSchema = { type: row.nullable ? [row.type, "null"] : row.type };
  if (row.description) prop.description = row.description;
  return prop;
}

export function rowsToSchema(rows: AttrRow[]): JsonSchema {
  const properties: Record<string, JsonSchema> = {};
  const required: string[] = [];
  for (const row of rows) {
    const name = row.name.trim();
    if (!name) continue;
    properties[name] = buildProp(row);
    if (row.required) required.push(name);
  }
  return { type: "object", additionalProperties: false, required, properties };
}
