import { afterEach, describe, expect, it, vi } from "vitest";
import type { NextApiRequest, NextApiResponse } from "next";
import { Readable, Writable } from "node:stream";
import proxy, { config } from "@/pages/api/review/[...path]";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
function request(headers: Record<string, string> = {}, method = "GET", peer: string | null = "127.0.0.1", body = "") {
  return Object.assign(Readable.from(body ? [Buffer.from(body)] : []), {
    socket: { remoteAddress: peer }, headers: { host: "127.0.0.1:3000", ...headers },
    method, query: { path: ["runs"] }, url: "/api/review/runs",
  }) as unknown as NextApiRequest;
}
function response() {
  const chunks: Buffer[] = [];
  const headers = new Map<string, string>();
  let sent = false;
  const stream = new Writable({ write(chunk, _encoding, done) { chunks.push(Buffer.from(chunk)); done(); } });
  const res = Object.assign(stream, {
    statusCode: 200,
    status(code: number) { res.statusCode = code; return res; },
    json(body: unknown) { sent = true; res.end(JSON.stringify(body)); return res; },
    setHeader(key: string, value: string) { headers.set(key.toLowerCase(), value); return res; },
    flushHeaders() { sent = true; },
  });
  Object.defineProperty(res, "headersSent", { get: () => sent });
  return { res: res as unknown as NextApiResponse, headers, text: () => Buffer.concat(chunks).toString() };
}

describe("loopback Review proxy", () => {
  it.each(["203.0.113.10", "192.168.1.4", "2001:db8::1", "::ffff:192.168.1.4", null])("rejects peer %s despite forged local headers and absent Origin", async (peer) => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    for (const method of ["GET", "POST"]) {
      const { res } = response();
      await proxy(request({ host: "localhost:3000", "x-forwarded-for": "127.0.0.1", "x-real-ip": "::1", "x-forwarded-host": "localhost:3000", forwarded: "for=127.0.0.1;host=localhost:3000" }, method, peer), res);
      expect(res.statusCode).toBe(403);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each(["http://evil.example", "null", "not-a-url", "file://127.0.0.1:3000"])("rejects origin %s without forwarding", async (origin) => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const { res } = response();
    await proxy(request({ origin }, "POST"), res);
    expect(res.statusCode).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each(["127.0.0.1", "::1", "::ffff:127.0.0.1"])("streams SSE from actual loopback peer %s", async (peer) => {
    const text = "event: update\ndata: {}\n\n";
    const fetcher = vi.fn().mockResolvedValue(new Response(text, { headers: { "Content-Type": "text/event-stream" } }));
    vi.stubGlobal("fetch", fetcher);
    const output = response();
    await proxy(request({ origin: "http://127.0.0.1:3000", "last-event-id": "12", authorization: "not-forwarded", "x-forwarded-for": "203.0.113.1" }, "GET", peer), output.res);
    expect(output.res.statusCode).toBe(200);
    expect(output.headers.get("content-type")).toContain("text/event-stream");
    expect(output.text()).toBe(text);
    const headers = fetcher.mock.calls[0][1].headers;
    expect(headers.get("last-event-id")).toBe("12");
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("x-forwarded-for")).toBeNull();
  });
  it("preserves raw POST upload and rerun query without buffering the body", async () => {
    const req = request({ "content-type": "multipart/form-data; boundary=test" }, "POST", "127.0.0.1", "raw-upload");
    req.url = "/api/review/runs/id/rerun?from_stage=visual";
    req.query.path = ["runs", "id", "rerun"];
    const fetcher = vi.fn().mockImplementation(async (_url, init) => {
      let body = "";
      for await (const chunk of init.body) body += chunk.toString();
      expect(body).toBe("raw-upload");
      return new Response("{}", { status: 202 });
    });
    vi.stubGlobal("fetch", fetcher);
    const { res } = response();
    await proxy(req, res);
    expect(res.statusCode).toBe(202);
    expect(String(fetcher.mock.calls[0][0])).toBe("http://127.0.0.1:8000/api/review/runs/id/rerun?from_stage=visual");
    expect(fetcher.mock.calls[0][1].body).toBe(req);
    expect(config.api.bodyParser).toBe(false);
  });
  it.each(["https://evil.example", "file:///tmp", "http://user:pass@localhost", "invalid"])("rejects backend %s", async (backend) => {
    vi.stubEnv("REVIEW_API_ORIGIN", backend);
    const { res } = response();
    await proxy(request(), res);
    expect(res.statusCode).toBe(503);
  });
  it("rejects traversal before fetch", async () => {
    const req = request(); req.query.path = ["runs", ".."];
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const { res } = response();
    await proxy(req, res);
    expect(res.statusCode).toBe(400);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("aborts upstream when a streaming client disconnects", async () => {
    const cancel = vi.fn();
    const fetcher = vi.fn().mockResolvedValue(new Response(new ReadableStream({ cancel })));
    vi.stubGlobal("fetch", fetcher);
    const { res } = response();
    const pending = proxy(request(), res);
    await vi.waitFor(() => expect(res.headersSent).toBe(true));
    res.destroy();
    await pending;
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    expect(cancel).toHaveBeenCalled();
  });
});
