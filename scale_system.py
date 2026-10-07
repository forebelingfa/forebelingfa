from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from runtime_state import Account, RuntimeState


@dataclass
class WorkerTier:
    name: str
    accounts: List[Dict[str, Any]] = field(default_factory=list)


class OpportunityQueue:
    """Queue tasks by bag value and freshness so the best opportunity is processed first."""

    def __init__(self) -> None:
        self._items: List[Dict[str, Any]] = []

    def enqueue(self, item: Dict[str, Any]) -> None:
        self._items.append(item)

    def pop_best(self) -> Optional[Dict[str, Any]]:
        if not self._items:
            return None
        best_index = max(
            range(len(self._items)),
            key=lambda index: (
                float(self._items[index].get("value", 0)),
                float(self._items[index].get("time", 0)),
            ),
        )
        return self._items.pop(best_index)


def _account_payload(account: Dict[str, Any] | Account) -> Dict[str, Any]:
    if isinstance(account, dict):
        return account
    return {"user_id": account.user_id, "ws_token": account.ws_token, "jwt": account.jwt}


def _account_user_id(account: Dict[str, Any] | Account) -> int:
    if isinstance(account, dict):
        return int(account["user_id"])
    return int(account.user_id)


def build_worker_tiers(state: RuntimeState) -> List[WorkerTier]:
    """Split the account pool into premium, fast, and fallback tiers."""
    premium: List[Dict[str, Any]] = []
    fast: List[Dict[str, Any]] = []
    fallback: List[Dict[str, Any]] = []

    for account in state.accounts:
        normalized = _account_payload(account)
        user_id = _account_user_id(normalized)
        health = state.worker_health.get(user_id)
        if health is None:
            fallback.append(normalized)
            continue
        success_count = getattr(health, "success_count", 0)
        failure_count = getattr(health, "failure_count", 0)
        if success_count >= 2 and failure_count <= 1:
            premium.append(normalized)
        elif success_count >= 1 or failure_count <= 2:
            fast.append(normalized)
        else:
            fallback.append(normalized)

    return [
        WorkerTier(name="premium", accounts=premium),
        WorkerTier(name="fast", accounts=fast),
        WorkerTier(name="fallback", accounts=fallback),
    ]


class AdaptiveMetrics:
    """Track throughput and win rate for the active worker pool."""

    def __init__(self) -> None:
        self.attempts = 0
        self.wins = 0
        self.total_gold = 0
        self.started_at = time.time()

    def record_result(self, won: bool, gold: int) -> None:
        self.attempts += 1
        if won:
            self.wins += 1
            self.total_gold += gold

    def win_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.wins / self.attempts

    def throughput(self) -> float:
        elapsed = max(1.0, time.time() - self.started_at)
        return self.attempts / elapsed


class AdaptiveRunner:
    """Thin orchestration layer for tiered workers and queue-based task execution."""

    def __init__(self, state: RuntimeState) -> None:
        self.state = state
        self.metrics = AdaptiveMetrics()
        self.queue = OpportunityQueue()
        self.tiers = build_worker_tiers(state)

    def push_opportunity(self, opportunity: Dict[str, Any]) -> None:
        self.queue.enqueue(opportunity)

    def next_worker(self) -> Optional[Dict[str, Any]]:
        for tier in self.tiers:
            if tier.accounts:
                return tier.accounts[0]
        return None

    def run_once(self, opportunity: Dict[str, Any], claim_fn: Any) -> Dict[str, Any]:
        worker = self.next_worker()
        if worker is None:
            return {"ok": False, "gold": 0, "message": "no worker available"}
        result = claim_fn(worker, opportunity.get("room_id"), opportunity.get("bag_id"))
        self.metrics.record_result(bool(result.get("ok")), int(result.get("gold", 0) or 0))
        return result

    def summary(self) -> Dict[str, Any]:
        return {
            "tiers": [tier.name for tier in self.tiers],
            "attempts": self.metrics.attempts,
            "wins": self.metrics.wins,
            "win_rate": self.metrics.win_rate(),
            "throughput_per_sec": self.metrics.throughput(),
            "total_gold": self.metrics.total_gold,
        }
