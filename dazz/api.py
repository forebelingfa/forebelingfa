#!/usr/bin/env python

import time
import hashlib
import json
import requests
import uuid
import os
import threading
from typing import Dict, Any, List, Union
from faker import Faker
from constant import APP_VERSION, DAZZ_BASE


BASE_URL = "https://api.dazz2.com/api/"
SIMPLE_LOGIN = "simple/login"
MEMBER_INFO = "member/info"
CHANGE_PIC_URL = "https://13.213.254.163/api/member/picture_resource"
INTR_URL = "https://13.213.254.163/api/member/intr"
MODIFY_INFO_URL = "https://13.213.254.163/api/member/modify_info"
GOOGLE_AUTH_URL = "https://13.213.254.163/api/go_v3/dazz/google_auth"
CLASSIFY_LIST_URL = "https://13.213.254.163/api/home/classify_list"
SYSMSG_TOKEN_URL = "https://13.213.254.163/api/go_v3/dazz/sysmsg_tken"
H5_BASE = "https://h5.idlive.xin/api/"


SECRET_KEY = "5d206b343f87f2ca3a0aa05c58b9a64d"
STATIC_SIGN = hashlib.md5("12345678987654321".encode("utf-8")).hexdigest()

session = requests.Session()
def user_agent():
    return Faker().user_agent()

AKUN_DIR = "akun"
CACHE_FILE = os.path.join(AKUN_DIR, "jwt_cache.json")
JWT_TTL = 3600 * 24 * 7


def load_cache():
    if os.path.isfile(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

def get_jwt(userid, password, cache):
    now = int(time.time())
    entry = cache.get(userid)
    # print(entry)

    if entry and entry["password"] == password and now - entry["ts"] < JWT_TTL:
        return entry.get("jwt")

    login_resp = login_web(userid, password)
    if login_resp.get("code") != 0:
        print(f"[-] Login failed for {userid}: {login_resp}")
        return None

    jwt = login_resp["data"].get("jwt_authorization_token")
    token = login_resp["data"].get("token")

    if not jwt:
        print(f"[-] No JWT for {userid}")
        return None

    cache[userid] = {"password": password, "jwt": jwt, "ts": now, "token": token}
    return jwt

def get_token(userid, password, cache):
    now = int(time.time())
    entry = cache.get(userid)

    if entry and entry["password"] == password and now - entry["ts"] < JWT_TTL:
        return entry["token"]

    login_resp = login_web(userid, password)
    if login_resp.get("code") != 0:
        print(f"[-] Login failed for {userid}: {login_resp}")
        return None

    token = login_resp["data"].get("token")

    if not token:
        print(f"[-] No Token for {userid}")
        return None

    cache[userid] = {"password": password, "ts": now, "token": token}
    return token

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

def login_dazz(userid, password):
    payload = {
        "code_type": 0,
        "pwd_str": f"{password}",
        "type": 20,
        "app_version": APP_VERSION,
        "channel_id": "3",
        "device_id": str(uuid.uuid4()).replace("-",""),
        "facility": "1",
        "lang": "id",
        "package_type": "Android-Google",
        "sign": "",
        "time": f"{int(time.time())}",
        "user_id": f"{userid}",
    }

    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "User-Agent": APP_VERSION,
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json",
        "encrypt-type": "1",
        "content-type": "application/json; charset=UTF-8",
        "cache-control": "no-cache",
    }

    response = session.post(
        BASE_URL + SIMPLE_LOGIN, data=json.dumps(payload), headers=headers
    )
    return response.json()

def generate_sign(payload, secret_key="yf76yzK79GYqfPhxF4VW2QY7WXqkZNqB"):
    sorted_keys = sorted(payload.keys())
    query_string = ""
    for key in sorted_keys:
        query_string += f"{key}={payload[key]}&"
    
    # Tambahkan secret key
    query_string += f"key={secret_key}"
    
    # Encrypt dengan MD5
    sign = hashlib.md5(query_string.encode('utf-8')).hexdigest()
    
    return sign

def login_web(userId, password):
    """
    return respanse.json()
    """
    payload = {
        "user_id": userId,
        "lpwd": password,
        "lang": "id",
        "time": str(int(time.time()))
    }

    payload['sign'] = generate_sign(payload)

    payload_json = json.dumps(payload)
    content_length = len(payload_json)

    #UDAH GOSAH DI OTAK-ATIK DAH BENER
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        "content-type": "application/json",
        "sec-ch-ua": "\"Chromium\";v=\"134\", \"Not:A-Brand\";v=\"24\", \"Google Chrome\";v=\"134\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "referrer": "https://www.dazz.live/",
        "referrerPolicy": "strict-origin-when-cross-origin",
        "Content-Length": str(content_length)
    }

    url = "https://www.dazz.live/web/pc_go/dazz/userid_login"

    respanse = requests.post(url, headers=headers, data=payload_json)

    return respanse.json()

