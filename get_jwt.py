#!/usr/bin/env python3
import json
import base64
import os
import re
import selectors
import subprocess
import sys
import time

PACKAGE = "com.limoolive.stream"
APPNAME = "Taal Mil"
DEVICE_SERIAL = "266c3127"
FRIDA_SCRIPT = os.path.join(os.path.dirname(__file__), "hook_goog.js")
SPAWN_TIMEOUT = 120

JWT_RE = re.compile(r"(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")


def decode_jwt_userid(token):
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded.decode("utf-8", errors="ignore"))
        for key in ("userId", "user_id", "uid", "id", "sub", "userid"):
            if key in claims:
                return str(claims[key])
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    return None


def _extract_auth_result(raw_result):
    if not isinstance(raw_result, dict):
        return None
    data = raw_result.get("data", raw_result)
    if not isinstance(data, dict):
        return None

    jwt = (
        data.get("jwt_authorization_token")
        or data.get("jwt_token")
        or data.get("jwt")
    )
    token = data.get("token") or data.get("ws_token")
    if not isinstance(jwt, str) or not JWT_RE.fullmatch(jwt):
        return None
    if not isinstance(token, str) or not token:
        return None

    user_id = data.get("user_id") or data.get("userId") or decode_jwt_userid(jwt)
    return {
        "jwt": jwt,
        "ws_token": token,
        "user_id": str(user_id) if user_id is not None else "",
    }


def _parse_auth_result_line(line):
    marker = line.find("AUTH_TOKENS:")
    if marker < 0:
        return None
    json_start = line.find("{", marker + len("AUTH_TOKENS:"))
    if json_start < 0:
        return None
    try:
        result, _ = json.JSONDecoder().raw_decode(line[json_start:])
    except json.JSONDecodeError:
        return None
    return _extract_auth_result(result)


def spawn_and_get_auth_result(serial_id):
    command = [
        "frida",
        "-D",
        serial_id,
        "-N",
        PACKAGE,
        "-l",
        FRIDA_SCRIPT,
    ]
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout is None:
        raise RuntimeError("Frida did not provide an output stream")

    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + SPAWN_TIMEOUT
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            remaining = max(0.0, deadline - time.monotonic())
            events = selector.select(timeout=min(1.0, remaining))
            for key, _ in events:
                line = key.fileobj.readline().strip()
                if not line:
                    continue
                if "AUTH_TOKENS:" in line:
                    auth_result = _parse_auth_result_line(line)
                    if auth_result:
                        return auth_result
                    print("Tamil auth response did not contain both session tokens", file=sys.stderr)
                else:
                    print(line, file=sys.stderr)
    finally:
        selector.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    return None


def main(serial_id):
    print(f"Waiting for Tamil Google auth on device {serial_id} ({APPNAME})...")
    result = spawn_and_get_auth_result(serial_id)
    if not result:
        print("ERROR: Did not capture a successful Tamil Google-auth response", file=sys.stderr)
        return None

    print("REGISTRATION_TOKENS:" + json.dumps(result, separators=(",", ":")))
    return result


if __name__ == "__main__":
    subprocess.run(
        [
            "adb",
            "-s",
            DEVICE_SERIAL,
            "shell",
            "monkey",
            "-p",
            PACKAGE,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
        check=True,
    )
    main(DEVICE_SERIAL)
