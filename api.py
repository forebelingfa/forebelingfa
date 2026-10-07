#!/usr/bin/env python3
"""Authenticated REST helpers for the Tamil app API.

Only endpoints confirmed against api.taalmil.live are included here. Dazz H5,
legacy static-IP, and app-branded endpoints are intentionally not redirected.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Dict, List, Optional

import requests

API_BASE = "https://api.taalmil.live/api"
APP_VERSION = "2.1.5"
API_SIGNING_SECRET = "5d206b343f87f2ca3a0aa05c58b9a64d"
TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
DEFAULT_TIMEOUT = 10.0

session = requests.Session()


class TamilAPIError(RuntimeError):
    """Raised when the Tamil API request or application response fails."""


def generate_sign_from_payload(payload: Dict[str, Any]) -> str:
    """Generate the confirmed MD5 signature for Tamil app API payloads."""
    filtered = {
        key: value
        for key, value in payload.items()
        if key not in {"CREATOR", "serialVersionUID", "sign"}
    }
    param_string = "&".join(f"{key}={value}" for key, value in sorted(filtered.items()))
    signed_string = f"{param_string}&key={API_SIGNING_SECRET}"
    return hashlib.md5(signed_string.encode("utf-8")).hexdigest()


def _headers(jwt_token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": APP_VERSION,
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json; charset=UTF-8",
        "encrypt-type": "1",
        "cache-control": "no-cache",
    }
    if jwt_token:
        headers["authorization-token"] = jwt_token.strip()
    return headers


def _post(
    endpoint: str,
    payload: Dict[str, Any],
    jwt_token: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
) -> Dict[str, Any]:
    """Post one signed app payload; retry only transport/server failures."""
    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    last_error: Optional[Exception] = None

    for attempt in range(retries + 1):
        signed_payload = dict(payload)
        signed_payload["sign"] = generate_sign_from_payload(signed_payload)
        try:
            response = session.post(
                url,
                json=signed_payload,
                headers=_headers(jwt_token),
                timeout=timeout,
            )
            if response.status_code in TRANSIENT_HTTP_STATUSES and attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 4))
                continue
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 4))
                continue
            raise TamilAPIError(f"{endpoint}: request failed: {exc}") from exc
        except ValueError as exc:
            raise TamilAPIError(f"{endpoint}: server returned invalid JSON") from exc

        if not isinstance(result, dict):
            raise TamilAPIError(f"{endpoint}: response was not a JSON object")
        return result

    raise TamilAPIError(f"{endpoint}: request failed: {last_error}")


def _require_success(result: Dict[str, Any], endpoint: str) -> Dict[str, Any]:
    if str(result.get("code")) not in {"0", "200"}:
        code = result.get("code", "missing")
        message = result.get("msg") or result.get("message") or "no error message"
        raise TamilAPIError(f"{endpoint}: API code={code}: {message}")
    return result


def login_tamil(user_id: str | int, password: str, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """Log in with app credentials and return the server response."""
    payload = {
        "code_type": 0,
        "pwd_str": str(password),
        "type": 20,
        "app_version": APP_VERSION,
        "channel_id": "3",
        "device_id": uuid.uuid4().hex,
        "facility": "1",
        "lang": "id",
        "package_type": "Android-Google",
        "time": str(int(time.time())),
        "user_id": str(user_id),
    }
    return _post("simple/login", payload, timeout=timeout)


def get_user_info(
    user_id: str | int,
    jwt_token: str,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
) -> Dict[str, Any]:
    """Fetch a public profile, including its current room ID and gold."""
    payload = {
        "id": str(user_id),
        "version": "1.0",
        "app_version": APP_VERSION,
        "channel_id": "3",
        "device_id": uuid.uuid4().hex,
        "facility": "1",
        "lang": "id",
        "package_type": "Android-Google",
        "time": str(int(time.time())),
        "user_id": str(user_id),
    }
    result = _require_success(
        _post("member/info", payload, jwt_token=jwt_token, timeout=timeout, retries=retries),
        "member/info",
    )
    if not isinstance(result.get("data"), dict):
        raise TamilAPIError("member/info: response did not contain profile data")
    return result


def get_room_id(user_id: str | int, jwt_token: str, timeout: float = DEFAULT_TIMEOUT) -> int:
    """Return a user's active room ID, or zero when they are not in a room."""
    info = get_user_info(user_id, jwt_token, timeout=timeout)
    room_id = info["data"].get("room_id")
    try:
        return int(room_id) if room_id not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def list_hot_anchors(
    page: int,
    jwt_token: str,
    user_id: int,
    timeout: float = DEFAULT_TIMEOUT,
) -> List[Dict[str, Any]]:
    """Fetch one page from the verified `/home/hot_anchor` endpoint."""
    if page < 1:
        raise ValueError("page must be at least 1")
    payload = {
        "classify_id": 0,
        "device_id": uuid.uuid4().hex,
        "group_id": 0,
        "home_id": 0,
        "lang": "id",
        "package_type": "haigou-Android",
        "page": page,
        "pkg": "3",
        "time": str(int(time.time())),
        "type": 1,
        "user_id": int(user_id),
        "version": APP_VERSION,
    }
    result = _require_success(
        _post("home/hot_anchor", payload, jwt_token=jwt_token, timeout=timeout),
        "home/hot_anchor",
    )
    data = result.get("data", {})
    rows = data.get("data", []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        raise TamilAPIError("home/hot_anchor: response data.data was not a list")
    return [row for row in rows if isinstance(row, dict)]


def list_beranda(page: int, jwt_token: str, user_id: int) -> Dict[str, Any]:
    """Return the Dazz-compatible nickname-to-room mapping for one page."""
    return {
        str(room.get("nickname") or room.get("user_id")): room.get("room_id")
        for room in list_hot_anchors(page, jwt_token, user_id)
        if room.get("room_id") not in (None, "")
    }


def get_all_rooms(
    jwt_token: str,
    user_id: int,
    max_pages: int = 100,
    page_delay: float = 0.1,
) -> Dict[str, Any]:
    """Fetch hot-anchor pages until exhausted, with an explicit safety limit."""
    if max_pages < 1 or page_delay < 0:
        raise ValueError("max_pages must be positive and page_delay cannot be negative")
    rooms: Dict[str, Any] = {}
    for page in range(1, max_pages + 1):
        page_rows = list_hot_anchors(page, jwt_token, user_id)
        if not page_rows:
            break
        for room in page_rows:
            room_id = room.get("room_id")
            if room_id not in (None, ""):
                name = str(room.get("nickname") or room.get("user_id") or room_id)
                rooms[name] = room_id
        if page_delay:
            time.sleep(page_delay)
    return rooms


def fetch_lucky_bag_rooms(
    jwt_token: str,
    user_id: int,
    max_pages: int = 100,
    page_delay: float = 0.1,
) -> List[Dict[str, Any]]:
    """Return hot-anchor records marked with `red_packet_logo == 1`."""
    if max_pages < 1 or page_delay < 0:
        raise ValueError("max_pages must be positive and page_delay cannot be negative")
    matches: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        rows = list_hot_anchors(page, jwt_token, user_id)
        if not rows:
            break
        matches.extend(row for row in rows if str(row.get("red_packet_logo")) == "1")
        if page_delay:
            time.sleep(page_delay)
    return matches
