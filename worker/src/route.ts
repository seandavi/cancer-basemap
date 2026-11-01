/**
 * Where a request goes. ADR-0001: `/data/` belongs to the bucket, so no page
 * is ever routed under it, and it serves bytes and never redirects (release
 * bundle views and every Hugging Face copy hard-code `/data/` URLs). Every
 * other path is a page.
 */
export type Route =
  | { kind: "data"; key: string; base: string }
  | { kind: "docs" }
  | { kind: "bad" };

export function route(url: URL): Route {
  let path: string;
  try {
    path = decodeURIComponent(url.pathname);
  } catch {
    return { kind: "bad" }; // malformed %-escape, e.g. /data/%E0%A4%A
  }
  if (path === "/data" || path.startsWith("/data/")) {
    return { kind: "data", key: path.slice("/data/".length), base: "/data" };
  }
  return { kind: "docs" };
}

/**
 * Workers static assets answer old pretty URLs (`/guides/x/`) with a 307 to
 * the canonical path. Those moves are permanent, so send a 301: search
 * engines pass link equity and clients may cache it.
 */
export function permanentRedirect(res: Response): Response {
  if (res.status !== 307) return res;
  return new Response(null, { status: 301, headers: res.headers });
}
