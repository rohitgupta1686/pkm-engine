// test/worker-clip.spec.ts — Vitest suite for worker-clip.js (CLIP-01..05 + MVP-02).
// Runs inside workerd via @cloudflare/vitest-pool-workers. Outbound fetch to
// api.github.com is intercepted by overriding the shared-isolate globalThis.fetch
// (the pool runs the main worker in the same isolate/context as tests, so global
// mocks apply to it). R2 assertions use the real env.RAW_BUCKET preview binding.
// No Cloudflare account, no PAT, no network required.

import { describe, it, expect, afterEach, beforeEach } from "vitest";
import { exports, env } from "cloudflare:workers";
import { reset } from "cloudflare:test";

const ORIG_FETCH = globalThis.fetch;

interface PutRecord {
  url: string;
  body: { message: string; content: string; sha?: string };
  auth: string;
}
interface DispatchRecord {
  url: string;
  body: { event_type: string; client_payload: { path: string } };
  auth: string;
}

// GitHub Contents API + dispatch mock. getSequence controls successive GET /contents
// responses (404 = new path, 200 = already exists -> dedup branch).
class GhMock {
  putCalls: PutRecord[] = [];
  dispatchCalls: DispatchRecord[] = [];
  getCalls = 0;
  private getSequence: number[];
  constructor(getSequence: number[] = [404]) {
    this.getSequence = [...getSequence];
  }
  fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : (input as URL).url ?? (input as Request).url;
    const method = ((init?.method as string) || "GET").toUpperCase();
    const headers: Record<string, string> = (init?.headers as Record<string, string>) || {};

    if (url.includes("/contents/") && method === "GET") {
      this.getCalls += 1;
      const status = this.getSequence.shift() ?? 404;
      return new Response("{}", { status });
    }
    if (url.includes("/contents/") && method === "PUT") {
      this.putCalls.push({
        url,
        body: init?.body ? JSON.parse(init.body as string) : ({} as any),
        auth: headers.Authorization || headers.authorization || "",
      });
      return new Response('{"commit":{"sha":"abc"}}', {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.endsWith("/dispatches") && method === "POST") {
      this.dispatchCalls.push({
        url,
        body: init?.body ? JSON.parse(init.body as string) : ({} as any),
        auth: headers.Authorization || headers.authorization || "",
      });
      return new Response(null, { status: 204 });
    }
    return new Response(`unmocked ${method} ${url}`, { status: 500 });
  };
}

function decodeB64Utf8(b64: string): string {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder("utf-8").decode(bytes);
}

function clipReq(payload: unknown, headers: Record<string, string> = {}): Request {
  return new Request("http://x/clip", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(payload),
  });
}

let mock: GhMock;

beforeEach(() => {
  mock = new GhMock();
  globalThis.fetch = mock.fetch as any;
});

afterEach(async () => {
  globalThis.fetch = ORIG_FETCH;
  await reset(); // clear R2 preview bucket state between tests
});

