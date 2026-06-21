// pkm-engine/worker-query.js
// Cloudflare Worker — semantic query endpoint.
//
// GET  /query?q=<text>            — public-style; key in X-PKM-Key header
// POST /query  {q: "..."}         — same auth gate
//
// Flow:
//   1. Auth (same X-PKM-Key constant-time gate as worker-clip.js)
//   2. Embed query via Workers AI binding (same @cf/baai/bge-base-en-v1.5 model as ingest)
//   3. ANN search in Vectorize (top-12 by cosine similarity)
//   4. Fetch claim text + source metadata from Turso via libsql HTTP pipeline API
//   5. Synthesize 2-4 sentence answer + inline [N] citations via OpenAI gpt-5.4-mini
//   6. Return {answer, citations: [{id, statement, source_title, raw_path, url}]}
//
// Security: same timingSafeEqual as worker-clip.js; OPENAI_API_KEY never logged or returned.

const EMBED_MODEL = "@cf/baai/bge-base-en-v1.5";
const TOP_K = 12;
const SYNTH_MODEL = "gpt-5.4-mini-2026-03-17";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-PKM-Key",
  "Access-Control-Max-Age": "86400",
};

function corsResponse(body, init = {}) {
  return new Response(body, {
    ...init,
    headers: { ...(init.headers || {}), "Access-Control-Allow-Origin": "*" },
  });
}

// Constant-time shared-secret compare (same as worker-clip.js).
async function timingSafeEqual(a, b) {
  if (!a || !b) return false;
  const enc = new TextEncoder();
  const [ha, hb] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(a)),
    crypto.subtle.digest("SHA-256", enc.encode(b)),
  ]);
  const va = new Uint8Array(ha);
  const vb = new Uint8Array(hb);
  let diff = 0;
  for (let i = 0; i < va.length; i++) diff |= va[i] ^ vb[i];
  return diff === 0 && a.length === b.length;
}

// libsql HTTP pipeline API (Turso).
// Endpoint: {TURSO_URL}/v2/pipeline
// Args are passed as {type:"text", value:"..."} regardless of SQL type; Turso casts.
async function tursoQuery(tursoUrl, tursoToken, sql, args = []) {
  const base = tursoUrl.replace(/\/+$/, "");
  const url = `${base}/v2/pipeline`;
  const body = {
    requests: [
      {
        type: "execute",
        stmt: {
          sql,
          args: args.map((v) => ({ type: "text", value: String(v === null ? "" : v) })),
        },
      },
      { type: "close" },
    ],
  };
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${tursoToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`Turso query failed: ${resp.status} ${text.slice(0, 200)}`);
  }
  const data = await resp.json();
  const result = data.results?.[0];
  if (result?.type === "error") {
    throw new Error(`Turso error: ${result.error?.message || JSON.stringify(result.error)}`);
  }
  return result?.response?.result || { cols: [], rows: [] };
}

// Synthesize a cited answer from the matched claims using OpenAI gpt-5.4-mini.
// Returns the answer string. Citations are [1]..[N] inline refs in the answer text.
async function synthesize(openaiKey, claims, question) {
  if (!claims.length) return "No relevant claims found in the knowledge base.";

  const context = claims
    .map((c, i) => `[${i + 1}] ${c.statement} (${c.source_title})`)
    .join("\n");

  const resp = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${openaiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: SYNTH_MODEL,
      messages: [
        {
          role: "system",
          content:
            "You are a research assistant answering questions from a personal knowledge base. " +
            "Use ONLY the numbered claims below. " +
            "Cite each claim you use with its number in brackets, e.g. [1]. " +
            "Answer in 2-4 concise sentences. Never invent facts not present in the claims.",
        },
        {
          role: "user",
          content: `Claims:\n${context}\n\nQuestion: ${question}`,
        },
      ],
      max_tokens: 300,
    }),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`OpenAI synthesis failed: ${resp.status} ${text.slice(0, 200)}`);
  }
  const data = await resp.json();
  return data.choices?.[0]?.message?.content?.trim() || "";
}

export default {
  async fetch(req, env) {
    // CORS preflight.
    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    // Auth gate — edge trust boundary (same pattern as worker-clip.js).
    const key = req.headers.get("X-PKM-Key");
    if (!key || !env.PKM_KEY || !(await timingSafeEqual(key, env.PKM_KEY))) {
      return new Response("unauthorized", {
        status: 401,
        headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "text/plain" },
      });
    }

    // Parse the query param.
    let q = "";
    if (req.method === "GET") {
      q = new URL(req.url).searchParams.get("q") || "";
    } else if (req.method === "POST") {
      let body;
      try {
        body = await req.json();
      } catch (_) {
        return corsResponse("invalid json", { status: 400 });
      }
      q = (body && typeof body.q === "string" ? body.q : "") || "";
    } else {
      return corsResponse("GET or POST only", { status: 405 });
    }

    if (!q.trim()) {
      return corsResponse(
        JSON.stringify({ error: "q param is required and must be non-empty" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }

    // 1. Embed query using Workers AI binding (same model as Python ingest pipeline).
    const aiResult = await env.AI.run(EMBED_MODEL, { text: q });
    const queryVec = aiResult.data[0];

    // 2. ANN search in Vectorize.
    const vectorResult = await env.VECTORIZE.query(queryVec, {
      topK: TOP_K,
      returnMetadata: "all",
    });
    const matches = vectorResult.matches || [];

    if (matches.length === 0) {
      return corsResponse(
        JSON.stringify({ answer: "No relevant claims found in the knowledge base.", citations: [] }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }

    // 3. Fetch claim text + source metadata from Turso via libsql HTTP.
    const claimIds = matches.map((m) => m.id);
    const placeholders = claimIds.map(() => "?").join(", ");
    let dbResult;
    try {
      dbResult = await tursoQuery(
        env.TURSO_URL,
        env.TURSO_TOKEN,
        `SELECT c.id, c.statement, s.title AS source_title, s.raw_path, s.url
         FROM claims c JOIN sources s ON c.source_id = s.id
         WHERE c.id IN (${placeholders})`,
        claimIds,
      );
    } catch (err) {
      return corsResponse(
        JSON.stringify({ error: `DB lookup failed: ${err.message}` }),
        { status: 502, headers: { "Content-Type": "application/json" } },
      );
    }

    // 4. Parse libsql HTTP result rows.
    const cols = dbResult.cols.map((c) => c.name);
    const rows = dbResult.rows.map((row) => {
      const obj = {};
      cols.forEach((col, i) => {
        obj[col] = row[i]?.value ?? null;
      });
      return obj;
    });

    // Maintain Vectorize score order; fall back to DB order for unmatched ids.
    const rowById = Object.fromEntries(rows.map((r) => [r.id, r]));
    const orderedRows = claimIds
      .map((id) => rowById[id])
      .filter(Boolean);

    // 5. Synthesize answer.
    let answer;
    try {
      answer = await synthesize(env.OPENAI_API_KEY, orderedRows, q);
    } catch (err) {
      return corsResponse(
        JSON.stringify({ error: `Synthesis failed: ${err.message}` }),
        { status: 502, headers: { "Content-Type": "application/json" } },
      );
    }

    // 6. Return result.
    const citations = orderedRows.map((r) => ({
      id: r.id,
      statement: r.statement,
      source_title: r.source_title,
      raw_path: r.raw_path,
      url: r.url,
    }));

    return corsResponse(JSON.stringify({ answer, citations }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  },
};
