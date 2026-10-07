from scale_system import AdaptiveMetrics, AdaptiveRunner, OpportunityQueue, WorkerTier, build_worker_tiers
from runtime_state import Account, RuntimeState


def test_build_worker_tiers_prioritizes_successful_accounts():
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
    tiers = build_worker_tiers(state)
    assert tiers[0].name == 'premium'
    assert any(account['user_id'] == 1 for account in tiers[0].accounts)


def test_opportunity_queue_prioritizes_high_value_then_recent():
    queue = OpportunityQueue()
    queue.enqueue({'bag_id': 1, 'value': 10, 'time': 100})
    queue.enqueue({'bag_id': 2, 'value': 30, 'time': 200})
    item = queue.pop_best()
    assert item['bag_id'] == 2


def test_metrics_compute_win_rate():
    metrics = AdaptiveMetrics()
    metrics.record_result(True, 5)
    metrics.record_result(False, 0)
    assert metrics.win_rate() == 0.5
