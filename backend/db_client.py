"""
db_client.py — Shared Supabase client
======================================
Import this anywhere in the backend instead of
inline create_client() calls.
"""

import os
from functools import lru_cache
from supabase import create_client, Client

SUPABASE_URL     = os.environ.get("SUPABASE_URL", "https://fpigpzmgqmzoxdknhetg.supabase.co")
SUPABASE_ANON    = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE = os.environ.get("SUPABASE_SERVICE_KEY", "")


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Shared anon client — for public reads."""
    return create_client(SUPABASE_URL, SUPABASE_ANON)


@lru_cache(maxsize=1)
def get_service_client() -> Client:
    """Service role client — for writes and admin reads."""
    key = SUPABASE_SERVICE or SUPABASE_ANON
    return create_client(SUPABASE_URL, key)