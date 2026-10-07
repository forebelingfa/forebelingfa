#!/usr/bin/env python
import os, time, json, uuid, asyncio, aiohttp, pathlib, requests
from api import load_cache, get_jwt, generate_sign_from_payload
from constant import favorite_anchors

# --- CONFIG ---
STATE_FILE = pathlib.Path("live_state.json")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8238863113:AAFuWYtwdjHayW1Gx5cihabRUhqSV3pBTDk")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "1700506814")

DAZZ_BASE = "https://api.dazz2.com/api"
CHECK_INTERVAL = 1   # seconds between checks


# --- TELEGRAM UTILS ---
async def send_telegram(text: str):
    """Send message to Telegram bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload) as r:
            if r.status != 200:
                print("[Telegram Error]", r.status, await r.text())


# --- API FETCH ---
def list_beranda(page: int, jwt_token: str, user_id: int) -> list:
    """Fetch a page of online anchors."""
    headers = {
        "User-Agent": "1.8.6",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "Authorization-token": jwt_token,
        "Cache-Control": "no-cache",
    }

    payload = {
        "classify_id": 0,
        "device_id": str(uuid.uuid4()),
        "group_id": 0,
        "home_id": 0,
        "lang": "id",
        "package_type": "haigou-Android",
        "page": page,
        "pkg": "3",
        "time": str(int(time.time())),
        "type": 1,
        "user_id": user_id,
        "version": "1.8.6",
    }

    payload["sign"] = generate_sign_from_payload(payload)
    url = f"{DAZZ_BASE}/home/hot_anchor"

    try:
        resp = requests.post(url, data=json.dumps(payload), headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        anchors = data.get("data", {}).get("data", [])
        return [a.get("user_id") for a in anchors]
    except Exception as e:
        print(f"[ListBeranda] Error: {e}")
        return []


# --- STATE HANDLING ---
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


# --- MAIN CHECK ---
async def run_check():
    state = load_state()
    cache = load_cache()

    uid = 19231496
    pw = ""
    jwt = "eyJ0eXAiOiJKV1QiLCJhbGciOiJTSEEyNTYifQ.eyJpc3MiOiJoaWdvIiwiaWF0IjoxNzYxNzQ0MTQxLCJleHAiOjE3NjIzNDg5NDEsInVzZXJfaWQiOjE5MjMxNDk2fQ.2912a0b3d7d6608553bd4573d45e3475f97313596e24ed87786ba103a2bd5ce5"
    if not jwt:
        print("[!] Failed to get JWT token")
        return

    # Fetch all pages of online anchors
    page = 1
    online_ids = []
    while True:
        page_data = list_beranda(page, jwt, uid)
        if not page_data:
            break
        online_ids.extend(page_data)
        page += 1

    new_state = {}
    print("\n=== Checking Favorites ===")
    for name, fav_id in favorite_anchors.items():
        is_online = fav_id in online_ids
        prev = state.get(str(fav_id), 0)
        new_state[str(fav_id)] = int(is_online)

        if is_online and prev == 0:
            text = f"🔴 {name} just went LIVE! (LINK: https://h5.dazz2.com/shareapp?anchor_id={fav_id})"
            print(text)
            await send_telegram(text)
        elif not is_online and prev == 1:
            text = f"⚫ {name} went offline. (ID: {fav_id})"
            print(text)
            await send_telegram(text)
        else:
            print(f"[=] {name} is {'ONLINE' if is_online else 'offline'} (no change)")

    save_state(new_state)


# --- LOOP FOREVER ---
async def main():
    while True:
        print(f"\n[Watcher] Checking at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        await run_check()
        print(f"[Watcher] Sleeping {CHECK_INTERVAL}s...")
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
