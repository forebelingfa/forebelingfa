#!/usr/bin/env python3
import asyncio
import json
import time
import hashlib
import logging
import os
import sys
import random
from datetime import datetime
from collections import defaultdict

import websockets
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.application import run_in_terminal
from rich.console import Console

# ───────────────────────── CONFIG ─────────────────────────
WS_URL = "ws://13.213.254.163:9001"
SALT = "tyxaefcverr4662xse#bfh790jnfe@ss"

NAME = ""
# ROOM_ID = int(input("ROOM ID: "))

# ───────────────────────── GLOBALS ─────────────────────────
console = Console(file=sys.__stdout__, force_terminal=True, markup=True)
stop_event = asyncio.Event()
user_cache = defaultdict(lambda: {"nick": "?", "gold": 0, "level": 0, "color": "white"})

USER_COLORS = [
    "cyan", "magenta", "yellow", "green", "blue",
    "bright_cyan", "bright_magenta", "bright_yellow"
]

# ───────────────────────── HELPERS ─────────────────────────
def timestamp():
    return datetime.now().strftime("%H:%M")

def md5_result(token, t):
    return hashlib.md5(f"tyxaefcverr4662xse#bfh790jnfe@ss{t}{token}".encode()).hexdigest()

def stable_color(uid):
    random.seed(uid)
    return random.choice(USER_COLORS)

def update_user(uid, nick, gold, level):
    """Update cached user info and color consistency."""
    u = user_cache[uid]
    if u["nick"] == "?":
        u["color"] = stable_color(uid)
    if nick:
        u["nick"] = nick
    if gold is not None:
        u["gold"] = gold
    if level is not None:
        u["level"] = level

def pretty_print(uid, msg, session=None):
    """Print chat line without stealing input focus."""
    u = user_cache[uid]
    name = f"[{u['color']}]{u['nick']}[/{u['color']}] [dim](Lv.{u['level']} | 💰{u['gold']})[/dim]"
    line = f"[green]{timestamp()}[/green] {name}: {msg}"

    # Ensures terminal input remains active
    if session:
        run_in_terminal(lambda: console.print(line))
    else:
        console.print(line)

    logging.info(f"{timestamp()} {u['nick']} (Lv.{u['level']} | 💰{u['gold']}): {msg}")

# ───────────────────────── CHAT HANDLER ─────────────────────────
async def handle_messages(ws, session):
    async for message in ws:
        # Log raw incoming WebSocket messages
        logging.info(f"RAW_RECV: {message}")

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            continue

        op = data.get("op")
        body = data.get("body", {})

        # Update user info (various ops)
        if op in (1001, 1011, 1064, 1085, 1066):
            uid = body.get("UserId")
            if uid:
                update_user(
                    uid, body.get("NickName") or body.get("UserName"), body.get("Gold"), body.get("Level") or body.get("GameLevel") or body.get("ConsumeLevel"),
                )
            continue

        if op == 1002:
            uid = body.get("SUserId")
            msg = body.get("Content", "")
            nick = body.get("SNickName")
            gold = body.get("Gold", 0) or body.get("SGold", 0)
            lvl = body.get("ConsumeLevel", 0) or body.get("SLevel", 0)

            # skip echo
            if uid == USER_ID:
                continue

            update_user(uid, nick, gold, lvl)

            # Check if message is directed to us
            is_mention = body.get("DUserID") == USER_ID

            if is_mention:
                run_in_terminal(lambda: console.print(
                    f"[green]{timestamp()}[/green] [bold red]@You[/bold red] from "
                    f"[{user_cache[uid]['color']}]{nick}[/{user_cache[uid]['color']}] "
                    f"[dim](Lv.{lvl} | 💰{gold})[/dim]: {msg}"
                ))
                # optional: play alert sound
                print('\a', end='')  
                logging.info(f"MENTION from {nick} ({lvl} | {gold}): {msg}")
            else:
                pretty_print(uid, msg, session)

# ───────────────────────── INPUT LOOP ─────────────────────────
async def send_loop(ws, session):
    with patch_stdout(raw=True):
        while not stop_event.is_set():
            try:
                text = await session.prompt_async(HTML("<b><ansiblue>You:</ansiblue></b> "))
            except (EOFError, KeyboardInterrupt):
                stop_event.set()
                break

            text = text.strip()
            if not text:
                continue

            if text.lower() in ("/quit", "q"):
                stop_event.set()
                break

            if text.lower() in ("like", "w"):
                for _ in range(7):
                    await ws.send(json.dumps({"body":{},"op":1017,"ver":1}))
                    await asyncio.sleep(0.1)
                continue

            payload = {
                "ver": 1,
                "op": 1002,
                "body": {
                    "ChatType": 0,
                    "Content": text,
                    "DUserID": 0,
                    "SUserId": USER_ID,
                    "SNickName": NAME,
                    "Gold": 9999999,
                    "ConsumeLevel": 91,
                },
            }

            json_payload = json.dumps(payload)

            try:
                # Log outgoing
                logging.info(f"RAW_SEND: {json_payload}")
                await ws.send(json_payload)

                console.print(f"[green]{timestamp()}[/green] [bold blue]You:[/bold blue] {text}")
                logging.info(f"{timestamp()} You: {text}")
            except Exception as e:
                console.print(f"[red]Send failed:[/red] {e}")
                logging.error(f"Send failed: {e}")

