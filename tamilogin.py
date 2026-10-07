import requests
import json
import hashlib
import time
import string, random
import datetime

timestamp = int(time.time())


def generate_sign_from_payload(payload):
    if not payload.get("sign"):
        payload["sign"] = hashlib.md5("12345678987654321".encode("utf-8")).hexdigest()
    secret_key = "5d206b343f87f2ca3a0aa05c58b9a64d"
    filtered = {k: v for k, v in payload.items() if k not in ["CREATOR","serialVersionUID","sign"]}
    sorted_items = sorted(filtered.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
    full_string = f"{param_str}&key={secret_key}"
    return hashlib.md5(full_string.encode("utf-8")).hexdigest()

def generate_device_id(length=32):
    hex_chars = string.hexdigits.lower()[:16]
    return ''.join(random.choice(hex_chars) for _ in range(length))


def DZLOGIN(bot_id, bot_pwd, bot_alias):
    url = "https://api.taalmil.live/api/simple/login"

    payload = {
        "code_type": 0,
        "pwd_str": f"{bot_pwd}",
        "type": 0,
        "app_version": "1.2.1",
        "channel_id": "3",
        "device_id":  f"{generate_device_id()}",
        "facility": "1",
        "lang": "id",
        "package_type": "Android-Google",
        "sign": "",
        "time": f"{timestamp}",
        "user_id": f"{bot_id}"
    }

    payload["sign"] = generate_sign_from_payload(payload)

    headers = {
    'User-Agent': "1.2.1",
    'Accept-Encoding': "gzip",
    'encrypt-type': "1",
    'content-type': "application/json; charset=UTF-8",
    'cache-control': "no-cache"
    }

    # Proxy config
    proxy_url = (
        "http://mr111593sXbg:"
        "M18oNxpeAs_country-id"
        "@ultra.marsproxies.com:44443"
    )

    proxies = {
        "http": proxy_url,
        "https": proxy_url
    }

    response = requests.post(url, data=json.dumps(payload), headers=headers, proxies=proxies)

    xdata = response.json()['data']

    idbot = xdata['user_id']
    bwstoken = xdata['token']
    bwjwt = xdata['jwt_authorization_token']

    print(f"{idbot},{bwstoken},{bwjwt}")


#ini akun baru bud tinggal login 
TLIST = [10673652,10673660,10673667,10673675,10673690]

for idlist in TLIST:
    DZLOGIN(idlist, "jiang123","TML")
