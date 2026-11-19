from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent

from issue_to_repro.agents import build_agents
from issue_to_repro.config import Settings


def test_fixed_pipeline():
    root = build_agents(Settings())
    assert isinstance(root, SequentialAgent) and root.name == "coordinator"
    assert [a.name for a in root.sub_agents] == [
        "retriever",
        "classifier",
        "repro_loop",
        "reporter",
    ]
    loop = root.sub_agents[2]
    assert isinstance(loop, LoopAgent)
    assert [a.name for a in loop.sub_agents] == ["reproducer", "verifier"]


def test_sub_agents_cannot_hand_off_control():
    root = build_agents(Settings())
    llm_agents = [
        a for a in [*root.sub_agents, *root.sub_agents[2].sub_agents] if isinstance(a, LlmAgent)
    ]
    assert len(llm_agents) == 5
    assert all(a.disallow_transfer_to_parent and a.disallow_transfer_to_peers for a in llm_agents)


def test_reproducer_can_stop_the_loop_for_non_bugs():
    reproducer = build_agents(Settings()).sub_agents[2].sub_agents[0]
    assert "exit_loop" in [getattr(t, "__name__", "") for t in reproducer.tools]


def test_models_and_loop_limit_are_configurable():
    root = build_agents(Settings(coordinator_model="c", worker_model="w", max_repro_attempts=2))
    retriever, _, loop, reporter = root.sub_agents
    assert retriever.model.model == "w"
    assert reporter.model.model == "c"
    assert loop.sub_agents[1].model.model == "c"  # verifier judges with the stronger model
    assert loop.max_iterations == 2


def test_models_retry_on_overload():
    retriever = build_agents(Settings(model_retry_attempts=3)).sub_agents[0]
    retry = retriever.model.retry_options
    assert retry.attempts == 3
    assert 503 in retry.http_status_codes and 429 in retry.http_status_codes
