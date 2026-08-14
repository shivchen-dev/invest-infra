from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from invest_api.config import get_settings
from invest_api.routers.admission import router as admission_router
from invest_api.routers.candidate_pool import router as candidate_pool_router
from invest_api.routers.data_freshness import router as data_freshness_router
from invest_api.routers.etf import router as etf_router
from invest_api.routers.external_workflows import router as external_workflows_router
from invest_api.routers.integration_health import router as integration_health_router
from invest_api.routers.market_breadth import router as market_breadth_router
from invest_api.routers.market_temperature import router as market_temperature_router
from invest_api.routers.opportunity_radar import router as opportunity_radar_router
from invest_api.routers.pipeline_runs import router as pipeline_runs_router
from invest_api.routers.research import router as research_router
from invest_api.routers.research_external_evidence import (
    router as research_external_evidence_router,
)
from invest_api.routes import router

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(etf_router)
app.include_router(external_workflows_router)
app.include_router(integration_health_router)
app.include_router(opportunity_radar_router)
app.include_router(candidate_pool_router)
app.include_router(admission_router)
app.include_router(pipeline_runs_router)
app.include_router(data_freshness_router)
app.include_router(research_router)
app.include_router(research_external_evidence_router)
app.include_router(market_temperature_router)
app.include_router(market_breadth_router)
