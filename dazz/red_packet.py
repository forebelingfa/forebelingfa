import json
import time
import hashlib
import threading
import os
import requests
import uuid
import queue
import sys
from websocket import create_connection, WebSocketTimeoutException
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Core Configuration ---
APP_VERSION = "1.9.5"
DAZZ_BASE = "https://api.dazz2.com/api"
WS_URL = "ws://13.213.254.163:9001"
NAMA_AKUN_FILE = "test"
SCAN_INTERVAL = 0.1

# --- Dispatch & Worker Control ---
WORKER_GROUP_SIZE = 3
MAX_WORKER_ONLINE = 24
WORKER_IDLE_TIMEOUT = 180 
MAX_SHIFT_DURATION = 200

# --- Global Queues & Events ---
stop_event = threading.Event()
priority_claim_queue = queue.PriorityQueue()
account_queue = queue.Queue()
retired_account_queue = queue.Queue()

# --- Real-time room tracking ---
active_rooms = {}
queued_rooms = set()
activity_lock = threading.Lock()

# Checkpoint cooldown (seconds) to avoid repeated checkpoint thrashing
CHECKPOINT_COOLDOWN = 30
last_checkpoint_time = 0.0

jwt = "eyJ0eXAiOiJKV1QiLCJhbGciOiJTSEEyNTYifQ"
main_user_id = 19595547

# Concurrency primitives
BLACKLIST_LOCK = threading.Lock()

# Basic ANSI color codes
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RESET = "\033[0m"

# --- Checkpoint Functions (Standalone) ---
DEFAULT_BLACK_FILE = "black.txt"
CHECKPOINT_LOCK = threading.Lock()

def _build_headers_for_checkpoint(app_version: str, jwt_token: str) -> dict:
    return {
        "User-Agent": app_version,
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "cache-control": "no-cache",
        "authorization-token": jwt_token,
    }

