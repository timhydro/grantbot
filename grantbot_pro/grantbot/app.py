from fastapi import FastAPI

from grantbot import __app_name__, __organization__, __version__
from grantbot.security.auth import ensure_admin_key


ensure_admin_key()

app = FastAPI(
    title="GrantBot Pro Unified",
    version=__version__,
    description=(
        "Unified funding intelligence, mission-aware discovery ranking, canonical "
        "organization knowledge, production single-voice adaptive multi-model grant and IRS "
        "application writing, cloud-first role routing, model telemetry, funder memory, "
        "opportunity portfolio scoring, sentence-level provenance, adversarial review, "
        "authoritative compliance, financial consistency, evidence-calibrated risk, "
        "adjudicated human learning, post-award management, executive portfolio command center, "
        "controlled organizational document vault, CrewAI orchestration, persistent workflow control, "
        "and human-gated application platform."
    ),
)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {
        "name": __app_name__,
        "organization": __organization__,
        "version": __version__,
        "status": "active",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": __app_name__,
        "version": __version__,
    }


def main() -> None:
    print(f"{__app_name__} {__version__} Unified System Active")


if __name__ == "__main__":
    main()


from grantbot.api.master_pipeline_v5 import router as master_pipeline_v5_router
from grantbot.api.discovery_v6 import router as discovery_v6_router
from grantbot.api.application_v7 import router as application_v7_router
from grantbot.api.orchestrator_v8 import router as orchestrator_v8_router
from grantbot.api.nofo_v9 import router as nofo_v9_router
from grantbot.api.applicant_role_v10 import router as applicant_role_v10_router
from grantbot.api.orchestrator_v11 import router as orchestrator_v11_router
from grantbot.api.partners_v12 import router as partners_v12_router
from grantbot.api.nofo_v13 import router as nofo_v13_router
from grantbot.api.matching_v14 import router as matching_v14_router
from grantbot.api.readiness_v15 import router as readiness_v15_router
from grantbot.api.live_queue_v16 import compat_router as live_queue_v16_compat_router, router as live_queue_v16_router
from grantbot.api.staging_v17 import router as staging_v17_router
from grantbot.api.application_writer_v18 import router as application_writer_v18_router
from grantbot.api.packet_v19 import router as packet_v19_router
from grantbot.api.master import router as master_router
from grantbot.api.requirement_compliance import router as requirement_compliance_router
from grantbot.api.budget_consistency import router as budget_consistency_router
from grantbot.api.risk_intelligence import router as risk_intelligence_router
from grantbot.api.discovery_campaigns import router as discovery_campaigns_router
from grantbot.api.review_learning import router as review_learning_router
from grantbot.api.post_award import router as post_award_router
from grantbot.api.command_center import router as command_center_router
from grantbot.api.document_vault import router as document_vault_router
from grantbot.api.local_ai_v21 import router as local_ai_v21_router
from grantbot.api.discovery_quality_v22 import router as discovery_quality_v22_router
from grantbot.api.knowledge_v23 import router as knowledge_v23_router
from grantbot.api.funding_live_v24 import router as funding_live_v24_router
from grantbot.api.agentic_v26 import router as agentic_v26_router
from grantbot.api.workflow_v27 import router as workflow_v27_router
from grantbot.api.irs1023_v28 import router as irs1023_v28_router
from grantbot.api.multimodel_v28 import router as multimodel_v28_router
from grantbot.api.production_v29 import router as production_v29_router
from grantbot.api.intelligence_v30 import router as intelligence_v30_router
from grantbot.api.production_v30 import router as production_v30_router

app.include_router(master_pipeline_v5_router)
app.include_router(discovery_v6_router)
app.include_router(application_v7_router)
app.include_router(orchestrator_v8_router)
app.include_router(nofo_v9_router)
app.include_router(applicant_role_v10_router)
app.include_router(orchestrator_v11_router)
app.include_router(partners_v12_router)
app.include_router(nofo_v13_router)
app.include_router(matching_v14_router)
app.include_router(readiness_v15_router)
app.include_router(live_queue_v16_router)
app.include_router(live_queue_v16_compat_router)
app.include_router(staging_v17_router)
app.include_router(application_writer_v18_router)
app.include_router(packet_v19_router)
app.include_router(master_router)
app.include_router(requirement_compliance_router)
app.include_router(budget_consistency_router)
app.include_router(risk_intelligence_router)
app.include_router(discovery_campaigns_router)
app.include_router(review_learning_router)
app.include_router(post_award_router)
app.include_router(command_center_router)
app.include_router(document_vault_router)
app.include_router(local_ai_v21_router)
app.include_router(discovery_quality_v22_router)
app.include_router(knowledge_v23_router)
app.include_router(funding_live_v24_router)
app.include_router(agentic_v26_router)
app.include_router(workflow_v27_router)
app.include_router(irs1023_v28_router)
app.include_router(multimodel_v28_router)
app.include_router(production_v29_router)
app.include_router(intelligence_v30_router)
app.include_router(production_v30_router)
