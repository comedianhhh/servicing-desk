"use client";

import { useEffect, useSyncExternalStore } from "react";

// One identity per browser tab, chosen in the header and used by every mutation on every page. The name is
// remembered in localStorage (a per-viewer convenience; storage may be unavailable, so it degrades to the
// first configured name). The role comes from the API's /me for that name, so the UI can disable what the
// role cannot do instead of letting the operator discover a 403 by clicking.

export type Role = "readonly" | "operator" | "supervisor" | null;
type Identity = { names: string[]; name: string; role: Role };

const KEY = "desk.operator";
const listeners = new Set<() => void>();
let state: Identity = { names: [], name: "", role: null };
const SERVER: Identity = state; // stable reference for the server snapshot (hydration must match)
let loaded = false;

function readStored(): string {
  try {
    return localStorage.getItem(KEY) || "";
  } catch {
    return "";
  }
}

function set(next: Partial<Identity>) {
  state = { ...state, ...next };
  listeners.forEach((cb) => cb());
}

async function fetchRole(name: string) {
  if (!name) return set({ role: null });
  const r = await fetch("/api/desk/me", { headers: { "x-operator": name } }).catch(() => null);
  if (state.name !== name) return; // the picker moved on while this was in flight
  set({ role: r && r.ok ? (await r.json()).role : null });
}

async function load() {
  if (loaded) return;
  loaded = true;
  const names: string[] = await fetch("/api/operators")
    .then((r) => r.json())
    .catch(() => []);
  const stored = readStored();
  const name = names.includes(stored) ? stored : (names[0] ?? "");
  set({ names, name });
  void fetchRole(name);
}

export function setOperator(name: string) {
  try {
    localStorage.setItem(KEY, name);
  } catch {}
  set({ name, role: null });
  void fetchRole(name);
}

export function useIdentity(): Identity {
  useEffect(() => {
    void load();
  }, []);
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
    () => SERVER,
  );
}

/** A JSON body must say so: without this the browser sends text/plain and the API rejects it with a 422
 * before any handler runs. (FormData posts must NOT set it — the browser adds the multipart boundary.) */
export const JSON_HEADERS = { "content-type": "application/json" } as const;

/** Headers for a mutation: who is acting. The proxy turns the name into the bearer token. */
export function asOperator(name: string, extra: Record<string, string> = {}): Record<string, string> {
  return { "x-operator": name, ...extra };
}

/** An API error body, readable. FastAPI's `detail` is a string for our own errors and a list of
 * {loc, msg} objects for validation errors; both end up on screen as-is. */
export function describe(status: number, j: unknown): string {
  const d = (j as { detail?: unknown })?.detail;
  if (typeof d === "string") return `${status}: ${d}`;
  if (Array.isArray(d)) return `${status}: ${d.map((e) => `${(e.loc ?? []).join(".")} — ${e.msg}`).join("; ")}`;
  return `${status}: ${d === undefined ? "request failed" : JSON.stringify(d)}`;
}
