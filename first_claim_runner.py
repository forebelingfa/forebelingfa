import argparse
import json

from room_poller import RoomPoller
from simple_account_manager import load_accounts
from simple_worker import claim_lucky_bag


def run_first_claim(account_file: str, room_id: int, lucky_bag_id: int, bag_value: int = 0) -> dict:
    accounts = load_accounts(account_file)
    account = accounts[0]
    result = claim_lucky_bag(account, room_id=room_id, lucky_bag_id=lucky_bag_id)
    print(json.dumps({
        "account_user_id": account["user_id"],
        "room_id": room_id,
        "bag_id": lucky_bag_id,
        "bag_value": bag_value,
        "result": result,
    }, indent=2, ensure_ascii=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Compact LuckyBag claim runner.")
    parser.add_argument("--accounts", default="accounts.txt", help="Account file with userId,ws_token,jwt rows")
    parser.add_argument("--room-id", type=int, help="Target room id")
    parser.add_argument("--bag-id", type=int, help="Lucky bag id to claim")
    parser.add_argument("--bag-value", type=int, default=0, help="Optional value hint")
    parser.add_argument("--poll", action="store_true", help="List one discovered LuckyBag room and exit")
    parser.add_argument("--poll-seconds", type=float, default=5.0, help="Polling interval used when --poll is set")
    args = parser.parse_args()

    if args.poll:
        poller = RoomPoller(poll_interval_seconds=args.poll_seconds)
        for opportunity in poller.poll_once():
            print(json.dumps({
                "room_id": opportunity.room_id,
                "owner_nick": opportunity.owner_nick,
                "bag_id": opportunity.bag_id,
                "value": opportunity.value,
                "source": opportunity.source,
            }, indent=2, ensure_ascii=False))
            return
        print("No LuckyBag room found on current backend response.")
        return

    if args.room_id is None or args.bag_id is None:
        parser.error("--room-id and --bag-id are required unless --poll is used")

    run_first_claim(args.accounts, args.room_id, args.bag_id, args.bag_value)


if __name__ == "__main__":
    main()