def _build_headers(app_version: str, jwt_token: str) -> Dict[str, str]:
    return {
        "User-Agent": app_version,
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "cache-control": "no-cache",
        "authorization-token": jwt_token,
    }

def get_user_info(user_id: str, jwt_token: str, timeout: int = 10) -> Dict[str, Any]:
    payload = {
        "id": str(user_id),
        "version": "1.0",
        "app_version": APP_VERSION,
        "channel_id": "3",
        "device_id": str(uuid.uuid4()).replace("-",""),
        "facility": "1",
        "lang": "id",
        "package_type": "Android-Google",
        "sign": "",
        "time": str(int(time.time())),
        "user_id": str(user_id),
    }
    payload["sign"] = generate_sign_from_payload(payload)
    headers = _build_headers(APP_VERSION, jwt_token)

    # network operations should use a finite timeout to avoid worker threads
    # blocking indefinitely and causing executor shutdowns to hang.
    resp = session.post(BASE_URL + MEMBER_INFO, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def get_room_id(user_id: str, jwt_token: str) -> int:
    info = get_user_info(user_id, jwt_token)
    room_id = info.get("data", {}).get("room_id", 0)

    try:
        return int(room_id) if room_id not in (None, "") else 0
    except (ValueError, TypeError):
        return 0


def keep_sign_h5(user_id: str, token: str, config_id: int = 2, lang: str = "id", sign: str = None, ts: int = None) -> Dict[str, Any]:
    """Call the H5 keep_sign endpoint.

    Args:
        user_id: user id (string or numeric)
        token: short token from h5 (string)
        config_id: config id (default 2)
        lang: language code (default 'id')
        sign: optional precomputed sign (if not set it's generated)
        ts: optional unix timestamp (int) — if not provided current time is used

    Returns:
        Parsed JSON response as dict.
    """
    t = str(ts or int(time.time()))
    payload = {
        "sign": sign or "",
        "user_id": int(user_id) if str(user_id).isdigit() else user_id,
        "config_id": config_id,
        "lang": lang,
        "token": token,
        "time": t,
    }

    if not sign:
        payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "User-Agent": APP_VERSION,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Content-Type": "application/json",
        "Origin": "https://h5.idlive.xin",
        "Connection": "keep-alive",
        "Referer": f"https://h5.idlive.xin/task/signtask?user_id={user_id}&token={token}",
        "encrypt-type": "1",
        "cache-control": "no-cache",
    }

    resp = session.post(H5_BASE + "go_v3/dazz/h5/keep_sign", json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()

def change_profile_picture(
    user_id: str,
    jwt_token: str,
    image_path: str,
    app_version: str = APP_VERSION,
    device_id: str = "4610ea917bca043b097f8b4d905a7ee4",
) -> Dict[str, Any]:
    payload = {
        "path": image_path,
        "type": 1,
        "app_version": app_version,
        "channel_id": "3",
        "device_id": device_id,
        "facility": "1",
        "lang": "id",
        "package_type": "Android-Google",
        "sign": "",
        "time": str(int(time.time())),
        "user_id": user_id,
    }
    payload["sign"] = generate_sign_from_payload(payload)
    headers = _build_headers(app_version, jwt_token)

    resp = session.post(CHANGE_PIC_URL, json=payload, headers=headers)
    resp.raise_for_status()
    return resp.json()

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
        "device_id": str(uuid.uuid4()).replace("-",""),
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

def update_intr(user_id: str, jwt_token: str, intr_text: str) -> Dict:
    """
    Update the user's introduction/status text (intr).

    Args:
        user_id: The user ID.
        jwt_token: JWT authorization token.
        intr_text: New introduction/status text.

    Returns:
        JSON response as dict.
    """
    payload = {
        "intr": intr_text,
        "lang": "id",
        "package_type": "haigou-Android",
        "sign": "",
        "time": str(int(time.time())),
        "user_id": user_id,
    }
    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "User-Agent": APP_VERSION,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "Authorization-token": jwt_token,
        "Cache-Control": "no-cache",
    }

    resp = session.post(INTR_URL, data=json.dumps(payload), headers=headers)
    resp.raise_for_status()
    return resp.json()

def update_nickname(user_id: str, jwt_token: str, new_nickname: str) -> Dict:
    """
    Update the user's nickname.

    Args:
        user_id: The user ID.
        jwt_token: JWT authorization token.
        new_nickname: The new nickname to set.

    Returns:
        JSON response as dict.
    """
    payload = {
        "lang": "id",
        "nickname": new_nickname,
        "package_type": "haigou-Android",
        "sign": "",
        "time": str(int(time.time())),
        "user_id": user_id,
    }
    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "User-Agent": APP_VERSION,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "Authorization-token": jwt_token,
        "Cache-Control": "no-cache",
    }

    resp = session.post(MODIFY_INFO_URL, data=json.dumps(payload), headers=headers)
    resp.raise_for_status()
    return resp.json()

