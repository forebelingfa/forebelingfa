from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
import tempfile
import time
import uuid
from hashlib import md5
from pathlib import Path
from typing import Any, Dict, List

import requests

from config import DEFAULT_CONFIG
from simple_account_manager import load_accounts

API_SIGNING_SECRET = "5d206b343f87f2ca3a0aa05c58b9a64d"
API_URL = "https://api.taalmil.live/api/member/info"
APP_VERSION = "2.1.5"
TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def generate_sign_from_payload(payload: Dict[str, Any]) -> str:
    filtered = {
        k: v
        for k, v in payload.items()
        if k not in {"CREATOR", "serialVersionUID", "sign"}
    }
    sorted_items = sorted(filtered.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    return md5(f"{param_str}&key={API_SIGNING_SECRET}".encode("utf-8")).hexdigest()


class GoldCheckError(RuntimeError):
    pass


def get_user_info(
    user_id: str | int,
    jwt_token: str,
    timeout: float = 10,
    retries: int = 2,
) -> Dict[str, Any]:
    headers = {
        "User-Agent": APP_VERSION,
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "cache-control": "no-cache",
        "authorization-token": jwt_token.strip(),
    }

    for attempt in range(retries + 1):
        payload = {
            "id": str(user_id),
            "version": "1.0",
            "app_version": APP_VERSION,
            "channel_id": "3",
            "device_id": uuid.uuid4().hex,
            "facility": "1",
            "lang": "id",
            "package_type": "Android-Google",
            "sign": "",
            "time": str(int(time.time())),
            "user_id": str(user_id),
        }
        payload["sign"] = generate_sign_from_payload(payload)

        try:
            response = requests.post(API_URL, json=payload, headers=headers, timeout=timeout)
            if response.status_code in TRANSIENT_HTTP_STATUSES and attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 4))
                continue
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            if attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 4))
                continue
            raise GoldCheckError(f"request failed: {exc}") from exc
        except ValueError as exc:
            raise GoldCheckError("server returned invalid JSON") from exc

        if not isinstance(result, dict):
            raise GoldCheckError("server response was not a JSON object")
        code = result.get("code")
        if str(code) not in {"0", "200"}:
            message = result.get("msg") or result.get("message") or "no error message"
            raise GoldCheckError(f"API code={code}: {message}")

        data = result.get("data")
        if not isinstance(data, dict) or "gold" not in data:
            raise GoldCheckError("successful response did not contain data.gold")
        return result

    raise GoldCheckError("request failed after retries")


def _check_account(account: Dict[str, Any], timeout: float, retries: int) -> Dict[str, Any]:
    user_id = account["user_id"]
    result = {
        "user_id": user_id,
        "nickname": None,
        "gold": None,
        "jwt": account["jwt"],
        "ws_token": account["ws_token"],
        "error": None,
    }
    try:
        info = get_user_info(user_id, account["jwt"], timeout=timeout, retries=retries)
        data = info["data"]
        result["nickname"] = data.get("nickname", "N/A")
        result["gold"] = int(data["gold"])
    except (GoldCheckError, TypeError, ValueError) as exc:
        result["error"] = str(exc)
    return result


def check_gold_from_file(
    file_path: str | Path,
    workers: int = 5,
    timeout: float = 10,
    retries: int = 2,
) -> List[Dict[str, Any]]:
    accounts = load_accounts(file_path)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        results = list(executor.map(lambda account: _check_account(account, timeout, retries), accounts))

    for result in results:
        user_id = result["user_id"]
        if result["error"]:
            print(f"[{user_id}] ERROR {result['error']}")
        else:
            print(f"[{user_id}] {result['nickname']} => gold={result['gold']}")
    return results


def split_accounts(rows: List[Dict[str, Any]], keep_zero_gold: bool = True) -> Dict[str, List[str]]:
    keep: List[str] = []
    move: List[str] = []
    for item in rows:
        line = f"{item['user_id']},{item['ws_token']},{item['jwt']}"
        gold = item.get("gold")
        if gold is None:
            keep.append(line)
        elif (gold == 0) == keep_zero_gold:
            keep.append(line)
        else:
            move.append(line)
    return {"keep": keep, "move": move}


def _write_text_atomically(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines) + ("\n" if lines else "")
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp_name = handle.name
            handle.write(content)
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def write_split_file(
    file_path: str | Path,
    rows: List[Dict[str, Any]],
    keep_zero_gold: bool = True,
) -> Dict[str, int]:
    file_path = Path(file_path)
    result = split_accounts(rows, keep_zero_gold=keep_zero_gold)
    side_suffix = ".rich" if keep_zero_gold else ".zero"
    side_file = file_path.with_suffix(file_path.suffix + side_suffix)
    _write_text_atomically(file_path, result["keep"])
    _write_text_atomically(side_file, result["move"])
    return {"kept": len(result["keep"]), "moved": len(result["move"])}


def write_json_report(path: str | Path, rows: List[Dict[str, Any]]) -> None:
    successful = [row for row in rows if row["gold"] is not None]
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "accounts_checked": len(rows),
        "accounts_succeeded": len(successful),
        "accounts_failed": len(rows) - len(successful),
        "total_gold": sum(row["gold"] for row in successful),
        "accounts": [
            {key: row[key] for key in ("user_id", "nickname", "gold", "error")}
            for row in rows
        ],
    }
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=report_path.parent, delete=False) as handle:
            temp_name = handle.name
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, report_path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tamil version of the Dazz gold-check utility.")
    parser.add_argument("--accounts", default=DEFAULT_CONFIG.account_file, help="Account list in userId,ws_token,jwt format")
    parser.add_argument("--workers", type=int, default=5, help="Maximum parallel account lookups")
    parser.add_argument("--timeout", type=float, default=10, help="Request timeout in seconds")
    parser.add_argument("--retries", type=int, default=2, help="Retries for transient network/server failures")
    parser.add_argument("--json-out", help="Write a credential-free JSON results report to this path")
    parser.add_argument("--keep-zero", action="store_true", help="Keep zero-gold accounts in the original file; move positive-gold accounts to a side file")
    parser.add_argument("--keep-rich", action="store_true", help="Keep rich accounts and move zero-gold accounts out")
    args = parser.parse_args()

    if args.workers < 1 or args.timeout <= 0 or args.retries < 0:
        parser.error("--workers must be positive, --timeout must be positive, and --retries cannot be negative")
    if args.keep_zero and args.keep_rich:
        parser.error("choose only one of --keep-zero or --keep-rich")

    keep_zero_gold = args.keep_zero or not args.keep_rich
    rows = check_gold_from_file(args.accounts, workers=args.workers, timeout=args.timeout, retries=args.retries)
    successful = [row for row in rows if row.get("gold") is not None]
    total_gold = sum(int(row["gold"]) for row in successful)
    failed = len(rows) - len(successful)
    print(f"Total gold across {len(successful)} valid accounts: {total_gold}")
    if failed:
        print(f"Failed accounts: {failed}")

    if args.json_out:
        write_json_report(args.json_out, rows)
        print(f"JSON report written: {args.json_out}")

    if args.keep_zero or args.keep_rich:
        stats = write_split_file(args.accounts, rows, keep_zero_gold=keep_zero_gold)
        print(f"Kept: {stats['kept']} | moved: {stats['moved']}")


if __name__ == "__main__":
    main()
