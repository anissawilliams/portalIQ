"""
PortalIQ — FastAPI Backend
===========================
Run locally:  uvicorn main:app --reload --port 8000
Docs:         http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import players, teams, analytics

app = FastAPI(
    title="PortalIQ",
    description="CFB NIL & Transfer Portal Analytics Platform",
    version="0.1.0",
)

# CORS — allow React frontend (and FSU demo) to hit the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(players.router)
app.include_router(teams.router)
app.include_router(analytics.router)


@app.get("/")
def root():
    return {
        "product": "PortalIQ",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "players": "/players/search, /players/moneyball, /players/portal-2026, /players/team/{team}",
            "teams":   "/teams/, /teams/nil-rankings, /teams/{team}, /teams/{team}/nil, /teams/{team}/seasons",
            "analytics": "/analytics/budget-optimizer, /analytics/program-comparison, /analytics/nil-roi",
        }
    }


@app.get("/health")
def health():
    return {"status": "ok"}
