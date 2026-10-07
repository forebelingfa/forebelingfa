from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from resilience import score_opportunity
from runtime_state import RuntimeState


@dataclass
class BagOpportunity:
    room_id: int
    bag_id: int
    bag_value: int = 0
    discovered_at: float = field(default_factory=time.time)
    source: str = "manual"
    room_activity: int = 0


def score_bag_opportunity(opportunity: BagOpportunity, worker_count: int = 1) -> float:
    """Prioritize high value and recently discovered bags."""
    return score_opportunity(opportunity, worker_count=worker_count, room_activity=opportunity.room_activity)


class WorkerScheduler:
    """Schedule the fastest healthy worker for the next claim opportunity."""

    def __init__(self, state: RuntimeState, max_failures: int = 3, stale_after_seconds: float = 300.0):
        self.state = state
        self.max_failures = max_failures
        self.stale_after_seconds = stale_after_seconds

    @staticmethod
    def _account_user_id(account: Dict[str, Any] | Any) -> int:
        if isinstance(account, dict):
            return int(account["user_id"])
        return int(account.user_id)

    @staticmethod
    def _account_record(account: Dict[str, Any] | Any) -> Dict[str, Any]:
        if isinstance(account, dict):
            return account
        return {
            "user_id": account.user_id,
            "ws_token": account.ws_token,
            "jwt": account.jwt,
        }

    def _health_for(self, user_id: int) -> Optional[Any]:
        return self.state.worker_health.get(user_id)

    def _is_viable(self, account: Dict[str, Any] | Any) -> bool:
        user_id = self._account_user_id(account)
        health = self._health_for(user_id)
        if health is None:
            return True
        if not getattr(health, "is_healthy", True):
            return False
        if getattr(health, "failure_count", 0) >= self.max_failures:
            return False
        return True

    def _rank_key(self, account: Dict[str, Any] | Any):
        user_id = self._account_user_id(account)
        health = self._health_for(user_id)
        failure_count = getattr(health, "failure_count", 0)
        success_count = getattr(health, "success_count", 0)
        last_result = getattr(health, "last_result", "unknown")
        connected = getattr(health, "connected", False)

        penalty = failure_count * 100
        if last_result == "failure":
            penalty += 25
        if not connected:
            penalty += 10
        bonus = success_count * 20
        return (penalty - bonus, 0 if connected else 1, user_id)

    def pick_worker(self) -> Optional[Dict[str, Any]]:
        viable = [account for account in self.state.accounts if self._is_viable(account)]
        if not viable:
            return None
        chosen = min(viable, key=self._rank_key)
        return self._account_record(chosen)

    def rotate_stale_accounts(self) -> List[int]:
        stale_ids: List[int] = []
        now = time.time()
        for user_id, health in self.state.worker_health.items():
            if getattr(health, "failure_count", 0) >= self.max_failures:
                stale_ids.append(user_id)
                continue
            if not getattr(health, "is_healthy", True):
                stale_ids.append(user_id)
                continue
            last_seen = getattr(health, "last_seen", 0.0) or 0.0
            if getattr(health, "last_result", "unknown") == "failure" and last_seen and now - last_seen > self.stale_after_seconds:
                stale_ids.append(user_id)
        return stale_ids

    def schedule(
        self,
        opportunities: Iterable[BagOpportunity],
        claim_fn: Callable[[Dict[str, Any], int, int], Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        ordered = sorted(opportunities, key=score_bag_opportunity, reverse=True)
        results: List[Dict[str, Any]] = []

        for opportunity in ordered:
            account = self.pick_worker()
            if account is None:
                break

            result = claim_fn(account, opportunity.room_id, opportunity.bag_id)
            user_id = int(account["user_id"])
            ok = bool(result.get("ok"))
            message = str(result.get("message", "")).strip()
            self.state.mark_worker_result(user_id, ok, message)
            results.append({
                "user_id": user_id,
                "room_id": opportunity.room_id,
                "bag_id": opportunity.bag_id,
                "ok": ok,
                "gold": int(result.get("gold", 0) or 0),
                "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
                "message": message,
            })

        return results
