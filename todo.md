# Dazz read confirmation

I read the actual Dazz implementation set that matters for runtime behavior and comparison, and this is the evidence snapshot.

## Confirmed Dazz files reviewed

- [dazz/api.py](dazz/api.py) — REST auth, user-info, signing helpers, and Dazz API access patterns.
- [dazz/binding.py](dazz/binding.py) — email / account binding flows and payload signing routines.
- [dazz/chat.py](dazz/chat.py) — websocket chat handling, message parsing, and live room interaction logic.
- [dazz/check_favorite.py](dazz/check_favorite.py) — favorite-anchor watcher that polls hot anchors and tracks live state.
- [dazz/check_gold.py](dazz/check_gold.py) — gold checks from account files and batch balance scanning.
- [dazz/constant.py](dazz/constant.py) — shared app version, favorite anchor IDs, and runtime constants.
- [dazz/gifting.py](dazz/gifting.py) — websocket gift/send flow and live room routines with reconnect/watchdog logic.
- [dazz/global_luckybag.py](dazz/global_luckybag.py) — the main LuckyBag detection and room-switching pattern.
- [dazz/h5.py](dazz/h5.py) — H5 task/sign workflow and signed API usage for web tasks.
- [dazz/helper.py](dazz/helper.py) — checkpointing, hot-anchor scanning, user-info fetch, and account separation helpers.
- [dazz/lokal_luckybag.py](dazz/lokal_luckybag.py) — the resilient websocket worker loop with reconnect and runtime control.
- [dazz/mailisa.py](dazz/mailisa.py) — OTP email polling and 6-digit code extraction.
- [dazz/paha.py](dazz/paha.py) — betting / poor-token batch flow using protobuf-like packet construction.
- [dazz/pemisah.py](dazz/pemisah.py) — account segregation by gold and file rewriting.
- [dazz/red_packet.py](dazz/red_packet.py) — hot-room scanning and LuckyBag claim orchestration.
- [dazz/send_messages.py](dazz/send_messages.py) — direct websocket messaging / claim-style live worker sample.
- [dazz/misc/check_point.py](dazz/misc/check_point.py) — account gold-check utility and blacklisting script.
- [dazz/misc/reverse_file.py](dazz/misc/reverse_file.py) — simple file reversal utility; not live logic, but part of the Dazz sample set.

## What this confirms

- Dazz is not just a collection of examples; it is a full operational runtime pattern.
- The key live logic is built around:
  - hot anchor / room discovery via `home/hot_anchor`
  - websocket join payloads on op `1001`
  - LuckyBag event detection on op `2100` with `LuckyBagData`
  - room switching to the anchor room
  - claim execution on op `2101`
  - reconnects, watchdogs, and runtime cleanup
  - token health and account segregation
- The missing layer in Tamil is not “more files”; it is the Dazz runtime behavior that keeps the worker alive and fast enough to compete.

## Tamil status after comparison

- [simple_worker.py](simple_worker.py) — working minimal direct join + claim path
- [room_poller.py](room_poller.py) — minimal room discovery/polling path
- [first_claim_runner.py](first_claim_runner.py) — compact runner for direct or poll mode
- [config.py](config.py) — compact runtime config and endpoint fallback list
- [simple_account_manager.py](simple_account_manager.py) — simplified account loader for `userId,ws_token,jwt`

## Bottom line

The Dazz files were read and used as the runtime reference baseline. The Tamil repo is now intentionally compact, but the next real step is to port the Dazz operational protections: room-switch detection, reconnect loop, watchdog, token health handling, and gold verification after claim.
