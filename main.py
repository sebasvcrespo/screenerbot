import json
import logging
import os
import sys

from screener_client import query_screener
from detector import passes_filters
from telegram_notifier import send_alert, send_message, check_commands
from state_store import get_offset, save_offset, get_exchange_states, save_exchange_states

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"


def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


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

    exchanges = get_exchange_states()
    if exchanges is None:
        exchanges = dict(config.get("exchanges", {}))
        if not exchanges:
            exchanges = {"BITGET": "abierto", "PIONEX": "abierto"}

    offset = get_offset()
    new_offset, toggles = check_commands(bot_token, offset)

    for exchange, estado, chat_origin in toggles:
        if exchange in exchanges:
            exchanges[exchange] = estado
            logger.info("Comando: %s → %s", exchange, estado)
        else:
            send_message(
                bot_token, chat_origin or chat_id,
                f"❌ Exchange '{exchange}' no reconocido"
            )

    save_offset(new_offset)
    save_exchange_states(exchanges)

    activos = [ex for ex, st in exchanges.items() if st == "abierto"]

    if not activos:
        logger.info("Todos los exchanges cerrados. No se escanea.")
        return

    logger.info("Escaneando %s...", activos)

    try:
        rows = query_screener(activos)
    except Exception as e:
        logger.error("Error en screener: %s", e)
        return

    logger.info("Obtenidos %d pares", len(rows))

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

    lines = ["✅ Ciclo completado", f"Pares evaluados: {len(rows)}"]
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
    main()
