#!/usr/bin/env python3
import time, json, re, base64, hashlib
import requests, random, os, sys, uuid

# from mel import wait_for_new_otp, wait_for_new_otp_for_target
from mailisa import wait_for_new_otp_for_target

API_BASE = "https://api.dazz2.com"
PATH_SEND = "/api/go_v3/dazz/send_email_code"
PATH_CHECK = "/api/go_v3/dazz/check_email_code"
PATH_BIND = "/api/go_v3/dazz/bind_email"

# Replace with your real token


DEVICE_ID = str(uuid.uuid4())
APP_VERSION = "1.8.6"
CHANNEL_ID = "3"
FACILITY = "1"
LANG = "id"
PACKAGE_TYPE = "Android-Google"


# ---- sign generation (copied from your apiberanda.py) ----
def generate_sign_from_payload(payload):
    """
    Uses the same algorithm from apiberanda.py:
      - filters out CREATOR, serialVersionUID, sign
      - sorts items by key
      - builds "k=v&k2=v2...&key=SECRET"
      - md5 hex digest returned
    """
    # default sign filler if not present (keeps behavior same as original)
    if not payload.get("sign"):
        payload["sign"] = hashlib.md5("12345678987654321".encode("utf-8")).hexdigest()

    secret_key = "5d206b343f87f2ca3a0aa05c58b9a64d"

    filtered = {
        k: v
        for k, v in payload.items()
        if k not in ["CREATOR", "serialVersionUID", "sign"]
    }

    sorted_items = sorted(filtered.items())

    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)

    full_string = f"{param_str}&key={secret_key}"
    md5_result = hashlib.md5(full_string.encode("utf-8")).hexdigest()

    return md5_result


# --------------------------------------------------------


def _extract_userid_from_jwt(token: str):
    if not token:
        return None
    if token.lower().startswith("bearer "):
        token = token.split(None, 1)[1]
    parts = token.split(".")
    if len(parts) < 2:
        return None
    b64 = parts[1]
    b64 += "=" * ((4 - len(b64) % 4) % 4)
    b64 = b64.replace("-", "+").replace("_", "/")
    try:
        payload = base64.b64decode(b64)
        j = json.loads(payload.decode("utf-8", errors="ignore"))
        for k in ("userId", "user_id", "uid", "id", "sub", "userid", "user_id"):
            if k in j:
                return str(j[k])
        for k, v in j.items():
            if isinstance(v, int) or (
                isinstance(v, str) and re.fullmatch(r"\d{4,}", v)
            ):
                return str(v)
    except Exception as e:
        print(f"[!] JWT decode failed: {e}")
        return None
    return None


def _post(path, payload, token, app_version=APP_VERSION, timeout=30):
    headers = {
        "Host": "api.dazz2.com",
        "encrypt-type": "1",
        "user-agent": app_version,
        "authorization-token": (
            token.split(None, 1)[1]
            if token and token.lower().startswith("bearer ")
            else token
        ),
        "content-type": "application/json; charset=UTF-8",
        "accept-encoding": "gzip",
        "cache-control": "no-cache",
    }
    url = API_BASE.rstrip("/") + path
    r = requests.post(url, json=payload, headers=headers, timeout=timeout)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text


def send_email_code(email, token, code_type: int = 0):
    user_id = _extract_userid_from_jwt(token)
    payload = {
        "account_type": 0,
        "code_type": code_type,
        "email": email,
        "type": 0,
        "app_version": APP_VERSION,
        "channel_id": CHANNEL_ID,
        "device_id": DEVICE_ID,
        "facility": FACILITY,
        "lang": LANG,
        "package_type": PACKAGE_TYPE,
        "time": str(int(time.time())),
        # user_id will be added below if present
    }
    if user_id:
        payload["user_id"] = user_id

    # compute sign using your working function
    payload["sign"] = generate_sign_from_payload(payload)
    return _post(PATH_SEND, payload, token)


def check_email_code(token, code):
    user_id = _extract_userid_from_jwt(token)
    payload = {
        "account_type": 0,
        "code": code,
        "code_type": 1,
        "type": 0,
        "app_version": APP_VERSION,
        "channel_id": CHANNEL_ID,
        "device_id": DEVICE_ID,
        "facility": FACILITY,
        "lang": LANG,
        "package_type": PACKAGE_TYPE,
        "time": str(int(time.time())),
    }
    if user_id:
        payload["user_id"] = user_id

    payload["sign"] = generate_sign_from_payload(payload)
    return _post(PATH_CHECK, payload, token)


def bind_email(email, token, code):
    user_id = _extract_userid_from_jwt(token)
    payload = {
        "account_type": 0,
        "code": code,
        "code_type": 0,
        "email": email,
        "type": 0,
        "app_version": APP_VERSION,
        "channel_id": CHANNEL_ID,
        "device_id": DEVICE_ID,
        "facility": FACILITY,
        "lang": LANG,
        "package_type": PACKAGE_TYPE,
        "time": str(int(time.time())),
    }
    if user_id:
        payload["user_id"] = user_id

    payload["sign"] = generate_sign_from_payload(payload)
    return _post(PATH_BIND, payload, token)


