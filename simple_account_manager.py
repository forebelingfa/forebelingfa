from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def load_accounts(path: str | Path) -> List[Dict[str, Any]]:
    """Load accounts from a plain text file.

    Expected format per line:
        userId,ws_token,jwt

    Example:
        1001,abc123,eyJ...
    """
    file_path = Path(path)
    accounts: List[Dict[str, Any]] = []

    with file_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 3:
                raise ValueError(
                    f"Invalid account format in {file_path} at line {line_number}: "
                    f"expected 'userId,ws_token,jwt'"
                )

            user_id_raw, ws_token, jwt = parts
            try:
                user_id = int(user_id_raw)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid user_id '{user_id_raw}' in {file_path} at line {line_number}"
                ) from exc

            if not ws_token:
                raise ValueError(f"Empty ws_token in {file_path} at line {line_number}")
            if not jwt:
                raise ValueError(f"Empty jwt in {file_path} at line {line_number}")

            accounts.append({
                "user_id": user_id,
                "ws_token": ws_token,
                "jwt": jwt,
            })

    if not accounts:
        raise ValueError(f"No valid accounts found in {file_path}")

    return accounts