def get_user_info_checkpoint(user_id: str, jwt_token: str, timeout: int = 15) -> dict:
    """Fetch user info with timeout protection. Returns empty dict on failure."""
    try:
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
        headers = _build_headers_for_checkpoint(APP_VERSION, jwt_token)

        resp = requests.post(
            "https://api.dazz2.com/api/member/info", 
            json=payload, 
            headers=headers,
            timeout=timeout
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[CHECKPOINT] Failed to get user info for {user_id}: {e}")
        return {"data": {"gold": 0, "nickname": "ERROR"}}

def check_gold_from_file(file_path):
    """Check gold balance for all accounts in file."""
    results = []
    with open(file_path, "r") as f:
        i = 0
        for line in f:
            if not line.strip():
                continue
            try:
                userid, jwt_tok, token = line.strip().split(",", 2)

                if not jwt_tok:
                    continue

                user_info = get_user_info_checkpoint(userid, jwt_tok)
                gold = user_info.get("data", {}).get("gold", 0)
                nick = user_info.get("data", {}).get("nickname", "N/A")

                print(f"[CHECKPOINT] [{i+1}] {nick} ({userid}) => Gold: {gold}")
                results.append({"userid": userid, "gold": gold, "token": token, "jwt": jwt_tok})

                i += 1
                
            except Exception as e:
                print(f"[CHECKPOINT] Error processing line '{line.strip()}': {e}")
    return results

def check_point(file_name: str):
    """Check gold balance and segregate accounts. Thread-safe."""
    if not os.path.isfile(file_name):
        print(f"[CHECKPOINT] Input file not found: {file_name}")
        return

    print(f"[CHECKPOINT] Processing {file_name}")
    results = check_gold_from_file(file_name)
    
    if not results:
        print(f"[CHECKPOINT] No accounts found in {file_name}")
        return

    to_black = [v for v in results if v["gold"] > 100]
    current_acc = [v for v in results if v["gold"] <= 100]
    total_gold = sum(r.get('gold', 0) for r in results)

    # Thread-safe file operations
    with CHECKPOINT_LOCK:
        # Update main file with zero-gold accounts
        try:
            with open(file_name, "w") as f:
                f.write("\n".join([f"{v['userid']},{v['jwt']},{v['token']}" for v in current_acc]))
            print(f"[CHECKPOINT] '{file_name}' updated with {len(current_acc)} zero-gold accounts")
        except IOError as e:
            print(f"[CHECKPOINT] Failed to write to {file_name}: {e}")

        # Append gold accounts to blacklist
        if to_black:
            try:
                with open(DEFAULT_BLACK_FILE, "a") as f:
                    f.write("\n".join([f"{v['userid']},{v['jwt']},{v['token']}" for v in to_black]))
                    f.write("\n")
                print(f"[CHECKPOINT] '{DEFAULT_BLACK_FILE}' updated with {len(to_black)} gold-bearing accounts")
            except IOError as e:
                print(f"[CHECKPOINT] Failed to write to {DEFAULT_BLACK_FILE}: {e}")

    print(f"[CHECKPOINT] Summary - Processed: {len(results)}, Kept: {len(current_acc)}, Blacklisted: {len(to_black)}, Total Gold: {total_gold}")


# --- Utility Functions ---
def generate_sign_from_payload(payload):
    secret_key = "5d206b343f87f2ca3a0aa05c58b9a64d"
    filtered = {k: v for k, v in payload.items() if k not in ["CREATOR", "serialVersionUID", "sign"]}
    sorted_items = sorted(filtered.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    return hashlib.md5(f"{param_str}&key={secret_key}".encode()).hexdigest()

def fetch_lucky_bag_rooms(jwt_token: str, user_id: int, max_workers: int = 10) -> list:
    """
    Concurrently fetch pages from the hot_anchor endpoint and return
    rooms where `red_packet_logo == 1`.
    """
    headers = {"User-Agent": APP_VERSION, "Authorization-token": jwt_token, "Content-Type": "application/json; charset=UTF-8"}
    url = f"{DAZZ_BASE}/home/hot_anchor"

    # Fetch first page to determine total pages
    payload = {"page": 1, "type": 1, "user_id": user_id, "version": APP_VERSION, "time": str(int(time.time())), "device_id": str(uuid.uuid4()).replace("-",""), "package_type": "haigou-Android", "classify_id": 0, "group_id": 0, "home_id": 0, "lang": "id", "pkg": "3"}
    payload["sign"] = generate_sign_from_payload(payload)
    try:
        resp = requests.post(url, data=json.dumps(payload), headers=headers, timeout=10)
        data = resp.json()
    except Exception:
        return []

    live_details = data.get("data", {}).get("data", [])
    last_page = int(data.get("data", {}).get("last_page", 1) or 1)

    results = []
    # collect from first page
    if live_details:
        results.extend([r for r in live_details if r.get("red_packet_logo") == 1])

    if last_page <= 1:
        return results

    # worker to fetch a single page
    def _fetch_page(p: int):
        p_payload = {"page": p, "type": 1, "user_id": user_id, "version": APP_VERSION, "time": str(int(time.time())), "device_id": str(uuid.uuid4()).replace("-",""), "package_type": "haigou-Android", "classify_id": 0, "group_id": 0, "home_id": 0, "lang": "id", "pkg": "3"}
        p_payload["sign"] = generate_sign_from_payload(p_payload)
        try:
            r = requests.post(url, data=json.dumps(p_payload), headers=headers, timeout=10)
            j = r.json()
            return j.get("data", {}).get("data", [])
        except Exception:
            return []

    pages = list(range(2, last_page + 1))
    with ThreadPoolExecutor(max_workers=min(max_workers, len(pages))) as ex:
        futures = {ex.submit(_fetch_page, p): p for p in pages}
        for fut in as_completed(futures):
            try:
                page_items = fut.result()
                if page_items:
                    results.extend([r for r in page_items if r.get("red_packet_logo") == 1])
            except Exception:
                pass

    return results

# --- The Main Worker Function ---
def dazz_worker(room_id, account_details, lock, active_rooms_dict):
    user_id = None
    token_id = None
    ws = None
    is_token_bad = False
    exited_on_timeout = False

    try:
        user_id = int(account_details['user_id'])
        token_id = account_details['token_id']

        # Helper to create websocket with retries/backoff
        RECONNECT_MAX = 5
        def connect_ws():
            last_err = None
            for attempt in range(1, RECONNECT_MAX + 1):
                try:
                    w = create_connection(WS_URL, timeout=10)
                    print(f"[{user_id}] WebSocket connected on attempt {attempt} for room {room_id}")
                    return w
                except Exception as e:
                    last_err = e
                    backoff = attempt * 1
                    print(f"[{user_id}] Connection attempt {attempt} failed: {e}. Retrying in {backoff}s...")
                    time.sleep(backoff)
            print(f"[{user_id}] Failed to connect websocket after {RECONNECT_MAX} attempts: {last_err}")
            return None

        ws = connect_ws()
        if not ws:
            # Can't proceed without a websocket
            is_token_bad = True
            raise RuntimeError("websocket connection failed")

        join_payload = {"body": {"RoomId": room_id, "Token": token_id, "UserId": user_id, "Lang":"id"}, "op": 1001, "ver": 1}
        ws.send(json.dumps(join_payload))

        ws.settimeout(15)
        last_bag_activity_time = time.time()
        shift_deadline = time.time() + MAX_SHIFT_DURATION
        recv_failures = 0

        while not stop_event.is_set():
            if time.time() > shift_deadline:
                print(f"[{user_id}] Shift ended in room {room_id} due to {GREEN}max duration reached.{RESET}")
                exited_on_timeout = True
                break

            if time.time() - last_bag_activity_time > WORKER_IDLE_TIMEOUT:
                print(f"[{user_id}] Shift ended in room {room_id} due to inactivity.")
                exited_on_timeout = True
                break

            try:
                if not ws:
                    print(f"[{user_id}] No websocket; exiting worker for room {room_id}")
                    break

                try:
                    message = ws.recv()
                except WebSocketTimeoutException:
                    # normal, just loop again
                    continue
                except Exception as e:
                    recv_failures += 1
                    msg = str(e).lower()
                    # On closed socket, attempt to reconnect a few times before giving up
                    if "socket is already closed" in msg or "already closed" in msg or "connection reset" in msg:
                        if recv_failures % 4 == 1:
                            print(f"[{user_id}] Socket closed while receiving in room {room_id}: {e} — attempting reconnect")
                        # attempt reconnect
                        new_ws = connect_ws()
                        if new_ws:
                            ws = new_ws
                            ws.settimeout(15)
                            recv_failures = 0
                            continue
                        else:
                            print(f"[{user_id}] Reconnect failed; exiting worker for room {room_id}")
                            break
                    else:
                        print(f"[{user_id}] recv error in room {room_id}: {e}")
                        time.sleep(0.5)
                        break

                # reset failure counter on successful recv
                recv_failures = 0

                # skip non-JSON messages silently
                try:
                    MSGData = json.loads(message)
                except Exception:
                    continue

                OP_TYPE = MSGData.get("op")
                body = MSGData.get("body", {})

                if OP_TYPE and OP_TYPE > 2000:
                    print(f"({user_id}) {GREEN}Online{RESET} in {room_id}")

                if OP_TYPE == 2100 and "LuckyBagData" in body:
                    countdown = body.get("CountDown", 0)
                    if countdown:
                        new_deadline = time.time() + countdown + 5
                        if new_deadline > shift_deadline:
                            print(f"[{user_id}] Countdown detected. Extending shift deadline for {countdown}s.")
                            shift_deadline = new_deadline

                LB_EXE = body.get("ID", 0)
                if LB_EXE:
                    last_bag_activity_time = time.time()
                status = body.get("Status", 0)

                if "sudah habis" in body.get("ErrStr", "").lower():
                    continue

                if LB_EXE and status == 1:
                    print(f"[{user_id}] Claiming bag {GREEN}{LB_EXE}{RESET} in room {room_id}")
                    for _ in range(7):
                        try:
                            ws.send(json.dumps({"body": {"ID": LB_EXE}, "op": 2101, "ver": 1}))
                        except Exception as e:
                            serr = str(e).lower()
                            # try reconnect-on-send for transient closure
                            if "already closed" in serr or "connection reset" in serr:
                                print(f"[{user_id}] Socket closed while sending in room {room_id}: {e} — attempting reconnect")
                                new_ws = connect_ws()
                                if new_ws:
                                    ws = new_ws
                                    ws.settimeout(15)
                                    try:
                                        ws.send(json.dumps({"body": {"ID": LB_EXE}, "op": 2101, "ver": 1}))
                                    except Exception as e2:
                                        print(f"[{user_id}] Retry send failed in room {room_id}: {e2}")
                                        break
                                else:
                                    print(f"[{user_id}] Reconnect failed after send error; aborting send loop")
                                    break
                            else:
                                print(f"[{user_id}] send error in room {room_id}: {e}")
                                break
                        time.sleep(0.1)

            except Exception as e:
                print(f"exiting due to {e}")
                break
    except Exception as e:
        is_token_bad = True
        print(f"[{user_id}] Token likely rejected. Error: {e}")

    finally:
        with lock:
            if room_id in active_rooms_dict:
                active_rooms_dict[room_id] -= 1
                if active_rooms_dict[room_id] <= 0:
                    del active_rooms_dict[room_id]
                    print(f"[MANAGER] Room {room_id} is now vacant and can be re-scanned.")

        if is_token_bad:
            BLACKLIST_FILE = "bad_tokens.txt"
            with BLACKLIST_LOCK:
                with open(BLACKLIST_FILE, "a") as f:
                    f.write(f"{user_id},{token_id}\n")
            print(f"[MANAGER] Blacklisted {user_id}")
        else:
            # Recycle any non-bad account (timeout or normal exit) back to the main queue
            account_queue.put(account_details)
            if exited_on_timeout:
                print(f"[MANAGER] ♻️ Recycled {user_id} (timeout) back to queue")
            else:
                print(f"[MANAGER] ♻️ Recycled {user_id} back to queue")
        if ws: ws.close()

def room_scanner_thread():
    print("[SCANNER] Room scanner deployed.")
    while not stop_event.is_set():
        try:
            new_rooms_found = fetch_lucky_bag_rooms(jwt, main_user_id, 5)
            new_room_count = 0
            
            with activity_lock:
                for room_data in new_rooms_found:
                    room_id = room_data['room_id']
                    if room_id not in active_rooms and room_id not in queued_rooms:
                        priority_claim_queue.put((time.time(), room_id))
                        queued_rooms.add(room_id)
                        new_room_count += 1
            
            if new_room_count > 0:
                print(f"\n[SCANNER] Found and queued {new_room_count} {GREEN}new rooms{RESET}.")
            time.sleep(SCAN_INTERVAL)
        except Exception as e:
            print(f"[SCANNER] Error during scan: {e}")
            time.sleep(SCAN_INTERVAL)

def load_akun():
    BLACKLIST_FILE = "bad_tokens.txt"
    if os.path.exists(BLACKLIST_FILE): os.remove(BLACKLIST_FILE)
    print("[MANAGER] Loading accounts...")
    try:
        with open(NAMA_AKUN_FILE) as fp:
            for line in fp:
                if not line.strip(): continue
                user_id, jwt, token_id = line.strip().split(",")
                account_queue.put({"user_id": user_id, "token_id": token_id})
        print(f"[MANAGER] Loaded {account_queue.qsize()} accounts.")
    except FileNotFoundError:
        print(f"[MANAGER] Account file '{NAMA_AKUN_FILE}' not found. Exiting.")
        sys.exit()

if __name__ == "__main__":

    load_akun()
    scanner = threading.Thread(target=room_scanner_thread, daemon=True)
    scanner.start()
    
    print(f"[MANAGER] Starting dispatcher...")
    active_threads = []

    priority_claim_queue.put((time.time(), 86372))

    try:
        while not stop_event.is_set():
            active_threads = [t for t in active_threads if t.is_alive()]

            # Calculate available worker slots
            available_slots = MAX_WORKER_ONLINE - len(active_threads)

            # Only proceed if we have at least one free slot
            if available_slots <= 0:
                print(f"\r[STATUS] No available worker slots ({len(active_threads)}/{MAX_WORKER_ONLINE}).", end="")
                time.sleep(1)
                continue

            # If the main account pool is empty, try checkpoint to refill
            if account_queue.empty():
                now = time.time()
                if now - last_checkpoint_time > CHECKPOINT_COOLDOWN:
                    print(f"\n{YELLOW}[MANAGER] Active account pool exhausted. Running checkpoint and reloading all accounts...{RESET}")

                    # Use the localized checkpoint daemon which ensures a direct socket and safe session handling.
                    try:
                        checkpoint_thread = threading.Thread(target=check_point, args=(NAMA_AKUN_FILE,), daemon=True); checkpoint_thread.start(); print(f"{GREEN}[MANAGER] Checkpoint running in background...{RESET}")
                    except Exception as e:
                        print(f"[MANAGER] Checkpoint failed: {e}")

                    # mark when we last ran a checkpoint to prevent tight repeated runs
                    last_checkpoint_time = time.time()

                    # Reload accounts from disk (checkpoint writes zero-gold accounts back to file)
                    load_akun()
                    print(f"{GREEN}[MANAGER] Reloaded {account_queue.qsize()} accounts from disk.{RESET}")
                else:
                    wait = int(CHECKPOINT_COOLDOWN - (now - last_checkpoint_time))
                    print(f"{YELLOW}[MANAGER] Checkpoint cooldown active; next attempt in {wait}s.{RESET}")

            # Check if we still have rooms to work on after potential refresh
            if priority_claim_queue.empty():
                print(f"\r[STATUS] No rooms queued, waiting for scanner ({len(active_threads)}/{MAX_WORKER_ONLINE}).", end="\n")
                time.sleep(1)
                continue

            # After a potential refresh, decide how many workers to spawn.
            # We allow partial groups: spawn up to WORKER_GROUP_SIZE but no more than
            # available_slots and no more than accounts available.
            accounts_available = account_queue.qsize()
            desired_group = min(WORKER_GROUP_SIZE, available_slots, accounts_available)
            if desired_group <= 0:
                # Not enough accounts yet; wait a bit and continue
                time.sleep(1)
                continue

            _, target_room = priority_claim_queue.get()

            with activity_lock:
                if target_room in queued_rooms:
                    queued_rooms.remove(target_room)
                # Initialize the room as active (workers will be added below).
                active_rooms[target_room] = 0

            print(f"\n[MANAGER] Top priority is room {BLUE}{target_room}{RESET}. Assembling group of {desired_group} (requested {WORKER_GROUP_SIZE})...")

            # Dispatch a new group (possibly partial) of workers from the fresh account queue.
            for i in range(desired_group):
                try:
                    account_to_use = account_queue.get_nowait()
                except Exception:
                    break
                with activity_lock:
                    active_rooms[target_room] += 1
                thread = threading.Thread(target=dazz_worker, args=(int(target_room), account_to_use, activity_lock, active_rooms))
                thread.daemon = True
                thread.start()
                active_threads.append(thread)

            priority_claim_queue.task_done()
            
            # More verbose status for debugging queues and rooms
            top_active = list(active_rooms.keys())[:3]
            queued_count = len(queued_rooms)
            print(
                f"\r[{time.strftime('%H:%M:%S')}] STATUS: PriorityQueued={priority_claim_queue.qsize()} QueuedSet={queued_count} "
                f"RoomsActive={len(active_rooms)}(top={top_active}) AccountsReady={account_queue.qsize()} "
                f"Reserve={retired_account_queue.qsize()} WorkersOnline={len(active_threads)}   ",
                end="",
            )
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n[MANAGER] Shutdown signal received. Stopping all threads...")
        stop_event.set()
        for t in active_threads: t.join(timeout=2)
        if scanner.is_alive(): scanner.join()