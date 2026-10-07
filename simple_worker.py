from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict

import websocket


SECRET = "uwkeovuoqnpn@13vxck9tjghazhhbrmy"
DEFAULT_WS_URL = "ws://47.84.51.23:9001"


def _room_login_payload(room_id: int, user_id: int, ws_token: str) -> Dict[str, Any]:
    timestamp = int(time.time())
    raw = f"{SECRET}{timestamp}{ws_token}"
    md5str = hashlib.md5(raw.encode()).hexdigest()

    return {
        "body": {
            "DeviceType": 1,
            "EnterType": 0,
            "FuncLevel": 1280,
            "IsSmallDialog": 0,
            "IsVoice": 0,
            "Lang": "id",
            "Md5Str": md5str,
            "RoomId": room_id,
            "TimeMill": timestamp,
            "Token": ws_token,
            "Tourist": 0,
            "UserId": user_id,
            "Version": "2.1.5",
            "Visitor": 0,
            "package_type": "haigou-Android",
        },
        "op": 1001,
        "ver": 1,
    }


def _claim_payload(lucky_bag_id: int) -> Dict[str, Any]:
    return {
        "body": {"ID": lucky_bag_id},
        "op": 2101,
        "ver": 1,
    }


def claim_lucky_bag(account: Dict[str, Any], room_id: int, lucky_bag_id: int, ws_url: str = DEFAULT_WS_URL) -> Dict[str, Any]:
    """Join a room and immediately attempt the first-claim race for a lucky bag.

    The goal is to win the race, so the code is optimized for the shortest path:
    join room -> receive join ACK -> send claim immediately -> return the result.
    """
    user_id = int(account["user_id"])
    ws_token = str(account["ws_token"])
    start_time = time.perf_counter()

    ws = websocket.create_connection(ws_url)
    try:
        ws.send(json.dumps(_room_login_payload(room_id, user_id, ws_token)))

        while True:
            raw_message = ws.recv()
            if not raw_message:
                break

            data = json.loads(raw_message)
            op_code = data.get("op")
            body = data.get("body", {})

            if op_code == 2101:
                lucky_id = body.get("ID")
                code = body.get("Code")
                gold = int(body.get("Gold", 0) or 0)
                err = body.get("ErrStr", "")
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)

                if lucky_id == lucky_bag_id:
                    if code == 0 and gold > 0:
                        return {
                            "ok": True,
                            "lucky_bag_id": lucky_id,
                            "gold": gold,
                            "elapsed_ms": elapsed_ms,
                            "message": "Lucky bag claimed successfully.",
                            "raw": data,
                        }

                    return {
                        "ok": False,
                        "lucky_bag_id": lucky_id,
                        "gold": gold,
                        "elapsed_ms": elapsed_ms,
                        "message": err or f"Claim failed with code={code}",
                        "raw": data,
                    }

            if op_code == 1001:
                # first claim objective: claim immediately after join confirmation
                ws.send(json.dumps(_claim_payload(lucky_bag_id)))
                continue

    finally:
        ws.close()

    return {
        "ok": False,
        "lucky_bag_id": lucky_bag_id,
        "gold": 0,
        "elapsed_ms": int((time.perf_counter() - start_time) * 1000),
        "message": "No claim response received before disconnect.",
        "raw": None,
    }
