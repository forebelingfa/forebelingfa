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
- `simple_account_manager.py` - loads the text file
- `simple_worker.py` - websocket join + claim logic
- `room_poller.py` - optional LuckyBag discovery
- `first_claim_runner.py` - entry point

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

## Notes

The claim path is intentionally minimal and optimized for one objective: claim the bag as soon as the room login is confirmed.

If the backend rejects the bag, the response is real and should be treated as a server-side state issue, not a code issue.
