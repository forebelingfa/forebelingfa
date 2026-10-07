#!/usr/bin/env python3
import json

# Read accounts.txt
with open('/home/patrick/Documents/Cline/tamil/forebelingfa/accounts.txt', 'r') as f:
    accounts = f.read().strip().splitlines()

# Parse accounts
parsed_accounts = []
for account in accounts:
    if account.startswith('#'):
        continue
    parts = account.split(',')
    if len(parts) >= 3:
        user_id, ws_token, jwt = parts[0], parts[1], parts[2]
        parsed_accounts.append((int(user_id), ws_token, jwt.strip()))

print(f"Found {len(parsed_accounts)} accounts")
for user_id, ws_token, jwt in parsed_accounts:
    print(f"  UserID: {user_id}, JWT provided: {jwt[:30]}...")

# Now let's call clone_user_profile with source=10622741, target=one of the accounts above
from api import clone_user_profile

source_user_id = 10622741

# Use the first account as target
if parsed_accounts:
    target_user_id, target_ws_token, target_jwt = parsed_accounts[0]
    print(f"\n--- Testing Clone Profile ---")
    print(f"Source UserID: {source_user_id}")
    print(f"Target UserID: {target_user_id}")
    
    result = clone_user_profile(source_user_id, target_user_id, target_jwt)
    print(f"\nResult: {json.dumps(result, indent=2)}")
else:
    print("No accounts available")
