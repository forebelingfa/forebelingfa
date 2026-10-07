# Tamil TODO

## Implemented

- Account loading uses `userId,ws_token,jwt`: [simple_account_manager.py](simple_account_manager.py)
- Direct LuckyBag claim and room discovery: [simple_worker.py](simple_worker.py), [room_poller.py](room_poller.py), [first_claim_runner.py](first_claim_runner.py)
- Shared Tamil API client for signed member-info and hot-anchor calls: [api.py](api.py)
- Gold lookup uses the shared member-info API: [check_gold.py](check_gold.py)
- Live-user room lookup and websocket sender: [send_messages.py](send_messages.py)
- Interactive chat client: [chat.py](chat.py)
- JWT-claim inspection, profile/gold/level scans, merge, and dedupe: [helper.py](helper.py)
- Favorite-anchor watcher: [check_favorite.py](check_favorite.py); verified against the live hot-anchor endpoint
- Rust LuckyBag scanner, room dispatcher, and bounded websocket worker: [tamil/src/red_packet.rs](tamil/src/red_packet.rs)

## Next

- [ ] Smoke-test chat and sender websocket join/message handling in a live room
- [x] Verify Rust websocket room join: room 14139 returned op 1001, code 0, with no error
- [ ] Verify claim acknowledgments when a bag-marked Tamil room is available
- [ ] Add `op 2100` anchor-room switching; the Rust worker currently scans and joins rooms marked by the hot-anchor API
- [ ] Add focused regression tests for account parsing, API signing, room resolution, and chat payloads
- [ ] Port additional Dazz API operations only after their Tamil endpoints and payloads are confirmed; Dazz H5 task/sign and password-reset routes returned 404
- [ ] Find a Tamil endpoint that actually validates JWT/session status; `member/info` is public

## Dazz reference reviewed

- API and account flows: [dazz/api.py](dazz/api.py), [dazz/binding.py](dazz/binding.py), [dazz/h5.py](dazz/h5.py), [dazz/mailisa.py](dazz/mailisa.py)
- Chat and room workers: [dazz/chat.py](dazz/chat.py), [dazz/gifting.py](dazz/gifting.py), [dazz/global_luckybag.py](dazz/global_luckybag.py), [dazz/lokal_luckybag.py](dazz/lokal_luckybag.py), [dazz/red_packet.py](dazz/red_packet.py), [dazz/send_messages.py](dazz/send_messages.py)
- Discovery, balances, and account utilities: [dazz/check_favorite.py](dazz/check_favorite.py), [dazz/check_gold.py](dazz/check_gold.py), [dazz/helper.py](dazz/helper.py), [dazz/pemisah.py](dazz/pemisah.py), [dazz/misc/check_point.py](dazz/misc/check_point.py), [dazz/misc/reverse_file.py](dazz/misc/reverse_file.py)
- Shared values and separate game protocol: [dazz/constant.py](dazz/constant.py), [dazz/paha.py](dazz/paha.py)
