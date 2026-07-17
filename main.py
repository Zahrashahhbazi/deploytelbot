"""
main.py
Entry point for the live gold-price & crypto Telegram notifier.

Fetches:
  - Gold price (18k, per gram, Toman) from tgju.org
  - Cryptocurrency prices (USDT pairs) from TradingView (Binance)
  - Forex, Commodities, Stocks, Indices from TradingView
  - Technical analysis (RSI, MACD, SMA)

Supports interactive buttons and commands.
"""
from __future__ import annotations

import http.server,json,os,platform,re,signal,sys,threading,time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

from gold_price import fetch_gold_price, format_message as format_gold
from crypto_price import (
    ASSETS,MARKET_CRYPTO, MARKET_FOREX, MARKET_COMMODITY,MARKET_STOCK,MARKET_INDEX, MARKET_NAMES, AssetPrice,
    fetch_prices, fetch_single_price, fetch_assets_by_market, get_assets_by_market,format_price_message,format_market_list, get_chart_url,
    AlertManager,  usd_to_toman,  toman_to_usd,  format_currency_conversion,  format_gold_comparison,  update_gold_price_toman,  download_chart_image, EXCHANGE_RATES, refresh_usd_irr_rate,
)
from telegram_bot import TelegramNotifier, escape_markdown

STATE_FILE = Path(__file__).parent / ".last_price"
ALERTS_FILE = Path(__file__).parent / "alerts.json"

# Global alert manager
alert_manager = AlertManager(storage_path=str(ALERTS_FILE))

# Per-chat pending numeric input (set by buttons, consumed by on_message)
_pending_input: Dict[str, str] = {}

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ENGLISH_DIGITS = "0123456789"


def _parse_int(raw: str) -> Optional[int]:
    """Parse an integer from text with Persian/English digits and commas."""
    if not raw:
        return None
    t = str(raw).translate(str.maketrans(_PERSIAN_DIGITS, _ENGLISH_DIGITS))
    t = re.sub(r"[^\d]", "", t)
    return int(t) if t else None


def _parse_float(raw: str) -> Optional[float]:
    """Parse a float from text with Persian/English digits, commas, and dots."""
    if not raw:
        return None
    t = str(raw).translate(str.maketrans(_PERSIAN_DIGITS, _ENGLISH_DIGITS))
    t = re.sub(r"[^\d.]", "", t)
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _parse_amount_unit(raw: str):
    """Parse a money amount and detect unit (usd/toman). Returns (amount, unit)."""
    if not raw:
        return None, None
    t = str(raw).translate(str.maketrans(_PERSIAN_DIGITS, _ENGLISH_DIGITS)).lower()
    unit = "toman"
    if any(k in t for k in ("dollar", "usd", "$", "دلار")):
        unit = "usd"
    elif any(k in t for k in ("toman", "تومان", "تومن", "rial", "ریال")):
        unit = "toman"
    num = re.sub(r"[^\d.]", "", t)
    if not num:
        return None, None
    try:
        return float(num), unit
    except ValueError:
        return None, None


def _handle_gold_range_input(notifier: TelegramNotifier, chat_id: str, mode: str, raw: str) -> None:
    """Process numeric input for gold price range min/max."""
    global _gold_range_min, _gold_range_max
    val = _parse_int(raw)
    if val is None:
        _pending_input[chat_id] = mode
        notifier.send_message(
            "❌ لطفاً یک عدد معتبر وارد کن (مثال: ۳۰۰۰۰۰۰۰).",
            buttons=[[("🔙 برگشت", "cmd_gold_range")]],
            chat_id=chat_id,
        )
        return
    if mode == "gold_range_min":
        _gold_range_min = val
    else:
        _gold_range_max = val
    _send_gold_range_menu(notifier, chat_id)


def _handle_convert_input(notifier: TelegramNotifier, chat_id: str, raw: str) -> None:
    """Process numeric input for currency conversion."""
    amount, unit = _parse_amount_unit(raw)
    if amount is None:
        _pending_input[chat_id] = "convert"
        notifier.send_message(
            "❌ مقدار را وارد کن (مثال: ۱۰۰ دلار یا ۵۰۰۰۰۰۰ تومان).",
            buttons=[[("🔙 برگشت", "cmd_convert")]],
            chat_id=chat_id,
        )
        return
    rate = refresh_usd_irr_rate()
    usd = amount if unit == "usd" else amount / rate
    toman = amount if unit == "toman" else amount * rate
    msg = (
        "💱 *تبدیل ارز*\n"
        "━━\n"
        f"🇺🇸 `{usd:,.2f}` دلار\n"
        f"🇮🇷 `{toman:,.0f}` تومان\n"
        f"📊 نرخ: 1 USD = {rate:,} تومان\n"
        "━━\n"
        "_نرخ تقریبی - ممکن است کمی متفاوت باشد_"
    )
    notifier.send_message(
        msg,
        buttons=[
            [("🔁 تبدیل دیگر", "cmd_convert")],
            [("🏠 منوی اصلی", "cmd_back")],
        ],
        chat_id=chat_id,
    )


