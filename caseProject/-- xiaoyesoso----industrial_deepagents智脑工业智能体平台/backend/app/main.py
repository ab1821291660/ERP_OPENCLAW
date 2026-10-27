"""FastAPI application entrypoint: wires routers, health, static frontend."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT#industrial_deepagents//
from .db import init_db##===================================
from .api import agents, auth, evals, industrial, tenants, threads, tools, traces
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()##===================================
    yield


app = FastAPI(title="DeepAgents Platform", version="0.1.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces to clients; trace table keeps the detail server-side.
    return JSONResponse(status_code=500, content={"detail": f"服务器内部错误：{type(exc).__name__}"})


@app.get("/health")
def health():
    return {"status": "ok"}


for r in (auth.router, tenants.router, agents.router, tools.router,
          threads.router, evals.router, traces.router, industrial.router):
    app.include_router(r, prefix="/api")




# Serve the single-file React app from the same origin (last so /api wins).
frontend_dir = PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")##===================================

