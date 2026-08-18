"""Regression coverage for first-turn context/output budgeting."""


class _Compressor:
    context_length = 131_072


class _Agent:
    context_compressor = _Compressor()
    model = "MiniMax-M2.7"
    provider = "minimax-cn"


def test_first_turn_completion_is_capped_by_remaining_context(monkeypatch):
    """A large default completion must leave room for the actual prompt."""
    import api.streaming as streaming

    monkeypatch.setattr(
        streaming,
        "_estimate_agent_request_tokens",
        lambda payload: 16_888,
    )

    payload = {
        "messages": [{"role": "user", "content": "first question"}],
        "max_tokens": 131_072,
    }
    bounded = streaming._bound_agent_request_output_to_context(_Agent(), payload)

    assert bounded["max_tokens"] < 131_072
    assert 16_888 + bounded["max_tokens"] + 2_048 <= 131_072
    assert payload["max_tokens"] == 131_072


def test_output_budget_guard_preserves_completion_parameter_name(monkeypatch):
    """OpenAI-style max_completion_tokens is bounded without renaming it."""
    import api.streaming as streaming

    monkeypatch.setattr(
        streaming,
        "_estimate_agent_request_tokens",
        lambda payload: 20_000,
    )

    payload = {
        "messages": [{"role": "user", "content": "first question"}],
        "max_completion_tokens": 131_072,
    }
    bounded = streaming._bound_agent_request_output_to_context(_Agent(), payload)

    assert "max_tokens" not in bounded
    assert "max_completion_tokens" in bounded
    assert bounded["max_completion_tokens"] < 131_072


def test_agent_context_output_guard_wraps_request_builder_once(monkeypatch):
    """Cached agents must use the guard without stacking wrappers per turn."""
    import api.streaming as streaming

    monkeypatch.setattr(
        streaming,
        "_estimate_agent_request_tokens",
        lambda payload: 16_888,
    )

    class Agent(_Agent):
        def __init__(self):
            self.calls = 0

        def _build_api_kwargs(self, messages):
            self.calls += 1
            return {
                "messages": messages,
                "max_tokens": 131_072,
            }

    agent = Agent()
    streaming._install_agent_context_output_guard(agent)
    first_builder = agent._build_api_kwargs
    streaming._install_agent_context_output_guard(agent)

    bounded = agent._build_api_kwargs([{"role": "user", "content": "hello"}])

    assert agent._build_api_kwargs is first_builder
    assert agent.calls == 1
    assert bounded["max_tokens"] < 131_072
