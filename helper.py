#!/usr/bin/env python3
"""Tamil account-file helpers built on the verified app API.

Dazz H5 task/sign and password-reset routes are not available on the Tamil API
host, so those workflows are deliberately not exposed here.
"""

from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, List, Optional

from api import TamilAPIError, generate_sign_from_payload, get_user_info, login_tamil
from simple_account_manager import load_accounts


def decode_jwt_claims(token: str) -> Optional[Dict[str, Any]]:
    """Decode JWT claims locally; this does not verify the token signature."""
    if not token:
        return None
    token = token.removeprefix("Bearer ").strip()
    parts = token.split(".")
    if len(parts) < 2:
        return None
    try:
        encoded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return claims if isinstance(claims, dict) else None


def decode_jwt_userid(token: str) -> Optional[str]:
    """Read a user ID claim from a JWT without verifying its signature."""
    claims = decode_jwt_claims(token)
    if claims is None:
        return None
    for key in ("userId", "user_id", "uid", "id", "sub", "userid"):
        if claims.get(key) not in (None, ""):
            return str(claims[key])
    return None


def _load_records(path: str | Path) -> List[Dict[str, Any]]:
    file_path = Path(path)
    if not file_path.is_file():
        return []
    raw_lines = [
        line.rstrip("\r\n")
        for line in file_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not raw_lines:
        return []
    accounts = load_accounts(file_path)
    return [{**account, "_line": raw_lines[index]} for index, account in enumerate(accounts)]


def _write_lines_atomically(path: str | Path, lines: List[str]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines) + ("\n" if lines else "")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False
        ) as handle:
            temporary_path = handle.name
            handle.write(content)
        os.replace(temporary_path, target)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _append_unique_lines(path: str | Path, lines: List[str]) -> None:
    target = Path(path)
    existing = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    seen = set(existing)
    for line in lines:
        if line not in seen:
            existing.append(line)
            seen.add(line)
    _write_lines_atomically(target, existing)


def _check_one(account: Dict[str, Any]) -> Dict[str, Any]:
    claims = decode_jwt_claims(account["jwt"])
    claim_user_id = decode_jwt_userid(account["jwt"])
    expiration = claims.get("exp") if claims else None
    try:
        expired = expiration is not None and int(expiration) <= int(time.time())
    except (TypeError, ValueError):
        expired = True

    if claims is None:
        jwt_claim_status = "malformed"
    elif claim_user_id != str(account["user_id"]):
        jwt_claim_status = "user_id_mismatch"
    elif expired:
        jwt_claim_status = "expired_or_invalid_exp"
    else:
        jwt_claim_status = "claims_ok_unverified"

    result: Dict[str, Any] = {
        "user_id": account["user_id"],
        "_line": account["_line"],
        "jwt_claim_status": jwt_claim_status,
        "profile": None,
        "gold": None,
        "level": None,
        "error": None,
    }
    try:
        response = get_user_info(account["user_id"], account["jwt"])
        profile = response["data"]
        result["profile"] = profile
        result["gold"] = int(profile["gold"])
        level = profile.get("level")
        result["level"] = int(level) if level not in (None, "") else 0
    except (TamilAPIError, KeyError, TypeError, ValueError) as exc:
        result["error"] = str(exc)
    return result


def _check_many(accounts: List[Dict[str, Any]], max_workers: int) -> List[Dict[str, Any]]:
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(_check_one, accounts))


def _response_for(result: Dict[str, Any]) -> Dict[str, Any]:
    if result["error"]:
        return {"code": -1, "message": result["error"], "data": None}
    return {"code": 0, "data": result["profile"]}


def _remove_lines(file_path: str | Path, removed: set[str]) -> int:
    if not removed:
        return 0
    path = Path(file_path)
    original = path.read_text(encoding="utf-8").splitlines()
    retained = [line for line in original if line not in removed]
    _write_lines_atomically(path, retained)
    return len(original) - len(retained)


