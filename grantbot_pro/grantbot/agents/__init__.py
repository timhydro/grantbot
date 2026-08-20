"""Agentic orchestration for GrantBot Pro.

The core GrantBot application does not require CrewAI.  The optional CrewAI
bridge is loaded only when the ``agents`` dependency extra is installed.
"""

from grantbot.agents.crewai_local import crewai_status
from grantbot.agents.pipeline_v26 import AGENT_ROLES, build_execution_plan

__all__ = ["AGENT_ROLES", "build_execution_plan", "crewai_status"]
