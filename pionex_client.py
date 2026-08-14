import logging
import time

import requests

logger = logging.getLogger(__name__)

PIONEX_TICKERS_URL = "https://api.pionex.com/api/v1/market/tickers"
PIONEX_FUNDING_URL = "https://api.pionex.com/api/v1/market/fundingRates"

MAX_RETRIES = 2
RETRY_DELAY = 1.5


def _symbol_to_pionex(symbol):
    if symbol.endswith("_PERP") or "_BTC_" in symbol:
        return symbol
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    return f"{base}_USDT_PERP"


def _parse_ticker(ticker, btc_price=None):
    entry = {}
    last_price = ticker.get("close")
    open_price = ticker.get("open")
    sym = ticker.get("symbol", "")

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
            amt_f = float(amount)
            if "_BTC_" in sym:
                if btc_price:
                    entry["volume_usd"] = amt_f * btc_price
                else:
                    entry["volume_usd"] = 0
            else:
                entry["volume_usd"] = amt_f
        except (ValueError, TypeError):
            pass

    return entry if entry else None


def fetch_pionex_data(symbols):
    if not symbols:
        return {}

    all_tickers = {}
    last_err = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                PIONEX_TICKERS_URL,
                params={"type": "PERP"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("result"):
                logger.warning("Pionex batch API result=false (intento %d)", attempt)
                last_err = "result=false"
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                return {}

            for ticker in data.get("data", {}).get("tickers", []):
                sym = ticker.get("symbol", "")
                if sym:
                    all_tickers[sym] = ticker

            logger.info("Pionex batch: %d perpetuos cargados", len(all_tickers))
            break

        except requests.exceptions.Timeout:
            last_err = "timeout"
            logger.warning("Pionex batch timeout (intento %d/%d)", attempt, MAX_RETRIES)
        except requests.exceptions.RequestException as e:
            last_err = str(e)
            logger.warning("Pionex batch error HTTP (intento %d/%d): %s", attempt, MAX_RETRIES, e)
        except Exception as e:
            last_err = str(e)
            logger.error("Pionex batch error inesperado: %s", e)
            return {}

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    if not all_tickers:
        logger.warning("Pionex: sin datos batch tras %d intentos (%s)", MAX_RETRIES, last_err)
        return {}

    btc_ticker = all_tickers.get("BTC_USDT_PERP")
    btc_price = 0
    if btc_ticker and btc_ticker.get("close"):
        try:
            btc_price = float(btc_ticker.get("close"))
        except (ValueError, TypeError):
            pass

    result = {}
    found = 0
    not_found = 0

    for symbol in symbols:
        pionex_sym = _symbol_to_pionex(symbol)
        ticker = all_tickers.get(pionex_sym)

        if ticker:
            entry = _parse_ticker(ticker, btc_price)
            if entry:
                result[symbol] = entry
                found += 1
        else:
            not_found += 1

    logger.info("Pionex: %d/%d pares matcheados (%d sin match en API)", found, len(symbols), not_found)
    return result


def fetch_pionex_funding(symbol):
    """Devuelve el funding rate más reciente en % (p.ej. 0.01) o None si falla."""
    pionex_sym = _symbol_to_pionex(symbol)
    try:
        resp = requests.get(
            PIONEX_FUNDING_URL,
            params={"symbol": pionex_sym},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("result"):
            return None
        rates = data.get("data", {}).get("rates", [])
        if not rates:
            return None
        rate = rates[0].get("fundingRate")
        if rate is None or rate == "":
            return None
        return float(rate) * 100
    except Exception as e:
        logger.debug("Pionex funding falló para %s: %s", pionex_sym, e)
        return None
