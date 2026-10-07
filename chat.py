import hashlib
import json
import logging
import time
from typing import Any, Dict

import websocket

from config import DEFAULT_CONFIG
from runtime_state import RuntimeState


logging.basicConfig(level=getattr(logging, DEFAULT_CONFIG.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dazz_debug")


state = RuntimeState.load_from_file(DEFAULT_CONFIG.account_path)
account = state.accounts[DEFAULT_CONFIG.account_index]


def md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def room_login_payload(room_id: int, user_id: int, ws_token: str, secret: str = DEFAULT_CONFIG.secret) -> Dict[str, Any]:
    timestamp = int(time.time())
    raw = f"{secret}{timestamp}{ws_token}"
    return {
        "body": {
            "DeviceType": 1,
            "EnterType": 0,
            "FuncLevel": 1280,
            "IsSmallDialog": 0,
            "IsVoice": 0,
            "Lang": "id",
            "Md5Str": md5_hex(raw),
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


def claim_payload(lucky_bag_id: int) -> Dict[str, Any]:
    return {
        "body": {"ID": lucky_bag_id},
        "op": 2101,
        "ver": 1,
    }


def dump_frame(prefix: str, payload: Any) -> None:
    print(f"{prefix}: {json.dumps(payload, ensure_ascii=False, indent=2)}")


def debug_socket() -> Dict[str, Any]:
    user_id = int(account.user_id)
    ws_token = str(account.ws_token)
    logger.info("connecting %s", DEFAULT_CONFIG.ws_url)
    logger.info("account user_id=%s room_id=%s bag_id=%s", user_id, DEFAULT_CONFIG.room_id, DEFAULT_CONFIG.bag_id)
    state.mark_worker_result(user_id, False, "connecting")

    ws = websocket.create_connection(DEFAULT_CONFIG.ws_url)
    try:
        login_packet = room_login_payload(DEFAULT_CONFIG.room_id, user_id, ws_token)
        state.record_packet("send", login_packet)
        dump_frame("SEND login", login_packet)
        ws.send(json.dumps(login_packet))

        for i in range(20):
            try:
                raw = ws.recv()
            except Exception as exc:
                logger.error("recv failed: %s", exc)
                state.mark_worker_result(user_id, False, str(exc))
                break

            logger.info("raw frame #%s: %s", i + 1, raw)
            try:
                data = json.loads(raw)
            except Exception:
                logger.warning("non-JSON frame received")
                continue

            state.record_packet("recv", data)
            dump_frame("RECV", data)

            if data.get("op") == 1001:
                logger.info("room join ACK received; sending claim immediately")
                pkt = claim_payload(DEFAULT_CONFIG.bag_id)
                state.record_packet("send", pkt)
                dump_frame("SEND claim", pkt)
                ws.send(json.dumps(pkt))
                continue

            if data.get("op") == 2101:
                logger.info("claim response received")
                body = data.get("body", {})
                ok = body.get("Code") == 0
                state.mark_worker_result(user_id, ok, body.get("ErrStr", ""))
                return {
                    "ok": ok,
                    "code": body.get("Code"),
                    "gold": body.get("Gold", 0),
                    "err": body.get("ErrStr", ""),
                    "raw": data,
                }

        return {"ok": False, "code": None, "gold": 0, "err": "No response received", "raw": None}
    finally:
        ws.close()
        logger.info("websocket closed")


def main() -> None:
    result = debug_socket()
    print("\n[SUMMARY]")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n[WORKER STATE]")
    print(json.dumps(state.summary(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
