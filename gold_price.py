"""
gold_price.py
Module for fetching live gold prices from tgju.org.
Uses the system HTTP/SOCKS proxy (e.g. a local فیلترشکن) automatically.
"""
from __future__ import annotations

import re
from typing import Optional, Dict

import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass

URL = "https://www.tgju.org/profile/geram18"


def _get_windows_proxy() -> Optional[Dict[str, str]]:
    """
    Read proxy settings from the Windows registry.
    Returns a dict suitable for requests' `proxies` argument, or None.

    The Windows registry format is:
        ProxyServer = "http=127.0.0.1:8080;https=127.0.0.1:8080;socks=127.0.0.1:1080"
    We normalise this to use the `http://` scheme so urllib3 doesn't try to
    establish a TLS connection to the proxy itself (which would fail with
    "WRONG_VERSION_NUMBER" on plain-HTTP proxies such as فیلترشکن).
    """
    try:
        import winreg
    except ImportError:
        return None

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return None
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except (OSError, FileNotFoundError):
        return None

    if not server:
        return None

    proxies: dict[str, str] = {}
    for part in str(server).split(";"):
        if "=" not in part:
            continue
        scheme, addr = part.split("=", 1)
        scheme = scheme.strip().lower()
        addr = addr.strip()
        if scheme in ("http", "https") and not addr.startswith("http://") and not addr.startswith("https://"):
            # Force http:// to prevent urllib3 trying TLS to the proxy.
            proxies[scheme] = f"http://{addr}"
        elif scheme == "socks":
            proxies[scheme] = f"socks5://{addr}"
    return proxies or None


# Resolve proxy once at import time.
PROXIES = _get_windows_proxy()


def _request_with_fallback(method: str, url: str, **kwargs):
    """Make an HTTP request, retrying without proxy on proxy/connection errors."""
    try:
        return requests.request(method, url, **kwargs)
    except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError):
        kwargs.pop("proxies", None)
        kwargs["proxies"] = {"http": None, "https": None}
        return requests.request(method, url, **kwargs)


@dataclass
class GoldPrice:
    """Gold price data container."""
    name: str
    price_toman: int
    change_value: int
    change_percent: float
    timestamp: str


def parse_persian_number(text: str) -> int:
    """Convert Persian digits to int (e.g. '۱۲٬۳۴۵٬۶۷۸' -> 12345678)."""
    if not text:
        return 0
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    english_digits = "0123456789"
    translation = str.maketrans(persian_digits, english_digits)
    cleaned = text.translate(translation).replace(",", "").replace(" ", "").strip()
    # Remove any non-numeric characters
    cleaned = re.sub(r"[^\d]", "", cleaned)
    return int(cleaned) if cleaned else 0


def parse_persian_float(text: str) -> float:
    """Convert Persian percentage to float (e.g. '۲٫۱۵٪' -> 2.15)."""
    if not text:
        return 0.0
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    english_digits = "0123456789"
    translation = str.maketrans(persian_digits, english_digits)
    cleaned = text.translate(translation).replace(",", ".").replace("٪", "").strip()
    cleaned = re.sub(r"[^\d.\-]", "", cleaned)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def fetch_gold_price() -> Optional[GoldPrice]:
    """
    Fetch the latest 18k gold price (per gram, in Toman) from tgju.org.
    Also tries TradingView for 24h change data.

    Returns:
        GoldPrice dataclass on success, None on failure.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "fa,en;q=0.9",
    }

    try:
        response = _request_with_fallback(
            "GET",
            URL,
            headers=headers,
            timeout=15,
            proxies=PROXIES,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[gold_price] Network error: {exc}")
        return None

    soup = BeautifulSoup(response.text, "lxml")

    # 1) Main price
    price_el = soup.select_one("span[data-col='info.last_trade.PDrCotVal']")
    if not price_el:
        print("[gold_price] Could not locate price element on page.")
        return None
    price_rials = parse_persian_number(price_el.get_text(strip=True))
    price_toman = price_rials // 10

    # 2) Change value from tgju (last trade change)
    change_el = soup.select_one("span[data-col='info.last_trade.PDrCotValChange']")
    change_rials = parse_persian_number(change_el.get_text(strip=True)) if change_el else 0
    change_toman = change_rials // 10

    # 3) Change percent from tgju (last trade change)
    percent_el = soup.select_one("span[data-col='info.last_trade.PDrCotValPercent']")
    percent = parse_persian_float(percent_el.get_text(strip=True)) if percent_el else 0.0

    # 4) Try TradingView for 24h change if tgju doesn't have it
    if change_toman == 0 and percent == 0.0:
        try:
            from crypto_price import fetch_single_price, EXCHANGE_RATES
            tv_gold = fetch_single_price("OANDA:XAUUSD")
            if tv_gold:
                # Convert USD change to Toman (approximate)
                usd_change = tv_gold.change
                usd_price = tv_gold.price
                if usd_price > 0:
                    # Approximate Toman price from USD price using current rate
                    rate = EXCHANGE_RATES.get("USD_IRR", 59700)
                    change_toman = int(usd_change * rate / 10)
                    percent = tv_gold.change_percent
        except Exception as exc:
            print(f"[gold_price] TradingView fallback error: {exc}")

    # 5) Timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return GoldPrice(
        name="طلای ۱۸ عیار (هر گرم)",
        price_toman=price_toman,
        change_value=change_toman,
        change_percent=percent,
        timestamp=timestamp,
    )


def format_message(gold: GoldPrice) -> str:
    """Format a GoldPrice as a pretty Telegram message."""
    direction = "🔺" if gold.change_value > 0 else ("🔻" if gold.change_value < 0 else "➖")
    sign = "+" if gold.change_value > 0 else ""
    return (
        "🥇 *قیمت لحظه‌ای طلای ۱۸ عیار*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 *قیمت:* `{gold.price_toman:,}` تومان\n"
        f"{direction} *تغییر:* `{sign}{gold.change_value:,}` تومان "
        f"({sign}{gold.change_percent:.2f}٪)\n"
        f"🕒 *زمان:* `{gold.timestamp}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "_منبع: tgju.org_"
    )


if __name__ == "__main__":
    data = fetch_gold_price()
    if data:
        print(format_message(data))
    else:
        print("Failed to fetch gold price.")
