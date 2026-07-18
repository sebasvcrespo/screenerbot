import logging
import time

import requests

logger = logging.getLogger(__name__)

BITGET_TICKERS_URL = "https://api.bitget.com/api/v2/mix/market/tickers"

MAX_RETRIES = 2
RETRY_DELAY = 1.5


def fetch_bitget_data():
    last_err = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                BITGET_TICKERS_URL,
                params={"productType": "USDT-FUTURES"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "00000":
                logger.warning("Bitget API error (intento %d): %s", attempt, data.get("msg"))
                last_err = data.get("msg")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
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
                    except (ValueError, TypeError) as e:
                        logger.debug("Bitget change24h inválido para %s: %s = %s", symbol, change24h, e)

                if "change" not in entry:
                    open_price = ticker.get("openUtc")
                    last_price = ticker.get("lastPr")
                    if open_price and last_price:
                        try:
                            open_f = float(open_price)
                            last_f = float(last_price)
                            if open_f != 0:
                                entry["change"] = (last_f - open_f) / open_f * 100
                        except (ValueError, TypeError) as e:
                            logger.debug("Bitget fallback change inválido para %s: %s", symbol, e)

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

        except requests.exceptions.Timeout:
            last_err = "timeout"
            logger.warning("Bitget timeout (intento %d/%d)", attempt, MAX_RETRIES)
        except requests.exceptions.RequestException as e:
            last_err = str(e)
            logger.warning("Bitget error HTTP (intento %d/%d): %s", attempt, MAX_RETRIES, e)
        except Exception as e:
            last_err = str(e)
            logger.error("Bitget error inesperado: %s", e)
            return {}

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    logger.warning("Bitget: sin datos tras %d intentos (último error: %s)", MAX_RETRIES, last_err)
    return {}
