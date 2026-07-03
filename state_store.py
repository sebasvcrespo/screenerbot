import json
import os
import requests

_rest_url = None
_rest_token = None


def _ensure():
    global _rest_url, _rest_token
    if _rest_url is None:
        _rest_url = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
        _rest_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")


def _request(method, path, body=None):
    _ensure()
    if not _rest_url:
        return None
    url = f"{_rest_url}{path}"
    headers = {"Authorization": f"Bearer {_rest_token}"}
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=10)
        else:
            resp = requests.post(url, headers=headers, data=body, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _get(key):
    result = _request("GET", f"/get/{key}")
    if result and "result" in result:
        return result["result"]
    return None


def _set(key, value):
    _request("POST", f"/set/{key}", body=str(value))


def get_offset():
    val = _get("telegram_offset")
    return int(val) if val else 0


def save_offset(offset):
    _set("telegram_offset", offset)


def get_exchange_states():
    val = _get("exchange_states")
    if val:
        return json.loads(val)
    return None


def save_exchange_states(states):
    _set("exchange_states", json.dumps(states))