def _handle_alert_input(notifier: TelegramNotifier, chat_id: str, mode: str, raw: str) -> None:
    """Process numeric input for price alerts (above/below)."""
    alert_type, ticker = mode.split(":", 1)
    val = _parse_float(raw)
    if val is None:
        _pending_input[chat_id] = mode
        notifier.send_message(
            "❌ لطفاً یک عدد معتبر وارد کن (مثال: ۲۵۰۰۰ یا ۱.۰۸۰۵).",
            buttons=[[("🔙 برگشت", f"cmd_asset_{ticker}")]],
            chat_id=chat_id,
        )
        return

    asset_name = ticker
    asset_symbol = ticker.split(":")[-1]
    for name, t, sym, _ in ASSETS:
        if t == ticker:
            asset_name = name
            asset_symbol = sym
            break

    alert = alert_manager.add_alert(ticker, asset_name, asset_symbol, alert_type, val)

    alert_type_text = "بالاتر از" if alert_type == "alert_above" else "پایین‌تر از"
    notifier.send_message(
        f"✅ *هشدار قیمت تنظیم شد!*\n\n"
        f"🔔 *{asset_name} ({asset_symbol})*\n"
        f"📊 {alert_type_text} `{val:,.2f}`\n\n"
        "وقتی قیمت به این مقدار برسه، بهت اطلاع می‌دم.",
        buttons=[
            [("📋 لیست هشدارها", "cmd_alerts")],
            [("🔙 برگشت", f"cmd_asset_{ticker}")],
        ],
        chat_id=chat_id,
    )


def parse_chat_ids(raw: str) -> List[str]:
    return [piece.strip() for piece in raw.split(",") if piece.strip()]


def get_optional_int(env_name: str) -> Optional[int]:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        print(f"[config] {env_name} is not a valid int, ignoring: {raw!r}")
        return None


def load_last_price() -> Optional[int]:
    try:
        text = STATE_FILE.read_text(encoding="utf-8").strip()
        return int(text) if text else None
    except (OSError, ValueError):
        return None


def save_last_price(price: int) -> None:
    try:
        STATE_FILE.write_text(str(price), encoding="utf-8")
    except OSError as exc:
        print(f"[main] Could not save last price: {exc}")


def _acquire_single_instance() -> object:
    """Ensure only one bot process polls Telegram at a time.

    Binds a localhost TCP socket; if another instance already holds it,
    this one exits. Works on both Windows and Linux and is released
    automatically when the process terminates. Returns the socket so the
    caller keeps it referenced for the process lifetime.
    """
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 18765))
    except OSError:
        print("[main] Another instance is already running. Exiting to avoid duplicate polling.")
        sys.exit(1)
    return sock


