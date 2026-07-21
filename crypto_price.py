"""
crypto_price.py
Module for fetching live prices from TradingView.
Supports multiple markets: Crypto, Forex, Commodities, Stocks, Indices.
Also provides technical analysis (RSI, MACD, SMA) and chart URLs.
"""
from __future__ import annotations
import html
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import requests
import urllib3
from telegram_bot import escape_markdown
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
TV_SCANNER = "https://scanner.tradingview.com/{market}/scan"
TV_CHART = "https://chart.tradingview.com/{market}/"
TV_SYMBOL_INFO = "https://symbol-info.tradingview.com/{market}/"

# ─── Market definitions ──────────────────────────────────────────────
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

# ─── Asset definitions ───────────────────────────────────────────────
# Format: (display_name, ticker, symbol, market)

ASSETS: List[Tuple[str, str, str, str]] = [
    # ── Crypto (Binance) ──
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

    # ── Forex ──
    ("یورو/دلار", "FX:EURUSD", "EUR/USD", MARKET_FOREX),
    ("پوند/دلار", "FX:GBPUSD", "GBP/USD", MARKET_FOREX),
    ("دلار/ین", "FX:USDJPY", "USD/JPY", MARKET_FOREX),
    ("دلار/فرانک", "FX:USDCHF", "USD/CHF", MARKET_FOREX),
    ("دلار/دلار کانادا", "FX:USDCAD", "USD/CAD", MARKET_FOREX),
    ("دلار/دلار استرالیا", "FX:AUDUSD", "AUD/USD", MARKET_FOREX),
    ("دلار/لیر ترکیه", "FX:USDTRY", "USD/TRY", MARKET_FOREX),
    ("یورو/پوند", "FX:EURGBP", "EUR/GBP", MARKET_FOREX),
    ("دلار/روپیه هند", "FX:USDINR", "USD/INR", MARKET_FOREX),
    ("دلار/یوآن چین", "FX:USDCNH", "USD/CNH", MARKET_FOREX),

    # ── Commodities ──
    ("طلای جهانی (XAU/USD)", "OANDA:XAUUSD", "XAU/USD", MARKET_COMMODITY),
    ("نقره جهانی (XAG/USD)", "OANDA:XAGUSD", "XAG/USD", MARKET_COMMODITY),
    ("نفت خام WTI", "NYMEX:CL1!", "WTI", MARKET_COMMODITY),
    ("نفت برنت", "NYMEX:BN1!", "BRENT", MARKET_COMMODITY),
    ("گاز طبیعی", "NYMEX:NG1!", "NAT.GAS", MARKET_COMMODITY),
    ("مس", "COMEX:HG1!", "COPPER", MARKET_COMMODITY),
    ("پلاتین", "NYMEX:PL1!", "PLATINUM", MARKET_COMMODITY),
    ("پالادیوم", "NYMEX:PA1!", "PALLADIUM", MARKET_COMMODITY),
    ("ذرت", "CBOT:ZC1!", "CORN", MARKET_COMMODITY),
    ("گندم", "CBOT:ZW1!", "WHEAT", MARKET_COMMODITY),
    ("قهوه", "NYBOT:KC1!", "COFFEE", MARKET_COMMODITY),
    ("شکر", "NYBOT:SB1!", "SUGAR", MARKET_COMMODITY),

    # ── US Stocks ──
    ("اپل", "NASDAQ:AAPL", "AAPL", MARKET_STOCK),
    ("مایکروسافت", "NASDAQ:MSFT", "MSFT", MARKET_STOCK),
    ("گوگل", "NASDAQ:GOOGL", "GOOGL", MARKET_STOCK),
    ("آمازون", "NASDAQ:AMZN", "AMZN", MARKET_STOCK),
    ("متا (فیسبوک)", "NASDAQ:META", "META", MARKET_STOCK),
    ("تسلا", "NASDAQ:TSLA", "TSLA", MARKET_STOCK),
    ("انویدیا", "NASDAQ:NVDA", "NVDA", MARKET_STOCK),
    ("جی‌پی مورگان", "NYSE:JPM", "JPM", MARKET_STOCK),
    ("برکشایر هاتاوی", "NYSE:BRK.B", "BRK.B", MARKET_STOCK),
    ("ویزا", "NYSE:V", "V", MARKET_STOCK),
    ("جانسون اند جانسون", "NYSE:JNJ", "JNJ", MARKET_STOCK),
    ("وال‌مارت", "NYSE:WMT", "WMT", MARKET_STOCK),
    ("پروکتر اند گمبل", "NYSE:PG", "PG", MARKET_STOCK),
    ("نتفلیکس", "NASDAQ:NFLX", "NFLX", MARKET_STOCK),
    ("ادوبی", "NASDAQ:ADBE", "ADBE", MARKET_STOCK),
    ("پایپال", "NASDAQ:PYPL", "PYPL", MARKET_STOCK),
    ("اوبر", "NYSE:UBER", "UBER", MARKET_STOCK),
    ("اسپوتیفای", "NYSE:SPOT", "SPOT", MARKET_STOCK),
    ("اسنپ", "NYSE:SNAP", "SNAP", MARKET_STOCK),
    ("کوین‌بیس", "NASDAQ:COIN", "COIN", MARKET_STOCK),
    ("مایکرواستراتژی", "NASDAQ:MSTR", "MSTR", MARKET_STOCK),
    ("ریپل لبز", "NASDAQ:RIOT", "RIOT", MARKET_STOCK),
    ("ماراتون دیجیتال", "NASDAQ:MARA", "MARA", MARKET_STOCK),
    ("بلاک (اسکوئر)", "NYSE:SQ", "SQ", MARKET_STOCK),

    # ── Indices ──
    ("S&P 500", "SP:SPX", "S&P 500", MARKET_INDEX),
    ("نزدک ۱۰۰", "NASDAQ:NDX", "NASDAQ", MARKET_INDEX),
    ("داوجونز", "DJ:DJI", "DOW JONES", MARKET_INDEX),
    ("راسل ۲۰۰۰", "AMEX:IWM", "RUSSELL", MARKET_INDEX),
    ("شاخص دلار", "TVC:DXY", "DXY", MARKET_INDEX),
    ("بیت‌کوین دامیننس", "CRYPTOCAP:BTC.D", "BTC.D", MARKET_INDEX),
    ("شاخص ترس و طمع", "CRYPTOCAP:FEAR", "FEAR", MARKET_INDEX),
]


