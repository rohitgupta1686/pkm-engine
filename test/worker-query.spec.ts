// test/worker-query.spec.ts — Vitest suite for worker-query.js (QURY-01..04).
//
// Bindings available from wrangler-query.toml (miniflare):
//   PKM_KEY, TURSO_URL, TURSO_TOKEN, OPENAI_API_KEY (injected by vitest.config.query.ts)
//   AI, VECTORIZE (overridden per-test via env property assignment)
//
// All outbound fetch calls (Turso, OpenAI) are intercepted via globalThis.fetch override.
// AI and Vectorize bindings are replaced with stub objects before each test.

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { exports, env } from "cloudflare:workers";

const ORIG_FETCH = globalThis.fetch;

// ---------------------------------------------------------------------------
// Mock AI + Vectorize bindings
// ---------------------------------------------------------------------------

const MOCK_VEC = new Array(768).fill(0.05);

const MOCK_AI = {
  run: async (_model: string, _opts: unknown) => ({
    data: [MOCK_VEC],
    shape: [1, 768],
  }),
};

const MOCK_VECTORIZE_MATCH = {
  id: "clm_abc123",
  score: 0.95,
  metadata: { source_id: "src_xyz", raw_path: "raw/example.md" },
};

const MOCK_VECTORIZE = {
  query: async (_vec: number[], _opts: unknown) => ({
    matches: [MOCK_VECTORIZE_MATCH],
  }),
};

const MOCK_VECTORIZE_EMPTY = {
  query: async (_vec: number[], _opts: unknown) => ({ matches: [] }),
};

// ---------------------------------------------------------------------------
// Turso + OpenAI fetch mock
// ---------------------------------------------------------------------------

const MOCK_TURSO_ROW = {
  id: "clm_abc123",
  statement: "Operating leverage amplifies profit growth when fixed costs are covered.",
  source_title: "Operating Leverage and Business Scalability",
  raw_path: "raw/example.md",
  url: "https://example.com/operating-leverage",
};

function buildTursoResponse(row: typeof MOCK_TURSO_ROW) {
  const cols = Object.keys(row).map((name) => ({ name, decltype: "TEXT" }));
  const rows = [Object.values(row).map((v) => ({ type: "text", value: v ?? "" }))];
  return JSON.stringify({
    baton: null,
    results: [
      {
        type: "ok",
        response: {
          type: "execute",
          result: { cols, rows, affected_row_count: 0, last_insert_rowid: null },
        },
      },
      { type: "ok", response: { type: "close" } },
    ],
  });
}

function buildOpenAIResponse(content: string) {
  return JSON.stringify({
    choices: [{ message: { role: "assistant", content } }],
    usage: { prompt_tokens: 50, completion_tokens: 80 },
  });
}

class HttpMock {
  tursoCalls = 0;
  openaiCalls = 0;
  tursoBody = buildTursoResponse(MOCK_TURSO_ROW);
  openaiBody = buildOpenAIResponse("Operating leverage [1] amplifies profits as fixed costs are spread over more revenue.");

