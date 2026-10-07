#!/usr/bin/python

import os, sys
from api import get_user_info

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

def main(file_name: str):
    total_gold = 0
    
    if not os.path.isfile(file_name):
        print(f"[!] Input file not found: {file_name}")
        return

    print(f"\n=== Processing {file_name} ===")
    results = check_gold_from_file(file_name)
    
    to_black = [v for v in results if v["gold"] >= 1]
    current_acc = [v for v in results if v["gold"] == 0]

    # Overwrite the original file with only the accounts that have 0 gold
    with open(file_name, "w") as wauto:
        wauto.write("\n".join([f"{v['userid']},{v['jwt']},{v['token']}" for v in current_acc]))
        print(f"'{file_name}' updated with accounts having zero gold.")

    # Append the accounts with gold to the 'black' file
    if to_black:
        black_file_path = "black"
        with open(black_file_path, "a") as wblack:
            wblack.write("\n".join([f"{v['userid']},{v['jwt']},{v['token']}" for v in to_black]))
            wblack.write("\n") # Add a newline for separation
            print(f"'{black_file_path}' updated with accounts having gold.")

    print("\n--- Summary ---")
    print(f"Total Accounts Processed: {len(results)}")
    print(f"Accounts Kept in File: {len(current_acc)}")
    print(f"Accounts Moved to 'black': {len(to_black)}")
    
    for r in results:
        total_gold += r.get('gold', 0)

    print(f"\n💰 Total Gold Found: {total_gold}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        # sys.argv[0] is the script name itself
        print("This script checks the gold balance of accounts in a file and separates them.")
        print(f"Usage: python {sys.argv[0]} <filename>")
        sys.exit(1)

    # The first command-line argument is the filename to process
    target_filename = sys.argv[1]
    main(target_filename)