# ─── Data classes ────────────────────────────────────────────────────

@dataclass
class AssetPrice:
    """Generic asset price data container."""
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
    # Technical indicators
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    recommendation: Optional[str] = None


@dataclass
class TechnicalAnalysis:
    """Technical analysis data."""
    rsi: float
    macd: float
    macd_signal: float
    macd_histogram: float
    sma_20: float
    sma_50: float
    sma_200: float
    bollinger_upper: float
    bollinger_lower: float
    recommendation: str  # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL


# ─── Proxy helper ────────────────────────────────────────────────────

def _get_windows_proxy() -> Optional[Dict[str, str]]:
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
    proxies: Dict[str, str] = {}
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


def _request_with_fallback(method: str, url: str, **kwargs):
    """Make an HTTP request, retrying without proxy on proxy/connection errors."""
    try:
        return requests.request(method, url, **kwargs)
    except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError):
        kwargs.pop("proxies", None)
        kwargs["proxies"] = {"http": None, "https": None}
        return requests.request(method, url, **kwargs)


# ─── Headers ─────────────────────────────────────────────────────────

def _get_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
    }


# ─── Market helpers ──────────────────────────────────────────────────

def _get_market_for_ticker(ticker: str) -> str:
    """Determine the market type from a ticker."""
    for _, t, _, market in ASSETS:
        if t == ticker:
            return market
    # Fallback: guess from ticker format
    if ":" in ticker:
        prefix = ticker.split(":")[0].upper()
        if prefix in ("BINANCE", "COINBASE", "BYBIT", "OKX", "KRAKEN", "BITFINEX", "HUOBI"):
            return MARKET_CRYPTO
        elif prefix in ("FX", "OANDA"):
            return MARKET_FOREX
        elif prefix in ("NASDAQ", "NYSE", "AMEX"):
            return MARKET_STOCK
        elif prefix in ("SP", "TVC", "CRYPTOCAP", "TSE"):
            return MARKET_INDEX
        elif prefix in ("NYMEX", "COMEX", "CBOT", "NYBOT", "ICE"):
            return MARKET_COMMODITY
    return MARKET_CRYPTO


# TradingView scanner slugs (the "commodity" slug returns 404; use "cfd")
SCANNER_MARKET = {
    MARKET_CRYPTO: "crypto",
    MARKET_FOREX: "forex",
    MARKET_COMMODITY: "cfd",
    MARKET_STOCK: "america",
    MARKET_INDEX: "index",
}

# Some indices live in a different scanner market than the generic "index".
# We try these slugs (in order) for each index ticker until one returns data.
INDEX_SCANNER_SLUGS = ["america", "global", "cfd", "forex", "crypto", "economy"]


def _get_scanner_endpoint(market: str) -> str:
    """Get the scanner endpoint for a market type."""
    slug = SCANNER_MARKET.get(market, market)
    return TV_SCANNER.format(market=slug)


def _index_scanner_endpoints() -> List[str]:
    """Return candidate scanner endpoints to try for index tickers."""
    return [TV_SCANNER.format(market=s) for s in INDEX_SCANNER_SLUGS]


# ─── Fetch functions ─────────────────────────────────────────────────

