#!/usr/bin/env python3
"""
bot.py - Gold & Crypto Telegram Bot (self-contained)
Deploy this single file to PythonAnywhere or any Python host.
"""
from __future__ import annotations
import json, os, re, sys, time, platform, signal
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# ─── Config ────────────────────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_IDS = [c.strip() for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]
INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))
GOLD_MIN = int(os.getenv("GOLD_PRICE_MIN", "0")) or None
GOLD_MAX = int(os.getenv("GOLD_PRICE_MAX", "0")) or None

# ─── Data classes ──────────────────────────────────────────────────

@dataclass
class GoldPrice:
    name: str
    price_toman: int
    change_value: int
    change_percent: float
    timestamp: str

@dataclass
class AssetPrice:
    name: str
    symbol: str
    ticker: str
    market: str
    price: float
    change: float
    change_percent: float
    high: float
    low: float
    volume: float
    timestamp: str
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    recommendation: Optional[str] = None

# ─── Proxy helper ──────────────────────────────────────────────────

def _get_windows_proxy():
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return None
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except Exception:
        return None
    if not server:
        return None
    proxies = {}
    for part in str(server).split(";"):
        if "=" not in part:
            continue
        scheme, addr = part.split("=", 1)
        scheme = scheme.strip().lower()
        addr = addr.strip()
        if scheme in ("http", "https") and not addr.startswith("http://") and not addr.startswith("https://"):
            proxies[scheme] = f"http://{addr}"
        elif scheme == "socks":
            proxies[scheme] = f"socks5://{addr}"
    return proxies or None

PROXIES = _get_windows_proxy()

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def _request_with_fallback(method: str, url: str, **kwargs):
    try:
        return requests.request(method, url, **kwargs)
    except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError):
        kwargs.pop("proxies", None)
        kwargs["proxies"] = {"http": None, "https": None}
        return requests.request(method, url, **kwargs)

# ─── Headers ───────────────────────────────────────────────────────

def _get_headers() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
    }

# ─── Market definitions ────────────────────────────────────────────

MARKET_CRYPTO = "crypto"
MARKET_FOREX = "forex"
MARKET_COMMODITY = "commodity"
MARKET_STOCK = "america"
MARKET_INDEX = "index"

MARKET_NAMES = {
    MARKET_CRYPTO: "🪙 ارز دیجیتال",
    MARKET_FOREX: "💱 فارکس",
    MARKET_COMMODITY: "🛢️ کالاها",
    MARKET_STOCK: "📈 سهام آمریکا",
    MARKET_INDEX: "📊 شاخص‌ها",
}

