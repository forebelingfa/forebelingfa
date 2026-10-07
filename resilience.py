from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from speed_scheduler import BagOpportunity


FAILURE_PATTERNS = {
    "expired": ("expired", "habis masa berlakunya", "expired bag", "time expired"),
    "room_missing": ("room not found", "room_missing", "room missing", "unknown room"),
    "blacklisted": ("black", "banned", "isblack"),
    "invalid_token": ("token", "invalid", "signature", "auth"),
    "rate_limited": ("too many", "rate limit", "slow down"),
}


def classify_failure(reason: str) -> str:
    normalized = (reason or "").lower()
    for category, patterns in FAILURE_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            return category
    return "unknown"


class ProtocolDriftDetector:
    """Detect important protocol differences versus the current expected wire format."""

    EXPECTED_OP_FIELDS = {
        1001: {"Code", "UserId"},
        1066: {"UserId", "Score", "RankNum"},
        1067: {"UserId", "LiveTime", "RankNum"},
        1070: {"Sharing", "BGUrl"},
        2014: {"Code", "Open", "CountSwitch"},
        2101: {"Code", "ID", "Gold", "ErrStr"},
    }

    def __init__(self) -> None:
        self.issues: List[str] = []

    def detect(self, payload: Dict[str, Any]) -> bool:
        op = payload.get("op")
        body = payload.get("body", {})
        if op is None or not isinstance(body, dict):
            self.issues.append("missing-op-or-body")
            return True
        required = self.EXPECTED_OP_FIELDS.get(op)
        if required is None:
            return False
        missing = sorted(field for field in required if field not in body)
        if missing:
            self.issues.append(f"missing-fields-op-{op}:{','.join(missing)}")
            return True
        return False


def score_opportunity(opportunity: "BagOpportunity", worker_count: int = 1, room_activity: int = 0) -> float:
    """Prioritize bags with high reward, recent discovery, healthy workers, and room activity."""
    age_seconds = max(0.0, time.time() - opportunity.discovered_at)
    freshness = max(0.0, 180.0 - age_seconds) * 2.0
    reward = (opportunity.bag_value or 1) * 150.0
    activity = float(room_activity or getattr(opportunity, "room_activity", 0)) * 25.0
    worker_pressure = max(0.0, 40.0 - (worker_count * 10.0))
    urgency = max(0.0, 120.0 - age_seconds) * 0.5
    return reward + freshness + activity + worker_pressure + urgency
