"use client";

// What the operator can do from the current state. The transition table mirrors state_machine.TRANSITIONS
// for human-driven moves; the server is still the authority (a wrong move gets a 409 and is shown as-is).
// Letter forms are built from /letters/templates, so a required field the rule names cannot be omitted.

import { useRouter } from "next/navigation";
import { useState } from "react";
import { JSON_HEADERS, asOperator, describe, useIdentity } from "@/app/components/use-operator";
import type { Case, TemplateSpec } from "@/lib/api";

const NEXT: Record<string, { to: string; label: string; needs?: string[] }[]> = {
  ACK_PENDING: [
    { to: "INVESTIGATING", label: "Acknowledged → investigate", needs: ["L1"] },
    { to: "EARLY_RESOLVED", label: "Fixed within 5 bd (no ack needed) §1024.35(f)(1)" },
  ],
  EXCEPTION_REVIEW: [
    { to: "CLOSED", label: "Exception stands → close", needs: ["L5"] },
    { to: "ACK_PENDING", label: "Exception does not hold → acknowledge" },
  ],
  INVESTIGATING: [{ to: "EXTENDED", label: "Extend 15 bd (30-day class only)", needs: ["L4"] }],
  RESPONDED: [
    { to: "DOCS_REQUESTED", label: "Borrower asked for relied-upon documents" },
    { to: "CLOSED", label: "Close" },
  ],
  DOCS_REQUESTED: [{ to: "CLOSED", label: "Documents provided → close", needs: ["L6"] }],
  PAYOFF_REQUEST: [
    { to: "CLOSED", label: "Payoff statement sent → close", needs: ["PAYOFF"] },
    { to: "PAYOFF_REASONABLE_TIME", label: "Bankruptcy / foreclosure / reverse / disaster → reasonable time" },
  ],
  PAYOFF_REASONABLE_TIME: [{ to: "CLOSED", label: "Payoff statement sent → close", needs: ["PAYOFF"] }],
};

// What this state means for the person looking at it — the rule behind the step they are about to take.
const STATE_NOTE: Record<string, string> = {
  ACK_PENDING: "Acknowledge in writing within 5 business days of receipt (L1), unless the error is fixed first — §1024.35(d), (f)(1).",
  EXCEPTION_REVIEW: "No acknowledgment on this path. The determination letter (L5) is due within 5 business days of the decision — §1024.35(g)(2) / §1024.36(f)(2). If the exception does not hold, acknowledge instead.",
  INVESTIGATING: "Respond with a correction (L2), a no-error finding (L3) or the requested information before the response clock; one 15-day extension is available for the 30-day class only (L4).",
  EXTENDED: "Extension taken. The response is now due on the extended date; no second extension.",
  RESPONDED: "The borrower may ask for the documents relied upon (15 business days, L6). Otherwise close.",
  DOCS_REQUESTED: "Provide the relied-upon documents within 15 business days (L6) — §1024.35(e)(4).",
  PAYOFF_REQUEST: "Payoff statement within 7 creditor business days — Reg Z §1026.36(c)(3). Bankruptcy, foreclosure, reverse mortgage or disaster → reasonable time.",
};

// Which letters make sense where. Responses go through the saga; the rest are queued directly.
const LETTERS_FOR: Record<string, string[]> = {
  ACK_PENDING: ["L1"],
  EXCEPTION_REVIEW: ["L5"],
  INVESTIGATING: ["L4", "L2", "L3", "RFI_RESPONSE"],
  EXTENDED: ["L2", "L3", "RFI_RESPONSE"],
  DOCS_REQUESTED: ["L6"],
  PAYOFF_REQUEST: ["PAYOFF"],
  PAYOFF_REASONABLE_TIME: ["PAYOFF"],
};
const VIA_SAGA = new Set(["L2", "L3", "RFI_RESPONSE"]);