def set_password(
    token,
    password,
    device_id=DEVICE_ID,
    app_version=APP_VERSION,
    channel_id=CHANNEL_ID,
    facility=FACILITY,
    lang=LANG,
    package_type=PACKAGE_TYPE,
    code_type=0,
    type_=1,
):
    user_id = _extract_userid_from_jwt(token)
    payload = {
        "code_type": code_type,
        "pwd_str": password,
        "type": type_,
        "app_version": app_version,
        "channel_id": channel_id,
        "device_id": device_id,
        "facility": facility,
        "lang": lang,
        "package_type": package_type,
        "time": str(int(time.time())),
    }
    if user_id:
        payload["user_id"] = user_id

    payload["sign"] = generate_sign_from_payload(payload)
    return _post("/api/go_v3/dazz/set_password", payload, token)


def unbind_account(
    token,
    code,
    account_type=3,
    code_type=0,
    type_=0,
    device_id=DEVICE_ID,
    app_version=APP_VERSION,
    channel_id=CHANNEL_ID,
    facility=FACILITY,
    lang=LANG,
    package_type=PACKAGE_TYPE,
):
    user_id = _extract_userid_from_jwt(token)
    payload = {
        "account_type": account_type,
        "code": code,
        "code_type": code_type,
        "type": type_,
        "app_version": app_version,
        "channel_id": channel_id,
        "device_id": device_id,
        "facility": facility,
        "lang": lang,
        "package_type": package_type,
        "time": str(int(time.time())),
    }
    if user_id:
        payload["user_id"] = user_id

    payload["sign"] = generate_sign_from_payload(payload)
    return _post("/api/go_v3/dazz/unbind_account", payload, token)


def binding(email: str, token: str, otp_code: str):
    if not otp_code:
        print(">>> Sending email code...")
        status, resp = send_email_code(email, token, 1)
        print(status, resp)
        time.sleep(3)

        otp_code = wait_for_new_otp_for_target(
            target_receiver=email,
            expected_sender="dazz.vip@m.dazz.live",  # optional
            timeout=180,
        )
        if otp_code is None:
            send_email_code(email, token, 1)
        print("Bind OTP:", otp_code)

    print(">>> Binding email...")
    status, resp = bind_email(email, token, otp_code)
    print("code first step:", resp.get("code"))
    if resp.get("code")==1009: # email sudah di pake
        return True
    
    while resp.get("code") != 0:
        print("code", resp.get("code"))
        if resp.get("code")==1009:
            return True
        otp = wait_for_new_otp_for_target(
            target_receiver=email,
            expected_sender="dazz.vip@m.dazz.live",  # optional
            timeout=180,
        )
        if otp is None:
            print(">>> Sending email code...")
            send_email_code(email, token, 1)
            time.sleep(3)

        print(f"Bind OTP: {otp}")
        print(">>> Binding email...")
        status, resp = bind_email(email, token, otp)
        print(status, resp)

    return True


def ini_set_password(token: str):
    DEVICE_ID = str(uuid.uuid4()).replace("-","")
    PASSWORD = DEVICE_ID[17:]
    print(">>> Setting password...")
    status, resp = set_password(token=token, device_id=DEVICE_ID, password=PASSWORD)
    print(status, resp)
    with open("regist.txt", "a") as nh:
        nh.write(f"{token},{DEVICE_ID},{PASSWORD}")
        nh.write("\n")

    return (True) if resp.get("code") == 0 else False


def unbind(email: str, token: str, otp: str):

    if not otp:
        print("Otw unbinding.. ")
        print(">>> Sending email code for unbinding...")
        status, resp = send_email_code(email, token, 3)
        print(status, resp)
        # === UNBIND OTP ===
        otp = wait_for_new_otp_for_target(
            target_receiver=email,
            expected_sender="dazz.vip@m.dazz.live",  # optional
            timeout=180,
        )
        if otp is None:
            send_email_code(email, token, 3)
        print("Unbind OTP:", otp)

    print(">>> Unbinding account...")
    status_code, resp_code = unbind_account(token, otp)

    print("code first step:", resp_code.get("code"))
    while resp_code.get("code") != 0:
        otp_code = wait_for_new_otp_for_target(
            target_receiver=email,
            expected_sender="dazz.vip@m.dazz.live",  # optional
            timeout=180,
        )
        if otp_code is None:
            print("Otw unbinding.. ")
            print(">>> Sending email code for unbinding...")
            status, resp = send_email_code(email, token, 3)
            print(status, resp)

        print(f"UNBIND OTP: {otp_code}")
        print(">>> UNBinding email...")

        status_code, resp_code = unbind_account(token, otp_code)
        print(status_code, resp_code)

    return True

# area anda tidak bla bla isVpn: 1
# akun anda telah di blokir, string device id di blacklist.
if __name__ == "__main__":
    token = "eyJ0eXAiOiJKV1QiLCAiYWxnIjoiU0hBMjU2In0.eyJpc3MiOiIiLCJpYXQiOjE3NjUzMzI3OTEsImV4cCI6MTc2NTkzNzU5MSwidXNlcl9pZCI6MjAxNjU2NTMsInRvdXJpc3RfdXJpIjoiIn0.5babcb046c36e6927d9569a96ace33d70e8998c5832aa92f86bbb94cf9df01a4"

    user_id = _extract_userid_from_jwt(token)
    email = (
        f"{user_id}@jamet.space"
        if user_id
        else f"{random.randint(100000, 900000)}@jamet.space"
    )

    a = 1
    if a:
        # ini_set_password(token)
        # binding(email, token, otp_code="")
        if ini_set_password(token):
            print("Email:", email)
            unbind(email, token, otp="")
            sys.exit(1)

    print("Email:", email)
    unbind(email, token, otp="")
