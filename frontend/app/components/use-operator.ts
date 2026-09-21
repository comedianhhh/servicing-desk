"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

const KEY = "desk.operator";
const listeners = new Set<() => void>();

function read(): string {
  try {
    return localStorage.getItem(KEY) || "";
  } catch {
    return "";
  }
}

/** Selected operator name, remembered per browser (a per-viewer convenience: storage may be unavailable,
 * so it degrades to "" and the picker falls back to the first configured name). useSyncExternalStore keeps
 * the server render and the first client render identical. */
export function useOperator(): [string, (v: string) => void] {
  const op = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    read,
    () => "",
  );
  const set = (v: string) => {
    try {
      localStorage.setItem(KEY, v);
    } catch {}
    listeners.forEach((cb) => cb());
  };
  return [op, set];
}

/** The names this UI is allowed to act as (from the server; tokens never come down). */
export function useOperatorNames(): string[] {
  const [names, setNames] = useState<string[]>([]);
  useEffect(() => {
    fetch("/api/operators")
      .then((r) => r.json())
      .then(setNames)
      .catch(() => setNames([]));
  }, []);
  return names;
}

/** A JSON body must say so: without this the browser sends text/plain and the API rejects it with a 422
 * before any handler runs. (FormData posts must NOT set it — the browser adds the multipart boundary.) */
export const JSON_HEADERS = { "content-type": "application/json" } as const;

/** Headers for a mutation: who is acting. The proxy turns the name into the bearer token. */
export function asOperator(name: string, extra: Record<string, string> = {}): Record<string, string> {
  return { "x-operator": name, ...extra };
}
