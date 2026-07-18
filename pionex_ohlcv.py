import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logger = logging.getLogger(__name__)

PIONEX_KLINES_URL = "https://api.pionex.com/api/v1/market/klines"

GRANULARITY_MAP = {
    "1H": "60M",
    "4H": "240M",
}


def fetch_pionex_ohlcv(symbol, granularity="1H", limit=100):
    pionex_interval = GRANULARITY_MAP.get(granularity, granularity)
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    pionex_symbol = f"{base}_USDT_PERP"

    try:
        resp = requests.get(
            PIONEX_KLINES_URL,
            params={
                "symbol": pionex_symbol,
                "interval": pionex_interval,
                "limit": str(limit),
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("data"):
            return []

        klines = data["data"].get("klines", [])
        if not klines:
            return []

        candles = []
        for c in klines:
            if isinstance(c, dict):
                candles.append({
                    "ts": int(c.get("time", 0)),
                    "open": float(c.get("open", 0)),
                    "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)),
                    "close": float(c.get("close", 0)),
                    "base_vol": float(c.get("volume", 0)),
                    "quote_vol": float(c.get("volume", 0)),
                })
            elif isinstance(c, list) and len(c) >= 6:
                candles.append({
                    "ts": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "base_vol": float(c[5]),
                    "quote_vol": float(c[5]),
                })
        return candles

    except Exception:
        return []


def fetch_pionex_ohlcv_batch(symbols, granularity="1H", limit=100, max_workers=10):
    if not symbols:
        return {}

    results = {}

    def _fetch(sym):
        return sym, fetch_pionex_ohlcv(sym, granularity, limit)

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
