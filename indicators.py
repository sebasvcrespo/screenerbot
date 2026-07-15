import logging

logger = logging.getLogger(__name__)


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    if len(gains) < period:
        return None

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None

    trs = []
    for i in range(1, len(closes)):
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i - 1])
        l_pc = abs(lows[i] - closes[i - 1])
        trs.append(max(h_l, h_pc, l_pc))

    if len(trs) < period:
        return None

    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period

    return atr


def calc_adx(highs, lows, closes, period=14):
    if len(closes) < period * 2 + 1:
        return None, None, None

    trs = []
    plus_dm = []
    minus_dm = []

    for i in range(1, len(closes)):
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i - 1])
        l_pc = abs(lows[i] - closes[i - 1])
        trs.append(max(h_l, h_pc, l_pc))

        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]

        if up > down and up > 0:
            plus_dm.append(up)
        else:
            plus_dm.append(0)

        if down > up and down > 0:
            minus_dm.append(down)
        else:
            minus_dm.append(0)

    if len(trs) < period:
        return None, None, None

    smooth_tr = sum(trs[:period])
    smooth_plus = sum(plus_dm[:period])
    smooth_minus = sum(minus_dm[:period])

    dx_values = []

    for i in range(period, len(trs)):
        smooth_tr = smooth_tr - smooth_tr / period + trs[i]
        smooth_plus = smooth_plus - smooth_plus / period + plus_dm[i]
        smooth_minus = smooth_minus - smooth_minus / period + minus_dm[i]

        if smooth_tr == 0:
            di_plus = 0
            di_minus = 0
        else:
            di_plus = (smooth_plus / smooth_tr) * 100
            di_minus = (smooth_minus / smooth_tr) * 100

        di_sum = di_plus + di_minus
        if di_sum == 0:
            dx = 0
        else:
            dx = abs(di_plus - di_minus) / di_sum * 100
        dx_values.append(dx)

    if len(dx_values) < period:
        return None, None, None

    adx = sum(dx_values[:period]) / period
    for i in range(period, len(dx_values)):
        adx = (adx * (period - 1) + dx_values[i]) / period

    if smooth_tr == 0:
        final_di_plus = 0
        final_di_minus = 0
    else:
        final_di_plus = (smooth_plus / smooth_tr) * 100
        final_di_minus = (smooth_minus / smooth_tr) * 100

    return adx, final_di_plus, final_di_minus


def calc_change_24h(candles_1h):
    if len(candles_1h) < 25:
        return None

    price_24h_ago = candles_1h[0]["open"]
    current_price = candles_1h[-1]["close"]

    if price_24h_ago == 0:
        return None

    return (current_price - price_24h_ago) / price_24h_ago * 100


def calc_indicators_from_ohlcv(candles_1h, candles_4h):
    result = {}

    if candles_1h:
        closes_1h = [c["close"] for c in candles_1h]
        highs_1h = [c["high"] for c in candles_1h]
        lows_1h = [c["low"] for c in candles_1h]

        rsi_1h = calc_rsi(closes_1h)
        if rsi_1h is not None:
            result["RSI|60"] = rsi_1h

        atr_1h = calc_atr(highs_1h, lows_1h, closes_1h)
        if atr_1h is not None:
            result["ATR|60"] = atr_1h

        adx_1h, di_plus_1h, di_minus_1h = calc_adx(highs_1h, lows_1h, closes_1h)
        if adx_1h is not None:
            result["ADX|60"] = adx_1h
            result["ADX+DI|60"] = di_plus_1h
            result["ADX-DI|60"] = di_minus_1h

        change_24h = calc_change_24h(candles_1h)
        if change_24h is not None:
            result["change_24h_calc"] = change_24h

        if closes_1h:
            result["close_calc"] = closes_1h[-1]

    if candles_4h:
        closes_4h = [c["close"] for c in candles_4h]
        highs_4h = [c["high"] for c in candles_4h]
        lows_4h = [c["low"] for c in candles_4h]

        rsi_4h = calc_rsi(closes_4h)
        if rsi_4h is not None:
            result["RSI|240"] = rsi_4h

        adx_4h, _, _ = calc_adx(highs_4h, lows_4h, closes_4h)
        if adx_4h is not None:
            result["ADX|240"] = adx_4h

    return result


def calc_1h_indicators(candles_1h):
    result = {}
    if not candles_1h:
        return result

    closes = [c["close"] for c in candles_1h]
    highs = [c["high"] for c in candles_1h]
    lows = [c["low"] for c in candles_1h]

    rsi = calc_rsi(closes)
    if rsi is not None:
        result["RSI|60"] = rsi

    atr = calc_atr(highs, lows, closes)
    if atr is not None:
        result["ATR|60"] = atr

    adx, di_plus, di_minus = calc_adx(highs, lows, closes)
    if adx is not None:
        result["ADX|60"] = adx
        result["ADX+DI|60"] = di_plus
        result["ADX-DI|60"] = di_minus

    change = calc_change_24h(candles_1h)
    if change is not None:
        result["change_24h_calc"] = change

    if closes:
        result["close_calc"] = closes[-1]

    return result


def calc_4h_indicators(candles_4h):
    result = {}
    if not candles_4h:
        return result

    closes = [c["close"] for c in candles_4h]
    highs = [c["high"] for c in candles_4h]
    lows = [c["low"] for c in candles_4h]

    rsi = calc_rsi(closes)
    if rsi is not None:
        result["RSI|240"] = rsi

    adx, _, _ = calc_adx(highs, lows, closes)
    if adx is not None:
        result["ADX|240"] = adx

    return result


def passes_1h_precheck(candles_1h):
    if not candles_1h or len(candles_1h) < 16:
        return False

    closes = [c["close"] for c in candles_1h]
    highs = [c["high"] for c in candles_1h]
    lows = [c["low"] for c in candles_1h]

    rsi = calc_rsi(closes)
    adx, di_plus, di_minus = calc_adx(highs, lows, closes)
    atr = calc_atr(highs, lows, closes)
    close = closes[-1] if closes else 0

    if rsi is None or adx is None or close == 0:
        return False

    rsi_ok = (54 <= rsi <= 64) or (33 <= rsi <= 45)
    adx_ok = 25 <= adx <= 45
    atr_ok = atr is not None and close > 0 and (atr / close * 100) >= 2

    return rsi_ok and adx_ok and atr_ok