# ───────────────────────── MAIN ─────────────────────────

def get_signed_payload(user_id, room_id, token):
    salt = "tyxaefcverr4662xse#bfh790jnfe@ss"
    
    # We will use the 'future' format seen in your Frida log 
    # but generate it based on current time to stay 'safe'
    # Current time (seconds) + the offset you observed
    # 1767729678 (Frida) - 1739274000 (Current) = ~28455678
    magic_offset = 28455678 
    fake_time = int(time.time()) + magic_offset
    
    # MD5(Salt + StringTime)
    time_str = str(fake_time)
    sign_data = salt + time_str
    md5_str = hashlib.md5(sign_data.encode()).hexdigest()

    return {
        "ver": 1,
        "op": 1001,
        "body": {
            "DeviceType": 1,
            "EnterType": 0,
            "FuncLevel": 1280,
            "IsSmallDialog": 0,
            "Lang": "id",
            "Md5Str": md5_str, # Dynamic MD5
            "RoomId": int(room_id),
            "TimeMill": fake_time, # Dynamic Time
            "Token": token,
            "UserId": int(user_id),
            "Version": "1.9.9",
            "package_type": "haigou-Android",
            "Visitor": 0,
            "Tourist": 0
        }
    }

def get_199_payload(user_id, room_id, token):
    # This offset is required to reach the Jan 2026 range seen in your logs
    # 1767729678 - 1739281500 = ~28,448,178
    magic_offset = 28448178 
    
    # Generate the 'Future' TimeMill
    time_mill = int(time.time()) + magic_offset
    # t_str = str(time_mill)
    
    # NEW FORMULA: Salt + TimeMill + Token
    # Order discovered in dazz_src_base_199/smali_classes2/app/dazz/live/utils/room_float/j.smali
    sign_data = f"{SALT}{time_mill}{token}"
    md5_str = hashlib.md5(sign_data.encode()).hexdigest()

    return {
        "body": {
            "DeviceType": 1,
            "EnterType": 0,
            "FuncLevel": 1280,
            "IsSmallDialog": 0,
            "Lang": "id",
            "Md5Str": md5_str,
            "RoomId": int(room_id),
            "TimeMill": time_mill,
            "Token": token,
            "UserId": int(user_id),
            "Version": "1.9.9",
            "package_type": "haigou-Android"
        },
        "op": 1001,
        "ver": 1
    }

async def main():
    global USER_ID
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(filename=log_file, level=logging.INFO, format="%(message)s")

    t = int(time.time() * 1000)

    USER_ID,ROOM_ID,TOKEN=16215415, 42449, "98d0189ebe7a0297"

    # payload = {"body":{"DeviceType":1,"EnterType":0,"FuncLevel":1280,"IsSmallDialog":0,"Lang":"id","Md5Str":"4c84afa5243a3fef8f89c3be11c4ff17","RoomId":86372,"TimeMill":1767729679,"Token":TOKEN,"Tourist":0,"UserId":USER_ID,"Version":"1.9.9","Visitor":0,"package_type":"haigou-Android"},"op":1001,"ver":1}

    payload = get_199_payload(USER_ID,ROOM_ID,TOKEN)

    session = PromptSession()

    while not stop_event.is_set():
        try:
            console.print(f"[green]Connecting as {NAME}...[/green]")
            async with websockets.connect(WS_URL, ping_interval=None) as ws:
                await ws.send(json.dumps(payload))
                console.print(f"[dim]{timestamp()}[/dim] [green]Connected. Type /quit to exit.[/green]")
                logging.info(f"{timestamp()} Connected as {NAME}")

                recv_task = asyncio.create_task(handle_messages(ws, session))
                send_task = asyncio.create_task(send_loop(ws, session))

                await asyncio.wait([recv_task, send_task], return_when=asyncio.FIRST_COMPLETED)
                stop_event.set()

        except Exception as e:
            console.print(f"[red]Connection error:[/red] {e}")
            logging.error(f"Connection error: {e}")
            await asyncio.sleep(3)

    console.print("[yellow]Disconnected.[/yellow]")
    logging.info(f"{timestamp()} Disconnected")

# ───────────────────────── ENTRY ─────────────────────────
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

    # t,token=int(time.time()),"83dd3f16c02d8b3a"
    # print(md5_result(token,t))