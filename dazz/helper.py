#!/usr/bin/env python
import os
import json
import time
import random
import threading
from api import clone_user_profile, update_nickname, change_profile_picture
from api import follow
from api import login_dazz, process_h5_accounts_batch, check_login_status, get_user_info, keep_sign_h5
from binding import binding

import re, base64, hashlib, uuid, requests
from typing import Optional

from constant import APP_VERSION

def decode_jwt_userid(token):
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        b = parts[1]
        b += "=" * ((4 - len(b) % 4) % 4)
        b = b.replace("-", "+").replace("_", "/")
        payload = base64.b64decode(b)
        j = json.loads(payload.decode('utf-8', errors='ignore'))
        for k in ("userId","user_id","uid","id","sub","userid"):
            if k in j:
                return str(j[k])
        for k,v in j.items():
            if isinstance(v, int) or (isinstance(v,str) and re.fullmatch(r"\d{4,}", v)):
                return str(v)
    except Exception:
        return None
    return None

def parser_uid_yang_ada_pp():
    f = open("enum_results.csv", "r", encoding="utf-8").read().splitlines()
    l = []

    for g in f:
        img = g.split(",")[-1]
        uid = g.split(",")[0]
        if len(img) >= 1:
            l.append(uid)

    with open("uid.txt", "w") as fp:
        fp.write("\n".join([v for v in l]))

def change_pp_dengan_file_akun(file_akun: str = "adnina", file_uid: str = "uid.txt"):
    # cache = load_cache()

    with open(file_uid, "r") as fu:
        uid_list = [uid.strip() for uid in fu.read().splitlines()]

    with open(file_akun, "r") as fa:
        akun_data = fa.read().splitlines()
        if not akun_data:
            print("Warning: Account file is empty.")
            return # Exit if account file is empty
        # semua_akun = [akun.strip() for akun in akun_data.split(",")]

        min_len = min(len(uid_list), len(akun_data)) # Determine the shortest list length
        print(f"Processing {file_akun}: {min_len} UID/Account pairs")

        for index in range(min_len): # Iterate up to shortest list length
            try:
                uid = random.choice(uid_list)
                akun = akun_data[index]

                try:
                    # Split the account, handle possible extra data
                    uid_akun, jwt, token = akun.split(",") # Get first two elements
                except ValueError:
                    print(f"Skipping account at index {index}: Invalid account format. Expected 'uid,pw', got '{akun}'")
                    continue  # Skip to the next account
                # jwt = get_jwt(uid_akun, pw, cache) # Use the extracted uid and pw
                if jwt:
                    print(f"Successfully got JWT for account at index {index} (UID: {uid_akun})")
                    
                    print( clone_user_profile(uid, uid_akun, jwt) )
                else:
                    print(f"Failed to get JWT for account at index {index} (UID: {uid_akun})")

            except IndexError:
                print(f"Warning: Index out of bounds. Mismatch in UID and account file length at index {index}")
                break #Or continue, depends on your needs
            except Exception as e:
                print(f"An unexpected error occurred during processing at index {index}: {e}")
                continue  # Continue to the next entry

    # save_cache(cache)

def load_akun(name_akun: str) -> dict:
    akunsemua = {}
    akun_files = os.listdir(os.path.join(os.getcwd(), "akun"))

    for akun_file in akun_files:
        if akun_file != name_akun:
            print(akun_file, "skipped.")
            continue

        akun_file = os.path.join(os.getcwd(), "akun", akun_file)
        lines = open(akun_file).read().splitlines()
        for line in lines:
            uid, password = line.split(",")
            akunsemua[uid] = password

    return akunsemua

def refresh_token(token_file):
    """
    jwt,deviceId,password -> user_id,jwt,token
    """

    out_file = token_file + '.txt'
    if not os.path.isfile(token_file):
        print("mana file token nya")
    token_list = open(token_file, encoding="utf-8").read().splitlines()
    if not token_list:
        print("token kosong")

    
    for token in token_list:
        jwt, device_id, pw = token.split(",")

        user_id = decode_jwt_userid(jwt)
        r = login_dazz(userid=user_id, password=pw)

        if r.get("code", 1) == 0:
            print(user_id, pw, "ok") 

            # print(r)
            new_jwt = r.get("data").get("jwt_authorization_token", "no jwt")
            new_token = r.get("data").get("token", "no token")

            with open(out_file, 'a') as out:
                out.write(f"{user_id},{new_jwt},{new_token}")
                out.write("\n")

        else:
            print(device_id, 'failed')

