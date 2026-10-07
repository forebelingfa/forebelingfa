from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

try:
    import requests
except Exception:  # pragma: no cover - optional dependency
    requests = None

from config import DEFAULT_CONFIG


@dataclass
class RoomOpportunity:
    room_id: int
    owner_nick: str = ""
    bag_id: Optional[int] = None
    value: int = 0
    discovered_at: float = field(default_factory=time.time)
    source: str = "poller"


class RoomPoller:
    """Poll the room discovery endpoint and extract LuckyBag opportunities."""

    def __init__(
        self,
        endpoint: str = DEFAULT_CONFIG.poll_url,
        session: Optional[Any] = None,
        poll_interval_seconds: float = 5.0,
        fallback_endpoints: Optional[List[str]] = None,
    ) -> None:
        self.endpoint = endpoint
        self.poll_interval_seconds = poll_interval_seconds
        self.session = session or (requests.Session() if requests is not None else None)
        self.fallback_endpoints = list(
            fallback_endpoints if fallback_endpoints is not None else DEFAULT_CONFIG.poll_urls
        )
        if self.endpoint not in self.fallback_endpoints:
            self.fallback_endpoints.insert(0, self.endpoint)

    def _candidate_endpoints(self) -> List[str]:
        ordered = []
        seen = set()
        for url in self.fallback_endpoints:
            if url and url not in seen:
                seen.add(url)
                ordered.append(url)
        return ordered

    @staticmethod
    def _coerce_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _extract_rows(self, payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("rooms", "items", "data", "list", "room_list", "hot_rooms"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
                if isinstance(value, dict):
                    return [value]
            return [payload]
        return []

    def _parse_room(self, room: Dict[str, Any]) -> Optional[RoomOpportunity]:
        room_id = (
            room.get("room_id")
            or room.get("roomId")
            or room.get("id")
            or room.get("roomID")
        )
        if room_id is None:
            return None

        lucky_flag = (
            room.get("red_packet_logo")
            or room.get("has_lucky_bag")
            or room.get("lucky_bag")
            or room.get("hasLuckyBag")
            or room.get("open_luckybag")
        )
        if lucky_flag in (0, False, None):
            return None

        bag_id = room.get("bag_id") or room.get("lucky_bag_id") or room.get("bagId")
        value = (
            room.get("task_gold")
            or room.get("bag_value")
            or room.get("gold")
            or room.get("reward")
            or room.get("money")
            or 0
        )
        owner_nick = (
            room.get("owner_nick")
            or room.get("ownerNick")
            or room.get("nick_name")
            or room.get("nickname")
            or ""
        )

        return RoomOpportunity(
            room_id=self._coerce_int(room_id),
            owner_nick=str(owner_nick),
            bag_id=self._coerce_int(bag_id) if bag_id not in (None, "") else None,
            value=self._coerce_int(value),
            discovered_at=time.time(),
            source="poller",
        )

    def poll_once(self) -> List[RoomOpportunity]:
        if not self.session:
            return []

        for url in self._candidate_endpoints():
            try:
                response = self.session.get(url, timeout=10)
                response.raise_for_status()
                payload = response.json()
            except Exception:
                continue

            if isinstance(payload, dict):
                code = payload.get("code")
                message = payload.get("message")
                if code not in (None, 0, 200) and "System Error" in str(message or ""):
                    continue

            opportunities: List[RoomOpportunity] = []
            for room in self._extract_rows(payload):
                parsed = self._parse_room(room)
                if parsed is not None:
                    opportunities.append(parsed)
            if opportunities:
                return opportunities

        return []

    def poll_forever(self, max_iterations: Optional[int] = None) -> Iterable[RoomOpportunity]:
        iterations = 0
        while True:
            if max_iterations is not None and iterations >= max_iterations:
                break
            iterations += 1
            for opportunity in self.poll_once():
                yield opportunity
            time.sleep(self.poll_interval_seconds)