ASSETS: List[Tuple[str, str, str, str]] = [
    ("بیت‌کوین", "BINANCE:BTCUSDT", "BTC", MARKET_CRYPTO),
    ("اتریوم", "BINANCE:ETHUSDT", "ETH", MARKET_CRYPTO),
    ("ریپل", "BINANCE:XRPUSDT", "XRP", MARKET_CRYPTO),
    ("بایننس کوین", "BINANCE:BNBUSDT", "BNB", MARKET_CRYPTO),
    ("سولانا", "BINANCE:SOLUSDT", "SOL", MARKET_CRYPTO),
    ("دوج کوین", "BINANCE:DOGEUSDT", "DOGE", MARKET_CRYPTO),
    ("کاردانو", "BINANCE:ADAUSDT", "ADA", MARKET_CRYPTO),
    ("پالیگان", "BINANCE:MATICUSDT", "MATIC", MARKET_CRYPTO),
    ("پولکادات", "BINANCE:DOTUSDT", "DOT", MARKET_CRYPTO),
    ("لایت کوین", "BINANCE:LTCUSDT", "LTC", MARKET_CRYPTO),
    ("ترون", "BINANCE:TRXUSDT", "TRX", MARKET_CRYPTO),
    ("آوالانچ", "BINANCE:AVAXUSDT", "AVAX", MARKET_CRYPTO),
    ("چین لینک", "BINANCE:LINKUSDT", "LINK", MARKET_CRYPTO),
    ("یونی سواپ", "BINANCE:UNIUSDT", "UNI", MARKET_CRYPTO),
    ("اتریوم کلاسیک", "BINANCE:ETCUSDT", "ETC", MARKET_CRYPTO),
    ("استلار", "BINANCE:XLMUSDT", "XLM", MARKET_CRYPTO),
    ("فایل کوین", "BINANCE:FILUSDT", "FIL", MARKET_CRYPTO),
    ("نیر پروتکل", "BINANCE:NEARUSDT", "NEAR", MARKET_CRYPTO),
    ("آربیتروم", "BINANCE:ARBUSDT", "ARB", MARKET_CRYPTO),
    ("اپتیمیزم", "BINANCE:OPUSDT", "OP", MARKET_CRYPTO),
    ("شیبا اینو", "BINANCE:SHIBUSDT", "SHIB", MARKET_CRYPTO),
    ("تتر", "BINANCE:USDTUSDT", "USDT", MARKET_CRYPTO),
    ("دای", "BINANCE:DAIUSDT", "DAI", MARKET_CRYPTO),
    ("میکر", "BINANCE:MKRUSDT", "MKR", MARKET_CRYPTO),
    ("اتم", "BINANCE:ATOMUSDT", "ATOM", MARKET_CRYPTO),
    ("الگوراند", "BINANCE:ALGOUSDT", "ALGO", MARKET_CRYPTO),
    ("وی چین", "BINANCE:VETUSDT", "VET", MARKET_CRYPTO),
    ("تتا", "BINANCE:THETAUSDT", "THETA", MARKET_CRYPTO),
    ("فانتوم", "BINANCE:FTMUSDT", "FTM", MARKET_CRYPTO),
    ("سندباکس", "BINANCE:SANDUSDT", "SAND", MARKET_CRYPTO),
    ("دسنترالند", "BINANCE:MANAUSDT", "MANA", MARKET_CRYPTO),
    ("اکسی اینفینیتی", "BINANCE:AXSUSDT", "AXS", MARKET_CRYPTO),
    ("گالا", "BINANCE:GALAUSDT", "GALA", MARKET_CRYPTO),
    ("ایاس", "BINANCE:EOSUSDT", "EOS", MARKET_CRYPTO),
    ("ایکش‌اینفینیتی", "BINANCE:ICPUSDT", "ICP", MARKET_CRYPTO),
    ("هدرا", "BINANCE:HBARUSDT", "HBAR", MARKET_CRYPTO),
    ("هارمونی", "BINANCE:ONEUSDT", "ONE", MARKET_CRYPTO),
    ("کازماس", "BINANCE:KSMUSDT", "KSM", MARKET_CRYPTO),
    ("فلو", "BINANCE:FLOWUSDT", "FLOW", MARKET_CRYPTO),
    ("ایگل", "BINANCE:EGLDUSDT", "EGLD", MARKET_CRYPTO),
    ("تزوس", "BINANCE:XTZUSDT", "XTZ", MARKET_CRYPTO),
    ("یورو/دلار", "FX:EURUSD", "EUR/USD", MARKET_FOREX),
    ("پوند/دلار", "FX:GBPUSD", "GBP/USD", MARKET_FOREX),
    ("دلار/ین", "FX:USDJPY", "USD/JPY", MARKET_FOREX),
    ("دلار/فرانک", "FX:USDCHF", "USD/CHF", MARKET_FOREX),
    ("دلار/دلار کانادا", "FX:USDCAD", "USD/CAD", MARKET_FOREX),
    ("دلار/دلار استرالیا", "FX:AUDUSD", "AUD/USD", MARKET_FOREX),
    ("طلای جهانی", "OANDA:XAUUSD", "XAU/USD", MARKET_COMMODITY),
    ("نقره جهانی", "OANDA:XAGUSD", "XAG/USD", MARKET_COMMODITY),
    ("نفت خام WTI", "NYMEX:CL1!", "WTI", MARKET_COMMODITY),
    ("گاز طبیعی", "NYMEX:NG1!", "NAT.GAS", MARKET_COMMODITY),
    ("مس", "COMEX:HG1!", "COPPER", MARKET_COMMODITY),
]

SCANNER_MARKET = {
    MARKET_CRYPTO: "crypto",
    MARKET_FOREX: "forex",
    MARKET_COMMODITY: "cfd",
    MARKET_STOCK: "america",
    MARKET_INDEX: "index",
}

