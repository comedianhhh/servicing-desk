// Server-only: which operators this UI can act as, and the bearer token for each. The browser picks a name;
// the /api/desk proxy swaps it for the token; the token never leaves the server. This stands in for a
// login: a real deployment puts SSO in front of the UI and maps the session to a token (or a JWT the API
// verifies) here, in one place.
//
// DESK_OPERATORS="op-1=tok-op,sup-1=tok-sup,ro-1=tok-ro"   (names/roles are defined on the API side)

const parsed = new Map<string, string>(
  (process.env.DESK_OPERATORS ?? "")
    .split(",")
    .map((e) => e.trim())
    .filter(Boolean)
    .map((e) => {
      const i = e.indexOf("=");
      return [e.slice(0, i).trim(), e.slice(i + 1).trim()] as [string, string];
    }),
);

export const OPERATOR_NAMES = [...parsed.keys()];
export const tokenFor = (name: string | null): string | undefined => (name ? parsed.get(name) : undefined);
/** Server-rendered pages read as the first configured operator; reads need any role. */
export const readToken = (): string | undefined => parsed.values().next().value;
