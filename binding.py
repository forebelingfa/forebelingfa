#!/usr/bin/env python3
import time, json, re, base64
import binascii
import requests, random, os, sys, uuid

# from mel import wait_for_new_otp, wait_for_new_otp_for_target
from mailisa import EMAIL_DOMAIN, wait_for_new_otp_for_target
from api import API_BASE, generate_sign_from_payload

PATH_SEND = "go_v3/limoo/send_email_code"
PATH_CHECK = "go_v3/limoo/check_email_code"
PATH_BIND = "go_v3/limoo/bind_email"
PATH_PASSWORD = "go_v3/limoo/set_password"
PATH_UNBIND = "go_v3/limoo/unbind_account"

# Replace with your real token


DEVICE_ID = str(uuid.uuid4()).replace("-", "")
APP_VERSION = "1.2.1"
CHANNEL_ID = "3"
FACILITY = "1"
LANG = "id"
PACKAGE_TYPE = "Android-Google"


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
    except (ValueError, UnicodeDecodeError, binascii.Error) as e:
        print(f"[!] JWT decode failed: {e}")
        return None
    return None


def _post(path, payload, token, app_version=APP_VERSION, timeout=30):
    headers = {
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
    url = f"{API_BASE.rstrip('/')}/{path.lstrip('/')}"
    r = requests.post(url, json=payload, headers=headers, timeout=timeout)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def _is_success(response):
    return isinstance(response, dict) and str(response.get("code")) in {"0", "200"}


def send_email_code(email, token, code_type: int = 1):
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
    return _post(PATH_PASSWORD, payload, token)


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
        "fake": 0,
        "lang": lang,
        "package_type": package_type,
        "time": str(int(time.time())),
        "tourist_uri": "",
    }
    if user_id:
        payload["user_id"] = user_id

    payload["sign"] = generate_sign_from_payload(payload)
    print(payload)
    return _post(PATH_UNBIND, payload, token)


def binding(email: str, token: str, otp_code: str):
    if not otp_code:
        print(">>> Sending email code...")
        status, resp = send_email_code(email, token, 1)
        print(status, resp)
        if not _is_success(resp):
            return False
        time.sleep(3)

        otp_code = wait_for_new_otp_for_target(
            target_receiver=email,
            timeout=120,
        )
        if otp_code is None:
            print("❌ Timed out waiting for Tamil email verification code")
            return False
        print("Bind OTP received")

    print(">>> Binding email...")
    status, resp = bind_email(email, token, otp_code)
    print(status, resp)
    return _is_success(resp)


def ini_set_password(token: str):
    DEVICE_ID = str(uuid.uuid4()).replace("-","")
    PASSWORD = "hellofool31" #DEVICE_ID[17:]
    print(">>> Setting password...")
    status, resp = set_password(token=token, device_id=DEVICE_ID, password=PASSWORD)
    print(status, resp)
    if not _is_success(resp):
        return False

    with open("tamil.txt", "a") as nh:
        nh.write(f"{token},{DEVICE_ID},{PASSWORD}\n")
    return True


def unbind(email: str, token: str, otp: str):

    if not otp:
        print("Otw unbinding.. ")
        print(">>> Sending email code for unbinding...")
        status, resp = send_email_code(email, token, 3)
        print(status, resp)
        if not _is_success(resp):
            return False
        otp = wait_for_new_otp_for_target(
            target_receiver=email,
            timeout=120,
        )
        if otp is None:
            print("❌ Timed out waiting for Tamil unbind verification code")
            return False
        print("Unbind OTP received")

    print(">>> Unbinding account...")
    status_code, resp_code = unbind_account(token, otp)
    print(status_code, resp_code)
    return _is_success(resp_code)

# area anda tidak bla bla isVpn: 1
# akun anda telah di blokir, string device id di blacklist.
if __name__ == "__main__":
    token = "eyJ0eXAiOiJKV1QiLCAiYWxnIjoiU0hBMjU2In0.eyJpc3MiOiIiLCJpYXQiOjE3OTE0NTUyOTksImV4cCI6MTc5MjA2MDA5OSwidXNlcl9pZCI6MTA2ODAxMTAsInRvdXJpc3RfdXJpIjoiIn0.e3e327bb9a4f0b83f70c912a2e89d402631c10a4807fa97214c0ea25ffe76ce9"

    user_id = _extract_userid_from_jwt(token)
    email = (
        f"{user_id}@{EMAIL_DOMAIN}"
        if user_id
        else f"{random.randint(100000, 900000)}@{EMAIL_DOMAIN}"
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
# REGISTRATION_TOKENS:{"jwt":"eyJ0eXAiOiJKV1QiLCAiYWxnIjoiU0hBMjU2In0.eyJpc3MiOiIiLCJpYXQiOjE3OTE0MzY2NzQsImV4cCI6MTc5MjA0MTQ3NCwidXNlcl9pZCI6MTA2Nzg0MTMsInRvdXJpc3RfdXJpIjoiIn0.db134998725fbde79f729ff07928e8157f3636e64807a6824aa49554190fd7b5","ws_token":"e9b5438f2941a54b","user_id":"10678413"}