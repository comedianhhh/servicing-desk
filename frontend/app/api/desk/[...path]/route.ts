// Same-origin proxy for client components: the browser never talks to the desk API directly, so there is
// no CORS to configure and the API base URL stays server-side. Bodies and status codes pass through
// untouched — a 409 (stale version) or 422 (missing letter field) reaches the form as-is.
import { API_URL } from "@/lib/api";

async function forward(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const url = `${API_URL}/${path.join("/")}${new URL(req.url).search}`;
  const init: RequestInit = { method: req.method, headers: { "content-type": "application/json" }, cache: "no-store" };
  if (req.method !== "GET") init.body = await req.text();
  const r = await fetch(url, init);
  return new Response(await r.text(), { status: r.status, headers: { "content-type": "application/json" } });
}

export { forward as GET, forward as POST };
