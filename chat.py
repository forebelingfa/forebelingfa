#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

import websocket
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from api import TamilAPIError, get_user_info
from config import DEFAULT_CONFIG
from send_messages import TAMIL_WS_URL, resolve_live_room_id, room_login_payload
from simple_account_manager import load_accounts


USER_INFO_OPS = {1001, 1011, 1064, 1085, 1066}


def chat_payload(
    user_id: int,
    nickname: str,
    gold: int,
    level: int,
    text: str,
    recipient_id: int = 0,
) -> Dict[str, Any]:
    return {
        "ver": 1,
        "op": 1002,
        "body": {
            "ChatType": 0,
            "Content": text,
            "DUserID": recipient_id,
            "SUserId": user_id,
            "SNickName": nickname,
            "Gold": gold,
            "ConsumeLevel": level,
        },
    }


class TamilChatClient:
    def __init__(
        self,
        room_id: int,
        account: Dict[str, Any],
        nickname: str,
        gold: int,
        level: int,
        max_runtime: float = 0,
        ws_url: str = TAMIL_WS_URL,
    ) -> None:
        self.room_id = room_id
        self.account = account
        self.user_id = int(account["user_id"])
        self.token = str(account["ws_token"])
        self.nickname = nickname
        self.gold = gold
        self.level = level
        self.max_runtime = max_runtime
        self.ws_url = ws_url
        self.stop_event = threading.Event()
        self.connected_event = threading.Event()
        self.ws_lock = threading.Lock()
        self.active_ws: Optional[websocket.WebSocketApp] = None
        self.user_cache: Dict[str, Dict[str, Any]] = {}
        self.prompt = PromptSession()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _user_key(user_id: Any) -> Optional[str]:
        return None if user_id in (None, "") else str(user_id)

    def _update_user(self, body: Dict[str, Any]) -> None:
        user_key = self._user_key(body.get("UserId") or body.get("SUserId"))
        if user_key is None:
            return

        user = self.user_cache.setdefault(user_key, {})
        nickname = body.get("NickName") or body.get("UserName") or body.get("SNickName")
        gold = body.get("SGold")
        if gold is None:
            gold = body.get("Gold")
        level = body.get("Level") or body.get("GameLevel") or body.get("ConsumeLevel") or body.get("SLevel")
        if nickname:
            user["nickname"] = nickname
        if gold is not None:
            user["gold"] = gold
        if level is not None:
            user["level"] = level

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        try:
            payload = room_login_payload(self.room_id, self.user_id, self.token)
            ws.send(json.dumps(payload, separators=(",", ":")))
            self.connected_event.set()
            print(f"[{self._timestamp()}] Connected to room {self.room_id} as {self.nickname} ({self.user_id}).")
        except Exception as exc:
            print(f"[{self._timestamp()}] Could not send room join: {exc}")
            ws.close()

    def _on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        try:
            data = json.loads(message)
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return

        body = data.get("body", {})
        if not isinstance(body, dict):
            return

        op = data.get("op")
        if op in USER_INFO_OPS:
            self._update_user(body)
            return
        if op != 1002:
            return

        sender_id = body.get("SUserId")
        sender_key = self._user_key(sender_id)
        if sender_key is None or sender_key == str(self.user_id):
            return

        text = body.get("Content")
        if not isinstance(text, str) or not text:
            return

        self._update_user(body)
        user = self.user_cache.get(sender_key, {})
        nickname = user.get("nickname") or str(sender_id)
        gold = user.get("gold", "?")
        level = user.get("level", "?")
        addressed_to_me = self._user_key(body.get("DUserID")) == str(self.user_id)
        mention = " @YOU" if addressed_to_me else ""
        print(f"[{self._timestamp()}]{mention} {nickname} (Lv.{level}, gold {gold}): {text}")

    def _on_error(self, ws: websocket.WebSocketApp, error: Any) -> None:
        print(f"[{self._timestamp()}] WebSocket error: {error}")

    def _on_close(self, ws: websocket.WebSocketApp, code: Any, reason: Any) -> None:
        self.connected_event.clear()
        print(f"[{self._timestamp()}] Disconnected from room {self.room_id} ({code}: {reason}).")

    def _send(self, payload: Dict[str, Any]) -> None:
        with self.ws_lock:
            ws = self.active_ws
        if ws is None or not self.connected_event.is_set():
            print("Not connected; message was not sent.")
            return
        try:
            ws.send(json.dumps(payload, separators=(",", ":")))
        except Exception as exc:
            print(f"Send failed: {exc}")

    def _handle_input(self) -> None:
        print("Commands: /to USER_ID MESSAGE, /like, /help, /quit")
        with patch_stdout(raw=True):
            while not self.stop_event.is_set():
                try:
                    text = self.prompt.prompt("You> ").strip()
                except (EOFError, KeyboardInterrupt):
                    self.stop_event.set()
                    break

                if not text:
                    continue
                command = text.lower()
                if command in {"/quit", "q"}:
                    self.stop_event.set()
                    with self.ws_lock:
                        ws = self.active_ws
                    if ws is not None:
                        ws.close()
                    break
                if command == "/help":
                    print("Enter a message to send it to the room. Use /to USER_ID MESSAGE for a direct message, /like for one like, or /quit to exit.")
                    continue
                if command == "/like":
                    self._send({"ver": 1, "op": 1017, "body": {}})
                    continue
                if command.startswith("/to "):
                    parts = text.split(maxsplit=2)
                    if len(parts) != 3:
                        print("Usage: /to USER_ID MESSAGE")
                        continue
                    try:
                        recipient_id = int(parts[1])
                    except ValueError:
                        print("USER_ID must be an integer.")
                        continue
                    message_text = parts[2].strip()
                    if message_text:
                        self._send(chat_payload(
                            self.user_id,
                            self.nickname,
                            self.gold,
                            self.level,
                            message_text,
                            recipient_id=recipient_id,
                        ))
                    continue
                if text.startswith("/"):
                    print("Unknown command. Use /help to see available commands.")
                    continue

                self._send(chat_payload(
                    self.user_id,
                    self.nickname,
                    self.gold,
                    self.level,
                    text,
                ))
                print(f"[{self._timestamp()}] You: {text}")

    def _stop_after_runtime(self) -> None:
        print("Maximum chat runtime reached.")
        self.stop_event.set()
        with self.ws_lock:
            ws = self.active_ws
        if ws is not None:
            ws.close()

    def run(self) -> None:
        input_thread = threading.Thread(target=self._handle_input, daemon=True)
        input_thread.start()
        runtime_timer = None
        if self.max_runtime:
            runtime_timer = threading.Timer(self.max_runtime, self._stop_after_runtime)
            runtime_timer.daemon = True
            runtime_timer.start()

        while not self.stop_event.is_set():
            ws = websocket.WebSocketApp(
                self.ws_url,
                header=["User-Agent: okhttp/4.8.1", "Accept-Encoding: gzip"],
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            with self.ws_lock:
                self.active_ws = ws

            try:
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as exc:
                print(f"[{self._timestamp()}] Connection ended: {exc}")
            finally:
                self.connected_event.clear()
                with self.ws_lock:
                    if self.active_ws is ws:
                        self.active_ws = None

            if not self.stop_event.is_set():
                print("Reconnecting in 3 seconds...")
                self.stop_event.wait(3)

        if runtime_timer is not None:
            runtime_timer.cancel()


def _account_profile(account: Dict[str, Any]) -> Dict[str, Any]:
    try:
        response = get_user_info(account["user_id"], account["jwt"])
        data = response.get("data", {})
        if isinstance(data, dict):
            return data
    except TamilAPIError as exc:
        print(f"Profile lookup failed; using account ID as nickname: {exc}")
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive Tamil room chat client.")
    parser.add_argument("--live-user-id", type=int, required=True, help="Live host user ID; its active room is resolved automatically")
    parser.add_argument("--accounts", default=DEFAULT_CONFIG.account_file, help="Account file in userId,ws_token,jwt format")
    parser.add_argument("--account-index", type=int, default=DEFAULT_CONFIG.account_index, help="Zero-based account used to join the room")
    parser.add_argument("--max-runtime", type=float, default=0, help="Optional maximum runtime in seconds; 0 runs until /quit")
    args = parser.parse_args()

    if args.max_runtime < 0:
        parser.error("--max-runtime cannot be negative")

    accounts = load_accounts(args.accounts)
    if args.account_index < 0 or args.account_index >= len(accounts):
        parser.error(f"--account-index must be between 0 and {len(accounts) - 1}")

    account = accounts[args.account_index]
    try:
        room_id = resolve_live_room_id(args.live_user_id, account["jwt"])
    except RuntimeError as exc:
        parser.error(str(exc))

    profile = _account_profile(account)
    nickname = str(profile.get("nickname") or account["user_id"])
    gold = int(profile.get("gold") or 0)
    level = int(profile.get("rlevel") or profile.get("level") or 0)
    print(f"Resolved live user {args.live_user_id} to room {room_id}.")

    TamilChatClient(
        room_id=room_id,
        account=account,
        nickname=nickname,
        gold=gold,
        level=level,
        max_runtime=args.max_runtime,
    ).run()


if __name__ == "__main__":
    main()
