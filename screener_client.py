import requests

TV_SCREENER_URL = "https://scanner.tradingview.com/crypto/scan"

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

    resp = requests.post(TV_SCREENER_URL, json=payload, timeout=30)
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
