#!/usr/bin/env python3
import uiautomator2 as u2
import time, sys, urllib.parse
import re, subprocess, json, threading
import gc


from binding import binding, ini_set_password, unbind
from get_jwt import SPAWN_TIMEOUT, main as jw
from mailisa import EMAIL_DOMAIN

APP_PACKAGE = "com.limoolive.stream"


def app_resource_id(name):
    return f"{APP_PACKAGE}:id/{name}"


def adb_input(d, text):
    esc = urllib.parse.quote(text, safe="")
    d.shell(f'input text "{esc}"')


def enter_text_into_edit(
    d, cls="android.widget.EditText", pkg=None, text="", timeout=5
):
    """Try set_text(), fallback to click+send_keys(), then adb_input()."""
    if pkg:
        sel = d(className=cls, packageName=pkg)
    else:
        sel = d(className=cls)

    if sel.exists(timeout=timeout):
        try:
            sel.set_text(text)
            return True
        except Exception:
            try:
                sel.click()
                time.sleep(0.2)
                # send_keys may not exist in some environments but try
                if hasattr(d, "send_keys"):
                    d.send_keys(text)
                    return True
            except Exception:
                pass
    # fallback to adb input
    adb_input(d, text)
    return True


def click_next(d, text_label="SELANJUTNYA", coord=(850, 1345), timeout=2):
    if d(text=text_label).exists(timeout=timeout):
        try:
            d(text=text_label).click()
            return True
        except Exception:
            pass
    # coordinate fallback (midpoint from your dump)
    try:
        d.click(coord[0], coord[1])
        return True
    except Exception:
        return False


def add_google_account(d, email, password, timeout=30):
    d.shell("am start -a android.settings.ADD_ACCOUNT_SETTINGS")
    time.sleep(1.2)

    # tap Google tile
    if d(text="Google").exists(timeout=timeout):
        d(text="Google").click()
    elif d(textContains="Google").exists(timeout=timeout):
        d(textContains="Google").click()
    # time.sleep(5)

    # enter email
    if d(resourceIdMatches=".*identifierId.*").exists(timeout=timeout):
        try:
            d(resourceIdMatches=".*identifierId.*").set_text(email)
        except Exception:
            enter_text_into_edit(d, text=email)
    else:
        enter_text_into_edit(d, text=email)

    time.sleep(1)
    click_next(d,"BERIKUTNYA")  # click SELANJUTNYA after email
    time.sleep(5)
    # click_next(d)  # click SELANJUTNYA after email


    # --- robust password entry ---
    # prefer EditText inside com.google.android.gms, but handle WebView/IME cases
    field = d(className="android.widget.EditText", packageName="com.google.android.gms")
    if not field.exists(timeout=15):
        # fallback to any EditText
        field = d(className="android.widget.EditText")

    if field.exists(timeout=2):
        try:
            # click to focus first (important for WebView)
            field.click()
            time.sleep(1)
        except Exception:
            pass

        # try set_text first
        try:
            field.set_text(password)
        except Exception:
            # fallback to shell input (percent-escaped)
            adb_input(d, password)

        # small pause to let IME settle and register text
        # print(d.dump_hierarchy())
        time.sleep(1)
    else:
        # nothing found: try adb input (best-effort)
        adb_input(d, password)
        time.sleep(1)

    # click Next on password screen
    # print(d.dump_hierarchy())
    click_next(d, text_label="BERIKUTNYA")
    time.sleep(1)

    drained = drain_consents(d)
    print("consent clicks:", drained)


