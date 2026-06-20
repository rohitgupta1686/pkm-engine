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
const EXPECTED_UA = "pkm-clip-worker";

interface PutRecord {
  url: string;
  body: { message: string; content: string; sha?: string };
  auth: string;
  ua: string;
}
interface DispatchRecord {
  url: string;
  body: { event_type: string; client_payload: { path: string } };
  auth: string;
  ua: string;
}

// GitHub Contents API + dispatch mock. PATH-AWARE: a PUT records the committed path
// in a Set, and a later GET for that same path returns 200 (exists -> dedup branch).
// This faithfully models the real GitHub Contents API + the Worker's content-addressed
// path, so identical content -> identical path -> second GET naturally 200s. The earlier
// getSequence:[404,200] hardcode masked the timestamp-in-path dedup bug (05-03 live deploy).
class GhMock {
  putCalls: PutRecord[] = [];
  dispatchCalls: DispatchRecord[] = [];
  getCalls = 0;
  getUAs: string[] = [];
  committedPaths = new Set<string>();

  private extractPath(url: string): string {
    // url forms: .../contents/<path>?ref=main  (GET)  or  .../contents/<path>  (PUT)
    const idx = url.indexOf("/contents/");
    let p = idx >= 0 ? url.slice(idx + "/contents/".length) : url;
    const q = p.indexOf("?");
    if (q >= 0) p = p.slice(0, q);
    return decodeURIComponent(p);
  }

  fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : (input as URL).url ?? (input as Request).url;
    const method = ((init?.method as string) || "GET").toUpperCase();
    const headers: Record<string, string> = (init?.headers as Record<string, string>) || {};
    const ua = headers["User-Agent"] || headers["user-agent"] || "";

    if (url.includes("/contents/") && method === "GET") {
      this.getCalls += 1;
      this.getUAs.push(ua);
      const exists = this.committedPaths.has(this.extractPath(url));
      return new Response("{}", { status: exists ? 200 : 404 });
    }
    if (url.includes("/contents/") && method === "PUT") {
      const path = this.extractPath(url);
      this.committedPaths.add(path);
      this.putCalls.push({
        url,
        body: init?.body ? JSON.parse(init.body as string) : ({} as any),
        auth: headers.Authorization || headers.authorization || "",
        ua,
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
        ua,
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

  it("200 on valid POST: path is content-addressed raw/<src>__<title>__<32hex>.md (NO timestamp), GitHub GET + User-Agent present (CLIP-01)", async () => {
    const r = await exports.default.fetch(
      clipReq(
        { url: "https://example.com/page", type: "Article", text: "hello world body", title: "My Title" },
        { "X-PKM-Key": "test-shared-secret" },
      ),
    );
    expect(r.status).toBe(200);
    const body = await r.json() as { ok: boolean; path: string; deduped: boolean };
    expect(body.ok).toBe(true);
    // Content-addressed: NO timestamp segment, 32-hex (128-bit) content key. This is the
    // contract that makes re-clip dedup work — a timestamp here would be a regression.
    expect(body.path).toMatch(/^raw\/[a-z0-9-]+__[a-z0-9-]+__[0-9a-f]{32}\.md$/);
    expect(mock.getCalls).toBe(1); // GitHub GET contents was called
    // GitHub requires a User-Agent; the Worker must send one on every GitHub request
    // (05-03 live deploy: missing UA -> GitHub 403 "Request forbidden by administrative rules").
    expect(mock.getUAs[0]).toBe(EXPECTED_UA);
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

  it("idempotent re-clip (MVP-02/Q3): same content -> same path -> 2nd GET 200 -> deduped:true, PUT once, dispatch twice, no R2 orphan", async () => {
    // No hardcoded getSequence: the path-aware mock returns 200 on the second GET
    // because the SAME content yields the SAME content-addressed path, which the
    // first clip's PUT recorded. A timestamp in the path would make the paths differ
    // and the second GET would 404 -> this test would FAIL (it did, pre-fix).
    const payload = { url: "https://example.com/same", type: "Article", text: "same body content", title: "Same Title" };
    const r1 = await exports.default.fetch(clipReq(payload, { "X-PKM-Key": "test-shared-secret" }));
    const b1 = await r1.json() as { deduped: boolean; path: string };
    expect(r1.status).toBe(200);
    expect(b1.deduped).toBe(false);

    const r2 = await exports.default.fetch(clipReq(payload, { "X-PKM-Key": "test-shared-secret" }));
    const b2 = await r2.json() as { deduped: boolean; path: string };
    expect(r2.status).toBe(200);
    expect(b2.deduped).toBe(true);
    // Same content-addressed path on both clips (this is the whole point).
    expect(b2.path).toBe(b1.path);

    // PUT called exactly once across both clips; the deduped clip did not rebuild.
    expect(mock.putCalls.length).toBe(1);
    // Dispatch fired on BOTH clips (Q3: skip-commit-still-dispatch).
    expect(mock.dispatchCalls.length).toBe(2);
    // Every GitHub request carried the required User-Agent.
    expect(mock.putCalls[0].ua).toBe(EXPECTED_UA);
    expect(mock.dispatchCalls.every((d) => d.ua === EXPECTED_UA)).toBe(true);

    // R2-after-dedup guard (05-03 defect #3): the deduped clip must not orphan an R2
    // blob even for >200K content. Verify with a large re-clip below in its own test.
  });

  it("R2-after-dedup (05-03 defect #3): a >200K re-clip is deduped and does NOT orphan a second R2 blob", async () => {
    const big = "Z".repeat(200_001);
    const payload = { url: "https://example.com/rebig", type: "Article", text: big, title: "Rebig" };
    const r1 = await exports.default.fetch(clipReq(payload, { "X-PKM-Key": "test-shared-secret" }));
    expect((await r1.json() as { deduped: boolean }).deduped).toBe(false);
    expect((await env.RAW_BUCKET.list()).objects.length).toBe(1);

    const r2 = await exports.default.fetch(clipReq(payload, { "X-PKM-Key": "test-shared-secret" }));
    expect((await r2.json() as { deduped: boolean }).deduped).toBe(true);
    // Only the first clip's blob exists — the deduped re-clip did not put to R2.
    expect((await env.RAW_BUCKET.list()).objects.length).toBe(1);
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