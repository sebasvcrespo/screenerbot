import logging

logger = logging.getLogger(__name__)

TV_COLUMN_MAP = {
    "change_24h": "change",
    "volume_usd": "volume",
    "volume_change_24h": "change_volume",
    "volatility": "Volatility.D",
    "adx_1h": "ADX|60",
    "adx_4h": "ADX|240",
    "rsi_1h": "RSI|60",
    "rsi_4h": "RSI|240",
}

_warned_filters = set()


def _get_filter_value(row, filter_name):
    if filter_name == "atr_1h_pct":
        atr = row.get("ATR|60")
        close = row.get("close")
        if atr is not None and close and close != 0:
            return atr / close * 100
        return None

    col = TV_COLUMN_MAP.get(filter_name)
    if col is None:
        if filter_name not in _warned_filters:
            logger.warning("Unknown filter: %s", filter_name)
            _warned_filters.add(filter_name)
        return None
    return row.get(col)


def passes_filters(row, filters):
    for filter_name, limits in filters.items():
        value = _get_filter_value(row, filter_name)
        if value is None:
            if filter_name not in _warned_filters:
                logger.warning("Filter '%s': no data available (column None), skipping", filter_name)
                _warned_filters.add(filter_name)
            continue

        min_val = limits.get("min")
        max_val = limits.get("max")

        if min_val is not None and value < min_val:
            return False
        if max_val is not None and value > max_val:
            return False

    return True
