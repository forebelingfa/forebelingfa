import time

from runtime_state import Account, RuntimeState
from speed_scheduler import BagOpportunity, WorkerScheduler, score_bag_opportunity


def test_score_bag_opportunity_prefers_high_value_and_newer_bags():
    now = time.time()
    old = BagOpportunity(room_id=123, bag_id=999, bag_value=1, discovered_at=now - 200)
    fresh = BagOpportunity(room_id=123, bag_id=500, bag_value=50, discovered_at=now)

    assert score_bag_opportunity(old) < score_bag_opportunity(fresh)


def test_worker_scheduler_picks_healthiest_account():
    state = RuntimeState(
        accounts=[
            Account(user_id=1, ws_token="a", jwt="x"),
            Account(user_id=2, ws_token="b", jwt="y"),
        ],
        worker_health={
            1: type("H", (), {"is_healthy": True, "failure_count": 0, "success_count": 2, "last_result": "success"})(),
            2: type("H", (), {"is_healthy": True, "failure_count": 3, "success_count": 0, "last_result": "failure"})(),
        },
    )

    scheduler = WorkerScheduler(state)
    chosen = scheduler.pick_worker()

    assert chosen is not None
    assert chosen["user_id"] == 1


def test_worker_scheduler_rotates_stale_accounts():
    state = RuntimeState(
        accounts=[Account(user_id=10, ws_token="a", jwt="x")],
        worker_health={
            10: type("H", (), {"is_healthy": False, "failure_count": 4, "success_count": 0, "last_result": "failure"})(),
        },
    )

    scheduler = WorkerScheduler(state)
    stale = scheduler.rotate_stale_accounts()

    assert stale == [10]