def drain_consents(d, max_iters=8, delay=0.6):
    """
    Handle the known Google first-sign-in disclosure and sharing screens.
    Scroll the managed-account disclosure before looking for its continue button.
    Returns the number of actions performed.
    """
    consent_buttons = [
        {"text": "Saya mengerti"},
        {"text": "SAYA MENGERTI"},
        {"resourceId": "com.google.android.gms:id/signinconsentNext"},
        {"resourceId": "com.google.android.gms:id/agree_and_share_button"},
        {"text": "Saya setuju"},
        {"text": "Setuju dan bagikan"},
    ]

    actions = 0
    scrolls = 0
    idle_since = time.monotonic()
    for _ in range(max_iters):
        consent_button = None
        for selector in consent_buttons:
            candidate = d(**selector)
            if candidate.exists(timeout=0.2):
                consent_button = candidate
                break

        if consent_button is not None:
            if selector.get("text", "").casefold() == "saya mengerti":
                _, height = d.window_size()
                bounds = consent_button.info["bounds"]
                # Google reports this button above its actual rendered position.
                x = (bounds["left"] + bounds["right"]) // 2
                y = round(height * 0.888)
                d.shell(f"input tap {x} {y}")
            else:
                consent_button.click()
            actions += 1
            deadline = time.monotonic() + 15
            while consent_button.exists(timeout=0.2):
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Google consent button remained visible after it was "
                        "clicked; refusing to click it repeatedly"
                    )
                time.sleep(delay)
            idle_since = time.monotonic()
            continue

        managed_account_disclosure = d(textContains="Google Workspace").exists(
            timeout=0.2
        )
        if managed_account_disclosure and scrolls < 4:
            scroll_arrow = d(
                text="Scroll ke bawah",
                packageName="com.google.android.gms",
            )
            if scroll_arrow.exists(timeout=0.2):
                scroll_arrow.click()
            else:
                d.swipe(540, 1800, 540, 500, 0.3)
            actions += 1
            scrolls += 1
            time.sleep(delay)
            idle_since = time.monotonic()
            continue

        if not managed_account_disclosure:
            if (
                d.app_current().get("package") == "com.google.android.gms"
                and time.monotonic() - idle_since < 15
            ):
                time.sleep(delay)
                continue
            break
        raise RuntimeError(
            "Google Workspace disclosure is still visible, but its continue "
            "button did not appear after scrolling"
        )
    else:
        if any(d(**selector).exists(timeout=0.2) for selector in consent_buttons) or d(
            textContains="Google Workspace"
        ).exists(timeout=0.2):
            raise RuntimeError(
                "Google consent flow exceeded its action limit before completing"
            )
    return actions


def remove_account(d, email, timeout=30):
    d.shell("am start -a android.settings.SYNC_SETTINGS")
    time.sleep(2)

    if d(text=email).exists(timeout=timeout):
        d(text=email).click()
        time.sleep(0.5)
        if d(text="Hapus akun").exists(timeout=3):
            d(text="Hapus akun").click()

            if d(resourceId="android:id/button1").exists(timeout=2):
                d(resourceId="android:id/button1").click()
            elif d(text="Hapus akun").exists(timeout=2):
                d(text="Hapus akun").click()

    else:
        print("⚠️ Account not found in Accounts list. Adjust selector.")

def make_sure_account_is_there(d, email, timeout=0):
    d.shell("am start -a android.settings.SYNC_SETTINGS")
    time.sleep(1)
    if d(text=email).exists(timeout=timeout):
        return True

    else:
        print(f"⚠️ {email} isn't found in Accounts list. Adjust selector.")
        return False

def login_with_google_in_tamil(d, timeout=25):
    """
    Wait for the Tamil login screen and click its Google login button.
    """
    if d.app_wait(APP_PACKAGE, timeout=timeout):
        print("✅ Tamil app is foreground")


        # wait until the Google login button is visible
        google_button = d(resourceId=app_resource_id("btLoginGoogle"))
        if google_button.exists(timeout=timeout):
            google_button.click()
            print("👉 Clicked Google login button")
            return True
        else:
            print("⚠️ Google login button not found within timeout")
            return False
    else:
        print("⚠️ Tamil app is not in foreground")
        return False


def debug_after_google_click(d, dump_file="tamil_google_consent.xml"):
    """
    After clicking Google login, dump the current UI for debugging.
    Pauses execution so you can inspect before continuing.
    """
    # time.sleep(2.0)  # short wait for consent dialog to appear
    # xml = d.dump_hierarchy()
    # with open(dump_file, "w", encoding="utf-8") as f:
    #     f.write(xml)
    print(f"📄 Dumped Google consent UI to {dump_file}")
    # input("👉 Inspect the XML, then press Enter to continue...")


