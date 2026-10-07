# Forebelingfa

This repo is built around a single objective: win the first-claim race for a LuckyBag by using the fastest valid worker path.

The current active workflow is intentionally simple:

- one account format: `userId,ws_token,jwt`
- one working account file: `accounts.txt`
- one direct claim flow: join room -> receive ACK -> send claim immediately
- one debug harness: websocket packet tracing

---

## Active files

The active project is centered on these files:

- `tamilogin.py` - refreshes account data from the live login flow
- `refresh_accounts.py` - writes fresh rows into `accounts.txt`
- `simple_account_manager.py` - loads `userId,ws_token,jwt` rows
- `simple_worker.py` - handles the join-and-claim path
- `first_claim_runner.py` - schedules the first-claim attempt
- `chat.py` - verbose websocket debug session for protocol inspection
- `config.py` - centralized runtime settings
- `runtime_state.py` - worker health and packet state
- `speed_scheduler.py` - worker scheduling and bag prioritization
- `resilience.py` - failure classification and protocol-drift detection
- `scale_system.py` - tiered worker pools and throughput metrics
- `todo.md` - roadmap and phase tracking

---

## Account file format

`accounts.txt` uses one account per line:

```text
userId,ws_token,jwt
```

Example:

```text
10673652,04b9864fab5436e8,eyJhbGciOiJIUzI1NiJ9...
```

---

## How to run the project

### 1) Refresh accounts from the live login flow

```bash
python tamilogin.py
```

Then regenerate the local account file:

```bash
python refresh_accounts.py
```

This writes the output into `accounts.txt` in the expected format.

### 2) Validate the simplified worker flow

```bash
python validate_simple_worker.py --check
```

Or inspect the account file content:

```bash
python validate_simple_worker.py --accounts accounts.txt
```

### 3) Run a first-claim attempt

```bash
python first_claim_runner.py --accounts accounts.txt --room-id 123 --bag-id 999 --bag-value 50
```

Useful flags:

- `--accounts` - account list path
- `--room-id` - target room
- `--bag-id` - LuckyBag to claim
- `--bag-value` - optional value hint used for prioritization

### 4) Run the websocket debug harness

```bash
python chat.py
```

This logs the actual sent and received websocket frames and is the best tool for protocol debugging when the server behavior changes.

### 5) Run the dedicated speed/resilience/scale checks

```bash
python - <<'PY'
from scale_system import AdaptiveMetrics, OpportunityQueue, build_worker_tiers
from runtime_state import Account, RuntimeState

state = RuntimeState(
    accounts=[
        Account(user_id=1, ws_token='a', jwt='x'),
        Account(user_id=2, ws_token='b', jwt='y'),
        Account(user_id=3, ws_token='c', jwt='z'),
    ],
    worker_health={
        1: type('H', (), {'success_count': 4, 'failure_count': 0, 'is_healthy': True})(),
        2: type('H', (), {'success_count': 1, 'failure_count': 1, 'is_healthy': True})(),
        3: type('H', (), {'success_count': 0, 'failure_count': 4, 'is_healthy': False})(),
    },
)
assert build_worker_tiers(state)[0].name == 'premium'
queue = OpportunityQueue(); queue.enqueue({'bag_id': 1, 'value': 10, 'time': 100}); queue.enqueue({'bag_id': 2, 'value': 30, 'time': 200}); assert queue.pop_best()['bag_id'] == 2
metrics = AdaptiveMetrics(); metrics.record_result(True, 5); metrics.record_result(False, 0); assert metrics.win_rate() == 0.5
print('scale checks passed')
PY
```

---

## Notes on the current design

The code is intentionally optimized for the shortest path to a valid response:

1. load accounts from `accounts.txt`
2. choose a suitable worker using health and scheduling logic
3. join the room
4. send claim immediately after the join ACK
5. log the result and classify the failure if it fails

The project is deliberately built for debugging and fast adaptation. If the upstream backend changes, the main thing you want to preserve is the packet-level tracing and the account/worker state model.

---

## Cleanup status

Legacy experimental files that were not part of the current active workflow were removed to keep the repo lean and easier to reason about. The surviving codebase is the simplified, testable, debug-friendly path for the first-claim objective.

---

## Notable risks and caveats

- The code is not production-ready in a security sense.
- There are hardcoded tokens, secrets, and account data.
- Some scripts appear to be prototypes or exploratory automation rather than a polished application.
- There is no dependency management file, virtualenv setup, or test suite beyond a small websocket smoke test.
- The code uses direct MD5-based signing logic and custom API payloads; any upstream change can break behavior immediately.
- Some script names are inconsistent (`tamilogin.py`, `tamilsatgas.py`, `tamilscan.py`, `tamilturis.py`), suggesting a rapid experimental project rather than a cleanly named codebase.

---

## Suggested next steps

If you want to continue developing this project, the most useful improvements would be:

1. Move secrets and tokens into environment variables or a secure config manager.
2. Add a real dependency file such as `requirements.txt`.
3. Standardize script naming and entry points.
4. Add structured logging and retry handling.
5. Add real tests around the scanner-to-satgas and satgas-to-worker lifecycle.
6. Replace ad hoc payload generation with a clearer modular API client.

---

## Summary

This repository is best understood as a custom automation pipeline for a LuckyBag reward system. It is built around:

- API signing and login flows
- room scanning for reward events
- websocket task relay architecture
- worker bots that claim rewards in real time

It is functional as a prototype or script stack, but it depends heavily on hardcoded data, live external services, and a fragile trust model around the upstream game backend.