def _scanner_parse(data: dict, m_tickers: List[str], market: str,
                   timestamp: str) -> Dict[str, Optional[AssetPrice]]:
    """Parse a TradingView scanner response into AssetPrice results."""
    results: Dict[str, Optional[AssetPrice]] = {}
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
                if rec_val >= 0.8:
                    rec_str = "STRONG_BUY"
                elif rec_val >= 0.3:
                    rec_str = "BUY"
                elif rec_val <= -0.8:
                    rec_str = "STRONG_SELL"
                elif rec_val <= -0.3:
                    rec_str = "SELL"
                else:
                    rec_str = "NEUTRAL"

            results[ticker] = AssetPrice(
                name=display_name,
                symbol=symbol,
                ticker=ticker,
                market=market,
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
        except (IndexError, TypeError, ValueError) as exc:
            print(f"[crypto_price] Parse error for {item.get('s', '?')}: {exc}")
            results[item.get("s", "?")] = None
    return results


def _scan_endpoints_for(market: str) -> List[str]:
    """Return the list of scanner endpoints to try for a market.

    Indices are spread across several TradingView scanner markets, so we
    try a list of candidates. Other markets use a single known endpoint.
    """
    if market == MARKET_INDEX:
        return _index_scanner_endpoints()
    return [_get_scanner_endpoint(market)]


def fetch_prices(tickers: List[str]) -> List[Optional[AssetPrice]]:
    """
    Fetch live prices for a list of TradingView tickers.
    Automatically detects the market for each ticker.
    """
    if not tickers:
        return []

    # Tickers that have a dedicated (non-scanner) source.
    special_sources = {
        "CRYPTOCAP:FEAR": fetch_fear_greed_index,
    }

    # Group tickers by market
    market_groups: Dict[str, List[str]] = {}
    for t in tickers:
        if t in special_sources:
            continue
        m = _get_market_for_ticker(t)
        if m not in market_groups:
            market_groups[m] = []
        market_groups[m].append(t)

    all_results: Dict[str, Optional[AssetPrice]] = {}
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Resolve special-source tickers first.
    for t, src in special_sources.items():
        if t in tickers:
            try:
                all_results[t] = src()
            except Exception as exc:
                print(f"[crypto_price] special source error for {t}: {exc}")
                all_results[t] = None

    # Columns to fetch (order MUST match the parsing below)
    columns = [
        "name", "close", "change", "change_abs",
        "high", "low", "volume",
        "RSI", "MACD.macd", "MACD.signal",
        "SMA20", "SMA50", "SMA200",
        "BB.upper", "BB.lower",
        "Recommend.All",
    ]

    for market, m_tickers in market_groups.items():
        endpoints = _scan_endpoints_for(market)

        # Index tickers live in different scanner markets, so each must be
        # queried individually against the candidate endpoint list.
        if market == MARKET_INDEX:
            for t in m_tickers:
                for endpoint in endpoints:
                    payload = {
                        "symbols": {"tickers": [t], "query": {"types": []}},
                        "columns": columns,
                    }
                    try:
                        response = _request_with_fallback(
                            "POST",
                            endpoint,
                            json=payload,
                            headers=_get_headers(),
                            timeout=15,
                            proxies=PROXIES,
                            verify=False,
                        )
                        response.raise_for_status()
                        data = response.json()
                    except Exception as exc:
                        print(f"[crypto_price] Network error for {t} @ {endpoint}: {exc}")
                        continue
                    parsed = _scanner_parse(data, [t], market, timestamp)
                    if parsed.get(t) is not None:
                        all_results[t] = parsed[t]
                        break
                else:
                    all_results[t] = None
            continue

        for endpoint in endpoints:
            payload = {
                "symbols": {"tickers": m_tickers, "query": {"types": []}},
                "columns": columns,
            }

            try:
                response = _request_with_fallback(
                    "POST",
                    endpoint,
                    json=payload,
                    headers=_get_headers(),
                    timeout=15,
                    proxies=PROXIES,
                    verify=False,
                )
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                print(f"[crypto_price] Network error for {market} @ {endpoint}: {exc}")
                continue

            # Only accept this endpoint if it returned data for our tickers.
            parsed = _scanner_parse(data, m_tickers, market, timestamp)
            if any(v is not None for v in parsed.values()):
                all_results.update(parsed)
                break
            else:
                print(f"[crypto_price] No data for {market} @ {endpoint}, trying next.")
        else:
            # All endpoints failed -> mark tickers as unavailable.
            for t in m_tickers:
                all_results[t] = None

    # Return results in the same order as input tickers
    return [all_results.get(t) for t in tickers]


# ─── OHLC (candle) data ─────────────────────────────────────────────

# Map our crypto symbols to CoinGecko coin ids so we can fetch candle data.
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "MATIC": "matic-network",
    "DOT": "polkadot",
    "LTC": "litecoin",
    "TRX": "tron",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ETC": "ethereum-classic",
    "XLM": "stellar",
    "FIL": "filecoin",
    "NEAR": "near",
    "ARB": "arbitrum",
    "OP": "optimism",
    "SHIB": "shiba-inu",
    "USDT": "tether",
    "DAI": "dai",
    "MKR": "maker",
    "ATOM": "cosmos",
    "ALGO": "algorand",
    "VET": "vechain",
    "THETA": "theta-token",
    "FTM": "fantom",
    "SAND": "the-sandbox",
    "MANA": "decentraland",
    "AXS": "axie-infinity",
    "GALA": "gala",
    "EOS": "eos",
    "ICP": "internet-computer",
    "HBAR": "hedera-hashgraph",
    "ONE": "harmony",
    "KSM": "kusama",
    "FLOW": "flow",
    "EGLD": "elrond-erd-2",
    "XTZ": "tezos",
}


@dataclass
class Candle:
    """A single OHLC candle."""
    timestamp: int          # unix seconds
    open: float
    high: float
    low: float
    close: float


