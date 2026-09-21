"use client";

// The operator's side of "the model only proposes". Every extracted value is shown next to the quote it came
// from; the operator can change any field before approving, and what they approve — not the proposal — is
// what the server writes. The version is sent along so a stale tab gets a 409 instead of a silent overwrite.

import { useRouter } from "next/navigation";
import { useState } from "react";
import { JSON_HEADERS, asOperator, describe, useIdentity } from "@/app/components/use-operator";
import type { Extracted, Proposal, Proposed } from "@/lib/api";

const CASE_TYPES = ["NOE", "RFI", "PAYOFF_REQUEST", "LOSS_MIT", "NOT_COVERED"];
const ERROR_CATS: [string, string][] = [
  ["b1", "failure to accept a conforming payment"],
  ["b2", "failure to apply an accepted payment"],
  ["b3", "failure to credit as of date of receipt"],
  ["b4", "escrow disbursement failure"],
  ["b5", "fee without reasonable basis"],
  ["b6", "inaccurate payoff balance — 7 bd"],
  ["b7", "loss-mitigation information error"],
  ["b8", "transfer information error"],
  ["b9", "foreclosure first notice/filing in violation — sale date cap"],
  ["b10", "foreclosure motion/sale in violation — sale date cap"],
  ["b11", "any other servicing error — 30 bd"],
];
const RFI_CATS = ["OWNER_IDENTITY", "OTHER"];
const EXCEPTIONS = ["", "DUPLICATIVE", "OVERBROAD", "UNTIMELY", "CONFIDENTIAL", "IRRELEVANT", "BURDENSOME"];

function Quote({ e }: { e: Extracted }) {
  if (!e.source_quote) return <span className="text-xs text-stone-400 italic">not in letter</span>;
  return <span className="text-xs text-stone-500">“{e.source_quote}”</span>;
}

export function ProposalReview({ caseId, version, proposal }: { caseId: string; version: number; proposal: Proposal }) {
  const router = useRouter();
  const p = proposal.proposed;
  const [form, setForm] = useState<Proposed>(structuredClone(p));
  const [exception, setException] = useState<string>(p.exception_candidates[0] ?? "");
  const { name: operator, role } = useIdentity();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setEl = (k: keyof Proposed["three_elements"], v: string) =>
    setForm({ ...form, three_elements: { ...form.three_elements, [k]: { ...form.three_elements[k], value: v || null } } });

  const edited = JSON.stringify(form) !== JSON.stringify(p);
  // Mirror the API's rule so the button says why before anyone clicks; the API still decides.
  const allowed = role === "supervisor" || (role === "operator" && !exception);
  const why = !role ? "no identity" : allowed ? undefined : exception ? `${operator} is ${role}; an exception determination needs supervisor` : `${operator} is ${role}; approving needs operator`;

  async function approve() {
    setBusy(true);
    setError(null);
    const body = {
      approved: { ...form, error_category: form.case_type === "NOE" ? form.error_category : null, rfi_category: form.case_type === "RFI" ? form.rfi_category : null },
      expected_version: version,
      exception_code: exception || null,
    };
    const r = await fetch(`/api/desk/cases/${caseId}/proposals/${proposal.id}/approve`, { method: "POST", headers: asOperator(operator, JSON_HEADERS), body: JSON.stringify(body) });
    setBusy(false);
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      setError(describe(r.status, j));
      return;
    }
    router.refresh();
  }

  return (
    <section className="bg-white border border-violet-200 rounded p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xs uppercase tracking-wide text-violet-700">Proposal — review before it touches the case</h2>
        <span className="text-xs text-stone-400" title="The model's own estimate. On the eval set it never drops below 0.90, including on its misses — nothing in the desk acts on it.">
          {proposal.model} · self-reported confidence {Math.round(p.confidence * 100)}%
        </span>
      </div>
      <p className="text-sm text-stone-600">{p.rationale}</p>

      <div className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-2 text-sm items-center">
        <label className="text-stone-500">Type</label>
        <select className="border rounded px-2 py-1" value={form.case_type} onChange={(e) => setForm({ ...form, case_type: e.target.value })}>
          {CASE_TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>

        {form.case_type === "NOE" && (
          <>
            <label className="text-stone-500">Error category</label>
            <select className="border rounded px-2 py-1" value={form.error_category ?? ""} onChange={(e) => setForm({ ...form, error_category: e.target.value || null })}>
              <option value="">—</option>
              {ERROR_CATS.map(([k, d]) => (
                <option key={k} value={k}>
                  {k} · {d}
                </option>
              ))}
            </select>
          </>
        )}
        {form.case_type === "RFI" && (
          <>
            <label className="text-stone-500">RFI category</label>
            <select className="border rounded px-2 py-1" value={form.rfi_category ?? ""} onChange={(e) => setForm({ ...form, rfi_category: e.target.value || null })}>
              <option value="">—</option>
              {RFI_CATS.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </>
        )}

        <label className="text-stone-500">Borrower</label>
        <div>
          <input className="border rounded px-2 py-1 w-full" value={form.three_elements.borrower_name.value ?? ""} onChange={(e) => setEl("borrower_name", e.target.value)} />
          <Quote e={p.three_elements.borrower_name} />
        </div>
        <label className="text-stone-500">Loan</label>
        <div>
          <input className="border rounded px-2 py-1 w-full font-mono" value={form.three_elements.loan_identifier.value ?? ""} onChange={(e) => setEl("loan_identifier", e.target.value)} />
          <Quote e={p.three_elements.loan_identifier} />
        </div>
        <label className="text-stone-500">Assertion / request</label>
        <div>
          <input className="border rounded px-2 py-1 w-full" value={form.three_elements.assertion_or_request.value ?? ""} onChange={(e) => setEl("assertion_or_request", e.target.value)} />
          <Quote e={p.three_elements.assertion_or_request} />
        </div>

        <label className="text-stone-500">Exception</label>
        <div>
          <select className="border rounded px-2 py-1" value={exception} onChange={(e) => setException(e.target.value)}>
            {EXCEPTIONS.map((x) => (
              <option key={x} value={x}>
                {x || "none — proceed"}
              </option>
            ))}
          </select>
          {p.exception_candidates.length > 0 && <span className="ml-2 text-xs text-orange-700">model flagged: {p.exception_candidates.join(", ")}</span>}
          {exception && (
            <div className="text-xs text-stone-500 mt-1">
              Declining under §1024.35(g) / §1024.36(f) is a determination, not a triage edit: it needs a <b>supervisor</b>, skips the
              acknowledgment, and starts a 5-business-day clock for the determination letter (L5).
            </div>
          )}
        </div>
      </div>

      {error && <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">{error}</div>}
      <div className="flex items-center gap-3">
        <button onClick={approve} disabled={busy || !allowed} title={why} className="rounded bg-violet-700 text-white px-3 py-1.5 text-sm disabled:opacity-50">
          {exception ? "Record exception determination" : "Approve"}
          {edited && " (with edits)"}
        </button>
        <span className="text-xs text-stone-500">
          {why ?? (exception ? "Recorded as a determination by the acting supervisor." : "Approving sets the clocks. Edits are recorded in the audit trail.")}
        </span>
      </div>
    </section>
  );
}
