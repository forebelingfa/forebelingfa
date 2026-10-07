#!/usr/bin/env python3
"""Batch bettor for `poor` token file.

Workflow:
- Read token lines from 'poor' (userid,jwt,token).
- Check balances via `get_user_info` and pick accounts with gold > 0.
- Process accounts in batches of `--batch-size` (default 10).
- For each account in a batch, join the WS with account token and place a bet for each item in ITEMS using the account's balance as amount.

By default runs in `--dry-run` mode (no actual websocket connections). Use `--run` to perform real bets.
"""
import argparse
import time
import logging
import ssl
import struct
import threading
from websocket import create_connection, ABNF
from api import get_user_info
import binascii
import re


# Minimal protobuf wire helpers from g.py inlined here
def read_varint(buf: bytes, off: int):
    shift = 0
    val = 0
    L = len(buf)
    while off < L:
        b = buf[off]
        off += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, off
        shift += 7
        if shift > 70:
            raise ValueError("varint too large")
    raise ValueError("truncated varint")


def read_fixed32(buf: bytes, off: int):
    return struct.unpack_from("<I", buf, off)[0], off + 4


def read_fixed64(buf: bytes, off: int):
    return struct.unpack_from("<Q", buf, off)[0], off + 8


def parse_protowire(payload: bytes):
    res = []
    off = 0
    L = len(payload)
    while off < L:
        try:
            key, off = read_varint(payload, off)
        except Exception:
            break
        field = key >> 3
        wire_type = key & 7
        if wire_type == 0:
            val, off = read_varint(payload, off)
            res.append((field, wire_type, val))
        elif wire_type == 1:
            val, off = read_fixed64(payload, off)
            res.append((field, wire_type, val))
        elif wire_type == 2:
            length, off = read_varint(payload, off)
            if off + length > L:
                val = payload[off:]
                off = L
            else:
                val = payload[off : off + length]
                off += length
            try:
                s = val.decode("utf-8")
                res.append((field, wire_type, ("str", s)))
            except Exception:
                res.append((field, wire_type, ("bytes", val)))
        elif wire_type == 5:
            val, off = read_fixed32(payload, off)
            res.append((field, wire_type, val))
        else:
            res.append((field, wire_type, None))
            break
    return res


def encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("Varint encoding expects non-negative integer values.")
    parts = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            parts.append(byte | 0x80)
        else:
            parts.append(byte)
            break
    return bytes(parts)


def build_join_frame(message_type: int, version: str, token: str, flags: int, anchor_id: int, user_id: int = None) -> bytes:
    payload = bytearray()
    vb = version.encode("utf-8")
    payload += b"\x0a" + bytes([len(vb)]) + vb
    tb = token.encode("utf-8")
    payload += b"\x12" + bytes([len(tb)]) + tb
    payload += b"\x18" + encode_varint(flags)
    payload += b"\x20" + encode_varint(anchor_id)
    if user_id is not None:
        payload += b"\x28" + encode_varint(user_id)
    header = struct.pack("<H", message_type)
    return header + bytes(payload)


def build_bet_frame(user_id: int, side: int, amount: int, odds: int) -> bytes:
    payload = bytearray()
    payload += b"\x08" + encode_varint(user_id)
    payload += b"\x10" + encode_varint(side)
    payload += b"\x18" + encode_varint(amount)
    payload += b"\x20" + encode_varint(odds)
    return struct.pack("<H", 1010) + bytes(payload)


def build_heartbeat_frame() -> bytes:
    return struct.pack("<H", 1013)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("poor_bet")

POOR_FILE = "poor"
WSS_URL = "wss://game.dazz2.com/ws/?port=9315"

pizza, salad = 9, 8
ITEM_ORDER = [7,6,5,4,3,2,1,0]
DEFAULT_ANCHOR = 10000000
FLAGS = 14
VERSION = "1.0"
MIN_BET = 1  # Minimum bet enforced by server (observed)
MAX_BET = 100  # cap the max bet amount per account by default


def load_file(path):
    accounts = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                parts = line.split(",", 2)
                if len(parts) == 3:
                    userid, jwt, token = parts
                elif len(parts) == 2:
                    userid, token = parts
                    jwt = ""
                else:
                    logger.warning("Skipping malformed line: %s", line)
                    continue
                accounts.append({"user_id": userid, "jwt": jwt, "token": token})
    except FileNotFoundError:
        logger.error("Token file not found: %s", path)
    return accounts


