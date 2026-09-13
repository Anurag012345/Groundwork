import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  // Fixed allowlist: this route cannot become an arbitrary URL proxy or expose internal callbacks.
  const route = path.join("/");
  const allowed = route === "v1/me" || route === "v1/knowledge-bases" ||
    route === "v1/chat" || route === "v1/chat/stream" ||
    /^v1\/knowledge-bases\/[0-9a-f-]{36}(?:\/documents)?$/i.test(route) ||
    /^v1\/ingestion-jobs\/[0-9a-f-]{36}(?:\/process)?$/i.test(route);
  if (!allowed) return Response.json({ detail: "Not found" }, { status: 404 });
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("Authorization", authorization);
  try {
    const timeout = route.startsWith("v1/chat") || route.endsWith("/process") ? 120000 : 15000;
    const response = await fetch(new URL(route, (process.env.API_BASE_URL || "http://127.0.0.1:8000") + "/"), {
      method: request.method, headers,
      body: request.method === "POST" ? await request.arrayBuffer() : undefined,
      cache: "no-store", signal: AbortSignal.timeout(timeout),
    });
    return new Response(response.body, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") || "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ detail: "The API is unavailable. Start the backend and database, then try again." },
      { status: 503 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