def refresh_token_concurrent(token_file, max_workers: int = 50):
    """
    Concurrent version of refresh_token using ThreadPoolExecutor.
    Expects input file lines in format: jwt,device_id,password
    Writes output to token_file + '.txt' as lines: user_id,new_jwt,new_token
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out_file = token_file + '.txt'

    if not os.path.isfile(token_file):
        print("mana file token nya")
        return
    token_list = open(token_file, encoding="utf-8").read().splitlines()
    if not token_list:
        print("token kosong")
        return

    lock = threading.Lock()
    stats = {"total": len(token_list), "ok": 0, "failed": 0}

    def worker(line):
        try:
            parts = line.split(",")
            if len(parts) < 3:
                return (False, line, "invalid_format")
            jwt, device_id, pw = parts[0], parts[1], parts[2]
            user_id = decode_jwt_userid(jwt)
            if not user_id:
                return (False, line, "cannot_decode_jwt")

            r = login_dazz(userid=user_id, password=pw)
            if r.get("code", 1) == 0:
                new_jwt = r.get("data", {}).get("jwt_authorization_token", "no jwt")
                new_token = r.get("data", {}).get("token", "no token")
                # write result
                with lock:
                    with open(out_file, 'a', encoding='utf-8') as out:
                        out.write(f"{user_id},{new_jwt},{new_token}\n")
                    stats["ok"] += 1
                return (True, user_id, None)
            else:
                with lock:
                    stats["failed"] += 1
                return (False, user_id, r)
        except Exception as e:
            with lock:
                stats["failed"] += 1
            return (False, line, str(e))

    print(f"Starting concurrent refresh: {stats['total']} entries, max_workers={max_workers}")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(worker, line) for line in token_list]
        for i, fut in enumerate(as_completed(futures), 1):
            ok, ident, info = fut.result()
            if i % 100 == 0 or i == stats['total']:
                with lock:
                    print(f"Progress: {i}/{stats['total']} — ok={stats['ok']} failed={stats['failed']}")

    print("Done.")
    print(f"Total: {stats['total']}, OK: {stats['ok']}, Failed: {stats['failed']}")

def follow_concurrent(token_file, follow_count: int = 3, max_workers: int = 50):
    """
    Concurrent follow function using ThreadPoolExecutor.
    Each account follows `follow_count` random accounts from the token_file.
    Expects input file lines in format: user_id,jwt,token
    Writes results to token_file + '_follow_results.txt'
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out_file = token_file + '_follow_results.txt'

    if not os.path.isfile(token_file):
        print(f"[follow_concurrent] token file not found: {token_file}")
        return
    
    token_list = open(token_file, encoding="utf-8").read().splitlines()
    if not token_list:
        print(f"[follow_concurrent] token file is empty: {token_file}")
        return

    # Parse accounts
    accounts = []
    for line in token_list:
        parts = line.split(",")
        if len(parts) >= 3:
            uid, jwt, token = parts[0].strip(), parts[1].strip(), parts[2].strip()
            accounts.append((uid, jwt, token, line))
    
    if not accounts:
        print(f"[follow_concurrent] no valid accounts found")
        return

    lock = threading.Lock()
    stats = {"total": len(accounts), "ok": 0, "failed": 0}

    def worker(account_idx, uid, jwt, token, raw_line):
        try:
            # Randomly select follow_count accounts to follow (excluding self)
            targets = [acc for acc in accounts if acc[0] != uid]
            if len(targets) < follow_count:
                selected = targets
            else:
                selected = random.sample(targets, follow_count)
            
            results = []
            for target_uid, _, _, _ in selected:
                try:
                    resp = follow(uid, jwt, target_uid, 'follow')
                    results.append({"target_uid": target_uid, "response": resp})
                    time.sleep(0.2)  # Small delay between follows to avoid rate limiting
                except Exception as e:
                    results.append({"target_uid": target_uid, "error": str(e)})
            
            with lock:
                with open(out_file, 'a', encoding='utf-8') as out:
                    out.write(f"{uid},{jwt},{token}|follows={len(selected)}\n")
                stats["ok"] += 1
            
            return (True, uid, results)
        except Exception as e:
            with lock:
                stats["failed"] += 1
            return (False, uid, str(e))

    print(f"[follow_concurrent] Starting: {stats['total']} accounts, each following {follow_count}, max_workers={max_workers}")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(worker, i, uid, jwt, tok, raw) for i, (uid, jwt, tok, raw) in enumerate(accounts)]
        for i, fut in enumerate(as_completed(futures), 1):
            ok, ident, info = fut.result()
            if i % 20 == 0 or i == stats['total']:
                with lock:
                    print(f"Progress: {i}/{stats['total']} — ok={stats['ok']} failed={stats['failed']}")

    print("[follow_concurrent] Done.")
    print(f"Total: {stats['total']}, OK: {stats['ok']}, Failed: {stats['failed']}")
    print(f"Results written to: {out_file}")

def _extract_userid_from_jwt(token: str):
    if not token:
        return None
    if token.lower().startswith("bearer "):
        token = token.split(None, 1)[1]
    parts = token.split(".")
    if len(parts) < 2:
        return None
    b64 = parts[1]
    b64 += "=" * ((4 - len(b64) % 4) % 4)
    b64 = b64.replace("-", "+").replace("_", "/")
    try:
        payload = base64.b64decode(b64)
        j = json.loads(payload.decode("utf-8", errors="ignore"))
        for k in ("userId", "user_id", "uid", "id", "sub", "userid", "user_id"):
            if k in j:
                return str(j[k])
        for k, v in j.items():
            if isinstance(v, int) or (
                isinstance(v, str) and re.fullmatch(r"\d{4,}", v)
            ):
                return str(v)
    except Exception as e:
        print(f"[!] JWT decode failed: {e}")
        return None
    return None

