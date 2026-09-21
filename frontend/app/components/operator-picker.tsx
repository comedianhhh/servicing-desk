"use client";

import { useOperator, useOperatorNames } from "./use-operator";

/** "Acting as" selector. Names come from the server's DESK_OPERATORS; the role behind each name is the
 * API's business — a 403 from it is shown verbatim by whichever form got it. */
export function OperatorPicker({ className = "" }: { className?: string }) {
  const [operator, setOperator] = useOperator();
  const names = useOperatorNames();
  const value = names.includes(operator) ? operator : (names[0] ?? "");
  return (
    <select className={`border rounded px-1 py-0.5 ${className}`} value={value} onChange={(e) => setOperator(e.target.value)}>
      {names.length === 0 && <option value="">no operators configured</option>}
      {names.map((n) => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
    </select>
  );
}

/** The effective name a mutation should be sent as (the stored choice, or the first configured). */
export function useActingOperator(): string {
  const [operator] = useOperator();
  const names = useOperatorNames();
  return names.includes(operator) ? operator : (names[0] ?? "");
}
