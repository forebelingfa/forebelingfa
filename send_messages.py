#!/usr/bin/env python3

import argparse
import hashlib
import json
import threading
import time

import websocket

TAMIL_WS_URL = "ws://47.84.51.23:9001"
TAMIL_API_BASE = "https://api.taalmil.live/api"
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


def main():
    parser = argparse.ArgumentParser(description="Tamil websocket room join/send equivalent of dazz/send_messages.py")
    parser.add_argument("--room-id", type=int, required=True)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--token", type=str, required=True)
    parser.add_argument("--bag-id", type=int, default=None, help="Lucky bag ID to claim immediately after join ack")
    parser.add_argument("--max-runtime", type=int, default=300, help="Auto-close after N seconds")
    args = parser.parse_args()

    run_room(
        room_id=args.room_id,
        user_id=args.user_id,
        token=args.token,
        lucky_bag_id=args.bag_id,
        max_runtime=args.max_runtime,
    )


if __name__ == "__main__":
    main()