def google_auth_login(
    google_id_token: str, is_vpn: str = "0", user_country: str = "ID"
) -> Dict:
    """
    Login via Google ID token.

    Args:
        google_id_token: The Google `id_token` from OAuth (JWT string).
        is_vpn: "0" or "1" depending on network.
        user_country: Country code, e.g. "ID".

    Returns:
        JSON response from the server (contains Dazz token, JWT, user_id, etc.).
    """
    payload = {
        "code": google_id_token,
        "isVpn": is_vpn,
        "type": "google",
        "userCountry": user_country,
        "app_version": APP_VERSION,
        "channel_id": "3",
        "device_id": str(uuid.uuid4()).replace("-",""),
        "facility": "1",
        "lang": "id",
        "package_type": "Android-Google",
        "sign": "",
        "time": str(int(time.time())),
        "user_id": "",
    }
    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "User-Agent": APP_VERSION,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "Cache-Control": "no-cache",
    }

    resp = session.post(GOOGLE_AUTH_URL, data=json.dumps(payload), headers=headers)
    resp.raise_for_status()
    return resp.json()

def clone_user_profile(
    source_user_id: str,
    target_user_id: str,
    target_jwt_token: str,
) -> dict:
    """
    Clone public profile fields (nickname, intro, picture) from any user onto your account.

    Args:
        source_user_id: The user ID to copy from.
        target_user_id: Your account's user ID to apply info to.
        target_jwt_token: Your JWT (target account).

    Returns:
        dict with status for each field.
    """
    result = {"nickname": None, "intr": None, "picture": None}

    # 1. Fetch source public profile (with target JWT)
    source_info = get_user_info(source_user_id, target_jwt_token)
    data = source_info.get("data", {})

    nickname = data.get("nickname")
    print(nickname)
    if nickname:
        try:
            update_nickname(target_user_id, target_jwt_token, nickname)
            result["nickname"] = "ok"
        except Exception as e:
            result["nickname"] = f"failed: {e}"

    intr = data.get("intr")
    if intr:
        try:
            update_intr(target_user_id, target_jwt_token, intr)
            result["intr"] = "ok"
        except Exception as e:
            result["intr"] = f"failed: {e}"

    picture_path = data.get("head_img")
    if picture_path:
        try:
            change_profile_picture(target_user_id, target_jwt_token, picture_path)
            result["picture"] = "ok"
        except Exception as e:
            result["picture"] = f"failed: {e}"

    return result

def update_sysmsg_token(user_id: str, jwt_token: str, fcm_token: str) -> Dict:
    """
    Update or register the system message (push notification) token for a user.

    Args:
        user_id: User ID of the account.
        jwt_token: JWT auth token.
        fcm_token: Firebase/notification token string to register.

    Returns:
        JSON response from the server as dict.
    """
    payload = {
        "token": fcm_token,
        "app_version": APP_VERSION,
        "channel_id": "3",
        "device_id": "4610ea917bca043b097f8b4d905a7ee4",
        "facility": "1",
        "lang": "id",
        "package_type": "Android-Google",
        "sign": "",
        "time": str(int(time.time())),
        "user_id": user_id,
    }
    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "User-Agent": APP_VERSION,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "Authorization-token": jwt_token,
        "Cache-Control": "no-cache",
    }

    resp = session.post(SYSMSG_TOKEN_URL, data=json.dumps(payload), headers=headers)
    resp.raise_for_status()
    return resp.json()

def get_classify_list(user_id: str, jwt_token: str, page: int = 0) -> Dict:
    """
    Get the home classification list (categories / tabs) from Dazz home API.

    Args:
        user_id: User ID of the account.
        jwt_token: JWT auth token.
        page: Page index (usually 0 for classify list).

    Returns:
        JSON response from the server as dict.
    """
    payload = {
        "classify_id": 0,
        "device_id": "4610ea917bca043b097f8b4d905a7ee4",
        "group_id": 0,
        "home_id": 0,
        "lang": "id",
        "package_type": "haigou-Android",
        "page": page,
        "sign": "",
        "time": str(int(time.time())),
        "user_id": user_id,
        "version": "1.0",
    }
    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "User-Agent": APP_VERSION,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "Authorization-token": jwt_token,
        "Cache-Control": "no-cache",
    }

    resp = session.post(CLASSIFY_LIST_URL, data=json.dumps(payload), headers=headers)
    resp.raise_for_status()
    return resp.json()

