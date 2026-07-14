import logging

import requests

logger = logging.getLogger(__name__)

BITGET_TICKERS_URL = "https://api.bitget.com/api/v2/mix/market/tickers"


def fetch_bitget_24h_changes():
    try:
        resp = requests.get(
            BITGET_TICKERS_URL,
            params={"productType": "USDT-FUTURES"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "00000":
            logger.warning("Bitget API error: %s", data.get("msg"))
            return {}

        changes = {}
        for ticker in data.get("data", []):
            symbol = ticker.get("symbol", "")
            change24h = ticker.get("change24h")
            if change24h is not None and change24h != "":
                try:
                    changes[symbol] = float(change24h)
                except (ValueError, TypeError):
                    pass
            else:
                open_price = ticker.get("openUtc")
                last_price = ticker.get("lastPr")
                if open_price and last_price:
                    try:
                        open_f = float(open_price)
                        last_f = float(last_price)
                        if open_f != 0:
                            changes[symbol] = (last_f - open_f) / open_f * 100
                    except (ValueError, TypeError):
                        pass

        logger.info("Bitget: %d pares con cambio 24h", len(changes))
        return changes

    except Exception as e:
        logger.error("Error consultando Bitget: %s", e)
        return {}