  fetch = async (input: RequestInfo | URL, _init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : (input as URL).href ?? (input as Request).url;
    if (url.includes("/v2/pipeline")) {
      this.tursoCalls++;
      return new Response(this.tursoBody, { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.includes("api.openai.com")) {
      this.openaiCalls++;
      return new Response(this.openaiBody, { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response(`unmocked fetch: ${url}`, { status: 500 });
  };
}

let mock: HttpMock;

function queryReq(q: string, headers: Record<string, string> = {}): Request {
  return new Request(`http://x/query?q=${encodeURIComponent(q)}`, {
    method: "GET",
    headers: { "X-PKM-Key": "test-shared-secret", ...headers },
  });
}

function queryPostReq(q: string, headers: Record<string, string> = {}): Request {
  return new Request("http://x/query", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-PKM-Key": "test-shared-secret", ...headers },
    body: JSON.stringify({ q }),
  });
}

beforeEach(() => {
  mock = new HttpMock();
  globalThis.fetch = mock.fetch as unknown as typeof fetch;
  // Override CF bindings with stubs so tests run without a real CF account.
  (env as Record<string, unknown>).AI = MOCK_AI;
  (env as Record<string, unknown>).VECTORIZE = MOCK_VECTORIZE;
});

afterEach(() => {
  globalThis.fetch = ORIG_FETCH;
  delete (env as Record<string, unknown>).AI;
  delete (env as Record<string, unknown>).VECTORIZE;
});

// ---------------------------------------------------------------------------
// Auth tests
// ---------------------------------------------------------------------------

describe("worker-query — auth", () => {
  it("401 when X-PKM-Key header is missing", async () => {
    const r = await exports.default.fetch(
      new Request("http://x/query?q=test", { method: "GET" }),
    );
    expect(r.status).toBe(401);
  });

  it("401 when X-PKM-Key is wrong", async () => {
    const r = await exports.default.fetch(
      new Request("http://x/query?q=test", {
        method: "GET",
        headers: { "X-PKM-Key": "wrong-key" },
      }),
    );
    expect(r.status).toBe(401);
    // No upstream calls on auth failure
    expect(mock.tursoCalls).toBe(0);
    expect(mock.openaiCalls).toBe(0);
  });

  it("Access-Control-Allow-Origin: * on 401", async () => {
    const r = await exports.default.fetch(
      new Request("http://x/query?q=test", { method: "GET" }),
    );
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  it("204 CORS preflight", async () => {
    const r = await exports.default.fetch(
      new Request("http://x/query", { method: "OPTIONS" }),
    );
    expect(r.status).toBe(204);
    expect(r.headers.get("Access-Control-Allow-Methods")).toContain("GET");
  });
});

// ---------------------------------------------------------------------------
// Query param validation
// ---------------------------------------------------------------------------

describe("worker-query — input validation", () => {
  it("400 when q param is missing on GET", async () => {
    const r = await exports.default.fetch(
      new Request("http://x/query", {
        method: "GET",
        headers: { "X-PKM-Key": "test-shared-secret" },
      }),
    );
    expect(r.status).toBe(400);
  });

  it("400 when q is empty string on GET", async () => {
    const r = await exports.default.fetch(
      new Request("http://x/query?q=", {
        method: "GET",
        headers: { "X-PKM-Key": "test-shared-secret" },
      }),
    );
    expect(r.status).toBe(400);
  });

  it("400 on POST with invalid JSON", async () => {
    const r = await exports.default.fetch(
      new Request("http://x/query", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-PKM-Key": "test-shared-secret" },
        body: "not json",
      }),
    );
    expect(r.status).toBe(400);
  });

  it("405 on unsupported method", async () => {
    const r = await exports.default.fetch(
      new Request("http://x/query", {
        method: "DELETE",
        headers: { "X-PKM-Key": "test-shared-secret" },
      }),
    );
    expect(r.status).toBe(405);
  });
});

// ---------------------------------------------------------------------------
// Happy path: GET query
// ---------------------------------------------------------------------------

describe("worker-query — happy path", () => {
  it("GET /query?q=... returns 200 with answer + citations (QURY-02)", async () => {
    const r = await exports.default.fetch(queryReq("what is operating leverage"));
    expect(r.status).toBe(200);
    const body = await r.json() as { answer: string; citations: unknown[] };
    expect(typeof body.answer).toBe("string");
    expect(body.answer.length).toBeGreaterThan(0);
    expect(Array.isArray(body.citations)).toBe(true);
    expect(body.citations.length).toBeGreaterThan(0);
  });

  it("POST /query {q} returns 200 with same shape", async () => {
    const r = await exports.default.fetch(queryPostReq("what is operating leverage"));
    expect(r.status).toBe(200);
    const body = await r.json() as { answer: string; citations: unknown[] };
    expect(typeof body.answer).toBe("string");
    expect(Array.isArray(body.citations)).toBe(true);
  });

  it("citations have required fields: id, statement, source_title, raw_path, url (QURY-03)", async () => {
    const r = await exports.default.fetch(queryReq("operating leverage"));
    const body = await r.json() as { citations: Record<string, string>[] };
    expect(body.citations.length).toBeGreaterThan(0);
    for (const c of body.citations) {
      expect(typeof c.id).toBe("string");
      expect(typeof c.statement).toBe("string");
      expect(typeof c.source_title).toBe("string");
      expect(typeof c.raw_path).toBe("string");
      // url may be null if the source has no URL — allow null or string
      expect(c.url === null || typeof c.url === "string").toBe(true);
    }
  });

  it("raw_path in citations has expected format (QURY-03 validity check)", async () => {
    const r = await exports.default.fetch(queryReq("operating leverage"));
    const body = await r.json() as { citations: { raw_path: string }[] };
    for (const c of body.citations) {
      // raw_path must be a vault-relative path starting with raw/
      expect(c.raw_path.startsWith("raw/")).toBe(true);
    }
  });

  it("AI.run called with correct embed model", async () => {
    const calledModels: string[] = [];
    (env as Record<string, unknown>).AI = {
      run: async (model: string, _opts: unknown) => {
        calledModels.push(model);
        return { data: [MOCK_VEC], shape: [1, 768] };
      },
    };

    await exports.default.fetch(queryReq("test question"));
    expect(calledModels).toEqual(["@cf/baai/bge-base-en-v1.5"]);
  });

  it("VECTORIZE.query called with topK:12", async () => {
    const capturedOpts: unknown[] = [];
    (env as Record<string, unknown>).VECTORIZE = {
      query: async (_vec: number[], opts: unknown) => {
        capturedOpts.push(opts);
        return { matches: [MOCK_VECTORIZE_MATCH] };
      },
    };

    await exports.default.fetch(queryReq("test question"));
    expect(capturedOpts.length).toBe(1);
    expect((capturedOpts[0] as { topK: number }).topK).toBe(12);
  });

  it("Turso libsql HTTP pipeline endpoint is called (not direct SQL over TCP)", async () => {
    await exports.default.fetch(queryReq("operating leverage"));
    expect(mock.tursoCalls).toBe(1);
  });

  it("OpenAI synthesis endpoint is called once", async () => {
    await exports.default.fetch(queryReq("operating leverage"));
    expect(mock.openaiCalls).toBe(1);
  });

  it("Content-Type: application/json on 200 response", async () => {
    const r = await exports.default.fetch(queryReq("operating leverage"));
    expect(r.headers.get("Content-Type")).toContain("application/json");
  });

  it("Access-Control-Allow-Origin: * on 200 response", async () => {
    const r = await exports.default.fetch(queryReq("operating leverage"));
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe("*");
  });
});

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

describe("worker-query — edge cases", () => {
  it("200 with empty citations when Vectorize returns no matches", async () => {
    (env as Record<string, unknown>).VECTORIZE = MOCK_VECTORIZE_EMPTY;

    const r = await exports.default.fetch(queryReq("obscure topic with no results"));
    expect(r.status).toBe(200);
    const body = await r.json() as { answer: string; citations: unknown[] };
    expect(body.citations).toEqual([]);
    expect(typeof body.answer).toBe("string");
    // When there are no matches, Turso and OpenAI must NOT be called
    expect(mock.tursoCalls).toBe(0);
    expect(mock.openaiCalls).toBe(0);
  });
});
