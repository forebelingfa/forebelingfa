#!/usr/bin/env python

import threading, sys, random, os
import websocket, json, time, hashlib
from api import get_room_id, get_user_info
from constant import favorite_anchors

# Color codes for terminal output
class Color:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    UNDERLINE = '\033[4m'
    
    # Foreground colors
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    
    # Background colors
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    
    @staticmethod
    def banner(text, color=None):
        """Create a colored banner text"""
        c = color or Color.CYAN
        return f"{Color.BOLD}{c}{text}{Color.RESET}"
    
    @staticmethod
    def success(text):
        return f"{Color.GREEN}{Color.BOLD}✓ {text}{Color.RESET}"
    
    @staticmethod
    def warning(text):
        return f"{Color.YELLOW}{Color.BOLD}⚠ {text}{Color.RESET}"
    
    @staticmethod
    def error(text):
        return f"{Color.RED}{Color.BOLD}✗ {text}{Color.RESET}"
    
    @staticmethod
    def info(text):
        return f"{Color.CYAN}{Color.BOLD}ℹ {text}{Color.RESET}"

WS_URL = "ws://13.213.254.163:9001"

SALT = "5d206b343f87f2ca3a0aa05c58b9a64d"

def md5_result(token, time_mill):
    raw = f"{time_mill}{token}{SALT}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def send(ws, payload):
    ws.send(json.dumps(payload, separators=(",", ":")))

