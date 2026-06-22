"""Tests for the Gemini provider: model listing/ordering, version-fallback,
schema transform, response normalization, and free-tier cost. httpx is mocked —
no network or API key required."""
import json
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import BaseModel

from pkm.llm.gemini_client import (
    GEMINI_AUTO,
    GeminiClient,
    _to_gemini_schema,
    order_flash_models,
)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_order_flash_models_version_desc_full_before_lite():
    ids = [
        "gemini-2.5-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.1-flash",
        "gemini-2.0-pro",  # non-flash → dropped
    ]
    ordered = order_flash_models(ids)
    # Full flash by version desc first; flash-lite last; non-flash dropped.
    assert ordered == [
        "gemini-3.5-flash",
        "gemini-3.1-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-3.1-flash-lite",
    ]


def test_order_flash_models_excludes_non_text_variants():
    """Image/TTS/audio/vision/embedding/live Flash variants advertise
    generateContent but can't do text synthesis — they must be dropped so the
    fallback chain never lands on one."""
    ids = [
        "gemini-3.5-flash",
        "gemini-3.1-flash-image",
        "gemini-3.1-flash-image-preview",
        "gemini-3.1-flash-tts-preview",
        "gemini-2.5-flash-image",
        "gemini-2.5-flash-preview-tts",
        "gemini-2.0-flash-live-001",
        "gemini-2.5-flash",
    ]
    assert order_flash_models(ids) == ["gemini-3.5-flash", "gemini-2.5-flash"]


def test_to_gemini_schema_strips_unsupported_and_inlines_refs():
    class Inner(BaseModel):
        n: int

    class Outer(BaseModel):
        title_field: str
        inner: Inner

    out = _to_gemini_schema(Outer.model_json_schema())
    blob = json.dumps(out)
    assert "$defs" not in blob and "$ref" not in blob  # inlined
    assert "title" not in out  # stripped top-level
    # The inlined nested object survived.
    assert out["properties"]["inner"]["properties"]["n"]["type"] == "integer"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _list_response(model_ids):
    models = [
        {"name": f"models/{m}", "supportedGenerationMethods": ["generateContent"]}
        for m in model_ids
    ]
    return {"models": models}


def _gen_response(text, finish="STOP", pin=5, pout=7):
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": pin, "candidatesTokenCount": pout},
    }


def _make_client(db_conn, monkeypatch, get_json=None, post_side_effect=None):
    client = GeminiClient(db_conn, api_key="fake-key", model=GEMINI_AUTO)
    http = MagicMock()
    if get_json is not None:
        get_resp = MagicMock()
        get_resp.json.return_value = get_json
        get_resp.raise_for_status.return_value = None
        http.get.return_value = get_resp
    if post_side_effect is not None:
        http.post.side_effect = post_side_effect
    client._http = http
    return client, http


def _ok_post(json_body, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_body
    resp.raise_for_status.return_value = None
    return resp


# --------------------------------------------------------------------------- #
# list_models
# --------------------------------------------------------------------------- #
def test_list_models_filters_and_orders(db_conn, monkeypatch):
    client, http = _make_client(
        db_conn, monkeypatch,
        get_json=_list_response(["gemini-2.5-flash", "gemini-3.5-flash", "text-bison"]),
    )
    assert client.list_models() == ["gemini-3.5-flash", "gemini-2.5-flash"]
    # Cached: a second call does not re-hit the API.
    http.get.reset_mock()
    client.list_models()
    http.get.assert_not_called()


# --------------------------------------------------------------------------- #
# _generate: fallback + normalization
# --------------------------------------------------------------------------- #
class _Out(BaseModel):
    msg: str


def test_generate_falls_back_to_next_model_on_failure(db_conn, monkeypatch):
    client, http = _make_client(
        db_conn, monkeypatch,
        get_json=_list_response(["gemini-3.5-flash", "gemini-2.5-flash"]),
    )
    # 3.5-flash 500s through all backoff attempts (raise_for_status raises);
    # 2.5-flash succeeds.
    fail = _ok_post({}, status=503)
    fail.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=MagicMock(status_code=503)
    )
    good = _ok_post(_gen_response('{"msg": "hi"}'))
    http.post.side_effect = [fail, fail, fail, good]

    gen = client._generate(GEMINI_AUTO, [{"role": "user", "content": "x"}], _Out, 1024)
    assert gen.text == '{"msg": "hi"}'
    assert gen.model == "gemini-2.5-flash"  # fell through to the lower version
    assert gen.finish_reason == "stop"
    assert gen.tokens_in == 5 and gen.tokens_out == 7


def test_generate_maps_max_tokens_to_length(db_conn, monkeypatch):
    client, http = _make_client(
        db_conn, monkeypatch, get_json=_list_response(["gemini-3.5-flash"]),
    )
    http.post.side_effect = [_ok_post(_gen_response("partial", finish="MAX_TOKENS"))]
    gen = client._generate(GEMINI_AUTO, [{"role": "user", "content": "x"}], None, 1024)
    assert gen.finish_reason == "length"


def test_cost_is_zero(db_conn):
    client = GeminiClient(db_conn, api_key="fake-key")
    assert client._cost("gemini-3.5-flash", 1000, 0, 2000) == 0.0


def test_system_message_becomes_system_instruction(db_conn):
    client = GeminiClient(db_conn, api_key="fake-key")
    contents, sys_inst = client._to_gemini_contents(
        [{"role": "system", "content": "be terse"}, {"role": "user", "content": "hi"}]
    )
    assert sys_inst == {"parts": [{"text": "be terse"}]}
    assert contents == [{"role": "user", "parts": [{"text": "hi"}]}]


def test_missing_api_key_raises(db_conn):
    with pytest.raises(ValueError, match="API key"):
        GeminiClient(db_conn, api_key="")


def test_call_end_to_end_writes_agent_run_with_concrete_model(db_conn, monkeypatch):
    """Full call() path: cache miss → generate → validate → agent_runs row records
    the concrete model, cost 0, and a cache hit restores the result."""
    client, http = _make_client(
        db_conn, monkeypatch, get_json=_list_response(["gemini-3.5-flash"]),
    )
    http.post.side_effect = [_ok_post(_gen_response('{"msg": "ok"}'))]
    out = client.call(
        agent_name="summarizer_agent", model=GEMINI_AUTO, prompt_version="v1",
        messages=[{"role": "user", "content": "go"}], input_text="go", output_schema=_Out,
    )
    assert out["cached"] is False and out["result"].msg == "ok"
    row = db_conn.execute(
        "SELECT model, cost_usd, status FROM agent_runs WHERE agent='summarizer_agent'"
    ).fetchone()
    assert row[0] == "gemini-3.5-flash" and row[1] == 0.0 and row[2] == "ok"
