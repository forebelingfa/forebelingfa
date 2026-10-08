#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
import tempfile
import time
from typing import Any, Dict, List

import requests
from api import TamilAPIError, get_user_info
from config import DEFAULT_CONFIG
from simple_account_manager import load_accounts

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
        # print(data)
        result["nickname"] = data.get("nickname", "N/A")
        result["gold"] = int(data["gold"])
    except (TamilAPIError, TypeError, ValueError) as exc:
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
