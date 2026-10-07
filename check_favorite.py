from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict, Optional, Set

from api import list_hot_anchors
from config import DEFAULT_CONFIG
from simple_account_manager import load_accounts


DEFAULT_FAVORITES = {
    # Fill with your Tamil favorite anchor IDs here.
    # Example:
    # "anchor_one": 123456,
    # "anchor_two": 654321,
}

STATE_FILE = Path(__file__).resolve().parent / "tamil_favorite_state.json"


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


def list_beranda(page: int, jwt_token: str, user_id: int) -> list[int]:
    """Return anchor IDs from one verified Tamil hot-anchor page."""
    anchor_ids: list[int] = []
    for row in list_hot_anchors(page, jwt_token, user_id):
        anchor_id = row.get("user_id") or row.get("anchor_id") or row.get("id")
        try:
            if anchor_id not in (None, ""):
                anchor_ids.append(int(anchor_id))
        except (TypeError, ValueError):
            continue
    return anchor_ids


def get_live_anchor_ids(jwt_token: str, user_id: int, page_limit: int = 5) -> Set[int]:
    live_ids: Set[int] = set()
    page = 1
    while page <= page_limit:
        ids = list_beranda(page, jwt_token, user_id)
        if not ids:
            break
        live_ids.update(ids)
        page += 1
    return live_ids


def watch_favorites(
    favorite_anchors: Optional[Dict[str, int]] = None,
    account_file: str = DEFAULT_CONFIG.account_file,
    state_file: Path = STATE_FILE,
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
        live_ids = get_live_anchor_ids(jwt_token, user_id, page_limit=page_limit)
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
        poll_interval_seconds=args.poll_interval,
        page_limit=args.page_limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
