import json
import time
import logging
from websocket import create_connection, WebSocketConnectionClosedException
import hashlib
import threading
import zlib
import random
import os
import requests
import uuid
try:
    import socks
    SOCKS_AVAILABLE = True
except Exception:
    socks = None
    SOCKS_AVAILABLE = False
import socket

# Store the original socket class before any modifications
ORIGINAL_SOCKET = socket.socket

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

if not SOCKS_AVAILABLE:
    logger.warning("PySocks not installed; SOCKS proxying disabled. Install with: pip install pysocks")

RECONNECT_DELAY = 1
REFRESH_INTERVAL = 20 * 60
MAX_WORKER = 199
ACCOUNT_PER_ROOM = 1
MAX_RETRY = int(MAX_WORKER / 2)

WS_URL = "ws://13.213.254.163:9001"
APP_VERSION = "1.9.9"
DEFAULT_ACCOUNT_FILE = "senin"
DEFAULT_BLACK_FILE = "black"
DEFAULT_PROXY_HOST = "167.172.93.190"
DEFAULT_PROXY_PORT = 10800
PROXY_PROTOCOL = "socks5"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RESET = "\033[0m"

session = requests.Session()
stop_event = threading.Event()
file_lock = threading.Lock()

def list_beranda(page: int, jwt_token: str, user_id: int) -> dict:
    """
    Fetch a list of hot anchors (home page) and return a dict of nickname -> room_id.
    Page number is dynamic.
    """
    headers = {
        "User-Agent": APP_VERSION,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "Authorization-token": jwt_token,
        "Cache-Control": "no-cache",
    }

    payload = {
        "classify_id": 0,
        "device_id": str(uuid.uuid4()).replace("-", ""),
        "group_id": 0,
        "home_id": 0,
        "lang": "id",
        "package_type": "haigou-Android",
        "page": page,  # ✅ dynamic page number
        "pkg": "3",
        "time": str(int(time.time())),  # ✅ fresh timestamp
        "type": 1,
        "user_id": user_id,
        "version": APP_VERSION,
    }

    payload["sign"] = generate_sign_from_payload(payload)
    url = "https://api.dazz2.com/api/home/hot_anchor"

    resp = session.post(url, data=json.dumps(payload), headers=headers)
    if resp.status_code != 200:
        print(f"[ListBeranda] Failed with status {resp.status_code}")
        return {}

    result = resp.json()
    room_list = result.get("data", {}).get("data", [])

    # Map nickname → room_id
    return {room.get("nickname"): room.get("room_id") for room in room_list}

def get_all_rooms(jwt, uid):
    all_rooms = {}
    page_num = 1

    while True:
        page_data = list_beranda(page_num, jwt, uid)
        if not page_data or len(page_data) == 0:
            break
        all_rooms.update(page_data)
        print(f"[✓] Loaded page {page_num} → {len(page_data)} rooms")
        page_num += 1
        time.sleep(0.5)

    print(f"[✓] Total rooms loaded: {len(all_rooms)}")
    return all_rooms

def md5_result(token, time_mill):
    salt = "5d206b343f87f2ca3a0aa05c58b9a64d"
    raw = f"{time_mill}{token}{salt}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def compress_message(message):
    json_message = json.dumps(message)
    return zlib.compress(json_message.encode("utf-8"))

def decompress_message(message):
    return zlib.decompress(message).decode("utf-8")

