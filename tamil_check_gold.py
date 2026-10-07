from __future__ import annotations

import argparse
import json
import time
import uuid
from hashlib import md5
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from config import DEFAULT_CONFIG
from simple_account_manager import load_accounts


def generate_sign_from_payload(payload: Dict[str, Any]) -> str:
    secret_key = DEFAULT_CONFIG.secret
    filtered = {
        k: v
        for k, v in payload.items()
        if k not in {"CREATOR", "serialVersionUID", "sign"}
    }
    sorted_items = sorted(filtered.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    return md5(f"{param_str}&key={secret_key}".encode("utf-8")).hexdigest()


def _endpoint_candidates() -> List[str]:
    return [
        "https://api.taalmil.live/api/member/info",
        "https://api.taalmil.live/api/v1/member/info",
        "https://api.taalmil.live/api/user/info",
        "https://api.taalmil.live/api/member/info/",
    ]


def _header_variants(jwt_token: str) -> List[Dict[str, str]]:
    token = jwt_token.strip()
    return [
        {
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "gzip",
            "Content-Type": "application/json; charset=UTF-8",
            "encrypt-type": "1",
            "cache-control": "no-cache",
            "authorization-token": token,
        },
        {
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "gzip",
            "Content-Type": "application/json; charset=UTF-8",
            "encrypt-type": "1",
            "cache-control": "no-cache",
            "Authorization-token": token,
        },
        {
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "gzip",
            "Content-Type": "application/json; charset=UTF-8",
            "encrypt-type": "1",
            "cache-control": "no-cache",
            "Authorization": f"Bearer {token}",
        },
        {
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "gzip",
            "Content-Type": "application/json; charset=UTF-8",
            "encrypt-type": "1",
            "cache-control": "no-cache",
            "Token": token,
        },
    ]


def get_user_info(user_id: str | int, jwt_token: str, timeout: int = 10) -> Dict[str, Any]:
    payloads = [
        {
            "id": str(user_id),
            "version": "1.0",
            "app_version": "2.1.5",
            "channel_id": "3",
            "device_id": str(uuid.uuid4()).replace("-", ""),
            "facility": "1",
            "lang": "id",
            "package_type": "Android-Google",
            "sign": "",
            "time": str(int(time.time())),
            "user_id": str(user_id),
        },
        {
            "id": str(user_id),
            "user_id": str(user_id),
            "version": "1.0",
            "app_version": "2.1.5",
            "channel_id": "3",
            "device_id": str(uuid.uuid4()).replace("-", ""),
            "facility": "1",
            "lang": "id",
            "package_type": "Android-Google",
            "time": str(int(time.time())),
        },
    ]

    last_error = {"code": -1, "msg": "user info request failed", "data": {}}
    for payload in payloads:
        payload = dict(payload)
        payload["sign"] = generate_sign_from_payload(payload)
        for url in _endpoint_candidates():
            for headers in _header_variants(jwt_token):
                try:
                    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
                    try:
                        payload_json = response.json()
                    except ValueError:
                        payload_json = {"code": -1, "msg": response.text, "data": {}}

                    if isinstance(payload_json, dict):
                        if payload_json.get("code") in (0, 200):
                            return payload_json
                        last_error = payload_json
                except Exception as exc:
                    last_error = {"code": -1, "msg": str(exc), "data": {}}

    return {"code": last_error.get("code", -1), "msg": last_error.get("msg", "user info request failed"), "data": {}}


def check_gold_from_file(file_path: str | Path) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    accounts = load_accounts(file_path)

    for account in accounts:
        user_id = account["user_id"]
        jwt_token = account["jwt"]
        info = get_user_info(user_id, jwt_token)
        code = info.get("code") if isinstance(info, dict) else None
        data = info.get("data", {}) if isinstance(info, dict) else {}

        if code not in (0, 200):
            msg = info.get("msg", "unknown api error")
            print(f"[{user_id}] API ERROR code={code} msg={msg}")
            results.append({
                "user_id": user_id,
                "nickname": "ERROR",
                "gold": None,
                "jwt": jwt_token,
                "ws_token": account["ws_token"],
                "code": code,
                "msg": msg,
            })
            continue

        gold = int(data.get("gold", 0) or 0)
        nick = data.get("nickname", "N/A")
        results.append({
            "user_id": user_id,
            "nickname": nick,
            "gold": gold,
            "jwt": jwt_token,
            "ws_token": account["ws_token"],
            "code": code,
            "msg": info.get("msg", "ok"),
        })
        print(f"[{user_id}] {nick} => gold={gold}")

    return results


def split_accounts(file_path: str | Path, keep_zero_gold: bool = True) -> Dict[str, List[str]]:
    rows = check_gold_from_file(file_path)
    lines = []
    for item in rows:
        line = f"{item['user_id']},{item['ws_token']},{item['jwt']}"
        lines.append(line)

    if keep_zero_gold:
        keep = [line for line, item in zip(lines, rows) if item["gold"] == 0]
        move = [line for line, item in zip(lines, rows) if item["gold"] > 0]
    else:
        keep = [line for line, item in zip(lines, rows) if item["gold"] > 0]
        move = [line for line, item in zip(lines, rows) if item["gold"] == 0]

    return {"keep": keep, "move": move}


def write_split_file(file_path: str | Path, keep_zero_gold: bool = True) -> Dict[str, int]:
    file_path = Path(file_path)
    result = split_accounts(file_path, keep_zero_gold=keep_zero_gold)
    keep_file = file_path
    move_file = file_path.with_suffix(file_path.suffix + ".rich")

    if result["keep"]:
        keep_file.write_text("\n".join(result["keep"]) + "\n", encoding="utf-8")
    else:
        keep_file.write_text("", encoding="utf-8")

    if result["move"]:
        move_file.write_text("\n".join(result["move"]) + "\n", encoding="utf-8")
    else:
        move_file.write_text("", encoding="utf-8")

    return {
        "kept": len(result["keep"]),
        "moved": len(result["move"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Tamil version of the Dazz gold-check utility.")
    parser.add_argument("--accounts", default=DEFAULT_CONFIG.account_file, help="Account list in userId,ws_token,jwt format")
    parser.add_argument("--keep-zero", action="store_true", help="Keep zero-gold accounts in the original file; move positive-gold accounts to a side file")
    parser.add_argument("--keep-rich", action="store_true", help="Keep rich accounts and move zero-gold accounts out")
    parser.add_argument("--probe", action="store_true", help="Print the exact API probe/result for the first account and exit")
    args = parser.parse_args()

    if args.probe:
        accounts = load_accounts(args.accounts)
        first = accounts[0]
        probe = get_user_info(first["user_id"], first["jwt"])
        print(json.dumps({
            "user_id": first["user_id"],
            "endpoint_probe": probe,
        }, ensure_ascii=False, indent=2))
        return

    keep_zero_gold = args.keep_zero or not args.keep_rich
    rows = check_gold_from_file(args.accounts)
    successful = [row for row in rows if row.get("gold") is not None]
    total_gold = sum(int(row["gold"]) for row in successful)
    failed = len(rows) - len(successful)
    print(f"Total gold across {len(successful)} valid accounts: {total_gold}")
    if failed:
        print(f"Failed accounts: {failed}")

    if args.keep_zero or args.keep_rich:
        stats = write_split_file(args.accounts, keep_zero_gold=keep_zero_gold)
        print(f"Kept: {stats['kept']} | moved: {stats['moved']}")


if __name__ == "__main__":
    main()
