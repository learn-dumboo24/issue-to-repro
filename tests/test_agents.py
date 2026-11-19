from google.adk.agents import LoopAgent

from issue_to_repro.agents import build_agents
from issue_to_repro.config import Settings


def test_hierarchy():
    root = build_agents(Settings())
    assert root.name == "coordinator"
    assert [a.name for a in root.sub_agents] == ["retriever", "classifier", "repro_loop"]
    loop = root.sub_agents[2]
    assert isinstance(loop, LoopAgent)
    assert [a.name for a in loop.sub_agents] == ["reproducer", "verifier"]


def test_models_and_loop_limit_are_configurable():
    root = build_agents(Settings(coordinator_model="c", worker_model="w", max_repro_attempts=2))
    assert root.model == "c"
    assert root.sub_agents[0].model == "w"
    assert root.sub_agents[2].max_iterations == 2
