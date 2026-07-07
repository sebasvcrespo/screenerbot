import json
import logging
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from dotenv import load_dotenv
from screener_client import query_screener, ScreenerBlockedError
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
    indicators = [
        ("Precio", f"${row.get('close'):.8f}" if row.get("close") else None),
        ("Cambio 24h", f"{row.get('change'):.2f}%" if row.get("change") is not None else None),
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
