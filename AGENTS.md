# TradingView Screener Agent

Monitoriza screeners de TradingView (Long y Short) y envía alertas a Telegram cuando
aparecen pares que cumplen los parámetros técnicos configurados.

## Estructura del proyecto

```
├── main.py                 # Entry point: orquesta el scan loop, bot commands, HTTP server
├── screener_client.py      # TradingView API client (POST a scanner.tradingview.com)
├── bitget_client.py        # Bitget ticker API (24h change, volume)
├── bitget_ohlcv.py         # Bitget OHLCV candles (1H, batch fetching)
├── indicators.py           # Cálculos: RSI, ATR, ADX/DI, volatilidad (pure Python, sin pandas/numpy)
├── detector.py             # Evalúa si un par pasa los filtros del config
├── telegram_notifier.py    # Bot API: send_alert, check_commands (/abrir, /cerrar, etc.)
├── state_store.py          # Estado persistente: Upstash Redis o state_cache.json
├── config.json             # Filtros de screeners + estados de exchanges
├── requirements.txt        # Solo requests y python-dotenv
└── .github/workflows/      # GitHub Actions: cron cada 5 min
```

## Dependencias

Solo dos librerías externas: `requests` y `python-dotenv`. Todo lo demás es stdlib.
Los indicadores técnicos se calculan con Python puro (no hay pandas, numpy, ni TA-Lib).

## Convenciones

- **Sin frameworks** — todo es módulos Python simples, sin clases complejas
- **Config centralizado** — `config.json` tiene todos los parámetros de filtros
- **Dual backend de estado** — Upstash Redis (producción) o JSON local (desarrollo)
- **Logging** — usa `logging` stdlib, no print statements para debug
- **APIs externas** — TradingView (con headers anti-Cloudflare), Bitget REST, Telegram Bot API
- **Runs on Python 3.10** en GitHub Actions (ubuntu-latest)

## Variables de entorno

| Variable | Descripción |
|---|---|
| `BOT_TOKEN` | Token de tu bot de Telegram |
| `CHAT_ID` | ID del chat donde recibirás las alertas |
| `UPSTASH_REDIS_REST_URL` | URL REST de Upstash (ej: `https://xxxx.upstash.io`) |
| `UPSTASH_REDIS_REST_TOKEN` | Token REST de Upstash |

## Configuración

### config.json

1. `exchanges` → Estados por defecto de cada exchange (`"abierto"` o `"cerrado"`)
2. `screeners.long.filters` → Parámetros del screener Long
3. `screeners.short.filters` → Parámetros del screener Short

## Uso local

```bash
export BOT_TOKEN="tu_token"
export CHAT_ID="tu_chat_id"
export UPSTASH_REDIS_REST_URL="https://xxxx.upstash.io"
export UPSTASH_REDIS_REST_TOKEN="tu_token"
python main.py
```

## Deploy en GitHub Actions (gratis)

Este proyecto corre como **GitHub Actions** cada 5 minutos. No necesita servidor.

### Requisitos

1. **Upstash Redis** (gratis) → [upstash.com](https://upstash.com)
2. **GitHub Secrets** en tu repo:
   - `UPSTASH_REDIS_REST_URL` → URL REST de Upstash
   - `UPSTASH_REDIS_REST_TOKEN` → Token REST de Upstash
   - `BOT_TOKEN` → Token de Telegram
   - `CHAT_ID` → ID del chat

### Control remoto vía Telegram

| Comando | Efecto |
|---|---|
| `/abrir bitget` | Activa alertas de BITGET |
| `/cerrar bitget` | Desactiva alertas de BITGET |
| `/abrir pionex` | Activa alertas de PIONEX |
| `/cerrar pionex` | Desactiva alertas de PIONEX |
| `/pausar` | Pausa el scan completo |
| `/reanudar` | Reanuda el scan |
| `/interval 10` | Cambia intervalo a 10 min |
| `/estado` | Muestra estado actual |

Cuando un exchange está **cerrado**, el agente no envía alertas de pares listados en ese exchange.

## Screeners

### LONG
- Cambio 24h: 0% a 3%
- Vol USD 24h: > $300K
- Cambio volumen 24h: 0% a 50%
- ATR 1H: > 2%
- Volatilidad: 5% a 25%
- ADX 1H: 25 a 45
- ADX 4H: 18 a 28
- RSI 1H: 54 a 64
- RSI 4H: 50 a 58

### SHORT
- Cambio 24h: -3% a 0%
- Vol USD 24h: > $300K
- Cambio volumen 24h: -30% a 50%
- ATR 1H: > 2%
- Volatilidad: 5% a 25%
- ADX 1H: 25 a 35
- ADX 4H: 18 a 28
- RSI 1H: 33 a 45
- RSI 4H: 42 a 50

### Exchanges
- BITGET
- PIONEX
- Solo pares USDT futuros perpetuos (sufijo .P)

## Columnas TradingView API

| Columna TV | Descripción |
|---|---|
| `change` | Cambio 24h % |
| `volume` | Volumen USD 24h |
| `change_volume` | Cambio volumen 24h |
| `ATR\|60` | ATR 1H |
| `Volatility.D` | Volatilidad diaria |
| `ADX\|60` | ADX 1H |
| `ADX\|240` | ADX 4H |
| `RSI\|60` | RSI 1H |
| `RSI\|240` | RSI 4H |

Si alguna columna no devuelve datos, ajustar los nombres en `screener_client.py`.

## Notas para desarrollo

- No hay tests ni linter configurados — verificar cambios ejecutando `python main.py`
- El flujo principal: `screener_client` → `detector.passes_filters()` → `indicators` → `telegram_notifier`
- `state_store.py` maneja el offset de scans para evitar alertas duplicadas
- TradingView puede bloquear requests — `screener_client.py` maneja HTTP 429 con backoff
