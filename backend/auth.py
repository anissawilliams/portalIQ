"""
auth.py — PortalIQ Authentication & Authorization
Uses Supabase JWT for auth, service role key for DB queries (bypasses RLS).
"""

import os
from typing import Optional
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL      = os.environ.get("SUPABASE_URL", "https://fpigpzmgqmzoxdknhetg.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_y1kHyx3hQ30UuxzpQbq7YA_bNRuG6RX")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def get_supabase() -> Client:
    """Anon client — for token verification only."""
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def get_supabase_admin() -> Client:
    """Service role client — bypasses RLS for server-side DB queries."""
    key = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
    return create_client(SUPABASE_URL, key)


@dataclass
class CurrentUser:
    id: str
    email: str
    school_id: Optional[str]
    school_name: Optional[str]
    role: str
    sport: str
    full_name: Optional[str]


security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> CurrentUser:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — provide a Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        # Verify token with anon client
        user_resp = get_supabase().auth.get_user(token)
        if not user_resp or not user_resp.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        user = user_resp.user

        # Fetch profile with admin client (bypasses RLS)
        profile_resp = (
            get_supabase_admin()
            .table("profiles")
            .select("*, schools(name, abbreviation, conference)")
            .eq("id", user.id)
            .execute()
        )

        profile = profile_resp.data[0] if profile_resp.data else {}
        school  = profile.get("schools") or {}

        return CurrentUser(
            id=user.id,
            email=user.email,
            school_id=profile.get("school_id"),
            school_name=school.get("name"),
            role=profile.get("role", "viewer"),
            sport=profile.get("sport", "football"),
            full_name=profile.get("full_name"),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[CurrentUser]:
    if not credentials:
        return None
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None


def require_role(*roles: str):
    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' not authorized. Required: {roles}",
            )
        return user
    return checker


def require_school(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.school_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No school associated with this account.",
        )
    return user