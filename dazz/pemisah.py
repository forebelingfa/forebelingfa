#!/usr/bin/env python3

import os
import concurrent.futures
from api import get_user_info

# Configuration
AKUN_FILE = "black"
# Adjust this! Too high and the server bans ye, too low and ye swim slow. 
# 20-50 is usually the sweet spot for most APIs.
MAX_WORKERS = 50 

def process_account(line):
    """
    A single shark bite. Processes one line/account.
    """
    if not line.strip():
        return None
    
    detail = {}
    
    try:
        parts = line.strip().split(",", 2)
        if len(parts) < 3:
            return None
            
        userid, jwt, token = parts
        
        if not jwt:
            return None
        
        detail.update({"userid": userid, "jwt": jwt, "token": token})

        # Fetch user info (The slow part!)
        user_info = get_user_info(userid, jwt)
        gold = user_info.get("data", {}).get("gold", 0)
        nick = user_info.get("data", {}).get("nickname", "Unknown")
        detail['gold'] = gold


        # Return the booty
        print(f"[{userid}] {nick} => 💰 {gold}")
        return detail

    except Exception as e:
        print(f"[!] Scallywag error on line '{line.strip()[:10]}...': {e}")
        detail['gold'] = 201
        return detail

def main():
    if not os.path.exists(AKUN_FILE):
        print(f"Arrgh! The file '{AKUN_FILE}' be missin'!")
        return

    print(f"🦈 Releasing {MAX_WORKERS} sharks to hunt for gold...")
    
    # 1. Read all lines first
    with open(AKUN_FILE, "r") as f:
        lines = f.readlines()

    all_results = []
    
    # 2. Multi-threading magic (The Speed Boost)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Map the lines to the function
        future_to_account = {executor.submit(process_account, line): line for line in lines}
        
        for future in concurrent.futures.as_completed(future_to_account):
            result = future.result()
            if result:
                all_results.append(result)

    # 3. Sort the loot
    rich_acc = []   # >= 5500
    poor_acc = []   # <= 100
    middle_acc = [] # The rest (stay in black)
    total_gold = 0

    for v in all_results:
        total_gold += v["gold"]
        if v["gold"] >= 5500:
            rich_acc.append(v)
        elif v["gold"] <= 200:
            poor_acc.append(v)
        else:
            middle_acc.append(v)

    print("\n⚔️ Sorting the Treasure...")

    # 4. Write to files (Batch write is faster than opening/closing constantly)
    
    # Overwrite 'black' with only the middle accounts
    with open("black", "w") as f:
        if middle_acc:
            f.write("\n".join([f"{v['userid']},{v['jwt']},{v['token']}" for v in middle_acc]) + "\n")
    print(f"🏴‍☠️ Black list updated (Remaining: {len(middle_acc)})")

    # Append Rich
    if rich_acc:
        with open("rich", "a") as f:
            f.write("\n".join([f"{v['userid']},{v['jwt']},{v['token']}" for v in rich_acc]) + "\n")
    print(f"💎 Rich list updated (Added: {len(rich_acc)})")

    # Append Poor
    if poor_acc:
        with open("poor", "a") as f:
            f.write("\n".join([f"{v['userid']},{v['jwt']},{v['token']}" for v in poor_acc]) + "\n")
    print(f"🦴 Poor list updated (Added: {len(poor_acc)})")

    # Final Report
    print("-" * 30)
    print(f"📊 Processed: {len(all_results)} accounts")
    print(f"💰 Total Gold Looted: {total_gold}")
    print("-" * 30)

if __name__ == "__main__":
    main()