def main() -> None:
    load_dotenv()

    # Prevent two bot processes (e.g. a spawned child) from polling the
    # same Telegram token at once, which breaks button handling.
    _instance_lock = _acquire_single_instance()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids_raw = os.getenv("TELEGRAM_CHAT_IDS", "").strip()
    interval = int(os.getenv("CHECK_INTERVAL", "60"))
    price_min = get_optional_int("GOLD_PRICE_MIN")
    price_max = get_optional_int("GOLD_PRICE_MAX")

    if not token or token in ("PUT_YOUR_BOT_TOKEN_HERE", "your_telegram_bot_token_here"):
        print("[main] TELEGRAM_BOT_TOKEN is missing. Set it in your .env file.")
        sys.exit(1)

    chat_ids = parse_chat_ids(chat_ids_raw)
    if not chat_ids:
        print("[main] TELEGRAM_CHAT_IDS is missing. Set at least one chat id in .env.")
        sys.exit(1)

    notifier = TelegramNotifier(token=token, chat_ids=chat_ids)
    print(
        f"[main] Bot started. Interval={interval}s | "
        f"min={price_min} | max={price_max} | chats={chat_ids}"
    )

    # Set the bot's command menu
    notifier.set_my_commands([
        ("start", "منوی اصلی"),
        ("gold", "قیمت طلا"),
        ("crypto", "ارزهای دیجیتال"),
        ("forex", "فارکس"),
        ("commodities", "کالاها (نفت، طلا و...)"),
        ("stocks", "سهام آمریکا"),
        ("indices", "شاخص‌ها"),
        ("help", "راهنما"),
    ])

    # Send a startup notice with interactive buttons
    startup_msg = (
        "📊 *ربات حرفه‌ای بازارهای مالی فعال شد!*\n\n"
        f"⏱ هر `{interval}` ثانیه قیمت طلا چک می‌شود.\n"
        f"📡 منابع: `tgju.org` و `TradingView`\n\n"
        "از دکمه‌های زیر استفاده کن 👇"
    )
    notifier.send_message(
        startup_msg,
        buttons=_build_main_menu_buttons(),
    )

    # Handle incoming messages and button clicks
    def on_message(chat_id: str, text: str) -> None:
        # Handle pending numeric input (gold range / converter / alerts) first
        if chat_id in _pending_input:
            mode = _pending_input.pop(chat_id)
            if mode in ("gold_range_min", "gold_range_max"):
                _handle_gold_range_input(notifier, chat_id, mode, text)
            elif mode == "convert":
                _handle_convert_input(notifier, chat_id, text)
            elif mode.startswith("alert_above:") or mode.startswith("alert_below:"):
                _handle_alert_input(notifier, chat_id, mode, text)
            return

        text_lower = text.strip().lower()
        if text_lower in ("/start", "سلام", "hi", "start", "menu", "منو"):
            _send_main_menu(notifier, chat_id)
        elif text_lower in ("/gold", "gold", "قیمت", "طلا"):
            _send_gold_price(notifier, chat_id)
        elif text_lower in ("/crypto", "crypt", "ارز"):
            _send_market_menu(notifier, chat_id, MARKET_CRYPTO)
        elif text_lower in ("/forex", "forex", "فارکس"):
            _send_market_menu(notifier, chat_id, MARKET_FOREX)
        elif text_lower in ("/commodities", "commodities", "commodity", "کالا", "نفت"):
            _send_market_menu(notifier, chat_id, MARKET_COMMODITY)
        elif text_lower in ("/stocks", "stocks", "stock", "سهام"):
            _send_market_menu(notifier, chat_id, MARKET_STOCK)
        elif text_lower in ("/indices", "indices", "index", "شاخص"):
            _send_market_menu(notifier, chat_id, MARKET_INDEX)
        elif text_lower in ("/help", "help", "راهنما"):
            _send_help(notifier, chat_id)
        elif text_lower in ("/alerts", "alerts", "هشدار"):
            _list_alerts(notifier, chat_id)
        elif text_lower in ("/convert", "convert", "تبدیل"):
            _send_converter_menu(notifier, chat_id)
        elif text_lower in ("/ta", "ta", "تحلیل"):
            _send_ta_menu(notifier, chat_id)
        elif text_lower in ("/compare", "compare", "مقایسه"):
            _send_compare_menu(notifier, chat_id)
        elif text_lower in ("/health", "health", "وضعیت"):
            _send_health_status(notifier, chat_id)
        else:
            notifier.send_message(
                "🤔 *دستور نامشخص!*\n\n"
                "از دکمه‌ها یا دستورات زیر استفاده کن:\n"
                "`/start` - منوی اصلی\n"
                "`/gold` - قیمت طلا\n"
                "`/crypto` - ارز دیجیتال\n"
                "`/forex` - فارکس\n"
                "`/commodities` - کالاها\n"
                "`/stocks` - سهام\n"
                "`/indices` - شاخص‌ها\n"
                "`/help` - راهنما",
                buttons=_build_main_menu_buttons(),
            )

    def on_callback(chat_id: str, data: str, cq_id: str) -> None:
        """Handle button clicks."""
        if data == "cmd_gold":
            _send_gold_price(notifier, chat_id)
        elif data == "cmd_crypto":
            _send_market_menu(notifier, chat_id, MARKET_CRYPTO)
        elif data == "cmd_forex":
            _send_market_menu(notifier, chat_id, MARKET_FOREX)
        elif data == "cmd_commodities":
            _send_market_menu(notifier, chat_id, MARKET_COMMODITY)
        elif data == "cmd_stocks":
            _send_market_menu(notifier, chat_id, MARKET_STOCK)
        elif data == "cmd_indices":
            _send_market_menu(notifier, chat_id, MARKET_INDEX)
        elif data.startswith("cmd_market_list_"):
            market = data.replace("cmd_market_list_", "")
            _send_market_list(notifier, chat_id, market)
        elif data.startswith("cmd_asset_"):
            ticker = data.replace("cmd_asset_", "")
            _send_single_asset(notifier, chat_id, ticker)
        elif data.startswith("cmd_chart_"):
            ticker = data.replace("cmd_chart_", "")
            _send_chart(notifier, chat_id, ticker)
        elif data.startswith("cmd_alert_above_"):
            ticker = data.replace("cmd_alert_above_", "")
            _pending_input[chat_id] = f"alert_above:{ticker}"
            asset = fetch_single_price(ticker)
            price_hint = f"{asset.price * 1.05:.2f}" if asset else "??? ..."
            notifier.send_message(
                f"📈 *تنظیم هشدار بالاتر از*\n\n"
                f"مقدار آستانه رو وارد کن:\n"
                f"مثال: `{price_hint}`",
                buttons=[[("🔙 برگشت", f"cmd_asset_{ticker}")]],
                chat_id=chat_id,
            )
        elif data.startswith("cmd_alert_below_"):
            ticker = data.replace("cmd_alert_below_", "")
            _pending_input[chat_id] = f"alert_below:{ticker}"
            asset = fetch_single_price(ticker)
            price_hint = f"{asset.price * 0.95:.2f}" if asset else "??? ..."
            notifier.send_message(
                f"📉 *تنظیم هشدار پایین‌تر از*\n\n"
                f"مقدار آستانه رو وارد کن:\n"
                f"مثال: `{price_hint}`",
                buttons=[[("🔙 برگشت", f"cmd_asset_{ticker}")]],
                chat_id=chat_id,
            )
        elif data.startswith("cmd_alert_del_"):
            idx = int(data.replace("cmd_alert_del_", ""))
            _delete_alert(notifier, chat_id, idx)
        elif data == "cmd_alerts":
            _list_alerts(notifier, chat_id)
        elif data == "cmd_convert":
            _pending_input[chat_id] = "convert"
            _send_converter_menu(notifier, chat_id)
        elif data == "cmd_convert_gold":
            _send_gold_comparison(notifier, chat_id)
        elif data == "cmd_help":
            _send_help(notifier, chat_id)
        elif data == "cmd_ta_menu":
            _send_ta_menu(notifier, chat_id)
        elif data == "cmd_compare_menu":
            _send_compare_menu(notifier, chat_id)
        elif data == "cmd_gold_range":
            _send_gold_range_menu(notifier, chat_id)
        elif data == "cmd_health":
            _send_health_status(notifier, chat_id)
        elif data.startswith("cmd_ta_asset_"):
            ticker = data.replace("cmd_ta_asset_", "")
            _send_advanced_ta(notifier, chat_id, ticker)
        elif data.startswith("cmd_compare_"):
            parts = data.replace("cmd_compare_", "").split("|")
            if len(parts) == 2:
                _send_compare_assets(notifier, chat_id, parts[0], parts[1])
        elif data == "cmd_gold_range_set_min":
            _pending_input[chat_id] = "gold_range_min"
            _send_gold_range_set(notifier, chat_id, "min")
        elif data == "cmd_gold_range_set_max":
            _pending_input[chat_id] = "gold_range_max"
            _send_gold_range_set(notifier, chat_id, "max")
        elif data == "cmd_gold_range_clear":
            _clear_gold_range(notifier, chat_id)
        elif data == "cmd_back":
            _send_main_menu(notifier, chat_id)
        notifier.answer_callback_query(cq_id)

    # Start receiving updates: Webhook mode (hosted/deploy) or Polling (local)
    webhook_base = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
    _runtime: Dict[str, object] = {"webhook_server": None}
    if webhook_base:
        secret = os.getenv("WEBHOOK_SECRET", "").strip()
        port = int(os.getenv("PORT", "8080"))
        full_url = f"{webhook_base}/webhook"
        notifier.set_webhook(full_url, secret or None)
        print(f"[main] Webhook mode -> POST {full_url} (port {port})")
        _runtime["webhook_server"] = _start_webhook_server(
            port, secret, on_message, on_callback
        )
    else:
        notifier.delete_webhook()
        print("[main] Polling mode (local)")
        notifier.start_polling(on_message=on_message, on_callback=on_callback)

    # Graceful shutdown
    stop_flag = {"value": False}

    def _handle_signal(_signum, _frame):
        stop_flag["value"] = True
        notifier.stop_polling()
        server = _runtime.get("webhook_server")
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
        print("\n[main] Shutdown signal received, exiting...")

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    last_sent_price: Optional[int] = load_last_price()
    cycle_count = 0

    while not stop_flag["value"]:
        gold = fetch_gold_price()
        cycle_count += 1

        if gold is not None:
            triggered = False
            reason = ""

            if price_min is not None and gold.price_toman < price_min:
                triggered = True
                reason = f"قیمت زیر حداقل ({price_min:,})"
            elif price_max is not None and gold.price_toman > price_max:
                triggered = True
                reason = f"قیمت بالای حداکثر ({price_max:,})"

            should_send = triggered or (last_sent_price != gold.price_toman)
            if should_send:
                message = format_gold(gold)
                if triggered:
                    message = f"🚨 *هشدار قیمت طلا*\n{reason}\n\n" + message
                notifier.send_message(
                    message,
                    buttons=_build_main_menu_buttons(),
                )
                last_sent_price = gold.price_toman
                save_last_price(gold.price_toman)
        else:
            print(f"[main] [{cycle_count}] Could not fetch price, retrying...")

        # Check price alerts for all active alerts
        alerts = alert_manager.list_alerts()
        if alerts:
            unique_tickers = list({a.ticker for a in alerts})
            try:
                alert_prices = fetch_prices(unique_tickers)
                ticker_price_map = {}
                for ticker, price_data in zip(unique_tickers, alert_prices):
                    if price_data is not None:
                        ticker_price_map[ticker] = price_data.price

                for alert in alerts:
                    current = ticker_price_map.get(alert.ticker)
                    if current is not None:
                        triggered = alert_manager.check_alerts(alert.ticker, current)
                        for trig_alert in triggered:
                            direction = "📈" if trig_alert.alert_type == "above" else "📉"
                            alert_msg = (
                                f"🚨 *هشدار قیمت*\n"
                                f"{direction} *{trig_alert.name}* ({trig_alert.symbol})\n"
                                f"📊 {trig_alert.threshold:,.2f} رو رسید!\n\n"
                                f"💰 قیمت فعلی: `{current:,.2f}`\n"
                                f"🕒 زمان: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
                            )
                            notifier.send_message(
                                alert_msg,
                                buttons=[
                                    [("📋 لیست هشدارها", "cmd_alerts")],
                                    [("🏠 منوی اصلی", "cmd_back")],
                                ],
                            )
            except Exception as exc:
                print(f"[main] Alert check error: {exc}")

        for _ in range(interval):
            if stop_flag["value"]:
                break
            time.sleep(1)

    print("[main] Bot stopped.")


