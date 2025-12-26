"""
Deterministic Agent Execution Engine - FastAPI Application.

This is the entry point for the execution engine API.
It provides endpoints for:
- Creating agent runs
- Executing steps
- Approving sensitive operations
- Querying run status and costs
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings
from src.db.session import init_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.
    """
    settings = get_settings()
    print(f"    🚀  Starting Deterministic Agent Execution Engine on port {settings.server_port}")
    print(f"    📁  Workspace root: {settings.workspace_path}")
    print(f"    📊  Smart Model Router: {settings.smart_router_url}")
    
    # Initialize database connection
    await init_db()
    
    yield  # Application runs here
    
    # Shutdown
    print("👋 Shutting down Execution Engine...")
    # Close database connections
    await close_db()


# Create FastAPI application
app = FastAPI(
    title="Deterministic Agent Execution Engine",
    description="""
    A production-ready execution layer between LLM plans and real-world actions.
    
    ## Key Features
    - **Deterministic execution**: No hidden tool calls or implicit retries
    - **State persistence**: Resume from any step after failures
    - **Cost tracking**: Per-step cost accounting via Smart Model Router
    - **Human approval**: Required for sensitive operations (file edits, commands)
    """,
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware - allow all origins for development
# In production, restrict to specific origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===================
# Health Check Endpoint
# ===================
# This is REQUIRED for production deployments
# Container orchestrators (Kubernetes, Docker) use this to check if the app is alive

@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns the current status of the engine and its dependencies.
    Used by container orchestrators and load balancers.
    """
    settings = get_settings()
    
    # TODO: Add actual health checks for DB and Smart Router
    return {
        "status": "healthy",
        "service": "deterministic-agent-engine",
        "version": "0.1.0",
        "smart_router_url": settings.smart_router_url,
        "workspace_root": str(settings.workspace_path),
    }


@app.get("/")
async def root():
    """
    Root endpoint with API information.
    """
    return {
        "name": "Deterministic Agent Execution Engine",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "agent_runs": "/v1/agent-runs (coming soon)",
        },
    }


# ===================
# API Routers
# ===================
# We'll add these as we build them:
# app.include_router(agent_runs_router, prefix="/v1")