def fetch_ohlc(symbol: str, hours: int = 24, interval: str = "1h") -> Optional[List[Candle]]:
    """Fetch recent OHLC candles for a crypto symbol from CoinGecko.

    Args:
        symbol: Our internal symbol, e.g. "BTC".
        hours: Number of hours of history to request (default 24 -> 24 candles).
        interval: Candle interval (CoinGecko supports 1h only for this call).

    Returns:
        List of Candle objects (oldest first), or None on failure.
    """
    coin_id = COINGECKO_IDS.get(symbol.upper())
    if not coin_id:
        return None

    # CoinGecko OHLC endpoint: days=1 gives ~hourly candles for the last 24h.
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": 1}
    try:
        response = _request_with_fallback(
            "GET",
            url,
            params=params,
            headers=_get_headers(),
            timeout=15,
            proxies=PROXIES,
            verify=False,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f"[crypto_price] OHLC fetch error for {symbol}: {exc}")
        return None

    if not data:
        return None

    candles: List[Candle] = []
    seen_hours = set()
    for row in data:
        # CoinGecko format: [timestamp_ms, open, high, low, close]
        ts = int(row[0]) // 1000
        hour_key = ts // 3600  # bucket by hour to drop duplicate candles
        if hour_key in seen_hours:
            continue
        seen_hours.add(hour_key)
        candles.append(
            Candle(
                timestamp=ts,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
            )
        )

    # Keep only the most recent `hours` candles.
    if len(candles) > hours:
        candles = candles[-hours:]
    return candles


BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
MAX_KLINES_PER_REQUEST = 1000


def _to_binance_symbol(ticker: str) -> str:
    if ":" in ticker:
        return ticker.split(":")[-1]
    return ticker


