#%%
import io
import json
import os
import sys
from unittest.mock import patch, Mock

# ── path setup so pytest can find src modules ─────────────────────────────────
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "src", "lambda_insights")
    ),
)
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "src", "layers", "shared_utils")
    ),
)

import synthesize
from retry_config import BEDROCK_CONFIG


# ── mock helpers ──────────────────────────────────────────────────────────────

def mock_tool_use_response(tool_calls: list[dict]) -> dict:
    """Simulates a Bedrock response where the model requests tool use.
    tool_calls: list of dicts with "name", "input", and optional "id" keys.
    Returns {"body": BytesIO} with stop_reason="tool_use".
    """
    content = [
        {"type": "tool_use", "id": tc.get("id", "toolu_001"),
         "name": tc["name"], "input": tc["input"]}
        for tc in tool_calls
    ]
    envelope = json.dumps({"content": content, "stop_reason": "tool_use"}).encode()
    return {"body": io.BytesIO(envelope)}


def mock_final_response(text: str) -> dict:
    """Simulates a Bedrock response with a final text answer (end_turn).
    text: the raw model text (e.g. '{"answer": "..."}').
    Returns {"body": BytesIO} with stop_reason="end_turn".
    """
    envelope = json.dumps(
        {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}
    ).encode()
    return {"body": io.BytesIO(envelope)}


# ── test 1: single tool call happy path ───────────────────────────────────────
def test_single_tool_call_happy_path():
    # model requests query_triage_data(sentiment="negative"), gets results,
    # then returns valid {"answer": "..."} → synthesis_failed=False
    # assert records_considered matches len of query_fn return
    # assert query_fn called once with sentiment="negative"
    pass


# ── test 2: two sequential tool calls ────────────────────────────────────────
def test_two_tool_calls_comparison():
    # model calls query_triage_data(category="billing") first,
    # then query_triage_data(category="bug_report") second, then answers
    # assert records_considered is sum of both calls
    # assert query_fn called twice with different kwargs
    pass


# ── test 3: model answers directly without tool use ──────────────────────────
def test_direct_answer_no_tool_use():
    # model returns end_turn immediately with valid {"answer": "..."}
    # no tool calls made — query_fn never called
    # assert records_considered == 0
    pass


# ── test 4: invalid final answer triggers Layer 2 retry ──────────────────────
def test_invalid_answer_triggers_retry():
    # attempt 1: model uses tool, gets results, returns invalid text
    # attempt 2: model uses tool, gets results, returns valid {"answer": "..."}
    # assert synthesis_failed=False (recovered on retry)
    pass


# ── test 5: both attempts fail — degraded result ─────────────────────────────
def test_both_attempts_fail_returns_degraded():
    # both attempts return invalid final text after tool use
    # assert answer is None, synthesis_failed=True, records_considered=0
    pass


# ── test 6: loop exceeds MAX_TOOL_TURNS — treated as failure ─────────────────
def test_max_tool_turns_exceeded():
    # model keeps requesting tool use for MAX_TOOL_TURNS+1 rounds
    # _invoke_with_tools returns (None, 0) → triggers retry
    pass


# ── test 7: records_considered accumulates across tool calls ──────────────────
def test_records_considered_accumulates():
    # tool call 1 returns 3 records, tool call 2 returns 2 records
    # assert records_considered == 5
    pass


# ── test 8: query_fn called with exact kwargs from tool input ─────────────────
def test_query_fn_receives_exact_tool_input():
    # model sends tool input {"category": "billing", "sentiment": "negative"}
    # assert query_fn called with category="billing", sentiment="negative"
    pass


# ── test 9: request body includes tools key with QUERY_TOOL ──────────────────
def test_invoke_includes_tools_in_request():
    # inspect the body kwarg passed to invoke_model
    # json.loads it → assert "tools" key present with QUERY_TOOL
    pass


# ── test 10: messages list builds correct multi-turn shape ────────────────────
def test_messages_multi_turn_shape():
    # after tool use round, messages should be:
    #   [user question, assistant tool_use, user tool_result]
    # inspect call_args_list[1] (second invoke) to verify messages structure
    pass


# ── test 11: INSIGHTS_BEDROCK_CONFIG distinct from shared BEDROCK_CONFIG ──────
def test_insights_config_is_distinct_from_shared():
    # regression boundary — ensures synthesize uses its own tighter config
    print(f"[test] INSIGHTS retries: {synthesize.INSIGHTS_BEDROCK_CONFIG.retries}")
    print(f"[test] INSIGHTS read_timeout: {synthesize.INSIGHTS_BEDROCK_CONFIG.read_timeout}")
    print(f"[test] shared BEDROCK retries: {BEDROCK_CONFIG.retries}")
    print(f"[test] shared BEDROCK read_timeout: {BEDROCK_CONFIG.read_timeout}")
    assert synthesize.INSIGHTS_BEDROCK_CONFIG is not BEDROCK_CONFIG
    assert synthesize.INSIGHTS_BEDROCK_CONFIG.retries == {"max_attempts": 2, "mode": "adaptive"}
    assert synthesize.INSIGHTS_BEDROCK_CONFIG.read_timeout == 5


# ── test 12: temperature=0.3 and max_tokens=1024 in request ──────────────────
def test_invoke_params_temperature_and_max_tokens():
    # inspect the body kwarg passed to invoke_model
    # json.loads it → assert temperature=0.3, max_tokens=1024
    pass
# %%
