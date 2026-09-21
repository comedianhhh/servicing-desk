// Same-origin proxy for client components: the browser never talks to the desk API directly, so there is
// no CORS to configure and the API base URL stays server-side. Bodies, content types and status codes pass
// through untouched — a 409 (stale version), a 422 (missing letter field) or a PNG original arrive as-is.
import { API_URL } from "@/lib/api";

async function forward(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const url = `${API_URL}/${path.join("/")}${new URL(req.url).search}`;
  const headers: Record<string, string> = {};
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
