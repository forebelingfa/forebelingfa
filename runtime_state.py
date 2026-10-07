from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class Account:
    user_id: int
    ws_token: str
    jwt: str

    @classmethod
    def from_line(cls, line: str, line_number: int) -> "Account":
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            raise ValueError(
                f"Invalid account format at line {line_number}: expected userId,ws_token,jwt"
            )
        user_id_str, ws_token, jwt = parts
        try:
            user_id = int(user_id_str)
        except ValueError as exc:
            raise ValueError(f"Invalid user_id '{user_id_str}' at line {line_number}") from exc
        if not ws_token:
            raise ValueError(f"Empty ws_token at line {line_number}")
        if not jwt:
            raise ValueError(f"Empty jwt at line {line_number}")
        return cls(user_id=user_id, ws_token=ws_token, jwt=jwt)


@dataclass
class WorkerHealth:
    user_id: int
    connected: bool = False
    last_result: str = "unknown"
    last_error: str = ""
    last_reason: str = "unknown"
    success_count: int = 0
    failure_count: int = 0
    is_healthy: bool = True
    last_seen: float = 0.0


@dataclass
class RuntimeState:
    accounts: List[Account] = field(default_factory=list)
    worker_health: Dict[int, WorkerHealth] = field(default_factory=dict)
    packet_log: List[Dict[str, Any]] = field(default_factory=list)
    failure_reasons: Dict[str, int] = field(default_factory=dict)

    @classmethod
    def load_from_file(cls, file_path: str | Path) -> "RuntimeState":
        path = Path(file_path)
        state = cls()
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                account = Account.from_line(line, line_number)
                state.accounts.append(account)
        if not state.accounts:
            raise ValueError(f"No valid accounts found in {path}")
        for account in state.accounts:
            state.worker_health[account.user_id] = WorkerHealth(user_id=account.user_id)
        return state

    def record_packet(self, direction: str, payload: Dict[str, Any]) -> None:
        self.packet_log.append({
            "direction": direction,
            "op": payload.get("op"),
            "body": payload.get("body", {}),
        })

    def mark_worker_result(self, user_id: int, ok: bool, error: str = "") -> None:
        import time

        from resilience import classify_failure

        health = self.worker_health.setdefault(user_id, WorkerHealth(user_id=user_id))
        health.connected = True
        health.last_error = error
        health.last_reason = classify_failure(error)
        self.failure_reasons[health.last_reason] = self.failure_reasons.get(health.last_reason, 0) + (0 if ok else 1)
        health.last_result = "success" if ok else "failure"
        health.last_seen = time.time()
        if ok:
            health.success_count += 1
        else:
            health.failure_count += 1
        health.is_healthy = health.failure_count < 3

    def summary(self) -> Dict[str, Any]:
        return {
            "accounts": len(self.accounts),
            "workers": {
                user_id: {
                    "connected": health.connected,
                    "healthy": health.is_healthy,
                    "last_result": health.last_result,
                    "last_error": health.last_error,
                    "last_reason": health.last_reason,
                    "success_count": health.success_count,
                    "failure_count": health.failure_count,
                }
                for user_id, health in sorted(self.worker_health.items())
            },
            "packet_count": len(self.packet_log),
            "failure_reasons": dict(sorted(self.failure_reasons.items())),
        }
