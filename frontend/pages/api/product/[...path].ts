import type { NextApiRequest, NextApiResponse } from "next";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

// Keep uploads and SSE streaming. Pages API exposes the actual TCP peer;
// App Router's Web Request only exposes caller-controlled Host/forwarded headers.
export const config = { api: { bodyParser: false, responseLimit: false } };

export default async function proxy(request: NextApiRequest, response: NextApiResponse) {
  const peer = request.socket?.remoteAddress;
  if (!peer || !["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(peer)) {
    response.status(403).json({ detail: "产品服务 仅供本机访问" });
    return;
  }
  const origin = request.headers.origin;
  const host = request.headers.host;
  let localOrigin = false;
  try {
    const hostUrl = new URL(`http://${host}`);
    localOrigin = !!host && hostUrl.host === host &&
      ["localhost", "127.0.0.1", "[::1]"].includes(hostUrl.hostname) &&
      (!origin || (new URL(origin).host === host && ["http:", "https:"].includes(new URL(origin).protocol)));
  } catch { /* malformed and opaque origins are not local */ }
  if (!localOrigin) {
    response.status(403).json({ detail: "跨来源请求被拒绝" });
    return;
  }
  if (request.method !== "GET" && request.method !== "POST") {
    response.setHeader("Allow", "GET, POST");
    response.status(405).end();
    return;
  }
  const path = request.query.path;
  if (!Array.isArray(path) || !path.length || path.some((part) => !/^[a-zA-Z0-9_.-]+$/.test(part) || part === "." || part === "..")) {
    response.status(400).json({ detail: "路径无效" });
    return;
  }
  let backend: URL;
  try { backend = new URL(process.env.PRODUCT_API_ORIGIN ?? "http://127.0.0.1:8000"); }
  catch { response.status(503).json({ detail: "产品服务 后端配置无效" }); return; }
  if (!["localhost", "127.0.0.1", "[::1]"].includes(backend.hostname) ||
      !["http:", "https:"].includes(backend.protocol) || backend.username || backend.password) {
    response.status(503).json({ detail: "产品服务 后端必须是本机服务" });
    return;
  }
  const headers = new Headers();
  for (const key of ["content-type", "idempotency-key"]) {
    const value = request.headers[key];
    if (typeof value === "string") headers.set(key, value);
  }
  const controller = new AbortController();
  const abort = () => controller.abort();
  request.once("aborted", abort);
  response.once("close", abort);
  try {
    const search = new URL(request.url ?? "/", "http://localhost").search;
    const upstream = await fetch(new URL(`/api/product/${path.map(encodeURIComponent).join("/")}${search}`, backend), {
      method: request.method, headers, cache: "no-store", redirect: "error",
      body: request.method === "POST" ? request : undefined,
      signal: controller.signal, duplex: "half",
    } as RequestInit & { duplex: string });
    response.status(upstream.status);
    for (const key of ["content-type", "content-disposition", "content-security-policy", "x-content-type-options"]) {
      const value = upstream.headers.get(key);
      if (value) response.setHeader(key, value);
    }
    response.setHeader("Cache-Control", "no-store, no-transform");
    response.flushHeaders();
    if (upstream.body) await pipeline(Readable.fromWeb(upstream.body as import("node:stream/web").ReadableStream), response);
    else response.end();
  } catch {
    if (!response.headersSent && !response.destroyed) {
      response.status(503).json({ detail: "产品服务 后端不可用，请启动本机 API 服务" });
    } else if (!response.destroyed) response.destroy();
  } finally {
    request.off("aborted", abort);
    response.off("close", abort);
  }
}