# ─── Exchange rates ────────────────────────────────────────────────
EXCHANGE_RATES = {"USD_IRR": 59700, "USD_TRY": 32.5, "EUR_USD": 1.08, "GBP_USD": 1.27}

# ─── Parsing helpers ───────────────────────────────────────────────

def parse_persian_number(text: str) -> int:
    if not text:
        return 0
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    english_digits = "0123456789"
    translation = str.maketrans(persian_digits, english_digits)
    cleaned = text.translate(translation).replace(",", "").replace(" ", "").strip()
    cleaned = re.sub(r"[^\d]", "", cleaned)
    return int(cleaned) if cleaned else 0

def parse_persian_float(text: str) -> float:
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

# ─── Fetch functions ───────────────────────────────────────────────

def fetch_prices(tickers: List[str]) -> List[Optional[AssetPrice]]:
    if not tickers:
        return []
    market_groups: Dict[str, List[str]] = {}
    for t in tickers:
        m = MARKET_CRYPTO
        if ":" in t:
            prefix = t.split(":")[0].upper()
            if prefix in ("FX", "OANDA"):
                m = MARKET_FOREX
            elif prefix in ("NASDAQ", "NYSE", "AMEX"):
                m = MARKET_STOCK
            elif prefix in ("SP", "TVC", "CRYPTOCAP", "TSE"):
                m = MARKET_INDEX
            elif prefix in ("NYMEX", "COMEX", "CBOT", "NYBOT", "ICE"):
                m = MARKET_COMMODITY
        market_groups.setdefault(m, []).append(t)

    columns = ["name", "close", "change", "change_abs", "high", "low", "volume",
               "RSI", "MACD.macd", "MACD.signal", "SMA20", "SMA50", "SMA200",
               "BB.upper", "BB.lower", "Recommend.All"]

    all_results: Dict[str, Optional[AssetPrice]] = {}
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for market, m_tickers in market_groups.items():
        endpoint = f"https://scanner.tradingview.com/{SCANNER_MARKET.get(market, market)}/scan"
        payload = {"symbols": {"tickers": m_tickers, "query": {"types": []}}, "columns": columns}
        try:
            response = _request_with_fallback("POST", endpoint, json=payload, headers=_get_headers(), timeout=15, verify=False)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            print(f"[bot] Network error for {market}: {exc}")
            for t in m_tickers:
                all_results[t] = None
            continue

        for item in data.get("data", []):
            try:
                d = item["d"]
                ticker = item["s"]
                display_name = ticker
                symbol = ticker.split(":")[-1]
                for name, t, sym, _ in ASSETS:
                    if t == ticker:
                        display_name = name
                        symbol = sym
                        break
                rec_val = d[15] if len(d) > 15 and d[15] is not None else None
                rec_str = None
                if rec_val is not None:
                    if rec_val >= 0.8: rec_str = "STRONG_BUY"
                    elif rec_val >= 0.3: rec_str = "BUY"
                    elif rec_val <= -0.8: rec_str = "STRONG_SELL"
                    elif rec_val <= -0.3: rec_str = "SELL"
                    else: rec_str = "NEUTRAL"

                all_results[ticker] = AssetPrice(
                    name=display_name, symbol=symbol, ticker=ticker, market=market,
                    price=float(d[1]) if d[1] else 0.0,
                    change=float(d[3]) if d[3] else 0.0,
                    change_percent=float(d[2]) if d[2] is not None else 0.0,
                    high=float(d[4]) if d[4] else 0.0,
                    low=float(d[5]) if d[5] else 0.0,
                    volume=float(d[6]) if d[6] else 0.0,
                    timestamp=timestamp,
                    rsi=float(d[7]) if len(d) > 7 and d[7] is not None else None,
                    macd=float(d[8]) if len(d) > 8 and d[8] is not None else None,
                    macd_signal=float(d[9]) if len(d) > 9 and d[9] is not None else None,
                    sma_50=float(d[11]) if len(d) > 11 and d[11] is not None else None,
                    sma_200=float(d[12]) if len(d) > 12 and d[12] is not None else None,
                    recommendation=rec_str,
                )
            except Exception as exc:
                print(f"[bot] Parse error for {item.get('s', '?')}: {exc}")
                all_results[item.get("s", "?")] = None
    return [all_results.get(t) for t in tickers]

