"""FastAPI application for the Eurekan Refinery Planner.

The app loads the Gulf Coast configuration on startup via the lifespan
hook and exposes a thin REST surface over the Stage 1 engine. All
business logic lives in `services.RefineryService`; routes only marshal
HTTP requests / responses.

Start with 1 worker for Stage 2A (in-memory scenario store is not shared
across workers). Use --workers 2+ only after adding a shared store (Stage 2B)::

    uvicorn eurekan.api.app:app --port 8000
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eurekan.api.routes import ai as ai_routes
from eurekan.api.routes import config as config_routes
from eurekan.api.routes import optimize as optimize_routes
from eurekan.api.routes import oracle as oracle_routes
from eurekan.api.routes import scenarios as scenario_routes
from eurekan.api.services import RefineryService
from eurekan.parsers.gulf_coast import GulfCoastParser

DEFAULT_DATA_FILE = Path("data/gulf_coast/Gulf_Coast.xlsx")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load Gulf Coast data once on startup; nothing to tear down."""
    data_path = Path(os.environ.get("EUREKAN_DATA_FILE", DEFAULT_DATA_FILE))
    parser = GulfCoastParser(data_path)
    config = parser.parse()
    app.state.config = config
    app.state.service = RefineryService(config)
    yield


app = FastAPI(
    title="Eurekan Refinery Planner",
    version="0.2.0",
    description="Refinery planning optimization API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(optimize_routes.router)
app.include_router(config_routes.router)
app.include_router(scenario_routes.router)
app.include_router(oracle_routes.router)
app.include_router(ai_routes.router)


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness check — returns the number of crudes loaded into the config."""
    config = app.state.config
    crude_count = len(config.crude_library)
    return {
        "status": "ok",
        "crudes_loaded": crude_count,
        "is_stale": app.state.service.is_stale,
    }
