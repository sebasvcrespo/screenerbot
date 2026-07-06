import logging

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_GET_UPDATES = "https://api.telegram.org/bot{token}/getUpdates"


def send_alert(bot_token, chat_id, screener_name, screener_emoji, pair, exchange, indicators):
    lines = [
        f"{screener_emoji} {screener_name} ALERT",
        f"Par: {pair}",
        f"Exchange: {exchange}",
    ]
    for label, value in indicators:
        if value is not None:
            lines.append(f"{label}: {value}")

    text = "\n".join(lines)
    url = TELEGRAM_API_URL.format(token=bot_token)

    resp = requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
    }, timeout=15)

    if not resp.ok:
        logger.error("Telegram respondio con %d: %s", resp.status_code, resp.json())

    resp.raise_for_status()
    return resp.json()


def send_message(bot_token, chat_id, text):
    url = TELEGRAM_API_URL.format(token=bot_token)
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
        }, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return None


def check_commands(bot_token, offset):
    url = TELEGRAM_GET_UPDATES.format(token=bot_token)
    params = {"offset": offset, "timeout": 5}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return offset, []

        data = resp.json()
        actions = []
        last_id = offset

        for update in data.get("result", []):
            last_id = max(last_id, update["update_id"] + 1)
            msg = update.get("message", {})
            text = msg.get("text", "").strip().lower()
            chat_id_msg = msg.get("chat", {}).get("id")

            if text == "/start":
                send_message(bot_token, chat_id_msg,
                             f"Bot activo. Tu chat_id es: {chat_id_msg}")
                continue

            if text == "/help":
                actions.append({"type": "help", "chat_id": chat_id_msg})
                continue

            if text == "/estado":
                actions.append({"type": "status", "chat_id": chat_id_msg})
                continue

            if text == "/pausar":
                actions.append({"type": "pause", "chat_id": chat_id_msg})
                continue

            if text == "/reanudar":
                actions.append({"type": "resume", "chat_id": chat_id_msg})
                continue

            if text.startswith("/interval "):
                parts = text.split()
                if len(parts) == 2:
                    try:
                        mins = int(parts[1])
                        if mins > 0:
                            actions.append({"type": "interval", "minutes": mins, "chat_id": chat_id_msg})
                        else:
                            send_message(bot_token, chat_id_msg,
                                         "❌ El intervalo debe ser mayor a 0")
                    except ValueError:
                        send_message(bot_token, chat_id_msg,
                                     "❌ Formato: /interval <minutos> (ej: /interval 10)")
                continue

            if text.startswith("/abrir ") or text.startswith("/cerrar "):
                parts = text.split()
                if len(parts) == 2:
                    exchange = parts[1].upper()
                    comando = "abierto" if parts[0] == "/abrir" else "cerrado"
                    actions.append({"type": "toggle", "exchange": exchange,
                                    "state": comando, "chat_id": chat_id_msg})

        return last_id, actions
    except Exception as e:
        print(f"Error checking commands: {e}")
        return offset, []
