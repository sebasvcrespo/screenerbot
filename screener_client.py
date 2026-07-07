import logging
import time

import requests

logger = logging.getLogger(__name__)

TV_SCREENER_URL = "https://scanner.tradingview.com/crypto/scan"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
}

MAX_RETRIES = 3
BACKOFF_SECONDS = [30, 60, 120]

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
        "range": [0, 200]
    }

    for attempt in range(MAX_RETRIES + 1):
        resp = requests.post(TV_SCREENER_URL, json=payload, headers=HEADERS, timeout=30)

        if resp.status_code == 429 and attempt < MAX_RETRIES:
            wait = BACKOFF_SECONDS[attempt]
            logger.warning("HTTP 429 — reintentando en %ds (intento %d/%d)", wait, attempt + 1, MAX_RETRIES)
            time.sleep(wait)
            continue

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
