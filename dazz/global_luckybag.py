#!/usr/bin/env python

import json
import time
import hashlib
import threading
import os, random, uuid, requests
from icecream import icecream as IC
from websocket import create_connection
from api import get_room_id, list_beranda


APP_VERSION = "1.9.2"
IC.ic.disable()
NAMA_AKUN_FILE = "selasa" 
WS_URL = "ws://13.213.254.163:9001"
ACCOUNTS_TO_JOIN = 3
LATEST_ACTIVE_ROOM_ID = 0


stop_event = threading.Event()
ACCOUNT_TOKEN_FILE = NAMA_AKUN_FILE

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RESET = "\033[0m"


def generate_sign_from_payload(payload):
    """Generates the required 'sign' hash for API payloads."""
    secret_key = "5d206b343f87f2ca3a0aa05c58b9a64d"
    filtered = {
        k: v
        for k, v in payload.items()
        if k not in ["CREATOR", "serialVersionUID", "sign"]
    }
    sorted_items = sorted(filtered.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    full_string = f"{param_str}&key={secret_key}"
    return hashlib.md5(full_string.encode("utf-8")).hexdigest()

def export_token_to_txt(output_filename: str, file_jwt_cache: str):
    """Reads the JSON cache and exports userid,token pairs to a simple text file."""
    if not os.path.isfile(file_jwt_cache):
        print(f"[!] Cache file not found: {file_jwt_cache}")
        return

    try:
        with open(file_jwt_cache, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[!] Error loading cache file: {e}")
        return

    with open(output_filename, "w") as f:
        count = 0
        for user_id, user_data in data.items():
            token = user_data.get("token")
            if token:
                f.write(f"{user_id},{token}\n")
                count += 1
    print(f"[✓] Exported {count} accounts with tokens to '{output_filename}'")

def dazz_websocket(room_id, user_id, token_id, jwt_token):
    global jwt
    global LATEST_ACTIVE_ROOM_ID
    """
    Handles the WebSocket connection, joining rooms, and claiming lucky bags.
    Switches rooms automatically and retires itself after a successful claim.
    """
    ws = None
    user_id = int(user_id)
    current_room_id = room_id

    def md5_result(token, time_mill):
        salt = "5d206b343f87f2ca3a0aa05c58b9a64d"
        raw = f"{time_mill}{token}{salt}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def send_ws_payload(ws_conn, payload):
        try:
            if ws_conn and ws_conn.connected:
                ws_conn.send(json.dumps(payload))
                return True
            return False
        except Exception:
            return False

    join_payload = {
        "body": {
            "DeviceType": 1,
            "EnterType": 0,
            "FuncLevel": 256,
            "Lang": "id",
            "Md5Str": "",
            "RoomId": current_room_id,
            "TimeMill": 0,
            "Token": token_id,
            "Tourist": 0,
            "UserId": user_id,
            "Version": APP_VERSION,
            "package_type": "haigou-Android",
        },
        "op": 1001,
        "ver": 1,
    }

    def update_and_send_join(ws_conn):
        """Helper to set latest time/hash and send the join payload."""
        mili_time = int(time.time() * 1000)
        md5str = md5_result(token_id, mili_time)
        join_payload["body"]["TimeMill"] = mili_time
        join_payload["body"]["Md5Str"] = md5str
        return send_ws_payload(ws_conn, join_payload)

    try:
        ws = create_connection(WS_URL, timeout=10)
        update_and_send_join(ws)
        print(f"[{user_id}] → Connected and joining initial room {current_room_id}")

        while not stop_event.is_set():
            try:
                message = ws.recv()
                MSGData = json.loads(message)
                OP_TYPE = MSGData.get("op")
                body = MSGData.get("body", {})
                IC.ic(body)
                if OP_TYPE > 2000:
                    print(
                        f"({user_id}) Online in room {current_room_id}, incoming 2K+ updates.."
                    )

                if (
                    isinstance(body, dict)
                    and OP_TYPE == 2100
                    and "LuckyBagData" in body
                ):
                    lb_data = body.get("LuckyBagData", {})
                    lb_id = lb_data.get("ID", 0)
                    anchor_id = body.get("AnchorId", 0)
                    if not anchor_id or not lb_id:
                        continue

                    print(
                        f"[{user_id}] {YELLOW}Spotted Global Lucky Bag {lb_id} from anchor {anchor_id}{RESET}"
                    )

                    new_room_id = int(get_room_id(anchor_id, jwt))
                    if new_room_id != current_room_id:
                        print(
                            f"[{user_id}] {BLUE}Switching from room {current_room_id} to {new_room_id} for the bag!{RESET}"
                        )

                        try:
                            ws.close()
                        except Exception:
                            pass

                        current_room_id = new_room_id
                        LATEST_ACTIVE_ROOM_ID = new_room_id

                        join_payload["body"]["RoomId"] = current_room_id
                        ws = create_connection(WS_URL, timeout=10)
                        update_and_send_join(
                            ws
                        )
                        print(
                            f"[{user_id}] → Re-connected to join new room {current_room_id}"
                        ) 

                    else:
                        print(
                            f"[{user_id}] {GREEN}Already in the correct room ({current_room_id}) for the bag.{RESET}"
                        )

                    continue

                if "sudah habis" in body.get("ErrStr", "").lower():
                    continue

                LB_EXE = body.get("ID", 0)
                status = body.get("Status", 0)

                if LB_EXE and status == 1:
                    for _ in range(7):
                        send_ws_payload(ws, {"body": {"ID": LB_EXE}, "op": 2101, "ver": 1})
                        print(f"[{user_id}] Executed lucky bag {GREEN}{LB_EXE}{RESET} in room {current_room_id}")
                        # time.sleep(0.3)

                    print(f"[{user_id}] Checking balance after claim attempt...")
                    try:
                        user_info = get_user_info(str(user_id), jwt)
                        gold = user_info.get("data", {}).get("gold", 0)
                        if gold > 0:
                            print(f"[{user_id}] {GREEN}SUCCESS! Gold balance is {gold}.{RESET}")
                            return
                        else:
                            print(f"[{user_id}] {YELLOW}Claim sent, but balance is still zero.{RESET}")
                    except Exception as e:
                        print(f"[{user_id}] {RED}Could not check balance after claim: {e}{RESET}")

            except json.JSONDecodeError:
                continue
            except Exception as inner_e:
                print(f"[{user_id}] recv error: {inner_e}")
                break

        ws.close()
    except Exception as e:
        print(f"[!] WebSocket error for user {user_id}: {e}")
    finally:
        if ws and ws.connected:
            ws.close()
        print(f"[{user_id}] Disconnected.")

def _build_headers(app_version: str, jwt_token: str) -> dict:
    return {
        "User-Agent": app_version,
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "cache-control": "no-cache",
        "authorization-token": jwt_token,
    }

def get_user_info(user_id: str, jwt_token: str) -> dict:
    payload = {
        "id": str(user_id),
        "version": "1.0",
        "app_version": APP_VERSION,
        "channel_id": "3",
        "device_id": str(uuid.uuid4()).replace("-", ""),
        "facility": "1",
        "lang": "id",
        "package_type": "Android-Google",
        "sign": "",
        "time": str(int(time.time())),
        "user_id": str(user_id),
    }
    payload["sign"] = generate_sign_from_payload(payload)
    headers = _build_headers(APP_VERSION, jwt_token)

    resp = requests.post(
        "https://api.dazz2.com/api/member/info", json=payload, headers=headers
    )
    resp.raise_for_status()
    return resp.json()

def check_gold_from_file(file_path):
    results = []
    with open(file_path, "r") as f:
        i = 0
        for line in f:
            if not line.strip():
                continue
            try:
                userid, jwt, token = line.strip().split(",", 2)

                if not jwt:
                    continue

                user_info = get_user_info(userid, jwt)
                gold = user_info.get("data", {}).get("gold", 0)
                nick = user_info.get("data", {}).get("nickname", "")

                print(f"[{i+1}] {nick} => Gold: {gold} {userid}")
                results.append(
                    {"userid": userid, "gold": gold, "jwt": jwt, "token": token}
                )

                i += 1

            except Exception as e:
                print(f"[!] Error processing line '{line.strip()}': {e}")
    return results

def check_point(file_name: str):
    akun_path = file_name
    black_path = "black"

    if not os.path.isfile(akun_path):
        print(f"[!] Account file not found: {akun_path}")
        return

    print(f"\n=== Processing {file_name} ===")

    results = []
    try:
        results = check_gold_from_file(akun_path)
    except Exception as e:
        print(f"[!] check_gold_from_file failed: {e}")

    if not results:
        print("[⚠️] No results returned — skipping update to prevent data loss.")
        return

    to_black = [v for v in results if v["gold"] >= 1]
    current_acc = [v for v in results if v["gold"] < 1]

    if current_acc:
        with open(akun_path, "w") as f_out:
            f_out.write(
                "\n".join(f"{v['userid']},{v['jwt']},{v['token']}" for v in current_acc)
            )

        print(f"[✓] Updated account file → {len(current_acc)} accounts remain.")
    else:
        print("[⚠️] No zero-gold accounts remain, skipping file rewrite.")

    if to_black:
        with open(black_path, "a") as f_black:
            f_black.write(
                "\n".join(f"{v['userid']},{v['jwt']},{v['token']}" for v in to_black)
            )
            f_black.write("\n")
        print(f"[✓] Added {len(to_black)} accounts to blacklist.")

    total_gold = sum(v["gold"] for v in results)
    print(
        f"[💰] Total gold: {total_gold} | Active: {len(current_acc)} | Blacked: {len(to_black)}"
    )

def checkpoint_daemon():
    """Background thread: check accounts and update blacklist/cache safely"""

    try:
        print("[🔍] Running checkpoint daemon...")
        check_point(NAMA_AKUN_FILE)
        print("[✅] Checkpoint done.")
    except Exception as e:
        print(f"[!] Checkpoint daemon error: {e}")

if __name__ == "__main__":
    jwt = "eyJpc3MiOiJoaWdvIiwiaWF0IjoxNzYyMjAyMDQxLCJleHAiOjE3NjI4MDY4NDEsInVzZXJfaWQiOjE5NTk1NTQ3fQ"

    try:
        target_room_ids = list_beranda(1, jwt, 19595547)
        anchor_names = list(target_room_ids)
        target_room_id = int(target_room_ids[anchor_names[1]])
    except Exception as e:
        print(f"{RED}[!] Failed to get initial room list: {e}{RESET}")
        exit()

    print("\n[⚙️] Preparing accounts...")
    # target_room_id = get_room_id(17567475,jwt)
    # checkpoint_daemon()

    try:
        with open(ACCOUNT_TOKEN_FILE) as fp:
            all_accounts = fp.read().splitlines()
    except FileNotFoundError:
        print(f"{RED}[!] Account file '{ACCOUNT_TOKEN_FILE}' not found.{RESET}")
        exit()

    if not all_accounts:
        print(f"{RED}[!] No accounts found in the account file.{RESET}")
        exit()

    print(f"\n[🚀] Starting Thread Manager for room {target_room_id}...")

    running_threads = {}
    dispatched_user_ids = set()
    next_account_index = 0

    try:
        while not stop_event.is_set():
            dead_user_ids = [user_id for user_id, thread in running_threads.items() if not thread.is_alive()]
            for user_id in dead_user_ids:
                print(
                    f"{YELLOW}[MANAGER] Thread for user {user_id} has stopped. Removing from active pool.{RESET}"
                )
                del running_threads[user_id]

            while len(running_threads) < ACCOUNTS_TO_JOIN and next_account_index < len(all_accounts):
                account_line = all_accounts[next_account_index]
                next_account_index += 1

                try:
                    user_id, jwt_token, token_id = account_line.strip().split(",", 2)
                    if user_id in dispatched_user_ids:
                        continue

                    print(
                        f"{BLUE}[MANAGER] Vacant slot found. Dispatching new worker: {user_id}{RESET}"
                    )

                    t = threading.Thread(
                        target=dazz_websocket,
                        args=(target_room_id, user_id, token_id, jwt_token),
                    )

                    t.daemon = True
                    t.start()

                    running_threads[user_id] = t
                    dispatched_user_ids.add(user_id)
                    time.sleep(random.randint(1, 7))

                except ValueError:
                    print(
                        f"{RED}[MANAGER] Skipping malformed line in account file: {account_line}{RESET}"
                    )

            if len(running_threads) == 0 and next_account_index >= len(all_accounts):
                print(
                    f"{GREEN}[MANAGER] All accounts have been processed and all threads have stopped. Mission complete.{RESET}"
                )
                continue

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[!] CTRL+C detected. Shutting down all connections...")
        stop_event.set()
        for thread in running_threads.values():
            thread.join(timeout=3)
        print("[✓] All threads stopped. Exiting.")