def inspect_account_file_concurrent(
    token_file: str,
    max_workers: int = 5,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Inspect JWT claims and public profile availability separately.

    Tamil member/info returns public profiles even without a valid JWT, so its
    response cannot establish whether the account is authenticated.
    """
    accounts = _load_records(token_file)
    if limit is not None:
        accounts = accounts[:max(0, limit)]
    if not accounts:
        return []

    results = _check_many(accounts, max_workers)
    for result in results:
        profile_state = "available" if result["error"] is None else f"lookup_error: {result['error']}"
        print(f"[{result['user_id']}] jwt_claims={result['jwt_claim_status']} profile={profile_state}")
    return [
        {
            "user_id": result["user_id"],
            "jwt_claim_status": result["jwt_claim_status"],
            "profile_available": result["error"] is None,
            "error": result["error"],
        }
        for result in results
    ]


def check_user_level_file_concurrent(
    token_file: str,
    out_file: Optional[str] = None,
    level_threshold: int = 3,
    max_workers: int = 5,
    limit: Optional[int] = None,
    remove_from_source: bool = False,
) -> List[tuple[int, int, Optional[int], Dict[str, Any]]]:
    """Check profile levels; only successful high-level records are moved."""
    accounts = _load_records(token_file)
    if limit is not None:
        accounts = accounts[:max(0, limit)]
    results = _check_many(accounts, max_workers)
    selected = [result for result in results if result["error"] is None and result["level"] > level_threshold]

    if out_file and selected:
        _append_unique_lines(out_file, [result["_line"] for result in selected])
    removed_count = 0
    if remove_from_source and selected:
        removed_count = _remove_lines(token_file, {result["_line"] for result in selected})

    output = []
    for index, result in enumerate(results):
        level = result["level"] if result["error"] is None else None
        output.append((index, result["user_id"], level, _response_for(result)))
        if result["error"]:
            print(f"[{result['user_id']}] ERROR {result['error']}")
        else:
            print(f"[{result['user_id']}] level={level}")
    if removed_count:
        print(f"Moved {removed_count} accounts from {token_file} to {out_file}")
    return output


def check_gold_file_concurrent(
    token_file: str,
    output_file: Optional[str] = None,
    max_workers: int = 5,
    limit: Optional[int] = None,
    transfer: bool = False,
    stotal_gold: int = 0,
    gold_threshold: Optional[int] = None,
    move_to_file: Optional[str] = None,
    remove_from_source: bool = False,
) -> List[Dict[str, Any]]:
    """Check balances via Tamil member-info; failed checks are never counted as zero."""
    accounts = _load_records(token_file)
    if limit is not None:
        accounts = accounts[:max(0, limit)]

    results: List[Dict[str, Any]] = []
    if transfer:
        total_gold = 0
        for account in accounts:
            result = _check_one(account)
            if result["error"] is None:
                total_gold += result["gold"]
            results.append(result)
            if result["error"] is None and total_gold >= stotal_gold:
                break
    else:
        results = _check_many(accounts, max_workers)

    successful = [result for result in results if result["error"] is None]
    for result in results:
        if result["error"]:
            print(f"[{result['user_id']}] ERROR {result['error']}")
        else:
            nickname = result["profile"].get("nickname", "N/A")
            print(f"[{result['user_id']}] {nickname} => gold={result['gold']}")

    if output_file:
        lines = [
            json.dumps(
                {
                    "user_id": result["user_id"],
                    "gold": result["gold"],
                    "nickname": result["profile"].get("nickname") if result["profile"] else None,
                    "error": result["error"],
                },
                ensure_ascii=False,
            )
            for result in results
        ]
        _append_unique_lines(output_file, lines)

    selected = []
    if gold_threshold is not None and move_to_file:
        selected = [result for result in successful if result["gold"] > gold_threshold]
        if selected:
            _append_unique_lines(move_to_file, [result["_line"] for result in selected])
    if remove_from_source and selected:
        removed_count = _remove_lines(token_file, {result["_line"] for result in selected})
        print(f"Moved {removed_count} accounts from {token_file} to {move_to_file}")

    print(f"Checked {len(results)} accounts; {len(successful)} succeeded; total gold={sum(r['gold'] for r in successful)}")
    return [
        {
            "user_id": result["user_id"],
            "nickname": result["profile"].get("nickname") if result["profile"] else None,
            "gold": result["gold"],
            "error": result["error"],
        }
        for result in results
    ]


def dedupe_by_userid(input_path: str, output_path: str) -> int:
    """Write the last account line for each user ID, preserving final-line order."""
    source = Path(input_path)
    lines = source.read_text(encoding="utf-8").splitlines()
    last_index: Dict[str, int] = {}
    for index, line in enumerate(lines):
        if line.strip():
            user_id = line.split(",", 1)[0].strip()
            last_index[user_id] = index
    deduplicated = [line for index, line in enumerate(lines) if line.strip() and last_index[line.split(",", 1)[0].strip()] == index]
    _write_lines_atomically(output_path, deduplicated)
    return len(deduplicated)


def merge_account_files(input_paths: List[str], output_path: str) -> int:
    """Merge Tamil account lists and retain the last record per user ID."""
    merged: Dict[int, Dict[str, Any]] = {}
    for path in input_paths:
        for account in _load_records(path):
            merged[int(account["user_id"])] = account
    output_lines = [
        f"{account['user_id']},{account['ws_token']},{account['jwt']}"
        for account in merged.values()
    ]
    _write_lines_atomically(output_path, output_lines)
    return len(output_lines)


def generate_accounts_file(
    credentials_file: str | Path,
    output_file: str | Path = "accounts.txt",
) -> int:
    """Log in credentials from ``userId,password`` lines and write ``userId,ws_token,jwt``."""
    source = Path(credentials_file)
    lines = source.read_text(encoding="utf-8").splitlines()
    account_lines = []

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        user_id_raw, separator, password = line.partition(",")
        if not separator or not user_id_raw.strip() or not password.strip():
            raise ValueError(
                f"Invalid credentials in {source} at line {line_number}: "
                "expected 'userId,password'"
            )
        try:
            user_id = int(user_id_raw.strip())
        except ValueError as exc:
            raise ValueError(
                f"Invalid user ID in {source} at line {line_number}"
            ) from exc

        try:
            response = login_tamil(user_id, password.strip())
        except TamilAPIError as exc:
            raise RuntimeError(
                f"Login failed for user {user_id} at line {line_number}: {exc}"
            ) from exc

        if str(response.get("code")) not in {"0", "200"}:
            message = response.get("msg") or response.get("message") or "no error message"
            raise RuntimeError(
                f"Login failed for user {user_id} at line {line_number}: "
                f"API code={response.get('code', 'missing')}: {message}"
            )

        data = response.get("data")
        if not isinstance(data, dict):
            raise RuntimeError(
                f"Login response for user {user_id} at line {line_number} "
                "did not contain account data"
            )
        ws_token = data.get("token")
        jwt = data.get("jwt_authorization_token")
        if not isinstance(ws_token, str) or not ws_token:
            raise RuntimeError(f"Login response for user {user_id} did not contain a websocket token")
        if not isinstance(jwt, str) or not jwt:
            raise RuntimeError(f"Login response for user {user_id} did not contain a JWT")
        if "," in ws_token or "," in jwt:
            raise RuntimeError(
                f"Login response for user {user_id} contains a comma in a token"
            )

        account_lines.append(f"{user_id},{ws_token},{jwt}")

    if not account_lines:
        raise ValueError(f"No credentials found in {source}")

    _write_lines_atomically(output_file, account_lines)
    return len(account_lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tamil account helper utilities")
    commands = parser.add_subparsers(dest="command", required=True)

    credentials_parser = commands.add_parser(
        "generate-accounts",
        help="Log in userId,password credentials and write Rust-compatible account rows",
    )
    credentials_parser.add_argument("credentials", help="Input file with userId,password lines")
    credentials_parser.add_argument("--output", default="accounts.txt")

    status_parser = commands.add_parser("inspect-accounts", help="Inspect JWT claims and profile lookup separately")
    status_parser.add_argument("accounts")
    status_parser.add_argument("--workers", type=int, default=5)
    status_parser.add_argument("--limit", type=int)

    gold_parser = commands.add_parser("check-gold", help="Check balances for Tamil accounts")
    gold_parser.add_argument("accounts")
    gold_parser.add_argument("--workers", type=int, default=5)
    gold_parser.add_argument("--limit", type=int)
    gold_parser.add_argument("--jsonl")
    gold_parser.add_argument("--threshold", type=int)
    gold_parser.add_argument("--move-to")
    gold_parser.add_argument("--remove-moved", action="store_true")

    level_parser = commands.add_parser("check-level", help="Check profile levels")
    level_parser.add_argument("accounts")
    level_parser.add_argument("--threshold", type=int, default=3)
    level_parser.add_argument("--workers", type=int, default=5)
    level_parser.add_argument("--limit", type=int)
    level_parser.add_argument("--move-to")
    level_parser.add_argument("--remove-moved", action="store_true")

    dedupe_parser = commands.add_parser("dedupe", help="Dedupe a list by user ID")
    dedupe_parser.add_argument("input")
    dedupe_parser.add_argument("output")

    merge_parser = commands.add_parser("merge", help="Merge account lists and dedupe by user ID")
    merge_parser.add_argument("output")
    merge_parser.add_argument("inputs", nargs="+")

    args = parser.parse_args()
    if getattr(args, "workers", 1) < 1:
        parser.error("--workers must be positive")
    if getattr(args, "limit", None) is not None and args.limit < 0:
        parser.error("--limit cannot be negative")

    if args.command == "generate-accounts":
        count = generate_accounts_file(args.credentials, args.output)
        print(f"Wrote credentials for {count} accounts to {args.output}")
    elif args.command == "inspect-accounts":
        inspect_account_file_concurrent(
            args.accounts,
            max_workers=args.workers,
            limit=args.limit,
        )
    elif args.command == "check-gold":
        check_gold_file_concurrent(
            args.accounts,
            output_file=args.jsonl,
            max_workers=args.workers,
            limit=args.limit,
            gold_threshold=args.threshold,
            move_to_file=args.move_to,
            remove_from_source=args.remove_moved,
        )
    elif args.command == "check-level":
        check_user_level_file_concurrent(
            args.accounts,
            out_file=args.move_to,
            level_threshold=args.threshold,
            max_workers=args.workers,
            limit=args.limit,
            remove_from_source=args.remove_moved,
        )
    elif args.command == "dedupe":
        print(f"Wrote {dedupe_by_userid(args.input, args.output)} unique users")
    elif args.command == "merge":
        print(f"Wrote {merge_account_files(args.inputs, args.output)} unique accounts")


if __name__ == "__main__":
    main()
