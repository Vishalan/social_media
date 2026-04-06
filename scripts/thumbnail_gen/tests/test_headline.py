"""Tests for scripts.thumbnail_gen.headline."""

from unittest.mock import MagicMock

import pytest

from scripts.thumbnail_gen.headline import generate_headline


def _make_client(*texts):
    """Build a fake Anthropic client whose messages.create returns each text in turn."""
    client = MagicMock()
    responses = []
    for t in texts:
        resp = MagicMock()
        resp.content = [MagicMock(text=t)]
        responses.append(resp)
    client.messages.create.side_effect = responses
    return client


def test_happy_path_returns_caps_headline():
    client = _make_client("AI TAKES OVER WORLD")
    result = generate_headline("A script about AI advances.", client=client)
    assert result == "AI TAKES OVER WORLD"
    assert 2 <= len(result.split()) <= 6
    assert client.messages.create.call_count == 1


def test_strips_punctuation_quotes_and_whitespace():
    client = _make_client('  "AI Takes Over!"  \n')
    result = generate_headline("script", client=client)
    assert result == "AI TAKES OVER"


def test_lowercase_gets_uppercased():
    client = _make_client("robots are coming")
    result = generate_headline("script", client=client)
    assert result == "ROBOTS ARE COMING"


def test_invalid_then_valid_retries_once():
    # First output is one word (invalid), second is valid
    client = _make_client("NO", "THREE VALID WORDS")
    result = generate_headline("script", client=client)
    assert result == "THREE VALID WORDS"
    assert client.messages.create.call_count == 2


def test_two_invalid_raises_value_error():
    client = _make_client("NO", "STILL")
    with pytest.raises(ValueError, match="Failed to generate valid headline"):
        generate_headline("script", client=client)
    assert client.messages.create.call_count == 2


def test_empty_script_raises_without_calling_client():
    client = _make_client("SHOULD NOT BE USED")
    with pytest.raises(ValueError):
        generate_headline("", client=client)
    assert client.messages.create.call_count == 0


def test_whitespace_script_raises_without_calling_client():
    client = _make_client("SHOULD NOT BE USED")
    with pytest.raises(ValueError):
        generate_headline("   \n\t  ", client=client)
    assert client.messages.create.call_count == 0


def test_must_include_proper_noun_from_script_retries_on_drift():
    """If the script contains a proper noun like 'Veo', the headline must include it.
    
    Regression: Haiku initially output 'GOOGLE VEVO LITE CHANGES EVERYTHING' for a
    script about 'Veo 3.1 Lite'. The validator must reject hallucinated misspellings.
    """
    # First attempt drifts to "VEVO", second attempt gets it right (preserves 3.1)
    client = _make_client("GOOGLE VEVO CHANGES EVERYTHING", "VEO 3.1 IS WILD")
    result = generate_headline(
        "Google just dropped Veo 3.1 Lite and it changes everything for creators.",
        client=client,
    )
    assert "VEO" in result
    assert "VEVO" not in result
    assert "3.1" in result
    assert client.messages.create.call_count == 2


def test_must_include_extracts_multiple_proper_nouns():
    """Headline can satisfy the constraint by including ANY of the must-include terms."""
    client = _make_client("CLAUDE 4.6 BREAKS INTERNET")
    result = generate_headline(
        "Anthropic released Claude Opus 4.6 with new capabilities.",
        client=client,
    )
    # "CLAUDE" is one of the proper nouns extracted (Anthropic, Claude, Opus)
    # And the version 4.6 must survive
    assert "CLAUDE" in result
    assert "4.6" in result


def test_preserves_version_numbers_with_dots():
    """Periods inside version numbers must survive: 'Veo 3.1' must not become 'Veo 31'."""
    client = _make_client("VEO 3.1 LITE RELEASED")
    result = generate_headline(
        "Google released Veo 3.1 Lite for AI video generation.",
        client=client,
    )
    assert result == "VEO 3.1 LITE RELEASED"
    assert "3.1" in result


def test_preserves_hyphenated_model_names():
    """Hyphens inside model names must survive: 'GPT-4' must not become 'GPT 4'."""
    client = _make_client("GPT-4 IS HERE")
    result = generate_headline(
        "OpenAI announced GPT-4 today with massive improvements.",
        client=client,
    )
    assert "GPT-4" in result