def generate_sign_from_payload(payload):
    if not payload.get("sign"):
        payload["sign"] = hashlib.md5("12345678987654321".encode("utf-8")).hexdigest()

    secret_key = "5d206b343f87f2ca3a0aa05c58b9a64d"
    filtered = {
        k: v
        for k, v in payload.items()
        if k not in ["CREATOR", "serialVersionUID", "sign"]
    }
    sorted_items = sorted(filtered.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    full_string = f"{param_str}&key={secret_key}"
    md5_result = hashlib.md5(full_string.encode("utf-8")).hexdigest()
    return md5_result

def get_199_payload(user_id, room_id, token):
    # This offset is required to reach the Jan 2026 range seen in your logs
    # 1767729678 - 1739281500 = ~28,448,178
    magic_offset = 28448178 
    
    # Generate the 'Future' TimeMill
    time_mill = int(time.time()) + magic_offset
    # t_str = str(time_mill)
    
    # NEW FORMULA: Salt + TimeMill + Token
    # Order discovered in dazz_src_base_199/smali_classes2/app/dazz/live/utils/room_float/j.smali
    sign_data = f"tyxaefcverr4662xse#bfh790jnfe@ss{time_mill}{token}"
    md5_str = hashlib.md5(sign_data.encode()).hexdigest()

    return {
        "body": {
            "DeviceType": 1,
            "EnterType": 0,
            "FuncLevel": 1280,
            "IsSmallDialog": 0,
            "Lang": "id",
            "Md5Str": md5_str,
            "RoomId": int(room_id),
            "TimeMill": time_mill,
            "Token": token,
            "UserId": int(user_id),
            "Version": APP_VERSION,
            "package_type": "haigou-Android"
        },
        "op": 1001,
        "ver": 1
    }
def dazz_websocket(ROOM_ID, USER_ID, TOKEN_ID, PROXY_CONFIG=None):
    """
    Establishes and maintains a WebSocket connection, handling messages
    and ensuring robust operation with proper error handling and file locking.
    """

    def send_ws_payload(ws_conn, payload):
        """Sends a JSON payload over the WebSocket connection."""
        try:
            if ws_conn and ws_conn.connected:
                ws_conn.send(json.dumps(payload))
                return True
            return False
        except (WebSocketConnectionClosedException, ConnectionResetError):
            return False # Fail silently if connection is already known to be closed
        except Exception as e:
            print(f"[{USER_ID}] Unexpected error during send: {e}")
            return False

    def initial_join_or_update_and_send_join(ws_conn):
        join_payload = get_199_payload(USER_ID,ROOM_ID,TOKEN_ID)
        return send_ws_payload(ws_conn, join_payload)

    for attempt in range(1, MAX_RETRY + 1):
        # *** FIX: Check the stop event before any new connection attempt ***
        if stop_event.is_set():
            print(f"[{USER_ID}] Stop event detected. Terminating connection attempts.")
            break

        ws = None # Ensure ws is reset for each attempt
        try:
            proxy_info = PROXY_CONFIG or {}
            print(
                f"[{USER_ID}] Attempt {attempt}/{MAX_RETRY}: Connecting via proxy "
                f"{proxy_info.get('http_proxy_host')}:{proxy_info.get('http_proxy_port')}"
            )

            ws = create_connection(WS_URL, **proxy_info)

            if not initial_join_or_update_and_send_join(ws):
                raise ConnectionError("Failed to send initial join payload after connecting.")

            print(f"[{USER_ID}] Successfully connected to room {ROOM_ID}")

            # Main message receiving loop
            while not stop_event.is_set():
                try:
                    message = ws.recv()
                    # if not message:
                    #     raise WebSocketConnectionClosedException("Received empty message (connection dropped)")

                    MSGData = json.loads(message)
                    OP_TYPE = MSGData.get("op")

                    if OP_TYPE and OP_TYPE > 2000:
                        body = MSGData.get("body", {})
                        print(f"{GREEN}({USER_ID}){RESET} receives updates..")
                        if not isinstance(body, dict): continue

                        # Instance untuk ngenalin lb global (with file lock)
                        if OP_TYPE == 2100 and "LuckyBagData" in body:
                            lb = body.get("LuckyBagData", {})
                            countdown = lb.get("CountDown", 0)
                            if countdown > 0:
                                os.system("clear") # This remains disruptive but is part of original logic


                        if "sudah habis" in body.get("ErrStr", "").lower():
                            continue

                        LB_EXE = body.get("ID", "")
                        status = body.get("Status", 0)
                        if LB_EXE and status == 1:
                            for _ in range(7):
                                send_ws_payload(ws, {"body": {"ID": LB_EXE}, "op": 2101, "ver": 1})
                                print(f"[{USER_ID}] Executed lucky bag {GREEN}{LB_EXE}{RESET}")
                                time.sleep(0.5)

                except WebSocketConnectionClosedException:
                    print(f"[{USER_ID}] {RED}Connection lost.{RESET} Will attempt to reconnect.")
                    break # Break inner loop to trigger outer reconnect loop
                except json.JSONDecodeError:
                    print(f"[{USER_ID}] Invalid JSON received, skipping message.")
                    continue
                except Exception as inner_e:
                    print(f"[{USER_ID}] Unexpected error in message loop: {inner_e}")
                    break

            # If the stop event was set, we need to exit the main retry loop
            if stop_event.is_set():
                break

            # If the inner while loop broke due to an error (not stop_event), we continue to the retry logic
            # If it exited cleanly (which it can't in this logic, but for completeness), we break the retry loop
            if ws and ws.connected:
                # This part is now less likely to be reached unless you add a clean exit condition
                print(f"[{USER_ID}] WebSocket closed cleanly.")
                break

        except Exception as e:
            print(f"[{USER_ID}] Connection attempt {attempt}/{MAX_RETRY} failed: {e}")


        finally:
            # Always ensure the socket is closed before the next attempt or exit
            if ws:
                try:
                    ws.close()
                except:
                    pass

        # *** FIX: Honor the stop_event during the reconnect delay ***
        if attempt < MAX_RETRY:
            print(f"[{USER_ID}] Reconnecting in {RECONNECT_DELAY} seconds...")
            # This will wait for the delay but will exit immediately if the event is set
            stop_event.wait(timeout=RECONNECT_DELAY)
        else:
            print(f"[{USER_ID}] Giving up after {MAX_RETRY} failed attempts.")

    print(f"[{USER_ID}] dazz_websocket function finished.")

def _build_headers(app_version: str, jwt_token: str) -> dict:
    return {
        "User-Agent": app_version,
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "cache-control": "no-cache",
        "authorization-token": jwt_token,
    }

def get_user_info(user_id: str, jwt_token: str, timeout: int = 15) -> dict:
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
        headers = _build_headers(APP_VERSION, jwt_token)

        resp = session.post(
            "https://api.dazz2.com/api/member/info", 
            json=payload, 
            headers=headers,
            timeout=timeout
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Failed to get user info for {user_id}: {e}")
        return {"data": {"gold": 0, "nickname": "ERROR"}}

def check_gold_from_file(file_path):
    results = []
    with open(file_path, "r") as f:
        i=0
        for line in f:
            if not line.strip():
                continue
            try:
                userid, jwt, token = line.strip().split(",", 2)

                if not jwt:
                    continue

                user_info = get_user_info(userid, jwt)
                gold = user_info.get("data", {}).get("gold", 0)
                nick = user_info.get("data", {}).get("nickname", "N/A")

                print(f"[{i+1}] {nick} ({userid}) => Gold: {gold}")
                results.append({"userid": userid, "gold": gold, "token":token, "jwt":jwt})

                i += 1
                
            except Exception as e:
                print(f"[!] Error processing line '{line.strip()}': {e}")
    return results

def check_point(file_name: str):
    """Check gold balance and segregate accounts. Thread-safe."""
    if not os.path.isfile(file_name):
        logger.error(f"Input file not found: {file_name}")
        return

    logger.info(f"Processing {file_name}")
    results = check_gold_from_file(file_name)
    
    if not results:
        logger.warning(f"No accounts found in {file_name}")
        return

    to_black = [v for v in results if v["gold"] > 100]
    current_acc = [v for v in results if v["gold"] <= 100]
    total_gold = sum(r.get('gold', 0) for r in results)

    # Thread-safe file operations
    with file_lock:
        # Update main file with zero-gold accounts
        try:
            with open(file_name, "w") as f:
                f.write("\n".join([f"{v['userid']},{v['jwt']},{v['token']}" for v in current_acc]))
            logger.info(f"'{file_name}' updated with {len(current_acc)} zero-gold accounts")
        except IOError as e:
            logger.error(f"Failed to write to {file_name}: {e}")

        # Append gold accounts to blacklist
        if to_black:
            try:
                with open(DEFAULT_BLACK_FILE, "a") as f:
                    f.write("\n".join([f"{v['userid']},{v['jwt']},{v['token']}" for v in to_black]))
                    f.write("\n")
                logger.info(f"'{DEFAULT_BLACK_FILE}' updated with {len(to_black)} gold-bearing accounts")
            except IOError as e:
                logger.error(f"Failed to write to {DEFAULT_BLACK_FILE}: {e}")

    logger.info(f"Summary - Processed: {len(results)}, Kept: {len(current_acc)}, Blacklisted: {len(to_black)}, Total Gold: {total_gold}")

def close_session():
    """
    Tukang tutup sesi requests
    """
    global session
    try:
        session.close()
    except Exception:
        pass
    session = requests.Session()

def set_proxy(proxy_data):
    if not proxy_data or not isinstance(proxy_data, dict):
        logger.error("Invalid proxy data provided to set_proxy()")
        return None

    proto = str(proxy_data.get("protocol", "")).lower()
    ip = proxy_data.get("ip")
    try:
        port = int(proxy_data.get("port") or 0)
    except Exception:
        port = 0

    if not ip or not port:
        logger.error(f"Invalid proxy values: ip={ip!r}, port={port!r}")
        return None

    if not SOCKS_AVAILABLE:
        logger.error("Cannot set proxy: PySocks (socks) library not installed")
        return None

    if proto == "socks5":
        socks.set_default_proxy(socks.SOCKS5, ip, port)
        socket.socket = socks.socksocket
        return {"http_proxy_host": ip, "http_proxy_port": port}

    if proto == "socks4":
        socks.set_default_proxy(socks.SOCKS4, ip, port)
        socket.socket = socks.socksocket
        return {"http_proxy_host": ip, "http_proxy_port": port}

    logger.error(f"Unsupported proxy protocol: {proto}")
    return None

def checkpoint_daemon(account_file=DEFAULT_ACCOUNT_FILE):
    """Background task: check accounts and update blacklist safely.
    
    Resets proxy to avoid stale connections from the main loop.
    Uses direct connection (no proxy) for checkpoint operations.
    """
    original_socket = socket.socket  # Save current socket state
    try:
        logger.info("Running checkpoint daemon...")
        
        # Reset global socket to direct connection (no proxy)
        socket.socket = ORIGINAL_SOCKET
        
        check_point(account_file)
        logger.info("Checkpoint completed successfully")
    except Exception as e:
        logger.error(f"Checkpoint daemon error: {e}", exc_info=True)
    finally:
        # Restore whatever socket was active (likely SOCKS proxy for main loop)
        socket.socket = original_socket
        # Ensure session is fresh for next cycle
        close_session()

if __name__ == "__main__":
    # Configuration
    jwt, uid = ("eyJ0eXAiOiJKV1QiLCJhbGciOiJTSEEyNTYifQ", 19231496)
    proxy_host = DEFAULT_PROXY_HOST
    proxy_port = DEFAULT_PROXY_PORT
    account_file = DEFAULT_ACCOUNT_FILE

    logger.info(f"Starting with proxy {proxy_host}:{proxy_port}")

    while True:
        try:
            logger.info("=" * 60)
            logger.info("Starting new cycle...")
            
            # Run checkpoint with error protection
            try:
                checkpoint_daemon(account_file)
            except Exception as e:
                logger.error(f"Checkpoint failed, continuing anyway: {e}")
            
            close_session()
            # input()

            # Wait for account file
            while not os.path.isfile(account_file):
                logger.warning(f"File {account_file} not found, retrying in 10s...")
                time.sleep(10)

            # Load accounts
            try:
                with open(account_file) as fp:
                    akun_list = [line.strip() for line in fp if line.strip()]
            except IOError as e:
                logger.error(f"Failed to read {account_file}: {e}")
                time.sleep(10)
                continue

            if not akun_list:
                logger.warning(f"No accounts found in {account_file}")
                time.sleep(10)
                continue

            stop_event.clear()
            threads = []

            page = get_all_rooms(jwt, uid)
            nicknames = list(page.keys())

            if not nicknames:
                logger.warning("No rooms found")
                time.sleep(REFRESH_INTERVAL)
                continue

            acc_index = 0
            total_acc = len(akun_list)

            for nick in nicknames:
                if acc_index >= MAX_WORKER:
                    logger.info(f"Reached MAX_WORKER limit ({MAX_WORKER})")
                    break

                room_id = int(page[nick])
                logger.info(f"Entering room: {nick} (ID: {room_id})")

                group = akun_list[acc_index : acc_index + ACCOUNT_PER_ROOM]
                if not group:
                    logger.warning("No more accounts available")
                    break

                # Rotate proxy every 10 accounts
                if acc_index % 10 == 0:
                    proxy_port += 1
                    proxy_config = set_proxy({
                        "protocol": PROXY_PROTOCOL,
                        "ip": proxy_host,
                        "port": proxy_port,
                    })
                else:
                    proxy_config = None

                for user in group:
                    USER_ID, JWT, TOKEN_ID = user.split(",", 2)
                    t = threading.Thread(
                        target=dazz_websocket,
                        args=(room_id, int(USER_ID), TOKEN_ID, proxy_config),
                    )
                    t.daemon = True
                    t.start()
                    threads.append(t)
                    logger.info(f"[{USER_ID}] Joined room {room_id}")
                    time.sleep(1)

                logger.info(f"{len(group)} account(s) joined room {room_id}")
                acc_index += ACCOUNT_PER_ROOM

                if acc_index >= total_acc:
                    logger.info("All accounts deployed")
                    break

            logger.info("All rooms processed")
            logger.info(f"Sleeping for {REFRESH_INTERVAL // 60} minutes ({REFRESH_INTERVAL}s)...")
            proxy_port = DEFAULT_PROXY_PORT
            
            try:
                time.sleep(REFRESH_INTERVAL)
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt during sleep")
                raise  # Re-raise to be caught by outer except

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt detected. Stopping all threads...")
            stop_event.set()
            for t in threads:
                t.join(timeout=3)
            logger.info("All threads stopped")
            break
        except Exception as e:
            logger.error(f"Error in main cycle: {e}", exc_info=True)
            logger.info("Waiting 30s before retrying...")
            time.sleep(30)  # Brief wait before retry instead of full interval
        finally:
            logger.info("Cleanup: stopping all threads...")
            stop_event.set()
            for t in threads:
                try:
                    t.join(timeout=3)
                except:
                    pass
            threads.clear()
            stop_event.clear()
            logger.info("Cycle complete, ready for next iteration")


