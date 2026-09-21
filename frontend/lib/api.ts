// Server-side access to the desk API. Pages fetch here (no CORS, no key in the browser); client components
// mutate through the /api/desk proxy route, which forwards to the same base URL.

export const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type Clock = { kind: string; due_on: string; calendar: string; citation: string; status: string };
export type Letter = {
  id: string;
  template: string;
  body: string;
  fields: Record<string, unknown>;
  sent_at: string | null;
  voided_at: string | null;
};
export type Extracted = { value: string | null; source_quote: string | null };
export type Proposed = {
  case_type: string;
  error_category: string | null;
  rfi_category: string | null;
  three_elements: { borrower_name: Extracted; loan_identifier: Extracted; assertion_or_request: Extracted };
  exception_candidates: string[];
  mentions_foreclosure_sale_date: Extracted;
  confidence: number;
  rationale: string;
};
export type Proposal = { id: string; model: string; proposed: Proposed; approved: Proposed | null; decided_by: string | null };
export type Case = {
  id: string;
  status: string;
  version: number;
  case_type: string | null;
  error_category: string | null;
  rfi_category: string | null;
  exception_code: string | null;
  borrower_name: string | null;
  loan_id: string | null;
  received_on: string;
  channel: string;
  letter_text: string;
  created_at: string;
  clocks: Clock[];
  letters: Letter[];
  proposals: Proposal[];
};
export type AuditRow = { at: string; actor: string; action: string; detail: Record<string, unknown> };
export type Effects = {
  sagas: { id: string; kind: string; state: string; step: string; attempts: number; last_error: string | null; started_by: string }[];
  ledger: { id: string; amount: string; memo: string; posted_at: string; reversed_at: string | null }[];
  credit_hold: { until: string; placed_at: string; released_at: string | null } | null;
};
export type TemplateSpec = { doc: string; fields: { name: string; required: boolean; type: string }[] };

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export const listCases = () => get<Case[]>("/cases");
export const getCase = (id: string) => get<Case>(`/cases/${id}`);
export const getAudit = (id: string) => get<AuditRow[]>(`/cases/${id}/audit`);
export const getEffects = (id: string) => get<Effects>(`/cases/${id}/effects`);
export const getTemplates = () => get<Record<string, TemplateSpec>>("/letters/templates");

/** Nearest pending clock, or null. Queue ordering and the days-left badge both come from this. */
export function nextClock(c: Case): Clock | null {
  const pending = c.clocks.filter((k) => k.status === "PENDING").sort((a, b) => a.due_on.localeCompare(b.due_on));
  return pending[0] ?? null;
}

export function daysUntil(iso: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(iso + "T00:00:00");
  return Math.round((due.getTime() - today.getTime()) / 86_400_000);
}