def make_ws_client(room_id, user_id, token, initial_balance=None, stop_event=None, max_runtime=300):
    def on_open(ws):
        # Store initial balance from API on the ws object
        if initial_balance is not None:
            ws.initial_saldo = initial_balance
            ws.initial_saldo_set = True
        else:
            ws.initial_saldo_set = False
            ws.initial_saldo = 0
        i = 0
        milli = int(time.time() * 1000)
        md5str = md5_result(token, milli)

        join_payload = {
        "ver": 1,
        "op": 1001,
        "body": {
            "RoomId": room_id,
            "Token": token,
            "UserId": user_id,
        },
    }
        send(ws, join_payload)

        def gifting():
            nonlocal i
            gift_payload = {
                "ver": 2,
                "op": 1069,
                "body": {
                    "Code": 0, "InRoomId": room_id, "GiftVipId": 1, "DUserId": receiver_id,
                }
            }
            while True:
                try:
                    rose_bucket = 57
                    basic = 135
                    emas_bunga = 172
                    bombar_dazz = 225
                    carnival = 127
                    jamet = [174, 171, 171, 171]
                    little_jamet = [ basic, basic, basic, 174 ]
                    gift_5500 = [ 57, 245, 166 ]
                    gift_10k = [ 246, 167, 83, 225 ]
                    bunga_murni = 142
                    dih_pelit_bet_anj = random.choice([11, 0, 0, 2, 1, 0.00, 1, 99999999.9])
                    mencari_cari_jp_gift_ids = random.choice(little_jamet)


                    gift_payload['body']['GiftId'] = mencari_cari_jp_gift_ids
                    gift_payload['body']['GiftCount'] = dih_pelit_bet_anj
                    send(ws, gift_payload)
                    i += 1

                    # time.sleep(2)
                except Exception:
                    break

        def heartbeat():
            heartbeat_count = 1
            for _ in range(3):
                try:
                    payload = {
                    "ver": 1,
                    "op": 1002,
                    "body": {
                        "ChatType": 0,
                        "Content": str(heartbeat_count),
                        "DUserID": 0,
                        "SUserId": user_id,
                        "SNickName": "",
                        "Gold": 0,
                        "ConsumeLevel": 91,
                    },
                }
                    send(ws, payload)
                    print(f"[WS-{room_id}] ping...{user_id} - {heartbeat_count}")
                    # time.sleep(3)
                    heartbeat_count += 1
                except Exception:
                    break


        threading.Thread(target=heartbeat, daemon=True).start()
        # threading.Thread(target=gifting, daemon=True).start()

        # Start a watchdog that will close the WS after `max_runtime` seconds
        def _watchdog():
            start = time.time()
            while True:
                # If stop requested externally, close the connection
                if stop_event is not None and stop_event.is_set():
                    try:
                        print(Color.warning(f"[WS-{room_id}] Stop event set for user {user_id}, closing connection"))
                        ws.close()
                    except Exception:
                        pass
                    break
                # Close if runtime exceeded
                if max_runtime is not None and (time.time() - start) > max_runtime:
                    try:
                        print(Color.warning(f"[WS-{room_id}] Max runtime {max_runtime}s exceeded for user {user_id}, closing connection"))
                        ws.close()
                    except Exception:
                        pass
                    break
                # If the socket has been closed by other means, exit watchdog
                time.sleep(1)

        threading.Thread(target=_watchdog, daemon=True).start()

    def on_message(ws, message):
        try:
            data = json.loads(message)
            body = data.get("body", {})
            # print(data)


            current_saldo = body.get("SGold")
            # Ensure current_saldo is a valid number; otherwise, treat as if SGold wasn't present
            if not isinstance(current_saldo, (int, float)):
                current_saldo = None

            # --- Saldo tracking and comparison logic ---
            if current_saldo is not None:
                # If initial_saldo has already been set (from API), compare current_saldo to it
                if ws.initial_saldo_set:
                    if current_saldo > ws.initial_saldo:
                        print(Color.success(f"Saldo increased from {ws.initial_saldo} to {current_saldo}. Closing connection."))
                        ws.close()
                        return # Exit early as connection is closing
                

            # --- Other message handling ---
            if data.get("body", {}).get("Code") == 1021:
                print(Color.error("Connection terminated by server (Code 1021)"))
                ws.close()
                return

            if data.get("op") > 2000:
                # print(f"[User-{user_id}][WS-{room_id}] {message[:80]}")
                LB_EXE = body.get("ID")
                if LB_EXE:
                    send(ws, {"body": {"ID": LB_EXE}, "op": 2101, "ver": 1})
                    time.sleep(1)

            if data.get("op") > 3000:
                send(ws, data)

            # --- Check against max_amt (use current_saldo if available, otherwise default to 0) ---
            saldo_for_max_amt_check = current_saldo if current_saldo is not None else 0
            if saldo_for_max_amt_check >= max_amt:
                print(Color.error(f"Saldo threshold reached ({saldo_for_max_amt_check} >= {max_amt}). Closing..."))
                ws.close()
                return

        except Exception as e:
            print(e)
            print(f"[WS-{room_id}] Raw:", message)

    def on_error(ws, error):
        print(f"{Color.error(f'[WS-{room_id}]')} {error}")

    def on_close(ws, code, msg):
        print(f"{Color.warning(f'[WS-{room_id}]')} Closed: {code} {msg}")

    return websocket.WebSocketApp(
        WS_URL,
        header=["User-Agent: okhttp/4.8.1", "Accept-Encoding: gzip"],
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

def run_room(room_id: int, user_id: int, token: str, proxy_config: dict, initial_balance: int = None, stop_event=None, max_runtime=300):
    if not token:
        print(f"[WS-{room_id}] No token, debugging harus")
        return

    ws = make_ws_client(room_id, user_id, token, initial_balance, stop_event=stop_event, max_runtime=max_runtime)
    try:
        ws.run_forever(ping_interval=30, ping_timeout=10, **proxy_config)
    except Exception as e:
        print(Color.error(f"[WS-{room_id}] Exception in run_forever: {e}"))

def set_proxy(proxy_data):
    """Returns a dictionary of keyword arguments for the WebSocketApp constructor."""
    proto = proxy_data.get("protocol", "").lower()
    ip = proxy_data.get("ip", "")
    port = int(proxy_data.get("port", 0))
    if not ip or not port: return None
    if proto in ["http", "https"]: return {"http_proxy_host": ip, "http_proxy_port": port}
    if proto in ["socks4", "socks5"]: return {"proxy_type": proto, "http_proxy_host": ip, "http_proxy_port": port}
    return None

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    # _MEIPASS is the temporary directory where PyInstaller extracts files
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

def check_user_balance(user_id: str, jwt: str) -> dict:
    """
    Check initial user balance before gifting
    Returns: {"success": bool, "balance": int, "nickname": str, "error": str}
    """
    try:
        user_info = get_user_info(user_id, jwt)
        gold = user_info.get("data", {}).get("gold", 0)
        nickname = user_info.get("data", {}).get("nickname", "Unknown")
        
        return {
            "success": True,
            "balance": int(gold),
            "nickname": nickname,
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "balance": 0,
            "nickname": None,
            "error": str(e)
        }

if __name__ == "__main__":
    _single_gift = 0
    _nama_akun = 'poor'
    _portnya = 10801
    _hostnya = '167.172.93.190'
    _proxy = {"protocol": "socks5", "ip": _hostnya, "port": _portnya}

    gift_id = 0
    max_amt = 1000000
    uid = 19762521
    gtg = 19715765
    cika = 13142383
    ucup = 16215415
    pw = 'hellofool31'

    anchor_id =  favorite_anchors.get("test")
    receiver_id = [ucup]
    jwt = 'eyJ0eXAiOiJKV1QiLCAiYWxnIjoiU0hBMjU2In0'
    room_id = get_room_id(anchor_id, jwt)

    
    input({'room_id': room_id, 'receiver': receiver_id, 'jwt': str(jwt)[:30]})

    if _single_gift:
        user_id=19715765
        token="42931f7197299770"
        jwt = "eyJ0eXAiOiJKV1QiLCJhbGciOiJTSEEyNTYifQ.eyJpc3MiOiJoaWdvIiwiaWF0IjoxNzY1MzAxMzg3LCJleHAiOjE3NjU5MDYxODcsInVzZXJfaWQiOjE5NzE1NzY1LCJ0b3VyaXN0X3VyaSI6IiJ9.a9a41fc3e93fec66279075f0a336ff7fb42ae9023e7e3fce51b1efa82a9572ff"

        # Check user balance before spawning worker
        print(Color.info(f"Checking balance for UID {user_id}..."))
        balance_info = check_user_balance(user_id, jwt)

        if not balance_info["success"]:
            print(Color.error(f"Failed to check balance for UID {user_id}: {balance_info['error']}"))


        nickname = balance_info["nickname"]
        initial_gold = balance_info["balance"]
        print(Color.success(f"UID {user_id} ({nickname}) - Initial Balance: {initial_gold} gold"))
        run_room(room_id=room_id, user_id=user_id, token=token, proxy_config={}, initial_balance=initial_gold, max_runtime=600)
        sys.exit(0)


    file_path = resource_path(_nama_akun)
    try:

        with open(file_path, "r") as f:
            c = 0
            d = 20
            # active_threads will hold tuples of (thread, stop_event)
            active_threads = []
            # How long a single WS worker is allowed to run before watchdog closes it (seconds)
            MAX_RUNTIME = 300
            # How long to wait for a worker to join at checkpoint before signaling stop
            PER_THREAD_JOIN_TIMEOUT = 30

            for akun in f.read().splitlines():
                proxy_config = {}

                if c % d == 0 and c > 0:
                    input()
                    # Wait for all active threads to complete (with timeouts)
                    print(Color.banner(f"\n{'='*60}", Color.MAGENTA))
                    print(Color.warning(f"CHECKPOINT #{c//d}: Waiting for {len(active_threads)} worker(s) to finish..."))
                    print(Color.banner(f"{'='*60}\n", Color.MAGENTA))

                    # Join with timeout; if a thread is still alive after the timeout,
                    # request it to stop via its stop_event and continue.
                    for thread, stop_ev in active_threads:
                        thread.join(timeout=PER_THREAD_JOIN_TIMEOUT)
                        if thread.is_alive():
                            print(Color.warning(f"Thread for UID still alive after {PER_THREAD_JOIN_TIMEOUT}s; signalling stop."))
                            stop_ev.set()

                    # Give them a short grace period to finish after signalling
                    for thread, stop_ev in active_threads:
                        if thread.is_alive():
                            thread.join(timeout=5)

                    # Report any threads still alive
                    still_alive = [t for t, ev in active_threads if t.is_alive()]
                    if still_alive:
                        print(Color.error(f"{len(still_alive)} worker(s) still alive after signalling; continuing anyway."))

                    active_threads = []
                    print(Color.success(f"All workers completed. Resuming..."))
                    print(Color.banner(f"{'='*60}\n", Color.GREEN))
                    time.sleep(1)

                uid, jwt, token = akun.split(",", 2)

                
                stop_ev = threading.Event()
                thread = threading.Thread(
                    target=run_room,
                    kwargs={"room_id": room_id, "user_id": int(uid), "token": token, "proxy_config": proxy_config, "initial_balance": 0, "stop_event": stop_ev, "max_runtime": MAX_RUNTIME},
                    daemon=False,
                )
                thread.start()
                active_threads.append((thread, stop_ev))
                c += 1
                # time.sleep(random.randint(1,5))

            # Wait for final batch of threads to complete
            print(Color.banner(f"\n{'='*60}", Color.CYAN))
            print(Color.warning(f"FINAL CHECKPOINT: Waiting for {len(active_threads)} worker(s) to finish..."))
            print(Color.banner(f"{'='*60}\n", Color.CYAN))

            for thread, stop_ev in active_threads:
                thread.join(timeout=PER_THREAD_JOIN_TIMEOUT)
                if thread.is_alive():
                    print(Color.warning(f"Final join: worker still alive after {PER_THREAD_JOIN_TIMEOUT}s; signaling stop."))
                    stop_ev.set()

            # Give them a short grace period
            for thread, stop_ev in active_threads:
                if thread.is_alive():
                    thread.join(timeout=5)

            alive_final = [t for t, ev in active_threads if t.is_alive()]
            if alive_final:
                print(Color.error(f"{len(alive_final)} worker(s) still alive at final checkpoint; they will be left running."))
            else:
                print(Color.success(f"All gifting operations completed!"))

            input(f"{Color.CYAN}Sedang menunggu kawan kawan selesai nge-gift.{Color.RESET}")
    except KeyboardInterrupt:
        print(Color.error("Operation interrupted by user!"))
        exit()
    except Exception as e:
        print(Color.error(f"Error: {e}"))
