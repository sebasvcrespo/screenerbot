import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logger = logging.getLogger(__name__)

BITGET_CANDLES_URL = "https://api.bitget.com/api/v2/mix/market/candles"


def fetch_ohlcv(symbol, granularity="1H", limit=100):
    try:
        resp = requests.get(
            BITGET_CANDLES_URL,
            params={
                "symbol": symbol,
                "productType": "USDT-FUTURES",
                "granularity": granularity,
                "limit": str(limit),
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "00000":
            return []

        candles = []
        for c in data.get("data", []):
            if len(c) < 7:
                continue
            candles.append({
                "ts": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "base_vol": float(c[5]),
                "quote_vol": float(c[6]),
            })
        return candles

    except Exception:
        return []


def fetch_ohlcv_batch(symbols, granularity="1H", limit=100, max_workers=10):
    if not symbols:
        return {}

    results = {}

    def _fetch(sym):
        return sym, fetch_ohlcv(sym, granularity, limit)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch, s): s for s in symbols}
        for future in as_completed(futures):
            try:
                sym, candles = future.result()
                if candles:
                    results[sym] = candles
            except Exception:
                pass

    return results
