"""
PortalIQ — FastAPI Backend
"""

import os
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from routers import players, teams, analytics, projections, watchlist, rosters

app = FastAPI(
    title="PortalIQ",
    description="CFB NIL & Transfer Portal Analytics Platform",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(players.router)
app.include_router(teams.router)
app.include_router(analytics.router)
app.include_router(projections.router)
app.include_router(watchlist.router)
app.include_router(rosters.router)   # ← 2026 ESPN roster data

security = HTTPBearer(auto_error=False)


@app.get("/")
def root():
    return {
        "product": "PortalIQ",
        "version": "0.3.0",
        "status":  "running",
        "docs":    "/docs",
        "data": {
            "portal": "2025 transfer portal (22 players/team)",
            "rosters": "2026 ESPN full rosters (13,765 players, all FBS)",
        }
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/me")
def me(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """Returns current user — inline auth to avoid caching issues."""
    if not credentials:
        return {"authenticated": False, "user": None}

    token = credentials.credentials

    try:
        from supabase import create_client
        url     = os.environ.get("SUPABASE_URL", "https://fpigpzmgqmzoxdknhetg.supabase.co")
        anon    = os.environ.get("SUPABASE_ANON_KEY", "")
        service = os.environ.get("SUPABASE_SERVICE_KEY", "")

        user_resp = create_client(url, anon).auth.get_user(token)
        if not user_resp or not user_resp.user:
            return {"authenticated": False, "user": None}

        profile_resp = (
            create_client(url, service or anon)
            .table("profiles")
            .select("*, schools(name)")
            .eq("id", user_resp.user.id)
            .execute()
        )
        profile = profile_resp.data[0] if profile_resp.data else {}
        school  = profile.get("schools") or {}

        return {
            "authenticated": True,
            "user": {
                "id":        user_resp.user.id,
                "email":     user_resp.user.email,
                "full_name": profile.get("full_name"),
                "school":    school.get("name"),
                "role":      profile.get("role", "viewer"),
                "sport":     profile.get("sport", "football"),
            }
        }
    except Exception as e:
        return {"authenticated": False, "error": str(e)}