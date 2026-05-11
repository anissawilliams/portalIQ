"""
routers/watchlist.py — Portal target watchlist
Each school tracks their own targets — fully isolated by school via RLS.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from auth import get_current_user, require_school, require_role, CurrentUser, get_supabase

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


# =============================================================================
# SCHEMAS
# =============================================================================

class WatchlistAdd(BaseModel):
    player_name: str
    position: Optional[str] = None
    stars: Optional[float] = None
    origin_school: Optional[str] = None
    sport: str = "football"
    season: int = 2025
    est_nil_cost: Optional[float] = None
    notes: Optional[str] = None
    priority: int = 3  # 1=high, 2=med, 3=low


class WatchlistUpdate(BaseModel):
    status: Optional[str] = None   # tracking, contacted, offered, signed, passed
    notes: Optional[str] = None
    priority: Optional[int] = None
    est_nil_cost: Optional[float] = None


class NoteAdd(BaseModel):
    note: str


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/")
def get_watchlist(
    status: Optional[str] = None,
    position: Optional[str] = None,
    sport: str = Query(default="football"),
    season: Optional[int] = None,
    user: CurrentUser = Depends(require_school),
):
    """Get your school's portal watchlist."""
    supabase = get_supabase()

    query = (
        supabase.table("watchlist")
        .select("*, recruit_notes(note, created_at, profiles(full_name))")
        .eq("school_id", user.school_id)
        .eq("sport", sport)
        .order("priority")
        .order("created_at", desc=True)
    )

    if status:
        query = query.eq("status", status)
    if position:
        query = query.eq("position", position)
    if season:
        query = query.eq("season", season)

    resp = query.execute()

    return {
        "school":  user.school_name,
        "sport":   sport,
        "count":   len(resp.data),
        "players": resp.data,
    }


@router.post("/")
def add_to_watchlist(
    body: WatchlistAdd,
    user: CurrentUser = Depends(require_role("admin", "coach", "analyst")),
):
    """Add a player to your school's watchlist."""
    supabase = get_supabase()

    # Check not already on watchlist
    existing = (
        supabase.table("watchlist")
        .select("id")
        .eq("school_id", user.school_id)
        .eq("player_name", body.player_name)
        .eq("season", body.season)
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=409,
            detail=f"{body.player_name} is already on your watchlist for {body.season}",
        )

    resp = (
        supabase.table("watchlist")
        .insert({
            "school_id":     user.school_id,
            "added_by":      user.id,
            "player_name":   body.player_name,
            "position":      body.position,
            "stars":         body.stars,
            "origin_school": body.origin_school,
            "sport":         body.sport,
            "season":        body.season,
            "est_nil_cost":  body.est_nil_cost,
            "notes":         body.notes,
            "priority":      body.priority,
            "status":        "tracking",
        })
        .execute()
    )

    return {"message": f"Added {body.player_name} to watchlist", "player": resp.data[0]}


@router.patch("/{watchlist_id}")
def update_watchlist_entry(
    watchlist_id: str,
    body: WatchlistUpdate,
    user: CurrentUser = Depends(require_role("admin", "coach", "analyst")),
):
    """Update status, notes, priority, or estimated cost for a watchlist entry."""
    supabase = get_supabase()

    # Verify belongs to this school
    existing = (
        supabase.table("watchlist")
        .select("id, school_id")
        .eq("id", watchlist_id)
        .eq("school_id", user.school_id)
        .single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updates["updated_at"] = "now()"

    resp = (
        supabase.table("watchlist")
        .update(updates)
        .eq("id", watchlist_id)
        .execute()
    )

    return {"message": "Updated", "player": resp.data[0]}


@router.delete("/{watchlist_id}")
def remove_from_watchlist(
    watchlist_id: str,
    user: CurrentUser = Depends(require_role("admin", "coach", "analyst")),
):
    """Remove a player from your watchlist."""
    supabase = get_supabase()

    supabase.table("watchlist")\
        .delete()\
        .eq("id", watchlist_id)\
        .eq("school_id", user.school_id)\
        .execute()

    return {"message": "Removed from watchlist"}


@router.post("/{watchlist_id}/notes")
def add_note(
    watchlist_id: str,
    body: NoteAdd,
    user: CurrentUser = Depends(require_school),
):
    """Add a scouting note to a watchlist entry."""
    supabase = get_supabase()

    resp = (
        supabase.table("recruit_notes")
        .insert({
            "watchlist_id": watchlist_id,
            "author_id":    user.id,
            "note":         body.note,
        })
        .execute()
    )

    return {"message": "Note added", "note": resp.data[0]}


@router.get("/summary")
def watchlist_summary(
    sport: str = Query(default="football"),
    user: CurrentUser = Depends(require_school),
):
    """Summary stats for your school's watchlist."""
    supabase = get_supabase()

    resp = (
        supabase.table("watchlist")
        .select("status, position, stars, priority, est_nil_cost")
        .eq("school_id", user.school_id)
        .eq("sport", sport)
        .execute()
    )

    players = resp.data or []

    by_status = {}
    for p in players:
        s = p.get("status", "tracking")
        by_status[s] = by_status.get(s, 0) + 1

    total_est_spend = sum(
        p.get("est_nil_cost", 0) or 0
        for p in players
        if p.get("status") in ("offered", "signed")
    )

    return {
        "school":          user.school_name,
        "sport":           sport,
        "total_tracked":   len(players),
        "by_status":       by_status,
        "committed_spend": total_est_spend,
        "avg_stars":       round(
            sum(p.get("stars", 0) or 0 for p in players) / len(players), 2
        ) if players else 0,
        "high_priority":   len([p for p in players if p.get("priority") == 1]),
    }
