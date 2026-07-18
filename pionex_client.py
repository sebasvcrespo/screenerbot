import logging

import requests

logger = logging.getLogger(__name__)

PIONEX_TICKERS_URL = "https://api.pionex.com/api/v1/market/tickers"


def fetch_pionex_ticker(symbol):
    pionex_symbol = f"{symbol}_USDT_PERP"
    try:
        resp = requests.get(
            PIONEX_TICKERS_URL,
            params={"symbol": pionex_symbol},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        tickers = data.get("data", {}).get("tickers", [])
        if not tickers:
            return None

        ticker = tickers[0]
        entry = {}

        last_price = ticker.get("close")
        open_price = ticker.get("open")

        if last_price and open_price:
            try:
                last_f = float(last_price)
                open_f = float(open_price)
                if open_f != 0:
                    entry["change"] = (last_f - open_f) / open_f * 100
                    entry["last_price"] = last_f
            except (ValueError, TypeError):
                pass

        if "last_price" not in entry and last_price:
            try:
                entry["last_price"] = float(last_price)
            except (ValueError, TypeError):
                pass

        amount = ticker.get("amount")
        if amount is not None and amount != "":
            try:
                entry["volume_usd"] = float(amount)
            except (ValueError, TypeError):
                pass

        return entry if entry else None

    except Exception:
        return None


def fetch_pionex_data(symbols):
    result = {}
    for symbol in symbols:
        entry = fetch_pionex_ticker(symbol)
        if entry:
            result[symbol] = entry

    logger.info("Pionex: %d pares con datos de %d consultados", len(result), len(symbols))
    return result
