"""
main_features.py
New feature modules for the Telegram bot (Advanced TA, Compare, Gold Range, Health).
"""
from __future__ import annotations

import datetime
import platform
from typing import List, Optional, Tuple

from crypto_price import (
    fetch_single_price,
    format_price_message,
    get_chart_url,
    MARKET_NAMES,
)
from gold_price import fetch_gold_price, format_message as format_gold
from telegram_bot import TelegramNotifier

# ─── Advanced TA ──────────────────────────────────────────────────────

TOP_TA_ASSETS = [
    ("بیت‌کوین", "BINANCE:BTCUSDT", "BTC"),
    ("اتریوم", "BINANCE:ETHUSDT", "ETH"),
    ("ریپل", "BINANCE:XRPUSDT", "XRP"),
    ("سولانا", "BINANCE:SOLUSDT", "SOL"),
    ("دوج کوین", "BINANCE:DOGEUSDT", "DOGE"),
    ("کاردانو", "BINANCE:ADAUSDT", "ADA"),
]