def accept_google_consent_in_tamil(d, timeout=10):
    """
    Handle the consent screen after clicking Google login.
    Clicks the 'Setuju dan lanjutkan' button.
    """
    # wait for the consent dialog to appear
    consent_button = d(resourceId=app_resource_id("bt_sure"))
    if consent_button.exists(timeout=timeout):
        consent_button.click()
        print("👉 Clicked 'Setuju dan lanjutkan'")
        return True
    else:
        print("⚠️ Consent button not found within timeout")
        return False


def pick_google_account(d, email, timeout=30):
    """
    On the Google account picker screen, select the given email.
    """
    print(f"🔍 Waiting for account picker to show {email}...")
    if d(text=email).exists(timeout=timeout):
        d(text=email).click()
        print(f"👉 Selected account: {email}")
        # debug_after_google_click(d)
        return True
    else:
        print(f"⚠️ Account {email} not found within timeout")
        return False


def debug_dump(d, filename="debug_ui.xml", msg="Paused for debugging"):
    xml = d.dump_hierarchy()
    with open(filename, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"📄 Dumped UI to {filename}")
    input(f"👉 {msg}. Press Enter to continue...")


def open_tamil(timeout: int = 30):
    # Step 1: stop app if already running
    try:
        d.app_stop(APP_PACKAGE)
        print("🛑 Stopped any running instance of the Tamil app")
    except Exception as e:
        print(f"⚠️ Could not stop the Tamil app: {e}")

    # Step 3: Launch the target app
    d.shell(f"monkey -p {APP_PACKAGE} -c android.intent.category.LAUNCHER 1")

    # Step 4: Wait for splash screen to finish
    if d.app_wait(APP_PACKAGE, timeout=timeout):
        print("✅ Tamil app is foreground; waiting for its login screen...")

        auth_result = {}
        auth_ready = threading.Event()

        def fetch_auth_result():
            try:
                auth_result["result"] = jw(d_serial)
            except Exception as exc:
                auth_result["error"] = exc
            finally:
                auth_ready.set()

        threading.Thread(target=fetch_auth_result, daemon=True).start()
        time.sleep(2)
        if login_with_google_in_tamil(d, timeout=timeout):
            accept_google_consent_in_tamil(d, timeout=timeout)
            if not pick_google_account(d, EMAIL, timeout=timeout):
                print(f"❌ Google account picker did not offer {EMAIL}")
                return {}
            consent_actions = drain_consents(d)
            print("Google consent actions:", consent_actions)
        else:
            return {}

        if not auth_ready.wait(timeout=SPAWN_TIMEOUT + 10):
            print("⚠️ Timed out waiting for Tamil Google-auth response")
            return {}
        if "error" in auth_result:
            print(f"⚠️ Failed to capture Tamil auth response: {auth_result['error']}")
            return {}
        return auth_result.get("result", {})

    else:
        print("⚠️ Tamil app did not come to foreground")
        return {}


def register_tamil_account(auth_tokens, email_domain):
    if not isinstance(auth_tokens, dict):
        print("❌ Tamil auth did not return registration tokens")
        return False

    jwt = auth_tokens.get("jwt")
    ws_token = auth_tokens.get("ws_token")
    user_id = auth_tokens.get("user_id")
    if not jwt or not ws_token or not user_id:
        print("❌ Tamil auth response is missing a required token or user ID")
        return False

    binding_email = f"{user_id}@{email_domain}"
    if not binding(binding_email, jwt, otp_code=""):
        print(f"❌ Could not bind custom email {binding_email}")
        return False

    if not ini_set_password(jwt):
        print(f"❌ Could not set password for Tamil user {user_id}")
        return False

    if not unbind(binding_email, jwt, otp=""):
        print(f"❌ Could not unlink Google from Tamil user {user_id}")
        return False

    print(
        f"✅ Tamil account {user_id} registered with "
        f"{binding_email}; Google link removed"
    )
    return True


