import logging
import random
import time

import requests

logger = logging.getLogger(__name__)

TV_BASE_URL = "https://www.tradingview.com"
TV_SCREENER_URL = "https://scanner.tradingview.com/crypto/scan"


class ScreenerBlockedError(Exception):
    """Se lanza cuando la IP está bloqueada por Cloudflare (HTTP 429)."""


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

HEADERS_BASE = {
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "Accept": "application/json",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

_session = None


def _get_session():
    global _session
    if _session is not None:
        return _session
    _session = requests.Session()
    _session.headers.update(HEADERS_BASE)
    _session.headers["User-Agent"] = random.choice(USER_AGENTS)
    try:
        _session.get(TV_BASE_URL, timeout=15)
        logger.info("Sesión TradingView iniciada (UA: %s...)",
                     _session.headers["User-Agent"][:40])
    except Exception as e:
        logger.warning("No se pudieron obtener cookies de TradingView: %s", e)
    return _session

COLUMNS = [
    "name",
    "exchange",
    "close",
    "change",
    "volume",
    "change_volume",
    "ATR|60",
    "Volatility.D",
    "ADX|60",
    "ADX|240",
    "RSI|60",
    "RSI|240",
    "ADX+DI|60",
    "ADX-DI|60",
]


def query_screener(exchanges):
    filter_conditions = [
        {"left": "exchange", "operation": "in_range", "right": exchanges},
        {"left": "name", "operation": "match", "right": "USDT.P"},
    ]

    payload = {
        "symbols": {
            "query": {"types": []},
            "tickers": []
        },
        "columns": COLUMNS,
        "filter": filter_conditions,
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "range": [0, 500]
    }

    sesion = _get_session()

    sesion.headers["User-Agent"] = random.choice(USER_AGENTS)
    jitter_secs = random.uniform(3, 8)
    time.sleep(jitter_secs)

    resp = sesion.post(TV_SCREENER_URL, json=payload, timeout=30)

    if resp.status_code == 429:
        raise ScreenerBlockedError("IP bloqueada por Cloudflare (HTTP 429)")

    resp.raise_for_status()
    return _parse_response(resp.json())


def _parse_response(data):
    results = []
    for item in data.get("data", []):
        values = item.get("d", [])
        row = {"symbol": item.get("s", "")}
        for i, col in enumerate(COLUMNS):
            row[col] = values[i] if i < len(values) else None
        results.append(row)
    return results
