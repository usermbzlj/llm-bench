import json

from llm_bench import gui_ng


def test_resolve_api_key_prefers_ui_then_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "env-key")

    assert gui_ng._resolve_api_key("ui-key") == "ui-key"
    assert gui_ng._resolve_api_key("") == "env-key"


def test_resolve_endpoint_supports_relative_and_absolute_inputs() -> None:
    assert (
        gui_ng._resolve_endpoint("https://demo.test/v1") == "https://demo.test/v1/chat/completions"
    )
    assert (
        gui_ng._resolve_endpoint("https://demo.test/v1", "/responses")
        == "https://demo.test/v1/responses"
    )
    assert (
        gui_ng._resolve_endpoint("https://demo.test/v1", "https://other.test/chat")
        == "https://other.test/chat"
    )
    assert (
        gui_ng._resolve_endpoint("https://demo.test/v1/chat/completions")
        == "https://demo.test/v1/chat/completions"
    )
    assert gui_ng._resolve_endpoint("https://demo.test/v1/chat/completions", "/responses") == (
        "https://demo.test/v1/responses"
    )


def test_resolve_proxy_inputs_validates_custom_proxy() -> None:
    assert gui_ng._resolve_proxy_inputs("direct", "") == ("direct", None, None)
    assert gui_ng._resolve_proxy_inputs("system", "") == ("system", None, None)
    assert gui_ng._resolve_proxy_inputs("custom", "http://127.0.0.1:7890") == (
        "custom",
        "http://127.0.0.1:7890",
        None,
    )

    mode, proxy_url, err = gui_ng._resolve_proxy_inputs("custom", "127.0.0.1:7890")
    assert mode == "custom"
    assert proxy_url is None
    assert err is not None


def test_parse_custom_body_rejects_non_object() -> None:
    body, err = gui_ng._parse_custom_body('["not-object"]')

    assert body is None
    assert err is not None


def test_stats_log_preview_truncates_large_payload() -> None:
    payload = {
        "metadata": {"mode": "run"},
        "items": ["x" * 2500, "y" * 2500],
    }

    preview = gui_ng._stats_log_preview(payload, max_chars=500)

    assert len(preview) <= 500
    assert "统计 JSON 已截断" in preview
    assert json.loads(json.dumps(payload, ensure_ascii=False))["metadata"]["mode"] == "run"


def test_run_state_reset_clears_previous_values() -> None:
    state = gui_ng._RunState()
    state.log_lines.append("old")
    state.stats["requests_total"] = 1
    state.raw_results.append(object())
    state.inflight_samples.append(3)

    state.reset()

    assert state.busy is True
    assert state.status == "运行中..."
    assert state.log_lines == []
    assert state.stats == {}
    assert state.raw_results == []
    assert state.inflight_samples == []
    assert state.stop_event.is_set() is False
