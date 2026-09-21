const TONE: Record<string, string> = {
  RECEIVED: "bg-stone-200 text-stone-800",
  TRIAGE: "bg-violet-100 text-violet-800",
  ACK_PENDING: "bg-amber-100 text-amber-800",
  EXCEPTION_REVIEW: "bg-orange-100 text-orange-800",
  INVESTIGATING: "bg-blue-100 text-blue-800",
  EXTENDED: "bg-blue-100 text-blue-800",
  RESPONDED: "bg-emerald-100 text-emerald-800",
  DOCS_REQUESTED: "bg-blue-100 text-blue-800",
  PAYOFF_REQUEST: "bg-teal-100 text-teal-800",
  PAYOFF_REASONABLE_TIME: "bg-teal-100 text-teal-800",
  CLOSED: "bg-stone-100 text-stone-500",
  NOT_COVERED: "bg-stone-100 text-stone-500",
  ROUTED_LOSS_MIT: "bg-stone-100 text-stone-500",
  EARLY_RESOLVED: "bg-emerald-100 text-emerald-800",
};

export function StatusChip({ status }: { status: string }) {
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${TONE[status] ?? "bg-stone-200"}`}>{status}</span>;
}

export function ClockChip({ status }: { status: string }) {
  const tone =
    status === "PENDING" ? "bg-amber-100 text-amber-800" : status === "FIRED" ? "bg-red-100 text-red-800" : status === "SATISFIED" ? "bg-emerald-100 text-emerald-800" : "bg-stone-100 text-stone-500";
  return <span className={`rounded px-1.5 py-0.5 text-xs ${tone}`}>{status}</span>;
}
