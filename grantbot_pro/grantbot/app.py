from fastapi import FastAPI
import sys

app = FastAPI(title="GrantBot Pro", version="5.0.0")
def main() -> None:
    print("GrantBot System Active")

if __name__ == "__main__":
    main()

from grantbot.api.master_pipeline_v5 import router as master_pipeline_v5_router

app.include_router(master_pipeline_v5_router)

from grantbot.api.discovery_v6 import router as discovery_v6_router
app.include_router(discovery_v6_router)

from grantbot.api.application_v7 import router as application_v7_router
app.include_router(application_v7_router)

from grantbot.api.orchestrator_v8 import router as orchestrator_v8_router
app.include_router(orchestrator_v8_router)

from grantbot.api.nofo_v9 import router as nofo_v9_router
app.include_router(nofo_v9_router)

from grantbot.api.applicant_role_v10 import router as applicant_role_v10_router
app.include_router(applicant_role_v10_router)

from grantbot.api.orchestrator_v11 import router as orchestrator_v11_router
app.include_router(orchestrator_v11_router)

from grantbot.api.partners_v12 import router as partners_v12_router
app.include_router(partners_v12_router)

from grantbot.api.nofo_v13 import router as nofo_v13_router
app.include_router(nofo_v13_router)

from grantbot.api.matching_v14 import router as matching_v14_router
app.include_router(matching_v14_router)

from grantbot.api.readiness_v15 import router as readiness_v15_router
app.include_router(readiness_v15_router)

from grantbot.api.live_queue_v16 import router as live_queue_v16_router, compat_router as live_queue_v16_compat_router
app.include_router(live_queue_v16_router)
app.include_router(live_queue_v16_compat_router)

from grantbot.api.staging_v17 import router as staging_v17_router
app.include_router(staging_v17_router)