def clear_app_data(d, package=APP_PACKAGE):
    """
    Force-stop the app and clear all its data (cache + storage).
    Equivalent to 'Clear storage' in system settings.
    ⚠️ This logs you out and wipes all local data for the app.
    """
    try:
        # stop if running
        d.app_stop(package)
        # clear all data
        d.shell(f"pm clear {package}")
        print(f"🧹 Cleared data for {package}")
        return True
    except Exception as e:
        print(f"⚠️ Failed to clear {package}: {e}")
        return False


def open_profile_in_tamil(d, timeout=8, dump_file="profile_debug.xml"):
    """
    Navigate to the Profile screen in the Tamil app.
    Uses bottom navigation bar (rl_bottom_nav), last tab (index 4).
    """
    bottom = d(resourceId=app_resource_id("rl_bottom_nav"))
    if bottom.exists(timeout=timeout):
        items = bottom.child(className="android.widget.RelativeLayout")
        if items and len(items) >= 5:
            items[4].click()
            print("👉 Clicked Profile tab (bottom nav index 4)")
            return True

    # fallback: try coordinate click on bottom-right corner
    try:
        d.click(950, 2100)  # adjust for your screen resolution
        print("👉 Clicked Profile tab by coordinates (fallback)")
        return True
    except Exception:
        print("⚠️ Could not click Profile tab, dumping UI...")

        return False


def dismiss_first_login_popup(d, timeout=5):
    """
    Detect and dismiss the first-login popup/banner if present.
    """
    close_button = d(resourceId=app_resource_id("iv_close"))
    if close_button.exists(timeout=timeout):
        close_button.click()
        print("🛑 Dismissed first-login popup (iv_close)")
        return True
    print("ℹ️ No first-login popup detected")
    return False


def open_account_security(d, timeout=5, dump_file="account_security_debug.xml"):
    """
    From the Settings screen, scroll and try to open Account & Security.
    """
    # Try visible first
    account_safe = d(resourceId=app_resource_id("rl_account_safe"))
    if account_safe.exists(timeout=timeout):
        account_safe.click()
        print("🔐 Opened Account & Security settings")
        return True

    # Scroll to reveal hidden items
    try:
        for _ in range(2):
            print("swiping..")
            d.swipe(500, 1800, 500, 800, 0.3)
            time.sleep(1)

        print("📜 Scrolled Settings page to bottom")
    except Exception:
        print("⚠️ Could not scroll Settings page")

    if d(text="Pengaturan").exists(timeout=5):
        d(text="Pengaturan").click()
        print("⚙️ Opened Settings")
    else:
        print("⚠️ Settings button not found, dump UI again.")

    account_safe = d(resourceId=app_resource_id("rl_account_safe"))
    if account_safe.exists(timeout=5):
        account_safe.click()
        print("🔐 Opened Account Security")

        return True
    else:
        print("⚠️ Keamanan akun not found, dumping UI again...")

    xml = d.dump_hierarchy()
    with open(dump_file, "w", encoding="utf-8") as f:
        f.write(xml)
    input(f"📄 Dumped to {dump_file}. Inspect and press Enter to continue...")

    return False


def go_to_settings_from_profile(d, dump_file="profile_section.xml"):
    """
    On Profile screen, try to click the Settings gear at bottom.
    """
    # dump before clicking
    xml = d.dump_hierarchy()
    with open(dump_file, "w", encoding="utf-8") as f:
        f.write(xml)
    input(
        "📄 Dumped Profile screen before clicking Settings. Inspect and press Enter..."
    )

    # try by coordinates (adjust based on your dump)
    try:
        d.click(950, 2100)  # example: bottom-right gear
        print("⚙️ Clicked Settings by coordinates")
    except Exception:
        print("⚠️ Coordinate click failed")

    # dump after click
    xml = d.dump_hierarchy()
    with open("after_click_settings.xml", "w", encoding="utf-8") as f:
        f.write(xml)
    input("📄 Dumped after clicking Settings. Inspect and press Enter...")