def generate_sign_from_payload(payload):
    """
    Uses the same algorithm from apiberanda.py:
      - filters out CREATOR, serialVersionUID, sign
      - sorts items by key
      - builds "k=v&k2=v2...&key=SECRET"
      - md5 hex digest returned
    """
    # default sign filler if not present (keeps behavior same as original)
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

def set_password(jwt_token, new_password, device_id):
    if not jwt_token:
        exit(1)
    user_id = _extract_userid_from_jwt(jwt_token)
    print(f"user id {user_id}")

    payload = {
        "code_type": 0,
        "pwd_str": new_password,
        "type": 1,
        "app_version": APP_VERSION,
        "channel_id": "3",
        "device_id": device_id,
        "facility": "1",
        "lang": "id",
        "package_type": "Android-Google",
        "time": str(int(time.time())),
    }
    if user_id:
        payload["user_id"] = user_id

    payload["sign"] = generate_sign_from_payload(payload)
    headers = {
        "Host": "api.dazz2.com",
        "encrypt-type": "1",
        "user-agent": APP_VERSION,
        "authorization-token": (
            jwt_token.split(None, 1)[1]
            if jwt_token and jwt_token.lower().startswith("bearer ")
            else jwt_token
        ),
        "content-type": "application/json; charset=UTF-8",
        "accept-encoding": "gzip",
        "cache-control": "no-cache",
    }

    r = requests.post(f"https://api.dazz2.com/api/go_v3/dazz/set_password", json=payload, headers=headers, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text

def ini_set_password(token: str):
    DEVICE_ID = str(uuid.uuid4()).replace("-","")
    PASSWORD = DEVICE_ID[17:]
    print(">>> Setting password...")
    status, resp = set_password(jwt_token=token, new_password=PASSWORD, device_id=DEVICE_ID)
    print(status, resp)
    with open("password_changed.txt", "a") as nh:
        nh.write(f"{token},{DEVICE_ID},{PASSWORD}")
        nh.write("\n")

def gabungin_akun():
    # Path to the directory containing account files
    misc_dir = 'akun'
    # Output JSON file name
    output_file = 'accounts.json'

    # Dictionary to store all account data
    all_accounts = {}

    # Check if the misc directory exists
    if not os.path.isdir(misc_dir):
        print(f"Error: Directory '{misc_dir}' not found.")
    else:
        # Iterate over each file in the misc directory
        for filename in os.listdir(misc_dir):
            file_path = os.path.join(misc_dir, filename)
            
            # Ensure that we are only reading files
            if os.path.isfile(file_path):
                try:
                    with open(file_path, 'r') as f:
                        # Read each line from the file
                        lines = f.read().splitlines()
                        for line in lines:
                            # Split the line to get JWT and password
                            parts = line.split(",")
                            jwt = parts[0]
                            pwd = parts[-1]
                            
                            try:
                                # Decode the JWT to get the user ID
                                uid = decode_jwt_userid(jwt)
                                # Add the user ID and password to our dictionary
                                all_accounts[uid] = pwd
                            except Exception as e:
                                print(f"Could not decode JWT '{jwt}' in file '{filename}': {e}")
                except Exception as e:
                    print(f"Error reading file '{filename}': {e}")

        # Write the collected data to a JSON file
        try:
            with open(output_file, 'w') as f:
                json.dump(all_accounts, f, indent=4)
            print(f"Successfully created '{output_file}' with {len(all_accounts)} accounts.")
        except Exception as e:
            print(f"Error writing to JSON file: {e}")

def change_token_file_to_login_file(TXT_FILE):
    # --- CONFIGURATION ---
    JSON_FILE = 'accounts.json'  # Contains {"UserID": "Password"}
    # TXT_FILE = 'selasa'    # Contains UserID,JWT,Token
    OUTPUT_FILE = f'{TXT_FILE}_refresh_list.txt' # Output: JWT,UserID,Password
    # 1. Load the Passwords
    if not os.path.exists(JSON_FILE):
        print(f"Error: {JSON_FILE} not found.")
        return

    print(f"Loading passwords from {JSON_FILE}...")
    try:
        with open(JSON_FILE, 'r') as f:
            # Structure: {"19791077": "7d391216be68507"}
            pass_db = json.load(f) 
    except json.JSONDecodeError:
        print("Error: Invalid JSON format.")
        return

    # 2. Process the TXT file and Match
    if not os.path.exists(TXT_FILE):
        print(f"Error: {TXT_FILE} not found.")
        return

    print(f"Processing {TXT_FILE}...")
    matched_count = 0
    missing_count = 0

    with open(TXT_FILE, 'r') as infile, open(OUTPUT_FILE, 'w') as outfile:
        for line in infile:
            line = line.strip()
            if not line:
                continue

            # Parse the TXT file (UserID, JWT, Token)
            parts = line.split(',')
            
            # Safety check to ensure line has enough data
            if len(parts) < 2: 
                continue

            user_id = parts[0].strip()
            jwt = parts[1].strip()
            # token = parts[2] # We don't need the old token

            # 3. Lookup Password
            if user_id in pass_db:
                password = pass_db[user_id]
                
                # 4. Write to Output (JWT,UserID,Password)
                outfile.write(f"{jwt},{user_id},{password}\n")
                matched_count += 1
            else:
                print(f"[Warning] Password not found for UserID: {user_id}")
                missing_count += 1

    print("-" * 30)
    print(f"Successfully generated '{OUTPUT_FILE}'")
    print(f"Matched Accounts: {matched_count}")
    print(f"Missing Passwords: {missing_count}")

def check_login_status_file_concurrent(
    token_file: str,
    expired_file: str = "poor_expired",
    max_workers: int = 20,
    limit: Optional[int] = None,
):
    """
    Concurrently check login status for a token file where each line is
    `user_id,jwt,token` and write expired/invalid lines to `expired_file`.

    Returns list of tuples: (index, user_id, token, response_dict)
    """
    if not os.path.isfile(token_file):
        print(f"[check_login_status] token file not found: {token_file}")
        return []

    lines = open(token_file, encoding="utf-8").read().splitlines()
    if not lines:
        print(f"[check_login_status] token file is empty: {token_file}")
        return []

    # Prepare expired file and load existing entries to avoid duplication
    existing = set()
    try:
        if os.path.exists(expired_file):
            with open(expired_file, "r", encoding="utf-8") as ef:
                for l in ef:
                    existing.add(l.rstrip("\n"))
        else:
            # create the file if it doesn't exist
            open(expired_file, "w", encoding="utf-8").close()
    except Exception as e:
        print(f"[check_login_status] could not prepare expired file: {e}")

    lock = threading.Lock()
    # lines we will remove from the original file if expired
    to_remove = set()

    def worker(idx, line):
        try:
            parts = line.split(",")
            if len(parts) < 3:
                return (idx, None, None, {"code": -1, "message": "invalid_line", "data": None})
            uid, jwt, token = parts[0].strip(), parts[1].strip(), parts[2].strip()
            resp = check_login_status(uid, token)

            # print output similar to previous behavior
            print(uid, token)
            print(resp)

            if resp.get("code", 1) != 0:
                with lock:
                    if line not in existing:
                        with open(expired_file, "a", encoding="utf-8") as ef:
                            ef.write(line + "\n")
                        existing.add(line)
                    to_remove.add(line)
            return (idx, uid, token, resp)
        except Exception as e:
            with lock:
                to_remove.add(line)
            return (idx, None, None, {"code": -1, "message": str(e), "data": None})

    entries = []
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {}
        for idx, line in enumerate(lines):
            if limit is not None and idx >= limit:
                break
            futures[ex.submit(worker, idx, line)] = idx

        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                res = fut.result()
                entries.append(res)
            except Exception as e:
                print(f"[check_login_status] Worker failed for line {idx}: {e}")

    # sort by original index and print summary
    entries.sort(key=lambda x: x[0] if x[0] is not None else -1)
    ok = sum(1 for _i, _u, _t, r in entries if r.get("code", 1) == 0)
    failed = sum(1 for _i, _u, _t, r in entries if r.get("code", 1) != 0)
    print(f"Processed {len(entries)} lines — ok={ok} failed={failed}")

    # Final dedupe pass to ensure expired file has unique lines (safe and idempotent)
    try:
        if os.path.exists(expired_file):
            with open(expired_file, "r", encoding="utf-8") as ef:
                unique_lines = []
                seen = set()
                for l in ef:
                    s = l.rstrip("\n")
                    if s and s not in seen:
                        unique_lines.append(s)
                        seen.add(s)
            with open(expired_file, "w", encoding="utf-8") as efw:
                for l in unique_lines:
                    efw.write(l + "\n")
    except Exception as e:
        print(f"[check_login_status] could not dedupe expired file: {e}")

    # Remove expired lines from original token file (atomic rewrite)
    try:
        if to_remove:
            tmp_path = token_file + ".tmp"
            removed = 0
            with open(token_file, "r", encoding="utf-8") as inf, open(tmp_path, "w", encoding="utf-8") as outf:
                for l in inf:
                    s = l.rstrip("\n")
                    if s and s in to_remove:
                        removed += 1
                        continue
                    outf.write(l)
            os.replace(tmp_path, token_file)
            print(f"[check_login_status] Removed {removed} expired lines from {token_file}")
    except Exception as e:
        print(f"[check_login_status] could not remove expired lines from original file: {e}")

    return entries

def check_user_level_file_concurrent(
    token_file: str,
    out_file: str = None,
    level_threshold: int = 3,
    max_workers: int = 50,
    limit: Optional[int] = None,
):
    """
    Concurrently check user level for each token line in `token_file` and
    move lines where `level` > `level_threshold` to `out_file`.

    token_file lines must be: `user_id,jwt,token` or `user_id,jwt` or `user_id,token`.
    Returns a list of tuples: (index, user_id, level, response_dict)
    """
    if not os.path.isfile(token_file):
        print(f"[check_user_level] token file not found: {token_file}")
        return []

    lines = open(token_file, encoding="utf-8").read().splitlines()
    if not lines:
        print(f"[check_user_level] token file is empty: {token_file}")
        return []

    if out_file is None:
        out_file = f"{token_file}.level_gt_{level_threshold}"

    lock = threading.Lock()
    to_move = set()
    entries = []

    def worker(idx, line):
        try:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                return (idx, None, None, {"code": -1, "message": "invalid_line", "data": None})
            uid = parts[0]
            # second default jwt if contains '.', otherwise try third
            jwt = parts[1] if len(parts) >= 2 else None
            if jwt and "." not in jwt and len(parts) >= 3:
                jwt = parts[2]

            if not jwt:
                return (idx, uid, None, {"code": -1, "message": "no_jwt_or_token", "data": None})

            resp = get_user_info(uid, jwt)

            if resp.get("code", 1) != 0:
                return (idx, uid, None, resp)

            level_val = resp.get("data", {}).get("level")
            try:
                level_int = int(level_val) if level_val not in (None, "") else 0
            except Exception:
                level_int = 0

            if level_int > level_threshold:
                with lock:
                    with open(out_file, "a", encoding="utf-8") as outf:
                        outf.write(line + "\n")
                    to_move.add(line)

            return (idx, uid, level_int, resp)
        except Exception as e:
            return (idx, None, None, {"code": -1, "message": str(e), "data": None})

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {}
        for idx, line in enumerate(lines):
            if limit is not None and idx >= limit:
                break
            futures[ex.submit(worker, idx, line)] = idx

        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                res = fut.result()
                entries.append(res)
            except Exception as e:
                print(f"[check_user_level] Worker failed for line {idx}: {e}")

    # sort by index and print summary
    entries.sort(key=lambda x: x[0] if x[0] is not None else -1)
    moved = sum(1 for _i, _u, lvl, r in entries if isinstance(lvl, int) and lvl > level_threshold)
    ok = sum(1 for _i, _u, lvl, r in entries if r.get("code", 1) == 0)
    failed = sum(1 for _i, _u, lvl, r in entries if r.get("code", 1) != 0)

    print(f"Processed {len(entries)} lines — ok={ok} failed={failed} moved={moved}")

    # Remove moved lines from original token_file
    try:
        if to_move:
            tmp_path = token_file + ".tmp"
            removed = 0
            with open(token_file, "r", encoding="utf-8") as inf, open(tmp_path, "w", encoding="utf-8") as outf:
                for l in inf:
                    s = l.rstrip("\n")
                    if s and s in to_move:
                        removed += 1
                        continue
                    outf.write(l)
            os.replace(tmp_path, token_file)
            print(f"[check_user_level] Moved {removed} lines from {token_file} to {out_file}")
    except Exception as e:
        print(f"[check_user_level] could not rewrite original file: {e}")

    return entries

def run_h5_batch_from_token_file(
    token_file: str,
    output_file: str = None,
    max_workers: int = 50,
    include_income: bool = False,
    retries: int = 1,
    start: int = 0,
    limit: int = None,
):
    """
    Read `token_file` lines and run `process_h5_accounts_batch` in one call.

    Expected token_file format per line: `user_id,jwt,token` or `user_id,token`.
    The function will parse user_id and token, slice by `start` and `limit`,
    call `process_h5_accounts_batch` and return the results list.

    If `output_file` is provided it will be forwarded to the batch function
    so results are appended there as well.
    """
    if not os.path.isfile(token_file):
        print(f"[run_h5_batch] token file not found: {token_file}")
        return []

    lines = open(token_file, encoding="utf-8").read().splitlines()
    if not lines:
        print(f"[run_h5_batch] token file is empty: {token_file}")
        return []

    # parse lines to (user_id, token) tuples
    accounts = []
    for i, line in enumerate(lines):
        if i < start:
            continue
        if limit is not None and len(accounts) >= limit:
            break
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if len(parts) >= 3:
            uid = parts[0]
            token = parts[2]
        elif len(parts) == 2:
            uid = parts[0]
            token = parts[1]
        else:
            print(f"[run_h5_batch] skipping invalid line: {line}")
            continue
        accounts.append((uid, token))

    print(f"[run_h5_batch] Parsed {len(accounts)} accounts, running with max_workers={max_workers}")

    try:
        results = process_h5_accounts_batch(
            accounts, max_workers=max_workers, output_file=output_file, include_income=include_income, retries=retries
        )
        print(f"[run_h5_batch] Completed: {len(results)} results")
        return results
    except Exception as e:
        print(f"[run_h5_batch] batch run failed: {e}")
        return []

def run_keep_sign_from_token_file(
    token_file: str,
    output_file: str = None,
    max_workers: int = 50,
    config_id: int = 2,
    retries: int = 1,
    start: int = 0,
    limit: int = None,
):
    """Read tokens and call `keep_sign_h5` concurrently. Writes JSON lines to `output_file` if provided."""
    if not os.path.isfile(token_file):
        print(f"[run_keep_sign] token file not found: {token_file}")
        return []

    lines = open(token_file, encoding="utf-8").read().splitlines()
    if not lines:
        print(f"[run_keep_sign] token file is empty: {token_file}")
        return []

    accounts = []
    for i, line in enumerate(lines):
        if i < start:
            continue
        if limit is not None and len(accounts) >= limit:
            break
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if len(parts) >= 3:
            uid = parts[0]
            token = parts[2]
        elif len(parts) == 2:
            uid = parts[0]
            token = parts[1]
        else:
            print(f"[run_keep_sign] skipping invalid line: {line}")
            continue

        # optional per-line config_id in 4th column
        if len(parts) >= 4:
            try:
                per_config = int(parts[3])
            except Exception:
                per_config = config_id
        else:
            per_config = config_id

        accounts.append((uid, token, per_config))

    print(f"[run_keep_sign] Parsed {len(accounts)} accounts, running with max_workers={max_workers}")

    results = []
    lock = threading.Lock()

    def worker(idx, uid, token, cfg):
        try:
            resp = keep_sign_h5(uid, token, config_id=cfg)
            with lock:
                if output_file:
                    with open(output_file, "a", encoding="utf-8") as of:
                        of.write(json.dumps({"user_id": uid, "config_id": cfg, "resp": resp}) + "\n")
            return (idx, uid, cfg, resp)
        except Exception as e:
            return (idx, uid, cfg, {"code": -1, "message": str(e)})

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(worker, i, uid, tok, cfg): i for i, (uid, tok, cfg) in enumerate(accounts)}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                results.append(res)
            except Exception as e:
                print(f"[run_keep_sign] Worker failed: {e}")

    results.sort(key=lambda x: x[0] if x[0] is not None else -1)
    ok = sum(1 for _i, _u, _cfg, r in results if isinstance(r, dict) and r.get("code", 0) == 0)
    failed = len(results) - ok
    print(f"[run_keep_sign] Completed {len(results)} — ok={ok} failed={failed}")

    return results

