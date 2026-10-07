import requests
import time
import re
import base64
import email
from email import policy
import json
import os

MAIL_URL = "https://mail.jamet.space/"
STATE_FILE = "last_seen.json"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print("⚠️ Failed to save state:", e)

def extract_6_digit_code(text: str):
    if not text:
        return None
    m = re.search(r"\b(\d{6})\b", text)
    return m.group(1) if m else None

def strip_html_tags(html: str) -> str:
    """Very basic HTML tag stripper using regex."""
    if not html:
        return ""
    # Remove script/style blocks
    html = re.sub(r"(?is)<(script|style).*?>.*?(</\1>)", "", html)
    # Remove all tags
    text = re.sub(r"(?s)<.*?>", " ", html)
    # Collapse whitespace
    return re.sub(r"\s+", " ", text).strip()

def parse_email_from_raw(raw_base64: str):
    raw_bytes = base64.b64decode(raw_base64)
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                return part.get_content()
            elif ctype == "text/html" and not body:
                body = strip_html_tags(part.get_content())
    else:
        body = msg.get_content()
        if body and body.strip().startswith("<"):
            body = strip_html_tags(body)

    return body

def wait_for_new_otp_for_target(target_receiver,
                                timeout=120,
                                poll_interval=5,
                                expected_sender=None):
    """
    Poll the fetch endpoint until a *new* OTP email arrives.
    Uses a persistent last_seen file to avoid reusing old codes.
    """
    state = load_state()
    last_seen_otp = state.get("last_seen_otp")

    start = time.time()

    while time.time() - start < timeout:
        try:
            r = requests.get(MAIL_URL, params={"to": target_receiver}, timeout=10)
            r.raise_for_status()
            data = r.json()

            if "error" in data or "message" in data:
                print("⏳ No email yet...")
            else:
                sender = data.get("from")
                raw = data.get("raw")
                body = parse_email_from_raw(raw) if raw else ""

                print("✉️ From:", sender)
                print("➡️ To:", data.get("to"))
                print("📨 Subject:", data.get("subject"))
                print(f"--- Body preview ---\n{body[:200]}\n--- END preview ---")

                if expected_sender and sender != expected_sender:
                    print(f"⚠️ Ignored email, sender mismatch ({sender})")
                else:
                    otp = extract_6_digit_code(body)
                    if otp:
                        if otp == last_seen_otp:
                            print(f"⚠️ Same OTP as before ({otp}), ignoring...")
                        else:
                            last_seen_otp = otp
                            save_state({"last_seen_otp": otp})
                            print(f"✅ New OTP extracted: {otp}")
                            return otp
                    else:
                        print("⚠️ OTP not found in email")
        except Exception as e:
            print("⚠️ Request failed:", e)

        time.sleep(poll_interval)

    print("❌ Timeout waiting for OTP")
    return None
