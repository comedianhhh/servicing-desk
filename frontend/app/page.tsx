import Link from "next/link";
import { daysUntil, listCases, nextClock, type Case } from "@/lib/api";
import { StatusChip } from "./components/chips";

export const dynamic = "force-dynamic";

const OPEN = new Set(["RECEIVED", "TRIAGE", "ACK_PENDING", "EXCEPTION_REVIEW", "INVESTIGATING", "EXTENDED", "RESPONDED", "DOCS_REQUESTED", "PAYOFF_REQUEST", "PAYOFF_REASONABLE_TIME"]);

function DueBadge({ c }: { c: Case }) {
  const k = nextClock(c);
  if (!k) return <span className="text-stone-400">—</span>;
  const d = daysUntil(k.due_on);
  const tone = d < 0 ? "bg-red-600 text-white" : d <= 2 ? "bg-amber-500 text-white" : "bg-stone-200 text-stone-800";
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${tone}`}>{d < 0 ? `${-d}d overdue` : d === 0 ? "today" : `${d}d`}</span>
      <span className="text-xs text-stone-600">
        {k.kind} · {k.due_on} · <span className="text-stone-400">{k.citation}</span>
      </span>
    </span>
  );
}

export default async function Queue() {
  const cases = await listCases();
  const open = cases.filter((c) => OPEN.has(c.status));
  const closed = cases.filter((c) => !OPEN.has(c.status));
  // Nearest pending clock first; cases with no clock (untriaged) float to the top — they need a human next.
  open.sort((a, b) => {
    const ka = nextClock(a), kb = nextClock(b);
    if (!ka && !kb) return a.created_at.localeCompare(b.created_at);
    if (!ka) return -1;
    if (!kb) return 1;
    return ka.due_on.localeCompare(kb.due_on);
  });

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-lg font-semibold mb-3">
          Queue <span className="text-stone-400 font-normal">· {open.length} open</span>
        </h1>
        <table className="w-full text-sm bg-white border border-stone-200 rounded">
          <thead className="text-left text-xs uppercase tracking-wide text-stone-500">
            <tr>
              <th className="px-3 py-2">Received</th>
              <th className="px-3 py-2">Borrower / loan</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Next deadline</th>
            </tr>
          </thead>
          <tbody>
            {open.map((c) => (
              <tr key={c.id} className="border-t border-stone-100 hover:bg-stone-50">
                <td className="px-3 py-2 whitespace-nowrap">
                  <Link href={`/cases/${c.id}`} className="text-blue-700 hover:underline">
                    {c.received_on}
                  </Link>
                  <span className="ml-2 text-xs text-stone-400">{c.channel}</span>
                </td>
                <td className="px-3 py-2">
                  {c.borrower_name ?? <span className="text-stone-400 italic">untriaged</span>}
                  {c.loan_id && <span className="ml-2 font-mono text-xs text-stone-500">{c.loan_id}</span>}
                </td>
                <td className="px-3 py-2 text-xs">
                  {c.case_type ?? "—"}
                  {c.error_category && <span className="ml-1 text-stone-500">({c.error_category})</span>}
                  {c.rfi_category && <span className="ml-1 text-stone-500">({c.rfi_category})</span>}
                </td>
                <td className="px-3 py-2">
                  <StatusChip status={c.status} />
                </td>
                <td className="px-3 py-2">
                  <DueBadge c={c} />
                </td>
              </tr>
            ))}
            {open.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-stone-400">
                  Nothing open. Run <code>desk-seed</code> to load sample letters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      {closed.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-stone-500 mb-2">Closed / routed · {closed.length}</h2>
          <ul className="text-sm space-y-1">
            {closed.map((c) => (
              <li key={c.id}>
                <Link href={`/cases/${c.id}`} className="text-blue-700 hover:underline">
                  {c.received_on}
                </Link>{" "}
                {c.borrower_name ?? "—"} <StatusChip status={c.status} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
