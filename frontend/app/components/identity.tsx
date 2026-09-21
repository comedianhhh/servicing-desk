"use client";

import { setOperator, useIdentity } from "./use-operator";

const ROLE_TONE: Record<string, string> = {
  readonly: "bg-stone-100 text-stone-600",
  operator: "bg-blue-100 text-blue-800",
  supervisor: "bg-violet-100 text-violet-800",
};

/** Header control: who this tab is acting as, and what that identity may do. Names come from the server's
 * DESK_OPERATORS; the role comes from the API for the chosen name. One place, every page. */
export function Identity() {
  const { names, name, role } = useIdentity();
  return (
    <label className="ml-auto flex items-center gap-2 text-xs text-stone-500">
      acting as
      <select className="border rounded px-1.5 py-0.5 text-sm text-stone-900" value={name} onChange={(e) => setOperator(e.target.value)}>
        {names.length === 0 && <option value="">no operators configured</option>}
        {names.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
      {role && <span className={`rounded px-1.5 py-0.5 ${ROLE_TONE[role] ?? ""}`}>{role}</span>}
    </label>
  );
}