def fetch_single_price(ticker: str) -> Optional[AssetPrice]:
    results = fetch_prices([ticker])
    return results[0] if results else None

# ─── Gold price ────────────────────────────────────────────────────

def fetch_gold_price() -> Optional[GoldPrice]:
    URL = "https://www.tgju.org/profile/geram18"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        response = _request_with_fallback("GET", URL, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as exc:
        print(f"[bot] Gold network error: {exc}")
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("[bot] beautifulsoup4 not installed")
        return None
    soup = BeautifulSoup(response.text, "lxml")
    price_el = soup.select_one("span[data-col='info.last_trade.PDrCotVal']")
    if not price_el:
        print("[bot] Could not locate gold price element.")
        return None
    price_rials = parse_persian_number(price_el.get_text(strip=True))
    price_toman = price_rials // 10
    change_el = soup.select_one("span[data-col='info.last_trade.PDrCotValChange']")
    change_rials = parse_persian_number(change_el.get_text(strip=True)) if change_el else 0
    change_toman = change_rials // 10
    percent_el = soup.select_one("span[data-col='info.last_trade.PDrCotValPercent']")
    percent = parse_persian_float(percent_el.get_text(strip=True)) if percent_el else 0.0
    return GoldPrice(name="طلای ۱۸ عیار (هر گرم)", price_toman=price_toman,
                     change_value=change_toman, change_percent=percent,
                     timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

# ─── Formatting ────────────────────────────────────────────────────

def format_gold(gold: GoldPrice) -> str:
    direction = "🔺" if gold.change_value > 0 else ("🔻" if gold.change_value < 0 else "➖")
    sign = "+" if gold.change_value > 0 else ""
    return (
        "🥇 *قیمت لحظه‌ای طلای ۱۸ عیار*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 *قیمت:* `{gold.price_toman:,}` تومان\n"
        f"{direction} *تغییر:* `{sign}{gold.change_value:,}` تومان ({sign}{gold.change_percent:.2f}٪)\n"
        f"🕒 *زمان:* `{gold.timestamp}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "_منبع: tgju.org_"
    )

# ─── Telegram Bot ─────────────────────────────────────────────────

class TelegramNotifier:
    def __init__(self, token: str, chat_ids: List[str]):
        self.token = token
        self.chat_ids = chat_ids
        self.base = f"https://api.telegram.org/bot{token}"

    def send_message(self, text: str, buttons=None, chat_id: str = None):
        for cid in self.chat_ids:
            payload = {"chat_id": cid, "text": text, "parse_mode": "Markdown"}
            if buttons:
                payload["reply_markup"] = {"inline_keyboard": buttons}
            try:
                _request_with_fallback("POST", f"{self.base}/sendMessage", json=payload, timeout=15)
            except Exception as exc:
                print(f"[bot] Send error: {exc}")

# ─── Main loop ─────────────────────────────────────────────────────

def main():
    if not TOKEN or not CHAT_IDS:
        print("[bot] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_IDS")
        sys.exit(1)

    notifier = TelegramNotifier(TOKEN, CHAT_IDS)
    print(f"[bot] Started. Interval={INTERVAL}s | Chats={CHAT_IDS}")

    def handle_signal(signum, frame):
        print("\n[bot] Shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    last_price = None

    while True:
        try:
            gold = fetch_gold_price()
            if gold:
                if GOLD_MIN and gold.price_toman < GOLD_MIN:
                    notifier.send_message(f"🚨 *هشدار:* قیمت طلا زیر {GOLD_MIN:,} تومان!\n\n" + format_gold(gold))
                elif GOLD_MAX and gold.price_toman > GOLD_MAX:
                    notifier.send_message(f"🚨 *هشدار:* قیمت طلا بالای {GOLD_MAX:,} تومان!\n\n" + format_gold(gold))
                elif last_price != gold.price_toman:
                    notifier.send_message(format_gold(gold))
                    last_price = gold.price_toman
            else:
                print("[bot] Could not fetch gold price, retrying...")
        except Exception as exc:
            print(f"[bot] Loop error: {exc}")

        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
