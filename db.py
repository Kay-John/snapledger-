import os
from supabase import create_client

_sb = None
def get_supabase():
    global _sb
    if _sb is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            from config import SUPABASE_URL, SUPABASE_KEY
            url, key = SUPABASE_URL, SUPABASE_KEY
        _sb = create_client(url, key)
    return _sb