# ─── Webhook server (for hosted/deploy mode) ──────────────────────────

def _start_webhook_server(port: int, secret: str, on_message, on_callback):
    """Start a minimal HTTP server that receives Telegram webhook updates.

    Telegram POSTs updates to POST /webhook. Each update is dispatched to the
    provided on_message / on_callback handlers in a background thread.
    Returns the HTTPServer instance so the caller can shut it down.
    """
    class _Handler(http.server.BaseHTTPRequestHandler):
        def _dispatch(self, update):
            try:
                if "callback_query" in update:
                    cq = update["callback_query"]
                    chat_id = str(cq["message"]["chat"]["id"])
                    on_callback(chat_id, cq.get("data", ""), cq["id"])
                elif "message" in update:
                    msg = update["message"]
                    chat_id = str(msg["chat"]["id"])
                    on_message(chat_id, msg.get("text", ""))
            except Exception as exc:
                print(f"[webhook] dispatch error: {exc}")

        def do_GET(self):
            if self.path.rstrip("/") == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            elif self.path.rstrip("/") in ("/", "/webhook"):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"OK")
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path.rstrip("/") != "/webhook":
                self.send_response(404)
                self.end_headers()
                return
            if secret and self.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
                self.send_response(403)
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(length) if length else b""
                update = json.loads(body.decode("utf-8")) if body else {}
            except Exception as exc:
                print(f"[webhook] bad request: {exc}")
                self.send_response(400)
                self.end_headers()
                return
            # Respond quickly, then process asynchronously
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("OK".encode("utf-8"))
            threading.Thread(target=self._dispatch, args=(update,), daemon=True).start()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    print(f"[webhook] Listening on 0.0.0.0:{port}/webhook")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ─── Button builders ─────────────────────────────────────────────────

