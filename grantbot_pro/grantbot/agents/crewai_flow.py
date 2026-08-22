from __future__ import annotations

from typing import Type

from pydantic import BaseModel, Field

from grantbot.agents.crewai_runtime import (
    ORCHESTRATION_MODE,
    CrewRunResult,
    CrewRuntime,
    _readiness_status,
    _stage_result,
    crewai_installed,
    run_grant_crew_raw,
)


class GrantFlowState(BaseModel):
    dossier: str = ""
    question: str = ""
    max_words: int = Field(default=0, ge=0)
    requested_model: str = ""
    provider: str = ""
    model: str = ""
    crew_output: str = ""
    staging_artifact: str = ""
    staging_sha256: str = ""
    status: str = "PENDING"
    human_review_required: bool = True
    submission_performed: bool = False
    safe_to_submit: bool = False


def build_grant_flow_class() -> Type[object]:
    if not crewai_installed():
        raise RuntimeError(
            "CrewAI is not installed. Install GrantBot with: "
            "python -m pip install -e '.[agents]'"
        )

    from crewai.flow.flow import Flow, listen, start

    class GrantBotGrantFlow(Flow[GrantFlowState]):
        @start()
        def execute_specialist_crew(self) -> str:
            runtime, output = run_grant_crew_raw(
                dossier=self.state.dossier,
                question=self.state.question,
                max_words=self.state.max_words or None,
                model=self.state.requested_model or None,
            )
            self.state.provider = runtime.provider
            self.state.model = runtime.model or "unknown"
            self.state.crew_output = output
            self.state.status = _readiness_status(output)
            return output

        @listen(execute_specialist_crew)
        def persist_human_staging_artifact(self, output: str) -> CrewRunResult:
            runtime = CrewRuntime(
                available=True,
                provider=self.state.provider,
                model=self.state.model,
                base_url=None,
                mode="flow-runtime",
            )
            artifact_path, artifact_sha256 = _stage_result(
                runtime=runtime,
                dossier=self.state.dossier,
                question=self.state.question,
                max_words=self.state.max_words or None,
                output=output,
                status=self.state.status,
                orchestration=ORCHESTRATION_MODE,
            )
            self.state.staging_artifact = artifact_path
            self.state.staging_sha256 = artifact_sha256
            self.state.human_review_required = True
            self.state.submission_performed = False
            self.state.safe_to_submit = False
            return CrewRunResult(
                output=output,
                provider=self.state.provider,
                model=self.state.model,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                status=self.state.status,
                orchestration=ORCHESTRATION_MODE,
                safe_to_submit=False,
            )

    return GrantBotGrantFlow


def kickoff_grant_flow(
    *,
    dossier: str,
    question: str,
    max_words: int | None = None,
    model: str | None = None,
) -> CrewRunResult:
    if not dossier.strip():
        raise ValueError("dossier cannot be empty")
    if not question.strip():
        raise ValueError("question cannot be empty")
    if max_words is not None and max_words <= 0:
        raise ValueError("max_words must be positive when supplied")

    flow_class = build_grant_flow_class()
    flow = flow_class()
    result = flow.kickoff(
        inputs={
            "dossier": dossier,
            "question": question,
            "max_words": max_words or 0,
            "requested_model": model or "",
            "human_review_required": True,
            "submission_performed": False,
            "safe_to_submit": False,
        }
    )
    if isinstance(result, CrewRunResult):
        return result

    state = flow.state
    if not state.staging_artifact or not state.staging_sha256 or not state.crew_output:
        raise RuntimeError("CrewAI Flow completed without a valid staging receipt")

    return CrewRunResult(
        output=state.crew_output,
        provider=state.provider,
        model=state.model or "unknown",
        artifact_path=state.staging_artifact,
        artifact_sha256=state.staging_sha256,
        status=state.status,
        orchestration=ORCHESTRATION_MODE,
        safe_to_submit=False,
    )
