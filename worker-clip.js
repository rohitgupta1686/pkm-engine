// pkm-engine/worker-clip.js
// Cloudflare Worker — the project's only edge entrypoint.
// Authenticated POST clips a source -> commits an immutable, content-addressed
// raw/*.md file to pkm-vault via the GitHub Contents API -> fires
// repository_dispatch(event_type:"ingest") to pkm-engine so the Phase-4
// pipeline picks it up. Runs at the Cloudflare/GitHub edge; Mac is never in path.
//
// Contract (pkm/pipeline/ingest.py::run_ingest):
//   front matter fields parsed by the pipeline: title, type, url, author, and the
//   saved-date field (NOT `date` — see ingest.py for the exact name). Body ALWAYS
//   holds the full text (Q1) — never reduced to an R2 pointer. slugify matches
//   pkm/ingest/hashing.py exactly. event_type MUST be exactly "ingest"
//   (ingest.yml listens on repository_dispatch.types:[ingest]).

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-PKM-Key",
  "Access-Control-Max-Age": "86400",
};

function corsResponse(body, init = {}) {
  return new Response(body, {
    ...init,
    headers: { ...(init.headers || {}), "Access-Control-Allow-Origin": "*" },
  });
}

// Constant-time shared-secret compare via SHA-256 digests (fixed-length XOR).
// Avoids short-circuit on the raw secret. Rejects empty env secret defensively.
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

