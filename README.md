# Forebelingfa

Small live LuckyBag claim runner.

This repo is intentionally compact:

- one account format: `userId,ws_token,jwt`
- one direct claim worker: join room, send claim immediately
- one optional room poller: looks for LuckyBag rooms
- one runner: executes the real flow

## Files

- `accounts.txt` - account list
- `config.py` - runtime settings
- `api.py` - shared signed Tamil REST API client
- `simple_account_manager.py` - loads the text file
- `simple_worker.py` - websocket join + claim logic
- `room_poller.py` - optional LuckyBag discovery
- `first_claim_runner.py` - entry point
- `check_gold.py` - account balance checker
- `check_favorite.py` - live favorite-anchor watcher
- `send_messages.py` - websocket room sender
- `chat.py` - interactive room chat client
- `helper.py` - JWT-claim inspection, profile, gold/level, merge, and dedupe utilities
- `tamil/` - Rust LuckyBag room scanner and worker dispatcher

## Account format

```text
userId,ws_token,jwt
```

Example:

```text
10673652,04b9864fab5436e8,eyJ... 
```

## Run directly

```bash
python first_claim_runner.py --accounts accounts.txt --room-id 123 --bag-id 999
```

## Poll for LuckyBag rooms

```bash
python first_claim_runner.py --poll --poll-seconds 3
```

## Rust LuckyBag worker

Scan Tamil's hot-anchor endpoint without opening WebSockets:

```bash
cargo run --manifest-path tamil/Cargo.toml -- --accounts accounts.txt --scan-only --max-pages 1
```

Run the room scanner and dispatcher:

```bash
cargo run --release --manifest-path tamil/Cargo.toml -- --accounts accounts.txt
```

Verify that one account can join a specific room without sending claims or chat:

```bash
cargo run --manifest-path tamil/Cargo.toml -- --join 14139 --logging on
```

The diagnostic exits after the server responds to the room-login frame (or after its 12-second timeout).

The worker reads `userId,ws_token,jwt` accounts, filters `red_packet_logo`, follows countdown announcements, and sends a bounded claim burst when a bag opens. Run `cargo run --manifest-path tamil/Cargo.toml -- --help` for worker, scan, and claim settings.

## Rust LuckyBag worker

Scan the live Tamil hot-anchor endpoint without opening sockets:

```bash
cargo run --manifest-path tamil/Cargo.toml -- --accounts accounts.txt --scan-only --max-pages 1
```

Run the scanner and dispatch workers to rooms marked with a LuckyBag:

```bash
cargo run --release --manifest-path tamil/Cargo.toml -- --accounts accounts.txt
```

The scanner uses the selected account's JWT; websocket workers use each account's `ws_token`. Worker count, group size, scan interval, shift limits, and claim burst are configurable; run with `--help` for options.

Run the Rust equivalent of the Dazz local LuckyBag room deployment:

```bash
cargo run --release --manifest-path tamil/Cargo.toml -- \
  --accounts accounts.txt --local-luckybag --max-workers 24
```

This mode scans all hot-anchor rooms (not only rooms marked as currently having a LuckyBag), assigns one account per room, and refreshes assignments every 20 minutes. Configure the cycle with `--local-refresh-secs`; claim bursts default to 7 attempts at 500 ms intervals and can be changed with `--local-claim-attempts` and `--local-claim-delay-ms`. The selected scan account is controlled by `--scan-account-index`.

## Account helper

```bash
python helper.py inspect-accounts accounts.txt
python helper.py check-gold accounts.txt --workers 5
python helper.py check-level accounts.txt --threshold 3 --move-to accounts.level3.txt
python helper.py dedupe accounts.txt accounts.deduped.txt
```

`member/info` is public and cannot prove JWT authentication; `inspect-accounts` reports decoded claims as unverified and profile availability separately. Dazz H5 login-status returned code 1003 with the stored websocket token. The Tamil host returned 404 for Dazz H5 task/sign and password-reset paths, so those workflows are not provided by this helper.

## Join a live user's room

Pass the live host's user ID. The sender uses the selected account's JWT to look up the host profile, resolves its active room ID, then joins with that account's websocket token.

```bash
python send_messages.py --live-user-id 10597440 --accounts accounts.txt --account-index 0
```

Add `--bag-id ID` to attempt a specific LuckyBag after joining, or `--max-runtime SECONDS` to change the connection limit.

## Interactive room chat

```bash
python chat.py --live-user-id 10597440 --accounts accounts.txt --account-index 0
```

Enter a message to send it to the room. Use `/to USER_ID MESSAGE` for a direct message, `/like` to send one like, `/help` for commands, or `/quit` to disconnect. Add `--max-runtime SECONDS` to set an optional session limit.

## Notes

The claim path is intentionally minimal and optimized for one objective: claim the bag as soon as the room login is confirmed.

If the backend rejects the bag, the response is real and should be treated as a server-side state issue, not a code issue.