def check_gold_file_concurrent(
    token_file: str,
    output_file: str = None,
    max_workers: int = 20,
    limit: int = None,
    transfer: bool = False,
    stotal_gold: int = 0,
    gold_threshold: int = None,
    move_to_file: str = None,
    remove_from_source: bool = True,
):
    """Concurrent gold check for token files (token_file lines: user_id,jwt,token).

    Writes JSON lines to `output_file` if provided and returns list of dicts.
    """
    if not os.path.isfile(token_file):
        print(f"[check_gold_file_concurrent] token file not found: {token_file}")
        return []

    lines = open(token_file, encoding="utf-8").read().splitlines()
    if not lines:
        print(f"[check_gold_file_concurrent] token file is empty: {token_file}")
        return []

    accounts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        # accept user_id,jwt,token  or user_id,token
        if len(parts) >= 3:
            uid, jwt, token = parts[0], parts[1], parts[2]
        else:
            uid, jwt, token = parts[0], None, parts[1]
        # store original line for possible move
        accounts.append((uid, jwt, token, line))

    if limit is not None:
        accounts = accounts[:limit]

    results = []
    total_gold = 0
    lock = threading.Lock()
    stop_event = threading.Event()

    to_move = set()

    def worker(idx, uid, jwt, token, raw_line):
        if stop_event.is_set():
            return (idx, uid, None, token, jwt, None, raw_line)
        try:
            resp = get_user_info(uid, jwt) if jwt else {"code": -1, "message": "no jwt"}
            if resp.get("code", 1) != 0:
                return (idx, uid, None, token, jwt, resp, raw_line)
            gold = resp.get("data", {}).get("gold", 0)
            nick = resp.get("data", {}).get("nickname", "")
            return (idx, uid, gold, token, jwt, nick, raw_line)
        except Exception as e:
            return (idx, uid, None, token, jwt, str(e), raw_line)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Use an explicit executor and handle shutdown/cancellation carefully so
    # we don't block indefinitely when worker threads are stuck or when a
    # cancel condition is triggered (e.g. reached transfer total or
    # KeyboardInterrupt). Workers use `get_user_info` which has a timeout to
    # avoid network calls hanging forever.
    ex = ThreadPoolExecutor(max_workers=max_workers)
    futures = [ex.submit(worker, i, uid, jw, tk, raw) for i, (uid, jw, tk, raw) in enumerate(accounts)]

    try:
        for fut in as_completed(futures):
            try:
                idx, uid, gold, token, jwt, nick, raw_line = fut.result()
            except Exception as e:
                print(f"[!] Worker raised: {e}")
                continue

            if gold is None:
                print(f"[!] Failed {uid}: {nick}")
                continue

            with lock:
                results.append({"userid": uid, "gold": gold, "token": token, "jwt": jwt, "nickname": nick})
                print(f"[{len(results)}] {nick} ({uid}) => Gold: {gold}")
                if transfer:
                    total_gold += gold
                    if total_gold >= stotal_gold:
                        print(f"[check_gold_file_concurrent] reached total {total_gold} >= {stotal_gold}")
                        stop_event.set()
                        # cancel remaining futures
                        for f in futures:
                            try:
                                f.cancel()
                            except Exception:
                                pass
                        # try to shutdown without waiting to avoid blocking
                        try:
                            ex.shutdown(wait=False)
                        except Exception:
                            pass
                        break

                # handle gold threshold -> move original line to move_to_file
                if gold_threshold is not None and gold is not None and gold > gold_threshold and move_to_file:
                    try:
                        with open(move_to_file, "a", encoding="utf-8") as mf:
                            mf.write(raw_line + "\n")
                        to_move.add(raw_line)
                    except Exception as e:
                        print(f"[!] Could not write to move file {move_to_file}: {e}")

                if output_file:
                    try:
                        with open(output_file, "a", encoding="utf-8") as of:
                            of.write(json.dumps({"userid": uid, "gold": gold, "nickname": nick}) + "\n")
                    except Exception as e:
                        print(f"[!] Could not write to output file {output_file}: {e}")
    except KeyboardInterrupt:
        print("[check_gold_file_concurrent] KeyboardInterrupt, cancelling pending futures...")
        stop_event.set()
        for f in futures:
            try:
                f.cancel()
            except Exception:
                pass
        try:
            ex.shutdown(wait=False)
        except Exception:
            pass
        raise
    finally:
        # ensure executor is shutdown (non-blocking)
        try:
            ex.shutdown(wait=False)
        except Exception:
            pass

    # Remove moved lines from original token_file if requested
    if remove_from_source and to_move:
        try:
            tmp_path = token_file + ".tmp"
            removed = 0
            with open(token_file, "r", encoding="utf-8") as inf, open(tmp_path, "w", encoding="utf-8") as outf:
                for l in inf:
                    s = l.rstrip("\n")
                    if s and s in to_move:
                        removed += 1
                        continue
                    outf.write(l)
            os.replace(tmp_path, token_file)
            print(f"[check_gold_file_concurrent] Moved {removed} lines from {token_file} to {move_to_file}")
        except Exception as e:
            print(f"[check_gold_file_concurrent] could not rewrite original file: {e}")

    return results

