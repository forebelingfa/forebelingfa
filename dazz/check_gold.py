#!/usr/bin/env python3

import os, sys, json, time
from api import get_user_info


def check_gold_from_file(file_path):
    results = []
    with open(file_path, "r") as f:
        i=0
        t=0
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

                # gold = int(gold/10000)
                if transfer:
                    t+=gold
                    if t>=stotal_gold:
                        break
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
    print("\n--- Summary ---")
    print(f"Total Accounts Processed: {len(results)}")
    
    for r in results:
        total_gold += r.get('gold', 0)

    print(f"\n💰 Total Gold Found: {total_gold}")


if __name__ == "__main__":
    transfer = 0
    stotal_gold = 200

    # Check if at least one command-line argument is provided
    if len(sys.argv) < 2:
        # Print a helpful usage message to standard error
        print("Usage: python your_script_name.py <filename>", file=sys.stderr)
        # Exit with a non-zero status code to indicate an error
        sys.exit(1)

    # Safely get the filename from the command-line arguments
    filename = sys.argv[1]
    main(filename)