def open_account_safe_via_am(
    d, timeout=8, dump_file="account_safe_after_direct_start.xml"
):
    """
    1) Read the user id from profile UI (tv_user_id)
    2) Launch AccountSafeActivity via am start
    3) Dump the resulting UI and pause for inspection
    Falls back to clicking the Account Security entry if am start fails.
    """
    # 1) get user id
    user_id = None
    try:
        user_id_view = d(resourceId=app_resource_id("tv_user_id"))
        if user_id_view.exists(timeout=timeout):
            raw = user_id_view.get_text()
            # normalize "ID 19122657" => "19122657"
            m = re.search(r"\d+", raw or "")
            user_id = m.group(0) if m else raw
            print("🆔 User ID:", user_id)
        else:
            print("⚠️ tv_user_id not found on profile (continuing anyway)")
    except Exception as e:
        print("⚠️ Error reading user id:", e)

    # 2) Try direct activity start via am
    comp = f"{APP_PACKAGE}/{APP_PACKAGE}.ui.activity.mine.AccountSafeActivity"
    print("➡️ Attempting to start AccountSafeActivity via am start -n", comp)
    try:
        out = d.shell(f"am start -n {comp}")
        # d.shell returns an object-like string or stdout; be permissive
        print("adb shell output:", out)
        time.sleep(1.2)
    except Exception as e:
        print("⚠️ am start failed:", e)

    # 3) wait a bit for UI to settle, then dump UI
    time.sleep(1.0)
    xml = d.dump_hierarchy()
    with open(dump_file, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"📄 Dumped UI after direct start to {dump_file}")

    # quick check: verify we see an AccountSafe indicator
    if d(resourceId=app_resource_id("rl_account_safe")).exists(timeout=3) or d(
        textContains="Keamanan"
    ).exists(timeout=3):
        print("🔐 AccountSecurity screen detected after direct start")
        input("Inspect dump and press Enter to continue...")
        return True

    # 4) fallback: try clicking the Account & Security entry in Settings (if present)
    print("⚠️ AccountSecurity not detected after direct start — trying click fallback")
    account_safe = d(resourceId=app_resource_id("rl_account_safe"))
    if account_safe.exists(timeout=3):
        account_safe.click()
        time.sleep(1.0)
        xml2 = d.dump_hierarchy()
        with open(
            dump_file.replace(".xml", "_fallback.xml"), "w", encoding="utf-8"
        ) as f:
            f.write(xml2)
        print(
            "📄 Dumped UI after fallback click to",
            dump_file.replace(".xml", "_fallback.xml"),
        )
        input("Inspect fallback dump and press Enter to continue...")
        return True

    # last-resort: locate text node and click by text or approximate coords
    if d(textContains="Keamanan").exists(timeout=2):
        d(textContains="Keamanan").click()
        time.sleep(1.0)
        xml3 = d.dump_hierarchy()
        with open(
            dump_file.replace(".xml", "_fallback2.xml"), "w", encoding="utf-8"
        ) as f:
            f.write(xml3)
        print(
            "📄 Dumped UI after text click to",
            dump_file.replace(".xml", "_fallback2.xml"),
        )
        input("Inspect fallback2 dump and press Enter to continue...")
        return True

    print(
        "❌ Unable to reach AccountSecurity screen automatically. Inspect dumps and we can adjust."
    )
    input("Press Enter to continue...")
    return False


def run_request_bind(email, token):
    cmd = ["python", "api_bind.py", "request_bind", "--email", email]
    if token:
        cmd += ["--token", token]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print("STDOUT:", r.stdout)
    print("STDERR:", r.stderr)
    if r.returncode != 0:
        raise RuntimeError("request_bind failed")
    return json.loads(r.stdout)


