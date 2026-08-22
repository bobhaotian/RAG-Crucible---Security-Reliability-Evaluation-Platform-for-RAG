from __future__ import annotations

from crucible.providers import Usage, estimate_tokens


def test_usage_adds_input_and_output_tokens() -> None:
    assert Usage(input_tokens=2, output_tokens=3) + Usage(
        input_tokens=5, output_tokens=7
    ) == Usage(input_tokens=7, output_tokens=10)


def test_estimate_tokens_has_a_minimum_and_uses_character_ratio() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("12345678") == 2
