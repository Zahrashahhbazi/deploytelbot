"""
telegram_bot.py
Sends messages to Telegram using the Bot API via `urllib3`.

Connection modes (in order of preference):
  1. Cloudflare Worker  — if WORKER_URL is set in .env (no VPN needed!)
  2. Psiphon proxy      — reads Windows registry (VPN needed)
  3. Direct             — no proxy (may fail in Iran)

Supports:
  - Inline keyboards (buttons)
  - Bot commands menu (/start, /price, /status, /help)
  - Callback query handling (button clicks)
"""
from __future__ import annotations
import json
import os
import re
import ssl
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
import urllib3
from urllib3 import ProxyManager
ChatId = Union[str, int]

API_BASE = "https://api.telegram.org/bot"


def escape_markdown(text: str) -> str:
    """Escape special Markdown characters for Telegram.

    Telegram's MarkdownV2 requires escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !
    For regular Markdown (parse_mode='Markdown'), only _ * [ ] ( ) ~ ` > need escaping.
    """
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(r"([" + re.escape(special_chars) + r"])", r"\\\1", text)


def _get_worker_url() -> Optional[str]:
    """
    Read the Cloudflare Worker URL from the WORKER_URL env var.
    Example: https://my-telegram-proxy.username.workers.dev
    """
    url = os.getenv("WORKER_URL", "").strip()
    if url and url.startswith("http"):
        return url.rstrip("/")
    return None


