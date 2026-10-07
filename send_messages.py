#!/usr/bin/env python3

import argparse
import hashlib
import json
import threading
import time

import websocket

from api import TamilAPIError, get_user_info
from config import DEFAULT_CONFIG
from simple_account_manager import load_accounts

TAMIL_WS_URL = "ws://47.84.51.23:9001"
TAMIL_SECRET = "uwkeovuoqnpn@13vxck9tjghazhhbrmy"


def md5_result(token: str, time_mill: int) -> str:
    raw = f"{TAMIL_SECRET}{time_mill}{token}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def send(ws, payload):
    ws.send(json.dumps(payload, separators=(",", ":")))


def room_login_payload(room_id: int, user_id: int, token: str):
    time_mill = int(time.time() * 1000)
    return {
        "ver": 1,
        "op": 1001,
        "body": {
            "DeviceType": 1,
            "EnterType": 0,
            "FuncLevel": 1280,
            "IsSmallDialog": 0,
            "IsVoice": 0,
            "Lang": "id",
            "Md5Str": md5_result(token, time_mill),
            "RoomId": room_id,
            "TimeMill": time_mill,
            "Token": token,
            "Tourist": 0,
            "UserId": user_id,
            "Version": "2.1.5",
            "Visitor": 0,
            "package_type": "haigou-Android",
        },
    }


def claim_payload(lucky_bag_id: int):
    return {
        "ver": 1,
        "op": 2101,
        "body": {"ID": lucky_bag_id},
    }


def resolve_live_room_id(live_user_id: int, jwt_token: str) -> int:
    try:
        response = get_user_info(live_user_id, jwt_token)
    except TamilAPIError as exc:
        raise RuntimeError(f"Could not look up live user {live_user_id}: {exc}") from exc

    data = response.get("data", {})
    room_id = data.get("room_id") if isinstance(data, dict) else None
    try:
        room_id = int(room_id)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"No active room found for user {live_user_id}; the profile returned no room ID."
        ) from exc

    if room_id <= 0:
        raise RuntimeError(
            f"No active room found for user {live_user_id}; the profile returned room ID {room_id}."
        )
    return room_id


def make_ws_client(room_id: int, user_id: int, token: str, lucky_bag_id: int | None = None, max_runtime: int = 300):
    def on_open(ws):
        ws.send(json.dumps(room_login_payload(room_id, user_id, token), separators=(",", ":")))

        def heartbeat():
            counter = 1
            while True:
                try:
                    payload = {
                        "ver": 1,
                        "op": 1002,
                        "body": {
                            "ChatType": 0,
                            "Content": str(counter),
                            "DUserID": 0,
                            "SUserId": user_id,
                            "SNickName": "",
                            "Gold": 0,
                            "ConsumeLevel": 91,
                        },
                    }
                    send(ws, payload)
                    counter += 1
                    time.sleep(10)
                except Exception:
                    break

        threading.Thread(target=heartbeat, daemon=True).start()

        def watchdog():
            start = time.time()
            while True:
                if (time.time() - start) > max_runtime:
                    try:
                        ws.close()
                    except Exception:
                        pass
                    break
                time.sleep(1)

        threading.Thread(target=watchdog, daemon=True).start()

    def on_message(ws, message):
        try:
            data = json.loads(message)
        except Exception:
            print(f"[WS-{room_id}] raw non-json: {message}")
            return

        body = data.get("body", {})
        op = data.get("op")

        if op == 1001:
            if lucky_bag_id is not None:
                send(ws, claim_payload(lucky_bag_id))
            return

        if op == 2101:
            print(json.dumps({"room_id": room_id, "op": op, "body": body}, ensure_ascii=False, indent=2))
            if body.get("Code") in (0, 200):
                ws.close()
            return

        if op > 2000 and body.get("ID"):
            send(ws, {"ver": 1, "op": 2101, "body": {"ID": body["ID"]}})
            return

    def on_error(ws, error):
        print(f"[WS-{room_id}] error: {error}")

    def on_close(ws, code, msg):
        print(f"[WS-{room_id}] closed: {code} {msg}")

    return websocket.WebSocketApp(
        TAMIL_WS_URL,
        header=["User-Agent: okhttp/4.8.1", "Accept-Encoding: gzip"],
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )


def run_room(room_id: int, user_id: int, token: str, lucky_bag_id: int | None = None, max_runtime: int = 300):
    if not token:
        raise ValueError("token is required")
    ws = make_ws_client(room_id, user_id, token, lucky_bag_id=lucky_bag_id, max_runtime=max_runtime)
    ws.run_forever(ping_interval=30, ping_timeout=10)


def run_live_user(
    live_user_id: int,
    account: dict,
    lucky_bag_id: int | None = None,
    max_runtime: int = 300,
) -> int:
    room_id = resolve_live_room_id(live_user_id, str(account["jwt"]))
    print(f"Live user {live_user_id} is in room {room_id}; joining with account {account['user_id']}.")
    run_room(
        room_id=room_id,
        user_id=int(account["user_id"]),
        token=str(account["ws_token"]),
        lucky_bag_id=lucky_bag_id,
        max_runtime=max_runtime,
    )
    return room_id


def main():
    parser = argparse.ArgumentParser(description="Join the room of a live Tamil user and handle LuckyBag messages.")
    parser.add_argument("--live-user-id", type=int, required=True, help="User ID of the live host; room ID is resolved from their profile")
    parser.add_argument("--accounts", default=DEFAULT_CONFIG.account_file, help="Account file in userId,ws_token,jwt format")
    parser.add_argument("--account-index", type=int, default=DEFAULT_CONFIG.account_index, help="Zero-based account used to join and look up the live room")
    parser.add_argument("--bag-id", type=int, default=None, help="Lucky bag ID to claim immediately after join ack")
    parser.add_argument("--max-runtime", type=int, default=300, help="Auto-close after N seconds")
    args = parser.parse_args()

    accounts = load_accounts(args.accounts)
    if args.account_index < 0 or args.account_index >= len(accounts):
        parser.error(f"--account-index must be between 0 and {len(accounts) - 1}")
    if args.max_runtime <= 0:
        parser.error("--max-runtime must be positive")

    try:
        run_live_user(
            live_user_id=args.live_user_id,
            account=accounts[args.account_index],
            lucky_bag_id=args.bag_id,
            max_runtime=args.max_runtime,
        )
    except RuntimeError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