export function Actions({ c, templates }: { c: Case; templates: Record<string, TemplateSpec> }) {
  const router = useRouter();
  const { name: operator, role } = useIdentity();
  const canAct = role === "operator" || role === "supervisor";
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const letterChoices = LETTERS_FOR[c.status] ?? [];
  // State survives router.refresh(), so the choice made under the previous status may no longer apply.
  const [chosen, setTemplate] = useState<string>("");
  const template = letterChoices.includes(chosen) ? chosen : (letterChoices[0] ?? "");
  const [fields, setFields] = useState<Record<string, string>>({});
  const sent = new Set(c.letters.filter((l) => l.sent_at && !l.voided_at).map((l) => l.template));

  async function post(path: string, body: unknown) {
    setBusy(true);
    setMsg(null);
    const r = await fetch(`/api/desk${path}`, { method: "POST", headers: asOperator(operator, JSON_HEADERS), body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    setBusy(false);
    if (!r.ok) {
      setMsg({ ok: false, text: describe(r.status, j) });
      return false;
    }
    setMsg({ ok: true, text: j.body ?? (j.saga_id ? `saga ${j.saga_id.slice(0, 8)} started at ${j.step}` : "ok") });
    router.refresh();
    return true;
  }

  const spec = template ? templates[template] : null;

  return (
    <section className="bg-white border border-stone-200 rounded p-4 space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xs uppercase tracking-wide text-stone-500">Actions</h2>
        {!canAct && role && <span className="text-xs text-stone-400">{operator} is {role} — read only</span>}
      </div>
      {STATE_NOTE[c.status] && <p className="text-xs text-stone-500 -mt-2">{STATE_NOTE[c.status]}</p>}

      {letterChoices.length > 0 && spec && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-stone-500">Letter</span>
            <select
              className="border rounded px-2 py-1"
              value={template}
              onChange={(e) => {
                setTemplate(e.target.value);
                setFields({});
              }}
            >
              {letterChoices.map((t) => (
                <option key={t} value={t}>
                  {t}
                  {sent.has(t) ? " (sent)" : ""}
                </option>
              ))}
            </select>
            <span className="text-xs text-stone-400">{VIA_SAGA.has(template) ? "via Respond saga" : "queued to letter worker"}</span>
          </div>
          <p className="text-xs text-stone-500">{spec.doc}</p>
          <div className="grid grid-cols-[160px_1fr] gap-x-3 gap-y-1.5 text-sm items-center">
            {spec.fields.map((f) => (
              <FieldInput key={f.name} name={f.name} required={f.required} type={f.type} value={fields[f.name] ?? ""} onChange={(v) => setFields({ ...fields, [f.name]: v })} />
            ))}
          </div>
          <button
            disabled={busy || !canAct}
            onClick={() => {
              const body: Record<string, unknown> = {};
              for (const f of spec.fields) {
                const v = fields[f.name];
                if (v === undefined || v === "") continue;
                body[f.name] = f.type === "array" ? v.split(",").map((s) => s.trim()).filter(Boolean) : v;
              }
              post(`/cases/${c.id}/${VIA_SAGA.has(template) ? "respond" : "letters"}`, { template, fields: body });
            }}
            className="rounded bg-stone-800 text-white px-3 py-1.5 text-sm disabled:opacity-50"
          >
            {VIA_SAGA.has(template) ? `Respond with ${template}` : `Queue ${template}`}
          </button>
        </div>
      )}

      {(NEXT[c.status] ?? []).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {(NEXT[c.status] ?? []).map((t) => {
            const blocked = t.needs && !t.needs.some((n) => sent.has(n));
            return (
              <button
                key={t.to}
                disabled={busy || blocked || !canAct}
                title={blocked ? `needs ${t.needs!.join(" or ")} delivered first` : undefined}
                onClick={() => post(`/cases/${c.id}/transition`, { to: t.to, expected_version: c.version })}
                className="rounded border border-stone-300 bg-white px-3 py-1.5 text-sm hover:bg-stone-50 disabled:opacity-40"
              >
                {t.label}
                {blocked && <span className="ml-1 text-xs text-stone-400">· needs {t.needs!.join("/")}</span>}
              </button>
            );
          })}
        </div>
      )}

      {msg && <div className={`text-sm rounded px-2 py-1 border ${msg.ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-700"}`}>{msg.text}</div>}
    </section>
  );
}

function FieldInput({ name, required, type, value, onChange }: { name: string; required: boolean; type: string; value: string; onChange: (v: string) => void }) {
  return (
    <>
      <label className="text-stone-500">
        {name.replaceAll("_", " ")}
        {required && <span className="text-red-600"> *</span>}
      </label>
      <input className="border rounded px-2 py-1 w-full" placeholder={type === "array" ? "comma-separated" : ""} value={value} onChange={(e) => onChange(e.target.value)} />
    </>
  );
}
