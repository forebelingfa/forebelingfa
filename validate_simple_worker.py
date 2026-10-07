import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simple_account_manager import load_accounts
from simple_worker import claim_lucky_bag


class FakeConnection:
    def __init__(self):
        self.sent = []
        self._responses = [
            json.dumps({"op": 1001, "body": {"Code": 0, "UserId": 1001, "NickName": "Tester"}}),
            json.dumps({
                "op": 2101,
                "body": {"ID": 999, "Code": 0, "Gold": 250, "ErrStr": ""},
            }),
        ]

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def recv(self):
        if not self._responses:
            raise RuntimeError("No more fake responses")
        return self._responses.pop(0)

    def close(self):
        pass


def run_checks():
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
        handle.write("1001,token_a,jwt_a\n")
        handle.write("1002,token_b,jwt_b\n")
        temp_path = handle.name

    try:
        accounts = load_accounts(temp_path)
        assert accounts == [
            {"user_id": 1001, "ws_token": "token_a", "jwt": "jwt_a"},
            {"user_id": 1002, "ws_token": "token_b", "jwt": "jwt_b"},
        ], "Account loader failed"

        fake_socket = FakeConnection()
        with patch("simple_worker.websocket.create_connection", return_value=fake_socket):
            result = claim_lucky_bag(
                account={"user_id": 1001, "ws_token": "token_a", "jwt": "jwt_a"},
                room_id=123,
                lucky_bag_id=999,
            )

        assert result["ok"] is True, result
        assert result["gold"] == 250, result
        assert result["lucky_bag_id"] == 999, result
        assert any(item.get("op") == 2101 for item in fake_socket.sent), fake_socket.sent

        print("OK: account loader and claim flow validated")
    finally:
        os.unlink(temp_path)


def main():
    parser = argparse.ArgumentParser(description="Validate the simplified account manager and worker claim flow.")
    parser.add_argument("--check", action="store_true", help="Run the account and claim validation checks.")
    parser.add_argument("--accounts", type=str, help="Optional account file to load and inspect.")
    args = parser.parse_args()

    if args.check:
        run_checks()
        return

    if args.accounts:
        accounts = load_accounts(args.accounts)
        print(json.dumps(accounts, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
