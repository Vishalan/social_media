"""Tests for BrollSelector."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from broll_gen.selector import BrollSelector

_VALID_TYPES = {
    "browser_visit",
    "image_montage",
    "code_walkthrough",
    "stats_card",
    "ai_video",
}


def _make_mock_client(response_text: str) -> MagicMock:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=response_text)]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_select_returns_valid_pair():
    """Claude returns a valid JSON pair; selector should parse and return it."""
    mock_client = _make_mock_client(
        '{"primary":"code_walkthrough","fallback":"image_montage"}'
    )
    selector = BrollSelector(mock_client)

    result = await selector.select(
        topic_title="How to use the OpenAI Responses API",
        topic_url="https://example.com/openai-responses-api",
        script_text="Today we look at the brand-new OpenAI Responses API...",
    )

    assert result == ["code_walkthrough", "image_montage"]


@pytest.mark.asyncio
async def test_select_claude_failure_returns_safe_default():
    """Any Claude exception should produce the safe default without re-raising."""
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("network error"))

    selector = BrollSelector(mock_client)

    result = await selector.select(
        topic_title="Some Topic",
        topic_url="https://example.com/topic",
        script_text="Script content here.",
    )

    assert result == ["image_montage", "ai_video"]


@pytest.mark.asyncio
async def test_select_returns_list_of_two():
    """Result is always a 2-element list of valid b-roll type strings."""
    mock_client = _make_mock_client(
        '{"primary":"code_walkthrough","fallback":"image_montage"}'
    )
    selector = BrollSelector(mock_client)

    result = await selector.select(
        topic_title="GPT-4o vs Claude 3.5 Benchmark",
        topic_url="https://example.com/benchmark",
        script_text="In today's comparison, GPT-4o scores 92% while Claude 3.5 hits 95%...",
    )

    assert len(result) == 2
    assert result[0] in _VALID_TYPES
    assert result[1] in _VALID_TYPES
