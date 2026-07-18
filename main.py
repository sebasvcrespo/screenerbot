import json
import logging
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from dotenv import load_dotenv
from screener_client import query_screener, ScreenerBlockedError
from bitget_client import fetch_bitget_data
from bitget_ohlcv import fetch_ohlcv, fetch_ohlcv_batch
from pionex_client import fetch_pionex_data
from pionex_ohlcv import fetch_pionex_ohlcv, fetch_pionex_ohlcv_batch
from indicators import calc_indicators_from_ohlcv, calc_1h_indicators, calc_4h_indicators, passes_1h_precheck
from detector import passes_filters
from telegram_notifier import send_alert, send_message, check_commands
from state_store import (
    get_offset,
    save_offset,
    get_exchange_states,
    save_exchange_states,
    get_scan_interval,
    save_scan_interval,
    get_paused_states,
    save_paused_states,
    get_blocked_until,
    set_blocked_until,
    clear_blocked_until,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"
DEFAULT_INTERVAL = 10

HELP_TEXT = """\
Comandos disponibles:
/start - Muestra tu chat_id
/help - Esta ayuda
/abrir <exchange> - Activa alertas (ej: /abrir bitget)
/cerrar <exchange> - Desactiva alertas (ej: /cerrar pionex)
/interval <minutos> - Cambia frecuencia de escaneo
/estado - Muestra configuraci\u00f3n actual
/pausar - Pausa todas las alertas
/reanudar - Reanuda alertas\
"""

PORT = int(os.environ.get("PORT", 10000))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        logger.info("HTTP: %s", format % args)


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info("Health server listening on port %d", PORT)
    server.serve_forever()


def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def format_status(exchanges, interval):
    lines = ["\U0001f4ca Estado actual", "Exchanges:"]
    for ex, st in sorted(exchanges.items()):
        icon = "\u2705" if st == "abierto" else "\u274c"
        lines.append(f"  {icon} {ex}: {st}")
    lines.append(f"Intervalo: {interval} min")
    return "\n".join(lines)


def format_indicators(row, screener_config):
    source = row.get("change_source", "")
    change_val = row.get("change")
    if change_val is not None:
        change_str = f"{change_val:.2f}%"
    else:
        change_str = None

    indicators = [
        ("Precio", f"${row.get('close'):.8f}" if row.get("close") else None),
        ("Cambio 24h", change_str),
        ("Vol USD", f"${row.get('volume'):,.0f}" if row.get("volume") else None),
    ]

    filters = screener_config.get("filters", {})

    if "rsi_1h" in filters and row.get("RSI|60") is not None:
        indicators.append(("RSI 1H", f"{row['RSI|60']:.1f}"))
    if "rsi_4h" in filters and row.get("RSI|240") is not None:
        indicators.append(("RSI 4H", f"{row['RSI|240']:.1f}"))
    if "adx_1h" in filters and row.get("ADX|60") is not None:
        indicators.append(("ADX 1H", f"{row['ADX|60']:.1f}"))
    if "adx_4h" in filters and row.get("ADX|240") is not None:
        indicators.append(("ADX 4H", f"{row['ADX|240']:.1f}"))
    if "atr_1h_pct" in filters and row.get("ATR|60") is not None and row.get("close"):
        atr_pct = row["ATR|60"] / row["close"] * 100
        indicators.append(("ATR 1H", f"{atr_pct:.2f}%"))

    if source:
        indicators.append(("Fuente", source))

    return indicators


def main():
    logger.info("=== TradingView Screener Agent ===")

    load_dotenv()

    bot_token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("CHAT_ID")
    if not bot_token or not chat_id:
        logger.error("Faltan variables de entorno: BOT_TOKEN y CHAT_ID")
        sys.exit(1)

    if isinstance(chat_id, str) and chat_id.lstrip("-").isdigit():
        chat_id = int(chat_id)

    try:
        config = load_config()
    except Exception as e:
        logger.error("Error cargando config.json: %s", e)
        sys.exit(1)

    if get_scan_interval() is None:
        save_scan_interval(DEFAULT_INTERVAL)

    exchanges = get_exchange_states()
    if exchanges is None:
        exchanges = dict(config.get("exchanges", {}))
        if not exchanges:
            exchanges = {"BITGET": "abierto", "PIONEX": "abierto"}

    blocked_until = get_blocked_until()
    if blocked_until > time.time():
        logger.warning(
            "IP bloqueada por Cloudflare — saltando ciclo hasta las %s",
            time.strftime("%H:%M:%S", time.localtime(blocked_until)),
        )
        return

    offset = get_offset()
    new_offset, actions = check_commands(bot_token, offset)

    for action in actions:
        t = action["type"]
        chat_origin = action["chat_id"]
        if t == "toggle":
            exchange = action["exchange"]
            estado = action["state"]
            if exchange in exchanges:
                exchanges[exchange] = estado
                logger.info("Comando: %s \u2192 %s", exchange, estado)
            else:
                send_message(
                    bot_token, chat_origin or chat_id,
                    f"\u274c Exchange '{exchange}' no reconocido"
                )
        elif t == "interval":
            mins = action["minutes"]
            save_scan_interval(mins)
            send_message(bot_token, chat_origin,
                         f"\u23f1 Intervalo cambiado a {mins} min")
            logger.info("Intervalo cambiado a %d min", mins)
        elif t == "help":
            send_message(bot_token, chat_origin, HELP_TEXT)
        elif t == "status":
            interval = get_scan_interval() or DEFAULT_INTERVAL
            send_message(bot_token, chat_origin,
                         format_status(exchanges, interval))
        elif t == "pause":
            save_paused_states(exchanges)
            for ex in exchanges:
                exchanges[ex] = "cerrado"
            save_exchange_states(exchanges)
            send_message(bot_token, chat_origin,
                         "\u23f8 Alertas pausadas")
            logger.info("Alertas pausadas")
        elif t == "resume":
            saved = get_paused_states()
            if saved:
                for ex in saved:
                    exchanges[ex] = "abierto"
                save_exchange_states(exchanges)
                send_message(bot_token, chat_origin,
                             "\u25b6\ufe0f Alertas reanudadas")
                logger.info("Alertas reanudadas")
            else:
                for ex, st in config.get("exchanges", {}).items():
                    if ex in exchanges and st == "abierto":
                        exchanges[ex] = "abierto"
                save_exchange_states(exchanges)
                send_message(bot_token, chat_origin,
                             "\u25b6\ufe0f Alertas reanudadas (desde config por defecto)")
                logger.info("Alertas reanudadas desde config por defecto")

    save_offset(new_offset)
    save_exchange_states(exchanges)

    activos = [ex for ex, st in exchanges.items() if st == "abierto"]

    if not activos:
        logger.info("Todos los exchanges cerrados. No se escanea.")
        return

    logger.info("Escaneando %s...", activos)

    rows = []
    try:
        rows = query_screener(activos)
        clear_blocked_until()
    except ScreenerBlockedError:
        set_blocked_until(time.time() + 900)
        return
    except Exception as e:
        logger.error("Error en screener: %s", e)
        return

    logger.info("Obtenidos %d pares en total", len(rows))

    for row in rows:
        row["change"] = None
        row["change_source"] = ""

    bitget_data = fetch_bitget_data()

    pionex_tv_symbols = []
    for row in rows:
        if row.get("exchange") == "PIONEX":
            symbol = row.get("name", "").replace(".P", "")
            if symbol:
                pionex_tv_symbols.append(symbol)
    pionex_data = fetch_pionex_data(pionex_tv_symbols)

    tv_symbols = set()
    for row in rows:
        name = row.get("name", "")
        base_symbol = name.replace(".P", "")
        tv_symbols.add(base_symbol)

        exchange_name = row.get("exchange", "")
        exchange_data = None
        if exchange_name == "BITGET":
            exchange_data = bitget_data.get(base_symbol)
        elif exchange_name == "PIONEX":
            exchange_data = pionex_data.get(base_symbol)

        if exchange_data:
            if "change" in exchange_data:
                row["change"] = exchange_data["change"]
                row["change_source"] = f"{exchange_name}_TICKER"
                logger.info("Change %s: %.4f%% [Fuente: %s_TICKER]", base_symbol, exchange_data["change"], exchange_name)
            if "volume_usd" in exchange_data:
                row["volume"] = exchange_data["volume_usd"]
            if "last_price" in exchange_data:
                row["close"] = exchange_data["last_price"]

    CRITICAL_INDICATORS = ["RSI|60", "ADX|60", "ADX+DI|60", "ADX-DI|60", "ATR|60", "ADX|240"]

    pairs_need_ohlcv = []
    for row in rows:
        for col in CRITICAL_INDICATORS:
            if row.get(col) is None:
                pairs_need_ohlcv.append(row)
                break

    if pairs_need_ohlcv:
        logger.info("Fetch OHLCV exchanges para %d pares con datos faltantes...", len(pairs_need_ohlcv))

        bitget_pairs = [r for r in pairs_need_ohlcv if r.get("exchange") == "BITGET"]
        pionex_pairs = [r for r in pairs_need_ohlcv if r.get("exchange") == "PIONEX"]

        if bitget_pairs:
            logger.info("Fetch OHLCV Bitget para %d pares...", len(bitget_pairs))
            for row in bitget_pairs:
                symbol = row["name"].replace(".P", "")
                candles_1h = fetch_ohlcv(symbol, "1H", 100)
                candles_4h = fetch_ohlcv(symbol, "4H", 100)
                if not candles_1h:
                    logger.warning("Sin OHLCV 1H Bitget para %s", symbol)
                    continue

                calculated = calc_indicators_from_ohlcv(candles_1h, candles_4h)

                if row.get("RSI|60") is None and "RSI|60" in calculated:
                    row["RSI|60"] = calculated["RSI|60"]
                if row.get("ADX|60") is None and "ADX|60" in calculated:
                    row["ADX|60"] = calculated["ADX|60"]
                if row.get("ADX+DI|60") is None and "ADX+DI|60" in calculated:
                    row["ADX+DI|60"] = calculated["ADX+DI|60"]
                if row.get("ADX-DI|60") is None and "ADX-DI|60" in calculated:
                    row["ADX-DI|60"] = calculated["ADX-DI|60"]
                if row.get("ATR|60") is None and "ATR|60" in calculated:
                    row["ATR|60"] = calculated["ATR|60"]
                if row.get("ADX|240") is None and "ADX|240" in calculated:
                    row["ADX|240"] = calculated["ADX|240"]
                if row.get("RSI|240") is None and "RSI|240" in calculated:
                    row["RSI|240"] = calculated["RSI|240"]
                if row.get("change") is None and "change_24h_calc" in calculated:
                    row["change"] = calculated["change_24h_calc"]
                    row["change_source"] = "BITGET_OHLCV"
                    logger.info("Change %s: %.4f%% [Fuente: BITGET_OHLCV]", symbol, calculated["change_24h_calc"])
                if row.get("close") is None and "close_calc" in calculated:
                    row["close"] = calculated["close_calc"]

                logger.info("OHLCV Bitget fallback %s completado", symbol)

        if pionex_pairs:
            logger.info("Fetch OHLCV Pionex para %d pares...", len(pionex_pairs))
            for row in pionex_pairs:
                symbol = row["name"].replace(".P", "")
                candles_1h = fetch_pionex_ohlcv(symbol, "1H", 100)
                candles_4h = fetch_pionex_ohlcv(symbol, "4H", 100)
                if not candles_1h:
                    logger.warning("Sin OHLCV 1H Pionex para %s", symbol)
                    continue

                calculated = calc_indicators_from_ohlcv(candles_1h, candles_4h)

                if row.get("RSI|60") is None and "RSI|60" in calculated:
                    row["RSI|60"] = calculated["RSI|60"]
                if row.get("ADX|60") is None and "ADX|60" in calculated:
                    row["ADX|60"] = calculated["ADX|60"]
                if row.get("ADX+DI|60") is None and "ADX+DI|60" in calculated:
                    row["ADX+DI|60"] = calculated["ADX+DI|60"]
                if row.get("ADX-DI|60") is None and "ADX-DI|60" in calculated:
                    row["ADX-DI|60"] = calculated["ADX-DI|60"]
                if row.get("ATR|60") is None and "ATR|60" in calculated:
                    row["ATR|60"] = calculated["ATR|60"]
                if row.get("ADX|240") is None and "ADX|240" in calculated:
                    row["ADX|240"] = calculated["ADX|240"]
                if row.get("RSI|240") is None and "RSI|240" in calculated:
                    row["RSI|240"] = calculated["RSI|240"]
                if row.get("change") is None and "change_24h_calc" in calculated:
                    row["change"] = calculated["change_24h_calc"]
                    row["change_source"] = "PIONEX_OHLCV"
                    logger.info("Change %s: %.4f%% [Fuente: PIONEX_OHLCV]", symbol, calculated["change_24h_calc"])
                if row.get("close") is None and "close_calc" in calculated:
                    row["close"] = calculated["close_calc"]

                logger.info("OHLCV Pionex fallback %s completado", symbol)

    pairs_need_change = []
    for row in rows:
        if row.get("change") is None:
            pairs_need_change.append(row)

    if pairs_need_change:
        logger.info("Fetch OHLCV para %d pares sin cambio 24h...", len(pairs_need_change))

        bitget_change = [r for r in pairs_need_change if r.get("exchange") == "BITGET"]
        pionex_change = [r for r in pairs_need_change if r.get("exchange") == "PIONEX"]

        for row in bitget_change:
            symbol = row["name"].replace(".P", "")
            candles_1h = fetch_ohlcv(symbol, "1H", 100)
            if not candles_1h:
                logger.warning("Sin OHLCV 1H para change Bitget %s", symbol)
                continue
            calc = calc_indicators_from_ohlcv(candles_1h, None)
            if "change_24h_calc" in calc:
                row["change"] = calc["change_24h_calc"]
                row["change_source"] = "BITGET_OHLCV"
                logger.info("Change %s: %.4f%% [Fuente: BITGET_OHLCV]", symbol, calc["change_24h_calc"])

        for row in pionex_change:
            symbol = row["name"].replace(".P", "")
            candles_1h = fetch_pionex_ohlcv(symbol, "1H", 100)
            if not candles_1h:
                logger.warning("Sin OHLCV 1H para change Pionex %s", symbol)
                continue
            calc = calc_indicators_from_ohlcv(candles_1h, None)
            if "change_24h_calc" in calc:
                row["change"] = calc["change_24h_calc"]
                row["change_source"] = "PIONEX_OHLCV"
                logger.info("Change %s: %.4f%% [Fuente: PIONEX_OHLCV]", symbol, calc["change_24h_calc"])

    if "BITGET" in activos:
        bitget_only_pairs = []
        for symbol, bd in bitget_data.items():
            if symbol in tv_symbols:
                continue
            if not symbol.endswith("USDT"):
                continue
            vol = bd.get("volume_usd", 0)
            if vol < 300000:
                continue
            change = bd.get("change", 0)
            if change < -8 or change > 8:
                continue
            bitget_only_pairs.append((symbol, bd))

        if bitget_only_pairs:
            logger.info("Pares Bitget no en TradingView: %d (vol>300K, change -8/+8)", len(bitget_only_pairs))

            symbols_1h = [s for s, _ in bitget_only_pairs]
            logger.info("Fetch OHLCV 1H paralelo para %d pares...", len(symbols_1h))
            batch_1h = fetch_ohlcv_batch(symbols_1h, "1H", 100, max_workers=10)

            candidates = []
            for symbol, bd in bitget_only_pairs:
                candles_1h = batch_1h.get(symbol)
                if not candles_1h:
                    continue
                if not passes_1h_precheck(candles_1h):
                    continue
                candidates.append((symbol, bd, candles_1h))

            logger.info("Pares que pasan pre-check 1H: %d / %d", len(candidates), len(bitget_only_pairs))

            if candidates:
                symbols_4h = [s for s, _, _ in candidates]
                logger.info("Fetch OHLCV 4H paralelo para %d candidates...", len(symbols_4h))
                batch_4h = fetch_ohlcv_batch(symbols_4h, "4H", 100, max_workers=10)

                for symbol, bd, candles_1h in candidates:
                    calc_1h = calc_1h_indicators(candles_1h)
                    candles_4h = batch_4h.get(symbol)
                    calc_4h = calc_4h_indicators(candles_4h) if candles_4h else {}

                    row = {
                        "name": symbol + ".P",
                        "exchange": "BITGET",
                        "close": calc_1h.get("close_calc"),
                        "change": bd.get("change"),
                        "change_source": "BITGET_TICKER" if bd.get("change") is not None else "",
                        "volume": bd.get("volume_usd"),
                        "change_volume": None,
                        "ATR|60": calc_1h.get("ATR|60"),
                        "Volatility.D": None,
                        "ADX|60": calc_1h.get("ADX|60"),
                        "ADX|240": calc_4h.get("ADX|240"),
                        "RSI|60": calc_1h.get("RSI|60"),
                        "RSI|240": calc_4h.get("RSI|240"),
                        "ADX+DI|60": calc_1h.get("ADX+DI|60"),
                        "ADX-DI|60": calc_1h.get("ADX-DI|60"),
                    }
                    rows.append(row)

    ex_counts = {}
    for r in rows:
        ex = r.get("exchange", "?")
        ex_counts[ex] = ex_counts.get(ex, 0) + 1

    screeners_alerts = {}

    for screener_key, screener_cfg in config["screeners"].items():
        logger.info("Filtrando %s...", screener_cfg["name"])
        alerts_by_ex = {}
        for row in rows:
            if passes_filters(row, screener_cfg["filters"]):
                pair = row.get("name", "?")
                exchange = row.get("exchange", "?")
                indicators = format_indicators(row, screener_cfg)

                logger.info("ALERTA %s: %s en %s", screener_cfg["name"], pair, exchange)

                try:
                    send_alert(
                        bot_token,
                        chat_id,
                        screener_cfg["name"],
                        screener_cfg.get("emoji", ""),
                        pair,
                        exchange,
                        indicators,
                    )
                except Exception as e:
                    logger.error("Error enviando alerta: %s", e)

                alerts_by_ex[exchange] = alerts_by_ex.get(exchange, 0) + 1

        screeners_alerts[screener_key] = alerts_by_ex
        total = sum(alerts_by_ex.values())
        logger.info("%s: %d alertas enviadas", screener_cfg["name"], total)

    lines = ["\u2705 Ciclo completado", f"Pares evaluados: {len(rows)}"]
    for ex, n in sorted(ex_counts.items()):
        lines.append(f"  {ex}: {n}")
    for sk, sc in config["screeners"].items():
        ac = screeners_alerts.get(sk, {})
        total = sum(ac.values())
        lines.append(f"{sc.get('emoji', '')} {sc['name']}: {total} alertas")
        for ex, n in sorted(ac.items()):
            lines.append(f"  {ex}: {n}")
    send_message(bot_token, chat_id, "\n".join(lines))

    logger.info("Ciclo completado.")


if __name__ == "__main__":
    if "--server" in sys.argv:
        threading.Thread(target=run_health_server, daemon=True).start()
        logger.info("Modo servidor iniciado (health check + loop)")
        loop = True
    else:
        loop = "--loop" in sys.argv

    while True:
        main()
        if not loop:
            break
        interval = get_scan_interval() or DEFAULT_INTERVAL
        logger.info("Esperando %d minutos para el pr\u00f3ximo ciclo...", interval)
        time.sleep(interval * 60)
