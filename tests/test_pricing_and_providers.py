import pytest
from test_runner import FIXED_BEHAVIOUR, agent_writing

from issue_to_repro.agents import build_agents, make_model
from issue_to_repro.backtest.pricing import PRICES, cost_usd, price_of, worst_case_cost
from issue_to_repro.backtest.runner import AgentRun, run_backtest
from issue_to_repro.config import Settings

CLAUDE = {
    "model_provider": "anthropic",
    "anthropic_api_key": "test-key",
    "coordinator_model": "claude-sonnet-5-5",
    "worker_model": "claude-haiku-5-5",
}


def test_claude_models_use_an_explicit_base_url_and_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://sandbox-proxy.invalid")
    model = make_model("claude-haiku-5-5", Settings(**CLAUDE))
    assert type(model).__name__ == "AnthropicLlm"
    assert model.model == "claude-haiku-5-5" and model.max_tokens == 16_000
    assert str(model.client.base_url).rstrip("/") == "https://api.anthropic.com"
    assert model.client.api_key == "test-key"


def test_build_agents_on_anthropic_uses_claude_everywhere():
    root = build_agents(Settings(**CLAUDE))
    retriever, _, loop, reporter = root.sub_agents
    assert retriever.model.model == "claude-haiku-5-5"
    assert (
        loop.sub_agents[1].model.model == "claude-sonnet-5-5"
    )  # verifier uses the coordinator model
    assert reporter.model.model == "claude-sonnet-5-5"


def test_anthropic_provider_needs_a_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        make_model("claude-haiku-5-5", Settings(model_provider="anthropic"))


def test_cost_and_worst_case():
    assert cost_usd("claude-sonnet-5-5", 100_000, 4_000) == pytest.approx(0.24)
    assert price_of("claude-haiku-5-5") == PRICES["claude-haiku-5-5"]
    with pytest.raises(ValueError, match="no price known"):
        price_of("gemini-3.8-flash")
    settings = Settings(**CLAUDE, backtest_max_tokens=150_000, anthropic_max_tokens=10_000)
    # Pricier model's rates: 150k input at $2/M + 10k output at $10/M.
    assert worst_case_cost(settings) == pytest.approx(0.30 + 0.10)


def two_cases(backtest_setup):
    case, prepare, out = backtest_setup
    second = case.__class__(**{**case.__dict__, "issue_number": 13})
    return [case, second], prepare, out


def spending(prompt_tokens: int):
    write = agent_writing(FIXED_BEHAVIOUR)

    def run_agents(case, checkout, settings) -> AgentRun:
        run = write(case, checkout, settings)
        run.prompt_tokens, run.output_tokens = prompt_tokens, 0
        return run

    return run_agents


def test_spend_cap_stops_before_a_case_that_might_not_fit(backtest_setup):
    cases, prepare, out = two_cases(backtest_setup)
    # Worst case per case: 100k*$2/M + 16k*$10/M = $0.36. First case spends $0.20 (100k at $2/M).
    settings = Settings(**CLAUDE, backtest_max_tokens=100_000, backtest_max_usd=0.50)
    messages: list[str] = []
    results = run_backtest(cases, out, prepare, spending(100_000), settings, log=messages.append)
    assert [r.issue_number for r in results] == [12]
    assert results[0].cost_usd == pytest.approx(0.20)
    assert messages[-1].startswith("spend cap: $0.20 spent") and "o/proj#13" in messages[-1]


def test_spend_cap_allows_cases_that_fit(backtest_setup):
    cases, prepare, out = two_cases(backtest_setup)
    settings = Settings(**CLAUDE, backtest_max_tokens=100_000, backtest_max_usd=5.0)
    results = run_backtest(cases, out, prepare, spending(1_000), settings, log=lambda m: None)
    assert [r.issue_number for r in results] == [12, 13]


def test_spend_cap_refuses_unpriced_models(backtest_setup):
    cases, prepare, out = two_cases(backtest_setup)
    with pytest.raises(ValueError, match="no price known"):
        run_backtest(cases, out, prepare, spending(1), Settings(backtest_max_usd=1.0))


def test_gemini_runs_record_no_cost_estimate(backtest_setup):
    case, prepare, out = backtest_setup
    [result] = run_backtest([case], out, prepare, spending(1_000), Settings(), log=lambda m: None)
    assert result.cost_usd is None
