"use client";

import { useSyncExternalStore } from "react";

const KEY = "desk.operator";
const listeners = new Set<() => void>();

function read(): string {
  try {
    return localStorage.getItem(KEY) || "op-1";
  } catch {
    return "op-1";
  }
}

/** Operator id, remembered per browser (a per-viewer convenience: storage may be unavailable, so it
 * degrades to op-1). useSyncExternalStore keeps the server render and the first client render identical. */
export function useOperator(): [string, (v: string) => void] {
  const op = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    read,
    () => "op-1",
  );
  const set = (v: string) => {
    try {
      localStorage.setItem(KEY, v);
    } catch {}
    listeners.forEach((cb) => cb());
  };
  return [op, set];
}
