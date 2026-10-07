from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from hashlib import md5
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import requests

from config import DEFAULT_CONFIG
from simple_account_manager import load_accounts


DEFAULT_FAVORITES = {
    # Fill with your Tamil favorite anchor IDs here.
    # Example:
    # "anchor_one": 123456,
    # "anchor_two": 654321,
}

STATE_FILE = Path(__file__).resolve().parent / "tamil_favorite_state.json"


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


def load_state(path: Path = STATE_FILE) -> Dict[str, int]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return {str(k): int(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_state(state: Dict[str, int], path: Path = STATE_FILE) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False)


def _extract_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        candidates = []
        for key in ("rooms", "items", "data", "list", "room_list", "hot_rooms", "anchors"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                candidates.append(value)
        if candidates:
            return candidates
        return [payload]
    return []


def _coerce_anchor_id(row: Dict[str, Any]) -> Optional[int]:
    for key in ("user_id", "uid", "anchor_id", "anchorId", "userId", "id"):
        value = row.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _coerce_room_id(row: Dict[str, Any]) -> Optional[int]:
    for key in ("room_id", "roomId", "roomID", "room"):
        value = row.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def list_beranda(page: int, jwt_token: str, user_id: int, api_url: str = DEFAULT_CONFIG.poll_url) -> List[int]:
    """Fetch live anchor IDs from the hot room endpoint."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "authorization-token": jwt_token,
        "cache-control": "no-cache",
    }

    payload = {
        "classify_id": 0,
        "device_id": str(uuid.uuid4()).replace("-", ""),
        "group_id": 0,
        "home_id": 0,
        "lang": "id",
        "package_type": "haigou-Android",
        "page": page,
        "pkg": "3",
        "time": str(int(time.time())),
        "type": 1,
        "user_id": user_id,
        "version": "2.1.5",
    }
    payload["sign"] = generate_sign_from_payload(payload)

    try:
        resp = requests.post(api_url, data=json.dumps(payload), headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    anchor_ids: List[int] = []
    for row in _extract_rows(data):
        anchor_id = _coerce_anchor_id(row)
        if anchor_id is not None:
            anchor_ids.append(anchor_id)
    return anchor_ids


def get_live_anchor_ids(jwt_token: str, user_id: int, page_limit: int = 5, api_url: str = DEFAULT_CONFIG.poll_url) -> Set[int]:
    live_ids: Set[int] = set()
    page = 1
    while page <= page_limit:
        ids = list_beranda(page, jwt_token, user_id, api_url=api_url)
        if not ids:
            break
        live_ids.update(ids)
        page += 1
    return live_ids


def watch_favorites(
    favorite_anchors: Optional[Dict[str, int]] = None,
    account_file: str = DEFAULT_CONFIG.account_file,
    state_file: Path = STATE_FILE,
    api_url: str = DEFAULT_CONFIG.poll_url,
    poll_interval_seconds: float = 5.0,
    page_limit: int = 5,
    dry_run: bool = False,
) -> Dict[str, int]:
    favorites = favorite_anchors or DEFAULT_FAVORITES
    if not favorites:
        raise ValueError("No favorite anchors configured. Add entries to DEFAULT_FAVORITES or pass --favorite.")

    accounts = load_accounts(account_file)
    account = accounts[0]
    jwt_token = str(account["jwt"])
    user_id = int(account["user_id"])

    previous = load_state(state_file)
    current_state: Dict[str, int] = {}

    while True:
        live_ids = get_live_anchor_ids(jwt_token, user_id, page_limit=page_limit, api_url=api_url)
        changed = []

        for name, anchor_id in sorted(favorites.items(), key=lambda item: item[0]):
            is_live = 1 if int(anchor_id) in live_ids else 0
            current_state[str(anchor_id)] = is_live

            prev = previous.get(str(anchor_id), 0)
            if is_live and prev == 0:
                changed.append(f"LIVE {name} ({anchor_id})")
            elif not is_live and prev == 1:
                changed.append(f"OFFLINE {name} ({anchor_id})")

            if dry_run:
                print(f"[{name}] anchor={anchor_id} status={'ONLINE' if is_live else 'OFFLINE'}")

        if changed:
            print("\n".join(changed))

        save_state(current_state, state_file)
        previous = current_state.copy()

        if dry_run:
            break

        time.sleep(poll_interval_seconds)

    return current_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Tamil favorite-anchor watcher based on the Dazz check_favorite pattern.")
    parser.add_argument("--accounts", default=DEFAULT_CONFIG.account_file, help="Account file in userId,ws_token,jwt format")
    parser.add_argument("--favorite", action="append", nargs=2, metavar=("NAME", "ANCHOR_ID"), help="Favorite anchor to watch, e.g. --favorite andina 123456")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between polling checks")
    parser.add_argument("--page-limit", type=int, default=5, help="Number of hot-anchor pages to scan")
    parser.add_argument("--state-file", type=str, default=str(STATE_FILE), help="Path for the live/offline state JSON file")
    parser.add_argument("--api-url", default=DEFAULT_CONFIG.poll_url, help="Hot anchor endpoint")
    parser.add_argument("--dry-run", action="store_true", help="Check once and exit")
    args = parser.parse_args()

    favorites: Dict[str, int] = dict(DEFAULT_FAVORITES)
    if args.favorite:
        for name, anchor_id in args.favorite:
            favorites[name] = int(anchor_id)

    if not favorites:
        parser.error("No favorite anchors configured. Add --favorite NAME ID or fill DEFAULT_FAVORITES.")

    state_path = Path(args.state_file)
    watch_favorites(
        favorite_anchors=favorites,
        account_file=args.accounts,
        state_file=state_path,
        api_url=args.api_url,
        poll_interval_seconds=args.poll_interval,
        page_limit=args.page_limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