def fetch_binance_ohlc(symbol: str, hours: int = 8760, interval: str = "1h") -> Optional[List[Candle]]:
    """Fetch Binance OHLC candles with pagination.

    Binance limits each request to 1000 candles, so for 1 year (~8760 hours)
    we paginate backwards using endTime. Returns oldest-first list of Candle.
    """
    binance_symbol = _to_binance_symbol(symbol)
    target = hours
    limit_per_request = MAX_KLINES_PER_REQUEST
    raw: List[List] = []

    for _ in range((target // limit_per_request) + 5):
        if len(raw) >= target:
            break
        remaining = target - len(raw)
        fetch_limit = min(limit_per_request, remaining)

        params = {
            "symbol": binance_symbol,
            "interval": interval,
            "limit": fetch_limit,
        }
        if raw:
            oldest_open_time = raw[-1][0]
            params["endTime"] = oldest_open_time - 1

        try:
            response = _request_with_fallback(
                "GET",
                BINANCE_KLINES,
                params=params,
                headers=_get_headers(),
                timeout=20,
                proxies=PROXIES,
                verify=False,
            )
            response.raise_for_status()
            data = response.json()
            if not data:
                break
        except Exception as exc:
            print(f"[crypto_price] Binance klines error for {binance_symbol}: {exc}")
            break

        raw.extend(data)
        if len(data) < fetch_limit:
            break

    if not raw:
        return None

    seen = set()
    candles: List[Candle] = []
    for row in raw:
        ts = int(row[0]) // 1000
        if ts in seen:
            continue
        seen.add(ts)
        candles.append(
            Candle(
                timestamp=ts,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
            )
        )

    candles.sort(key=lambda c: c.timestamp)
    while len(candles) > target:
        candles.pop(0)
    return candles if candles else None


def _ohlc_price_decimals(candles: List[Candle]) -> int:
    """Pick decimal places so tiny coins (e.g. SHIB) stay readable in the table."""
    ref = max(
        max(abs(c.open), abs(c.high), abs(c.low), abs(c.close)) for c in candles
    )
    ref = max(ref, 1e-12)
    if ref < 0.001:
        return 8
    if ref < 1:
        return 6
    if ref < 100:
        return 4
    return 2


def _build_ohlc_pre_table(candles: List[Candle], decimals: int) -> str:
    """Build a box-drawing OHLC table for Telegram <pre> blocks."""

    def fp(value: float) -> str:
        return f"{value:,.{decimals}f}"

    time_w = 11
    price_w = max(
        len(fp(v))
        for c in candles
        for v in (c.open, c.high, c.low, c.close)
    )
    close_w = price_w + 1  # room for ▲/▼

    def cell(text: str, width: int) -> str:
        return text.rjust(width)

    top = (
        f"┌{'─' * time_w}┬{'─' * price_w}┬{'─' * price_w}"
        f"┬{'─' * price_w}┬{'─' * close_w}┐"
    )
    header = (
        f"│{cell('Time', time_w)}│{cell('Open', price_w)}│{cell('High', price_w)}"
        f"│{cell('Low', price_w)}│{cell('Close', close_w)}│"
    )
    mid = (
        f"├{'─' * time_w}┼{'─' * price_w}┼{'─' * price_w}"
        f"┼{'─' * price_w}┼{'─' * close_w}┤"
    )
    bottom = (
        f"└{'─' * time_w}┴{'─' * price_w}┴{'─' * price_w}"
        f"┴{'─' * price_w}┴{'─' * close_w}┘"
    )

    rows = [top, header, mid]
    for candle in candles:
        t = datetime.fromtimestamp(candle.timestamp).strftime("%m/%d %H:%M")
        direction = "▲" if candle.close >= candle.open else "▼"
        rows.append(
            f"│{cell(t, time_w)}"
            f"│{cell(fp(candle.open), price_w)}"
            f"│{cell(fp(candle.high), price_w)}"
            f"│{cell(fp(candle.low), price_w)}"
            f"│{cell(fp(candle.close) + direction, close_w)}│"
        )
    rows.append(bottom)
    return "\n".join(rows)


def format_ohlc_table(name: str, symbol: str, candles: List[Candle]) -> str:
    """Format a 24h OHLC table as an HTML Telegram message."""
    decimals = _ohlc_price_decimals(candles)

    def fp(value: float) -> str:
        return f"{value:,.{decimals}f}"

    first, last = candles[0], candles[-1]
    change = last.close - first.open
    change_pct = (change / first.open * 100) if first.open else 0.0
    period_high = max(c.high for c in candles)
    period_low = min(c.low for c in candles)
    green_count = sum(1 for c in candles if c.close >= c.open)
    red_count = len(candles) - green_count

    arrow = "📈" if change >= 0 else "📉"
    sign = "+" if change >= 0 else ""
    updated = datetime.fromtimestamp(last.timestamp).strftime("%Y-%m-%d %H:%M")

    table = html.escape(_build_ohlc_pre_table(candles, decimals))
    safe_name = html.escape(name)
    safe_symbol = html.escape(symbol)

    return (
        f"<b>📊 جدول OHLC — {safe_name}</b>\n"
        f"<i>{safe_symbol} · کندل ۱س · ۲۴ ساعت · USD</i>\n\n"
        f"<pre>{table}</pre>\n"
        f"<b>{arrow} خلاصه ۲۴ ساعت</b>\n"
        f"▫️ تغییر: <code>{sign}{fp(change)} ({sign}{change_pct:.2f}%)</code>\n"
        f"▫️ سقف: <code>{fp(period_high)}</code>  ·  "
        f"کف: <code>{fp(period_low)}</code>\n"
        f"▫️ باز: <code>{fp(first.open)}</code>  →  "
        f"بسته: <code>{fp(last.close)}</code>\n"
        f"▫️ کندل: 🟢 {green_count}  ·  🔴 {red_count}\n"
        f"🕒 آخرین: <i>{updated}</i>"
    )


def fetch_fear_greed_index() -> Optional[AssetPrice]:
    """Fetch the Crypto Fear & Greed index from alternative.me.

    TradingView's CRYPTOCAP:FEAR ticker is not available via the scanner,
    so we use the free public Fear & Greed API as a fallback source.
    """
    try:
        response = _request_with_fallback(
            "GET",
            "https://api.alternative.me/fng/?limit=1",
            headers=_get_headers(),
            timeout=15,
            proxies=PROXIES,
            verify=False,
        )
        response.raise_for_status()
        data = response.json()
        entry = data.get("data", [{}])[0]
        value = int(entry.get("value", 0))
        classification = entry.get("value_classification", "")
    except Exception as exc:
        print(f"[crypto_price] Fear&Greed fetch error: {exc}")
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return AssetPrice(
        name="شاخص ترس و طمع",
        symbol="FEAR",
        ticker="CRYPTOCAP:FEAR",
        market=MARKET_INDEX,
        price=float(value),
        change=0.0,
        change_percent=0.0,
        high=0.0,
        low=0.0,
        volume=0.0,
        timestamp=timestamp,
        recommendation=classification,
    )


def fetch_single_price(ticker: str) -> Optional[AssetPrice]:
    """Fetch a single asset price."""
    if ticker == "CRYPTOCAP:FEAR":
        return fetch_fear_greed_index()
    results = fetch_prices([ticker])
    return results[0] if results else None


def fetch_assets_by_market(market: str) -> List[Optional[AssetPrice]]:
    """Fetch all assets in a given market."""
    tickers = [t[1] for t in ASSETS if t[3] == market]
    return fetch_prices(tickers)


def get_assets_by_market(market: str) -> List[Tuple[str, str, str, str]]:
    """Get all asset definitions for a market."""
    return [a for a in ASSETS if a[3] == market]


# ─── Chart URL generator ─────────────────────────────────────────────

def get_chart_url(ticker: str, interval: str = "60") -> str:
    """
    Generate a TradingView chart URL for a ticker.

    Args:
        ticker: TradingView ticker (e.g. 'BINANCE:BTCUSDT')
        interval: Chart interval (1, 5, 15, 60, 240, D, W, M)

    Returns:
        URL to the TradingView chart
    """
    return f"https://www.tradingview.com/chart/?symbol={ticker}&interval={interval}"


def get_chart_image_url(ticker: str, interval: str = "60") -> str:
    """
    Generate a chart image URL (for embedding in Telegram).
    Uses TradingView's widget API.
    """
    encoded = ticker.replace(":", "%3A")
    return (
        f"https://charts.tradingview.com/widgetembed/"
        f"?symbol={encoded}"
        f"&interval={interval}"
        f"&hidesidetoolbar=1"
        f"&theme=dark"
        f"&style=1"
        f"&width=600"
        f"&height=400"
        f"&locale=fa_IR"
    )


# ─── Formatting functions ────────────────────────────────────────────

def _format_price(value: float, market: str) -> str:
    """Format a price with appropriate decimal places per market."""
    if market == MARKET_FOREX:
        return f"{value:,.5f}"
    elif market == MARKET_CRYPTO:
        if value >= 100:
            return f"{value:,.2f}"
        elif value >= 1:
            return f"{value:,.4f}"
        elif value >= 0.01:
            return f"{value:,.6f}"
        else:
            return f"{value:,.8f}"
    else:
        return f"{value:,.2f}"


def format_price_message(asset: AssetPrice, include_ta: bool = False) -> str:
    """Format an AssetPrice as a pretty Telegram message."""
    direction = "🟢▲" if asset.change > 0 else ("🔴▼" if asset.change < 0 else "⚪➖")
    sign = "+" if asset.change > 0 else ""
    market_icon = MARKET_NAMES.get(asset.market, "📊")
    price_str = _format_price(asset.price, asset.market)
    change_str = _format_price(asset.change, asset.market)
    high_str = _format_price(asset.high, asset.market)
    low_str = _format_price(asset.low, asset.market)

    msg = (
        f"{market_icon} *{asset.name} ({asset.symbol})*\n"
        "━━━━━━\n"
        f"💰 *قیمت:* `{price_str}`\n"
        f"{direction} *تغییر:* `{sign}{change_str}` "
        f"({sign}{asset.change_percent:.2f}٪)\n"
        f"📈 *بالاترین:* `{high_str}`\n"
        f"📉 *پایین‌ترین:* `{low_str}`\n"
    )
    if asset.market == MARKET_CRYPTO:
        usd_volume = asset.volume * asset.price if asset.price > 0 else 0
        if usd_volume >= 1_000_000:
            volume_display = f"{usd_volume / 1_000_000:,.2f}M"
        elif usd_volume >= 1_000:
            volume_display = f"{usd_volume / 1_000:,.2f}K"
        else:
            volume_display = f"{usd_volume:,.2f}"
        msg += f"📊 *حجم:* `{volume_display}` *({asset.symbol.split(':')[-1]})*\n"
    elif asset.market == MARKET_STOCK:
        msg += f"📊 *حجم:* `{asset.volume:,.0f}` *سهام*\n"
    elif asset.market == MARKET_COMMODITY:
        msg += f"📊 *حجم:* `{asset.volume:,.0f}` *قرارداد*\n"
    elif asset.market == MARKET_INDEX:
        msg += f"📊 *حجم:* `{asset.volume:,.0f}`*\n"
    else:
        msg += f"📊 *حجم:* `{asset.volume:,.0f}` *({asset.symbol.split(':')[-1]})*\n"
    if include_ta and asset.rsi is not None:
        rsi_icon = "🟢" if asset.rsi < 30 else ("🔴" if asset.rsi > 70 else "🟡")
        msg += (
            f"\n📊 *تحلیل تکنیکال*\n"
            f"{rsi_icon} *RSI:* `{asset.rsi:.1f}`\n"
        )
        if asset.macd is not None and asset.macd_signal is not None:
            macd_icon = "🟢" if asset.macd > asset.macd_signal else "🔴"
            msg += f"{macd_icon} *MACD:* `{asset.macd:.2f}` / `{asset.macd_signal:.2f}`\n"
        if asset.sma_50 is not None:
            sma_icon = "🟢" if asset.price > asset.sma_50 else "🔴"
            msg += f"{sma_icon} *SMA50:* `{asset.sma_50:,.2f}`\n"
        if asset.sma_200 is not None:
            sma_icon = "🟢" if asset.price > asset.sma_200 else "🔴"
            msg += f"{sma_icon} *SMA200:* `{asset.sma_200:,.2f}`\n"
        if asset.recommendation:
            rec_icon = {
                "STRONG_BUY": "🟢🟢",
                "BUY": "🟢",
                "NEUTRAL": "🟡",
                "SELL": "🔴",
                "STRONG_SELL": "🔴🔴",
            }.get(asset.recommendation, "⚪")
            msg += f"\n{rec_icon} *سيگنال:* `{escape_markdown(asset.recommendation)}`\n"

    msg += (
        f"\n🕒 *زمان:* `{asset.timestamp}`\n"
        "━━━━━━\n"
        "_منبع: TradingView_"
    )
    return msg

def format_market_list(prices: List[Optional[AssetPrice]], market: str) -> str:
    """Format a list of asset prices as a compact table."""
    market_name = MARKET_NAMES.get(market, "بازار")
    lines = [f"{market_name} *لیست قیمت*\n━━━━━━"]

    for p in prices:
        if p is None:
            continue
        direction = "🟢▲" if p.change_percent > 0 else ("🔴▼" if p.change_percent < 0 else "⚪➖")
        sign = "+" if p.change_percent > 0 else ""
        price_str = _format_price(p.price, market)
        lines.append(
            f"• *{p.symbol}*: `{price_str}` "
            f"{direction} {sign}{p.change_percent:.2f}٪"
        )

    lines.append("━━━━━━\n_منبع: TradingView_")
    return "\n".join(lines)


def format_alert_message(asset: AssetPrice, alert_type: str, threshold: float) -> str:
    """Format an alert message when price crosses a threshold."""
    direction = "📈" if alert_type == "above" else "📉"
    return (
        f"🚨 *هشدار قیمت*\n"
        f"{direction} *{asset.name}* به {threshold:,.2f} رسید!\n\n"
        f"💰 *قیمت فعلی:* `{asset.price:,.2f}`\n"
        f"📊 *تغییر:* `{asset.change_percent:.2f}٪`\n"
        f"🕒 *زمان:* `{asset.timestamp}`"
    )


# ─── Alert system ────────────────────────────────────────────────────

class PriceAlert:
    """Represents a price alert for an asset."""

    def __init__(self, ticker: str, name: str, symbol: str, alert_type: str, threshold: float):
        """
        Args:
            ticker: TradingView ticker (e.g. 'BINANCE:BTCUSDT')
            name: Display name (e.g. 'بیت‌کوین')
            symbol: Short symbol (e.g. 'BTC')
            alert_type: 'above' or 'below'
            threshold: Price threshold
        """
        self.ticker = ticker
        self.name = name
        self.symbol = symbol
        self.alert_type = alert_type  # 'above' or 'below'
        self.threshold = threshold
        self.triggered = False
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def check(self, current_price: float) -> bool:
        """Check if the alert should trigger."""
        if self.alert_type == "above" and current_price >= self.threshold:
            return True
        elif self.alert_type == "below" and current_price <= self.threshold:
            return True
        return False

    def to_dict(self) -> Dict:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "symbol": self.symbol,
            "alert_type": self.alert_type,
            "threshold": self.threshold,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "PriceAlert":
        alert = cls(
            ticker=data["ticker"],
            name=data["name"],
            symbol=data["symbol"],
            alert_type=data["alert_type"],
            threshold=data["threshold"],
        )
        alert.created_at = data.get("created_at", "")
        return alert


class AlertManager:
    """Manages price alerts for multiple assets."""

    def __init__(self, storage_path: str = "alerts.json"):
        self.storage_path = storage_path
        self.alerts: List[PriceAlert] = []
        self._load()

    def add_alert(self, ticker: str, name: str, symbol: str, alert_type: str, threshold: float) -> PriceAlert:
        """Add a new price alert."""
        alert = PriceAlert(ticker, name, symbol, alert_type, threshold)
        self.alerts.append(alert)
        self._save()
        return alert

    def remove_alert(self, index: int) -> Optional[PriceAlert]:
        """Remove an alert by index."""
        if 0 <= index < len(self.alerts):
            alert = self.alerts.pop(index)
            self._save()
            return alert
        return None

    def get_alerts_for_ticker(self, ticker: str) -> List[PriceAlert]:
        """Get all alerts for a specific ticker."""
        return [a for a in self.alerts if a.ticker == ticker]

    def check_alerts(self, ticker: str, current_price: float) -> List[PriceAlert]:
        """Check all alerts for a ticker and return triggered ones."""
        triggered = []
        for alert in self.get_alerts_for_ticker(ticker):
            if alert.check(current_price) and not alert.triggered:
                alert.triggered = True
                triggered.append(alert)
                self._save()
        return triggered

    def list_alerts(self) -> List[PriceAlert]:
        """List all active alerts."""
        return [a for a in self.alerts if not a.triggered]

    def _save(self) -> None:
        """Save alerts to JSON file."""
        try:
            data = [a.to_dict() for a in self.alerts]
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[alerts] Save error: {exc}")

    def _load(self) -> None:
        """Load alerts from JSON file."""
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.alerts = [PriceAlert.from_dict(d) for d in data]
        except (FileNotFoundError, json.JSONDecodeError):
            self.alerts = []


# ─── Currency converter ──────────────────────────────────────────────

# Approximate exchange rates (updated periodically)
EXCHANGE_RATES = {
    "USD_IRR": 137500,  # 1 USD = 137,500 Toman (fallback - free-market rate)
    "USD_TRY": 32.5,    # 1 USD = 32.5 TRY
    "EUR_USD": 1.08,    # 1 EUR = 1.08 USD
    "GBP_USD": 1.27,    # 1 GBP = 1.27 USD
}

# tgju.org page for the free-market USD price (per USD, in Toman)
_TGju_USD_URL = "https://www.tgju.org/profile/price_dollar_rl"

# Free public currency API (jsDelivr CDN mirror) used as a reliable fallback
# for the USD/Toman rate when tgju is unreachable.
_FNG_CURRENCY_API = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"
)


def _fetch_usd_irr_rate() -> Optional[float]:
    """Fetch live free-market USD/Toman rate.

    Tries tgju.org first, then falls back to a free public currency API.
    Returns the price per 1 USD in Toman, or None on failure.
    """
    # 1) Try tgju.org (scrapes the live free-market USD price in Toman)
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        BeautifulSoup = None

    if BeautifulSoup is not None:
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
                _TGju_USD_URL,
                headers=headers,
                timeout=10,
                proxies=PROXIES,
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")
            el = soup.select_one("span[data-col='info.last_trade.PDrCotVal']")
            if el:
                text = el.get_text(strip=True)
                persian_digits = "۰۱۲۳۴۵۶۷۸۹"
                cleaned = text.translate(str.maketrans(persian_digits, "0123456789"))
                cleaned = re.sub(r"[^\d]", "", cleaned)
                if cleaned:
                    rials = int(cleaned)
                    rate = rials / 10  # to Toman
                    if rate > 0:
                        return rate
        except Exception as exc:
            print(f"[crypto_price] USD rate (tgju) error: {exc}")

    # 2) Fallback: free public currency API (1 USD in IRR -> Toman)
    try:
        response = _request_with_fallback(
            "GET",
            _FNG_CURRENCY_API,
            headers=_get_headers(),
            timeout=12,
            proxies=PROXIES,
            verify=False,
        )
        response.raise_for_status()
        data = response.json()
        irr = data.get("usd", {}).get("irr")
        if irr:
            rate = float(irr) / 10.0  # IRR -> Toman
            if rate > 0:
                return rate
    except Exception as exc:
        print(f"[crypto_price] USD rate (api) error: {exc}")

    return None


# Update USD_IRR rate at import time if possible
_live_rate = _fetch_usd_irr_rate()
if _live_rate and _live_rate > 0:
    EXCHANGE_RATES["USD_IRR"] = _live_rate
    print(f"[crypto_price] Live USD/Toman rate loaded: 1 USD = {_live_rate:,.0f} Toman")
else:
    print(f"[crypto_price] Using fallback USD/Toman rate: 1 USD = {EXCHANGE_RATES['USD_IRR']:,} Toman")

# Gold price in Toman (from tgju.org, updated every cycle)
_gold_price_toman: Optional[int] = None


def update_gold_price_toman(price: int) -> None:
    """Update the cached gold price in Toman."""
    global _gold_price_toman
    _gold_price_toman = price


def get_gold_price_toman() -> Optional[int]:
    """Get the cached gold price in Toman."""
    return _gold_price_toman


def refresh_usd_irr_rate() -> float:
    """Refresh the live USD/Toman rate from tgju.org and return it.

    Falls back to the last known/existing value on failure.
    """
    global _live_rate
    rate = _fetch_usd_irr_rate()
    if rate and rate > 0:
        _live_rate = rate
        EXCHANGE_RATES["USD_IRR"] = rate
    return EXCHANGE_RATES["USD_IRR"]


def usd_to_toman(usd: float) -> float:
    """Convert USD to Iranian Toman."""
    return usd * EXCHANGE_RATES["USD_IRR"]


def toman_to_usd(toman: float) -> float:
    """Convert Iranian Toman to USD."""
    return toman / EXCHANGE_RATES["USD_IRR"]


def format_currency_conversion(usd_amount: float, toman_amount: float) -> str:
    """Format a currency conversion message."""
    return (
        "💱 *تبدیل ارز*\n"
        "━━━━━━━━━━\n"
        f"🇺🇸 *USD:* `${usd_amount:,.2f}`\n"
        f"🇮🇷 *تومان:* `{toman_amount:,.0f}` تومان\n"
        f"📊 *نرخ:* 1 USD = {EXCHANGE_RATES['USD_IRR']:,} تومان\n"
        "━━━━━━━━━━\n"
        "_نرخ تقریبی - ممکن است کمی متفاوت باشد_"
    )


def format_gold_comparison(gold_toman: int, gold_usd: float) -> str:
    """Compare gold price in Iran (per gram) vs global (per gram)."""
    gold_usd_per_gram = gold_usd / 31.1035
    gold_toman_per_ounce = gold_toman * 31.1035
    return (
        "🥇 *مقایسه قیمت طلا*\n"
        "━━━━━━\n"
        f"🇮🇷 *ایران:* `{gold_toman:,}` تومان (هر گرم ۱۸ عیار)\n"
        f"🌍 *جهانی:* `${gold_usd:,.2f}` (XAU/USD - هر اونس)\n"
        f"🔄 *معادل:* `${gold_usd_per_gram:,.2f}` (هر گرم)\n"
        f"🔄 *معادل:* `{gold_toman_per_ounce:,.0f}` تومان (هر اونس)\n"
        "━━━━━━\n"
        "_منابع: tgju.org و TradingView_"
    )


# ─── Chart image download ────────────────────────────────────────────

def download_chart_image(ticker: str, interval: str = "60") -> Optional[bytes]:
    """
    Download a chart image from TradingView widget.

    Args:
        ticker: TradingView ticker (e.g. 'BINANCE:BTCUSDT')
        interval: Chart interval (1, 5, 15, 60, 240, D, W, M)

    Returns:
        PNG image bytes, or None on failure.
    """
    url = get_chart_image_url(ticker, interval)
    try:
        response = _request_with_fallback(
            "GET",
            url,
            headers=_get_headers(),
            timeout=15,
            proxies=PROXIES,
            verify=False,
        )
        if response.status_code == 200 and len(response.content) > 1000:
            return response.content
        return None
    except Exception as exc:
        print(f"[crypto_price] Chart download error: {exc}")
        return None

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 50)
    print("TEST: Fetching crypto prices...")
    print("=" * 50)
    prices = fetch_assets_by_market(MARKET_CRYPTO)
    print(format_market_list(prices, MARKET_CRYPTO))

    print("\n\n" + "=" * 50)
    print("TEST: Fetching Bitcoin with TA...")
    print("=" * 50)
    btc = fetch_single_price("BINANCE:BTCUSDT")
    if btc:
        print(format_price_message(btc, include_ta=True))
        print(f"\nChart URL: {get_chart_url(btc.ticker)}")

    print("\n\n" + "=" * 50)
    print("TEST: Fetching Forex...")
    print("=" * 50)
    forex = fetch_assets_by_market(MARKET_FOREX)
    print(format_market_list(forex, MARKET_FOREX))

    print("\n\n" + "=" * 50)
    print("TEST: Fetching Commodities...")
    print("=" * 50)
    commodities = fetch_assets_by_market(MARKET_COMMODITY)
    print(format_market_list(commodities, MARKET_COMMODITY))
