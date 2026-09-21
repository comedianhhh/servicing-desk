import Link from "next/link";
import { notFound } from "next/navigation";
import { daysUntil, getAudit, getCase, getEffects, getTemplates } from "@/lib/api";
import { ClockChip, StatusChip } from "@/app/components/chips";
import { ProposalReview } from "./proposal-review";
import { Actions } from "./actions";

export const dynamic = "force-dynamic";

/** Top-level proposal fields whose approved value differs from the proposed one. */
function diffFields(proposed: Record<string, unknown>, approved: Record<string, unknown>): string[] {
  return Object.keys(proposed).filter((k) => JSON.stringify(proposed[k]) !== JSON.stringify(approved[k]));
}

export default async function CasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let c;
  try {
    c = await getCase(id);
  } catch {
    notFound();
  }
  const [audit, effects, templates] = await Promise.all([getAudit(id), getEffects(id), getTemplates()]);
  const pendingProposal = c.proposals.find((p) => !p.decided_by) ?? null;
  const decided = c.proposals.find((p) => p.decided_by) ?? null;
  // Which fields the reviewer changed, from the proposal itself (proposed vs approved), not from the audit row.
  const editedFields = decided?.approved ? diffFields(decided.proposed, decided.approved) : [];
  const title = c.borrower_name ?? (pendingProposal ? "Awaiting review" : decided ? "Correspondence" : "Awaiting triage");

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <div>
          <Link href="/" className="text-xs text-stone-500 hover:underline">
            ← queue
          </Link>
          <h1 className="text-lg font-semibold">
            {title}{" "}
            {c.loan_id && <span className="font-mono text-sm text-stone-500 ml-2">{c.loan_id}</span>}
          </h1>
          <div className="text-xs text-stone-500">
            received {c.received_on} via {c.channel} · case <span className="font-mono">{c.id.slice(0, 8)}</span> · v{c.version}
          </div>
        </div>
        <StatusChip status={c.status} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: the letter, verbatim. Everything on the right must be checkable against this. */}
        <section className="bg-white border border-stone-200 rounded p-4">
          <h2 className="text-xs uppercase tracking-wide text-stone-500 mb-2">Letter</h2>
          <pre className="whitespace-pre-wrap text-sm leading-6 font-sans">{c.letter_text}</pre>
          {c.documents.length > 0 && (
            <div className="mt-3 border-t border-stone-100 pt-2 text-xs text-stone-500 space-y-1">
              {c.documents.map((d) => (
                <div key={d.id}>
                  Original:{" "}
                  <a className="text-blue-700 hover:underline" href={`/api/desk/documents/${d.id}`} target="_blank" rel="noreferrer">
                    {d.filename}
                  </a>{" "}
                  · {d.pages} page{d.pages === 1 ? "" : "s"} · text via <span className="font-mono">{d.engine}</span> · sha256{" "}
                  <span className="font-mono">{d.sha256.slice(0, 12)}</span> · retained per §1024.38(c)(1)
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="space-y-6">
          {pendingProposal ? (
            <ProposalReview caseId={c.id} version={c.version} proposal={pendingProposal} />
          ) : decided ? (
            <div className="bg-white border border-stone-200 rounded p-4 text-sm">
              <h2 className="text-xs uppercase tracking-wide text-stone-500 mb-2">Triage</h2>
              <div className="font-medium">
                {c.case_type}
                {c.error_category && ` · ${c.error_category}`}
                {c.rfi_category && ` · ${c.rfi_category}`}
              </div>
              <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs text-stone-500">
                <dt>proposed by</dt>
                <dd>
                  <span className="font-mono">{decided.model}</span>
                </dd>
                <dt>reviewed by</dt>
                <dd>
                  <span className="text-blue-700">{decided.decided_by}</span>
                  {editedFields.length > 0 ? ` · edited ${editedFields.join(", ")}` : " · no edits"}
                </dd>
                {c.exception_code && (
                  <>
                    <dt className="text-orange-700">determination</dt>
                    <dd className="text-orange-700">
                      {c.exception_code} — declined under {c.case_type === "RFI" ? "§1024.36(f)(1)" : "§1024.35(g)(1)"} by {decided.decided_by}; L5 due within 5 business days
                    </dd>
                  </>
                )}
              </dl>
            </div>
          ) : (
            <div className="bg-white border border-dashed border-stone-300 rounded p-4 text-sm text-stone-500">
              Waiting for the triage worker&apos;s proposal…
            </div>
          )}

          <section className="bg-white border border-stone-200 rounded p-4">
            <h2 className="text-xs uppercase tracking-wide text-stone-500 mb-2">Clocks</h2>
            {c.clocks.length === 0 ? (
              <div className="text-sm text-stone-400">None yet — clocks start when a NOE/RFI is confirmed.</div>
            ) : (
              <table className="w-full text-sm">
                <tbody>
                  {[...c.clocks]
                    .sort((a, b) => a.due_on.localeCompare(b.due_on))
                    .map((k, i) => {
                      const d = daysUntil(k.due_on);
                      return (
                        <tr key={i} className="border-t border-stone-100">
                          <td className="py-1.5 pr-2 font-medium">{k.kind}</td>
                          <td className="py-1.5 pr-2 font-mono text-xs">{k.due_on}</td>
                          <td className="py-1.5 pr-2 text-xs text-stone-500">
                            {k.status === "PENDING" ? (d < 0 ? <span className="text-red-700">{-d}d overdue</span> : `${d}d left`) : ""}
                          </td>
                          <td className="py-1.5 pr-2 text-xs text-stone-400">{k.calendar}</td>
                          <td className="py-1.5 pr-2 text-xs text-stone-500">{k.citation}</td>
                          <td className="py-1.5 text-right">
                            <ClockChip status={k.status} />
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            )}
          </section>

          <Actions c={c} templates={templates} />
        </section>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="bg-white border border-stone-200 rounded p-4">
          <h2 className="text-xs uppercase tracking-wide text-stone-500 mb-2">Letters out</h2>
          {c.letters.length === 0 ? (
            <div className="text-sm text-stone-400">None.</div>
          ) : (
            <ul className="space-y-3 text-sm">
              {c.letters.map((l) => (
                <li key={l.id} className="border-t border-stone-100 pt-2 first:border-0 first:pt-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{l.template}</span>
                    {l.voided_at ? (
                      <span className="rounded bg-stone-100 px-1.5 text-xs text-stone-500 line-through">void</span>
                    ) : l.sent_at ? (
                      <span className="rounded bg-emerald-100 px-1.5 text-xs text-emerald-800">sent</span>
                    ) : (
                      <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-800">queued</span>
                    )}
                  </div>
                  <div className="text-stone-600 mt-1">{l.body}</div>
                </li>
              ))}
            </ul>
          )}

          <h2 className="text-xs uppercase tracking-wide text-stone-500 mt-5 mb-2">Outside this case</h2>
          <dl className="text-sm grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-stone-500">Credit hold</dt>
            <dd>
              {effects.credit_hold
                ? effects.credit_hold.released_at
                  ? `released (was until ${effects.credit_hold.until})`
                  : `on until ${effects.credit_hold.until} · §1024.35(i)(1)`
                : "none"}
            </dd>
            <dt className="text-stone-500">Ledger</dt>
            <dd>
              {effects.ledger.length === 0
                ? "no postings"
                : effects.ledger.map((a) => (
                    <div key={a.id} className="font-mono text-xs">
                      {a.amount} {a.memo} {a.reversed_at && <span className="text-red-700">REVERSED</span>}
                    </div>
                  ))}
            </dd>
            <dt className="text-stone-500">Sagas</dt>
            <dd>
              {effects.sagas.length === 0
                ? "none"
                : effects.sagas.map((s) => (
                    <div key={s.id} className="text-xs">
                      {s.kind} · <b>{s.state}</b> at {s.step} · attempts {s.attempts}
                      {s.last_error && <span className="text-red-700"> · {s.last_error}</span>}
                    </div>
                  ))}
            </dd>
          </dl>
        </section>

        <section className="bg-white border border-stone-200 rounded p-4">
          <h2 className="text-xs uppercase tracking-wide text-stone-500 mb-2">Audit trail · {audit.length}</h2>
          <ol className="text-xs space-y-1 font-mono max-h-96 overflow-auto">
            {audit.map((a, i) => (
              <li key={i} className="grid grid-cols-[150px_150px_1fr] gap-2">
                <span className="text-stone-400">{a.at.slice(0, 19).replace("T", " ")}</span>
                <span className={a.actor.startsWith("system:") || a.actor.startsWith("llm:") ? "text-stone-500" : "text-blue-700"}>{a.actor}</span>
                <span>
                  {a.action}
                  {Object.keys(a.detail).length > 0 && (
                    <span className="text-stone-400"> {JSON.stringify(a.detail).slice(0, 120)}</span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}