describe("worker-clip", () => {
  it("401 when X-PKM-Key missing (CORS present, no upstream call)", async () => {
    const r = await exports.default.fetch(clipReq({ url: "https://example.com/a", text: "hi" }));
    expect(r.status).toBe(401);
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe("*");
    expect(mock.putCalls.length).toBe(0);
    expect(mock.dispatchCalls.length).toBe(0);
  });

  it("401 when X-PKM-Key wrong (no upstream call)", async () => {
    const r = await exports.default.fetch(
      clipReq({ url: "https://example.com/a", text: "hi" }, { "X-PKM-Key": "wrong" }),
    );
    expect(r.status).toBe(401);
    expect(mock.putCalls.length).toBe(0);
    expect(mock.dispatchCalls.length).toBe(0);
  });

  it("200 on valid POST: path matches raw/<ts>__<src>__<title>__<hash6>.md and GitHub GET called (CLIP-01)", async () => {
    const r = await exports.default.fetch(
      clipReq(
        { url: "https://example.com/page", type: "Article", text: "hello world body", title: "My Title" },
        { "X-PKM-Key": "test-shared-secret" },
      ),
    );
    expect(r.status).toBe(200);
    const body = await r.json() as { ok: boolean; path: string; deduped: boolean };
    expect(body.ok).toBe(true);
    expect(body.path).toMatch(/^raw\/\d{8}T\d{4}Z__[a-z0-9-]+__[a-z0-9-]+__[0-9a-f]{6}\.md$/);
    expect(mock.getCalls).toBe(1); // GitHub GET contents was called
  });

  it("405 on GET (non-POST/OPTIONS)", async () => {
    const r = await exports.default.fetch(new Request("http://x/clip", { method: "GET" }));
    expect(r.status).toBe(405);
    expect(mock.putCalls.length).toBe(0);
  });

  it("OPTIONS preflight returns 204 with Access-Control-Allow-Headers containing X-PKM-Key", async () => {
    const r = await exports.default.fetch(new Request("http://x/clip", { method: "OPTIONS" }));
    expect(r.status).toBe(204);
    expect(r.headers.get("Access-Control-Allow-Headers")).toContain("X-PKM-Key");
    expect(mock.putCalls.length).toBe(0);
  });

  it("413 when text.length > 5_000_000 (rejected before any GitHub/R2 call)", async () => {
    const big = "a".repeat(5_000_001);
    const r = await exports.default.fetch(
      clipReq(
        { url: "https://example.com/a", type: "Article", text: big, title: "Big" },
        { "X-PKM-Key": "test-shared-secret" },
      ),
    );
    expect(r.status).toBe(413);
    expect(mock.putCalls.length).toBe(0);
    expect(mock.dispatchCalls.length).toBe(0);
    expect(mock.getCalls).toBe(0);
    const r2list = await env.RAW_BUCKET.list();
    expect(r2list.objects.length).toBe(0); // no R2 put before the size guard
  });

  it("R2 offload (CLIP-03): >200K mirrored to R2, r2key in front matter, body STILL full text (Q1)", async () => {
    const big = "X".repeat(200_001);
    const r = await exports.default.fetch(
      clipReq(
        { url: "https://example.com/long", type: "Article", text: big, title: "Long One" },
        { "X-PKM-Key": "test-shared-secret" },
      ),
    );
    expect(r.status).toBe(200);

    // R2 received the blob.
    const r2list = await env.RAW_BUCKET.list();
    expect(r2list.objects.length).toBe(1);
    const r2key = r2list.objects[0].key;
    expect(r2key.startsWith("blobs/")).toBe(true);
    const blob = await env.RAW_BUCKET.get(r2key);
    expect(blob).not.toBe(null);
    const blobText = await blob!.text();
    expect(blobText.length).toBe(200_001);
    expect(blobText).toBe(big);

    // Committed PUT body: front matter contains r2key: blobs/ ...
    expect(mock.putCalls.length).toBe(1);
    const decoded = decodeB64Utf8(mock.putCalls[0].body.content);
    expect(decoded).toContain("r2key: blobs/");

    // Q1 invariant: decoded body STILL contains the full 200_001-char text (not a pointer).
    expect(decoded.length).toBeGreaterThanOrEqual(200_001);
    expect(decoded).toContain(big);
    expect(decoded).not.toContain("[blob in R2:");
  });

  it("<=200K: no R2 put and no r2key in front matter", async () => {
    const text = "Y".repeat(200_000); // exactly at threshold boundary (NOT >200K)
    const r = await exports.default.fetch(
      clipReq(
        { url: "https://example.com/mid", type: "Article", text, title: "Mid" },
        { "X-PKM-Key": "test-shared-secret" },
      ),
    );
    expect(r.status).toBe(200);
    const r2list = await env.RAW_BUCKET.list();
    expect(r2list.objects.length).toBe(0); // no R2 put
    expect(mock.putCalls.length).toBe(1);
    const decoded = decodeB64Utf8(mock.putCalls[0].body.content);
    expect(decoded).not.toContain("r2key:");
    expect(decoded).toContain(text); // body has full text
  });

  it("idempotent re-clip (MVP-02/Q3): PUT once across two clips, dispatch twice, deduped:true on 2nd", async () => {
    // getSequence: first clip GET -> 404 (create), second clip GET -> 200 (exists -> dedup).
    mock = new GhMock([404, 200]);
    globalThis.fetch = mock.fetch as any;

    const payload = { url: "https://example.com/same", type: "Article", text: "same body content", title: "Same Title" };
    const r1 = await exports.default.fetch(clipReq(payload, { "X-PKM-Key": "test-shared-secret" }));
    const b1 = await r1.json() as { deduped: boolean; path: string };
    expect(r1.status).toBe(200);
    expect(b1.deduped).toBe(false);

    const r2 = await exports.default.fetch(clipReq(payload, { "X-PKM-Key": "test-shared-secret" }));
    const b2 = await r2.json() as { deduped: boolean; path: string };
    expect(r2.status).toBe(200);
    expect(b2.deduped).toBe(true);

    // PUT called exactly once across both clips.
    expect(mock.putCalls.length).toBe(1);
    // Dispatch fired on BOTH clips (Q3: skip-commit-still-dispatch).
    expect(mock.dispatchCalls.length).toBe(2);
  });

  it("dispatch contract (CLIP-05): POST /dispatches body has event_type === ingest and client_payload.path === committed path", async () => {
    const r = await exports.default.fetch(
      clipReq(
        { url: "https://example.com/d", type: "Article", text: "dispatch body", title: "Dispatched" },
        { "X-PKM-Key": "test-shared-secret" },
      ),
    );
    expect(r.status).toBe(200);
    const b = await r.json() as { path: string };
    expect(mock.dispatchCalls.length).toBe(1);
    const d = mock.dispatchCalls[0];
    expect(d.url).toMatch(/\/repos\/rohitgupta1686\/pkm-engine\/dispatches$/);
    expect(d.body.event_type).toBe("ingest");
    expect(d.body.client_payload.path).toBe(b.path);
  });

  it("commit contract (CLIP-04): PUT /contents/<path> body has message + base64 content; Authorization Bearer test-pat", async () => {
    const r = await exports.default.fetch(
      clipReq(
        { url: "https://example.com/c", type: "Article", text: "commit body", title: "Committed" },
        { "X-PKM-Key": "test-shared-secret" },
      ),
    );
    expect(r.status).toBe(200);
    const b = await r.json() as { path: string };
    expect(mock.putCalls.length).toBe(1);
    const put = mock.putCalls[0];
    expect(put.url).toContain(`/contents/${b.path}`);
    expect(put.body.message).toMatch(/^clip:/);
    expect(typeof put.body.content).toBe("string");
    // base64 round-trips back to a markdown string containing the front matter + body.
    const decoded = decodeB64Utf8(put.body.content);
    expect(decoded.startsWith("---")).toBe(true);
    expect(put.auth).toBe("Bearer test-pat");
  });

  it("front-matter field-name contract (Pitfall 2): decoded PUT content has title/type/url/author/date_saved and NO bare ^date: line", async () => {
    const r = await exports.default.fetch(
      clipReq(
        { url: "https://example.com/fm", type: "Article", text: "field name contract body", title: "Field Check" },
        { "X-PKM-Key": "test-shared-secret" },
      ),
    );
    expect(r.status).toBe(200);
    expect(mock.putCalls.length).toBe(1);
    const decoded = decodeB64Utf8(mock.putCalls[0].body.content);

    // run_ingest parses these fields:
    expect(decoded).toContain("title:");
    expect(decoded).toContain("type:");
    expect(decoded).toContain("url:");
    expect(decoded).toContain("author:");
    expect(decoded).toContain("date_saved:");

    // The skeleton's WRONG field must NOT appear as a bare `date:` line.
    // `^date:` does NOT match `date_saved:` (after "date" comes "_", not ":").
    expect(/^date:/m.test(decoded)).toBe(false);
  });
});