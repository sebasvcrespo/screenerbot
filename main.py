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

    try:
        config = load_config()
    except Exception as e:
        logger.error("Error cargando config.json: %s", e)
        sys.exit(1)

    # 1. Estados de exchanges: Redis con fallback a config.json
    exchanges = get_exchange_states()
    if exchanges is None:
        exchanges = dict(config.get("exchanges", {}))
        if not exchanges:
            exchanges = {"BITGET": "abierto", "PIONEX": "abierto"}

    # 2. Procesar comandos Telegram
    offset = get_offset()
    new_offset, toggles = check_commands(bot_token, offset)

    for exchange, estado, chat_origin in toggles:
        if exchange in exchanges:
            exchanges[exchange] = estado
            msg = f"✅ {exchange}: {estado.upper()}"
            send_message(bot_token, chat_origin or chat_id, msg)
            logger.info("Comando: %s → %s", exchange, estado)
        else:
            send_message(
                bot_token, chat_origin or chat_id,
                f"❌ Exchange '{exchange}' no reconocido"
            )

    save_offset(new_offset)
    save_exchange_states(exchanges)

    # 3. Exchanges activos
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

    # 4. Filtrar y enviar alertas
    for screener_key, screener_cfg in config["screeners"].items():
        logger.info("Filtrando %s...", screener_cfg["name"])
        count = 0
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

                count += 1

        logger.info("%s: %d alertas enviadas", screener_cfg["name"], count)

    logger.info("Ciclo completado.")


if __name__ == "__main__":
    main()
