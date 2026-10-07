import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from room_poller import RoomPoller
from runtime_state import RuntimeState
from scale_system import AdaptiveRunner
from simple_account_manager import load_accounts
from simple_worker import claim_lucky_bag
from speed_scheduler import BagOpportunity, WorkerScheduler


def run_first_claim(account_file: str, room_id: int, lucky_bag_id: int, bag_value: int = 0) -> None:
    accounts = load_accounts(account_file)
    state = RuntimeState(accounts=accounts)
    for account in accounts:
        state.worker_health.setdefault(account["user_id"], type("Health", (), {"user_id": account["user_id"], "connected": False, "last_result": "unknown", "last_error": "", "success_count": 0, "failure_count": 0, "is_healthy": True, "last_seen": 0.0})())
    scheduler = WorkerScheduler(state)
    opportunity = BagOpportunity(room_id=room_id, bag_id=lucky_bag_id, bag_value=bag_value, discovered_at=time.time())
    adaptive = AdaptiveRunner(state)
    adaptive.push_opportunity({
        "room_id": opportunity.room_id,
        "bag_id": opportunity.bag_id,
        "value": opportunity.bag_value,
        "time": opportunity.discovered_at,
    })

    result = adaptive.run_once(
        adaptive.queue.pop_best() or {"room_id": room_id, "bag_id": lucky_bag_id, "value": bag_value, "time": time.time()},
        lambda account, target_room_id, target_bag_id: claim_lucky_bag(
            account=account,
            room_id=target_room_id,
            lucky_bag_id=target_bag_id,
        ),
    )
    results = [{
        "user_id": result.get("user_id", next(iter(state.worker_health.keys()), 0)),
        "room_id": room_id,
        "bag_id": lucky_bag_id,
        "ok": result.get("ok", False),
        "gold": result.get("gold", 0),
        "elapsed_ms": result.get("elapsed_ms", 0),
        "message": result.get("message", ""),
    }]

    print(json.dumps(results, indent=2))
    print(json.dumps(adaptive.summary(), indent=2))

    winners = [r for r in results if r["ok"]]
    if winners:
        winner = min(winners, key=lambda item: item["elapsed_ms"])
        print(f"WINNER: user_id={winner['user_id']} gold={winner['gold']} elapsed_ms={winner['elapsed_ms']}")
    else:
        print("NO WINNER: no worker claimed the bag successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the first-claim race against a target LuckyBag.")
    parser.add_argument("--accounts", default="accounts.txt", help="Account file with userId,ws_token,jwt rows")
    parser.add_argument("--room-id", type=int, help="Target room id")
    parser.add_argument("--bag-id", type=int, help="Lucky bag id to claim")
    parser.add_argument("--bag-value", type=int, default=0, help="Optional bag value used to prioritize the queue")
    parser.add_argument("--poll", action="store_true", help="Poll for LuckyBag rooms continuously and claim the first discovered opportunity.")
    parser.add_argument("--poll-seconds", type=float, default=5.0, help="Polling interval for room discovery when --poll is used.")
    args = parser.parse_args()

    if args.poll:
        poller = RoomPoller(endpoint="https://api.taalmil.live/api/go_v3/hot_anchor", poll_interval_seconds=args.poll_seconds)
        for opportunity in poller.poll_forever(max_iterations=1):
            print(json.dumps({
                "room_id": opportunity.room_id,
                "owner_nick": opportunity.owner_nick,
                "bag_id": opportunity.bag_id,
                "value": opportunity.value,
                "source": opportunity.source,
            }, indent=2))
            break
        return

    if args.room_id is None or args.bag_id is None:
        parser.error("--room-id and --bag-id are required unless --poll is used")

    run_first_claim(args.accounts, args.room_id, args.bag_id, args.bag_value)


if __name__ == "__main__":
    main()