def _get_psiphon_proxy() -> Optional[str]:
    """
    Read the HTTP proxy address from the Windows registry (set by Psiphon).
    Returns an HTTP proxy URL like 'http://127.0.1:59485' or None.
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

    for part in str(server).split(";"):
        if "=" not in part:
            continue
        scheme, addr = part.split("=", 1)
        scheme = scheme.strip().lower()
        addr = addr.strip()
        if scheme == "http" and not addr.startswith("http://") and not addr.startswith("https://"):
            if addr.startswith("127.0.1") and not addr.startswith("127.0.0.1"):
                addr = addr.replace("127.0.1", "127.0.0.1", 1)
            return f"http://{addr}"
    return None


def _build_inline_keyboard(buttons: List[List[Tuple[str, str]]]) -> List[List[Dict[str, str]]]:
    """
    Build an inline keyboard markup from a list of button rows.
    Each row is a list of (text, callback_data) tuples.
    """
    return [
        [{"text": text, "callback_data": data} for text, data in row]
        for row in buttons
    ]


class TelegramNotifier:
    """Sends messages to one or more Telegram chats via the Bot API."""

    def __init__(self, token: str, chat_ids: Iterable[ChatId]):
        if not token:
            raise ValueError("Telegram bot token is empty.")
        chat_list = [str(c).strip() for c in chat_ids if str(c).strip()]
        if not chat_list:
            raise ValueError("No chat IDs provided.")
        self.token = token
        self.chat_ids = chat_list
        self._last_update_id = 0
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None

        # Determine connection mode
        worker_url = _get_worker_url()
        proxy_url = _get_psiphon_proxy()

        if worker_url:
            # Mode 1: Cloudflare Worker (no VPN needed!)
            self._api_base = worker_url + "/bot"
            self._http = urllib3.PoolManager()
            print(f"[telegram] Using Cloudflare Worker: {worker_url}")
        elif proxy_url:
            # Mode 2: Psiphon proxy (VPN needed)
            self._api_base = API_BASE
            self._http = ProxyManager(
                proxy_url=proxy_url,
                cert_reqs=ssl.CERT_NONE,
                assert_hostname=False,
            )
            print(f"[telegram] Using Psiphon proxy: {proxy_url}")
        else:
            # Mode 3: Direct (may fail in Iran)
            self._api_base = API_BASE
            self._http = urllib3.PoolManager()
            print("[telegram] No proxy/worker configured, connecting directly")

    def _api_url(self, method: str) -> str:
        return f"{self._api_base}{self.token}/{method}"

    def _request(self, method: str, endpoint: str, payload: Optional[Dict] = None) -> Optional[Dict]:
        """Make a request to the Telegram API and return parsed JSON."""
        url = self._api_url(endpoint)
        body = json.dumps(payload).encode("utf-8") if payload else None
        headers = {"Content-Type": "application/json"} if payload else {}
        try:
            resp = self._http.request(
                method.upper(),
                url,
                body=body,
                headers=headers,
                timeout=15.0,
            )
            if resp.status == 200:
                return json.loads(resp.data.decode("utf-8"))
            else:
                print(f"[telegram] HTTP {resp.status} on {endpoint}: {resp.data[:200]}")
                return None
        except Exception as exc:
            print(f"[telegram] Error on {endpoint}: {exc}")
            return None

    def send_message(
        self,
        text: str,
        parse_mode: str = "Markdown",
        buttons: Optional[List[List[Tuple[str, str]]]] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        """Send a message with optional inline keyboard buttons.

        Args:
            text: Message text (Markdown supported).
            parse_mode: 'Markdown' or 'HTML'.
            buttons: Optional inline keyboard buttons.
            chat_id: Specific chat to send to. If None, sends to all configured chat_ids.
        """
        target_ids = [chat_id] if chat_id else self.chat_ids
        for cid in target_ids:
            payload: Dict[str, Any] = {
                "chat_id": cid,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            if buttons:
                payload["reply_markup"] = {
                    "inline_keyboard": _build_inline_keyboard(buttons)
                }
            self._request("POST", "sendMessage", payload)

    def send_message_sync(self, text: str, chat_id: Optional[str] = None) -> None:
        """Synchronous helper (just calls send_message directly)."""
        self.send_message(text, chat_id=chat_id)

    def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: str = "Markdown",
        buttons: Optional[List[List[Tuple[str, str]]]] = None,
    ) -> None:
        """Edit an existing message (e.g. update price without spamming)."""
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": _build_inline_keyboard(buttons)
            }
        self._request("POST", "editMessageText", payload)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        """Respond to a button press (shows a toast notification)."""
        payload = {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": False,
        }
        self._request("POST", "answerCallbackQuery", payload)

    def set_webhook(self, url: str, secret_token: Optional[str] = None) -> Optional[Dict]:
        """Register a webhook URL with Telegram.

        Args:
            url: Public HTTPS URL Telegram will POST updates to (e.g. https://host/webhook).
            secret_token: Optional secret token Telegram will send in the
                X-Telegram-Bot-Api-Secret-Token header (recommended).
        """
        payload: Dict[str, Any] = {"url": url}
        if secret_token:
            payload["secret_token"] = secret_token
        # Drop any pending updates so we don't immediately replay old ones.
        payload["drop_pending_updates"] = True
        result = self._request("POST", "setWebhook", payload)
        if result and result.get("ok"):
            print(f"[telegram] Webhook set to {url}")
        else:
            print(f"[telegram] Failed to set webhook: {result}")
        return result

    def delete_webhook(self) -> Optional[Dict]:
        """Remove any registered webhook (so long-polling works)."""
        return self._request("POST", "deleteWebhook", {"drop_pending_updates": True})

    def get_webhook_info(self) -> Optional[Dict]:
        """Return current webhook info (for diagnostics)."""
        return self._request("POST", "getWebhookInfo", {})

    def set_my_commands(self, commands: List[Tuple[str, str]]) -> None:
        """Set the bot's command menu (shown as /commands in chat)."""
        payload = {
            "commands": [
                {"command": cmd, "description": desc}
                for cmd, desc in commands
            ]
        }
        self._request("POST", "setMyCommands", payload)

    def get_updates(self, timeout: int = 30) -> List[Dict]:
        """Poll for new updates (messages, button clicks, etc.)."""
        payload = {
            "offset": self._last_update_id + 1,
            "timeout": timeout,
        }
        result = self._request("POST", "getUpdates", payload)
        if result and result.get("ok") and result.get("result"):
            updates = result["result"]
            if updates:
                self._last_update_id = updates[-1]["update_id"]
            return updates
        return []

    def send_photo(
        self,
        chat_id: str,
        photo_bytes: Optional[bytes] = None,
        photo_url: Optional[str] = None,
        caption: str = "",
        parse_mode: str = "Markdown",
        buttons: Optional[List[List[Tuple[str, str]]]] = None,
    ) -> None:
        """Send a photo to a chat using multipart/form-data or URL."""
        if photo_url:
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "photo": photo_url,
                "caption": caption,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            if buttons:
                payload["reply_markup"] = {
                    "inline_keyboard": _build_inline_keyboard(buttons)
                }
            self._request("POST", "sendPhoto", payload)
            return

        if not photo_bytes:
            return

        from urllib3.filepost import encode_multipart_formdata

        fields = [
            ("chat_id", str(chat_id)),
            ("caption", caption),
            ("parse_mode", parse_mode),
            ("disable_web_page_preview", "true"),
            ("photo", ("chart.png", photo_bytes, "image/png")),
        ]
        if buttons:
            fields.append((
                "reply_markup",
                json.dumps({"inline_keyboard": _build_inline_keyboard(buttons)}),
            ))

        data, content_type = encode_multipart_formdata(fields)
        url = self._api_url("sendPhoto")
        try:
            resp = self._http.request(
                "POST",
                url,
                body=data,
                headers={"Content-Type": content_type},
                timeout=30.0,
            )
            if resp.status != 200:
                print(f"[telegram] HTTP {resp.status} on sendPhoto: {resp.data[:200]}")
        except Exception as exc:
            print(f"[telegram] Error on sendPhoto: {exc}")

    def start_polling(
        self,
        on_message=None,
        on_callback=None,
        interval: float = 1.0,
    ) -> None:
        """
        Start a background thread that polls for updates.

        Args:
            on_message: Callback(chat_id, text) when a text message is received.
            on_callback: Callback(chat_id, callback_data, callback_query_id) when a button is pressed.
            interval: Seconds between polls.
        """
        if self._running:
            return

        self._running = True

        def _poll_loop():
            while self._running:
                try:
                    updates = self.get_updates(timeout=10)
                    for upd in updates:
                        self._handle_update(upd, on_message, on_callback)
                except Exception as exc:
                    print(f"[telegram] Poll error: {exc}")
                time.sleep(interval)

        self._poll_thread = threading.Thread(target=_poll_loop, daemon=True)
        self._poll_thread.start()
        print("[telegram] Polling started (listening for messages & button clicks)")

    def stop_polling(self) -> None:
        """Stop the background polling thread."""
        self._running = False
        print("[telegram] Polling stopped")

    def _handle_update(self, update: Dict, on_message, on_callback) -> None:
        """Process a single update from Telegram."""
        # Handle callback queries (button clicks)
        if "callback_query" in update:
            cq = update["callback_query"]
            chat_id = str(cq["message"]["chat"]["id"])
            data = cq.get("data", "")
            cq_id = cq["id"]
            if on_callback:
                on_callback(chat_id, data, cq_id)
            return

        # Handle text messages
        if "message" in update:
            msg = update["message"]
            chat_id = str(msg["chat"]["id"])
            text = msg.get("text", "")
            if on_message:
                on_message(chat_id, text)
