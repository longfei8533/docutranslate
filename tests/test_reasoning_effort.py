import pytest
import httpx
from pydantic import TypeAdapter, ValidationError

from docutranslate.agents.agent import (
    Agent,
    AgentConfig,
    UnsupportedReasoningEffortError,
)
from docutranslate.core.schemas import TranslatePayload
from docutranslate.core.factory import create_workflow_from_payload


def _agent(**overrides):
    values = {
        "base_url": "https://example.com/v1",
        "api_key": "test-key",
        "model_id": "gpt-5.6-luna",
        "temperature": 0.7,
        "top_p": 0.9,
        "retry": 0,
    }
    values.update(overrides)
    return Agent(AgentConfig(**values))


@pytest.mark.parametrize("effort", ["none", "low", "medium", "high", "xhigh"])
def test_reasoning_effort_is_sent_with_supported_value(effort):
    _, data = _agent(reasoning_effort=effort)._prepare_request_data("hello", "translate")

    assert data["reasoning_effort"] == effort
    if effort == "none":
        assert data["temperature"] == 0.7
        assert data["top_p"] == 0.9
    else:
        assert "temperature" not in data
        assert "top_p" not in data


def test_reasoning_effort_wins_over_legacy_thinking_and_extra_body_cannot_restore_sampling():
    _, data = _agent(
        thinking="disable",
        reasoning_effort="high",
        extra_body='{"temperature": 0, "top_p": 0.1}',
    )._prepare_request_data("hello", "translate")

    assert data["reasoning_effort"] == "high"
    assert "temperature" not in data
    assert "top_p" not in data


def test_extra_body_cannot_override_selected_reasoning_effort():
    with pytest.raises(UnsupportedReasoningEffortError, match="不能覆盖"):
        _agent(
            reasoning_effort="high",
            extra_body='{"reasoning_effort": "none"}',
        )._prepare_request_data("hello", "translate")


def test_extra_body_reasoning_also_removes_sampling_parameters():
    _, data = _agent(thinking="default", extra_body='{"reasoning_effort": "low"}')._prepare_request_data(
        "hello", "translate"
    )

    assert data["reasoning_effort"] == "low"
    assert "temperature" not in data
    assert "top_p" not in data


def test_legacy_enable_maps_to_medium_for_default_provider():
    _, data = _agent(thinking="enable")._prepare_request_data("hello", "translate")

    assert data["reasoning_effort"] == "medium"
    assert "temperature" not in data
    assert "top_p" not in data


def test_non_native_provider_rejects_non_none_formal_effort():
    with pytest.raises(UnsupportedReasoningEffortError, match="未自动降级"):
        _agent(provider="bigmodel", reasoning_effort="high")._prepare_request_data(
            "hello", "translate"
        )


def test_translate_payload_exposes_reasoning_effort_and_maps_legacy_thinking():
    payload = TypeAdapter(TranslatePayload).validate_python({
        "workflow_type": "txt",
        "base_url": "https://example.com/v1",
        "api_key": "test-key",
        "model_id": "gpt-5.6-luna",
        "thinking": "enable",
    })
    assert payload.reasoning_effort == "medium"

    explicit = TypeAdapter(TranslatePayload).validate_python({
        "workflow_type": "txt",
        "base_url": "https://example.com/v1",
        "api_key": "test-key",
        "model_id": "gpt-5.6-luna",
        "thinking": "enable",
        "reasoning_effort": "none",
    })
    assert explicit.reasoning_effort == "none"

    workflow = create_workflow_from_payload(explicit)
    assert workflow.config.translator_config.reasoning_effort == "none"


def test_translate_payload_rejects_unrequested_effort_names():
    with pytest.raises(ValidationError):
        TypeAdapter(TranslatePayload).validate_python({
            "workflow_type": "txt",
            "base_url": "https://example.com/v1",
            "api_key": "test-key",
            "model_id": "gpt-5.6-luna",
            "reasoning_effort": "minimal",
        })


@pytest.mark.asyncio
async def test_gateway_rejection_is_not_silently_retried_or_downgraded():
    seen_requests = []

    async def handler(request):
        seen_requests.append(request)
        return httpx.Response(
            400,
            json={"error": {"message": "unsupported reasoning_effort"}},
            request=request,
        )

    agent = _agent(reasoning_effort="high")
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(UnsupportedReasoningEffortError, match="未自动降级"):
            await agent.send_async(client, "hello", retry=False)

    assert len(seen_requests) == 1
