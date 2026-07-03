import os
import redis

_r = None


def _get_client():
    global _r
    if _r is None:
        url = os.environ.get("REDIS_URL")
        if not url:
            url = "redis://localhost:6379/0"
        _r = redis.Redis.from_url(url, decode_responses=True)
    return _r


def get_offset():
    r = _get_client()
    val = r.get("telegram_offset")
    return int(val) if val else 0


def save_offset(offset):
    r = _get_client()
    r.set("telegram_offset", str(offset))
