from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent import router as agent_router
from app.api.agent_trace import router as agent_trace_router
from app.api.cost import router as cost_router
from app.api.data import router as data_router
from app.api.forecast import router as forecast_router
from app.api.health import router as health_router
from app.api.optimization import router as optimization_router
from app.api.resources import router as resources_router
from app.api.settings import router as settings_router
from app.api.usage import router as usage_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

# Local dev origins always work without any env var; production origins come
# from ALLOWED_ORIGINS (comma-separated exact matches — e.g. the Vercel
# production URL). Vercel preview deployments get their own random
# *.vercel.app subdomain per branch/PR, so those are matched via
# allow_origin_regex instead of requiring ALLOWED_ORIGINS to be updated
# every time one is created.
_default_dev_origins = ["http://localhost:5173", "http://localhost:5174"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[*_default_dev_origins, *settings.allowed_origins_list],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
def root_health() -> dict:
    """Unauthenticated liveness check with no DB dependency — used as
    Render's healthCheckPath. GET /api/health (below) also checks DB
    connectivity and is what the frontend's Settings page calls."""
    return {"status": "ok"}


app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(data_router, prefix="/api/data", tags=["data"])
app.include_router(forecast_router, prefix="/api/forecast", tags=["forecast"])
app.include_router(cost_router, prefix="/api/cost", tags=["cost"])
app.include_router(optimization_router, prefix="/api/optimization", tags=["optimization"])
app.include_router(resources_router, prefix="/api/resources", tags=["resources"])
app.include_router(usage_router, prefix="/api/usage", tags=["usage"])
app.include_router(agent_router, prefix="/api/agent", tags=["agent"])
app.include_router(agent_trace_router, prefix="/api/agent-trace", tags=["agent-trace"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