def run_confirm_bind(ticket, email, otp, token):
    cmd = [
        "python",
        "api_bind.py",
        "confirm_bind",
        "--ticket",
        ticket,
        "--email",
        email,
        "--otp",
        otp,
    ]
    if token:
        cmd += ["--token", token]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("confirm_bind failed: " + r.stderr)
    return json.loads(r.stdout)


if __name__ == "__main__":

    d_serial = "266c3127"
    # d_serial = "27959bfa7cf4"
    TIMEOUT = 60
    MAX_TAMIL_ACCOUNTS_PER_GOOGLE = 5
    d = u2.connect(serial=d_serial)  # auto-detect USB
    d.screen_on()

    create_tamil_account = 1
    login_google_account = 1
    # Define a maximum number of retries to prevent infinite loops
    MAX_VERIFICATION_RETRIES = 6
    sf7=30
    for mail_num_idx in range(56):
        

        
        EMAIL = f"duj{sf7+mail_num_idx}@gosmail.xyz"
        PASSWORD = "qwertyui"

        # --- Start of the loop to ensure the account is present ---
        account_is_present = False
        retry_count = 0


        while not account_is_present and retry_count < MAX_VERIFICATION_RETRIES:
            print(f"Attempting to ensure account {EMAIL} is present (Retry {retry_count + 1}/{MAX_VERIFICATION_RETRIES})...")

            # Call add_account if login_google_account is true. This acts as your "re-insert" mechanism.
            account_is_present = make_sure_account_is_there(d, EMAIL)

            # Check if the account is confirmed to be there

            if not account_is_present:
                print(f"Account {EMAIL} not confirmed. Retrying...")
                retry_count += 1

            else:
                print(f"Account {EMAIL} successfully confirmed.")


                break # Exit the inner while loop, account is now confirmed

            if login_google_account:
                add_google_account(d, EMAIL, PASSWORD, TIMEOUT)
                # time.sleep(5) # Give some time for the account addition/login to process
        
        # If after max retries the account is still not present, skip this email
        if not account_is_present:
            print(f"Failed to ensure account {EMAIL} is present after {MAX_VERIFICATION_RETRIES} attempts. Skipping this email and moving to the next.")

            with open("skipped.txt", "a") as f:
                f.write(f"{EMAIL}\n")
            continue # Move to the next email in the outer `for` loop

        # --- End of the account verification loop ---

        # The rest of your original code, which now *assumes* the account is definitely there
        completed_registrations = 0
        try:
            if create_tamil_account:
                for account_index in range(MAX_TAMIL_ACCOUNTS_PER_GOOGLE):
                    print(
                        f"Registering Tamil account {account_index + 1}/"
                        f"{MAX_TAMIL_ACCOUNTS_PER_GOOGLE} for Google account {EMAIL}"
                    )
                    try:
                        auth_tokens = open_tamil(timeout=TIMEOUT)
                        if isinstance(auth_tokens, dict) and auth_tokens.get("jwt"):
                            if not clear_app_data(d):
                                raise RuntimeError(
                                    "Could not stop Tamil after capturing its JWT"
                                )
                        if not register_tamil_account(auth_tokens, EMAIL_DOMAIN):
                            with open("skipped.txt", "a") as skip:
                                skip.write(f"{EMAIL},{account_index + 1}\n")
                            pass
                        completed_registrations += 1
                    finally:
                        gc.collect()
        except Exception as e:
            print(f"Registration batch stopped for {EMAIL}: {e}")

        if (
            create_tamil_account
            and completed_registrations == MAX_TAMIL_ACCOUNTS_PER_GOOGLE
        ):
            d.set_orientation("n")
            remove_account(d, EMAIL)

        if (
            create_tamil_account
            and completed_registrations < MAX_TAMIL_ACCOUNTS_PER_GOOGLE
        ):
            print(
                f"Keeping Google account {EMAIL} on the device: only "
                f"{completed_registrations}/{MAX_TAMIL_ACCOUNTS_PER_GOOGLE} "
                "Tamil registrations succeeded. Stopping the batch."
            )
            break
        # adb shell pm clear com.google.android.gms