def _build_main_menu_buttons() -> List[List[tuple]]:
    """Build the main menu buttons."""
    return [
        [("🥇 طلا", "cmd_gold"), ("🪙 ارز دیجیتال", "cmd_crypto")],
        [("💱 فارکس", "cmd_forex"), ("🛢️ کالاها", "cmd_commodities")],
        [("📈 سهام", "cmd_stocks"), ("📊 شاخص‌ها", "cmd_indices")],
        [("🔔 هشدارها", "cmd_alerts"), ("💱 تبدیل ارز", "cmd_convert")],
        [("📊 تحلیل تکنیکال", "cmd_ta_menu"), ("⚖️ مقایسه دارایی‌ها", "cmd_compare_menu")],
        [("🎯 تنظیم بازه طلا", "cmd_gold_range"), ("🩺 وضعیت سیستم", "cmd_health")],
        [("📖 راهنما", "cmd_help")],
    ]


def _build_market_buttons(market: str) -> List[List[tuple]]:
    """Build buttons for assets in a specific market."""
    assets = get_assets_by_market(market)
    buttons = []
    row = []
    for name, ticker, symbol, _ in assets:
        row.append((symbol, f"cmd_asset_{ticker}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    # Add "list all" and "back" buttons
    buttons.append([("📋 لیست همه", f"cmd_market_list_{market}")])
    buttons.append([("🏠 منوی اصلی", "cmd_back")])
    return buttons


# ─── Message senders ─────────────────────────────────────────────────

def _send_main_menu(notifier: TelegramNotifier, chat_id: str) -> None:
    """Send the main menu."""
    notifier.send_message(
        "🏠 *منوی اصلی*\n\n"
        "به ربات بازارهای مالی خوش آمدی!\n"
        "یک بازار رو انتخاب کن:",
        buttons=_build_main_menu_buttons(),
        chat_id=chat_id,
    )


def _send_gold_price(notifier: TelegramNotifier, chat_id: str) -> None:
    """Fetch and send the current gold price."""
    gold = fetch_gold_price()
    if gold is None:
        notifier.send_message(
            "❌ *خطا در دریافت قیمت طلا*\nکمی بعد دوباره امتحان کن.",
            buttons=[[("🔄 تلاش مجدد", "cmd_gold"), ("🏠 منو", "cmd_back")]],
            chat_id=chat_id,
        )
        return
    notifier.send_message(
        format_gold(gold),
        buttons=[
            [("🔄 تازه‌سازی", "cmd_gold")],
            [("🏠 منوی اصلی", "cmd_back")],
        ],
        chat_id=chat_id,
    )


def _send_market_menu(notifier: TelegramNotifier, chat_id: str, market: str) -> None:
    """Send a market sub-menu with asset buttons."""
    market_name = MARKET_NAMES.get(market, "بازار")
    notifier.send_message(
        f"{market_name}\n\n"
        "یک دارایی رو انتخاب کن یا لیست کامل رو ببین:",
        buttons=_build_market_buttons(market),
        chat_id=chat_id,
    )


def _send_market_list(notifier: TelegramNotifier, chat_id: str, market: str) -> None:
    """Fetch and send the list of all assets in a market."""
    notifier.send_message("⏳ در حال دریافت لیست قیمت‌ها...", chat_id=chat_id)
    prices = fetch_assets_by_market(market)
    if not prices or all(p is None for p in prices):
        notifier.send_message(
            "❌ *خطا در دریافت قیمت‌ها*\nکمی بعد دوباره امتحان کن.",
            buttons=[[("🔄 تلاش مجدد", f"cmd_market_list_{market}"), ("🏠 منو", "cmd_back")]],
            chat_id=chat_id,
        )
        return
    notifier.send_message(
        format_market_list(prices, market),
        buttons=[
            [("🏠 منوی اصلی", "cmd_back")],
        ],
        chat_id=chat_id,
    )


def _send_single_asset(notifier: TelegramNotifier, chat_id: str, ticker: str) -> None:
    """Fetch and send a single asset price with technical analysis."""
    notifier.send_message("⏳ در حال دریافت قیمت و تحلیل...", chat_id=chat_id)
    asset = fetch_single_price(ticker)
    if asset is None:
        notifier.send_message(
            "❌ *خطا در دریافت قیمت*\nکمی بعد دوباره امتحان کن.",
            buttons=[[("🔄 تلاش مجدد", f"cmd_asset_{ticker}"), ("🏠 منو", "cmd_back")]],
            chat_id=chat_id,
        )
        return

    # Send price with TA
    notifier.send_message(
        format_price_message(asset, include_ta=True),
        buttons=[
            [("🔄 تازه‌سازی", f"cmd_asset_{ticker}")],
            [("📈 نمودار", f"cmd_chart_{ticker}")],
            [("📈 بالاتر از", f"cmd_alert_above_{ticker}"), ("📉 پایین‌تر از", f"cmd_alert_below_{ticker}")],
            [("🏠 منوی اصلی", "cmd_back")],
        ],
        chat_id=chat_id,
    )


def _send_chart(notifier: TelegramNotifier, chat_id: str, ticker: str) -> None:
    """Send a chart image for an asset."""
    chart_url = get_chart_url(ticker)
    image_url = f"https://image.thum.io/get/crop/800x450/{chart_url}"

    notifier.send_photo(
        chat_id=chat_id,
        photo_url=image_url,
        caption=(
            f"📈 *نمودار {escape_markdown(ticker)}*\n\n"
            f"🔗 [مشاهده در TradingView]({chart_url})"
        ),
        buttons=[
            [("🔄 تازه‌سازی", f"cmd_chart_{ticker}")],
            [("🔙 برگشت", f"cmd_asset_{ticker}")],
        ],
    )


def _delete_alert(notifier: TelegramNotifier, chat_id: str, index: int) -> None:
    """Delete a price alert."""
    alert = alert_manager.remove_alert(index)
    if alert:
        notifier.send_message(
        f"✅ *هشدار حذف شد:* {alert.name} ({alert.symbol})",
        buttons=[[("📋 لیست هشدارها", "cmd_alerts"), ("🏠 منو", "cmd_back")]],
        chat_id=chat_id,
    )
    else:
        notifier.send_message(
            "❌ هشدار یافت نشد.",
            buttons=[[("📋 لیست هشدارها", "cmd_alerts"), ("🏠 منو", "cmd_back")]],
            chat_id=chat_id,
        )


def _list_alerts(notifier: TelegramNotifier, chat_id: str) -> None:
    """List all active price alerts."""
    alerts = alert_manager.list_alerts()
    if not alerts:
        notifier.send_message(
            "🔔 *هشدارهای قیمت*\n\n"
            "هیچ هشدار فعالی وجود ندارد.\n\n"
            "برای تنظیم هشدار، روی یک دارایی کلیک کن و گزینه 'تنظیم هشدار' رو انتخاب کن.",
            buttons=[[("🏠 منوی اصلی", "cmd_back")]],
            chat_id=chat_id,
        )
        return

    msg = "🔔 *هشدارهای فعال*\n━━━━━━━━━━\n"
    for i, alert in enumerate(alerts):
        alert_type_text = "📈 بالاتر از" if alert.alert_type == "above" else "📉 پایین‌تر از"
        msg += f"{i+1}. *{alert.name}* ({alert.symbol})\n"
        msg += f"   {alert_type_text} `{alert.threshold:,.2f}`\n"

    # Build delete buttons
    buttons = []
    for i in range(len(alerts)):
        buttons.append([(f"❌ حذف {i+1}", f"cmd_alert_del_{i}")])
    buttons.append([("🏠 منوی اصلی", "cmd_back")])

    notifier.send_message(msg, buttons=buttons, chat_id=chat_id)


def _send_converter_menu(notifier: TelegramNotifier, chat_id: str) -> None:
    """Send currency converter menu."""
    rate = refresh_usd_irr_rate()
    notifier.send_message(
        "💱 *تبدیل ارز*\n\n"
        f"۱ USD = {rate:,.0f} تومان\n\n"
        "مقدار مورد نظر رو به تومان یا دلار وارد کن:\n"
        "مثال: `100` دلار یا `5000000` تومان",
        buttons=[
            [("🥇 مقایسه طلا", "cmd_convert_gold")],
            [("🏠 منوی اصلی", "cmd_back")],
        ],
        chat_id=chat_id,
    )


def _send_gold_comparison(notifier: TelegramNotifier, chat_id: str) -> None:
    """Compare gold price in Iran vs global."""
    from gold_price import fetch_gold_price

    gold_iran = fetch_gold_price()
    gold_global = fetch_single_price("OANDA:XAUUSD")

    if gold_iran and gold_global:
        update_gold_price_toman(gold_iran.price_toman)
        notifier.send_message(
            format_gold_comparison(gold_iran.price_toman, gold_global.price),
            buttons=[
                [("🔄 تازه‌سازی", "cmd_convert_gold")],
                [("💱 تبدیل ارز", "cmd_convert")],
                [("🏠 منوی اصلی", "cmd_back")],
            ],
            chat_id=chat_id,
        )
    else:
        notifier.send_message(
            "❌ *خطا در دریافت قیمت‌ها*\nکمی بعد دوباره امتحان کن.",
            buttons=[[("🔄 تلاش مجدد", "cmd_convert_gold"), ("🏠 منو", "cmd_back")]],
            chat_id=chat_id,
        )


def _send_help(notifier: TelegramNotifier, chat_id: str) -> None:
    """Send help message."""
    notifier.send_message(
        "📖 *راهنمای ربات*\n\n"
        "🔹 `/start` — منوی اصلی\n"
        "🔹 `/gold` — قیمت طلا\n"
        "🔹 `/crypto` — ارزهای دیجیتال\n"
        "🔹 `/forex` — فارکس\n"
        "🔹 `/commodities` — کالاها (نفت، طلای جهانی)\n"
        "🔹 `/stocks` — سهام آمریکا\n"
        "🔹 `/indices` — شاخص‌ها\n"
        "🔹 `/alerts` — هشدارهای قیمت\n"
        "🔹 `/convert` — تبدیل ارز\n"
        "🔹 `/ta` — تحلیل تکنیکال پیشرفته\n"
        "🔹 `/compare` — مقایسه دارایی‌ها\n"
        "🔹 `/health` — وضعیت سیستم\n"
        "🔹 `/help` — راهنما\n\n"
        "💡 می‌تونی از دکمه‌ها هم استفاده کنی!\n"
        "📡 *منابع:*\n"
        "🥇 طلا: `tgju.org`\n"
        "📊 سایر بازارها: `TradingView`\n"
        "⚙️ *تنظیمات:*\n"
        "بازه ارسال خودکار: هر ۶۰ ثانیه",
        buttons=_build_main_menu_buttons(),
        chat_id=chat_id,
    )

TOP_TA_ASSETS = [
    ("بیت‌کوین", "BINANCE:BTCUSDT", "BTC"),
    ("اتریوم", "BINANCE:ETHUSDT", "ETH"),
    ("ریپل", "BINANCE:XRPUSDT", "XRP"),
    ("سولانا", "BINANCE:SOLUSDT", "SOL"),
    ("دوج کوین", "BINANCE:DOGEUSDT", "DOGE"),
    ("کاردانو", "BINANCE:ADAUSDT", "ADA"),
]


def _send_ta_menu(notifier: TelegramNotifier, chat_id: str) -> None:
    """Send the advanced technical analysis menu."""
    buttons = []
    for name, ticker, symbol in TOP_TA_ASSETS:
        buttons.append([(f"📊 {name} ({symbol})", f"cmd_ta_asset_{ticker}")])
    buttons.append([("🏠 منوی اصلی", "cmd_back")])

    notifier.send_message(
        "📊 *تحلیل تکنیکال پیشرفته*\n"
        "یک دارایی رو برای تحلیل انتخاب کن:\n"
        "شامل: RSI, MACD, SMA, باند بولینگر و میانگین‌های متحرک",
        buttons=buttons,
        chat_id=chat_id,
    )


def _send_advanced_ta(notifier: TelegramNotifier, chat_id: str, ticker: str) -> None:
    asset = fetch_single_price(ticker)
    if asset is None:
        notifier.send_message(
            "❌ *خطا در دریافت تحلیل*\nکمی بعد دوباره امتحان کن.",
            buttons=[[("🔄 تلاش مجدد", f"cmd_ta_asset_{ticker}"), ("🏠 منو", "cmd_back")]],
            chat_id=chat_id,
        )
        return

    msg = f"📊 *تحلیل تکنیکال {asset.name}*\n"
    msg += "━━\n"
    msg += f"💰 *قیمت:* `{asset.price:,.2f}`\n"
    msg += f"📈 *تغییر:* {asset.change_percent:+.2f}%\n"
    msg += "━━\n"

    if asset.rsi is not None:
        rsi_status = "🟢 اشباع خرید" if asset.rsi > 70 else ("🔴 اشباع فروش" if asset.rsi < 30 else "⚪ خنثی")
        msg += f"📊 *RSI:* `{asset.rsi:.1f}` — {rsi_status}\n"

    if asset.macd is not None and asset.macd_signal is not None:
        macd_status = "🟢 صعودی" if asset.macd > asset.macd_signal else "🔴 نزولی"
        msg += f"📊 *MACD:* `{asset.macd:.2f}` / `{asset.macd_signal:.2f}` — {macd_status}\n"

    if asset.sma_50 is not None:
        sma_status = "🟢 بالای SMA" if asset.price > asset.sma_50 else "🔴 پایین SMA"
        msg += f"📊 *SMA50:* `{asset.sma_50:.2f}` — {sma_status}\n"

    if asset.sma_200 is not None:
        sma200_status = "🟢 بالای SMA" if asset.price > asset.sma_200 else "🔴 پایین SMA"
        msg += f"📊 *SMA200:* `{asset.sma_200:.2f}` — {sma200_status}\n"

    if asset.recommendation:
        rec_emoji = {
            "STRONG_BUY": "🟢", "BUY": "🟢",
            "STRONG_SELL": "🔴", "SELL": "🔴",
            "NEUTRAL": "⚪"
        }
        emoji = rec_emoji.get(asset.recommendation, "⚪")
        msg += f"📊 *توصیه:* {emoji} {escape_markdown(asset.recommendation)}\n"

    msg += "━━\n"
    msg += f"🔗 [نمودار در TradingView]({get_chart_url(ticker)})"

    notifier.send_message(
        msg,
        buttons=[
            [("🔄 تازه‌سازی", f"cmd_ta_asset_{ticker}")],
            [("📈 نمودار", f"cmd_chart_{ticker}")],
            [("🔙 برگشت به تحلیل", "cmd_ta_menu")],
            [("🏠 منوی اصلی", "cmd_back")],
        ],
        chat_id=chat_id,
    )

COMPARE_PAIRS = [
    ("بیت‌کوین / اتریوم", "BINANCE:BTCUSDT", "BINANCE:ETHUSDT"),
    ("بیت‌کوین / سولانا", "BINANCE:BTCUSDT", "BINANCE:SOLUSDT"),
    ("اتریوم / سولانا", "BINANCE:ETHUSDT", "BINANCE:SOLUSDT"),
    ("بیت‌کوین / طلای جهانی", "BINANCE:BTCUSDT", "OANDA:XAUUSD"),
]


def _send_compare_menu(notifier: TelegramNotifier, chat_id: str) -> None:
    """Send the asset comparison menu."""
    buttons = []
    for name, ticker1, ticker2 in COMPARE_PAIRS:
        buttons.append([(f"⚖️ {name}", f"cmd_compare_{ticker1}|{ticker2}")])
    buttons.append([("🏠 منوی اصلی", "cmd_back")])

    notifier.send_message(
        "⚖️ *مقایسه دارایی‌ها*\n\n"
        "دو دارایی رو برای مقایسه انتخاب کن:\n"
        "قیمت، تغییرات و نسبت بین اونها نمایش داده می‌شه.",
        buttons=buttons,
        chat_id=chat_id,
    )


def _send_compare_assets(notifier: TelegramNotifier, chat_id: str, ticker1: str, ticker2: str) -> None:
    """Compare two assets side by side."""
    notifier.send_message("⏳ در حال دریافت اطلاعات برای مقایسه...", chat_id=chat_id)
    asset1 = fetch_single_price(ticker1)
    asset2 = fetch_single_price(ticker2)

    if asset1 is None or asset2 is None:
        notifier.send_message(
            "❌ *خطا در دریافت قیمت‌ها*\nکمی بعد دوباره امتحان کن.",
            buttons=[[("🔄 تلاش مجدد", f"cmd_compare_{ticker1}|{ticker2}"), ("🏠 منو", "cmd_back")]],
            chat_id=chat_id,
        )
        return
    ratio = asset1.price / asset2.price if asset2.price != 0 else 0
    msg = "⚖️ *مقایسه دارایی‌ها*\n"
    msg += "━━\n"
    msg += f"🔹 *{escape_markdown(asset1.name)}*\n"
    msg += f"   💰 قیمت: `{asset1.price:,.2f}`\n"
    msg += f"   📈 تغییر: {asset1.change_percent:+.2f}%\n"
    msg += "━━\n"
    msg += f"🔸 *{escape_markdown(asset2.name)}*\n"
    msg += f"   💰 قیمت: `{asset2.price:,.2f}`\n"
    msg += f"   📈 تغییر: {asset2.change_percent:+.2f}%\n"
    msg += "━━\n"
    msg += f"📊 *نسبت:* 1 {escape_markdown(asset1.symbol)} = `{ratio:.6f}` {escape_markdown(asset2.symbol)}\n"
    msg += "━━\n"

    if asset1.change_percent > asset2.change_percent:
        msg += f"🏆 *{escape_markdown(asset1.name)}* عملکرد بهتری داشته!"
    elif asset2.change_percent > asset1.change_percent:
        msg += f"🏆 *{escape_markdown(asset2.name)}* عملکرد بهتری داشته!"
    else:
        msg += "🤝 هر دو عملکرد مشابهی دارند."

    notifier.send_message(
        msg,
        buttons=[
            [("🔄 تازه‌سازی", f"cmd_compare_{ticker1}|{ticker2}")],
            [("🔙 برگشت به مقایسه", "cmd_compare_menu")],
            [("🏠 منوی اصلی", "cmd_back")],
        ],
        chat_id=chat_id,
    )

_gold_range_min: Optional[int] = None
_gold_range_max: Optional[int] = None

def _send_gold_range_menu(notifier: TelegramNotifier, chat_id: str) -> None:
    """Send the gold price range settings menu."""
    global _gold_range_min, _gold_range_max
    msg = "🎯 *تنظیم بازه قیمت طلا*\n"
    msg += "━━\n"
    msg += "با تنظیم بازه، ربات فقط وقتی قیمت طلا\n"
    msg += "خارج از این محدوده باشه بهت اطلاع می‌ده.\n\n"

    if _gold_range_min is not None:
        msg += f"📉 *حداقل:* `{_gold_range_min:,}` تومان\n"
    else:
        msg += "📉 *حداقل:* تنظیم نشده\n"

    if _gold_range_max is not None:
        msg += f"📈 *حداکثر:* `{_gold_range_max:,}` تومان\n"
    else:
        msg += "📈 *حداکثر:* تنظیم نشده\n"

    msg += "\nمقدار مورد نظر رو به تومان وارد کن:\n"
    msg += "مثال: برای حداقل `30000000`"

    buttons = [
        [("📉 تنظیم حداقل", "cmd_gold_range_set_min"), ("📈 تنظیم حداکثر", "cmd_gold_range_set_max")],
    ]
    if _gold_range_min is not None or _gold_range_max is not None:
        buttons.append([("🗑️ پاک کردن بازه", "cmd_gold_range_clear")])
    buttons.append([("🏠 منوی اصلی", "cmd_back")])

    notifier.send_message(msg, buttons=buttons, chat_id=chat_id)


def _send_gold_range_set(notifier: TelegramNotifier, chat_id: str, range_type: str) -> None:
    """Ask user to enter a value for gold range."""
    label = "حداقل" if range_type == "min" else "حداکثر"
    notifier.send_message(
        f"📝 *تنظیم {label} قیمت طلا*\n\n"
        f"مقدار {label} رو به تومان وارد کن:\n"
        "مثال: `30000000`",
        buttons=[[("🔙 برگشت", "cmd_gold_range")]],
        chat_id=chat_id,
    )


def _clear_gold_range(notifier: TelegramNotifier, chat_id: str) -> None:
    """Clear the gold price range settings."""
    global _gold_range_min, _gold_range_max
    _gold_range_min = None
    _gold_range_max = None
    notifier.send_message(
        "✅ *بازه قیمت طلا پاک شد!*\n\n"
        "حالا ربات تمام تغییرات قیمت رو گزارش می‌ده.",
        buttons=[[("🎯 تنظیم بازه", "cmd_gold_range"), ("🏠 منو", "cmd_back")]],
        chat_id=chat_id,
    )

# ─── Health Check ─────────────────────

def _send_health_status(notifier: TelegramNotifier, chat_id: str) -> None:
    """Send system health status."""
    import datetime
    msg = "🩺 *وضعیت سیستم*\n"
    msg += "━━\n"
    msg += f"🕒 *زمان:* `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
    msg += f"💻 *پلتفرم:* `{platform.system()} {platform.release()}`\n"
    msg += f"🐍 *پایتون:* `{platform.python_version()}`\n"
    msg += "━━\n"

    gold = fetch_gold_price()
    if gold:
        msg += f"✅ *طلا:* `{gold.price_toman:,}` تومان (آخرین به‌روزرسانی: {gold.timestamp})\n"
    else:
        msg += "❌ *طلا:* خطا در دریافت\n"

    btc = fetch_single_price("BINANCE:BTCUSDT")
    if btc:
        msg += f"✅ *بیت‌کوین:* `${btc.price:,.2f}`\n"
    else:
        msg += "❌ *بیت‌کوین:* خطا در دریافت\n"

    msg += "━━\n"

    alerts = alert_manager.list_alerts()
    msg += f"🔔 *هشدارهای فعال:* `{len(alerts)}`\n"

    if _gold_range_min is not None or _gold_range_max is not None:
        msg += "🎯 *بازه طلا:* فعال\n"
    else:
        msg += "🎯 *بازه طلا:* غیرفعال\n"

    msg += "━━\n"
    msg += "✅ *همه سرویس‌ها فعال هستند*" if gold and btc else "⚠️ *برخی سرویس‌ها مشکل دارند*"

    notifier.send_message(
        msg,
        buttons=[
            [("🔄 تازه‌سازی", "cmd_health")],
            [("🏠 منوی اصلی", "cmd_back")],
        ],
        chat_id=chat_id,
    )


if __name__ == "__main__":
    main()
