"""Entry point for `adk web` / `adk run`, which look for a module-level `root_agent`."""

from .agents import build_agents

root_agent = build_agents()
