import { useEffect, useState } from "react";
import { Loader2, Search, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { type DirectoryPatient, directoryErrorDetail, usePatientSearch } from "./api";

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/**
 * Patient picker (admins, #31 Part B): searches the admin's directory host by
 * name, email or person id — the host's access rules decide who appears.
 */
export function PatientPicker({
  value,
  onChange,
  autoFocus,
  inlineResults,
  className,
}: {
  value: DirectoryPatient | null;
  onChange: (p: DirectoryPatient | null) => void;
  autoFocus?: boolean;
  /** Render results in the flow (e.g. inside a dialog) instead of a floating list. */
  inlineResults?: boolean;
  className?: string;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const debounced = useDebounced(query);
  const search = usePatientSearch(debounced, !value);
  const results = search.data ?? [];
  const typing = query.trim() !== debounced.trim();

  const pick = (p: DirectoryPatient) => {
    onChange(p);
    setQuery("");
    setOpen(false);
  };

  if (value) {
    return (
      <div className={cn("flex h-8 items-center gap-2 rounded-md border bg-background px-2 text-sm", className)}>
        <span className="min-w-0 flex-1 truncate text-left">
          <span className="font-medium">{value.name || "Unnamed patient"}</span>
          <span className="text-muted-foreground">
            {value.email ? ` · ${value.email}` : ""} · #{value.person_id}
          </span>
        </span>
        <button
          type="button"
          aria-label="Clear patient"
          className="text-muted-foreground hover:text-foreground"
          onClick={() => onChange(null)}
        >
          <X className="size-4" />
        </button>
      </div>
    );
  }

  const showList = (open || inlineResults) && query.trim().length >= 2;
  return (
    <div className={cn("relative", className)}>
      <Search className="pointer-events-none absolute left-2 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        className="h-8 bg-background pl-8"
        value={query}
        autoFocus={autoFocus}
        placeholder="Search patients by name, email or ID"
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((i) => Math.min(i + 1, results.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((i) => Math.max(i - 1, 0));
          } else if (e.key === "Enter" && results[active]) {
            e.preventDefault();
            pick(results[active]);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        role="combobox"
        aria-expanded={showList}
        aria-autocomplete="list"
      />
      {showList && (
        <div
          role="listbox"
          className={cn(
            "mt-1 max-h-72 overflow-auto rounded-md border bg-popover p-1 text-left text-sm",
            inlineResults ? "relative" : "absolute left-0 right-0 top-full z-20 shadow-md",
          )}
        >
          {(typing || search.isFetching) && results.length === 0 && (
            <div className="flex items-center gap-2 px-2 py-1.5 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Searching…
            </div>
          )}
          {search.isError && (
            <div className="px-2 py-1.5 text-destructive">
              {directoryErrorDetail(search.error) ?? "Patient search failed."}
            </div>
          )}
          {!typing && search.isSuccess && results.length === 0 && (
            <div className="px-2 py-1.5 text-muted-foreground">No matching patients.</div>
          )}
          {results.map((p, i) => (
            <button
              key={p.person_id}
              type="button"
              role="option"
              aria-selected={i === active}
              className={cn(
                "flex w-full flex-col rounded-sm px-2 py-1.5 text-left",
                i === active ? "bg-accent text-accent-foreground" : "hover:bg-accent/60",
              )}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => e.preventDefault()} // keep focus so onBlur doesn't close first
              onClick={() => pick(p)}
            >
              <span className="font-medium">{p.name || "Unnamed patient"}</span>
              <span className="text-xs text-muted-foreground">
                {p.email || "no email"} · #{p.person_id}
                {p.organization ? ` · ${p.organization}` : ""}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
