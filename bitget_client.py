import logging

import requests

logger = logging.getLogger(__name__)

BITGET_TICKERS_URL = "https://api.bitget.com/api/v2/mix/market/tickers"


def fetch_bitget_data():
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

        result = {}
        for ticker in data.get("data", []):
            symbol = ticker.get("symbol", "")
            if not symbol:
                continue

            entry = {}

            change24h = ticker.get("change24h")
            if change24h is not None and change24h != "":
                try:
                    entry["change"] = float(change24h) * 100
                except (ValueError, TypeError):
                    pass

            if "change" not in entry:
                open_price = ticker.get("openUtc")
                last_price = ticker.get("lastPr")
                if open_price and last_price:
                    try:
                        open_f = float(open_price)
                        last_f = float(last_price)
                        if open_f != 0:
                            entry["change"] = (last_f - open_f) / open_f * 100
                    except (ValueError, TypeError):
                        pass

            usdt_volume = ticker.get("usdtVolume") or ticker.get("quoteVolume")
            if usdt_volume is not None and usdt_volume != "":
                try:
                    entry["volume_usd"] = float(usdt_volume)
                except (ValueError, TypeError):
                    pass

            last_pr = ticker.get("lastPr")
            if last_pr is not None and last_pr != "":
                try:
                    entry["last_price"] = float(last_pr)
                except (ValueError, TypeError):
                    pass

            if entry:
                result[symbol] = entry

        logger.info("Bitget: %d pares con datos", len(result))
        return result

    except Exception as e:
        logger.error("Error consultando Bitget: %s", e)
        return {}
