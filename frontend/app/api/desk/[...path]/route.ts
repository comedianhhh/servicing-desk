// Same-origin proxy for client components: the browser never talks to the desk API directly, so there is
// no CORS to configure and the API base URL stays server-side. Bodies, content types and status codes pass
// through untouched — a 409 (stale version), a 422 (missing letter field) or a PNG original arrive as-is.
//
// Identity: the client sends `x-operator: <name>`; this route replaces it with that operator's bearer token
// (lib/operators.ts). A name this UI does not know is a 401 here, before anything reaches the API.
import { API_URL } from "@/lib/api";
import { readToken, tokenFor } from "@/lib/operators";

async function forward(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const url = `${API_URL}/${path.join("/")}${new URL(req.url).search}`;
  const name = req.headers.get("x-operator");
  const token = req.method === "GET" ? (tokenFor(name) ?? readToken()) : tokenFor(name);
  if (!token) return Response.json({ detail: `unknown operator ${name ?? "(none)"}` }, { status: 401 });
  const headers: Record<string, string> = { authorization: `Bearer ${token}` };
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;
  const init: RequestInit & { duplex?: "half" } = { method: req.method, headers, cache: "no-store" };
  if (req.method !== "GET") {
    init.body = req.body;
    init.duplex = "half";
  }
  const r = await fetch(url, init);
  const out = new Headers();
  for (const h of ["content-type", "content-disposition", "content-length"]) {
    const v = r.headers.get(h);
    if (v) out.set(h, v);
  }
  return new Response(r.body, { status: r.status, headers: out });
}

export { forward as GET, forward as POST };