async function sha256Hex(data) {
  const buf = new TextEncoder().encode(data);
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// MUST match pkm/ingest/hashing.py::slugify exactly: lowercase, [^a-z0-9]+ -> "-",
// strip leading/trailing "-". (Consecutive hyphens collapse because each run maps
// to a single hyphen, matching the Python `re.sub(r"[^a-z0-9]+", "-", s)`.)
function slugify(s) {
  return String(s)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Minimal YAML scalar: quote if it contains YAML-special chars or a newline.
function yamlScalar(s) {
  const str = String(s);
  return /[:#{}\[\],&*?|>!%@`'"~]/.test(str) || str.includes("\n") || str === ""
    ? JSON.stringify(str)
    : str;
}

async function buildRawFile({ url, type, title, text, r2key }) {
  // 6-char content hash for the filename (bookkeeping dedup; NOT pipeline dedup,
  // which is sha256 of the ENTIRE file). Matches the established fixture hash6 (e.g. 9709e6).
  const hash6 = (await sha256Hex(text || url || "")).slice(0, 6);
  // UTC timestamp with NO hyphens/colons: 20260620T1230Z
  const ts = new Date().toISOString().replace(/[-:]/g, "").slice(0, 13) + "Z";
  let sourceSlug = "clip";
  try {
    sourceSlug = slugify(new URL(url).hostname.replace(/^www\./, "")) || "clip";
  } catch (_) {
    sourceSlug = slugify("clip");
  }
  const titleSlug = slugify(title || "untitled").slice(0, 40) || "untitled";
  const path = `raw/${ts}__${sourceSlug}__${titleSlug}__${hash6}.md`;

  const nowIso = new Date().toISOString();
  const fmLines = [
    "---",
    `title: ${yamlScalar(title || "(untitled)")}`,
    `type: ${yamlScalar(type || "Article")}`,
    `url: ${yamlScalar(url || "")}`,
    `author: ""`,
    `date_saved: ${nowIso}`,
    r2key ? `r2key: ${r2key}` : null,
    `sha8: ${hash6}${hash6}`,
    "---",
    "",
  ];
  const fm = fmLines.filter((x) => x !== null).join("\n");

  // Q1: body ALWAYS holds the FULL text. Never reduced to an R2 pointer.
  // R2 mirror is belt-and-suspenders; the pipeline synthesizes from this body.
  const body = text;
  return { path, content: fm + body };
}

function ghHeaders(env, extra = {}) {
  return {
    Authorization: `Bearer ${env.GH_PAT}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    ...extra,
  };
}

async function dispatch(env, event_type, client_payload) {
  const r = await fetch(
    `https://api.github.com/repos/${env.ENGINE_OWNER}/${env.ENGINE_REPO}/dispatches`,
    {
      method: "POST",
      headers: ghHeaders(env, { "Content-Type": "application/json" }),
      body: JSON.stringify({ event_type, client_payload }),
    },
  );
  if (!r.ok) throw new Error(`dispatch failed: ${r.status}`);
}

export default {
  async fetch(req, env) {
    // 1-2. CORS preflight + method gate.
    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }
    if (req.method !== "POST") {
      return corsResponse("POST only", { status: 405 });
    }

    // 3. Auth FIRST — edge is the trust boundary. No upstream call before this.
    const key = req.headers.get("X-PKM-Key");
    if (!key || !env.PKM_KEY || !(await timingSafeEqual(key, env.PKM_KEY))) {
      return new Response("unauthorized", {
        status: 401,
        headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "text/plain" },
      });
    }

    // 4. Parse + size-limit (DoS guard). JSON parse error -> 400.
    let body;
    try {
      body = await req.json();
    } catch (_) {
      return corsResponse("invalid json", { status: 400 });
    }
    const { url = "", type = "Article", text = "", title = "" } = body || {};
    if (
      typeof text !== "string" ||
      typeof url !== "string" ||
      typeof title !== "string" ||
      typeof type !== "string"
    ) {
      return corsResponse("invalid field types", { status: 400 });
    }
    if (text.length > 5_000_000) {
      return corsResponse("payload too large", { status: 413 });
    }

    // 5. R2 offload (Q1): mirror to R2 when >200K, but body keeps the full text.
    let r2key = null;
    if (text.length > 200_000) {
      r2key = "blobs/" + crypto.randomUUID() + ".txt";
      await env.RAW_BUCKET.put(r2key, text);
    }

    // 6. Build the raw/*.md file (front matter + full-text body).
    const { path, content } = await buildRawFile({ url, type, title, text, r2key });

    // 7. Commit via GitHub Contents API — GET-first idempotency (CLIP-04, Q3, raw/ immutable).
    const getUrl = `https://api.github.com/repos/${env.VAULT_OWNER}/${env.VAULT_REPO}/contents/${path}?ref=main`;
    const exists = await fetch(getUrl, { headers: ghHeaders(env) });
    let deduped = false;
    if (exists.status === 200) {
      // raw/ is immutable — path already committed. Skip PUT. Still dispatch (Q3).
      deduped = true;
    } else if (exists.status === 404) {
      const putBody = JSON.stringify({
        message: `clip: ${path.split("__")[2] || "untitled"}`,
        content: btoa(unescape(encodeURIComponent(content))),
      });
      const created = await fetch(
        `https://api.github.com/repos/${env.VAULT_OWNER}/${env.VAULT_REPO}/contents/${path}`,
        {
          method: "PUT",
          headers: ghHeaders(env, { "Content-Type": "application/json" }),
          body: putBody,
        },
      );
      if (created.ok) {
        // success (201)
      } else if (created.status === 422) {
        // Defense in depth: 422 "sha wasn't supplied" -> already exists. Skip, dispatch.
        deduped = true;
      } else {
        const errText = await created.text();
        throw new Error(`commit failed: ${created.status} ${errText.replace(env.GH_PAT || "", "***")}`);
      }
    } else {
      const errText = await exists.text();
      throw new Error(`contents GET failed: ${exists.status} ${errText.replace(env.GH_PAT || "", "***")}`);
    }

    // 8. Dispatch (CLIP-05): event_type MUST be exactly "ingest".
    await dispatch(env, "ingest", { path });

    // 9. Return success.
    return corsResponse(JSON.stringify({ ok: true, path, deduped }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  },
};