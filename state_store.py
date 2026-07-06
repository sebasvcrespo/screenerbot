import json
import os
import requests

STATE_FILE = "state_cache.json"

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


def _file_store():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _file_save(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)


def _get(key):
    result = _request("GET", f"/get/{key}")
    if result and "result" in result:
        return result["result"]
    store = _file_store()
    return store.get(key)


def _set(key, value):
    _request("POST", f"/set/{key}", body=str(value))
    store = _file_store()
    store[key] = value
    _file_save(store)


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


def get_scan_interval():
    val = _get("scan_interval")
    return int(val) if val else None


def save_scan_interval(minutes):
    _set("scan_interval", str(minutes))


def get_paused_states():
    val = _get("paused_states")
    return json.loads(val) if val else None


def save_paused_states(states):
    _set("paused_states", json.dumps(states))