def follow(user_id: str, jwt_token: str, fId: str, type: str) -> Dict:

    payload = {
        "classify_id": 0,
        "device_id": str(uuid.uuid4()).replace("-",""),
        "group_id": 0,
        "home_id": 0,
        "lang": "id",
        "package_type": "haigou-Android",
        "pkg": "3",
        "time": str(int(time.time())),  # ✅ fresh timestamp
        "type": 1 if type == "follow" else 2,
        "user_id": user_id,
        "version": APP_VERSION,
        "follow_id": fId,
    }

    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "User-Agent": APP_VERSION,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "Authorization-token": jwt_token,
        "Cache-Control": "no-cache",
    }

    resp = session.post(
        "https://api.dazz2.com/api/member/follow",
        data=json.dumps(payload),
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()

def get_stream_token(user_id: int, stream_key: str, jwt_token: str) -> Dict:

    payload = {
        "classify_id": 0,
        "device_id": str(uuid.uuid4()).replace("-",""),
        "group_id": 0,
        "home_id": 0,
        "lang": "id",
        "package_type": "haigou-Android",
        "pkg": "3",
        "time": str(int(time.time())),  # ✅ fresh timestamp
        "type": 1,
        "version": APP_VERSION,
        "channel": stream_key,
        "user_id": user_id,
    }

    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "User-Agent": APP_VERSION,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "Authorization-token": jwt_token,
        "Cache-Control": "no-cache",
    }

    resp = session.post(
        "https://api.dazz2.com/api/home/agora_access",
        data=json.dumps(payload),
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()

def get_stream_detail(user_id: int, room_id: int, jwt_token: str) -> Dict:

    payload = {
        "id": room_id,  # room_id
        "passwd": "123",
        "city_name": "",
        "img": "",
        "is_game_open": 1,
        "lat": "0",
        "lon": "0",
        "room_name": "",
        "type": 1,
        "device_id": str(uuid.uuid4()).replace("-",""),
        "user_id": user_id,
        "lang": "id",
        "pkg": "3",
        "package_type": "haigou-Android",
        "time": str(int(time.time())),
        "version": APP_VERSION,
    }

    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "User-Agent": APP_VERSION,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "Authorization-token": jwt_token,
        "Cache-Control": "no-cache",
    }

    resp = session.post(
        "https://api.dazz2.com/api/video/anchor",
        data=json.dumps(payload),
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()

def broom_specific_accounts(accounts_to_check: List[str]):
    """
    Checks a specific list of accounts, moves any with a gold balance from
    mulung.txt to black.txt. This function is designed to be thread-safe.

    Args:
        accounts_to_check: A list of account lines, e.g., ["USERID,PASSWORD", ...].
    """
    print(f"🧹 Brooming {len(accounts_to_check)} recently used accounts...")
    
    source_file = os.path.join(AKUN_DIR, "mulung.txt")
    archive_file = os.path.join(AKUN_DIR, "black.txt")
    cache = load_cache()

    # --- Read current state of account files ---
    try:
        with open(source_file, "r") as f:
            # Use a set for efficient removal
            mulung_accounts = set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        print(f"Warning: '{source_file}' not found. Cannot broom.")
        return

    # --- Check balances for the specified accounts ---
    accounts_to_move = set()
    for account_line in accounts_to_check:
        try:
            userid, password = account_line.split(",", 1)
            jwt = get_jwt(userid, password, cache) # Uses your new API logic
            if not jwt:
                continue

            user_info = get_user_info(userid, jwt)
            gold = user_info.get("data", {}).get("gold", 0)

            if gold >= 1:
                print(f"  [SUCCESS] User {userid} has {gold} gold. Migrating to black.txt.")
                accounts_to_move.add(account_line)

        except Exception as e:
            print(f"[Broom Error] Could not process account '{account_line}': {e}")
            
    if not accounts_to_move:
        print("✨ Broom complete. No accounts had a balance.")
        return

    # --- Atomically update files ---
    # Remove accounts that are being moved from the mulung set
    remaining_mulung = mulung_accounts - accounts_to_move

    # Write the updated mulung.txt
    with open(source_file, "w") as f:
        f.write("\n".join(sorted(list(remaining_mulung))))
        f.write("\n")

    # Append the successful accounts to black.txt
    with open(archive_file, "a") as f:
        f.write("\n".join(sorted(list(accounts_to_move))))
        f.write("\n")
        
    save_cache(cache)
    print(f"✅ Broom complete. {len(accounts_to_move)} accounts were migrated.")

def export_token_to_txt(output_filename: str, file_jwt_cache: str):


    if os.path.isfile(file_jwt_cache):
        try:
            with open(file_jwt_cache, "r") as f:
                data = json.load(f)
        except Exception:
            print("error pas load data cache")

    with open(output_filename, 'w') as f:
        # Iterate through the items in the data dictionary
        for user_id, user_data in data.items():
            # Get the token from the user_data dictionary
            token = user_data.get("token")

            # Write the id and token to the file, separated by a comma
            if token:
                f.write(f"{user_id},{token}\n")

    print(f"Data has been written to {output_filename}")

def praise_user(user_id, large_user, token):
    payload = {
        "user_id": str(user_id),
        "large_user": int(large_user),
        "lang": "id",
        "token": str(token),
        "time": str(int(time.time())),
    }

    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "Host": "h5.idlive.xin",
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0 (Linux; Android 10; POCO F1 Build/QQ3A.200905.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/90.0.4430.82 Mobile Safari/537.36",
        "content-type": "application/json",
        "origin": "https://h5.idlive.xin",
        "x-requested-with": "app.dazz.live",
        "referer": f"https://h5.idlive.xin/anniversary/wallofhonor?user_id={user_id}&token={token}",
        "accept-encoding": "gzip, deflate",
        "accept-language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    response = session.post(
        "https://h5.idlive.xin/api/dazzact/praiseUser",
        data=json.dumps(payload),
        headers=headers,
    )

    return response.json()

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

def fetch_lucky_bag_rooms(jwt_token: str, user_id: int) -> list:
    """
    Fetches all pages of hot anchors from the API and returns a filtered list
    containing only rooms where red_packet_logo == 1.
    This function replaces the problematic list_beranda from api.py.
    """
    all_filtered_rooms = []
    all_live_room_id = []
    page = 1
    
    headers = {
        "User-Agent": APP_VERSION, "Connection": "Keep-Alive", "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8", "encrypt-type": "1",
        "Authorization-token": jwt_token, "Cache-Control": "no-cache",
    }
    url = f"{DAZZ_BASE}/home/hot_anchor"

    while True:
        payload = {
            "classify_id": 0, "device_id": str(uuid.uuid4()).replace("-",""), "group_id": 0,
            "home_id": 0, "lang": "id", "package_type": "haigou-Android", "page": page,
            "pkg": "3", "time": str(int(time.time())), "type": 1,
            "user_id": user_id, "version": APP_VERSION,
        }
        payload["sign"] = generate_sign_from_payload(payload)

        try:
            resp = requests.post(url, data=json.dumps(payload), headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            # print(data)
            
            live_details = data.get("data", {}).get("data", [])
            if not live_details:
                break # Exit loop if there are no more rooms on the page

            # Filter the rooms on the current page
            page_filtered_rooms = [
                room for room in live_details if room.get("red_packet_logo") == 1
            ]
            all_filtered_rooms.extend(page_filtered_rooms)
            all_live_room_id = [room for room in live_details]
            
            page += 1
            time.sleep(0.5) # Be respectful to the API between page calls

        except requests.RequestException as e:
            print(f"[API Error in Mandor] Failed to fetch page {page}: {e}")
            break # Exit loop on error
        except json.JSONDecodeError:
            print(f"[API Error in Mandor] Failed to decode JSON from page {page}")
            break

    return all_filtered_rooms

def get_task_list(user_id: int, token: str, task_type: str = "1,10", lang: str = "id") -> Dict:
    """
    Get available tasks for the user from the H5 task system.
    
    Args:
        user_id: User ID
        token: User access token
        task_type: Task type filter, comma-separated (default: "1,4" for daily and special tasks)
        lang: Language code (default: "id" for Indonesian)
    
    Returns:
        JSON response with task_config array containing available tasks
    """
    payload = {
        "sign": "",
        "user_id": user_id,
        "task_type": task_type,
        "lang": lang,
        "token": token,
        "time": str(int(time.time()))
    }
    payload["sign"] = generate_sign_from_payload(payload)
    
    headers = {
        "Host": "h5.idlive.xin",
        "User-Agent": user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/json",
        "Origin": "https://h5.idlive.xin",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    
    resp = session.post(
        "https://h5.idlive.xin/api/go_v3/dazz/h5/task_list",
        data=json.dumps(payload),
        headers=headers
    )
    resp.raise_for_status()
    return resp.json()

def apply_task(user_id: int, token: str, task_id: int, lang: str = "id") -> Dict:
    """
    Apply/accept a task for completion by the user.
    
    Args:
        user_id: User ID
        token: User access token
        task_id: Task ID to apply for
        lang: Language code (default: "id" for Indonesian)
    
    Returns:
        JSON response indicating success or failure of task application
    """
    payload = {
        "sign": "",
        "user_id": user_id,
        "task_id": task_id,
        "lang": lang,
        "token": token,
        "time": str(int(time.time()))
    }
    payload["sign"] = generate_sign_from_payload(payload)
    
    headers = {
        "Host": "h5.idlive.xin",
        "User-Agent": user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/json",
        "Origin": "https://h5.idlive.xin",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    
    resp = session.post(
        "https://h5.idlive.xin/api/go_v3/dazz/h5/task_apply",
        data=json.dumps(payload),
        headers=headers
    )
    resp.raise_for_status()
    return resp.json()

def open_box(user_id: int, token: str, box_type: int = 1, box_id: int = 1, lang: str = "id") -> Dict:
    """
    Open/claim a reward box (turntable or gift box) in the H5 system.
    
    Args:
        user_id: User ID
        token: User access token
        box_type: Type of box to open (default: 1)
        box_id: ID of the specific box (default: 1)
        lang: Language code (default: "id" for Indonesian)
    
    Returns:
        JSON response with reward details from opening the box
    """
    payload = {
        "sign": "",
        "user_id": user_id,
        "box_type": box_type,
        "box_id": box_id,
        "lang": lang,
        "token": token,
        "time": str(int(time.time()))
    }
    payload["sign"] = generate_sign_from_payload(payload)
    
    headers = {
        "Host": "h5.idlive.xin",
        "User-Agent": user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/json",
        "Origin": "https://h5.idlive.xin",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    
    resp = session.post(
        "https://h5.idlive.xin/api/go_v3/dazz/h5/open_box",
        data=json.dumps(payload),
        headers=headers
    )
    resp.raise_for_status()
    return resp.json()

def get_income(user_id: int, token: str, lang: str = "id") -> Dict:
    """
    Query user's income summary from H5 endpoint.

    Mirrors the HAR: POST https://h5.idlive.xin/api/go_v3/dazz/h5/income

    Args:
        user_id: User ID
        token: H5 token
        lang: Language code (default 'id')

    Returns:
        Parsed JSON response from the income endpoint.
    """
    payload = {
        "sign": "",
        "user_id": str(user_id),
        "lang": lang,
        "token": token,
        "time": str(int(time.time()))
    }

    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
        "Host": "h5.idlive.xin",
        "User-Agent": user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/json",
        "Origin": "https://h5.idlive.xin",
        "Connection": "keep-alive",
        "Referer": f"https://h5.idlive.xin/my_income?user_id={user_id}&token={token}&in_room=0&channel_id=3&package_name=app.dazz.live&version=1.8.6&language={lang}&form=dazz&isGooglePay=1&is_show_gm=1&is_obs=0&is_shenhe=0",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }

    resp = session.post(
        "https://h5.idlive.xin/api/go_v3/dazz/h5/income",
        data=json.dumps(payload),
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()

def check_login_status(user_id: str, token: str, lang: str = "id") -> Dict:
    """
    Check the user's login status and verify session validity.
    
    Args:
        user_id: User ID
        token: User access token
        lang: Language code (default: "id" for Indonesian)
    
    Returns:
        JSON response with login status information
    """
    payload = {
        "sign": "",
        "user_id": user_id,
        "token": token,
        "lang": lang,
        "time": str(int(time.time()))
    }
    payload["sign"] = generate_sign_from_payload(payload)
    
    headers = {
        "Host": "h5.idlive.xin",
        "User-Agent": user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/json",
        "Origin": "https://h5.idlive.xin",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    
    resp = session.post(
        "https://h5.idlive.xin/api/go_v3/hg/h5/loginstatus",
        data=json.dumps(payload),
        headers=headers
    )
    resp.raise_for_status()
    return resp.json()

def sign_in(user_id: int, token: str, sign_type: int = 1, lang: str = "id") -> Dict:
    """

Halaman web tidak tersedia
Halaman web di https://h5.idlive.xin/task/signtask?user_id=19890048&token=1f97f2c59cb2a44d&in_room=0&channel_id=3&package_name=app.dazz.live&version=1.9.9&language=id&form=dazz&isGooglePay=1&is_show_gm=1&rtl=0&is_obs=0&is_shenhe=0&is_anchor=0 tidak dapat dimuat karena:

net::ERR_TIMED_OUT
    Daily sign-in to claim rewards (experience, gold, turntable entries).
    
    Args:
        user_id: User ID
        token: User access token
        sign_type: Type of sign-in (default: 1 for daily sign-in)
        lang: Language code (default: "id" for Indonesian)
    
    Returns:
        JSON response with sign-in rewards:
        - exp: Experience points awarded
        - gold: Gold coins awarded
        - turntable_num: Turntable entries awarded
    """
    payload = {
        "sign": "",
        "user_id": user_id,
        "type": sign_type,
        "lang": lang,
        "token": token,
        "time": str(int(time.time()))
    }
    payload["sign"] = generate_sign_from_payload(payload)
    
    headers = {
        "Host": "h5.idlive.xin",
        "User-Agent": user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/json",
        "Origin": "https://h5.idlive.xin",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    
    resp = session.post(
        "https://h5.idlive.xin/api/go_v3/dazz/h5/sign",
        data=json.dumps(payload),
        headers=headers
    )
    resp.raise_for_status()
    return resp.json()

def sign_in_batch(accounts: List[tuple], max_workers: int = 50) -> List[Dict]:
    """
    Execute daily sign-in (type 1 and 2) for multiple accounts using threading.
    
    Args:
        accounts: List of tuples (user_id, token) to sign in
        max_workers: Maximum number of concurrent threads (default: 50)
    
    Returns:
        List of dicts with sign-in results for each account
    """
    import concurrent.futures
    
    results = []
    results_lock = threading.Lock()
    
    def process_account(user_id: int, token: str):
        """Process a single account: sign_type 1 and 2"""
        account_result = {
            "user_id": user_id,
            "token": token,
            "sign_type_1": None,
            "sign_type_2": None,
            "error": None
        }
        
        try:
            # Sign type 1 (Daily sign-in)
            response_1 = sign_in(user_id, token, sign_type=1)
            account_result["sign_type_1"] = response_1.get("data")
            
            # Small delay between requests
            time.sleep(0.1)
            
            # Sign type 2 (Bonus sign-in)
            response_2 = sign_in(user_id, token, sign_type=2)
            account_result["sign_type_2"] = response_2.get("data")
            
            print(f"✓ User {user_id}: Type1={response_1.get('code')} Type2={response_2.get('code')}")
            
        except Exception as e:
            account_result["error"] = str(e)
            print(f"✗ User {user_id}: {str(e)}")
        
        with results_lock:
            results.append(account_result)
    
    # Execute with thread pool
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(process_account, user_id, token)
            for user_id, token in accounts
        ]
        
        # Wait for all threads to complete
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"Thread error: {e}")
    
    return results

def process_h5_account(user_id: int, token: str, do_sign: bool = True, do_tasks: bool = True, lang: str = "id") -> Dict:
    """
    Perform the H5 per-account workflow described by the user:
      1. check_login_status
      2. sign_in type=1 (if do_sign)
      3. sign_in type=2 (if do_sign)
      4. get_task_list and apply_task for open tasks (if do_tasks)

    Returns a dict with the outcomes for each step.
    """
    result = {
        "user_id": user_id,
        "token": token,
        "login_ok": False,
        "login_status": None,
        "signed_type_1": None,
        "signed_type_2": None,
        "tasks_applied": [],
        "opened_boxes": [],
        "errors": [],
    }

    try:
        # 1. Check login status
        try:
            login_resp = check_login_status(str(user_id), token, lang=lang)
            result["login_status"] = login_resp
            if isinstance(login_resp, dict) and login_resp.get("code") == 0:
                result["login_ok"] = True
            else:
                result["errors"].append("login_invalid")
                # If login invalid, skip further steps
                return result
        except Exception as e:
            result["errors"].append(f"check_login_status_error: {e}")
            return result

        # 2. Sign-in steps
        if do_sign:
            try:
                r1 = sign_in(user_id, token, sign_type=1, lang=lang)
                result["signed_type_1"] = r1
                # only proceed to next sign if first succeeded (code==0)
                if not (isinstance(r1, dict) and r1.get("code") == 0):
                    result["errors"].append("sign_type_1_failed")
                time.sleep(0.1)
            except Exception as e:
                result["errors"].append(f"sign_type_1_exception: {e}")

            try:
                r2 = sign_in(user_id, token, sign_type=2, lang=lang)
                result["signed_type_2"] = r2
                if not (isinstance(r2, dict) and r2.get("code") == 0):
                    result["errors"].append("sign_type_2_failed")
            except Exception as e:
                result["errors"].append(f"sign_type_2_exception: {e}")

        # 3. Task listing and apply
        if do_tasks:
            try:
                tl = get_task_list(user_id, token, lang=lang)
                task_data = tl.get("data", {}) if isinstance(tl, dict) else {}
                task_config = task_data.get("task_config", [])
                for task in task_config:
                    try:
                        status = task.get("status")
                        task_id = task.get("task_id") or task.get("id")
                        # Consider status open when equals 1 or string 'open' (robust)
                        if status in (1, "1") or (isinstance(status, str) and status.lower() == "open"):
                            if task_id:
                                ar = apply_task(user_id, token, int(task_id), lang=lang)
                                result["tasks_applied"].append({"task_id": task_id, "resp": ar})
                                # small delay between applies
                                time.sleep(0.1)
                    except Exception as e:
                        result["errors"].append(f"apply_task_exception_task_{task.get('task_id', '?')}: {e}")
            except Exception as e:
                result["errors"].append(f"get_task_list_exception: {e}")

        # 4. Open boxes (IDs 1,2,3) and collect responses
        try:
            opened = []
            for box_id in (1, 2, 3):
                try:
                    ob = open_box(user_id, token, box_type=1, box_id=box_id, lang=lang)
                    opened.append({"box_id": box_id, "resp": ob})
                    time.sleep(0.1)
                except Exception as e:
                    result["errors"].append(f"open_box_{box_id}_exception: {e}")
            result["opened_boxes"] = opened
        except Exception as e:
            result["errors"].append(f"open_boxes_exception: {e}")

    except Exception as e:
        result["errors"].append(f"unexpected_exception: {e}")

    return result


def process_h5_accounts_batch(
    accounts: List[Union[tuple, str]],
    max_workers: int = 50,
    output_file: str = None,
    include_income: bool = False,
    retries: int = 1,
) -> List[Dict]:
    """
    Run `process_h5_account` concurrently for many accounts.

    Accounts may be provided as a list of (user_id, token) tuples, or as
    raw account lines like "userid,jwt,token". The function will try to
    parse those formats.

    Args:
        accounts: list of (user_id, token) or raw account lines
        max_workers: concurrency
        output_file: optional CSV filepath to append results (header auto-added)
        include_income: if True, call `get_income` per account and include income in output
        retries: number of times to retry per-account on transient failures

    Returns list of per-account results.
    """
    import concurrent.futures

    results = []
    results_lock = threading.Lock()

    # Prepare output file header if requested
    if output_file:
        try:
            write_header = not os.path.exists(output_file)
            if write_header:
                with open(output_file, "w") as f:
                    columns = ["user_id", "login_ok", "num_tasks_applied", "opened_boxes", "errors"]
                    if include_income:
                        columns.insert(4, "income")
                    f.write(",".join(columns) + "\n")
        except Exception as e:
            print(f"[Warning] could not prepare output file '{output_file}': {e}")

    def _parse_account(item):
        # item can be (uid, token) or a CSV-like line
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                uid = int(item[0])
            except Exception:
                uid = item[0]
            token = item[1]
            return uid, token

        if isinstance(item, str):
            parts = item.split(",")
            if len(parts) >= 3:
                try:
                    uid = int(parts[0])
                except Exception:
                    uid = parts[0]
                token = parts[2]
                return uid, token
            if len(parts) >= 2:
                try:
                    uid = int(parts[0])
                except Exception:
                    uid = parts[0]
                token = parts[1]
                return uid, token

        raise ValueError("Unsupported account format: %s" % repr(item))

    def worker(item):
        try:
            uid, token = _parse_account(item)
        except Exception as e:
            with results_lock:
                results.append({"user_id": None, "error": f"parse_error: {e}", "raw": item})
            return

        attempt = 0
        last_exc = None
        while attempt < max(1, retries):
            try:
                res = process_h5_account(uid, token)
                # Optionally fetch income
                if include_income:
                    try:
                        inc = get_income(uid, token)
                        # extract numeric income if present
                        if isinstance(inc, dict) and inc.get("code") == 0:
                            res["income"] = inc.get("data", {}).get("income")
                        else:
                            res["income"] = None
                    except Exception as e:
                        res["income"] = None
                        res.setdefault("errors", []).append(f"get_income_error: {e}")

                with results_lock:
                    results.append(res)
                    if output_file:
                        try:
                            with open(output_file, "a") as f:
                                opened_json = json.dumps(res.get("opened_boxes", []), ensure_ascii=False)
                                errors_json = json.dumps(res.get("errors", []), ensure_ascii=False)
                                income_val = res.get("income") if include_income else ""
                                line_parts = [str(res.get("user_id")), str(res.get("login_ok")), str(len(res.get("tasks_applied", []))), f'"{opened_json}"']
                                if include_income:
                                    line_parts.append(str(income_val))
                                line_parts.append(f'"{errors_json}"')
                                f.write(",".join(line_parts) + "\n")
                        except Exception as e:
                            print(f"[Warning] failed to write batch output for {uid}: {e}")
                return
            except Exception as e:
                last_exc = e
                attempt += 1
                time.sleep(0.2)

        # if reached here, all retries failed
        with results_lock:
            results.append({"user_id": uid, "error": f"failed_after_retries: {last_exc}"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as exc:
        futures = [exc.submit(worker, item) for item in accounts]
        for fut in concurrent.futures.as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                print(f"Batch worker error: {e}")

    return results


if __name__ == "__main__":
    # acc_file = open("poor", "r").read().splitlines()
    # accounts = [(line.split(",")[0], line.split(",")[2]) for line in acc_file if line.count(",") >= 2]
    # sign_in_batch(accounts, max_workers=20)

    uid = '20534744'
    token = 'ec1ee538b0b09dfd'
    # print(check_login_status(uid, token))
    # print(sign_in(uid, token, 2))

    # print(apply_task(int(uid), token, 5))

    """
    now in one run, we do
    1. # print(check_login_status(uid, token)) for checking either the token is still valid. move to the next job if valid.
    2. # print(sign_in(uid, token, 1)) with status 1, move to the next job if it return code 0
    3. # print(sign_in(uid, token, 2)) claiming
    4. we do something like 
    r = get_task_list(int(uid), token)
    data = r.get("data", {})

    for task in data.get("task_config", []):
        print(task)

    for claiming all task currently with status open.
    """

    res = process_h5_account(uid, token)
    print(res)