def collect_positive_accounts(accounts, limit=None, min_gold=1):
    """Return list of accounts with gold>=min_gold, preserving order.
    If limit provided, stop when collected that many.
    """
    result = []
    for a in accounts:
        try:
            info = get_user_info(a['user_id'], a['jwt'])
            gold = int(info.get('data', {}).get('gold', 0)) if isinstance(info, dict) else 0
        except Exception as e:
            logger.warning("Failed to query %s: %s", a['user_id'], e)
            gold = 0
        if gold >= min_gold:
            a['gold'] = gold
            result.append(a)
            logger.info("Account %s has gold=%s", a['user_id'], gold)
            if limit and len(result) >= limit:
                break
        else:
            logger.debug("Skipping %s: gold=%s < min_gold=%s", a['user_id'], gold, min_gold)
    return result


def place_bets_for_account(account, assigned_item, anchor_id=DEFAULT_ANCHOR, wss=WSS_URL, dry_run=True, wait_between_bets=0.1, start_event=None, **kwargs):
    # NOTE: This function may be called with extra kwargs inserted later (retries, retry_delay, wait_for_start, ack_mode)
    user_id = int(account['user_id'])
    token = account['token']
    amount = int(account.get('gold', 0))
    if amount <= 0:
        logger.info("Skipping %s: zero balance", user_id)
        return
    min_bet = kwargs.get('min_bet', MIN_BET)
    if amount < min_bet:
        logger.info("Skipping %s: balance %s below min_bet %s", user_id, amount, min_bet)
        return
    # Round down according to 'round_increment' CLI flag; if 0, do not round
    round_increment = kwargs.get('round_increment', 100)
    if round_increment and round_increment > 0:
        rounded = (amount // round_increment) * round_increment
    else:
        rounded = amount
    max_bet = kwargs.get('max_bet', MAX_BET)
    base_bet = min(rounded, max_bet)
    remaining = base_bet
    if remaining < MIN_BET:
        logger.info("Skipping %s: effective bet %s below MIN_BET %s after rounding", user_id, remaining, MIN_BET)
        return
    item_name = ITEM_ORDER_map(assigned_item)
    logger.info("Preparing bets for %s: balance=%s assigned=%s(%s) base_bet=%s (rounded=%s, max=%s)", user_id, amount, assigned_item, item_name, base_bet, rounded, max_bet)
    if dry_run:
        logger.info("[DRY] Would bet %s on %s (id=%s) and will not perform live bets", base_bet, item_name, assigned_item)
        return

    # live mode
    try:
        ws = create_connection(wss, sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=10)
        join = build_join_frame(1001, VERSION, token, FLAGS, anchor_id, user_id)
        if kwargs.get('debug'):
            logger.debug("Join frame hex: %s", binascii.hexlify(join))
        ws.send(join, opcode=ABNF.OPCODE_BINARY)
        logger.info("Sent join for user %s, waiting for betting window...", user_id)
        prev_balance = amount

        # Wait for 'start' status (msg_type 1003) if requested; otherwise, grab some initial state
        status_wait = kwargs.get('status_wait', 8.0)
        wait_for_start = kwargs.get('wait_for_start', False)
        deadline = time.time() + (status_wait if wait_for_start else 2.0)
        started = False
        ws.settimeout(1)
        # parse_protowire inlined above
        while time.time() < deadline:
            try:
                data = ws.recv()
            except Exception:
                continue
            if not isinstance(data, (bytes, bytearray)) or len(data) < 2:
                continue
            msg_type = struct.unpack_from("<H", data, 0)[0]
            payload = data[2:]
            parsed = parse_protowire(payload)
            logger.debug("Pre-bet WS msg_type=%s parsed=%s", msg_type, parsed)
            if msg_type == 1003:
                # find field 1 string status
                for field, _, val in parsed:
                    if field == 1 and isinstance(val, tuple) and val[0] == 'str':
                        logger.info("Round status: %s", val[1])
                        if val[1] == 'start':
                            started = True
                            logger.info("Betting window is open for user %s", user_id)
                            if start_event is not None and not start_event.is_set():
                                start_event.set()
                            break
            elif msg_type == 1002:
                # LoginACK includes Round info (field 3) - parse nested if present
                for field, _, val in parsed:
                    if field == 3 and isinstance(val, tuple) and val[0] == 'bytes':
                        inner = parse_protowire(val[1])
                        # logger.info("LoginACK Round info: %s", inner)
            if started:
                break

        if wait_for_start and not started:
            logger.info("Betting window not detected within wait; will wait for start before attempting bets")

        # Send a proper ChipInREQ (proto id 1004) with fields: 1=Gold,2=TeamID
        # We'll build the payload per attempt using 'remaining' and 'base_bet'
        # Send attempt with retries if necessary
        max_retries = kwargs.get('retries', 2)
        retry_delay = kwargs.get('retry_delay', 2.0)
        ack_mode = kwargs.get('ack_mode', 'strict')

        attempt = 0
        success = False
        while attempt <= max_retries and not success and remaining >= MIN_BET:
            attempt += 1

            # If requested, ensure betting window is open before sending
            if wait_for_start and not started:
                # Wait up to retry_delay seconds for a start signal before proceeding to next attempt
                logger.info("Waiting up to %ss for betting window before attempt %s", retry_delay, attempt)
                watch_deadline = time.time() + retry_delay
                ws.settimeout(1)
                detected_start = False
                while time.time() < watch_deadline:
                    try:
                        data = ws.recv()
                    except Exception:
                        continue
                    if not isinstance(data, (bytes, bytearray)) or len(data) < 2:
                        continue
                    msg_type = struct.unpack_from("<H", data, 0)[0]
                    payload = data[2:]
                    parsed = parse_protowire(payload)
                    if msg_type == 1003:
                        for field, _, val in parsed:
                            if field == 1 and isinstance(val, tuple) and val[0] == 'str' and val[1] == 'start':
                                detected_start = True
                                logger.info("Detected start window for user %s, proceeding to attempt %s", user_id, attempt)
                                # set shared event if present
                                if start_event is not None and not start_event.is_set():
                                    start_event.set()
                                break
                    if detected_start:
                        started = True
                        break
                if not detected_start:
                    # If a shared event exists, wait for it to be set by another participant
                    if start_event is not None and start_event.wait(timeout=retry_delay):
                        logger.info("Shared start_event detected; proceeding to attempt %s", attempt)
                        detected_start = True
                        started = True
                    else:
                        logger.info("No start detected for attempt %s; will retry later", attempt)
                    # loop to next attempt (which will wait again)
                    continue

            # determine attempt amount and build payload dynamically
            attempt_amount = min(remaining, base_bet)
            if attempt_amount < MIN_BET:
                logger.info("Remaining %s less than MIN_BET %s; stopping for user %s", attempt_amount, MIN_BET, user_id)
                break
            chipin_payload = bytearray()
            chipin_payload += b"\x08" + encode_varint(attempt_amount)
            chipin_payload += b"\x10" + encode_varint(assigned_item)
            frame = struct.pack("<H", 1004) + bytes(chipin_payload)
            if kwargs.get('debug'):
                logger.debug("ChipInREQ frame hex: %s", binascii.hexlify(frame))
            ws.send(frame, opcode=ABNF.OPCODE_BINARY)
            logger.info("Sent ChipInREQ for user %s (attempt %s/%s): team=%s amount=%s remaining=%s", user_id, attempt, max_retries+1, assigned_item, attempt_amount, remaining)

            # Wait briefly for server responses and parse them for confirmation
            confirm_wait = 6.0
            end_time = time.time() + confirm_wait
            ws.settimeout(1)
            accepted = False
            ack_info = {}
            while time.time() < end_time and not accepted:
                try:
                    data = ws.recv()
                    if not isinstance(data, (bytes, bytearray)):
                        logger.info("WS recv (non-bytes): %s", data)
                        continue
                    if len(data) < 2:
                        logger.info("WS recv short frame")
                        continue
                    msg_type = struct.unpack_from("<H", data, 0)[0]
                    payload = data[2:]
                    parsed = parse_protowire(payload)
                    logger.info("WS msg_type=%s parsed=%s", msg_type, parsed)

                    if msg_type == 1005:
                        if kwargs.get('debug'):
                            logger.debug("Raw 1005 hex: %s", binascii.hexlify(payload))
                        info = {}
                        for field, _, val in parsed:
                            if field == 1:
                                info['result'] = val
                            elif field == 2:
                                info['team'] = val
                            elif field == 3:
                                info['gold'] = val
                            elif field == 4:
                                info['balance'] = val
                            else:
                                info.setdefault('other', []).append((field, val))
                        ack_info = info
                        logger.info("ChipInACK received: %s", info)
                        # Acceptance heuristics using deduction and ack result
                        deduction = 0
                        if info.get('balance') is not None:
                            try:
                                newbal = int(info.get('balance'))
                                deduction = prev_balance - newbal
                            except Exception:
                                deduction = 0
                        if info.get('result') == 0 or deduction >= attempt_amount:
                            accepted = True
                        else:
                            # Try lenient heuristics if configured
                            if ack_mode == 'lenient' and (info.get('gold') == attempt_amount and info.get('team') == assigned_item):
                                accepted = True
                            else:
                                logger.info("ChipInACK indicates failure result=%s (deduction=%s)", info.get('result'), deduction)
                                accepted = False
                                break

                    elif msg_type == 1010:
                        pid = None
                        team = None
                        gold = None
                        for field, _, val in parsed:
                            if field == 1:
                                pid = val
                            elif field == 2:
                                team = val
                            elif field == 3:
                                gold = val
                        # interpret gold as integer when possible and compare against attempt_amount
                        g_val = None
                        try:
                            g_val = int(gold) if gold is not None else None
                        except Exception:
                            g_val = None
                        if pid == user_id and team == assigned_item and g_val == attempt_amount:
                            logger.info("Detected ChipInNotify for our bet: pid=%s team=%s gold=%s", pid, team, gold)
                            # assume a full deduction equal to attempt_amount for notify
                            try:
                                remaining -= attempt_amount
                                prev_balance -= attempt_amount
                                logger.info("Account %s deducted %s via notify, remaining=%s", user_id, attempt_amount, remaining)
                            except Exception:
                                pass
                            accepted = True
                except Exception:
                    # timeout or no data
                    pass

            if accepted:
                # attempt to determine deduction and update remaining
                try:
                    ded = 0
                    if ack_info.get('balance') is not None:
                        try:
                            newbal = int(ack_info.get('balance'))
                            ded = prev_balance - newbal
                        except Exception:
                            ded = 0
                    else:
                        # Re-query the account to measure deduction
                        try:
                            resp = get_user_info(str(user_id), account.get('jwt',''))
                            newbal = int(resp.get('data', {}).get('gold', 0)) if isinstance(resp, dict) else None
                            if newbal is not None:
                                ded = prev_balance - newbal
                        except Exception:
                            ded = 0
                    if ded > 0:
                        remaining -= ded
                        prev_balance = newbal
                        logger.info("Account %s deducted %s, remaining=%s", user_id, ded, remaining)
                    else:
                        logger.info("Accepted response for user %s but no deduction observed; remaining=%s", user_id, remaining)
                except Exception:
                    logger.exception("Error updating remaining for %s", user_id)
                # If we've spent all or nothing left over the minimum, we're done
                if remaining <= 0:
                    success = True
                    logger.info("Bet goals achieved for user %s (remaining <= 0)", user_id)
                    break
                # If we still have meaningful remaining, mark we will try again until retries exhausted
                if remaining < MIN_BET:
                    logger.info("Remaining %s < MIN_BET (%s), stopping for user %s", remaining, MIN_BET, user_id)
                    break
            else:
                if attempt <= max_retries:
                    logger.info("Bet not accepted (attempt %s). Retrying after %ss...", attempt, retry_delay)
                    time.sleep(retry_delay)

        # Re-query account balance to see if it changed
        try:
            info_after = get_user_info(str(user_id), account.get('jwt',''))
            gold_after = int(info_after.get('data', {}).get('gold', 0)) if isinstance(info_after, dict) else None
            logger.info("Balance after bet for %s: %s", user_id, gold_after)
            try:
                if gold_after is not None:
                    spent = amount - gold_after
                    logger.info("User %s: spent=%s remaining=%s (final)", user_id, spent, remaining)
                else:
                    spent = None
            except Exception:
                spent = None
        except Exception as e:
            logger.warning("Failed to re-query balance for %s: %s", user_id, e)
            gold_after = None
            spent = None
        except Exception as e:
            logger.warning("Failed to re-query balance for %s: %s", user_id, e)

        time.sleep(wait_between_bets)
        # Final summary for this account
        try:
            logger.info("FINAL: user=%s before=%s after=%s spent=%s remaining=%s success=%s", user_id, amount, gold_after, spent, remaining, success)
        except Exception:
            logger.info("FINAL: user=%s before=%s after=%s spent=%s remaining=%s success=%s", user_id, amount, gold_after if 'gold_after' in locals() else None, spent if 'spent' in locals() else None, remaining if 'remaining' in locals() else None, success if 'success' in locals() else False)
    except Exception as e:
        logger.exception("Error placing bets for %s: %s", user_id, e)
    finally:
        try:
            ws.close()
        except Exception:
            pass


def ITEM_ORDER_map(item_id):
    names = {9: 'Pizza',8:'Salad',7:'Daging',6:'Paha',5:'Sate',4:'Hotdog',3:'Wortel',2:'Sawi',1:'Jagung',0:'Tomato'}
    return names.get(item_id, str(item_id))


def process_batches_concurrent(accounts, batch_size=10, dry_run=True, delay_between_accounts=0.02, **kwargs):
    """Process accounts in batches concurrently: all accounts in a batch connect and wait for the same betting window.
    When one detects 'start' it signals others via a shared threading.Event.
    """
    idx = 0
    total = len(accounts)
    while idx < total:
        batch = accounts[idx: idx + batch_size]
        logger.info("Processing batch %s - %s (size=%s) concurrently", idx+1, idx+len(batch), len(batch))
        start_event = threading.Event()
        threads = []
        for i, acc in enumerate(batch):
            assigned_item = ITEM_ORDER[i % len(ITEM_ORDER)]
            th = threading.Thread(
                target=place_bets_for_account,
                args=(acc, assigned_item),
                kwargs={**kwargs, 'dry_run': dry_run, 'start_event': start_event}
            )
            th.daemon = True
            th.start()
            threads.append(th)
            time.sleep(delay_between_accounts)

        # Wait for all members to complete or timeout
        for t in threads:
            t.join()
        idx += batch_size


def process_all_batches(accounts, batch_size=10, dry_run=True, delay_between_accounts=0.5):
    idx = 0
    total = len(accounts)
    while idx < total:
        batch = accounts[idx: idx + batch_size]
        logger.info("Processing batch %s - %s (size=%s)", idx+1, idx+len(batch), len(batch))
        for i, acc in enumerate(batch):
            assigned_item = ITEM_ORDER[i % len(ITEM_ORDER)]
            place_bets_for_account(acc, assigned_item, dry_run=dry_run)
            time.sleep(delay_between_accounts)
        idx += batch_size


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', default=POOR_FILE)
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--run', action='store_true', help='Actually perform bets (live). Default is dry-run')
    parser.add_argument('--anchor', type=int, default=DEFAULT_ANCHOR)
    parser.add_argument('--limit', type=int, default=None, help='Limit number of positive accounts to collect before processing')
    parser.add_argument('--min-bet', type=int, default=MIN_BET, help='Minimum gold required to use an account')
    parser.add_argument('--round-increment', type=int, default=100, help='Round bets down to this increment (0 to disable rounding)')
    parser.add_argument('--max-bet', type=int, default=MAX_BET, help='Maximum bet to place per account')
    parser.add_argument('--retries', type=int, default=2, help='Number of retries on failure')
    parser.add_argument('--retry-delay', type=float, default=2.0, help='Delay between retries in seconds')
    parser.add_argument('--wait-for-start', action='store_true', help='Wait for betting "start" status before attempting bets')
    parser.add_argument('--ack-mode', choices=['strict', 'lenient'], default='strict', help='Acceptance mode for ACKs')
    parser.add_argument('--debug', action='store_true', help='Enable verbose debug logging (hex dumps)')
    parser.add_argument('--force', action='store_true', help='Force live bets even if debug is enabled')
    args = parser.parse_args()

    accounts = load_file(args.file)
    if not accounts:
        logger.error('No accounts loaded; exiting')
        raise SystemExit(1)

    positive = collect_positive_accounts(accounts, limit=args.limit, min_gold=args.min_bet)
    if not positive:
        logger.info('No accounts with balance >= %s found', args.min_bet)
        raise SystemExit(0)

    # pass retry and wait params through via kwargs closure
    def _process(accounts, batch_size, dry_run):
        idx = 0
        total = len(accounts)
        if not dry_run:
            # Live run: use concurrent batch processing so accounts in a batch act in the same window
            process_batches_concurrent(accounts, batch_size=batch_size, dry_run=dry_run, delay_between_accounts=0.02, retries=args.retries, retry_delay=args.retry_delay, wait_for_start=args.wait_for_start, ack_mode=args.ack_mode, max_bet=args.max_bet, min_bet=args.min_bet, round_increment=args.round_increment, debug=args.debug)
            return
        while idx < total:
            batch = accounts[idx: idx + batch_size]
            logger.info("Processing batch %s - %s (size=%s)", idx+1, idx+len(batch), len(batch))
            for i, acc in enumerate(batch):
                assigned_item = ITEM_ORDER[i % len(ITEM_ORDER)]
                place_bets_for_account(acc, assigned_item, dry_run=dry_run, retries=args.retries, retry_delay=args.retry_delay, wait_for_start=args.wait_for_start, ack_mode=args.ack_mode, max_bet=args.max_bet, min_bet=args.min_bet, round_increment=args.round_increment, debug=args.debug)
                time.sleep(0.5)
            idx += batch_size

    # Safe mode: if debug is enabled but --force wasn't provided, keep dry-run mode
    run_flag = args.run
    if args.debug and args.run and not args.force:
        logger.warning("Debugging without --force; will remain dry-run to avoid spending coins")
        run_flag = False
    _process(positive, batch_size=args.batch_size, dry_run=not run_flag)