def dedupe_by_userid(input_path: str, output_path: str):
    import sys

    GREEN = "\033[92m"
    CYAN = "\033[96m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"

    print(f"{CYAN}🔍 Starting dedupe process...{RESET}")

    # Pass 1: find the LAST line index for each user_id
    last_index = {}
    print(f"{YELLOW}📌 Pass 1/2: Scanning file...{RESET}")
    with open(input_path, "r") as f:
        for i, line in enumerate(f):
            user_id = line.strip().split(",")[0]
            last_index[user_id] = i
    
    print(f"{GREEN}✔ Found {len(last_index):,} unique user IDs!{RESET}")

    # Pass 2: write only the latest occurrences
    print(f"{YELLOW}📌 Pass 2/2: Writing deduped output...{RESET}")
    written = 0
    with open(input_path, "r") as inp, open(output_path, "w") as out:
        for i, line in enumerate(inp):
            user_id = line.strip().split(",")[0]
            if last_index[user_id] == i:
                out.write(line)
                written += 1

    print(f"{GREEN}🎉 Done!{RESET}")
    print(f"{CYAN}➡ Output written to: {output_path}{RESET}")
    print(f"{GREEN}➡ Total lines written: {written:,}{RESET}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Helper CLI for account tooling")

    # shorthand and long options
    parser.add_argument("-s", "--sign-in", action="store_true", help="Run sign-in batch (run_h5_batch_from_token_file)")
    parser.add_argument("-r", "--refresh-tokens", metavar="FILE", help="Refresh tokens from FILE (concurrent)")
    parser.add_argument("--refresh-workers", type=int, default=50, help="Workers for token refresh")
    parser.add_argument("-f", "--follow", metavar="FILE", help="Run concurrent follow on accounts listed in FILE")
    parser.add_argument("--follow-count", type=int, default=3, help="How many targets each account follows")
    parser.add_argument("--follow-workers", type=int, default=50, help="Max concurrent follow workers")
    parser.add_argument("-g", "--check-gold", metavar="FILE", help="Run gold check on FILE")
    parser.add_argument("--gold-threshold", type=int, default=100, help="Gold threshold for moving accounts")
    parser.add_argument("--move-to-file", default="black.txt", help="File to move high-gold accounts into")
    parser.add_argument("-c", "--check-login-status", metavar="FILE", help="Check login status for token file")
    parser.add_argument("--check-user-level", metavar="FILE", help="Check user level for token file")
    parser.add_argument("--dedupe", nargs=2, metavar=("INPUT","OUTPUT"), help="Dedupe input file by userid writing to output")
    parser.add_argument("--gabungin", action="store_true", help="Run gabungin_akun() to produce accounts.json")
    parser.add_argument("--convert-token", metavar="TXT_FILE", help="Convert token file to login file format")
    parser.add_argument("--run-keep-sign", metavar="FILE", help="Run keep sign for tokens in FILE")
    parser.add_argument("--mass-profile-change", nargs=2, metavar=("ACCOUNTS_FILE","UID_FILE"), help="Change profile pictures using accounts and uid lists")
    parser.add_argument("--clone-profile", nargs=3, metavar=("TARGET_UID","SOURCE_UID","JWT"), help="Clone profile: target source jwt")
    parser.add_argument("--update-nickname", nargs=2, metavar=("UID","JWT"), help="Update nickname for UID using JWT")
    parser.add_argument("--update-profile-picture", nargs=3, metavar=("UID","JWT","URL"), help="Update profile picture")
    parser.add_argument("--ini-set-password", metavar="FILE", help="Set password for tokens listed in FILE (writes password_changed.txt)")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Show actions without performing network calls")

    args = parser.parse_args()

    # Map flags to functions (respect --dry-run)
    def _do_or_dry(desc: str, fn, *fargs, **fkwargs):
        if args.dry_run:
            print(f"DRY RUN: {desc}")
        else:
            return fn(*fargs, **fkwargs)

    if args.refresh_tokens:
        _do_or_dry(f"refresh tokens from {args.refresh_tokens} with {args.refresh_workers} workers", refresh_token_concurrent, args.refresh_tokens, args.refresh_workers)

    if args.sign_in:
        _do_or_dry("run sign-in batch using 'poor' token file", run_h5_batch_from_token_file, "poor", None, 100, False)

    if args.follow:
        _do_or_dry(f"run follow_concurrent on {args.follow} (count={args.follow_count})", follow_concurrent, args.follow, args.follow_count, args.follow_workers)

    if args.check_gold:
        _do_or_dry(f"check gold on {args.check_gold}", check_gold_file_concurrent, args.check_gold, None, 50, None, False, 0, args.gold_threshold, args.move_to_file, True)

    if args.check_login_status:
        _do_or_dry(f"check login status on {args.check_login_status}", check_login_status_file_concurrent, args.check_login_status, f"{args.check_login_status}.expired", 20, None)

    if args.check_user_level:
        _do_or_dry(f"check user level on {args.check_user_level}", check_user_level_file_concurrent, args.check_user_level, f"{args.check_user_level}.level", 3, 50, None)

    if args.dedupe:
        _do_or_dry(f"dedupe {args.dedupe[0]} -> {args.dedupe[1]}", dedupe_by_userid, args.dedupe[0], args.dedupe[1])

    if args.gabungin:
        _do_or_dry("gabungin_akun() to produce accounts.json", gabungin_akun)

    if args.convert_token:
        _do_or_dry(f"convert token file {args.convert_token}", change_token_file_to_login_file, args.convert_token)

    if args.run_keep_sign:
        _do_or_dry(f"run keep sign on {args.run_keep_sign}", run_keep_sign_from_token_file, args.run_keep_sign, f"{args.run_keep_sign}.keep_sign.jsonl", 100, 2)

    if args.mass_profile_change:
        _do_or_dry(f"mass profile change: {args.mass_profile_change}", change_pp_dengan_file_akun, args.mass_profile_change[0], args.mass_profile_change[1])

    if args.clone_profile:
        target_uid, source_uid, jwt = args.clone_profile
        _do_or_dry(f"clone profile source={source_uid} target={target_uid}", clone_user_profile, int(target_uid), int(source_uid), jwt)

    if args.update_nickname:
        uid, jwt = args.update_nickname
        _do_or_dry(f"update nickname for {uid}", update_nickname, int(uid), jwt, "updated_name")

    if args.update_profile_picture:
        uid, jwt, url = args.update_profile_picture
        _do_or_dry(f"update profile picture for {uid}", change_profile_picture, int(uid), jwt, url)

    if args.ini_set_password:
        filename = args.ini_set_password
        if args.dry_run:
            print(f"DRY RUN: set passwords from {filename}")
        else:
            with open(filename, "r") as fp:
                for line in fp.read().splitlines():
                    try:
                        uid, jwt, token = line.split(",", 2)
                        print(ini_set_password(jwt))
                    except Exception as e:
                        print(f"Skipping malformed line: {line} -> {e}")

    # If no arguments were provided, print help
    if not any(vars(args).values()):
        parser.print_help()
 