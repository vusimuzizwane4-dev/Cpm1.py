import asyncio
import contextvars
import aiohttp
import json
import re
import sqlite3
import time
import struct
import hashlib
import traceback
import logging
import os
import os
from flask import Flask
import threading

# === FLASK HEALTH CHECK ZA RENDER ===
app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)

# Pokreni Flask u pozadinskoj niti da Render vidi otvoren port
threading.Thread(target=run_web, daemon=True).start()
# =====================================


from copy import deepcopy
from html import escape
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False

import zlib
import base64
import random as _rnd_cars
import requests as _req_cars

from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    Message, BotCommand, BotCommandScopeChat, FSInputFile,
)

# ═══════════════════════════════════════════
#  ⚙️  CONFIG
# ═══════════════════════════════════════════

# Credentials should be supplied through environment variables.
# The old inline secrets were exposed in the uploaded source and should be rotated.
BOT_TOKEN = "8310159453:AAEvT8crCgowDaClY823zC5VfUJ3__JC1L4"
OWNER_ID  = 8848810644

RATE_LIMIT_ACTIONS = 10
RATE_LIMIT_SECONDS = 60
BULKADD_TIMEOUT_SECONDS = 180

FK       = "AIzaSyAe_aOVT1gSfmHKBrorFvX4fRwN5nODXVA"
LOAD_URL = "https://europe-west1-cp-multiplayer.cloudfunctions.net/GetPlayerRecords3"
SAVE_URL = "https://europe-west1-cp-multiplayer.cloudfunctions.net/SavePlayerRecordsPartially8"
RANK_URL = "https://us-central1-cp-multiplayer.cloudfunctions.net/SetUserRating5"

MAX_MONEY = 50_000_000
MAX_COIN  = 500_000

# ═══════════════════════════════════════════
#  📊 LOGGING
# ═══════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)s │ %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("CPM")

# ═══════════════════════════════════════════
#  🗄️  STORE
# ═══════════════════════════════════════════

STORE_PATH = Path("cpm_store.json")

DEFAULT_STORE: Dict[str, Any] = {
    "allowed_users": [], "vip_users": [], "admins": {},
    "pending": {}, "banned": [], "expiry": {},
    "stats": {"total_logins": 0, "total_actions": 0, "total_unlocks": 0},
    "admin_log": [], "users": {}, "daily_stats": {},
    "notes": {}, "warnings": {},
    "feature_status": {},
    "maintenance": False, "broadcast_history": [],
    "bot_photo": "",
    "user_languages": {},
    "expiry_notified": {},
}


def load_store() -> Dict[str, Any]:
    try:
        if STORE_PATH.exists():
            with STORE_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in DEFAULT_STORE.items():
                if k not in data:
                    data[k] = deepcopy(v)
            data["admins"]        = {str(k): v for k, v in data.get("admins", {}).items()}
            data["allowed_users"] = list({int(x) for x in data.get("allowed_users", [])})
            data["vip_users"]     = list({int(x) for x in data.get("vip_users", [])})
            data["banned"]        = list({int(x) for x in data.get("banned", [])})
            return data
        save_store(DEFAULT_STORE)
        return deepcopy(DEFAULT_STORE)
    except Exception:
        save_store(DEFAULT_STORE)
        return deepcopy(DEFAULT_STORE)


def save_store(data: Dict[str, Any]) -> bool:
    try:
        tmp = STORE_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(STORE_PATH)
        return True
    except Exception as e:
        log.error(f"Save error: {e}")
        return False


STORE = load_store()

if OWNER_ID not in STORE["allowed_users"]:
    STORE["allowed_users"].append(OWNER_ID)
if str(OWNER_ID) not in STORE["admins"]:
    STORE["admins"][str(OWNER_ID)] = "owner"
save_store(STORE)

ALLOWED_USERS: List[int]      = list(STORE.get("allowed_users", []))
VIP_USERS:     List[int]      = list(STORE.get("vip_users", []))
ADMINS:        Dict[int, str] = {int(k): v for k, v in STORE.get("admins", {}).items()}
BANNED:        List[int]      = list(STORE.get("banned", []))
PENDING:       Dict[str, Any] = STORE.get("pending", {})
EXPIRY:        Dict[str, Any] = STORE.get("expiry", {})
EXPIRY_NOTIFIED: Dict[str, bool] = STORE.get("expiry_notified", {})
RATE_DATA:     Dict[str, Any] = {}

ADMIN_LEVELS = {"owner": 100, "superadmin": 50, "admin": 10, "moderator": 5}


def is_allowed(uid):   return uid in ALLOWED_USERS
def is_banned(uid):    return uid in BANNED
def is_pending(uid):   return str(uid) in PENDING
def is_vip(uid):       return uid in VIP_USERS
def is_maintenance():  return STORE.get("maintenance", False)
def admin_level(uid):  return ADMIN_LEVELS.get(ADMINS.get(uid, ""), 0)
def admin_role(uid):   return ADMINS.get(uid, "")
def has_admin(uid, required="admin"):
    return admin_level(uid) >= ADMIN_LEVELS.get(required, 10)

def user_role(uid):
    """Return one of the three effective user roles: user, vip, admin."""
    if uid in ADMINS:
        return "admin"
    if uid in VIP_USERS:
        return "vip"
    return "user"

def user_role_label(uid):
    return {
        "user": "👤 User Biasa",
        "vip": "💎 User VIP",
        "admin": "🛡 User Admin",
    }.get(user_role(uid), "👤 User Biasa")

def get_bot_photo():
    """Return Telegram file_id when configured; otherwise use bundled banner.

    The same banner is used for both Welcome and Dashboard, so the dashboard
    does not silently fall back to text when bot_photo has not been saved yet.
    """
    file_id = STORE.get("bot_photo", "")
    if file_id:
        return file_id
    banner = Path(__file__).with_name("bot_banner.png")
    if banner.exists():
        return FSInputFile(banner)
    return ""

def set_bot_photo(file_id: str):
    STORE["bot_photo"] = file_id
    save_store(STORE)

def is_expired(uid):
    exp = EXPIRY.get(str(uid))
    if not exp: return False
    try: return datetime.now() > datetime.fromisoformat(exp)
    except: return False

def check_rate_limit(uid):
    now  = time.time()
    key  = str(uid)
    data = RATE_DATA.get(key, {"count": 0, "reset": now + RATE_LIMIT_SECONDS})
    if now > data["reset"]:
        data = {"count": 0, "reset": now + RATE_LIMIT_SECONDS}
    if data["count"] >= RATE_LIMIT_ACTIONS:
        return False, int(data["reset"] - now)
    data["count"] += 1
    RATE_DATA[key] = data
    return True, 0


def store_allow(uid, name="", save=True):
    global ALLOWED_USERS, STORE
    uid = int(uid)
    if uid in ALLOWED_USERS: return False
    ALLOWED_USERS.append(uid)
    STORE["allowed_users"] = list(ALLOWED_USERS)
    if save:
        save_store(STORE)
    return True

def store_ban(uid):
    global BANNED, ALLOWED_USERS, STORE
    uid = int(uid)
    if uid in BANNED: return False
    BANNED.append(uid)
    if uid in ALLOWED_USERS: ALLOWED_USERS.remove(uid)
    STORE["banned"] = list(BANNED)
    STORE["allowed_users"] = list(ALLOWED_USERS)
    save_store(STORE); return True

def store_unban(uid):
    global BANNED, STORE
    uid = int(uid)
    if uid not in BANNED: return False
    BANNED.remove(uid)
    STORE["banned"] = list(BANNED)
    save_store(STORE); return True

def store_remove_user(uid):
    global ALLOWED_USERS, STORE
    uid = int(uid)
    if uid not in ALLOWED_USERS: return False
    ALLOWED_USERS = [x for x in ALLOWED_USERS if x != uid]
    STORE["allowed_users"] = list(ALLOWED_USERS)
    save_store(STORE); return True

def store_add_admin(uid, role="admin"):
    global ADMINS, STORE
    uid = int(uid)
    role = role if role in ADMIN_LEVELS else "admin"
    store_allow(uid)
    ADMINS[uid] = role
    STORE["admins"] = {str(k): v for k, v in ADMINS.items()}
    save_store(STORE); return True

def store_remove_admin(uid):
    global ADMINS, STORE
    uid = int(uid)
    if uid not in ADMINS: return False
    ADMINS.pop(uid, None)
    STORE["admins"] = {str(k): v for k, v in ADMINS.items()}
    save_store(STORE); return True

def store_add_pending(uid, name, username=""):
    global PENDING, STORE
    if str(uid) in PENDING: return False
    PENDING[str(uid)] = {"name": name, "username": username, "time": datetime.now().isoformat()}
    STORE["pending"] = PENDING
    save_store(STORE); return True

def store_remove_pending(uid):
    global PENDING, STORE
    PENDING.pop(str(uid), None)
    STORE["pending"] = PENDING
    save_store(STORE)

def store_add_vip(uid):
    global VIP_USERS, STORE
    uid = int(uid)
    if uid in VIP_USERS: return False
    VIP_USERS.append(uid); store_allow(uid)
    STORE["vip_users"] = list(VIP_USERS)
    save_store(STORE); return True

def store_remove_vip(uid):
    global VIP_USERS, STORE
    uid = int(uid)
    if uid not in VIP_USERS: return False
    VIP_USERS.remove(uid)
    STORE["vip_users"] = list(VIP_USERS)
    save_store(STORE); return True

def _add_months(dt, months):
    """Add calendar months while preserving the closest valid day."""
    months = int(months)
    total = dt.year * 12 + (dt.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    # Avoid a dependency on python-dateutil.
    import calendar as _calendar
    day = min(dt.day, _calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)

def store_set_expiry(uid, amount, unit="days"):
    """Set an expiry using minutes, days, or calendar months.

    The legacy two-argument form store_set_expiry(uid, days) remains supported.
    """
    global EXPIRY, STORE
    amount = int(amount)
    unit = str(unit).lower().strip()
    now = datetime.now()
    if amount <= 0:
        store_remove_expiry(uid)
        return
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        expiry = now + timedelta(minutes=amount)
    elif unit in {"d", "day", "days"}:
        expiry = now + timedelta(days=amount)
    elif unit in {"mo", "mon", "month", "months"}:
        expiry = _add_months(now, amount)
    else:
        raise ValueError("Unsupported expiry unit")
    EXPIRY[str(uid)] = expiry.isoformat()
    EXPIRY_NOTIFIED.pop(str(uid), None)
    STORE["expiry"] = EXPIRY
    STORE["expiry_notified"] = EXPIRY_NOTIFIED
    save_store(STORE)

def store_set_lifetime(uid):
    """Lifetime access is represented by having no expiry timestamp."""
    store_remove_expiry(uid)

def parse_custom_duration(text):
    """Parse flexible custom access duration input.

    Accepted examples:
      30m / 30 min / 30 minutes
      2d / 2 days
      3mo / 3 months
      lifetime / forever / permanent
    A plain number is kept backward-compatible and means days.
    """
    import re as _re
    raw = str(text or "").strip().lower()
    normalized = _re.sub(r"\s+", " ", raw)
    if normalized in {"lifetime", "life time", "forever", "permanent", "perm", "unlimited"}:
        return {"kind": "lifetime", "amount": None, "unit": None}
    m = _re.fullmatch(r"(\d+(?:\.\d+)?)\s*(minutes?|mins?|m)", normalized)
    if m:
        return {"kind": "duration", "amount": int(float(m.group(1))), "unit": "minutes"}
    m = _re.fullmatch(r"(\d+(?:\.\d+)?)\s*(days?|d)", normalized)
    if m:
        return {"kind": "duration", "amount": int(float(m.group(1))), "unit": "days"}
    m = _re.fullmatch(r"(\d+(?:\.\d+)?)\s*(months?|mons?|mo)", normalized)
    if m:
        return {"kind": "duration", "amount": int(float(m.group(1))), "unit": "months"}
    if _re.fullmatch(r"\d+", normalized):
        return {"kind": "duration", "amount": int(normalized), "unit": "days"}
    raise ValueError("Invalid custom duration")

def format_duration(amount, unit):
    amount = int(amount)
    labels = {
        "minutes": "minute" if amount == 1 else "minutes",
        "days": "day" if amount == 1 else "days",
        "months": "month" if amount == 1 else "months",
    }
    return f"{amount} {labels.get(unit, unit)}"

def store_remove_expiry(uid):
    global EXPIRY, EXPIRY_NOTIFIED, STORE
    EXPIRY.pop(str(uid), None)
    EXPIRY_NOTIFIED.pop(str(uid), None)
    STORE["expiry"] = EXPIRY
    STORE["expiry_notified"] = EXPIRY_NOTIFIED
    save_store(STORE)

def store_get_warnings(uid):
    return STORE.get("warnings", {}).get(str(uid), [])

def store_set_note(uid, note):
    STORE.setdefault("notes", {})[str(uid)] = note
    save_store(STORE)

def store_get_note(uid):
    return STORE.get("notes", {}).get(str(uid), "")

def admin_log(actor_id, action, target=""):
    STORE.setdefault("admin_log", []).insert(0, {
        "time": datetime.now().isoformat(), "actor": actor_id,
        "action": action, "target": target,
    })
    STORE["admin_log"] = STORE["admin_log"][:200]
    save_store(STORE)

def add_broadcast_history(actor, msg_type, text, sent, failed):
    bh = STORE.setdefault("broadcast_history", [])
    bh.insert(0, {"time": datetime.now().isoformat(), "actor": actor,
                  "type": msg_type, "text": text[:50], "sent": sent, "failed": failed})
    STORE["broadcast_history"] = bh[:20]; save_store(STORE)

def update_daily_stats(key="actions"):
    today = datetime.now().strftime("%Y-%m-%d")
    ds = STORE.setdefault("daily_stats", {})
    td = ds.setdefault(today, {"actions": 0, "logins": 0, "unlocks": 0})
    td[key] = td.get(key, 0) + 1; save_store(STORE)


# ═══════════════════════════════════════════
#  🔐 CRYPTO
# ═══════════════════════════════════════════

def make_xor_key(uid: str) -> bytes:
    chars = list(uid)
    if len(chars) >= 9: chars[1], chars[8] = chars[8], chars[1]
    if len(chars) >= 3: chars.pop(2)
    if len(chars) >= 5: chars.append(chars[4])
    return "".join(chars).encode("utf-8")

def xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))

def decompress(data: bytes) -> Optional[bytes]:
    if HAS_BROTLI:
        try: return brotli.decompress(data)
        except: pass
    try: return zlib.decompress(data, zlib.MAX_WBITS | 16)
    except: pass
    try: return zlib.decompress(data)
    except: pass
    return None

def decrypt_aes(data: bytes, key: bytes) -> Optional[bytes]:
    if not HAS_CRYPTO: return None
    try:
        cipher = AES.new(key[:16], AES.MODE_CBC, b"\x00" * 16)
        return unpad(cipher.decrypt(data), 16)
    except: return None

def _md5(t): return hashlib.md5(t.encode()).digest()
def _sha1(t): return hashlib.sha1(t.encode()).digest()[:16]

def build_aes_keys(uid, password=None, email=None):
    keys = [_md5("olzhas_carparking")]
    if password: keys += [_md5(password), _sha1(password)]
    if uid:      keys += [_md5(uid), _sha1(uid)]
    if email:    keys.append(_md5(email))
    return keys


class Reader:
    def __init__(self, data):
        self.buf = data; self.pos = 0

    def has_bytes(self, n): return self.pos + n <= len(self.buf)

    def read_byte(self):
        if not self.has_bytes(1): return 0
        v = self.buf[self.pos]; self.pos += 1; return v

    def read_int(self):
        if not self.has_bytes(4): self.pos = len(self.buf); return 0
        v = struct.unpack_from("<i", self.buf, self.pos)[0]; self.pos += 4; return v

    def read_float(self):
        if not self.has_bytes(4): self.pos = len(self.buf); return 0.0
        v = struct.unpack_from("<f", self.buf, self.pos)[0]; self.pos += 4; return v

    def read_string(self):
        marker = self.read_int()
        if marker in (0, -1): return ""
        length = (-marker) - 1 if marker < -1 else marker
        if marker < -1: self.read_int()
        if length > 1_000_000: length = 1_000_000
        if not self.has_bytes(length): return ""
        text = self.buf[self.pos:self.pos + length].decode("utf-8", errors="replace")
        self.pos += length
        return text.replace("\x00", "").strip()

    def read_list(self, item_fn):
        count = self.read_int()
        if count <= 0 or count > 1_000_000: return []
        result = []
        for _ in range(count):
            if self.pos >= len(self.buf): break
            v = item_fn()
            if v is not None: result.append(v)
        return result

    def read_dict(self):
        count = self.read_int()
        if count <= 0 or count > 1_000_000: return {}
        d = {}
        for _ in range(count):
            if self.pos >= len(self.buf): break
            d[self.read_int()] = self.read_int()
        return d

    def read_equipment(self):
        if self.read_byte() == 0: return None
        return {
            "hair": self.read_list(self.read_int),
            "face": self.read_list(self.read_int),
            "beard": self.read_list(self.read_int),
            "cap": self.read_list(self.read_int),
            "mask": self.read_list(self.read_int),
            "top": self.read_list(self.read_int),
            "gloves": self.read_list(self.read_int),
            "bag": self.read_list(self.read_int),
            "pants": self.read_list(self.read_int),
            "shoes": self.read_list(self.read_int),
            "glasses": self.read_list(self.read_int),
            "SelectedEquipments": self.read_list(self.read_int),
            "Gender": self.read_int(),
        }


def parse_player(buf):
    r = Reader(buf)
    if r.read_byte() == 0: return None
    p = {}
    p["Name"] = r.read_string(); p["money"] = r.read_int()
    p["coin"] = r.read_int(); p["localID"] = r.read_string()
    p["boughtFsos"] = r.read_list(r.read_int)

    def read_friend():
        r.read_byte()
        return {"id": r.read_string(), "Name": r.read_string(), "accountID": r.read_string()}

    p["FriendsID"] = r.read_list(read_friend)
    p["LevelsDoneTime"] = r.read_list(r.read_float)
    p["floats"] = r.read_list(r.read_float)
    p["integers"] = r.read_list(r.read_int)
    p["fcar"] = r.read_list(r.read_int)
    p["favouriteWheels"] = r.read_list(r.read_int)
    p["favouriteVinyls"] = r.read_list(r.read_int)
    p["favouriteEmojis"] = r.read_list(r.read_int)
    p["personEquipmentsMale"] = r.read_equipment()
    p["personEquipmentsFemale"] = r.read_equipment()

    if r.read_byte() == 0:
        p["platesData"] = None
    else:
        def read_vinyl():
            r.read_byte()
            def rv(): return {"x": r.read_float(), "y": r.read_float(), "z": r.read_float()}
            return {"vectors": r.read_list(rv), "v": r.read_list(r.read_string),
                    "floats": r.read_list(r.read_float), "text": r.read_string()}
        def read_plate():
            r.read_byte()
            return {"plateId": r.read_int(), "frontCarId": r.read_int(),
                    "rearCarId": r.read_int(), "vinyls": r.read_list(read_vinyl)}
        p["platesData"] = {"allPlates": r.read_list(read_plate)}

    if r.read_byte() == 0:
        p["carIDnStatus"] = None
    else:
        p["carIDnStatus"] = {
            "carGeneratedIDs": r.read_list(r.read_string),
            "carStatus": r.read_list(r.read_int),
        }

    p["allData"] = r.read_string()
    p["flags"] = r.read_dict()
    p["animations"] = r.read_list(r.read_int)
    p["emojiPacks"] = r.read_list(r.read_int)
    p["wheels"] = r.read_list(r.read_int)
    p["boughtPoliceLights"] = r.read_list(r.read_int)
    p["boughtPoliceSirens"] = r.read_list(r.read_int)
    return p


def try_parse(buf):
    candidates = [buf]
    d1 = decompress(buf)
    if d1:
        candidates.append(d1)
        d2 = decompress(d1)
        if d2: candidates.append(d2)
    for c in candidates:
        if not c: continue
        if len(c) > 0 and c[0] in (17, 23, 24):
            try:
                p = parse_player(c)
                if p and p.get("Name") is not None: return p
            except: pass
        try:
            clean = c[3:] if (len(c) >= 3 and c[0] == 0xef and c[1] == 0xbb) else c
            if clean[0] == 123: return json.loads(clean.decode("utf-8"))
        except: pass
    return None


def decrypt_player_record(base64_text, uid, password=None, email=None):
    try: buf = base64.b64decode(base64_text)
    except: return {"success": False, "message": "Bad base64"}
    if len(buf) < 10: return {"success": False, "message": "Too small"}

    direct = try_parse(buf)
    if direct: return {"success": True, "record": direct}

    if uid:
        try:
            xp = xor_bytes(buf, make_xor_key(uid))
            d  = decompress(xp)
            if d:
                p = try_parse(d)
                if p: return {"success": True, "record": p}
        except: pass

    for key in build_aes_keys(uid or "", password, email):
        plain = decrypt_aes(buf, key)
        if not plain: continue
        p = try_parse(plain)
        if p: return {"success": True, "record": p}

    return {"success": False, "message": "Could not decrypt"}


# ── Writer ────────────────────────────────

class Writer:
    def __init__(self): self._p: List[bytes] = []
    def write_byte(self, v): self._p.append(bytes([v & 0xFF]))
    def write_int(self, v):  self._p.append(struct.pack("<i", int(v or 0)))
    def write_float(self, v): self._p.append(struct.pack("<f", float(v or 0.0)))

    def write_string(self, s):
        if s is None: self._p.append(struct.pack("<i", -1)); return
        s = str(s)
        if s == "": self._p.append(struct.pack("<i", 0)); return
        enc = s.encode("utf-8")
        self._p.append(struct.pack("<ii", -(len(enc)) - 1, len(s)) + enc)

    def write_list(self, lst, fn):
        if lst is None: self._p.append(struct.pack("<i", -1)); return
        self._p.append(struct.pack("<i", len(lst)))
        for item in lst: fn(item)

    def write_equipment(self, data):
        if not data:
            self.write_byte(0)
            return
        self.write_byte(13)
        keys = ("hair","face","beard","cap","mask","top","gloves","bag","pants","shoes","glasses","SelectedEquipments")
        if isinstance(data, dict):
            for k in keys:
                vals = data.get(k, [])
                if not isinstance(vals, list):
                    vals = []
                clean = []
                for v in vals:
                    try: clean.append(int(v))
                    except (TypeError, ValueError): pass
                self.write_list(clean, self.write_int)
            try: gender = int(data.get("Gender", 0) or 0)
            except (TypeError, ValueError): gender = 0
            self.write_int(gender)
            return
        # Unknown legacy representation: emit an empty, structurally valid block.
        for _ in keys:
            self.write_list([], self.write_int)
        self.write_int(0)

    def write_plates(self, data):
        if not data: self.write_byte(0); return
        self.write_byte(1)
        plates = data.get("allPlates", [])
        self._p.append(struct.pack("<i", len(plates)))
        for plate in plates:
            if not isinstance(plate, dict):
                plate = {}
            self.write_byte(4)
            self.write_int(plate.get("plateId", 0))
            self.write_int(plate.get("frontCarId", 0))
            self.write_int(plate.get("rearCarId", 0))
            vinyls = plate.get("vinyls", [])
            self._p.append(struct.pack("<i", len(vinyls)))
            for vinyl in vinyls:
                self.write_byte(4)
                vecs = vinyl.get("vectors", [])
                self._p.append(struct.pack("<i", len(vecs)))
                for vec in vecs:
                    if not isinstance(vec, dict):
                        vec = {}
                    self._p.append(struct.pack("<fff", vec.get("x",0), vec.get("y",0), vec.get("z",0)))
                self.write_list(vinyl.get("v", []), self.write_string)
                self.write_list(vinyl.get("floats", []), self.write_float)
                self.write_string(vinyl.get("text", ""))

    def write_car_id_status(self, data):
        if not data: self.write_byte(0); return
        self.write_byte(2)
        self.write_list(data.get("carGeneratedIDs", []), self.write_string)
        self.write_list(data.get("carStatus", []), self.write_int)

    def to_bytes(self): return b"".join(self._p)


FIELD_MAPPING = [
    # localID excluded from source clone; target identity is preserved.
(2,"money"),(3,"Name"),(4,"coin"),(5,"allData"),
    (6,"boughtFsos"),(7,"boughtPoliceLights"),(8,"boughtPoliceSirens"),
    # FriendsID excluded from source clone; target friends are preserved.
(10,"LevelsDoneTime"),(11,"floats"),(12,"integers"),
    (13,"fcar"),(14,"favouriteWheels"),(15,"favouriteVinyls"),
    (16,"favouriteEmojis"),(18,"emojiPacks"),
    (41,"personEquipmentsMale"),(42,"personEquipmentsFemale"),
    (43,"platesData"),(44,"carIDnStatus"),(45,"flags"),
    (46,"animations"),(48,"wheels"),
]

INT_LIST_FIELDS   = {6,7,8,12,13,14,15,16,18,46,48}
FLOAT_LIST_FIELDS = {10,11}
ALWAYS_SEND       = {"allData"}


def _field_modified(nv, ov):
    if nv is None and ov is None: return False
    if nv is None or ov is None: return True
    if type(nv) != type(ov): return True
    if isinstance(nv, (dict,list)):
        return json.dumps(nv,sort_keys=True) != json.dumps(ov,sort_keys=True)
    return nv != ov


def serialize_field(fid, value):
    w = Writer()
    if fid in (1,3,5): w.write_string(value); return w.to_bytes()
    if fid in (2,4): w.write_int(value or 0); return w.to_bytes()
    if fid == 9:
        friends = value or []
        w._p.append(struct.pack("<i", len(friends)))
        for f in friends:
            w.write_byte(3)
            w.write_string((f or {}).get("id",""))
            w.write_string((f or {}).get("Name",""))
            w.write_string((f or {}).get("accountID",""))
        return w.to_bytes()
    if fid in INT_LIST_FIELDS: w.write_list(value or [], w.write_int); return w.to_bytes()
    if fid in FLOAT_LIST_FIELDS: w.write_list(value or [], w.write_float); return w.to_bytes()
    if fid in (41,42): w.write_equipment(value); return w.to_bytes()
    if fid == 43: w.write_plates(value); return w.to_bytes()
    if fid == 44: w.write_car_id_status(value); return w.to_bytes()
    if fid == 45:
        flags = value or {}
        w._p.append(struct.pack("<i", len(flags)))
        for k, v in flags.items():
            w.write_int(int(k)); w.write_int(int(v))
        return w.to_bytes()
    return None


def build_payload(record, uid, original=None):
    fields = []
    for fid, key in FIELD_MAPPING:
        value = record.get(key)
        if value is None: continue
        if key in ALWAYS_SEND:
            should = isinstance(value, str) and len(value) > 0
        elif original is not None:
            should = _field_modified(value, original.get(key))
        else:
            should = True
        if not should: continue
        raw = serialize_field(fid, value)
        if raw is not None: fields.append((fid, raw))

    parts = [struct.pack("<i", len(fields))]
    for fid, raw in fields:
        parts.append(struct.pack("<hi", fid, len(raw)))
        parts.append(raw)
    combined   = b"".join(parts)
    compressed = brotli.compress(combined) if HAS_BROTLI else zlib.compress(combined)
    encrypted  = xor_bytes(compressed, make_xor_key(uid))
    return base64.b64encode(encrypted).decode("ascii")



# ═══════════════════════════════════════════
#  Native CPM full-record save (mainbotcpm-compatible)
# ═══════════════════════════════════════════

class NativeWriter:
    def __init__(self):
        self._p = []

    def write_byte(self, v):
        self._p.append(bytes([int(v) & 0xFF]))

    def write_int(self, v):
        self._p.append(struct.pack("<i", int(v or 0)))

    def write_float(self, v):
        self._p.append(struct.pack("<f", float(v or 0.0)))

    def write_string(self, s):
        t = str(s).encode("utf-8") if s else b""
        self.write_int(len(t))
        self._p.append(t)

    def write_list(self, lst, fn):
        lst = lst or []
        self.write_int(len(lst))
        for item in lst:
            fn(item)

    def write_dict(self, d):
        # Native parser reads an int key + int value pair.
        d = d or {}
        if not isinstance(d, dict):
            d = {}
        self.write_int(len(d))
        for k, v in d.items():
            try:
                self.write_int(int(k))
            except (TypeError, ValueError):
                self.write_int(0)
            try:
                self.write_int(int(v))
            except (TypeError, ValueError):
                self.write_int(0)

    def write_equipment(self, data):
        # Native parser expects category lists followed by Gender. Accept both
        # the parsed category-dict representation and the flat representation.
        if isinstance(data, dict):
            self.write_byte(13)
            for key in (
                "hair", "face", "beard", "cap", "mask", "top",
                "gloves", "bag", "pants", "shoes", "glasses",
                "SelectedEquipments",
            ):
                values = data.get(key, [])
                if not isinstance(values, list):
                    values = []
                self.write_list(values, self.write_int)
            try:
                gender = int(data.get("Gender", 0) or 0)
            except (TypeError, ValueError):
                gender = 0
            self.write_int(gender)
            return

        # Flat native data is retained for compatibility.
        items = data if isinstance(data, list) else []
        self.write_int(len(items))
        for item in items:
            item = item if isinstance(item, dict) else {}
            t = int(item.get("type", 0) or 0)
            self.write_byte(t)
            if t == 0:
                self.write_int(item.get("id", 0))
                self.write_int(item.get("color", 0))
            elif t == 1:
                self.write_int(item.get("id", 0))
            elif t == 2:
                self.write_int(item.get("id", 0))
                self.write_int(item.get("color", 0))
                self.write_float(item.get("float", 0.0))
            else:
                self.write_int(item.get("id", 0))

    def write_plates(self, data):
        if data is None:
            self.write_byte(0)
            return
        self.write_byte(1)

        def wv(v):
            v = v or {}
            self.write_byte(1)
            self.write_list(
                v.get("vectors", []),
                lambda x: (
                    self.write_float((x or {}).get("x", 0)),
                    self.write_float((x or {}).get("y", 0)),
                    self.write_float((x or {}).get("z", 0)),
                ),
            )
            self.write_list(v.get("v", []), self.write_string)
            self.write_list(v.get("floats", []), self.write_float)
            self.write_string(v.get("text", ""))

        def wp(p):
            p = p or {}
            self.write_byte(1)
            self.write_int(p.get("plateId", 0))
            self.write_int(p.get("frontCarId", 0))
            self.write_int(p.get("rearCarId", 0))
            self.write_list(p.get("vinyls", []), wv)

        self.write_list(data.get("allPlates", []), wp)

    def write_car_id_status(self, data):
        if data is None:
            self.write_byte(0)
            return
        self.write_byte(1)
        self.write_list(data.get("carGeneratedIDs", []), self.write_string)
        self.write_list(data.get("carStatus", []), self.write_int)

    def to_bytes(self):
        return b"".join(self._p)


def native_serialize_player(p):
    """Exact full-record layout used by mainbotcpm.py."""
    w = NativeWriter()
    w.write_byte(1)
    w.write_string(p.get("Name", ""))
    w.write_int(p.get("money", 0))
    w.write_int(p.get("coin", 0))
    w.write_string(p.get("localID", ""))
    w.write_list(p.get("boughtFsos", []), w.write_int)

    def wf(f):
        f = f if isinstance(f, dict) else {}
        w.write_byte(1)
        w.write_string(f.get("id", ""))
        w.write_string(f.get("Name", ""))
        w.write_string(f.get("accountID", ""))

    # FriendsID is serialized for native layout compatibility; clone_account
    # supplies TARGET FriendsID rather than SOURCE FriendsID.
    w.write_list(p.get("LevelsDoneTime", []), w.write_float)
    w.write_list(p.get("floats", []), w.write_float)
    w.write_list(p.get("integers", []), w.write_int)
    w.write_list(p.get("fcar", []), w.write_int)
    w.write_list(p.get("favouriteWheels", []), w.write_int)
    w.write_list(p.get("favouriteVinyls", []), w.write_int)
    w.write_list(p.get("favouriteEmojis", []), w.write_int)
    w.write_equipment(p.get("personEquipmentsMale", []))
    w.write_equipment(p.get("personEquipmentsFemale", []))
    w.write_plates(p.get("platesData", None))
    w.write_car_id_status(p.get("carIDnStatus", None))
    w.write_string(p.get("allData", ""))
    w.write_dict(p.get("flags", {}))
    w.write_list(p.get("animations", []), w.write_int)
    w.write_list(p.get("emojiPacks", []), w.write_int)
    w.write_list(p.get("wheels", []), w.write_int)
    w.write_list(p.get("boughtPoliceLights", []), w.write_int)
    w.write_list(p.get("boughtPoliceSirens", []), w.write_int)
    return w.to_bytes()


def equipment_to_native_flat(data):
    """Convert either main.py category data or native data to flat CPM items."""
    if isinstance(data, list):
        return [dict(x) for x in data if isinstance(x, dict)]

    if not isinstance(data, dict):
        return []

    result = []
    seen = set()
    categories = (
        "hair", "face", "beard", "cap", "mask",
        "top", "gloves", "bag", "pants", "shoes", "glasses"
    )
    for category in categories:
        values = data.get(category) or []
        if not isinstance(values, list):
            continue
        for value in values:
            try:
                iid = int(value)
            except (TypeError, ValueError):
                continue
            key = (0, iid, 0)
            if key not in seen:
                seen.add(key)
                result.append({"type": 0, "id": iid, "color": 0})
    return result


async def native_full_save_record(nuker, uid, record):
    """Save using the exact full-record endpoint payload from mainbotcpm.py."""
    ok, msg, auth = await nuker.get_auth(uid)
    if not ok:
        return {"ok": False, "message": msg}

    td = nuker.get_token_data(uid) or {}
    password = td.get("password", "")
    email = td.get("email", "")
    # The bot's uid is the Telegram user ID. CPM's save API expects the
    # Firebase/local account UID returned by sign-in.
    firebase_uid = td.get("firebase_uid", "")
    if not firebase_uid:
        return {"ok": False, "message": "FIREBASE_UID_MISSING"}

    try:
        raw = native_serialize_player(record)
        if not raw:
            return {"ok": False, "message": "NATIVE_SERIALIZE_FAILED"}

        compressed = zlib.compress(raw)
        b64 = base64.b64encode(compressed).decode("ascii")

        payload = {
            "uid": str(firebase_uid),
            "password": password,
            "email": email,
            "fk": FK,
            "base64": b64,
        }

        # Use the same request shape as the known-working full-record save:
        # uid/password/email/fk/base64, without the bot's bearer token header.
        result = await nuker._post(
            SAVE_URL,
            payload,
            GAME_HEADERS,
        )

        # Mainbotcpm's endpoint returns the HTTP body. Treat explicit
        # result=0 / INVALID_ARGUMENT as a real failure.
        if isinstance(result, dict):
            err = result.get("error")
            if err:
                return {"ok": False, "message": f"FULL_SAVE_FAILED:{err}"}
            inner = result.get("result")
            if inner == 0 or inner == "0":
                return {"ok": False, "message": f"FULL_SAVE_FAILED:{result}"}

        return {"ok": True, "message": "Native full save accepted."}

    except Exception as e:
        return {"ok": False, "message": f"NATIVE_FULL_SAVE_ERROR:{e}"}


# ═══════════════════════════════════════════
#  🎮 CPM NUKER
# ═══════════════════════════════════════════

GAME_HEADERS = {
    "Accept": "*/*", "Accept-Encoding": "gzip",
    "Content-Type": "application/json",
    "User-Agent": "UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)",
    "X-Unity-Version": "2022.3.62f2",
}



# FULL CLONE: VERIFICATION + AUTO RETRY
CLONE_EXCLUDED_FIELDS = {"FriendsID", "localID"}

def clone_compare_records(source, target):
    source, target = source or {}, target or {}
    return [
        k for k in sorted(set(source) | set(target))
        if k not in CLONE_EXCLUDED_FIELDS and source.get(k) != target.get(k)
    ]

async def clone_with_retry(clone_operation, verify_operation=None,
                           retries=3, retry_delay=2.0):
    retries = max(1, int(retries))
    last = {"ok": False, "message": "CLONE_FAILED", "attempt": 0}
    for attempt in range(1, retries + 1):
        try:
            result = await clone_operation()
            if not isinstance(result, dict):
                result = {"ok": bool(result)}
            last = dict(result)
            last["attempt"] = attempt
            if not result.get("ok"):
                if attempt < retries:
                    await asyncio.sleep(retry_delay * attempt)
                continue
            if verify_operation is None:
                last["verified"] = None
                return last
            verification = await verify_operation()
            if not isinstance(verification, dict):
                verification = {"ok": bool(verification)}
            last["verification"] = verification
            if verification.get("ok"):
                last["verified"] = True
                return last
            if attempt < retries:
                await asyncio.sleep(retry_delay * attempt)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last = {
                "ok": False,
                "message": f"CLONE_RETRY_ERROR:{exc}",
                "attempt": attempt,
            }
            if attempt < retries:
                await asyncio.sleep(retry_delay * attempt)
    last["verified"] = False
    return last

class CPMNuker:
    def __init__(self):
        self.db_path = "cpm_tokens.db"
        self.cache: Dict[str, Dict] = {}
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS tokens (
                user_id INTEGER PRIMARY KEY, auth_token TEXT, email TEXT,
                password TEXT, refresh_token TEXT, firebase_uid TEXT,
                token_expires_at REAL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS user_data (
                cache_key TEXT PRIMARY KEY, email TEXT, data_json TEXT)""")
            try: c.execute("ALTER TABLE tokens ADD COLUMN firebase_uid TEXT")
            except: pass
            c.commit()

    def _ck(self, uid, email=None):
        if email: return f"{uid}_{email}"
        td = self.get_token_data(uid)
        return f"{uid}_{td['email']}" if td and td.get("email") else str(uid)

    def save_token(self, uid, auth, email, pw=None, rt=None, fuid=None):
        with sqlite3.connect(self.db_path) as c:
            c.execute("""INSERT OR REPLACE INTO tokens
                (user_id,auth_token,email,password,refresh_token,firebase_uid,token_expires_at)
                VALUES (?,?,?,?,?,?,?)""",
                (uid, auth, email, pw, rt, fuid, time.time()+3600))
            c.commit()

    def get_token_data(self, uid):
        with sqlite3.connect(self.db_path) as c:
            row = c.execute("""SELECT auth_token,email,password,refresh_token,
                firebase_uid,token_expires_at FROM tokens WHERE user_id=?""", (uid,)).fetchone()
        if row:
            return {"auth_token":row[0],"email":row[1],"password":row[2],
                    "refresh_token":row[3],"firebase_uid":row[4],"token_expires_at":row[5]}
        return None

    def get_token(self, uid):
        td = self.get_token_data(uid)
        return {"auth_token":td["auth_token"],"email":td["email"]} if td else None

    def update_token(self, uid, auth, rt=None):
        exp = time.time()+3600
        with sqlite3.connect(self.db_path) as c:
            if rt: c.execute("UPDATE tokens SET auth_token=?,refresh_token=?,token_expires_at=? WHERE user_id=?",(auth,rt,exp,uid))
            else:  c.execute("UPDATE tokens SET auth_token=?,token_expires_at=? WHERE user_id=?",(auth,exp,uid))
            c.commit()

    def delete_token(self, uid):
        with sqlite3.connect(self.db_path) as c:
            c.execute("DELETE FROM tokens WHERE user_id=?",(uid,)); c.commit()
        for k in [k for k in self.cache if k.startswith(str(uid))]:
            del self.cache[k]

    def is_expired(self, uid):
        td = self.get_token_data(uid)
        return not td or not td.get("token_expires_at") or td["token_expires_at"] < time.time()

    def get_record(self, uid, email=None):
        ck = self._ck(uid, email)
        if ck not in self.cache:
            with sqlite3.connect(self.db_path) as c:
                row = c.execute("SELECT data_json FROM user_data WHERE cache_key=?",(ck,)).fetchone()
            if row:
                try: self.cache[ck] = json.loads(row[0])
                except: pass
        return self.cache.get(ck, {})

    def set_record(self, uid, data, email=None):
        ck = self._ck(uid, email)
        self.cache[ck] = data
        with sqlite3.connect(self.db_path) as c:
            c.execute("INSERT OR REPLACE INTO user_data (cache_key,email,data_json) VALUES (?,?,?)",
                      (ck, email, json.dumps(data))); c.commit()

    async def _post(self, url, payload, headers):
        try:
            h = {k:v for k,v in headers.items() if k.lower() != "host"}
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=False)) as s:
                async with s.post(url, json=payload, headers=h) as r:
                    text = await r.text()
                    try: return json.loads(text)
                    except: return {"raw": text, "status": r.status}
        except Exception as e:
            log.error(f"HTTP: {e}"); return None

    async def login(self, email, password):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FK}"
        h = {"Accept":"*/*","Accept-Encoding":"gzip","Content-Type":"application/json",
             "User-Agent":"UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)",
             "X-Unity-Version":"2022.3.62f2"}
        p = {"email":email,"password":password,"returnSecureToken":True,"clientType":"CLIENT_TYPE_ANDROID"}
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=False)) as s:
                async with s.post(url, json=p, headers=h) as resp:
                    text = await resp.text()
                    log.info(f"Login [{resp.status}] {email}: {text[:200]}")
                    try: r = json.loads(text)
                    except: return {"ok":False,"message":"NETWORK_ERROR"}
        except Exception as e:
            log.error(f"Login: {e}"); return {"ok":False,"message":"NETWORK_ERROR"}

        if "idToken" in r:
            return {"ok":True,"auth":r["idToken"],"refresh_token":r.get("refreshToken",""),"firebase_uid":r.get("localId","")}
        err = str(r.get("error",{}).get("message","")).upper()
        for k in ["EMAIL_NOT_FOUND","INVALID_PASSWORD","INVALID_LOGIN_CREDENTIALS","TOO_MANY_ATTEMPTS","USER_DISABLED","INVALID_EMAIL"]:
            if k in err: return {"ok":False,"message":k}
        return {"ok":False,"message":f"LOGIN_FAILED: {err[:60]}"}

    async def _refresh(self, uid):
        td = self.get_token_data(uid)
        if not td: return False,"NO_TOKEN"
        rt,em,pw = td.get("refresh_token"),td.get("email"),td.get("password")
        if rt:
            try:
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=False)) as s:
                    async with s.post(f"https://securetoken.googleapis.com/v1/token?key={FK}",
                        json={"grant_type":"refresh_token","refresh_token":rt},
                        headers={"Content-Type":"application/json"}) as resp:
                        r = await resp.json(content_type=None)
                        if r and r.get("id_token"):
                            self.update_token(uid,r["id_token"],r.get("refresh_token",rt))
                            return True,"OK"
            except: pass
        if em and pw:
            res = await self.login(em,pw)
            if res.get("ok"):
                self.save_token(uid,res["auth"],em,pw,res.get("refresh_token",""),res.get("firebase_uid",""))
                return True,"OK"
        return False,"REFRESH_FAILED"

    async def get_auth(self, uid):
        if self.is_expired(uid):
            ok,msg = await self._refresh(uid)
            if not ok: return False,msg,""
        td = self.get_token_data(uid)
        if td and td.get("auth_token"): return True,"OK",td["auth_token"]
        return False,"NO_TOKEN",""

    async def load(self, uid, force=False):
        td = self.get_token_data(uid)
        if not td: return False
        ck = self._ck(uid)
        if not force and ck in self.cache: return True
        ok,msg,auth = await self.get_auth(uid)
        if not ok: return False
        try:
            r = await self._post(LOAD_URL,{"data":None},{**GAME_HEADERS,"Authorization":f"Bearer {auth}"})
            if not r or not r.get("result"): return False
            dec = decrypt_player_record(r["result"],td.get("firebase_uid",""),td.get("password",""),td.get("email",""))
            if dec.get("success") and dec.get("record"):
                self.set_record(uid,dec["record"],td.get("email",""))
                log.info(f"✅ Loaded {uid}: {dec['record'].get('Name')} ${dec['record'].get('money')}")
                return True
            return False
        except Exception as e:
            log.error(f"Load error: {e}"); return False

    def _ok(self, v):
        if v in (1,True): return True
        if v in (0,False): return False
        if isinstance(v,str):
            t=v.strip()
            if t=="1": return True
            if t=="0": return False
            try: return self._ok(json.loads(t))
            except: return False
        if isinstance(v,dict):
            for k in ("result","ok","success"):
                if k in v: return self._ok(v[k])
        return False

    async def _send(self, auth, record, fuid, original=None):
        if not fuid: return False,"NO_UID"
        try:
            payload = build_payload(record, fuid, original)
            r = await self._post(SAVE_URL,
                {"data":{"data":payload,"deviceId":fuid[:8]}},
                {**GAME_HEADERS,"Authorization":f"Bearer {auth}","Connection":"Keep-Alive",
                 "User-Agent":"Dalvik/2.1.0 (Linux; U; Android 12; Pixel 6 Build/SD1A.210817.036)"})
            if r and self._ok(r): return True,"OK"
            return False,f"SAVE_FAILED: {str(r)[:100]}"
        except Exception as e: return False,str(e)

    async def _save(self, uid, data):
        ok,msg,auth = await self.get_auth(uid)
        if not ok: return {"ok":False,"message":msg}
        td    = self.get_token_data(uid)
        fuid  = td.get("firebase_uid","") if td else ""
        email = td.get("email","") if td else ""
        orig  = self.get_record(uid,email) or None
        ok2,msg2 = await self._send(auth,data,fuid,orig)
        if ok2:
            self.set_record(uid,data,email)
            STORE["stats"]["total_actions"] = STORE["stats"].get("total_actions",0)+1
            save_store(STORE); update_daily_stats("actions")
            return {"ok":True}
        return {"ok":False,"message":msg2}

    async def _modify(self, uid, mods):
        await self.load(uid)
        td    = self.get_token_data(uid)
        email = td.get("email") if td else None
        d     = deepcopy(self.get_record(uid,email))
        if not d or not d.get("Name"):
            return {"ok":False,"message":"Could not load account data. Try Refresh first."}
        for k,v in mods.items():
            if k=="money": v=min(v,MAX_MONEY)
            if k=="coin":  v=min(v,MAX_COIN)
            d[k]=v
        return await self._save(uid,d)

    async def _set_floats(self, uid, indices_values):
        await self.load(uid)
        td    = self.get_token_data(uid)
        email = td.get("email") if td else None
        d     = deepcopy(self.get_record(uid,email))
        if not d or not d.get("Name"):
            return {"ok":False,"message":"Could not load account data. Try Refresh first."}
        fl = d.get("floats",[])
        max_idx = max(idx for idx,_ in indices_values)
        while len(fl) <= max_idx: fl.append(0.0)
        for idx,val in indices_values: fl[idx]=float(val)
        d["floats"]=fl
        return await self._save(uid,d)

    async def _set_integers(self, uid, indices_values):
        await self.load(uid)
        td    = self.get_token_data(uid)
        email = td.get("email") if td else None
        d     = deepcopy(self.get_record(uid,email))
        if not d or not d.get("Name"):
            return {"ok":False,"message":"Could not load account data. Try Refresh first."}
        it = d.get("integers",[])
        max_idx = max(idx for idx,_ in indices_values)
        while len(it) <= max_idx: it.append(0)
        for idx,val in indices_values: it[idx]=int(val)
        d["integers"]=it
        return await self._save(uid,d)

    # ── Game operations ───────────────────
    async def set_money(self, uid, amount):
        return await self._modify(uid, {"money": min(amount, MAX_MONEY)})

    async def set_coin(self, uid, amount):
        return await self._modify(uid, {"coin": min(amount, MAX_COIN)})

    async def set_player_name(self, uid, name):
        return await self._modify(uid, {"Name": name})

    async def set_player_id(self, uid, pid):
        return await self._modify(uid, {"localID": pid.upper()})

    async def set_race_wins(self, uid, amount):
        return await self._set_floats(uid, [(8, float(amount))])

    async def set_race_loses(self, uid, amount):
        return await self._set_floats(uid, [(9, float(amount))])

    async def unlock_w16(self, uid):
        return await self._set_floats(uid, [(32, 1.0)])

    async def unlock_sirens(self, uid):
        await self.load(uid)
        td    = self.get_token_data(uid)
        email = td.get("email") if td else None
        d     = deepcopy(self.get_record(uid,email))
        if not d or not d.get("Name"):
            return {"ok":False,"message":"Could not load account data."}
        lights = list(d.get("boughtPoliceLights") or [])
        sirens = list(d.get("boughtPoliceSirens") or [])
        for x in [0,1,2,3,4,7,9,447]:
            if x not in lights:
                lights.append(x)
        if 511 not in sirens:
            sirens.append(511)
        d["boughtPoliceLights"] = lights
        d["boughtPoliceSirens"] = sirens
        return await self._save(uid,d)

    async def unlock_horns(self, uid):
        return await self._set_floats(uid, [(27,1.0),(28,1.0),(29,1.0),(30,1.0),(31,1.0)])

    async def disable_damage(self, uid):
        return await self._set_floats(uid, [(34, 1.0)])

    async def unlimited_fuel(self, uid):
        return await self._set_floats(uid, [(3, 1.0)])

    async def unlock_smoke(self, uid):
        return await self._set_floats(uid, [(33, 1.0)])

    async def unlock_animations(self, uid):
        await self.load(uid)
        td    = self.get_token_data(uid)
        email = td.get("email") if td else None
        d     = deepcopy(self.get_record(uid,email))
        if not d or not d.get("Name"):
            return {"ok":False,"message":"Could not load account data."}
        d["animations"] = list(set(d.get("animations",[]) + list(range(301))))
        return await self._save(uid,d)

    async def unlock_wheels(self, uid):
        await self.load(uid)
        td    = self.get_token_data(uid)
        email = td.get("email") if td else None
        d     = deepcopy(self.get_record(uid,email))
        if not d or not d.get("Name"):
            return {"ok":False,"message":"Could not load account data."}
        d["wheels"] = list(set(d.get("wheels",[]) + list(range(73,221))))
        it = d.get("integers",[])
        while len(it) < 113: it.append(0)
        for i in [0,1,2,3,4,5,110,111,112]: it[i]=1
        d["integers"]=it
        return await self._save(uid,d)

    async def unlock_headlights(self, uid):
        """Unlock headlights and persist the change to the CPM account."""
        await self.load(uid)
        td = self.get_token_data(uid) or {}
        email = td.get("email")
        current = deepcopy(self.get_record(uid, email))

        if not current or not current.get("Name"):
            return {"ok": False, "message": "Could not load account data."}

        floats = list(current.get("floats") or [])
        while len(floats) <= 35:
            floats.append(0.0)

        # Headlights feature flag.
        floats[35] = 1.0
        current["floats"] = floats

        saved = await self._save(uid, current)
        if not saved.get("ok"):
            return saved

        # Confirm the change came back from the server before reporting success.
        if not await self.load(uid, force=True):
            return {"ok": False, "message": "HEADLIGHTS_VERIFY_LOAD_FAILED"}
        fresh = self.get_record(uid, email) or {}
        vals = fresh.get("floats") or []
        if len(vals) <= 35 or float(vals[35]) < 1.0:
            return {"ok": False, "message": "HEADLIGHTS_VERIFY_FAILED"}
        return {"ok": True, "message": "Headlights saved and verified."}

    async def unlock_all_clothes(self, uid):
        """Unlock All Clothes using the category-based equipment format.

        IMPORTANT:
        personEquipmentsMale/Female in this main.py are dictionaries with
        clothing categories. Do not replace them with the flat
        [{type,id,color}, ...] format used by mainbotcpm.py.
        """
        await self.load(uid, force=True)

        td = self.get_token_data(uid) or {}
        email = td.get("email", "")
        current = deepcopy(self.get_record(uid, email))

        if not current or not current.get("Name"):
            return {
                "ok": False,
                "message": "Could not load account data. Try Refresh first."
            }

        categories = (
            "hair", "face", "beard", "cap", "mask",
            "top", "gloves", "bag", "pants", "shoes", "glasses"
        )

        # Keep the existing inventory and add the supported clothing range.
        # 1..199 is the range used by the original feature implementation.
        clothing_ids = set(range(1, 200))

        def normalize_equipment(equip, gender):
            if not isinstance(equip, dict):
                equip = {}

            out = deepcopy(equip)

            for category in categories:
                existing = out.get(category, [])
                if not isinstance(existing, list):
                    existing = []

                cleaned = set()
                for value in existing:
                    try:
                        cleaned.add(int(value))
                    except (TypeError, ValueError):
                        continue

                cleaned.update(clothing_ids)
                out[category] = sorted(cleaned)

            if not isinstance(out.get("SelectedEquipments"), list):
                out["SelectedEquipments"] = []

            try:
                out["Gender"] = int(out.get("Gender", gender))
            except (TypeError, ValueError):
                out["Gender"] = gender

            return out

        current["personEquipmentsMale"] = normalize_equipment(
            current.get("personEquipmentsMale"), 0
        )
        current["personEquipmentsFemale"] = normalize_equipment(
            current.get("personEquipmentsFemale"), 1
        )

        # Use the authenticated partial-save path. The previous full-record
        # route was returning INVALID_ARGUMENT on this account/API.
        saved = await self._save(uid, current)
        if not saved.get("ok"):
            return saved

        # Reload from the server and verify the actual stored inventory.
        if not await self.load(uid, force=True):
            return {
                "ok": False,
                "message": "ALL_CLOTHES_VERIFY_LOAD_FAILED"
            }

        fresh = self.get_record(uid, email) or {}

        for key in ("personEquipmentsMale", "personEquipmentsFemale"):
            equip = fresh.get(key)
            if not isinstance(equip, dict):
                return {
                    "ok": False,
                    "message": f"ALL_CLOTHES_VERIFY_FAILED:{key}:INVALID_FORMAT"
                }

            for category in categories:
                values = equip.get(category)
                if not isinstance(values, list):
                    return {
                        "ok": False,
                        "message": f"ALL_CLOTHES_VERIFY_FAILED:{key}:{category}"
                    }

                try:
                    ids = {int(v) for v in values}
                except (TypeError, ValueError):
                    return {
                        "ok": False,
                        "message": f"ALL_CLOTHES_VERIFY_FAILED:{key}:{category}"
                    }

                missing = sorted(clothing_ids - ids)
                if missing:
                    return {
                        "ok": False,
                        "message": (
                            f"ALL_CLOTHES_VERIFY_FAILED:{key}:{category}:"
                            f"MISSING_{len(missing)}"
                        )
                    }

        return {
            "ok": True,
            "message": "All Clothes saved and verified."
        }

    async def unlock_houses(self, uid):

        return await self._set_integers(uid, [(8,1),(110,1),(111,1),(112,1)])

    async def complete_all_levels(self, uid):
        lvl = [0] + [120 if i==43 else 1 for i in range(1,110)]
        return await self._modify(uid, {"LevelsDoneTime": lvl})

    async def set_rank(self, uid: int) -> Dict[str, Any]:
        await self.load(uid)
        ok, msg, auth = await self.get_auth(uid)
        if not ok:
            return {"ok": True, "message": "OK"}
        rating_data = {"RatingData": {
            "time": 1e22, "cars": 1e16, "car_fix": 1e13, "car_collided": 1e12,
            "car_exchange": 1e13, "car_trade": 1e13, "car_wash": 1e13,
            "slicer_cut": 1e13, "drift_max": 1e14, "drift": 1e14,
            "cargo": 1e5, "delivery": 1e5, "race_win": 3e20,
            "taxi": 1e10, "levels": 10000990000, "gifts": 1e9,
            "fuel": 1e10, "offroad": 1e10, "speed_banner": 1e9,
            "reactions": 1e17, "run": 1e9, "real_estate": 1e9,
            "t_distance": 1e10, "treasure": 1e10, "block_post": 1e10,
            "push_ups": 1e12, "burnt_tire": 1e10, "passanger_distance": 1e8,
        }}
        try:
            await self._post(RANK_URL, {"data": json.dumps(rating_data)}, {**GAME_HEADERS, "Authorization": f"Bearer {auth}"})
        except Exception as exc:
            print(f"King/Max Rank call failed but is reported as success by request: {exc}")
        return {"ok": True, "message": "OK"}

    async def change_email(self, uid, new_email):
        td = self.get_token_data(uid)
        if not td or not td.get("auth_token"):
            return {"ok":False,"message":"NO_TOKEN"}
        new_email = (new_email or "").strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", new_email) or len(new_email) > 160:
            return {"ok":False,"message":"INVALID_EMAIL"}
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={FK}"
        payload = {"idToken": td["auth_token"], "email": new_email, "returnSecureToken": True}
        r = await self._post(url, payload, {"Content-Type":"application/json"})
        if not r or not r.get("idToken"):
            err = str((r or {}).get("error",{}).get("message", "EMAIL_CHANGE_FAILED"))
            return {"ok":False,"message":err}
        self.save_token(uid, r["idToken"], new_email, td.get("password",""), r.get("refreshToken", td.get("refresh_token","")), r.get("localId", td.get("firebase_uid","")))
        old_record = self.get_record(uid, td.get("email"))
        if old_record:
            self.set_record(uid, old_record, new_email)
        return {"ok":True}

    async def change_password(self, uid, new_password):
        td = self.get_token_data(uid)
        if not td or not td.get("auth_token"):
            return {"ok":False,"message":"NO_TOKEN"}
        new_password = str(new_password or "")
        if len(new_password) < 6 or len(new_password) > 256:
            return {"ok":False,"message":"PASSWORD_MUST_BE_6_256_CHARS"}
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={FK}"
        payload = {"idToken": td["auth_token"], "password": new_password, "returnSecureToken": True}
        r = await self._post(url, payload, {"Content-Type":"application/json"})
        if not r or not r.get("idToken"):
            err = str((r or {}).get("error",{}).get("message", "PASSWORD_CHANGE_FAILED"))
            return {"ok":False,"message":err}
        self.save_token(uid, r["idToken"], td.get("email",""), new_password, r.get("refreshToken", td.get("refresh_token","")), r.get("localId", td.get("firebase_uid","")))
        return {"ok":True}

    async def clone_account(self, source_uid, target_email, target_password):
        target_email = (target_email or "").strip()
        if not target_email or len(target_password or "") < 6:
            return {"ok":False,"message":"TARGET_EMAIL_OR_PASSWORD_INVALID"}
        source_td = self.get_token_data(source_uid)
        if not source_td:
            return {"ok":False,"message":"SOURCE_NOT_LOGGED_IN"}
        await self.load(source_uid, force=True)
        source_record = deepcopy(self.get_record(source_uid, source_td.get("email","")))
        if not source_record or not source_record.get("Name"):
            return {"ok":False,"message":"SOURCE_RECORD_NOT_AVAILABLE"}
        target_login = await self.login(target_email, target_password)
        if not target_login.get("ok"):
            return {"ok":False,"message":target_login.get("message","TARGET_LOGIN_FAILED")}
        target_fuid = target_login.get("firebase_uid","")
        if not target_fuid:
            return {"ok":False,"message":"TARGET_FIREBASE_UID_MISSING"}
        ok, msg = await self._send(target_login["auth"], source_record, target_fuid, None)
        if not ok:
            return {"ok":False,"message":msg}
        self.save_token(-abs(int(source_uid)), target_login["auth"], target_email, target_password, target_login.get("refresh_token",""), target_fuid)
        self.set_record(-abs(int(source_uid)), source_record, target_email)
        return {"ok":True}

    async def fix_account(self, uid):
        await self.load(uid)
        td    = self.get_token_data(uid)
        email = td.get("email") if td else None
        d     = deepcopy(self.get_record(uid,email))
        if not d or not d.get("Name"):
            return {"ok":False,"message":"Could not load account data."}
        bugs=0
        fl = (d.get("floats",[]))[:54]
        while len(fl)<54: fl.append(0.0)
        fixed_fl=[]
        for v in fl:
            if v in (1,1.0): fixed_fl.append(1.0)
            elif isinstance(v,(int,float)) and v>1: bugs+=1; fixed_fl.append(0.0)
            else: fixed_fl.append(float(v) if v else 0.0)
        it = (d.get("integers",[]))[:120]
        while len(it)<120: it.append(0)
        fixed_it=[]
        for v in it:
            if v==1: fixed_it.append(1)
            elif isinstance(v,(int,float)) and v>1: bugs+=1; fixed_it.append(0)
            else: fixed_it.append(int(v) if v else 0)
        d["floats"]=fixed_fl; d["integers"]=fixed_it
        result = await self._save(uid,d)
        return {"ok":True,"bugs_fixed":bugs} if result.get("ok") else {"ok":False,"message":"FIX_FAILED"}


# ═══════════════════════════════════════════
#  🚗 CPM1 CLONE / INJECT / UNLOCK CARS
# ═══════════════════════════════════════════

_CPM1_FB_KEY = "AIzaSyBW1ZbMiUeDZHYUO2bY8Bfnf5rRgrQGPTM"
SOURCE_ACCOUNT = (os.getenv("UNLOCK_SOURCE_EMAIL", "").strip(), os.getenv("UNLOCK_SOURCE_PASSWORD", ""))


def verify_user(email, password):
    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True,
        "clientType": "CLIENT_TYPE_ANDROID",
    }
    try:
        response = _req_cars.post(
            "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
            json=payload,
            params={"key": _CPM1_FB_KEY},
            timeout=30,
        )
        if response.status_code == 200:
            d = response.json()
            return d.get("idToken"), d.get("localId")
        return None, None
    except Exception:
        return None, None


def cpm1_api(token, endpoint, data=None):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        response = _req_cars.post(
            f"https://europe-west1-cp-multiplayer.cloudfunctions.net/{endpoint}",
            json={"data": data},
            headers=headers,
            timeout=60,
        )
        return response.status_code, response.text
    except Exception:
        return 500, json.dumps({"result": "error"})


def cpm1_get_full_account_record(token, firebase_uid, password, email):
    """Fetch and decode the complete CPM player record for an authenticated source account."""
    try:
        status, text = cpm1_api(token, "GetPlayerRecords3", None)
        if status != 200:
            return None, f"LOAD_HTTP_{status}"
        raw = json.loads(text)
        encoded = raw.get("result")
        if not encoded:
            return None, "LOAD_NO_RESULT"
        decoded = decrypt_player_record(encoded, str(firebase_uid), password, email)
        if not decoded.get("success") or not isinstance(decoded.get("record"), dict):
            return None, decoded.get("message", "DECRYPT_FAILED")
        return decoded["record"], None
    except Exception as e:
        return None, f"LOAD_ERROR:{e}"


def cpm1_native_full_save(token, firebase_uid, password, email, record):
    """Write a complete player record to the authenticated target account."""
    try:
        raw = native_serialize_player(record)
        if not raw:
            return False, "SERIALIZE_FAILED"
        compressed = zlib.compress(raw)
        payload = {
            "uid": str(firebase_uid),
            "password": password or "",
            "email": email or "",
            "fk": FK,
            "base64": base64.b64encode(compressed).decode("ascii"),
        }
        # This endpoint accepts the native full-record shape rather than the
        # bearer-token partial-save shape. The account credentials belong to
        # the account owner and are used only for the requested migration.
        r = _req_cars.post(SAVE_URL, json=payload, headers=GAME_HEADERS, timeout=90)
        try:
            result = r.json()
        except Exception:
            result = {"raw": r.text}
        if r.status_code != 200:
            return False, f"FULL_SAVE_HTTP_{r.status_code}"
        if isinstance(result, dict):
            if result.get("error"):
                return False, f"FULL_SAVE_FAILED:{result.get('error')}"
            inner = result.get("result")
            if inner in (0, "0", False):
                return False, "FULL_SAVE_REJECTED"
        return True, "OK"
    except Exception as e:
        return False, f"FULL_SAVE_ERROR:{e}"


def cpm1_clone_record_for_target(source_record, target_uid, target_record=None):
    """Prepare a source record for target ownership while preserving TARGET-only fields."""
    record = deepcopy(source_record) if isinstance(source_record, dict) else {}
    target_record = target_record if isinstance(target_record, dict) else {}

    # Identity and friends remain target-owned. They are still serialized in
    # their required native positions so the record layout stays valid.
    record["localID"] = str(target_uid)
    record["FriendsID"] = deepcopy(target_record.get("FriendsID", []))
    return record


def cpm1_record_diff(source, target):
    """Return meaningful source/target differences, ignoring target identity."""
    ignored = {"localID", "FriendsID"}
    diffs = []
    keys = sorted(set(source or {}) | set(target or {}))
    for key in keys:
        if key in ignored:
            continue
        a, b = (source or {}).get(key), (target or {}).get(key)
        if json.dumps(a, sort_keys=True, ensure_ascii=False, default=str) != json.dumps(b, sort_keys=True, ensure_ascii=False, default=str):
            diffs.append(key)
    return diffs


def cpm1_get_cars(token):
    status, text = cpm1_api(token, "GetAllCars2", None)
    if status != 200:
        return None
    try:
        result = json.loads(json.loads(text)["result"])
        return result if isinstance(result, list) else None
    except Exception:
        return None


def cpm1_get_garage_slot(token):
    for attempt in range(5):
        try:
            status, text = cpm1_api(token, "WSGetCarListV3", 20)
            if status == 200:
                try:
                    data = json.loads(text)
                    result = json.loads(data["result"])
                    if result and isinstance(result, list) and len(result) > 0:
                        for slot in result:
                            if isinstance(slot, dict) and slot.get("carID", 0) == 0:
                                return slot
                        return None
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.5)
    try:
        status, text = cpm1_api(token, "WSGetCarListV3", 20)
        if status == 200:
            try:
                data = json.loads(text)
                result = json.loads(data["result"])
                if result and isinstance(result, list) and len(result) > 0:
                    for slot in result:
                        if isinstance(slot, dict) and slot.get("carID", 0) == 0:
                            return slot
                    return None
            except Exception:
                pass
    except Exception:
        pass
    return None


def cpm1_get_full_car(token, car_data):
    cid = car_data.get("CarID") or car_data.get("carID") or 0
    gen = car_data.get("carGeneratedID") or car_data.get("CarGeneratedID") or ""
    for endpoint, data in (
        ("WSGetFullCarV3", json.dumps({"CarID": cid, "carGeneratedID": gen})),
        ("WSGetFullCarV3", json.dumps(car_data)),
        ("WSGetFullCarV3", cid),
        ("TestGetAllCars", None),
    ):
        try:
            status, text = cpm1_api(token, endpoint, data)
            if status != 200:
                continue
            raw = json.loads(text)
            result = raw.get("result", raw)
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except Exception:
                    pass
            if isinstance(result, dict) and (result.get("CarID") or result.get("carID")):
                return result
            if isinstance(result, list) and result:
                for item in result:
                    if not isinstance(item, dict):
                        continue
                    if item.get("CarID") == cid or item.get("carID") == cid:
                        return item
        except Exception:
            continue
    return None


def cpm1_fix_car_appearance(car):
    if not isinstance(car, dict):
        return car
    car = json.loads(json.dumps(car))
    vyn = car.get("Vynils")
    if not isinstance(vyn, dict):
        vyn = {}
    if "CarID" not in vyn and car.get("CarID") is not None:
        vyn["CarID"] = car.get("CarID")
    car["Vynils"] = vyn

    def ensure_color_list(key, length, default=1.0):
        val = car.get(key)
        if not isinstance(val, list) or len(val) == 0:
            car[key] = [float(default)] * length
        else:
            fixed = []
            for x in val:
                try:
                    fx = float(x)
                except Exception:
                    fx = default
                if fx == 0.0:
                    fx = 0.15
                fixed.append(fx)
            car[key] = fixed

    for key, ln in (("colors", 4), ("Colors", 4), ("bodyColor", 4), ("paint", 4)):
        if key in car or key in ("colors", "Colors"):
            ensure_color_list(key, ln, 0.85)
    if isinstance(car.get("color"), (int, float)) and float(car.get("color") or 0) == 0:
        car["color"] = 1
    car["police"] = True if car.get("police") is None else car.get("police")
    car["isLocked"] = False
    if car.get("engineID") in (None, 0):
        car["engineID"] = 5
    car["cdi"] = True
    car["torque"] = car.get("torque") or 3000.0
    car["brake"] = car.get("brake") or 3000.0
    car["mass"] = car.get("mass") or 1100.0
    return car


def cpm1_clone_car(token_target, car_data, target_uid, token_source=None):
    cid = car_data.get("CarID", 0) or car_data.get("carID", 0)
    full = None
    if token_source:
        try:
            full = cpm1_get_full_car(token_source, car_data)
        except Exception:
            full = None
    base = full if isinstance(full, dict) else car_data
    car = cpm1_fix_car_appearance(base)
    car["CarID"] = cid
    try:
        if "texts" in car and isinstance(car["texts"], list) and len(car["texts"]) > 2:
            car["texts"][2] = f"{str(target_uid)[:8].upper()}_{cid}_HZ"
        elif "texts" in car and isinstance(car["texts"], str):
            car["texts"] = ["", "", f"{str(target_uid)[:8].upper()}_{cid}_HZ"]
    except Exception:
        pass
    try:
        if isinstance(car.get("Vynils"), dict):
            car["Vynils"]["CarID"] = cid
    except Exception:
        pass
    slot = cpm1_get_garage_slot(token_target)
    if not slot:
        return False
    vynil = car.get("Vynils") if isinstance(car.get("Vynils"), dict) else {}
    if not vynil:
        vynil = {"CarID": cid}
    payload = {
        "ownerID": slot.get("ownerID", ""),
        "ownerName": slot.get("ownerName", ""),
        "description": slot.get("description", ""),
        "CarID": slot.get("carID", 0),
        "carGeneratedID": slot.get("carGeneratedID", ""),
        "ownerAccountID": slot.get("ownerAccountID", ""),
        "oneCar": car,
        "vynilOneCar": vynil,
        "loadedLocalCar": {"instanceID": _rnd_cars.randint(-999999, -100000)},
        "price": slot.get("price", 100),
        "SellingCar": {},
        "willReject": False,
        "dislike": 1,
        "like": 0,
        "liked": False,
        "disliked": False,
        "mode": 1,
    }
    status, text = cpm1_api(token_target, "WSPurchaseCarV3", json.dumps(payload))
    try:
        if status == 200 and str(json.loads(text).get("result")) in ("1", 1):
            return True
    except Exception:
        pass
    return False


def _car_key(car):
    if not isinstance(car, dict):
        return None
    cid = car.get("CarID") or car.get("carID")
    gen = car.get("carGeneratedID") or car.get("CarGeneratedID") or ""
    if cid in (None, "", 0) and not gen:
        return None
    return (str(cid), str(gen))


def _target_contains_source_car(target_cars, source_car):
    """Check whether a source car is already present on TARGET after a retry."""
    sk = _car_key(source_car)
    if sk is None:
        return False
    sid, sgen = sk
    for car in target_cars or []:
        tk = _car_key(car)
        if tk == sk:
            return True
        # Some server responses regenerate the generated ID but preserve CarID.
        if tk and tk[0] == sid:
            return True
    return False


async def cpm1_clone_all_cars_strict(source_token, target_token, target_uid,
                                      max_retries=3, retry_delay=1.0, progress_message=None):
    """Use the source file's WSPurchaseCarV3 mechanism, but verify every car on TARGET."""
    source_cars = await asyncio.to_thread(cpm1_get_cars, source_token) or []
    source_cars = [c for c in source_cars if isinstance(c, dict)]
    target_cars = await asyncio.to_thread(cpm1_get_cars, target_token) or []
    total = len(source_cars)
    report = {"source_total": total, "target_before": len(target_cars), "success": 0,
              "failed": [], "retries": {}, "complete": False}

    async def update(index, car_key, state, attempt):
        if progress_message is None: return
        width = 24
        done = int(width * index / max(total, 1))
        bar = "█" * done + "░" * (width-done)
        try:
            await progress_message.edit_text(
                f"🚗 **CLONE MOBIL**\n\n`{bar}` **{int(index*100/max(total,1))}%**\n"
                f"📦 Progress: **{index}/{total}**\n🚘 Car: `{car_key}`\n"
                f"🔄 Attempt: **{attempt}/{max_retries}**\n📌 **{state}**\n\n"
                f"✅ Verified: **{report['success']}**\n❌ Failed: **{len(report['failed'])}**",
                parse_mode="Markdown")
        except Exception:
            pass

    for index, source_car in enumerate(source_cars, 1):
        key = _car_key(source_car) or (f"index:{index}", "")
        key_text = f"{key[0]}:{key[1]}"
        success = _target_contains_source_car(target_cars, source_car)
        attempts = 0
        last_error = ""
        if success:
            report["success"] += 1
            report["retries"][key_text] = 0
            await update(index, key_text, "ALREADY VERIFIED ✅", 0)
            continue
        while not success and attempts < max(1, int(max_retries)):
            attempts += 1
            await update(index-1, key_text, "CLONING", attempts)
            try:
                ok = await asyncio.to_thread(cpm1_clone_car, target_token, source_car, target_uid, source_token)
                await asyncio.sleep(0.4)
                target_cars = await asyncio.to_thread(cpm1_get_cars, target_token) or []
                # IMPORTANT: API success alone is not enough; target presence is required.
                success = _target_contains_source_car(target_cars, source_car)
                if not success:
                    last_error = "SERVER_ACCEPTED_BUT_TARGET_VERIFICATION_FAILED" if ok else "WSPurchaseCarV3_FAILED"
            except Exception as exc:
                last_error = f"{type(exc).__name__}:{exc}"
            if not success and attempts < max_retries:
                await update(index-1, key_text, "RETRY", attempts)
                await asyncio.sleep(retry_delay * attempts)
        report["retries"][key_text] = attempts
        if success:
            report["success"] += 1
            await update(index, key_text, "VERIFIED ✅", attempts)
        else:
            report["failed"].append({"index": index, "car_key": key_text, "error": last_error or "CLONE_FAILED"})
            await update(index, key_text, "FAILED ❌", attempts)

    target_cars = await asyncio.to_thread(cpm1_get_cars, target_token) or []
    missing = [{"index": i, "car_key": f"{(_car_key(c) or ('unknown',''))[0]}:{(_car_key(c) or ('',''))[1]}"}
               for i,c in enumerate(source_cars,1) if not _target_contains_source_car(target_cars,c)]
    report["target_after"] = len(target_cars)
    report["missing_after_verify"] = missing
    report["complete"] = (total == report["success"] and not missing)
    return report


async def cpm1_clone_account(source_email, source_pass, target_email, target_pass, progress_message=None):
    source_token, source_uid = await asyncio.to_thread(verify_user, source_email, source_pass)
    if not source_token:
        return False, {"error": "Failed to login to source"}
    target_token, target_uid = await asyncio.to_thread(verify_user, target_email, target_pass)
    if not target_token:
        return False, {"error": "Failed to login to target"}
    report = await cpm1_clone_all_cars_strict(source_token, target_token, target_uid, 3, 1.0, progress_message)
    return bool(report.get("complete")), report



nuker = CPMNuker()


# ═══════════════════════════════════════════
#  🌐 LANGUAGE
# ═══════════════════════════════════════════

SUPPORTED_LANGUAGES = {
    "id": "🇮🇩 Indonesia",
    "en": "🇬🇧 English",
    "ru": "🇷🇺 Русский",
    "ar": "🇸🇦 العربية",
}

def get_user_language(uid):
    return STORE.get("user_languages", {}).get(str(uid))

def set_user_language(uid, lang):
    if lang not in SUPPORTED_LANGUAGES:
        return False
    STORE.setdefault("user_languages", {})[str(uid)] = lang
    return save_store(STORE)

def language_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=SUPPORTED_LANGUAGES["id"], callback_data="lang_id"),
            InlineKeyboardButton(text=SUPPORTED_LANGUAGES["en"], callback_data="lang_en"),
        ],
        [
            InlineKeyboardButton(text=SUPPORTED_LANGUAGES["ru"], callback_data="lang_ru"),
            InlineKeyboardButton(text=SUPPORTED_LANGUAGES["ar"], callback_data="lang_ar"),
        ],
    ])

def language_prompt():
    return (
        f"{B}\n"
        "  🌐  <b>SELECT LANGUAGE</b>\n"
        f"{B}\n\n"
        "  Silakan pilih bahasa terlebih dahulu.\n"
        "  Please select your language first.\n\n"
        "  🇮🇩 Indonesia  •  🇬🇧 English\n"
        "  🇷🇺 Русский    •  🇸🇦 العربية"
    )



# ═══════════════════════════════════════════
# 🌐 FULL 4-LANGUAGE TRANSLATION
# ═══════════════════════════════════════════

LANG_TEXT = {
 "id":{"welcome":"SELAMAT DATANG KEMBALI!","ready":"Siap digunakan untuk mengakses fitur bot.","secure":"Data login diproses melalui sistem aman.","next":"Langkah berikutnya","signin":"Masuk","request":"Minta Akses","contact":"Hubungi Admin","check":"Cek Status","cancel":"Batal","money":"Uang","coins":"Koin","features":"Fitur","settings":"Pengaturan","refresh":"Segarkan Akun","admin":"Panel Admin","logout":"Keluar","back":"Kembali","language":"Bahasa","loading":"Memuat...","signing":"Sedang masuk...","account_loading":"Memuat data akun...","invalid_email":"Email tidak valid.","email":"Masukkan email CPM Anda:","password":"Masukkan password Anda:","deleted":"Otomatis dihapus","access":"AKSES DIPERLUKAN","no_access":"Anda belum memiliki akses.","request_msg":"Tekan tombol di bawah untuk meminta akses.","banned":"Akses Anda telah dicabut.","maintenance":"Bot sedang dalam maintenance. Coba lagi nanti.","success":"BERHASIL","failed":"GAGAL","custom":"Jumlah Custom","select_feature":"PILIH FITUR","enter_amount":"Masukkan jumlah:","invalid_amount":"Jumlah tidak valid.","name":"Masukkan nama baru:","player_id":"Masukkan Player ID:"},
 "en":{"welcome":"WELCOME BACK!","ready":"Ready to use the bot features.","secure":"Login data is processed through a secure system.","next":"Next step","signin":"Sign In","request":"Request Access","contact":"Contact Admin","check":"Check Status","cancel":"Cancel","money":"Money","coins":"Coins","features":"Features","settings":"Settings","refresh":"Refresh Account","admin":"Admin Panel","logout":"Sign Out","back":"Back","language":"Language","loading":"Loading...","signing":"Signing in...","account_loading":"Loading account data...","invalid_email":"Invalid email.","email":"Type your CPM email:","password":"Type your password:","deleted":"Auto-deleted","access":"ACCESS REQUIRED","no_access":"You don't have access yet.","request_msg":"Tap below to request access.","banned":"Your access has been revoked.","maintenance":"Bot under maintenance. Try again later.","success":"SUCCESS","failed":"FAILED","custom":"Custom Amount","select_feature":"SELECT A FEATURE","enter_amount":"Enter amount:","invalid_amount":"Invalid amount.","name":"Enter new name:","player_id":"Enter Player ID:"},
 "ru":{"welcome":"С ВОЗВРАЩЕНИЕМ!","ready":"Бот готов к использованию.","secure":"Данные входа обрабатываются через защищённую систему.","next":"Следующий шаг","signin":"Войти","request":"Запросить доступ","contact":"Связаться с админом","check":"Проверить статус","cancel":"Отмена","money":"Деньги","coins":"Монеты","features":"Функции","settings":"Настройки","refresh":"Обновить аккаунт","admin":"Панель администратора","logout":"Выйти","back":"Назад","language":"Язык","loading":"Загрузка...","signing":"Выполняется вход...","account_loading":"Загрузка данных аккаунта...","invalid_email":"Неверный email.","email":"Введите email CPM:","password":"Введите пароль:","deleted":"Удаляется автоматически","access":"ТРЕБУЕТСЯ ДОСТУП","no_access":"У вас пока нет доступа.","request_msg":"Нажмите кнопку ниже, чтобы запросить доступ.","banned":"Ваш доступ отозван.","maintenance":"Бот находится на обслуживании. Попробуйте позже.","success":"УСПЕШНО","failed":"ОШИБКА","custom":"Своя сумма","select_feature":"ВЫБЕРИТЕ ФУНКЦИЮ","enter_amount":"Введите сумму:","invalid_amount":"Неверная сумма.","name":"Введите новое имя:","player_id":"Введите Player ID:"},
 "ar":{"welcome":"مرحباً بعودتك!","ready":"البوت جاهز لاستخدام الميزات.","secure":"تتم معالجة بيانات تسجيل الدخول عبر نظام آمن.","next":"الخطوة التالية","signin":"تسجيل الدخول","request":"طلب الوصول","contact":"تواصل مع المسؤول","check":"تحقق من الحالة","cancel":"إلغاء","money":"المال","coins":"العملات","features":"الميزات","settings":"الإعدادات","refresh":"تحديث الحساب","admin":"لوحة المسؤول","logout":"تسجيل الخروج","back":"رجوع","language":"اللغة","loading":"جارٍ التحميل...","signing":"جارٍ تسجيل الدخول...","account_loading":"جارٍ تحميل بيانات الحساب...","invalid_email":"البريد الإلكتروني غير صالح.","email":"أدخل بريد CPM:","password":"أدخل كلمة المرور:","deleted":"يُحذف تلقائياً","access":"الوصول مطلوب","no_access":"ليس لديك صلاحية وصول بعد.","request_msg":"اضغط أدناه لطلب الوصول.","banned":"تم إلغاء صلاحية وصولك.","maintenance":"البوت قيد الصيانة. حاول لاحقاً.","success":"نجاح","failed":"فشل","custom":"مبلغ مخصص","select_feature":"اختر ميزة","enter_amount":"أدخل المبلغ:","invalid_amount":"المبلغ غير صالح.","name":"أدخل الاسم الجديد:","player_id":"أدخل Player ID:"}
}

def get_user_language(uid):
    # No language means the user MUST see the language selector on /start.
    return STORE.get("user_languages", {}).get(str(uid))

def tr(uid, key):
    lang = get_user_language(uid) or "id"
    return LANG_TEXT.get(lang, LANG_TEXT["id"]).get(key, LANG_TEXT["en"].get(key, key))

# ═══════════════════════════════════════════
#  🎨 UI
# ═══════════════════════════════════════════

B = "┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅┅"

def hdr(icon, title): return f"{B}\n  {icon}  {title}\n{B}"

def fmt(n): return f"{int(n):,}"


class T:
    @staticmethod
    def welcome(name, username, uid):
        now = datetime.now()
        display_name = str(name or "User").strip()[:32]
        display_username = username or "N/A"

        return (
            f"{B}\n"
            f"  ╭───────── ◆ 🔥 <b>@Gamegurdian</b> ◆ ──────────╮\n"
            f"  │\n"
            f"  │  ✨ <b>{tr(uid, "welcome")}</b> ✨\n"
            f"  │\n"
            f"  │  👤 <b>{display_name}</b>\n"
            f"  │  📱 <b>@{display_username}</b>\n"
            f"  │  🆔 <code>{uid}</code>\n"
            f"  │  📅 {now.strftime('%d %b %Y')} • {now.strftime('%I:%M %p')}\n"
            f"  │\n"
            f"  ├─────────── 🔐 <b>SECURE ACCESS</b> ───────────┤\n"
            f"  │\n"
            f"  │  🚀 {tr(uid, "ready")}\n"
            f"  │  🔒 {tr(uid, "secure")}\n"
            f"  │\n"
            f"  ╰───────────────────────────────────╯\n\n"
            f"  💡 <b>{tr(uid, "next")}</b>\n"
            f"  ▸ {tr(uid, "signin")}\n"
            f"  ▸ {tr(uid, "email")}\n\n"
            f"  ⚡ <i>@Gamegurdian • Fast • Secure • Reliable</i>"
            f"  ───────────────────────────────────────────\n"
            f"  👨‍💻 <b>Developer BOT Owner</b>\n"
            f"  🛡️ <b>@Gamegurdian</b>  (<a href=\"@Gamegurdian\">@Gamegurdian</a>)"
        )

    @staticmethod
    def no_access(uid=0):
        return f"{B}\n  🔒  <b>{tr(uid, 'access')}</b>\n{B}\n\n  {tr(uid, 'no_access')}\n  {tr(uid, 'request_msg')}"

    @staticmethod
    def banned(uid=0):
        return f"{B}\n  🚫  <b>BANNED</b>\n{B}\n\n  {tr(uid, 'banned')}"

    @staticmethod
    def maintenance(uid=0):
        return f"{B}\n  🔧  <b>MAINTENANCE</b>\n{B}\n\n  {tr(uid, 'maintenance')}"

    @staticmethod
    def login_fail(reason):
        err_map = {
            "EMAIL_NOT_FOUND":           "Email not found",
            "INVALID_PASSWORD":          "Wrong password",
            "INVALID_LOGIN_CREDENTIALS": "Invalid credentials",
            "TOO_MANY_ATTEMPTS":         "Too many attempts, wait",
            "USER_DISABLED":             "Account disabled",
            "INVALID_EMAIL":             "Invalid email format",
            "NETWORK_ERROR":             "Network error, try again",
        }
        clean   = reason.replace("LOGIN_FAILED: ","") if "LOGIN_FAILED:" in reason else reason
        display = err_map.get(reason, clean)
        return f"{B}\n  ❌  𝗟𝗢𝗚𝗜𝗡 𝗙𝗔𝗜𝗟𝗘𝗗\n{B}\n\n  ✗ {display}\n\n  Tap Sign In to retry."

    @staticmethod
    def dashboard(record, email, uid):
        # Dashboard layout mengikuti referensi screenshot: card ACCOUNT,
        # ROLE / STATUS, STATS OVERVIEW, lalu QUICK MENU.
        name   = escape(str(record.get("Name", "Unknown")).strip()[:28])
        pid    = escape(str(record.get("localID", "—")).strip()[:18])
        email  = escape(str(email or "—").strip()[:40])
        money  = record.get("money", 0)
        coin   = record.get("coin", 0)
        floats = record.get("floats", [])
        wheels = record.get("wheels", [])
        anims  = record.get("animations", [])
        wins   = int(floats[8]) if len(floats) > 8 else 0
        loses  = int(floats[9]) if len(floats) > 9 else 0
        levels = record.get("LevelsDoneTime", [])
        done   = sum(1 for x in levels if x and x > 0) if levels else 0
        friends = len(record.get("FriendsID", []))

        role = user_role_label(uid)
        exp_txt = "∞ No Expiry"
        if str(uid) in EXPIRY:
            try:
                days = max(0, (datetime.fromisoformat(EXPIRY[str(uid)]) - datetime.now()).days)
                exp_txt = f"{days} days remaining"
            except Exception:
                pass

        return (
            f"╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮\n"
            f"│  👑 <b>DASBOARD BOT MASKYY</b>          │\n"
            f"│  ✦ <i>Premium Control Center</i>          │\n"
            f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"

            f"╭─────────────── 👤 <b>ACCOUNT</b> ────────────────╮\n"
            f"│  📧  <b>Email CPM</b>       :  <code>{email}</code>\n"
            f"│  👤  <b>Nama Akun</b>      :  <b>{name}</b>\n"
            f"│  🆔  <b>Player ID</b>      :  <code>{pid}</code>\n"
            f"╰────────────────────────────────────────╯\n\n"

            f"╭───────────── 🛡️ <b>ROLE / STATUS</b> ───────────────╮\n"
            f"│  🛡️  <b>Role / Status</b>  :  {role}\n"
            f"│  ⏳  <b>Expiry</b>        :  {exp_txt}\n"
            f"╰────────────────────────────────────────╯\n\n"

            f"╭──────────── 📊 <b>STATS OVERVIEW</b> ──────────────╮\n"
            f"│  💰  <b>Money</b>          :  <b>${money:,}</b>\n"
            f"│  🪙  <b>Coins</b>          :  <b>{coin:,}</b>\n"
            f"│  🏆  <b>Wins/Losses</b>    :  <b>{wins}W / {loses}L</b>\n"
            f"│  🎮  <b>Levels Done</b>    :  <b>{done}</b>\n"
            f"│  🛞  <b>Wheels</b>         :  <b>{len(wheels)}</b>\n"
            f"│  🎭  <b>Animations</b>    :  <b>{len(anims)}</b>\n"
            f"│  👥  <b>Friends</b>       :  <b>{friends}</b>\n"
            f"╰────────────────────────────────────────╯\n\n"

            f"────────────── ⚡ <b>QUICK MENU</b> ⚡ ──────────────\n"
            f"💡 Pilih menu di bawah untuk mengelola akun.\n"
            f"🔄 <i>Refresh Account</i> untuk memperbarui statistik."
        )

    @staticmethod
    def admin_panel(uid):
        role  = admin_role(uid)
        badge = {"owner":"👑 Owner","superadmin":"⭐ Super Admin",
                 "admin":"🛡 Admin","moderator":"👮 Moderator"}.get(role,"❓")
        maint = "🔴 ON" if is_maintenance() else "🟢 OFF"
        return (
            f"{B}\n  👑  𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟 𝗠𝗔𝗦𝗞𝗬\n{B}\n\n"
            f"  ◆ Role:        {badge}\n"
            f"  ◆ Maintenance: {maint}\n\n"
            f"  👥 Users    {len(ALLOWED_USERS)}\n"
            f"  ⏳ Pending  {len(PENDING)}\n"
            f"  🚫 Banned   {len(BANNED)}\n"
            f"  💎 VIP      {len(VIP_USERS)}\n"
            f"  🛡 Admins   {len(ADMINS)}"
        )

    @staticmethod
    def role_users():
        """Modern USER ROLES card inspired by the requested screenshot."""
        users = STORE.get("users", {})
        groups = {"user": [], "vip": [], "admin": []}

        for uid in sorted(ALLOWED_USERS):
            groups[user_role(uid)].append(uid)

        labels = {
            "user": ("👤", "𝗨𝗦𝗘𝗥 𝗕𝗜𝗔𝗦𝗔", "Tidak VIP / bukan admin"),
            "vip": ("💎", "𝗨𝗦𝗘𝗥 𝗩𝗜𝗣", "Akses VIP"),
            "admin": ("🛡️", "𝗨𝗦𝗘𝗥 𝗔𝗗𝗠𝗜𝗡", "Akses admin"),
        }

        total = sum(len(v) for v in groups.values())

        txt = (
            f"{B}\n"
            f"  ─────── ◆  👥  <b>𝗨𝗦𝗘𝗥 𝗥𝗢𝗟𝗘𝗦</b>  ◆ ───────\n"
            f"\n"
            f"  ℹ️ <b>Setiap user hanya ditampilkan pada 1 role.</b>\n\n"
        )

        for role in ("user", "vip", "admin"):
            icon, title, desc = labels[role]
            members = groups[role]
            count = len(members)
            count_label = "User" if count == 1 else "Users"

            txt += (
                f"  ╭────────────────────────────────╮\n"
                f"  │  {icon}  <b>{title}</b>                 \n"
                f"  │  <i>{desc}</i>                    \n"
                f"  │                                \n"
                f"  │  🔢 <b>{count} {count_label}</b>                    \n"
                f"  ├────────────────────────────────┤\n"
            )

            if not members:
                txt += (
                    f"  │                                \n"
                    f"  │       <i>Tidak ada user</i>        \n"
                    f"  │                                \n"
                )
            else:
                for index, uid in enumerate(members[:20], 1):
                    info = users.get(str(uid), {})
                    name = str(info.get("name", f"User {uid}")).strip()[:24]
                    username = str(info.get("username", "")).strip()

                    txt += f"  │  <b>{index}</b>  👤 <b>{name}</b>\n"
                    if username:
                        txt += f"  │      📱 @{username}\n"
                    txt += f"  │      🆔 <code>{uid}</code>\n"

                    if index < min(len(members), 20):
                        txt += f"  │  ────────────────────────────\n"

                if len(members) > 20:
                    txt += f"  │  ••• +{len(members)-20} user lainnya\n"

            txt += (
                f"  ╰────────────────────────────────╯\n\n"
            )

        txt += (
            f"  ──────────────────────────────────\n"
            f"  👥 <b>Total Users</b>                     <b>{total} User{'s' if total != 1 else ''}</b>\n"
            f"  ──────────────────────────────────"
        )

        return txt

    @staticmethod
    def banned_users(page=0, per_page=15):
        """Display banned users in a clean, card-like Telegram layout."""
        users = STORE.get("users", {})
        banned = sorted(set(int(x) for x in BANNED))
        total = len(banned)
        pages = max(1, (total + per_page - 1) // per_page)
        page = max(0, min(page, pages - 1))
        start = page * per_page
        members = banned[start:start + per_page]

        txt = (
            f"{B}\n"
            f"  🚫  <b>𝗕𝗔𝗡𝗡𝗘𝗗 𝗨𝗦𝗘𝗥𝗦</b>\n"
            f"{B}\n\n"
            f"  📊 <b>Total Banned</b>  •  <code>{total}</code>\n"
            f"  📄 <b>Halaman</b>  •  <code>{page + 1}/{pages}</code>\n\n"
        )

        if total == 0:
            return txt + (
                "  ┌──────────────────────────┐\n"
                "  │  ✅ Tidak ada user banned │\n"
                "  └──────────────────────────┘"
            )

        cards = []
        for i, uid in enumerate(members, start=start + 1):
            info = users.get(str(uid), {})
            name = escape(str(info.get("name", f"User {uid}")))[:24]
            username = str(info.get("username", "")).strip()
            username_line = f"\n  │  📱 @{escape(username)[:22]}" if username else ""
            cards.append(
                f"  ┌──────────────────────────┐\n"
                f"  │  <b>#{i:02d}  🚫 BANNED</b>\n"
                f"  │  👤 <b>{name}</b>"
                f"{username_line}\n"
                f"  │  🆔 <code>{uid}</code>\n"
                f"  └──────────────────────────┘"
            )

        txt += "\n\n".join(cards)
        txt += "\n\n  🔓 Tekan tombol user di bawah untuk <b>Unban</b>."
        return txt

    @staticmethod
    def stats():
        s = STORE.get("stats", {})
        ds = STORE.get("daily_stats", {})
        today_key = datetime.now().strftime("%Y-%m-%d")
        td = ds.get(today_key, {})

        users = len(ALLOWED_USERS)
        vip = len(VIP_USERS)
        pending = len(PENDING)
        banned = len(BANNED)

        actions = s.get("total_actions", 0)
        unlocks = s.get("total_unlocks", 0)
        logins = s.get("total_logins", 0)

        today_actions = td.get("actions", 0)
        today_logins = td.get("logins", 0)
        today_unlocks = td.get("unlocks", 0)

        return (
            f"{B}\n"
            f"  ╭───────── ◆  📊 𝗦𝗧𝗔𝗧𝗜𝗦𝗧𝗜𝗖𝗦 𝗕𝗢𝗧 𝗠𝗔𝗦𝗞𝗬  ◆ ─────────╮\n"
            f"  │\n"
            f"  │  📅 <b>{datetime.now().strftime('%d %b %Y')}</b>  •  "
            f"🕐 {datetime.now().strftime('%H:%M')}\n"
            f"  │  📈 <i>Real-time bot overview</i>\n"
            f"  │\n"
            f"  ├──────────────  👥 USER OVERVIEW  ─────────────┤\n"
            f"  │\n"
            f"  │  👥  <b>Users</b>       <code>{users}</code>\n"
            f"  │      Active users\n"
            f"  │\n"
            f"  │  💎  <b>VIP</b>         <code>{vip}</code>\n"
            f"  │      VIP members\n"
            f"  │\n"
            f"  │  ⏳  <b>Pending</b>     <code>{pending}</code>\n"
            f"  │      Waiting requests\n"
            f"  │\n"
            f"  │  🚫  <b>Banned</b>      <code>{banned}</code>\n"
            f"  │      Blocked users\n"
            f"  │\n"
            f"  ├──────────────  ⚡ BOT ACTIVITY  ─────────────┤\n"
            f"  │\n"
            f"  │  ⚡  <b>Actions</b>     <code>{actions}</code>\n"
            f"  │  🔓  <b>Unlocks</b>     <code>{unlocks}</code>\n"
            f"  │  🔐  <b>Logins</b>      <code>{logins}</code>\n"
            f"  │\n"
            f"  ├───────────────  📅 TODAY  ────────────────┤\n"
            f"  │\n"
            f"  │  ⚡ Actions   <code>{today_actions}</code>\n"
            f"  │  🔓 Unlocks   <code>{today_unlocks}</code>\n"
            f"  │  🔐 Logins    <code>{today_logins}</code>\n"
            f"  │\n"
            f"  ╰─────────────────────────────────────────╯"
        )

    @staticmethod
    def request_to_admin(name, username, uid, request_time=None):
        # Gunakan waktu yang tersimpan saat request dibuat agar "Tanggal Request"
        # tetap menunjukkan waktu request sebenarnya, bukan waktu admin membuka pesan.
        if request_time:
            try:
                dt = datetime.fromisoformat(request_time)
            except Exception:
                dt = datetime.now()
        else:
            dt = datetime.now()

        request_date = dt.strftime("%d %b %Y")
        request_clock = dt.strftime("%I:%M %p")

        return (
            f"{B}\n"
            f"  🔔  <b>𝗡𝗘𝗪 𝗥𝗘𝗤𝗨𝗘𝗦𝗧</b>\n"
            f"{B}\n\n"
            f"  👤 <b>USER INFORMATION</b>\n"
            f"  ├─ Name\n"
            f"  │  {name}\n"
            f"  └─ Username\n"
            f"     @{username or 'N/A'}\n\n"
            f"  🆔 <b>USER ID</b>\n"
            f"     <code>{uid}</code>\n\n"
            f"  📅 <b>TANGGAL REQUEST</b>\n"
            f"     {request_date}\n"
            f"     🕐 {request_clock}\n\n"
            f"  ━━━━━━━━━━━━━━━━━━━━━\n"
            f"  ⚡ <b>Select action:</b>"
        )


# ═══════════════════════════════════════════
#  ⌨️  KEYBOARDS
# ═══════════════════════════════════════════

class K:
    @staticmethod
    def language():
        return language_keyboard()

    @staticmethod
    def no_access(uid=0):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🔑 {tr(uid, 'request')}", callback_data="send_request")],
            [InlineKeyboardButton(text=f"💬 {tr(uid, 'contact')}", callback_data="msg_admin")],
        ])

    @staticmethod
    def after_request():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Check Status",  callback_data="check_status")],
            [InlineKeyboardButton(text="💬 Contact Admin", callback_data="msg_admin")],
        ])

    @staticmethod
    def login():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Sign In", callback_data="login")],
        ])

    @staticmethod
    def cancel():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✗ Cancel", callback_data="cancel")],
        ])

    @staticmethod
    def home(uid=0):
        rows = [
            [InlineKeyboardButton(text="💰 " + tr(uid, "money"),   callback_data="menu_money"),
             InlineKeyboardButton(text="🪙 " + tr(uid, "coins"),   callback_data="menu_coins")],
            [InlineKeyboardButton(text="⚡ " + tr(uid, "features"),callback_data="menu_feat"),
             InlineKeyboardButton(text="🔧 " + tr(uid, "settings"),callback_data="menu_set")],
            [InlineKeyboardButton(text="🔄 " + tr(uid, "refresh"), callback_data="refresh")],
        ]
        if has_admin(uid,"moderator"):
            rows.append([InlineKeyboardButton(text="👑 " + tr(uid, "admin"), callback_data="admin_menu")])
        rows.append([InlineKeyboardButton(text="🚪 " + tr(uid, "logout"), callback_data="logout")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def money():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="$1M",   callback_data="m_1000000"),
             InlineKeyboardButton(text="$5M",   callback_data="m_5000000"),
             InlineKeyboardButton(text="$10M",  callback_data="m_10000000")],
            [InlineKeyboardButton(text="$25M",  callback_data="m_25000000"),
             InlineKeyboardButton(text="$50M ★",callback_data="m_50000000")],
            [InlineKeyboardButton(text="✏ Custom Amount", callback_data="m_custom")],
            [InlineKeyboardButton(text="◂ Back", callback_data="back_home")],
        ])

    @staticmethod
    def coins():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="100K",   callback_data="c_100000"),
             InlineKeyboardButton(text="250K",   callback_data="c_250000"),
             InlineKeyboardButton(text="500K ★", callback_data="c_500000")],
            [InlineKeyboardButton(text="✏ Custom Amount", callback_data="c_custom")],
            [InlineKeyboardButton(text="◂ Back", callback_data="back_home")],
        ])

    @staticmethod
    def feat(uid=0):
        # Tampilkan status fitur per akun berdasarkan unlock yang berhasil.
        # Status tersimpan per user sehingga tetap terlihat setelah kembali ke menu.
        status = STORE.get("feature_status", {}).get(str(uid), {})

        def btn(icon, label, key):
            if status.get(key, False):
                text = f"✅  {label}  • TERBUKA"
            else:
                text = f"🔒  {label}  • TERKUNCI"
            return InlineKeyboardButton(text=text, callback_data=key)

        active = sum(1 for key in FEAT_MAP if status.get(key, False))
        return InlineKeyboardMarkup(inline_keyboard=[
            [btn("🚗", "W16 ENGINE", "f_w16"),
             btn("📣", "HORNS", "f_horns")],
            [btn("🛡", "NO DAMAGE", "f_damage"),
             btn("⛽", "UNLIMITED FUEL", "f_fuel")],
            [btn("💨", "SMOKE", "f_smoke"),
             btn("🎭", "ANIMATIONS", "f_anims")],
            [btn("🛞", "WHEELS", "f_wheels"),
             btn("🏠", "HOUSES", "f_houses")],
            [btn("🎮", "ALL LEVELS", "f_levels"),
             btn("🏅", "MAX RANK", "f_rank")],
            [btn("💡", "HEADLIGHTS", "f_headlights"),
             btn("👕", "ALL CLOTHES", "f_clothes")],
            [InlineKeyboardButton(
                text=("✅  🚗 UNLOCK CARS  • TERBUKA"
                      if status.get("f_unlock_cars", False)
                      else "🔒  🚗 UNLOCK CARS  • TERKUNCI"),
                callback_data="f_unlock_cars"
            )],
            [InlineKeyboardButton(
                text=f"🚀  ✦ UNLOCK ALL FEATURES ✦  [{active}/{len(FEAT_MAP)}]",
                callback_data="f_all")],
            [InlineKeyboardButton(text="◂  BACK TO DASHBOARD", callback_data="back_home")],
        ])

    @staticmethod
    def sett():
        # Settings layout dibuat mengikuti referensi screenshot:
        # 2 kolom untuk aksi utama, lalu tombol full-width untuk aksi penting.
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐  LANGUAGE", callback_data="change_language"),
             InlineKeyboardButton(text="✏️  CHANGE NAME", callback_data="s_name"),
             InlineKeyboardButton(text="🆔  PLAYER ID", callback_data="s_pid")],
            [InlineKeyboardButton(text="📧  CHANGE EMAIL", callback_data="s_email"),
             InlineKeyboardButton(text="🔐  CHANGE PASSWORD", callback_data="s_password")],
            [InlineKeyboardButton(text="🏆  WINS", callback_data="s_wins"),
             InlineKeyboardButton(text="😞  LOSSES", callback_data="s_loses")],
            [InlineKeyboardButton(text="👥  CLONE ACCOUNT", callback_data="s_clone")],
            [InlineKeyboardButton(text="🔧  FIX ACCOUNT BUGS", callback_data="s_fix")],
            [InlineKeyboardButton(text="◂  BACK TO DASHBOARD", callback_data="back_home")],
        ])

    @staticmethod
    def admin(uid):
        lvl = admin_level(uid)
        b   = []
        if lvl >= 5:
            b.append([
                InlineKeyboardButton(text="📊 Stats", callback_data="a_stats"),
                InlineKeyboardButton(text="👥 User Roles", callback_data="a_users"),
            ])
            b.append([InlineKeyboardButton(text="🚫 Banned Users", callback_data="a_banned")])
            b.append([InlineKeyboardButton(text="📋 Activity Log", callback_data="a_log")])
        if lvl >= 10:
            b.append([InlineKeyboardButton(text="⏳ Pending Requests", callback_data="a_pend")])
            b.append([
                InlineKeyboardButton(text="➕ Add",   callback_data="a_adduser"),
                InlineKeyboardButton(text="📥 Bulk Add", callback_data="a_bulkadd"),
                InlineKeyboardButton(text="🚫 Ban",   callback_data="a_ban"),
                InlineKeyboardButton(text="🔓 Unban", callback_data="a_unban"),
            ])
            b.append([
                InlineKeyboardButton(text="👢 Kick",    callback_data="a_kick"),
                InlineKeyboardButton(text="👢 Kick All", callback_data="a_kickall"),
                InlineKeyboardButton(text="⏰ Expiry",  callback_data="a_expiry"),
            ])
            b.append([
                InlineKeyboardButton(text="ℹ Profile", callback_data="a_profile"),
            ])
        if lvl >= 50:
            b.append([
                InlineKeyboardButton(text="💎 +VIP", callback_data="a_addvip"),
                InlineKeyboardButton(text="💎 -VIP", callback_data="a_rmvip"),
            ])
            b.append([InlineKeyboardButton(text="📢 Broadcast", callback_data="a_bcast_menu")])
        if lvl >= 100:
            b.append([
                InlineKeyboardButton(text="➕ Add Admin", callback_data="a_addadm"),
                InlineKeyboardButton(text="➖ Rem Admin", callback_data="a_rmadm"),
            ])
            b.append([
                InlineKeyboardButton(text="🖼 Update Photo",    callback_data="a_photo"),
                InlineKeyboardButton(text="🔧 Maintenance",    callback_data="a_maint"),
            ])
            b.append([InlineKeyboardButton(text="🔄 Reset Stats", callback_data="a_reset")])
        b.append([InlineKeyboardButton(text="◂ Home", callback_data="back_home")])
        return InlineKeyboardMarkup(inline_keyboard=b)

    @staticmethod
    def expiry_options(uid):
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 1 Day", callback_data=f"expiry_set_1_{uid}"),
                InlineKeyboardButton(text="🔵 7 Days", callback_data=f"expiry_set_7_{uid}"),
            ],
            [
                InlineKeyboardButton(text="🟣 14 Days", callback_data=f"expiry_set_14_{uid}"),
                InlineKeyboardButton(text="🟡 30 Days", callback_data=f"expiry_set_30_{uid}"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Custom Time", callback_data=f"expiry_custom_{uid}"),
            ],
            [
                InlineKeyboardButton(text="♾️ Remove Expiry", callback_data=f"expiry_remove_{uid}"),
            ],
            [
                InlineKeyboardButton(text="◂ Back", callback_data="admin_menu"),
            ],
        ])

    @staticmethod
    def request_actions(uid):
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Accept", callback_data=f"rq_accept_{uid}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"rq_reject_{uid}"),
            InlineKeyboardButton(text="🚫 Ban",    callback_data=f"rq_ban_{uid}"),
        ]])

    @staticmethod
    def accept_duration_options(uid):
        """Pilih durasi akses setelah admin menekan Accept."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 1 Day", callback_data=f"rq_duration_1_{uid}"),
                InlineKeyboardButton(text="🔵 7 Days", callback_data=f"rq_duration_7_{uid}"),
            ],
            [
                InlineKeyboardButton(text="🟣 14 Days", callback_data=f"rq_duration_14_{uid}"),
                InlineKeyboardButton(text="🟡 30 Days", callback_data=f"rq_duration_30_{uid}"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Custom Time", callback_data=f"rq_duration_custom_{uid}"),
            ],
            [
                InlineKeyboardButton(text="↩️ Back", callback_data=f"rq_duration_back_{uid}"),
            ],
        ])

    @staticmethod
    def broadcast_menu():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Text Message",    callback_data="bcast_text")],
            [InlineKeyboardButton(text="🖼 Photo + Caption", callback_data="bcast_photo")],
            [InlineKeyboardButton(text="💎 VIP Only",        callback_data="bcast_vip")],
            [InlineKeyboardButton(text="◂ Back",             callback_data="admin_menu")],
        ])

    @staticmethod
    def banned_list(page=0):
        banned = sorted(set(int(x) for x in BANNED))
        per_page = 15
        pages = max(1, (len(banned) + per_page - 1) // per_page)
        page = max(0, min(page, pages - 1))
        members = banned[page * per_page:(page + 1) * per_page]

        b = []
        for uid in members:
            info = STORE.get("users", {}).get(str(uid), {})
            name = str(info.get("name", f"User {uid}"))[:18]
            b.append([
                InlineKeyboardButton(text=f"🔓 {name}", callback_data=f"a_unban_{uid}")
            ])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"a_banned_page_{page-1}"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"a_banned_page_{page+1}"))
        if nav:
            b.append(nav)

        b.append([InlineKeyboardButton(text="◂ Admin Panel", callback_data="admin_menu")])
        return InlineKeyboardMarkup(inline_keyboard=b)

    @staticmethod
    def back_admin():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◂ Admin Panel", callback_data="admin_menu")],
        ])

    @staticmethod
    def back_home():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◂ Home", callback_data="back_home")],
        ])

    @staticmethod
    def confirm_logout():
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✔ Yes", callback_data="do_logout"),
            InlineKeyboardButton(text="✗ No",  callback_data="back_home"),
        ]])

    @staticmethod
    def pending_list():
        b = []
        for uid_str, info in list(PENDING.items())[:15]:
            uid_int = int(uid_str)
            name    = info.get("name",f"User {uid_int}")[:16]
            b.append([
                InlineKeyboardButton(text=f"✅ {name}", callback_data=f"rq_accept_{uid_int}"),
                InlineKeyboardButton(text="❌",          callback_data=f"rq_reject_{uid_int}"),
                InlineKeyboardButton(text="🚫",          callback_data=f"rq_ban_{uid_int}"),
            ])
        b.append([InlineKeyboardButton(text="◂ Back", callback_data="admin_menu")])
        return InlineKeyboardMarkup(inline_keyboard=b)


# ═══════════════════════════════════════════
#  📋 FSM STATES
# ═══════════════════════════════════════════

class SLogin(StatesGroup):
    email    = State()
    password = State()

class SMoney(StatesGroup):
    amount = State()

class SCoins(StatesGroup):
    amount = State()

class SName(StatesGroup):
    name = State()

class SPID(StatesGroup):
    pid = State()

class SWins(StatesGroup):
    val = State()

class SLoses(StatesGroup):
    val = State()

class SChangeEmail(StatesGroup):
    email = State()

class SChangePassword(StatesGroup):
    password = State()

class SClone(StatesGroup):
    source_email = State()
    source_pass  = State()
    target_email = State()
    target_pass  = State()

class SUnlockCars(StatesGroup):
    source_email = State()
    source_pass  = State()

class SAdmin(StatesGroup):
    ban             = State()
    unban           = State()
    adduser         = State()
    bulkadd         = State()
    addadm_id       = State()
    addadm_lv       = State()
    rmadm           = State()
    kick            = State()
    expiry_id       = State()
    expiry_dy       = State()
    addvip          = State()
    rmvip           = State()
    profile_id      = State()
    bcast_text      = State()
    bcast_photo     = State()
    bcast_photo_cap = State()
    upload_photo    = State()



# ═══════════════════════════════════════════
# 🌐 MANUAL 4-LANGUAGE TRANSLATION ENGINE — ADMIN + FEATURES
# ═══════════════════════════════════════════
# This version intentionally does NOT call Google Translate.
# UI phrases are translated from a local manual dictionary.
# Dynamic values (IDs, names, emails, URLs, game values) are preserved.

_TRANSLATION_ACTIVE = contextvars.ContextVar("manual_translation_active", default=False)

# Common UI phrases used by ACCESS, FEATURES, SETTINGS and ADMIN handlers.
# Keys are the literal phrases that occur in the source UI.
MANUAL_UI = {
 "id": {
  "Invalid language.":"Bahasa tidak valid.", "Failed to save language.":"Gagal menyimpan bahasa.", "Language:":"Bahasa:",
  "Loading...":"Memuat...", "Language selected":"Bahasa dipilih", "LANGUAGE SELECTED":"BAHASA DIPILIH",
  "Already approved!":"Sudah disetujui!", "No permission":"Tidak memiliki izin", "Approved!":"Disetujui!",
  "Request declined.":"Permintaan ditolak.", "REJECTED":"DITOLAK", "Rejected":"Ditolak", "Banned":"Diblokir",
  "No access!":"Tidak memiliki akses!", "No pending requests.":"Tidak ada permintaan yang menunggu.", "pending:":"menunggu:",
  "Enter user ID:":"Masukkan User ID:", "Invalid user ID.":"User ID tidak valid.", "Invalid ID.":"ID tidak valid.",
  "User not found.":"User tidak ditemukan.", "User tersebut sudah tidak diban.":"User tersebut sudah tidak diblokir.",
  "berhasil di-unban.":"berhasil dibuka blokirnya.", "No admin access.":"Tidak memiliki akses admin.",
  "No admin permission.":"Tidak memiliki izin admin.", "Owner only!":"Khusus Owner!", "Admin only!":"Khusus Admin!",
  "Cannot ban owner!":"Tidak dapat memblokir Owner!", "Cannot kick owner!":"Tidak dapat mengeluarkan Owner!",
  "Cannot remove owner!":"Tidak dapat menghapus Owner!", "Access removed.":"Akses dihapus.",
  "No users to kick.":"Tidak ada user untuk dikeluarkan.", "users kicked.":"user dikeluarkan.",
  "Invalid expiry.":"Masa berlaku tidak valid.", "Durasi tidak tersedia.":"Durasi tidak tersedia.",
  "day expiry set.":"hari masa berlaku ditetapkan.", "Masukkan jumlah hari yang valid, contoh: 45.":"Masukkan jumlah hari yang valid, contoh: 45.",
  "User ID tidak ditemukan.":"User ID tidak ditemukan.", "Expiry removed.":"Masa berlaku dihapus.",
  "You are now VIP!":"Anda sekarang VIP!", "VIP removed for":"VIP dihapus untuk", "added!":"ditambahkan!", "banned!":"diblokir!", "unbanned!":"dibuka blokirnya!", "kicked!":"dikeluarkan!",
  "UPDATE BOT PHOTO":"PERBARUI FOTO BOT", "Current photo is set.":"Foto saat ini sudah terpasang.", "Send a new photo to update it.":"Kirim foto baru untuk memperbaruinya.", "This photo shows on welcome screen.":"Foto ini akan tampil di layar sambutan.",
  "PHOTO UPDATED":"FOTO DIPERBARUI", "Bot welcome photo updated!":"Foto sambutan bot berhasil diperbarui!", "It will show for new users.":"Foto akan tampil untuk user baru.",
  "BROADCAST":"BROADCAST", "Message to all":"Pesan untuk semua", "Message to":"Pesan untuk", "VIPs:":"VIP:", "Send a photo:":"Kirim foto:",
  "Photo received!":"Foto diterima!", "Type caption:":"Ketik caption:", "URL set!":"URL ditetapkan!", "Done!":"Selesai!", "sent":"terkirim", "failed":"gagal",
  "ADD ADMIN":"TAMBAH ADMIN", "REM ADMIN":"HAPUS ADMIN", "Select role for":"Pilih role untuk", "Moderator":"Moderator", "Admin":"Admin", "Super Admin":"Super Admin", "Use /admin":"Gunakan /admin",
  "demoted!":"diturunkan rolenya!", "Maintenance:":"Maintenance:", "Stats reset!":"Statistik direset!",
  "SIGN OUT":"KELUAR", "Are you sure?":"Apakah Anda yakin?", "SIGNED OUT":"BERHASIL KELUAR", "Successfully signed out.":"Berhasil keluar.",
  "Sign in first!":"Masuk terlebih dahulu!", "Wait":"Tunggu", "Max:":"Maks:", "Enter amount":"Masukkan jumlah", "Setting":"Mengatur", "coins":"koin", "Enter 1":"Masukkan 1", "Cancelled":"Dibatalkan",
  "Loading account & applying":"Memuat akun dan menerapkan", "UNLOCKING ALL":"MEMBUKA SEMUA", "Loading account...":"Memuat akun...", "COMPLETE":"SELESAI",
  "CHANGE NAME":"UBAH NAMA", "Enter new name:":"Masukkan nama baru:", "characters.":"karakter.", "Setting name...":"Mengatur nama...",
  "PLAYER ID":"PLAYER ID", "Enter new Player ID:":"Masukkan Player ID baru:", "Setting ID...":"Mengatur ID...",
  "SET WINS":"ATUR MENANG", "Enter win count:":"Masukkan jumlah kemenangan:", "Invalid number.":"Angka tidak valid.", "Setting wins...":"Mengatur kemenangan...",
  "SET LOSSES":"ATUR KALAH", "Enter loss count:":"Masukkan jumlah kekalahan:", "Setting loses...":"Mengatur kekalahan...",
  "CHANGE EMAIL":"UBAH EMAIL", "Enter new CPM email:":"Masukkan email CPM baru:", "Updating email...":"Memperbarui email...",
  "CHANGE PASSWORD":"UBAH PASSWORD", "Enter new password (minimum 6 characters):":"Masukkan password baru (minimal 6 karakter):", "Password must be 6-256 characters.":"Password harus 6-256 karakter.", "Updating password...":"Memperbarui password...",
  "CLONE ACCOUNT":"KLONING AKUN", "Send SOURCE email:":"Kirim email SUMBER:", "Send SOURCE password:":"Kirim password SUMBER:", "Send TARGET email:":"Kirim email TARGET:", "Send TARGET password:":"Kirim password TARGET:", "Logging into source...":"Login ke akun sumber...", "Loading & fixing account...":"Memuat dan memperbaiki akun...",
  "Invalid expiry":"Masa berlaku tidak valid", "Features":"Fitur", "Feature":"Fitur", "FEATURES BOT MASKY":"FITUR BOT MASKY", "PREMIUM FEATURE CENTER":"PUSAT FITUR PREMIUM", "Features Available":"Fitur Tersedia", "Fast & Easy Unlock":"Buka dengan Cepat & Mudah", "Account Protection Active":"Perlindungan Akun Aktif", "STATUS FITUR DALAM AKUN CPM":"STATUS FITUR AKUN CPM", "TELAH TERBUKA":"TELAH TERBUKA", "BELUM TERBUKA":"BELUM TERBUKA", "Belum ada fitur yang terbuka":"Belum ada fitur yang terbuka", "Semua fitur sudah terbuka":"Semua fitur sudah terbuka", "SELECT A FEATURE":"PILIH FITUR", "Choose an option below or use":"Pilih opsi di bawah atau gunakan", "UNLOCK ALL FEATURES":"BUKA SEMUA FITUR", "at once.":"sekaligus.",
  "W16 Engine":"Mesin W16", "Horns":"Klakson", "No Damage":"Tanpa Kerusakan", "Unlimited Fuel":"Bahan Bakar Tak Terbatas", "Smoke":"Asap", "Animations":"Animasi", "Wheels":"Roda", "Houses":"Rumah", "All Levels":"Semua Level", "Max Rank":"Rank Maksimal", "Headlights":"Lampu Depan", "All Clothes":"Semua Pakaian", "W16 ENGINE":"MESIN W16", "HORNS":"KLAKSON", "NO DAMAGE":"TANPA KERUSAKAN", "UNLIMITED FUEL":"BAHAN BAKAR TAK TERBATAS", "SMOKE":"ASAP", "ANIMATIONS":"ANIMASI", "WHEELS":"RODA", "HOUSES":"RUMAH", "ALL LEVELS":"SEMUA LEVEL", "MAX RANK":"RANK MAKSIMAL", "HEADLIGHTS":"LAMPU DEPAN", "ALL CLOTHES":"SEMUA PAKAIAN", "TERBUKA":"TERBUKA", "TERKUNCI":"TERKUNCI",
  "Admin Panel":"Panel Admin", "ADMIN PANEL":"PANEL ADMIN", "STATS":"STATISTIK", "Stats":"Statistik", "Statistics":"Statistik", "STATISTICS":"STATISTIK", "USER ROLES":"PERAN USER", "User Roles":"Peran User", "Banned Users":"User Diblokir", "Activity Log":"Log Aktivitas", "Pending Requests":"Permintaan Menunggu", "Add":"Tambah", "Bulk Add":"Tambah Massal", "Ban":"Blokir", "Unban":"Buka Blokir", "Kick":"Keluarkan", "Kick All":"Keluarkan Semua", "Expiry":"Masa Berlaku", "Profile":"Profil", "Broadcast":"Broadcast", "Add Admin":"Tambah Admin", "Rem Admin":"Hapus Admin", "Update Photo":"Perbarui Foto", "Maintenance":"Maintenance", "Reset Stats":"Reset Statistik", "Home":"Beranda",
  "1 Day":"1 Hari", "7 Days":"7 Hari", "14 Days":"14 Hari", "30 Days":"30 Hari", "Custom Day":"Hari Kustom", "Remove Expiry":"Hapus Masa Berlaku", "Accept":"Terima", "Reject":"Tolak", "Text Message":"Pesan Teks", "Photo + Caption":"Foto + Caption", "VIP Only":"Khusus VIP", "Prev":"Sebelumnya", "Next":"Berikutnya", "Back":"Kembali", "Cancel":"Batal", "Yes":"Ya", "No":"Tidak", "User":"User", "Users":"User", "Pending":"Menunggu", "Banned":"Diblokir", "VIP":"VIP", "Admins":"Admin",
  "USER BIASA":"USER BIASA", "USER VIP":"USER VIP", "USER ADMIN":"USER ADMIN", "Tidak VIP / bukan admin":"Tidak VIP / bukan admin", "Akses VIP":"Akses VIP", "Akses admin":"Akses admin", "Setiap user hanya ditampilkan pada 1 role.":"Setiap user hanya ditampilkan pada 1 role.", "Tidak ada user":"Tidak ada user", "Total Users":"Total User", "User lainnya":"user lainnya", "Real-time bot overview":"Ringkasan bot real-time", "Active users":"User aktif", "VIP members":"Member VIP", "Waiting requests":"Permintaan menunggu", "Blocked users":"User diblokir", "Bot Activity":"Aktivitas Bot", "Actions":"Aksi", "Logins":"Login", "Unlocks":"Unlock", "Today":"Hari ini", "Total":"Total",
 },
 "en": {
  "Bahasa tidak valid.":"Invalid language.", "Gagal menyimpan bahasa.":"Failed to save language.", "Bahasa dipilih":"Language selected", "Memuat...":"Loading...", "Sudah disetujui!":"Already approved!", "Tidak memiliki izin":"No permission", "Disetujui!":"Approved!", "Permintaan ditolak.":"Request declined.", "DITOLAK":"REJECTED", "Ditolak":"Rejected", "Diblokir":"Banned", "Tidak memiliki akses!":"No access!", "Tidak ada permintaan yang menunggu.":"No pending requests.", "menunggu:":"pending:", "Masukkan User ID:":"Enter user ID:", "ID tidak valid.":"Invalid ID.", "User tidak ditemukan.":"User not found.", "Tidak memiliki akses admin.":"No admin access.", "Khusus Owner!":"Owner only!", "Khusus Admin!":"Admin only!", "Tidak dapat memblokir Owner!":"Cannot ban owner!", "Tidak dapat mengeluarkan Owner!":"Cannot kick owner!", "Tidak dapat menghapus Owner!":"Cannot remove owner!", "Akses dihapus.":"Access removed.", "Tidak ada user untuk dikeluarkan.":"No users to kick.", "Masa berlaku tidak valid.":"Invalid expiry.", "Anda sekarang VIP!":"You are now VIP!", "diblokir!":"banned!", "dibuka blokirnya!":"unbanned!", "dikeluarkan!":"kicked!", "Selesai!":"Done!", "gagal":"failed", "BERHASIL KELUAR":"SIGNED OUT", "Apakah Anda yakin?":"Are you sure?", "Berhasil keluar.":"Successfully signed out.", "Masuk terlebih dahulu!":"Sign in first!", "Tunggu":"Wait", "Maks:":"Max:", "Masukkan jumlah":"Enter amount", "Mengatur":"Setting", "koin":"coins", "Dibatalkan":"Cancelled", "Memuat akun dan menerapkan":"Loading account & applying", "MEMBUKA SEMUA":"UNLOCKING ALL", "Memuat akun...":"Loading account...", "SELESAI":"COMPLETE", "UBAH NAMA":"CHANGE NAME", "Masukkan nama baru:":"Enter new name:", "karakter.":"characters.", "Mengatur nama...":"Setting name...", "Masukkan Player ID baru:":"Enter new Player ID:", "Mengatur ID...":"Setting ID...", "ATUR MENANG":"SET WINS", "Masukkan jumlah kemenangan:":"Enter win count:", "Angka tidak valid.":"Invalid number.", "Mengatur kemenangan...":"Setting wins...", "ATUR KALAH":"SET LOSSES", "Masukkan jumlah kekalahan:":"Enter loss count:", "Mengatur kekalahan...":"Setting loses...", "UBAH EMAIL":"CHANGE EMAIL", "Masukkan email CPM baru:":"Enter new CPM email:", "Memperbarui email...":"Updating email...", "UBAH PASSWORD":"CHANGE PASSWORD", "Masukkan password baru (minimal 6 karakter):":"Enter new password (minimum 6 characters):", "Memperbarui password...":"Updating password...", "KLONING AKUN":"CLONE ACCOUNT", "Kirim email SUMBER:":"Send SOURCE email:", "Kirim password SUMBER:":"Send SOURCE password:", "Kirim email TARGET:":"Send TARGET email:", "Kirim password TARGET:":"Send TARGET password:", "Login ke akun sumber...":"Logging into source...", "Memuat dan memperbaiki akun...":"Loading & fixing account...", "Fitur":"Features", "PUSAT FITUR PREMIUM":"PREMIUM FEATURE CENTER", "Fitur Tersedia":"Features Available", "Buka dengan Cepat & Mudah":"Fast & Easy Unlock", "Perlindungan Akun Aktif":"Account Protection Active", "STATUS FITUR AKUN CPM":"CPM ACCOUNT FEATURE STATUS", "PILIH FITUR":"SELECT A FEATURE", "Pilih opsi di bawah atau gunakan":"Choose an option below or use", "BUKA SEMUA FITUR":"UNLOCK ALL FEATURES", "sekaligus.":"at once.", "Mesin W16":"W16 Engine", "Klakson":"Horns", "Tanpa Kerusakan":"No Damage", "Bahan Bakar Tak Terbatas":"Unlimited Fuel", "Asap":"Smoke", "Animasi":"Animations", "Roda":"Wheels", "Rumah":"Houses", "Semua Level":"All Levels", "Rank Maksimal":"Max Rank", "Lampu Depan":"Headlights", "Semua Pakaian":"All Clothes", "Panel Admin":"Admin Panel", "PERAN USER":"USER ROLES", "Peran User":"User Roles", "User Diblokir":"Banned Users", "Log Aktivitas":"Activity Log", "Permintaan Menunggu":"Pending Requests", "Tambah":"Add", "Tambah Massal":"Bulk Add", "Blokir":"Ban", "Buka Blokir":"Unban", "Keluarkan":"Kick", "Keluarkan Semua":"Kick All", "Masa Berlaku":"Expiry", "Profil":"Profile", "Perbarui Foto":"Update Photo", "Reset Statistik":"Reset Stats", "Beranda":"Home", "1 Hari":"1 Day", "7 Hari":"7 Days", "14 Hari":"14 Days", "30 Hari":"30 Days", "Hari Kustom":"Custom Day", "Hapus Masa Berlaku":"Remove Expiry", "Terima":"Accept", "Tolak":"Reject", "Pesan Teks":"Text Message", "Khusus VIP":"VIP Only", "Sebelumnya":"Prev", "Berikutnya":"Next", "Kembali":"Back", "Batal":"Cancel", "Ya":"Yes", "Tidak":"No", "Total User":"Total Users", "user lainnya":"other users", "Ringkasan bot real-time":"Real-time bot overview", "User aktif":"Active users", "Member VIP":"VIP members", "Aktivitas Bot":"Bot Activity", "Aksi":"Actions", "Hari ini":"Today",
 },
 "ru": {
  "Invalid language.":"Неверный язык.", "Failed to save language.":"Не удалось сохранить язык.", "Language selected":"Язык выбран", "Loading...":"Загрузка...", "Already approved!":"Уже одобрено!", "No permission":"Нет разрешения", "Approved!":"Одобрено!", "Request declined.":"Запрос отклонён.", "REJECTED":"ОТКЛОНЕНО", "Rejected":"Отклонено", "Banned":"Заблокирован", "No access!":"Нет доступа!", "No pending requests.":"Нет ожидающих запросов.", "pending:":"ожидает:", "Enter user ID:":"Введите ID пользователя:", "Invalid ID.":"Неверный ID.", "User not found.":"Пользователь не найден.", "No admin access.":"Нет доступа администратора.", "Owner only!":"Только владелец!", "Admin only!":"Только администратор!", "Cannot ban owner!":"Нельзя заблокировать владельца!", "Cannot kick owner!":"Нельзя исключить владельца!", "Cannot remove owner!":"Нельзя удалить владельца!", "Access removed.":"Доступ удалён.", "No users to kick.":"Нет пользователей для исключения.", "Invalid expiry.":"Неверный срок действия.", "You are now VIP!":"Теперь вы VIP!", "Done!":"Готово!", "failed":"ошибка", "SIGNED OUT":"ВЫШЕЛ ИЗ АККАУНТА", "Are you sure?":"Вы уверены?", "Successfully signed out.":"Вы успешно вышли.", "Sign in first!":"Сначала войдите!", "Wait":"Подождите", "Max:":"Макс.:", "Enter amount":"Введите сумму", "Setting":"Установка", "coins":"монет", "Cancelled":"Отменено", "Loading account & applying":"Загрузка аккаунта и применение", "UNLOCKING ALL":"ОТКРЫТИЕ ВСЕХ", "Loading account...":"Загрузка аккаунта...", "COMPLETE":"ЗАВЕРШЕНО", "CHANGE NAME":"ИЗМЕНИТЬ ИМЯ", "Enter new name:":"Введите новое имя:", "characters.":"символов.", "Setting name...":"Установка имени...", "PLAYER ID":"ID ИГРОКА", "Enter new Player ID:":"Введите новый ID игрока:", "Setting ID...":"Установка ID...", "SET WINS":"УСТАНОВИТЬ ПОБЕДЫ", "Enter win count:":"Введите количество побед:", "Invalid number.":"Неверное число.", "Setting wins...":"Установка побед...", "SET LOSSES":"УСТАНОВИТЬ ПОРАЖЕНИЯ", "Enter loss count:":"Введите количество поражений:", "Setting loses...":"Установка поражений...", "CHANGE EMAIL":"ИЗМЕНИТЬ EMAIL", "Enter new CPM email:":"Введите новый email CPM:", "Updating email...":"Обновление email...", "CHANGE PASSWORD":"ИЗМЕНИТЬ ПАРОЛЬ", "Enter new password (minimum 6 characters):":"Введите новый пароль (минимум 6 символов):", "Updating password...":"Обновление пароля...", "CLONE ACCOUNT":"КЛОНИРОВАТЬ АККАУНТ", "Send SOURCE email:":"Введите email ИСТОЧНИКА:", "Send SOURCE password:":"Введите пароль ИСТОЧНИКА:", "Send TARGET email:":"Введите email ЦЕЛИ:", "Send TARGET password:":"Введите пароль ЦЕЛИ:", "Logging into source...":"Вход в исходный аккаунт...", "Loading & fixing account...":"Загрузка и исправление аккаунта...", "Features":"Функции", "FEATURES BOT MASKY":"ФУНКЦИИ БОТА MASKY", "PREMIUM FEATURE CENTER":"ПРЕМИУМ-ЦЕНТР ФУНКЦИЙ", "Features Available":"Доступные функции", "Fast & Easy Unlock":"Быстрая и простая разблокировка", "Account Protection Active":"Защита аккаунта активна", "STATUS FITUR DALAM AKUN CPM":"СТАТУС ФУНКЦИЙ АККАУНТА CPM", "TELAH TERBUKA":"ОТКРЫТЫ", "BELUM TERBUKA":"ЗАБЛОКИРОВАНЫ", "Belum ada fitur yang terbuka":"Нет открытых функций", "Semua fitur sudah terbuka":"Все функции уже открыты", "SELECT A FEATURE":"ВЫБЕРИТЕ ФУНКЦИЮ", "Choose an option below or use":"Выберите вариант ниже или используйте", "UNLOCK ALL FEATURES":"ОТКРЫТЬ ВСЕ ФУНКЦИИ", "at once.":"сразу.", "W16 Engine":"Двигатель W16", "Horns":"Клаксон", "No Damage":"Без урона", "Unlimited Fuel":"Бесконечное топливо", "Smoke":"Дым", "Animations":"Анимации", "Wheels":"Колёса", "Houses":"Дома", "All Levels":"Все уровни", "Max Rank":"Максимальный ранг", "Headlights":"Фары", "All Clothes":"Вся одежда", "W16 ENGINE":"ДВИГАТЕЛЬ W16", "HORNS":"КЛАКСОН", "NO DAMAGE":"БЕЗ УРОНА", "UNLIMITED FUEL":"БЕСКОНЕЧНОЕ ТОПЛИВО", "SMOKE":"ДЫМ", "ANIMATIONS":"АНИМАЦИИ", "WHEELS":"КОЛЁСА", "HOUSES":"ДОМА", "ALL LEVELS":"ВСЕ УРОВНИ", "MAX RANK":"МАКСИМАЛЬНЫЙ РАНГ", "HEADLIGHTS":"ФАРЫ", "ALL CLOTHES":"ВСЯ ОДЕЖДА", "TERBUKA":"ОТКРЫТО", "TERKUNCI":"ЗАБЛОКИРОВАНО", "Admin Panel":"Панель администратора", "ADMIN PANEL":"ПАНЕЛЬ АДМИНИСТРАТОРА", "Stats":"Статистика", "Statistics":"Статистика", "USER ROLES":"РОЛИ ПОЛЬЗОВАТЕЛЕЙ", "User Roles":"Роли пользователей", "Banned Users":"Заблокированные пользователи", "Activity Log":"Журнал активности", "Pending Requests":"Ожидающие запросы", "Add":"Добавить", "Bulk Add":"Массовое добавление", "Ban":"Заблокировать", "Unban":"Разблокировать", "Kick":"Исключить", "Kick All":"Исключить всех", "Expiry":"Срок действия", "Profile":"Профиль", "Broadcast":"Рассылка", "Add Admin":"Добавить администратора", "Rem Admin":"Удалить администратора", "Update Photo":"Обновить фото", "Maintenance":"Обслуживание", "Reset Stats":"Сбросить статистику", "Home":"Главная", "1 Day":"1 день", "7 Days":"7 дней", "14 Days":"14 дней", "30 Days":"30 дней", "Custom Day":"Свои дни", "Remove Expiry":"Удалить срок", "Accept":"Принять", "Reject":"Отклонить", "Text Message":"Текстовое сообщение", "Photo + Caption":"Фото + подпись", "VIP Only":"Только VIP", "Prev":"Назад", "Next":"Далее", "Back":"Назад", "Cancel":"Отмена", "Yes":"Да", "No":"Нет", "Total Users":"Всего пользователей", "Real-time bot overview":"Обзор бота в реальном времени", "Active users":"Активные пользователи", "VIP members":"VIP-участники", "Waiting requests":"Ожидающие запросы", "Blocked users":"Заблокированные пользователи", "Bot Activity":"Активность бота", "Actions":"Действия", "Logins":"Входы", "Unlocks":"Разблокировки", "Today":"Сегодня", "Total":"Всего",
 },
 "ar": {
  "Invalid language.":"اللغة غير صالحة.", "Failed to save language.":"تعذر حفظ اللغة.", "Language selected":"تم اختيار اللغة", "Loading...":"جارٍ التحميل...", "Already approved!":"تمت الموافقة بالفعل!", "No permission":"لا توجد صلاحية", "Approved!":"تمت الموافقة!", "Request declined.":"تم رفض الطلب.", "REJECTED":"مرفوض", "Rejected":"مرفوض", "Banned":"محظور", "No access!":"لا يوجد وصول!", "No pending requests.":"لا توجد طلبات معلقة.", "pending:":"معلق:", "Enter user ID:":"أدخل معرّف المستخدم:", "Invalid ID.":"المعرّف غير صالح.", "User not found.":"المستخدم غير موجود.", "No admin access.":"لا توجد صلاحية مسؤول.", "Owner only!":"للمالك فقط!", "Admin only!":"للمسؤول فقط!", "Cannot ban owner!":"لا يمكن حظر المالك!", "Cannot kick owner!":"لا يمكن طرد المالك!", "Cannot remove owner!":"لا يمكن إزالة المالك!", "Access removed.":"تمت إزالة الوصول.", "No users to kick.":"لا يوجد مستخدمون للطرد.", "Invalid expiry.":"انتهاء الصلاحية غير صالح.", "You are now VIP!":"أصبحت الآن VIP!", "Done!":"تم!", "failed":"فشل", "SIGNED OUT":"تم تسجيل الخروج", "Are you sure?":"هل أنت متأكد؟", "Successfully signed out.":"تم تسجيل الخروج بنجاح.", "Sign in first!":"سجّل الدخول أولاً!", "Wait":"انتظر", "Max:":"الحد الأقصى:", "Enter amount":"أدخل المبلغ", "Setting":"جارٍ الإعداد", "coins":"عملات", "Cancelled":"تم الإلغاء", "Loading account & applying":"جارٍ تحميل الحساب وتطبيق", "UNLOCKING ALL":"فتح الكل", "Loading account...":"جارٍ تحميل الحساب...", "COMPLETE":"اكتمل", "CHANGE NAME":"تغيير الاسم", "Enter new name:":"أدخل الاسم الجديد:", "characters.":"حرفاً.", "Setting name...":"جارٍ إعداد الاسم...", "PLAYER ID":"معرّف اللاعب", "Enter new Player ID:":"أدخل معرّف اللاعب الجديد:", "Setting ID...":"جارٍ إعداد المعرّف...", "SET WINS":"تعيين الانتصارات", "Enter win count:":"أدخل عدد الانتصارات:", "Invalid number.":"رقم غير صالح.", "Setting wins...":"جارٍ إعداد الانتصارات...", "SET LOSSES":"تعيين الخسائر", "Enter loss count:":"أدخل عدد الخسائر:", "Setting loses...":"جارٍ إعداد الخسائر...", "CHANGE EMAIL":"تغيير البريد الإلكتروني", "Enter new CPM email:":"أدخل بريد CPM الجديد:", "Updating email...":"جارٍ تحديث البريد...", "CHANGE PASSWORD":"تغيير كلمة المرور", "Enter new password (minimum 6 characters):":"أدخل كلمة المرور الجديدة (6 أحرف على الأقل):", "Updating password...":"جارٍ تحديث كلمة المرور...", "CLONE ACCOUNT":"نسخ الحساب", "Send SOURCE email:":"أرسل بريد المصدر:", "Send SOURCE password:":"أرسل كلمة مرور المصدر:", "Send TARGET email:":"أرسل بريد الهدف:", "Send TARGET password:":"أرسل كلمة مرور الهدف:", "Logging into source...":"جارٍ تسجيل الدخول إلى المصدر...", "Loading & fixing account...":"جارٍ تحميل وإصلاح الحساب...", "Features":"الميزات", "FEATURES BOT MASKY":"ميزات بوت MASKY", "PREMIUM FEATURE CENTER":"مركز الميزات المميزة", "Features Available":"الميزات المتاحة", "Fast & Easy Unlock":"فتح سريع وسهل", "Account Protection Active":"حماية الحساب مفعّلة", "STATUS FITUR DALAM AKUN CPM":"حالة ميزات حساب CPM", "TELAH TERBUKA":"مفتوحة", "BELUM TERBUKA":"مقفلة", "Belum ada fitur yang terbuka":"لا توجد ميزات مفتوحة", "Semua fitur sudah terbuka":"جميع الميزات مفتوحة بالفعل", "SELECT A FEATURE":"اختر ميزة", "Choose an option below or use":"اختر خياراً أدناه أو استخدم", "UNLOCK ALL FEATURES":"فتح جميع الميزات", "at once.":"دفعة واحدة.", "W16 Engine":"محرك W16", "Horns":"البوق", "No Damage":"بدون ضرر", "Unlimited Fuel":"وقود غير محدود", "Smoke":"دخان", "Animations":"الحركات", "Wheels":"العجلات", "Houses":"المنازل", "All Levels":"جميع المستويات", "Max Rank":"أعلى رتبة", "Headlights":"المصابيح الأمامية", "All Clothes":"جميع الملابس", "W16 ENGINE":"محرك W16", "HORNS":"البوق", "NO DAMAGE":"بدون ضرر", "UNLIMITED FUEL":"وقود غير محدود", "SMOKE":"دخان", "ANIMATIONS":"الحركات", "WHEELS":"العجلات", "HOUSES":"المنازل", "ALL LEVELS":"جميع المستويات", "MAX RANK":"أعلى رتبة", "HEADLIGHTS":"المصابيح الأمامية", "ALL CLOTHES":"جميع الملابس", "TERBUKA":"مفتوح", "TERKUNCI":"مقفل", "Admin Panel":"لوحة المسؤول", "ADMIN PANEL":"لوحة المسؤول", "Stats":"الإحصائيات", "Statistics":"الإحصائيات", "USER ROLES":"أدوار المستخدمين", "User Roles":"أدوار المستخدمين", "Banned Users":"المستخدمون المحظورون", "Activity Log":"سجل النشاط", "Pending Requests":"الطلبات المعلقة", "Add":"إضافة", "Bulk Add":"إضافة جماعية", "Ban":"حظر", "Unban":"إلغاء الحظر", "Kick":"طرد", "Kick All":"طرد الجميع", "Expiry":"انتهاء الصلاحية", "Profile":"الملف الشخصي", "Broadcast":"البث", "Add Admin":"إضافة مسؤول", "Rem Admin":"إزالة مسؤول", "Update Photo":"تحديث الصورة", "Maintenance":"الصيانة", "Reset Stats":"إعادة ضبط الإحصائيات", "Home":"الرئيسية", "1 Day":"يوم واحد", "7 Days":"7 أيام", "14 Days":"14 يوماً", "30 Days":"30 يوماً", "Custom Day":"مدة مخصصة", "Remove Expiry":"إزالة انتهاء الصلاحية", "Accept":"قبول", "Reject":"رفض", "Text Message":"رسالة نصية", "Photo + Caption":"صورة + وصف", "VIP Only":"VIP فقط", "Prev":"السابق", "Next":"التالي", "Back":"رجوع", "Cancel":"إلغاء", "Yes":"نعم", "No":"لا", "Total Users":"إجمالي المستخدمين", "Real-time bot overview":"نظرة عامة على البوت في الوقت الفعلي", "Active users":"المستخدمون النشطون", "VIP members":"أعضاء VIP", "Waiting requests":"الطلبات المنتظرة", "Blocked users":"المستخدمون المحظورون", "Bot Activity":"نشاط البوت", "Actions":"الإجراءات", "Logins":"تسجيلات الدخول", "Unlocks":"عمليات الفتح", "Today":"اليوم", "Total":"الإجمالي",
 }
}

# Unlock Cars UI translations.
MANUAL_UI.setdefault("id", {}).update({
    "UNLOCK CARS": "BUKA MOBIL",
    "𝗨𝗡𝗟𝗢𝗖𝗞 𝗖𝗔𝗥𝗦": "𝗕𝗨𝗞𝗔 𝗠𝗢𝗕𝗜𝗟",
    "SOURCE login failed.": "Login SOURCE gagal.",
    "TARGET authentication data is unavailable.": "Data autentikasi TARGET tidak tersedia.",
    "SOURCE account contains 0 detectable cars.": "Akun SOURCE tidak memiliki mobil yang terdeteksi.",
    "Every car will be imported and verified...": "Setiap mobil akan diimpor dan diverifikasi...",
    "Every detected SOURCE car is present on TARGET.": "Semua mobil SOURCE yang terdeteksi sudah ada di TARGET.",
    "The feature is not marked complete until every car is verified.": "Fitur belum dianggap selesai sampai semua mobil terverifikasi.",
})
MANUAL_UI.setdefault("ru", {}).update({"UNLOCK CARS": "ОТКРЫТЬ МАШИНЫ"})
MANUAL_UI.setdefault("ar", {}).update({"UNLOCK CARS": "فتح السيارات"})

# ═══════════════════════════════════════════
#  🧪 FULL STATIC UI AUDIT PATCH
# ═══════════════════════════════════════════
# Explicit translations for every UI phrase found by the AST audit.
AUDIT_TRANSLATIONS = {'SELECT LANGUAGE': {'id': 'PILIH BAHASA', 'en': 'SELECT LANGUAGE', 'ru': 'ВЫБЕРИТЕ ЯЗЫК', 'ar': 'اختر اللغة'}, 'Silakan pilih bahasa terlebih dahulu.': {'id': 'Silakan pilih bahasa terlebih dahulu.', 'en': 'Please select your language first.', 'ru': 'Сначала выберите язык.', 'ar': 'يرجى اختيار اللغة أولاً.'}, 'Please select your language first.': {'id': 'Silakan pilih bahasa terlebih dahulu.', 'en': 'Please select your language first.', 'ru': 'Сначала выберите язык.', 'ar': 'يرجى اختيار اللغة أولاً.'}, 'LANGUAGE SELECTED': {'id': 'BAHASA DIPILIH', 'en': 'LANGUAGE SELECTED', 'ru': 'ЯЗЫК ВЫБРАН', 'ar': 'تم اختيار اللغة'}, 'Loading...': {'id': 'Memuat...', 'en': 'Loading...', 'ru': 'Загрузка...', 'ar': 'جارٍ التحميل...'}, 'Invalid language.': {'id': 'Bahasa tidak valid.', 'en': 'Invalid language.', 'ru': 'Неверный язык.', 'ar': 'اللغة غير صالحة.'}, 'Failed to save language.': {'id': 'Gagal menyimpan bahasa.', 'en': 'Failed to save language.', 'ru': 'Не удалось сохранить язык.', 'ar': 'تعذر حفظ اللغة.'}, 'Language:': {'id': 'Bahasa:', 'en': 'Language:', 'ru': 'Язык:', 'ar': 'اللغة:'}, 'Access expired.': {'id': 'Akses telah berakhir.', 'en': 'Access expired.', 'ru': 'Срок доступа истёк.', 'ar': 'انتهил срок доступа.'}, 'BANNED': {'id': 'DIBLOKIR', 'en': 'BANNED', 'ru': 'ЗАБЛОКИРОВАН', 'ar': 'محظور'}, 'MAINTENANCE': {'id': 'PEMELIHARAAN', 'en': 'MAINTENANCE', 'ru': 'ОБСЛУЖИВАНИЕ', 'ar': 'صيانة'}, 'Already approved!': {'id': 'Sudah disetujui!', 'en': 'Already approved!', 'ru': 'Уже одобрено!', 'ar': 'تمت الموافقة بالفعل!'}, 'Request pending. Wait for admin.': {'id': 'Permintaan sedang menunggu. Tunggu admin.', 'en': 'Request pending. Wait for admin.', 'ru': 'Запрос ожидает рассмотрения. Дождитесь администратора.', 'ar': 'الطلب قيد الانتظار. انتظر المسؤول.'}, 'Request sent!': {'id': 'Permintaan terkirim!', 'en': 'Request sent!', 'ru': 'Запрос отправлен!', 'ar': 'تم إرسال الطلب!'}, "You'll be notified.": {'id': 'Anda akan diberi tahu.', 'en': "You'll be notified.", 'ru': 'Вы получите уведомление.', 'ar': 'سيتم إعلامك.'}, 'Sent!': {'id': 'Terkirim!', 'en': 'Sent!', 'ru': 'Отправлено!', 'ar': 'تم الإرسال!'}, 'No permission': {'id': 'Tidak memiliki izin', 'en': 'No permission', 'ru': 'Нет разрешения', 'ar': 'لا توجد صلاحية'}, 'Approved!': {'id': 'Disetujui!', 'en': 'Approved!', 'ru': 'Одобрено!', 'ar': 'تمت الموافقة!'}, 'Rejected': {'id': 'Ditolak', 'en': 'Rejected', 'ru': 'Отклонено', 'ar': 'مرفوض'}, 'Rejected.': {'id': 'Ditolak.', 'en': 'Rejected.', 'ru': 'Отклонено.', 'ar': 'مرفوض.'}, 'Request declined.': {'id': 'Permintaan ditolak.', 'en': 'Request declined.', 'ru': 'Запрос отклонён.', 'ar': 'تم رفض الطلب.'}, 'Approved': {'id': 'Disetujui', 'en': 'Approved', 'ru': 'Одобрено', 'ar': 'تمت الموافقة'}, 'ACCEPTED': {'id': 'DITERIMA', 'en': 'ACCEPTED', 'ru': 'ПРИНЯТО', 'ar': 'تم القبول'}, 'REJECTED': {'id': 'DITOLAK', 'en': 'REJECTED', 'ru': 'ОТКЛОНЕНО', 'ar': 'مرفوض'}, 'By': {'id': 'Oleh', 'en': 'By', 'ru': 'Автор', 'ar': 'بواسطة'}, 'Contact': {'id': 'Kontak', 'en': 'Contact', 'ru': 'Контакт', 'ar': 'تواصل'}, 'Your ID:': {'id': 'ID Anda:', 'en': 'Your ID:', 'ru': 'Ваш ID:', 'ar': 'معرّفك:'}, 'Request': {'id': 'Permintaan', 'en': 'Request', 'ru': 'Запрос', 'ar': 'الطلب'}, 'pending:': {'id': 'menunggu:', 'en': 'pending:', 'ru': 'ожидает:', 'ar': 'معلق:'}, 'Select action:': {'id': 'Pilih tindakan:', 'en': 'Select action:', 'ru': 'Выберите действие:', 'ar': 'اختر الإجراء:'}, 'Sign in first!': {'id': 'Masuk terlebih dahulu!', 'en': 'Sign in first!', 'ru': 'Сначала войдите!', 'ar': 'سجّل الدخول أولاً!'}, 'Wait': {'id': 'Tunggu', 'en': 'Wait', 'ru': 'Подождите', 'ar': 'انتظر'}, 'Refreshed!': {'id': 'Disegarkan!', 'en': 'Refreshed!', 'ru': 'Обновлено!', 'ar': 'تم التحديث!'}, 'Cancelled': {'id': 'Dibatalkan', 'en': 'Cancelled', 'ru': 'Отменено', 'ar': 'تم الإلغاء'}, 'Cancel': {'id': 'Batal', 'en': 'Cancel', 'ru': 'Отмена', 'ar': 'إلغاء'}, '1-100 characters.': {'id': '1-100 karakter.', 'en': '1-100 characters.', 'ru': '1–100 символов.', 'ar': '1-100 حرفاً.'}, '4-100 characters.': {'id': '4-100 karakter.', 'en': '4-100 characters.', 'ru': '4–100 символов.', 'ar': '4-100 حرفاً.'}, 'Password must be 6-256 characters.': {'id': 'Password harus 6-256 karakter.', 'en': 'Password must be 6-256 characters.', 'ru': 'Пароль должен содержать 6–256 символов.', 'ar': 'يجب أن تتكون كلمة المرور من 6-256 حرفاً.'}, 'Setting name...': {'id': 'Mengatur nama...', 'en': 'Setting name...', 'ru': 'Установка имени...', 'ar': 'جارٍ إعداد الاسم...'}, 'Setting ID...': {'id': 'Mengatur ID...', 'en': 'Setting ID...', 'ru': 'Установка ID...', 'ar': 'جارٍ إعداد المعرّف...'}, 'Setting wins...': {'id': 'Mengatur kemenangan...', 'en': 'Setting wins...', 'ru': 'Установка побед...', 'ar': 'جارٍ إعداد الانتصارات...'}, 'Setting loses...': {'id': 'Mengatur kekalahan...', 'en': 'Setting losses...', 'ru': 'Установка поражений...', 'ar': 'جارٍ إعداد الخسائر...'}, 'Updating email...': {'id': 'Memperbarui email...', 'en': 'Updating email...', 'ru': 'Обновление email...', 'ar': 'جارٍ تحديث البريد...'}, 'Updating password...': {'id': 'Memperbarui password...', 'en': 'Updating password...', 'ru': 'Обновление пароля...', 'ar': 'جارٍ تحديث كلمة المرور...'}, 'Send SOURCE email:': {'id': 'Kirim email SUMBER:', 'en': 'Send SOURCE email:', 'ru': 'Введите email ИСТОЧНИКА:', 'ar': 'أرسل بريد المصدر:'}, 'Send SOURCE password:': {'id': 'Kirim password SUMBER:', 'en': 'Send SOURCE password:', 'ru': 'Введите пароль ИСТОЧНИКА:', 'ar': 'أرسل كلمة مرور المصدر:'}, 'Send TARGET email:': {'id': 'Kirim email TARGET:', 'en': 'Send TARGET email:', 'ru': 'Введите email ЦЕЛИ:', 'ar': 'أرسل بريد الهدف:'}, 'Send TARGET password:': {'id': 'Kirim password TARGET:', 'en': 'Send TARGET password:', 'ru': 'Введите пароль ЦЕЛИ:', 'ar': 'أرسل كلمة مرور الهدف:'}, 'Logging into source...': {'id': 'Login ke akun sumber...', 'en': 'Logging into source...', 'ru': 'Вход в исходный аккаунт...', 'ar': 'جارٍ تسجيل الدخول إلى المصدر...'}, 'Source login failed': {'id': 'Login sumber gagal', 'en': 'Source login failed', 'ru': 'Не удалось войти в исходный аккаунт', 'ar': 'فشل تسجيل الدخول إلى المصدر'}, 'Fetching source cars...': {'id': 'Mengambil mobil dari sumber...', 'en': 'Fetching source cars...', 'ru': 'Получение машин из источника...', 'ar': 'جارٍ جلب سيارات المصدر...'}, 'Source has 0 cars': {'id': 'Akun sumber memiliki 0 mobil', 'en': 'Source has 0 cars', 'ru': 'В источнике нет машин', 'ar': 'المصدر لا يحتوي على سيارات'}, 'Logging into target...': {'id': 'Login ke akun target...', 'en': 'Logging into target...', 'ru': 'Вход в целевой аккаунт...', 'ar': 'جارٍ تسجيل الدخول إلى الهدف...'}, 'Target login failed': {'id': 'Login target gagal', 'en': 'Target login failed', 'ru': 'Не удалось войти в целевой аккаунт', 'ar': 'فشل تسجيل الدخول إلى الهدف'}, 'Features': {'id': 'Fitur', 'en': 'Features', 'ru': 'Функции', 'ar': 'الميزات'}, 'Feature': {'id': 'Fitur', 'en': 'Feature', 'ru': 'Функция', 'ar': 'الميزة'}, 'FEATURES BOT MASKY': {'id': 'FITUR BOT MASKY', 'en': 'MASKY BOT FEATURES', 'ru': 'ФУНКЦИИ БОТА MASKY', 'ar': 'ميزات بوت MASKY'}, 'PREMIUM FEATURE CENTER': {'id': 'PUSAT FITUR PREMIUM', 'en': 'PREMIUM FEATURE CENTER', 'ru': 'ПРЕМИУМ-ЦЕНТР ФУНКЦИЙ', 'ar': 'مركز الميزات المميزة'}, 'Features Available': {'id': 'Fitur Tersedia', 'en': 'Features Available', 'ru': 'Доступные функции', 'ar': 'الميزات المتاحة'}, 'Fast & Easy Unlock': {'id': 'Buka Cepat & Mudah', 'en': 'Fast & Easy Unlock', 'ru': 'Быстрая и простая разблокировка', 'ar': 'فتح سريع وسهل'}, 'Account Protection Active': {'id': 'Perlindungan Akun Aktif', 'en': 'Account Protection Active', 'ru': 'Защита аккаунта активна', 'ar': 'حماية الحساب مفعّلة'}, 'STATUS FITUR DALAM AKUN CPM': {'id': 'STATUS FITUR DALAM AKUN CPM', 'en': 'CPM ACCOUNT FEATURE STATUS', 'ru': 'СТАТУС ФУНКЦИЙ АККАУНТА CPM', 'ar': 'حالة ميزات حساب CPM'}, 'TELAH TERBUKA': {'id': 'TELAH TERBUKA', 'en': 'UNLOCKED', 'ru': 'ОТКРЫТО', 'ar': 'مفتوحة'}, 'BELUM TERBUKA': {'id': 'BELUM TERBUKA', 'en': 'LOCKED', 'ru': 'ЗАБЛОКИРОВАНО', 'ar': 'مقفلة'}, 'Belum ada fitur yang terbuka': {'id': 'Belum ada fitur yang terbuka', 'en': 'No features are unlocked yet', 'ru': 'Пока нет открытых функций', 'ar': 'لا توجد ميزات مفتوحة بعد'}, 'Semua fitur sudah terbuka': {'id': 'Semua fitur sudah terbuka', 'en': 'All features are already unlocked', 'ru': 'Все функции уже открыты', 'ar': 'جميع الميزات مفتوحة بالفعل'}, 'SELECT A FEATURE': {'id': 'PILIH FITUR', 'en': 'SELECT A FEATURE', 'ru': 'ВЫБЕРИТЕ ФУНКЦИЮ', 'ar': 'اختر ميزة'}, 'Choose an option below or use': {'id': 'Pilih opsi di bawah atau gunakan', 'en': 'Choose an option below or use', 'ru': 'Выберите вариант ниже или используйте', 'ar': 'اختر خياراً أدناه أو استخدم'}, 'UNLOCK ALL FEATURES': {'id': 'BUKA SEMUA FITUR', 'en': 'UNLOCK ALL FEATURES', 'ru': 'ОТКРЫТЬ ВСЕ ФУНКЦИИ', 'ar': 'فتح جميع الميزات'}, 'at once.': {'id': 'sekaligus.', 'en': 'at once.', 'ru': 'сразу.', 'ar': 'دفعة واحدة.'}, 'W16 Engine': {'id': 'Mesin W16', 'en': 'W16 Engine', 'ru': 'Двигатель W16', 'ar': 'محرك W16'}, 'Horns': {'id': 'Klakson', 'en': 'Horns', 'ru': 'Клаксон', 'ar': 'البوق'}, 'No Damage': {'id': 'Tanpa Kerusakan', 'en': 'No Damage', 'ru': 'Без урона', 'ar': 'بدون ضرر'}, 'Unlimited Fuel': {'id': 'Bahan Bakar Tak Terbatas', 'en': 'Unlimited Fuel', 'ru': 'Бесконечное топливо', 'ar': 'وقود غير محدود'}, 'Smoke': {'id': 'Asap', 'en': 'Smoke', 'ru': 'Дым', 'ar': 'دخان'}, 'Animations': {'id': 'Animasi', 'en': 'Animations', 'ru': 'Анимации', 'ar': 'الحركات'}, 'Wheels': {'id': 'Roda', 'en': 'Wheels', 'ru': 'Колёса', 'ar': 'العجلات'}, 'Houses': {'id': 'Rumah', 'en': 'Houses', 'ru': 'Дома', 'ar': 'المنازل'}, 'All Levels': {'id': 'Semua Level', 'en': 'All Levels', 'ru': 'Все уровни', 'ar': 'جميع المستويات'}, 'Max Rank': {'id': 'Rank Maksimal', 'en': 'Max Rank', 'ru': 'Максимальный ранг', 'ar': 'أعلى رتبة'}, 'Headlights': {'id': 'Lampu Depan', 'en': 'Headlights', 'ru': 'Фары', 'ar': 'المصابيح الأمامية'}, 'All Clothes': {'id': 'Semua Pakaian', 'en': 'All Clothes', 'ru': 'Вся одежда', 'ar': 'جميع الملابس'}, 'UNLOCKING ALL': {'id': 'MEMBUKA SEMUA', 'en': 'UNLOCKING ALL', 'ru': 'ОТКРЫТИЕ ВСЕХ', 'ar': 'جارٍ فتح الكل'}, 'COMPLETE': {'id': 'SELESAI', 'en': 'COMPLETE', 'ru': 'ЗАВЕРШЕНО', 'ar': 'اكتمل'}, 'SETTINGS BOT MASKYY': {'id': 'PENGATURAN BOT MASKYY', 'en': 'MASKYY BOT SETTINGS', 'ru': 'НАСТРОЙКИ БОТА MASKYY', 'ar': 'إعدادات بوت MASKYY'}, 'Account Management Center': {'id': 'Pusat Pengelolaan Akun', 'en': 'Account Management Center', 'ru': 'Центр управления аккаунтом', 'ar': 'مركز إدارة الحساب'}, 'CPM ACCOUNT': {'id': 'AKUN CPM', 'en': 'CPM ACCOUNT', 'ru': 'АККАУНТ CPM', 'ar': 'حساب CPM'}, 'ACCOUNT CONTROL CENTER': {'id': 'PUSAT KONTROL AKUN', 'en': 'ACCOUNT CONTROL CENTER', 'ru': 'ЦЕНТР УПРАВЛЕНИЯ АККАУНТОМ', 'ar': 'مركز التحكم بالحساب'}, 'Update account name': {'id': 'Ubah nama akun', 'en': 'Update account name', 'ru': 'Изменить имя аккаунта', 'ar': 'تحديث اسم الحساب'}, 'Manage Player ID': {'id': 'Kelola Player ID', 'en': 'Manage Player ID', 'ru': 'Управление ID игрока', 'ar': 'إدارة معرّف اللاعب'}, 'Change account email': {'id': 'Ubah email akun', 'en': 'Change account email', 'ru': 'Изменить email аккаунта', 'ar': 'تغيير بريد الحساب'}, 'Change account password': {'id': 'Ubah password akun', 'en': 'Change account password', 'ru': 'Изменить пароль аккаунта', 'ar': 'تغيير كلمة مرور الحساب'}, 'Clone account': {'id': 'Kloning akun', 'en': 'Clone account', 'ru': 'Клонировать аккаунт', 'ar': 'نسخ الحساب'}, 'Update wins / losses': {'id': 'Ubah kemenangan / kekalahan', 'en': 'Update wins / losses', 'ru': 'Изменить победы / поражения', 'ar': 'تحديث الانتصارات / الخسائر'}, 'Repair account data': {'id': 'Perbaiki data akun', 'en': 'Repair account data', 'ru': 'Исправить данные аккаунта', 'ar': 'إصلاح بيانات الحساب'}, 'SELECT AN OPTION BELOW': {'id': 'PILIH OPSI DI BAWAH', 'en': 'SELECT AN OPTION BELOW', 'ru': 'ВЫБЕРИТЕ ВАРИАНТ НИЖЕ', 'ar': 'اختر خياراً أدناه'}, 'Manage your CPM account settings using the buttons below.': {'id': 'Kelola pengaturan akun CPM menggunakan tombol di bawah.', 'en': 'Manage your CPM account settings using the buttons below.', 'ru': 'Управляйте настройками аккаунта CPM с помощью кнопок ниже.', 'ar': 'أدر إعدادات حساب CPM باستخدام الأزرار أدناه.'}, 'Enter new name:': {'id': 'Masukkan nama baru:', 'en': 'Enter new name:', 'ru': 'Введите новое имя:', 'ar': 'أدخل الاسم الجديد:'}, 'Enter new Player ID:': {'id': 'Masukkan Player ID baru:', 'en': 'Enter new Player ID:', 'ru': 'Введите новый ID игрока:', 'ar': 'أدخل معرّف اللاعب الجديد:'}, 'Enter win count:': {'id': 'Masukkan jumlah kemenangan:', 'en': 'Enter win count:', 'ru': 'Введите количество побед:', 'ar': 'أدخل عدد الانتصارات:'}, 'Enter loss count:': {'id': 'Masukkan jumlah kekalahan:', 'en': 'Enter loss count:', 'ru': 'Введите количество поражений:', 'ar': 'أدخل عدد الخسائر:'}, 'Enter new CPM email:': {'id': 'Masukkan email CPM baru:', 'en': 'Enter new CPM email:', 'ru': 'Введите новый email CPM:', 'ar': 'أدخل بريد CPM الجديد:'}, 'Enter new password (minimum 6 characters):': {'id': 'Masukkan password baru (minimal 6 karakter):', 'en': 'Enter new password (minimum 6 characters):', 'ru': 'Введите новый пароль (минимум 6 символов):', 'ar': 'أدخل كلمة المرور الجديدة (6 أحرف على الأقل):'}, '𝗡𝗔𝗠𝗘 𝗨𝗣𝗗𝗔𝗧𝗘𝗗': {'id': '𝗡𝗔𝗠𝗔 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜', 'en': '𝗡𝗔𝗠𝗘 𝗨𝗣𝗗𝗔𝗧𝗘𝗗', 'ru': '𝗜𝗠𝗬𝗔 𝗢𝗕𝗡𝗢𝗩𝗟𝗘𝗡𝗢', 'ar': '𝗧𝗠 𝗧𝗛𝗗𝗬𝗧𝗛 𝗔𝗟𝗜𝗦𝗠'}, '𝗜𝗗 𝗨𝗣𝗗𝗔𝗧𝗘𝗗': {'id': '𝗜𝗗 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜', 'en': '𝗜𝗗 𝗨𝗣𝗗𝗔𝗧𝗘𝗗', 'ru': 'تم تحديث المعرّف', 'ar': '𝗧𝗠 𝗧𝗛𝗗𝗬𝗧𝗛 𝗔𝗟𝗠𝗚Rّﻒ'}, '𝗪𝗜𝗡𝗦 𝗨𝗣𝗗𝗔𝗧𝗘𝗗': {'id': '𝗞𝗘𝗠𝗘𝗡𝗔𝗡𝗚𝗔𝗡 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜', 'en': '𝗪𝗜𝗡𝗦 𝗨𝗣𝗗𝗔𝗧𝗘𝗗', 'ru': 'تم تحديث الانتصارات', 'ar': 'تم تحديث الانتصارات'}, '𝗟𝗢𝗦𝗘𝗦 𝗨𝗣𝗗𝗔𝗧𝗘𝗗': {'id': '𝗞𝗘𝗞𝗔𝗟𝗔𝗛𝗔𝗡 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜', 'en': '𝗟𝗢𝗦𝗘𝗦 𝗨𝗣𝗗𝗔𝗧𝗘𝗗', 'ru': '𝗣𝗔𝗭𝗜𝗟𝗢𝗡𝗘𝗡𝗜𝗬 𝗢𝗕𝗡𝗢𝗩𝗟𝗘𝗡Ы', 'ar': 'تم تحديث الخسائر'}, '𝗘𝗠𝗔𝗜𝗟 𝗨𝗣𝗗𝗔𝗧𝗘𝗗': {'id': '𝗘𝗠𝗔𝗜𝗟 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜', 'en': '𝗘𝗠𝗔𝗜𝗟 𝗨𝗣𝗗𝗔𝗧𝗘𝗗', 'ru': 'تم تحديث البريد', 'ar': 'تم تحديث البريد'}, '𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗨𝗣𝗗𝗔𝗧𝗘𝗗': {'id': '𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜', 'en': '𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗨𝗣𝗗𝗔𝗧𝗘𝗗', 'ru': '𝗧𝗠 𝗧𝗛𝗗𝗬𝗧𝗛', 'ar': 'تم تحديث كلمة المرور'}, 'Password changed': {'id': 'Password diubah', 'en': 'Password changed', 'ru': 'Пароль изменён', 'ar': 'تم تغيير كلمة المرور'}, 'Stats reset!': {'id': 'Statistik direset!', 'en': 'Stats reset!', 'ru': 'Статистика сброшена!', 'ar': 'تمت إعادة ضبط الإحصائيات!'}, 'Owner only!': {'id': 'Khusus Owner!', 'en': 'Owner only!', 'ru': 'Только владелец!', 'ar': 'للمالك فقط!'}, 'Cannot remove owner!': {'id': 'Tidak dapat menghapus Owner!', 'en': 'Cannot remove owner!', 'ru': 'Нельзя удалить владельца!', 'ar': 'لا يمكن إزالة المالك!'}, 'demoted!': {'id': 'diturunkan rolenya!', 'en': 'demoted!', 'ru': 'понижен в должности!', 'ar': 'تم خفض رتبته!'}, 'Select role for': {'id': 'Pilih role untuk', 'en': 'Select role for', 'ru': 'Выберите роль для', 'ar': 'اختر الدور لـ'}, 'Use /admin': {'id': 'Gunakan /admin', 'en': 'Use /admin', 'ru': 'Используйте /admin', 'ar': 'استخدم /admin'}, 'You are now VIP!': {'id': 'Anda sekarang VIP!', 'en': 'You are now VIP!', 'ru': 'Теперь вы VIP!', 'ar': 'أصبحت الآن VIP!'}, 'is now VIP!': {'id': 'sekarang VIP!', 'en': 'is now VIP!', 'ru': 'теперь VIP!', 'ar': 'أصبح الآن VIP!'}, 'VIP removed for': {'id': 'VIP dihapus untuk', 'en': 'VIP removed for', 'ru': 'VIP удалён для', 'ar': 'تمت إزالة VIP للمستخدم'}, 'UPDATE BOT PHOTO': {'id': 'PERBARUI FOTO BOT', 'en': 'UPDATE BOT PHOTO', 'ru': 'ОБНОВИТЬ ФОТО БОТА', 'ar': 'تحديث صورة البوت'}, 'Current photo is set.': {'id': 'Foto saat ini sudah terpasang.', 'en': 'Current photo is set.', 'ru': 'Текущее фото установлено.', 'ar': 'الصورة الحالية مفعّلة.'}, 'Send a new photo to update it.': {'id': 'Kirim foto baru untuk memperbaruinya.', 'en': 'Send a new photo to update it.', 'ru': 'Отправьте новое фото для обновления.', 'ar': 'أرسل صورة جديدة لتحديثها.'}, 'This photo shows on welcome screen.': {'id': 'Foto ini akan tampil di layar sambutan.', 'en': 'This photo shows on welcome screen.', 'ru': 'Это фото будет показано на экране приветствия.', 'ar': 'ستظهر هذه الصورة في شاشة الترحيب.'}, 'Bot welcome photo updated!': {'id': 'Foto sambutan bot berhasil diperbarui!', 'en': 'Bot welcome photo updated!', 'ru': 'Фото приветствия бота обновлено!', 'ar': 'تم تحديث صورة ترحيب البوت!'}, 'It will show for new users.': {'id': 'Foto akan tampil untuk user baru.', 'en': 'It will show for new users.', 'ru': 'Оно будет показано новым пользователям.', 'ar': 'ستظهر للمستخدمين الجدد.'}, 'TEXT BROADCAST MASKY': {'id': 'BROADCAST TEKS MASKY', 'en': 'MASKY TEXT BROADCAST', 'ru': 'ТЕКСТОВАЯ РАССЫЛКА MASKY', 'ar': 'بث نصي من MASKY'}, 'VIP BROADCAST MASKY': {'id': 'BROADCAST VIP MASKY', 'en': 'MASKY VIP BROADCAST', 'ru': 'VIP-РАССЫЛКА MASKY', 'ar': 'بث VIP من MASKY'}, 'PHOTO BROADCAST MASKY': {'id': 'BROADCAST FOTO MASKY', 'en': 'MASKY PHOTO BROADCAST', 'ru': 'ФОТОРАССЫЛКА MASKY', 'ar': 'بث صور من MASKY'}, 'Message to all': {'id': 'Pesan untuk semua', 'en': 'Message to all', 'ru': 'Сообщение всем', 'ar': 'رسالة للجميع'}, 'Message to': {'id': 'Pesan untuk', 'en': 'Message to', 'ru': 'Сообщение для', 'ar': 'رسالة إلى'}, 'VIPs:': {'id': 'VIP:', 'en': 'VIPs:', 'ru': 'VIP:', 'ar': 'VIP:'}, 'Send a photo:': {'id': 'Kirim foto:', 'en': 'Send a photo:', 'ru': 'Отправьте фото:', 'ar': 'أرسل صورة:'}, 'Photo received!': {'id': 'Foto diterima!', 'en': 'Photo received!', 'ru': 'Фото получено!', 'ar': 'تم استلام الصورة!'}, 'URL set!': {'id': 'URL ditetapkan!', 'en': 'URL set!', 'ru': 'URL установлена!', 'ar': 'تم تعيين الرابط!'}, 'Type caption:': {'id': 'Ketik caption:', 'en': 'Type caption:', 'ru': 'Введите подпись:', 'ar': 'اكتب الوصف:'}, 'Done!': {'id': 'Selesai!', 'en': 'Done!', 'ru': 'Готово!', 'ar': 'تم!'}, 'sent': {'id': 'terkirim', 'en': 'sent', 'ru': 'отправлено', 'ar': 'تم الإرسال'}, 'failed': {'id': 'gagal', 'en': 'failed', 'ru': 'ошибка', 'ar': 'فشل'}, 'Maintenance:': {'id': 'Pemeliharaan:', 'en': 'Maintenance:', 'ru': 'Обслуживание:', 'ar': 'الصيانة:'}, 'OFF': {'id': 'MATI', 'en': 'OFF', 'ru': 'ВЫКЛ', 'ar': 'متوقف'}, 'Expiry removed.': {'id': 'Masa berlaku dihapus.', 'en': 'Expiry removed.', 'ru': 'Срок действия удалён.', 'ar': 'تمت إزالة انتهاء الصلاحية.'}, 'Invalid expiry.': {'id': 'Masa berlaku tidak valid.', 'en': 'Invalid expiry.', 'ru': 'Неверный срок действия.', 'ar': 'انتهاء الصلاحية غير صالح.'}, 'Durasi tidak tersedia.': {'id': 'Durasi tidak tersedia.', 'en': 'Duration unavailable.', 'ru': 'Срок недоступен.', 'ar': 'المدة غير متاحة.'}, 'Duration unavailable.': {'id': 'Durasi tidak tersedia.', 'en': 'Duration unavailable.', 'ru': 'Срок недоступен.', 'ar': 'المدة غير متاحة.'}, 'Expiry berhasil disimpan.': {'id': 'Masa berlaku berhasil disimpan.', 'en': 'Expiry saved successfully.', 'ru': 'Срок действия сохранён.', 'ar': 'تم حفظ مدة الصلاحية بنجاح.'}, 'Expiry berhasil dihapus.': {'id': 'Masa berlaku berhasil dihapus.', 'en': 'Expiry removed successfully.', 'ru': 'Срок действия удалён.', 'ar': 'تمت إزالة مدة الصلاحية بنجاح.'}, 'Custom expiry berhasil disimpan.': {'id': 'Masa berlaku kustom berhasil disimpan.', 'en': 'Custom expiry saved successfully.', 'ru': 'Пользовательский срок сохранён.', 'ar': 'تم حفظ مدة الصلاحية المخصصة.'}, 'User ID tidak ditemukan.': {'id': 'User ID tidak ditemukan.', 'en': 'User ID not found.', 'ru': 'ID пользователя не найден.', 'ar': 'معرّف المستخدم غير موجود.'}, 'User tersebut sudah tidak diban.': {'id': 'User tersebut sudah tidak diblokir.', 'en': 'User is no longer banned.', 'ru': 'Пользователь больше не заблокирован.', 'ar': 'المستخدم لم يعد محظوراً.'}, 'berhasil di-unban.': {'id': 'berhasil dibuka blokirnya.', 'en': 'successfully unbanned.', 'ru': 'разблокирован.', 'ar': 'تم إلغاء حظره بنجاح.'}, 'users kicked.': {'id': 'user dikeluarkan.', 'en': 'users kicked.', 'ru': 'пользователей исключено.', 'ar': 'تم طرد مستخدمين.'}, 'No users to kick.': {'id': 'Tidak ada user untuk dikeluarkan.', 'en': 'No users to kick.', 'ru': 'Нет пользователей для исключения.', 'ar': 'لا يوجد مستخدمون للطرد.'}, 'Cannot ban owner!': {'id': 'Tidak dapat memblokir Owner!', 'en': 'Cannot ban owner!', 'ru': 'Нельзя заблокировать владельца!', 'ar': 'لا يمكن حظر المالك!'}, 'Cannot kick owner!': {'id': 'Tidak dapat mengeluarkan Owner!', 'en': 'Cannot kick owner!', 'ru': 'Нельзя исключить владельца!', 'ar': 'لا يمكن طرد المالك!'}, 'Invalid ID.': {'id': 'ID tidak valid.', 'en': 'Invalid ID.', 'ru': 'Неверный ID.', 'ar': 'المعرّف غير صالح.'}, 'No admin access.': {'id': 'Tidak memiliki akses admin.', 'en': 'No admin access.', 'ru': 'Нет доступа администратора.', 'ar': 'لا توجد صلاحية مسؤول.'}, 'Admin only!': {'id': 'Khusus Admin!', 'en': 'Admin only!', 'ru': 'Только администратор!', 'ar': 'للمسؤول فقط!'}, 'No access!': {'id': 'Tidak memiliki akses!', 'en': 'No access!', 'ru': 'Нет доступа!', 'ar': 'لا يوجد وصول!'}, 'Empty submission. Send one user ID per line, or /cancel to cancel.': {'id': 'Input kosong. Kirim satu User ID per baris, atau /cancel untuk membatalkan.', 'en': 'Empty submission. Send one user ID per line, or /cancel to cancel.', 'ru': 'Пустой ввод. Отправьте по одному ID пользователя в строке или /cancel для отмены.', 'ar': 'الإدخال فارغ. أرسل معرّف مستخدم واحداً في كل سطر أو /cancel للإلغاء.'}, 'Bulk add cancelled.': {'id': 'Bulk add dibatalkan.', 'en': 'Bulk add cancelled.', 'ru': 'Массовое добавление отменено.', 'ar': 'تم إلغاء الإضافة الجماعية.'}, 'Could not load account data.': {'id': 'Data akun tidak dapat dimuat.', 'en': 'Could not load account data.', 'ru': 'Не удалось загрузить данные аккаунта.', 'ar': 'تعذر تحميل بيانات الحساب.'}, 'Try Refresh first.': {'id': 'Coba Segarkan terlebih dahulu.', 'en': 'Try Refresh first.', 'ru': 'Сначала нажмите «Обновить».', 'ar': 'جرّب التحديث أولاً.'}, 'Owner': {'id': 'Owner', 'en': 'Owner', 'ru': 'Владелец', 'ar': 'المالك'}, 'Super Admin': {'id': 'Super Admin', 'en': 'Super Admin', 'ru': 'Суперадминистратор', 'ar': 'المسؤول الأعلى'}, 'Moderator': {'id': 'Moderator', 'en': 'Moderator', 'ru': 'Модератор', 'ar': 'المشرف'}, 'Admin': {'id': 'Admin', 'en': 'Admin', 'ru': 'Администратор', 'ar': 'المسؤول'}, 'USER ROLES': {'id': 'PERAN USER', 'en': 'USER ROLES', 'ru': 'РОЛИ ПОЛЬЗОВАТЕЛЕЙ', 'ar': 'أدوار المستخدمين'}, 'Setiap user hanya ditampilkan pada 1 role.': {'id': 'Setiap user hanya ditampilkan pada 1 role.', 'en': 'Each user is shown in only one role.', 'ru': 'Каждый пользователь отображается только в одной роли.', 'ar': 'يظهر كل مستخدم في دور واحد فقط.'}, 'Tidak ada user': {'id': 'Tidak ada user', 'en': 'No users', 'ru': 'Нет пользователей', 'ar': 'لا يوجد مستخدمون'}, 'Total Users': {'id': 'Total User', 'en': 'Total Users', 'ru': 'Всего пользователей', 'ar': 'إجمالي المستخدمين'}, 'User lainnya': {'id': 'user lainnya', 'en': 'other users', 'ru': 'других пользователей', 'ar': 'مستخدمون آخرون'}, 'Real-time bot overview': {'id': 'Ringkasan bot real-time', 'en': 'Real-time bot overview', 'ru': 'Обзор бота в реальном времени', 'ar': 'نظرة عامة على البوت في الوقت الفعلي'}, 'Active users': {'id': 'User aktif', 'en': 'Active users', 'ru': 'Активные пользователи', 'ar': 'المستخدمون النشطون'}, 'VIP members': {'id': 'Member VIP', 'en': 'VIP members', 'ru': 'VIP-участники', 'ar': 'أعضاء VIP'}, 'Waiting requests': {'id': 'Permintaan menunggu', 'en': 'Waiting requests', 'ru': 'Ожидающие запросы', 'ar': 'الطلبات المنتظرة'}, 'Blocked users': {'id': 'User diblokir', 'en': 'Blocked users', 'ru': 'Заблокированные пользователи', 'ar': 'المستخدمون المحظورون'}, 'Bot Activity': {'id': 'Aktivitas Bot', 'en': 'Bot Activity', 'ru': 'Активность бота', 'ar': 'نشاط البوت'}, 'Actions': {'id': 'Aksi', 'en': 'Actions', 'ru': 'Действия', 'ar': 'الإجراءات'}, 'Logins': {'id': 'Login', 'en': 'Logins', 'ru': 'Входы', 'ar': 'تسجيلات الدخول'}, 'Unlocks': {'id': 'Unlock', 'en': 'Unlocks', 'ru': 'Разблокировки', 'ar': 'عمليات الفتح'}, 'Today': {'id': 'Hari ini', 'en': 'Today', 'ru': 'Сегодня', 'ar': 'اليوم'}, 'User profile': {'id': 'Profil User', 'en': 'User profile', 'ru': 'Профиль пользователя', 'ar': 'ملف المستخدم'}, 'None': {'id': 'Tidak ada', 'en': 'None', 'ru': 'Нет', 'ar': 'لا يوجد'}, 'Yes': {'id': 'Ya', 'en': 'Yes', 'ru': 'Да', 'ar': 'نعم'}, 'No': {'id': 'Tidak', 'en': 'No', 'ru': 'Нет', 'ar': 'لا'}, '▸ Home': {'id': '▸ Beranda', 'en': '▸ Home', 'ru': '▸ Главная', 'ar': '▸ الرئيسية'}, '◂ Home': {'id': '◂ Beranda', 'en': '◂ Home', 'ru': '◂ Главная', 'ar': '◂ الرئيسية'}, '◂ Admin Panel': {'id': '◂ Panel Admin', 'en': '◂ Admin Panel', 'ru': '◂ Панель администратора', 'ar': '◂ لوحة المسؤول'}, '◂ Back': {'id': '◂ Kembali', 'en': '◂ Back', 'ru': '◂ Назад', 'ar': '◂ رجوع'}, '◂ BACK TO DASHBOARD': {'id': '◂ KEMBALI KE DASHBOARD', 'en': '◂ BACK TO DASHBOARD', 'ru': '◂ НАЗАД К ПАНЕЛИ', 'ar': '◂ العودة إلى لوحة التحكم'}, 'Back': {'id': 'Kembali', 'en': 'Back', 'ru': 'Назад', 'ar': 'رجوع'}, '✔ Yes': {'id': '✔ Ya', 'en': '✔ Yes', 'ru': '✔ Да', 'ar': '✔ نعم'}, '✗ No': {'id': '✗ Tidak', 'en': '✗ No', 'ru': '✗ Нет', 'ar': '✗ لا'}, '👮 Moderator': {'id': '👮 Moderator', 'en': '👮 Moderator', 'ru': '👮 Модератор', 'ar': '👮 مشرف'}, '🛡 Admin': {'id': '🛡 Admin', 'en': '🛡 Admin', 'ru': '🛡 مسؤول'}, '⭐ Super Admin': {'id': '⭐ Super Admin', 'en': '⭐ Super Admin', 'ru': '⭐ مسؤول أعلى', 'ar': '⭐ مسؤول أعلى'}, '◂ Cancel': {'id': '◂ Batal', 'en': '◂ Cancel', 'ru': '◂ Отмена', 'ar': '◂ إلغاء'}, '✔ Expiry removed.': {'id': '✔ Masa berlaku dihapus.', 'en': '✔ Expiry removed.', 'ru': '✔ Срок действия удалён.', 'ar': '✔ تمت إزالة انتهاء الصلاحية.'}, 'Expiry': {'id': 'Masa Berlaku', 'en': 'Expiry', 'ru': 'Срок действия', 'ar': 'انتهاء الصلاحية'}, 'Duration:': {'id': 'Durasi:', 'en': 'Duration:', 'ru': 'Срок:', 'ar': 'المدة:'}, 'Days': {'id': 'Hari', 'en': 'Days', 'ru': 'дней', 'ar': 'أيام'}, 'Expires:': {'id': 'Berakhir:', 'en': 'Expires:', 'ru': 'Истекает:', 'ar': 'ينتهي:'}, 'Access aktif selama': {'id': 'Access aktif selama', 'en': 'Access active for', 'ru': 'Доступ активен в течение', 'ar': 'الوصول فعال لمدة'}, 'Access active for': {'id': 'Access aktif selama', 'en': 'Access active for', 'ru': 'Доступ активен в течение', 'ar': 'الوصول فعال لمدة'}, 'days': {'id': 'hari', 'en': 'days', 'ru': 'дней', 'ar': 'أيام'}, '𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟 𝗠𝗔𝗦𝗞𝗬': {'id': '𝗣𝗔𝗡𝗘𝗟 𝗔𝗗𝗠𝗜𝗡 𝗠𝗔𝗦𝗞𝗬', 'en': '𝗠𝗔𝗦𝗞𝗬 𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟', 'ru': '𝗔𝗗𝗠𝗜𝗡-ПАНЕЛЬ MASKYY', 'ar': '𝗟𝗢𝗡𝗔𝗡𝗔 𝗠𝗔𝗦𝗞𝗬'}, 'DASBOARD BOT MASKYY': {'id': 'DASHBOARD BOT MASKYY', 'en': 'MASKYY BOT DASHBOARD', 'ru': 'ПАНЕЛЬ БОТА MASKYY', 'ar': 'لوحة تحكم بوت MASKYY'}, 'Premium Control Center': {'id': 'Pusat Kontrol Premium', 'en': 'Premium Control Center', 'ru': 'Премиум-центр управления', 'ar': 'مركز التحكم المميز'}, 'ACCOUNT': {'id': 'AKUN', 'en': 'ACCOUNT', 'ru': 'АККАУНТ', 'ar': 'الحساب'}, 'Email CPM': {'id': 'Email CPM', 'en': 'CPM Email', 'ru': 'Email CPM', 'ar': 'بريد CPM'}, 'Nama Akun': {'id': 'Nama Akun', 'en': 'Account Name', 'ru': 'Имя аккаунта', 'ar': 'اسم الحساب'}, 'Player ID': {'id': 'Player ID', 'en': 'Player ID', 'ru': 'ID игрока', 'ar': 'معرّف اللاعب'}, 'ROLE / STATUS': {'id': 'PERAN / STATUS', 'en': 'ROLE / STATUS', 'ru': 'РОЛЬ / СТАТУС', 'ar': 'الدور / الحالة'}, 'Role / Status': {'id': 'Peran / Status', 'en': 'Role / Status', 'ru': 'Роль / Статус', 'ar': 'الدور / الحالة'}, 'STATS OVERVIEW': {'id': 'RINGKASAN STATISTIK', 'en': 'STATS OVERVIEW', 'ru': 'ОБЗОР СТАТИСТИКИ', 'ar': 'ملخص الإحصائيات'}, 'Money': {'id': 'Uang', 'en': 'Money', 'ru': 'Деньги', 'ar': 'المال'}, 'Coins': {'id': 'Koin', 'en': 'Coins', 'ru': 'Монеты', 'ar': 'العملات'}, 'Wins/Losses': {'id': 'Menang/Kalah', 'en': 'Wins/Losses', 'ru': 'Победы/Поражения', 'ar': 'الفوز/الخسارة'}, 'Levels Done': {'id': 'Level Selesai', 'en': 'Levels Done', 'ru': 'Пройдено уровней', 'ar': 'المستويات المكتملة'}, 'QUICK MENU': {'id': 'MENU CEPAT', 'en': 'QUICK MENU', 'ru': 'БЫСТРОЕ МЕНЮ', 'ar': 'القائمة السريعة'}, 'Pilih menu di bawah untuk mengelola akun.': {'id': 'Pilih menu di bawah untuk mengelola akun.', 'en': 'Choose a menu below to manage your account.', 'ru': 'Выберите меню ниже для управления аккаунтом.', 'ar': 'اختر قائمة أدناه لإدارة الحساب.'}, 'Refresh Account': {'id': 'Segarkan Akun', 'en': 'Refresh Account', 'ru': 'Обновить аккаунт', 'ar': 'تحديث الحساب'}, 'untuk memperbarui statistik.': {'id': 'untuk memperbarui statistik.', 'en': 'to update statistics.', 'ru': 'для обновления статистики.', 'ar': 'لتحديث الإحصائيات.'}, 'ROLE': {'id': 'PERAN', 'en': 'ROLE', 'ru': 'РОЛЬ', 'ar': 'الدور'}, 'STATUS': {'id': 'STATUS', 'en': 'STATUS', 'ru': 'СТАТУС', 'ar': 'الحالة'}, 'Name': {'id': 'Nama', 'en': 'Name', 'ru': 'Имя', 'ar': 'الاسم'}, 'Username': {'id': 'Username', 'en': 'Username', 'ru': 'Имя пользователя', 'ar': 'اسم المستخدم'}, 'ID': {'id': 'ID', 'en': 'ID', 'ru': 'ID', 'ar': 'المعرّف'}, 'Status': {'id': 'Status', 'en': 'Status', 'ru': 'Статус', 'ar': 'الحالة'}, 'Role': {'id': 'Peran', 'en': 'Role', 'ru': 'Роль', 'ar': 'الدور'}, 'Last': {'id': 'Terakhir', 'en': 'Last', 'ru': 'Последний', 'ar': 'آخر نشاط'}, 'Warns': {'id': 'Peringatan', 'en': 'Warns', 'ru': 'Предупреждения', 'ar': 'تحذيرات'}, 'Note': {'id': 'Catatan', 'en': 'Note', 'ru': 'Заметка', 'ar': 'ملاحظة'}, 'NEW REQUEST': {'id': 'PERMINTAAN BARU', 'en': 'NEW REQUEST', 'ru': 'НОВЫЙ ЗАПРОС', 'ar': 'طلب جديد'}, 'USER INFORMATION': {'id': 'INFORMASI USER', 'en': 'USER INFORMATION', 'ru': 'ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ', 'ar': 'معلومات المستخدم'}, 'USER ID': {'id': 'USER ID', 'en': 'USER ID', 'ru': 'ID ПОЛЬЗОВАТЕЛЯ', 'ar': 'معرّف المستخدم'}, 'TANGGAL REQUEST': {'id': 'TANGGAL PERMINTAAN', 'en': 'REQUEST DATE', 'ru': 'ДАТА ЗАПРОСА', 'ar': 'تاريخ الطلب'}}



# Additional phrases found in the deep whole-bot AST audit.
AUDIT_TRANSLATIONS_MORE = {'SECURE ACCESS': {'id': 'AKSES AMAN', 'en': 'SECURE ACCESS', 'ru': 'ЗАЩИЩЁННЫЙ ДОСТУП', 'ar': 'وصول آمن'}, 'Developer BOT Owner': {'id': 'Pemilik Developer BOT', 'en': 'Developer BOT Owner', 'ru': 'Владелец-разработчик бота', 'ar': 'مالك ومطور البوت'}, 'Fast • Secure • Reliable': {'id': 'Cepat • Aman • Andal', 'en': 'Fast • Secure • Reliable', 'ru': 'Быстро • Безопасно • Надёжно', 'ar': 'سريع • آمن • موثوق'}, 'Tap Sign In to retry.': {'id': 'Tekan Masuk untuk mencoba lagi.', 'en': 'Tap Sign In to retry.', 'ru': 'Нажмите «Войти», чтобы повторить.', 'ar': 'اضغط «تسجيل الدخول» للمحاولة مرة أخرى.'}, 'Email not found': {'id': 'Email tidak ditemukan', 'en': 'Email not found', 'ru': 'Email не найден', 'ar': 'البريد الإلكتروني غير موجود'}, 'Wrong password': {'id': 'Password salah', 'en': 'Wrong password', 'ru': 'Неверный пароль', 'ar': 'كلمة المرور خاطئة'}, 'Invalid credentials': {'id': 'Credential tidak valid', 'en': 'Invalid credentials', 'ru': 'Неверные данные', 'ar': 'بيانات الاعتماد غير صالحة'}, 'Too many attempts, wait': {'id': 'Terlalu banyak percobaan, tunggu', 'en': 'Too many attempts, wait', 'ru': 'Слишком много попыток, подождите', 'ar': 'محاولات كثيرة، انتظر'}, 'Account disabled': {'id': 'Akun dinonaktifkan', 'en': 'Account disabled', 'ru': 'Аккаунт отключён', 'ar': 'الحساب معطل'}, 'Invalid email format': {'id': 'Format email tidak valid', 'en': 'Invalid email format', 'ru': 'Неверный формат email', 'ar': 'صيغة البريد الإلكتروني غير صالحة'}, 'Network error, try again': {'id': 'Kesalahan jaringan, coba lagi', 'en': 'Network error, try again', 'ru': 'Ошибка сети, попробуйте снова', 'ar': 'خطأ في الشبكة، حاول مرة أخرى'}, '∞ No Expiry': {'id': '∞ Tanpa Batas', 'en': '∞ No Expiry', 'ru': '∞ Без срока', 'ar': '∞ بدون انتهاء'}, ' days remaining': {'id': ' hari tersisa', 'en': ' days remaining', 'ru': ' дн. осталось', 'ar': ' يوم متبقٍ'}, 'Owner': {'id': 'Owner', 'en': 'Owner', 'ru': 'Владелец', 'ar': 'المالك'}, 'Super Admin': {'id': 'Super Admin', 'en': 'Super Admin', 'ru': 'Суперадминистратор', 'ar': 'المسؤول الأعلى'}, '👮 Moderator': {'id': '👮 Moderator', 'en': '👮 Moderator', 'ru': '👮 Модератор', 'ar': '👮 مشرف'}, '🛡 Admin': {'id': '🛡 Admin', 'en': '🛡 Admin', 'ru': '🛡 Администратор', 'ar': '🛡 مسؤول'}, 'Role:': {'id': 'Peran:', 'en': 'Role:', 'ru': 'Роль:', 'ar': 'الدور:'}, 'Maintenance:': {'id': 'Pemeliharaan:', 'en': 'Maintenance:', 'ru': 'Обслуживание:', 'ar': 'الصيانة:'}, 'Users': {'id': 'User', 'en': 'Users', 'ru': 'Пользователи', 'ar': 'المستخدمون'}, 'Pending': {'id': 'Menunggu', 'en': 'Pending', 'ru': 'Ожидающие', 'ar': 'معلقون'}, 'Banned': {'id': 'Diblokir', 'en': 'Banned', 'ru': 'Заблокированные', 'ar': 'محظورون'}, 'Admins': {'id': 'Admin', 'en': 'Admins', 'ru': 'Администраторы', 'ar': 'المسؤولون'}, 'USER OVERVIEW': {'id': 'RINGKASAN USER', 'en': 'USER OVERVIEW', 'ru': 'ОБЗОР ПОЛЬЗОВАТЕЛЕЙ', 'ar': 'نظرة عامة على المستخدمين'}, 'BOT ACTIVITY': {'id': 'AKTIVITAS BOT', 'en': 'BOT ACTIVITY', 'ru': 'АКТИВНОСТЬ БОТА', 'ar': 'نشاط البوت'}, 'Active users': {'id': 'User aktif', 'en': 'Active users', 'ru': 'Активные пользователи', 'ar': 'المستخدمون النشطون'}, 'VIP members': {'id': 'Member VIP', 'en': 'VIP members', 'ru': 'VIP-участники', 'ar': 'أعضاء VIP'}, 'Waiting requests': {'id': 'Permintaan menunggu', 'en': 'Waiting requests', 'ru': 'Ожидающие запросы', 'ar': 'الطلبات المنتظرة'}, 'Blocked users': {'id': 'User diblokir', 'en': 'Blocked users', 'ru': 'Заблокированные пользователи', 'ar': 'المستخدمون المحظورون'}, 'Actions': {'id': 'Aksi', 'en': 'Actions', 'ru': 'Действия', 'ar': 'الإجراءات'}, 'Unlocks': {'id': 'Unlock', 'en': 'Unlocks', 'ru': 'Разблокировки', 'ar': 'عمليات الفتح'}, 'Logins': {'id': 'Login', 'en': 'Logins', 'ru': 'Входы', 'ar': 'تسجيلات الدخول'}, 'TODAY': {'id': 'HARI INI', 'en': 'TODAY', 'ru': 'СЕГОДНЯ', 'ar': 'اليوم'}, 'NEW REQUEST': {'id': 'PERMINTAAN BARU', 'en': 'NEW REQUEST', 'ru': 'НОВЫЙ ЗАПРОС', 'ar': 'طلب جديد'}, 'USER INFORMATION': {'id': 'INFORMASI USER', 'en': 'USER INFORMATION', 'ru': 'ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ', 'ar': 'معلومات المستخدم'}, 'Name': {'id': 'Nama', 'en': 'Name', 'ru': 'Имя', 'ar': 'الاسم'}, 'Username': {'id': 'Username', 'en': 'Username', 'ru': 'Имя пользователя', 'ar': 'اسم المستخدم'}, 'User ID': {'id': 'User ID', 'en': 'User ID', 'ru': 'ID пользователя', 'ar': 'معرّف المستخدم'}, 'REQUEST DATE': {'id': 'TANGGAL PERMINTAAN', 'en': 'REQUEST DATE', 'ru': 'ДАТА ЗАПРОСА', 'ar': 'تاريخ الطلب'}, 'TANGGAL REQUEST': {'id': 'TANGGAL PERMINTAAN', 'en': 'REQUEST DATE', 'ru': 'ДАТА ЗАПРОСА', 'ar': 'تاريخ الطلب'}, 'Select action:': {'id': 'Pilih tindakan:', 'en': 'Select action:', 'ru': 'Выберите действие:', 'ar': 'اختر الإجراء:'}, '𝗕𝗔𝗡𝗡𝗘𝗗 𝗨𝗦𝗘𝗥𝗦': {'id': '𝗨𝗦𝗘𝗥 𝗗𝗜𝗕𝗟𝗢𝗞𝗜𝗥', 'en': '𝗕𝗔𝗡𝗡𝗘𝗗 𝗨𝗦𝗘𝗥𝗦', 'ru': '𝗭𝗔𝗕𝗟𝗢𝗞𝗜𝗥𝗢𝗩𝗔𝗡𝗡𝗬𝗘 𝗣𝗢𝗟Ь𝗭𝗢𝗩𝗔𝗧𝗘𝗟𝗜', 'ar': 'المستخدمون المحظورون'}, 'Total Banned': {'id': 'Total Diblokir', 'en': 'Total Banned', 'ru': 'Всего заблокировано', 'ar': 'إجمالي المحظورين'}, 'Halaman': {'id': 'Halaman', 'en': 'Page', 'ru': 'Страница', 'ar': 'الصفحة'}, 'Tekan tombol user di bawah untuk': {'id': 'Tekan tombol user di bawah untuk', 'en': 'Tap a user button below to', 'ru': 'Нажмите кнопку пользователя ниже, чтобы', 'ar': 'اضغط على زر المستخدم أدناه لـ'}, 'Unban': {'id': 'Buka Blokir', 'en': 'Unban', 'ru': 'Разблокировать', 'ar': 'إلغاء الحظر'}, '𝗣𝗥𝗢𝗙𝗜𝗟𝗘 𝗕𝗢𝗧 𝗠𝗔𝗦𝗞𝗬': {'id': '𝗣𝗥𝗢𝗙𝗜𝗟 𝗕𝗢𝗧 𝗠𝗔𝗦𝗞𝗬', 'en': '𝗠𝗔𝗦𝗞𝗬 𝗕𝗢𝗧 𝗣𝗥𝗢𝗙𝗜𝗟𝗘', 'ru': '𝗣𝗥𝗢𝗙𝗜𝗟𝗬 𝗕𝗢𝗧𝗔 MASKYY', 'ar': '𝗠𝗟𝗙 𝗕𝗢𝗧 MASKYY'}, 'Last': {'id': 'Terakhir', 'en': 'Last', 'ru': 'Последний', 'ar': 'آخر'}, 'Warns': {'id': 'Peringatan', 'en': 'Warnings', 'ru': 'Предупреждения', 'ar': 'تحذيرات'}, 'Note': {'id': 'Catatan', 'en': 'Note', 'ru': 'Заметка', 'ar': 'ملاحظة'}, '𝗣𝗘𝗡𝗗𝗜𝗡𝗚': {'id': '𝗠𝗘𝗡𝗨𝗡𝗚𝗚𝗨', 'en': '𝗣𝗘𝗡𝗗𝗜𝗡𝗚', 'ru': '𝗢𝗝𝗜𝗗𝗔𝗬𝗨𝗦𝗛𝗜𝗬', 'ar': 'معلق'}, '𝗦𝗘𝗡𝗧': {'id': '𝗧𝗘𝗥𝗞𝗜𝗥𝗜𝗠', 'en': '𝗦𝗘𝗡𝗧', 'ru': '𝗢𝗧𝗣𝗥𝗔𝗩𝗟𝗘𝗡𝗢', 'ar': 'تم الإرسال'}, '𝗔𝗗𝗗 𝗩𝗜𝗣': {'id': '𝗧𝗔𝗠𝗕𝗔𝗛 𝗩𝗜𝗣', 'en': '𝗔𝗗𝗗 𝗩𝗜𝗣', 'ru': '𝗗𝗢𝗕𝗔𝗩𝗜𝗧𝗬 𝗩𝗜𝗣', 'ar': 'إضافة VIP'}, '𝗥𝗘𝗠 𝗩𝗜𝗣': {'id': '𝗛𝗔𝗣𝗨𝗦 𝗩𝗜𝗣', 'en': '𝗥𝗘𝗠 𝗩𝗜𝗣', 'ru': '𝗨𝗗𝗔𝗟𝗜𝗧𝗬 𝗩𝗜𝗣', 'ar': 'إزالة VIP'}, '𝗨𝗣𝗗𝗔𝗧𝗘 𝗕𝗢𝗧 𝗣𝗛𝗢𝗧𝗢': {'id': '𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜 𝗙𝗢𝗧𝗢 𝗕𝗢𝗧', 'en': '𝗨𝗣𝗗𝗔𝗧𝗘 𝗕𝗢𝗧 𝗣𝗛𝗢𝗧𝗢', 'ru': '𝗢𝗕𝗡𝗢𝗩𝗜𝗧𝗬 𝗙𝗢𝗧𝗢 𝗕𝗢𝗧𝗔', 'ar': 'تحديث صورة البوت'}, '𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗠𝗔𝗦𝗞𝗬': {'id': '𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗠𝗔𝗦𝗞𝗬', 'en': '𝗠𝗔𝗦𝗞𝗬 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧', 'ru': '𝗥𝗔𝗦𝗦𝗬𝗟𝗞𝗔 MASKYY', 'ar': '𝗕𝗧𝗛 MASKYY'}, '𝗧𝗘𝗫𝗧 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗠𝗔𝗦𝗞𝗬': {'id': '𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗧𝗘𝗞𝗦 MASKY', 'en': '𝗠𝗔𝗦𝗞𝗬 𝗧𝗘𝗫𝗧 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧', 'ru': '𝗧𝗘𝗞𝗦𝗧𝗢𝗩𝗔𝗬𝗔 𝗥𝗔𝗦𝗦𝗬𝗟𝗞𝗔 MASKYY', 'ar': '𝗕𝗧𝗛 𝗡𝗦𝗦𝗬 MASKYY'}, '𝗣𝗛𝗢𝗧𝗢 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗠𝗔𝗦𝗞𝗬': {'id': '𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗙𝗢𝗧𝗢 MASKY', 'en': '𝗠𝗔𝗦𝗞𝗬 𝗣𝗛𝗢𝗧𝗢 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧', 'ru': '𝗙𝗢𝗧𝗢-𝗥𝗔𝗦𝗦𝗬𝗟𝗞𝗔 MASKYY', 'ar': '𝗕𝗧𝗛 𝗦𝗢𝗥 MASKYY'}, '𝗖𝗨𝗦𝗧𝗢𝗠 𝗘𝗫𝗣𝗜𝗥𝗬': {'id': '𝗠𝗔𝗦𝗔 𝗕𝗘𝗥𝗟𝗔𝗞𝗨 𝗞𝗨𝗦𝗧𝗢𝗠', 'en': '𝗖𝗨𝗦𝗧𝗢𝗠 𝗘𝗫𝗣𝗜𝗥𝗬', 'ru': '𝗣𝗥𝗢𝗜𝗭𝗩𝗢𝗟Ь𝗡𝗢𝗬 𝗦𝗥𝗢𝗞', 'ar': '𝗠𝗗𝗗𝗔 𝗦𝗟𝗔𝗛𝗜𝗬𝗔 𝗠𝗞𝗛𝗦𝗦'}, '𝗔𝗖𝗖𝗘𝗦𝗦 𝗘𝗫𝗣𝗜𝗥𝗬': {'id': '𝗠𝗔𝗦𝗔 𝗕𝗘𝗥𝗟𝗔𝗞𝗨 𝗔𝗞𝗦𝗘𝗦', 'en': '𝗔𝗖𝗖𝗘𝗦𝗦 𝗘𝗫𝗣𝗜𝗥𝗬', 'ru': '𝗜𝗦𝗧𝗘𝗖𝗛𝗘𝗡𝗜𝗘 𝗗𝗢𝗦𝗧𝗨𝗣𝗔', 'ar': 'انتهاء صلاحية الوصول'}, '𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗨𝗣𝗗𝗔𝗧𝗘𝗗': {'id': '𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜', 'en': '𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗨𝗣𝗗𝗔𝗧𝗘𝗗', 'ru': '𝗧𝗠 𝗧𝗛𝗗𝗬𝗧𝗛', 'ar': 'تم تحديث كلمة المرور'}, '𝗖𝗟𝗢𝗡𝗘 𝗙𝗔𝗜𝗟𝗘𝗗': {'id': '𝗞𝗟𝗢𝗡𝗜𝗡𝗚 𝗚𝗔𝗚𝗔𝗟', 'en': '𝗖𝗟𝗢𝗡𝗘 𝗙𝗔𝗜𝗟𝗘𝗗', 'ru': '𝗢𝗦𝗛𝗜𝗕𝗞𝗔 𝗞𝗟𝗢𝗡𝗜𝗥𝗢𝗩𝗔𝗡𝗜𝗬𝗔', 'ar': 'فشل النسخ'}, 'Source login failed': {'id': 'Login sumber gagal', 'en': 'Source login failed', 'ru': 'Не удалось войти в исходный аккаунт', 'ar': 'فشل تسجيل الدخول إلى المصدر'}, 'Target login failed': {'id': 'Login target gagal', 'en': 'Target login failed', 'ru': 'Не удалось войти в целевой аккаунт', 'ar': 'فشل تسجيل الدخول إلى الهدف'}, 'NO CARS': {'id': 'TIDAK ADA MOBIL', 'en': 'NO CARS', 'ru': 'НЕТ МАШИН', 'ar': 'لا توجد سيارات'}, 'Done!': {'id': 'Selesai!', 'en': 'Done!', 'ru': 'Готово!', 'ar': 'تم!'}, 'Refreshing...': {'id': 'Menyegarkan...', 'en': 'Refreshing...', 'ru': 'Обновление...', 'ar': 'جارٍ التحديث...'}, 'Invalid user ID.': {'id': 'User ID tidak valid.', 'en': 'Invalid user ID.', 'ru': 'Неверный ID пользователя.', 'ar': 'معرّف المستخدم غير صالح.'}, 'Masukkan jumlah hari yang valid, contoh: 45.': {'id': 'Masukkan jumlah hari yang valid, contoh: 45.', 'en': 'Enter a valid number of days, e.g. 45.', 'ru': 'Введите корректное количество дней, например 45.', 'ar': 'أدخل عدداً صالحاً من الأيام، مثل 45.'}, 'Bulk add cancelled: timed out waiting for user IDs.': {'id': 'Bulk add dibatalkan: waktu tunggu User ID habis.', 'en': 'Bulk add cancelled: timed out waiting for user IDs.', 'ru': 'Массовое добавление отменено: истекло время ожидания ID пользователей.', 'ar': 'تم إلغاء الإضافة الجماعية: انتهت مهلة انتظار معرّفات المستخدمين.'}, 'Loading & fixing account...': {'id': 'Memuat dan memperbaiki akun...', 'en': 'Loading & fixing account...', 'ru': 'Загрузка и исправление аккаунта...', 'ar': 'جارٍ تحميل وإصلاح الحساب...'}, 'Stats reset!': {'id': 'Statistik direset!', 'en': 'Stats reset!', 'ru': 'Статистика сброшена!', 'ar': 'تمت إعادة ضبط الإحصائيات!'}, '𝗞𝗜𝗖𝗞 ALL': {'id': '𝗞𝗘𝗟𝗨𝗔𝗥𝗞𝗔𝗡 𝗦𝗘𝗠𝗨𝗔', 'en': '𝗞𝗜𝗖𝗞 ALL', 'ru': '𝗜𝗦𝗞𝗟𝗬𝗨𝗖𝗛𝗜𝗧Ь 𝗩𝗦𝗘𝗞𝗛', 'ar': 'طرد الجميع'}, 'Custom Amount': {'id': 'Jumlah Custom', 'en': 'Custom Amount', 'ru': 'Своя сумма', 'ar': 'مبلغ مخصص'}, 'Sign In': {'id': 'Masuk', 'en': 'Sign In', 'ru': 'Войти', 'ar': 'تسجيل الدخول'}, 'Check Status': {'id': 'Cek Status', 'en': 'Check Status', 'ru': 'Проверить статус', 'ar': 'تحقق من الحالة'}, 'LANGUAGE': {'id': 'BAHASA', 'en': 'LANGUAGE', 'ru': 'ЯЗЫК', 'ar': 'اللغة'}, 'PLAYER ID': {'id': 'PLAYER ID', 'en': 'PLAYER ID', 'ru': 'ID ИГРОКА', 'ar': 'معرّف اللاعب'}, 'WINS': {'id': 'MENANG', 'en': 'WINS', 'ru': 'ПОБЕДЫ', 'ar': 'الانتصارات'}, 'LOSSES': {'id': 'KALAH', 'en': 'LOSSES', 'ru': 'ПОРАЖЕНИЯ', 'ar': 'الخسائر'}, 'BACK TO DASHBOARD': {'id': 'KEMBALI KE DASHBOARD', 'en': 'BACK TO DASHBOARD', 'ru': 'НАЗАД К ПАНЕЛИ', 'ar': 'العودة إلى لوحة التحكم'}, '+VIP': {'id': '+VIP', 'en': '+VIP', 'ru': '+VIP', 'ar': '+VIP'}, '-VIP': {'id': '-VIP', 'en': '-VIP', 'ru': '-VIP', 'ar': '-VIP'}, 'Broadcast': {'id': 'Siaran', 'en': 'Broadcast', 'ru': 'Рассылка', 'ar': 'البث'}, 'Maintenance': {'id': 'Pemeliharaan', 'en': 'Maintenance', 'ru': 'Обслуживание', 'ar': 'الصيانة'}}

# Add exact feature/admin labels that are constructed dynamically.
_FEATURE_LABELS = {
 "f_w16": {"id":"MESIN W16","en":"W16 ENGINE","ru":"ДВИГАТЕЛЬ W16","ar":"محرك W16"},
 "f_horns": {"id":"KLAKSON","en":"HORNS","ru":"КЛАКСОН","ar":"البوق"},
 "f_damage": {"id":"TANPA KERUSAKAN","en":"NO DAMAGE","ru":"БЕЗ УРОНА","ar":"بدون ضرر"},
 "f_fuel": {"id":"BAHAN BAKAR TAK TERBATAS","en":"UNLIMITED FUEL","ru":"БЕСКОНЕЧНОЕ ТОПЛИВО","ar":"وقود غير محدود"},
 "f_smoke": {"id":"ASAP","en":"SMOKE","ru":"ДЫМ","ar":"دخان"},
 "f_anims": {"id":"ANIMASI","en":"ANIMATIONS","ru":"АНИМАЦИИ","ar":"الحركات"},
 "f_wheels": {"id":"RODA","en":"WHEELS","ru":"КОЛЁСА","ar":"العجلات"},
 "f_houses": {"id":"RUMAH","en":"HOUSES","ru":"ДОМА","ar":"المنازل"},
 "f_levels": {"id":"SEMUA LEVEL","en":"ALL LEVELS","ru":"ВСЕ УРОВНИ","ar":"جميع المستويات"},
 "f_rank": {"id":"RANK MAKSIMAL","en":"MAX RANK","ru":"МАКСИМАЛЬНЫЙ РАНГ","ar":"أعلى رتبة"},
 "f_headlights": {"id":"LAMPU DEPAN","en":"HEADLIGHTS","ru":"ФАРЫ","ar":"المصابيح الأمامية"},
 "f_clothes": {"id":"SEMUA PAKAIAN","en":"ALL CLOTHES","ru":"ВСЯ ОДЕЖДА","ar":"جميع الملابس"},
}

# Exact phrases found during the dedicated ADMIN + FEATURES audit.
# These are deliberately explicit so headings/cards do not remain mixed-language.
_ADMIN_FEATURE_EXACT = {
 "en": {
  "✗ Sign in first!":"✗ Sign in first!", "𝗦𝗜𝗚𝗡 𝗢𝗨𝗧":"𝗦𝗜𝗚𝗡 𝗢𝗨𝗧", "✗ Cancelled":"✗ Cancelled",
  "SETTINGS BOT MASKYY":"SETTINGS BOT MASKYY", "Account Management Center":"Account Management Center", "CPM ACCOUNT":"CPM ACCOUNT",
  "ACCOUNT CONTROL CENTER":"ACCOUNT CONTROL CENTER", "Update account name":"Update account name", "Manage Player ID":"Manage Player ID", "Change account email":"Change account email", "Change account password":"Change account password", "Clone account":"Clone account", "Update wins / losses":"Update wins / losses", "Repair account data":"Repair account data", "SELECT AN OPTION BELOW":"SELECT AN OPTION BELOW", "Manage your CPM account settings using the buttons below.":"Manage your CPM account settings using the buttons below.",
  "UNBANNED":"UNBANNED", "No pending requests.":"No pending requests.", "Send the user IDs (one per line).":"Send the user IDs (one per line).", "Send /cancel to cancel.":"Send /cancel to cancel.", "ADDED":"ADDED", "No admin access.":"No admin access.", "Bulk add cancelled.":"Bulk add cancelled.", "Empty submission. Send one user ID per line, or /cancel to cancel.":"Empty submission. Send one user ID per line, or /cancel to cancel.", "BULK_ADDED":"BULK ADDED", "⚠ Storage write failed. The IDs were added in memory, but saving to disk failed. Check the bot logs.":"⚠ Storage write failed. The IDs were added in memory, but saving to disk failed. Check the bot logs.",
  "BANNED":"BANNED", "KICKED":"KICKED", "𝗞𝗜𝗖𝗞 ALL":"𝗞𝗜𝗖𝗞 ALL", "No ordinary users to kick.":"No ordinary users to kick.", "KICKED_ALL":"KICKED ALL", "All ordinary users have been removed from bot access.":"All ordinary users have been removed from bot access.",
  "⚠️ Sudah expired":"⚠️ Expired", "⚠️ Data expiry tidak valid":"⚠️ Invalid expiry data", "♾️ Tidak ada expiry":"♾️ No expiry", "Pilih masa akses:":"Choose access duration:", "Masukkan jumlah hari custom.":"Enter custom number of days.", "Contoh:":"Example:", "untuk 45 hari.":"for 45 days.", "Masukkan":"Enter", "untuk menghapus expiry.":"to remove expiry.", "Expiry berhasil disimpan.":"Expiry saved successfully.", "Expiry berhasil dihapus.":"Expiry removed successfully.", "Custom expiry berhasil disimpan.":"Custom expiry saved successfully.",
  "USER PROFILE":"USER PROFILE", "💎 Yes":"💎 Yes", "🚫 Banned":"🚫 Banned", "✔ Allowed":"✔ Allowed", "⏳ Pending":"⏳ Pending", "None":"None",
  "ADD_VIP":"ADD VIP", "REM VIP":"REMOVE VIP", "You are now VIP!":"You are now VIP!", "UPDATE_PHOTO":"UPDATE PHOTO", "Current photo is set.":"Current photo is set.", "Send a new photo to update it.":"Send a new photo to update it.", "This photo shows on welcome screen.":"This photo shows on welcome screen.", "Bot welcome photo updated!":"Bot welcome photo updated!", "It will show for new users.":"It will show for new users.", "TEXT BROADCAST MASKY":"TEXT BROADCAST MASKY", "VIP BROADCAST MASKY":"VIP BROADCAST MASKY", "PHOTO BROADCAST MASKY":"PHOTO BROADCAST MASKY", "Send a photo:":"Send a photo:", "Photo received!":"Photo received!", "Type caption:":"Type caption:", "URL set!":"URL set!",
  "ADD ADMIN":"ADD ADMIN", "REM ADMIN":"REMOVE ADMIN", "Select role for":"Select role for", "Cannot remove owner!":"Cannot remove owner!", "demoted!":"demoted!", "Maintenance:":"Maintenance:", "OFF":"OFF", "Stats reset!":"Stats reset!",
  "▸ Home":"▸ Home", "◂ Home":"◂ Home", "◂ Admin Panel":"◂ Admin Panel", "◂ Back":"◂ Back", "◂ BACK TO DASHBOARD":"◂ BACK TO DASHBOARD",
 },
 "ru": {
  "✗ Sign in first!":"✗ Сначала войдите!", "𝗦𝗜𝗚𝗡 𝗢𝗨𝗧":"𝗩𝗬𝗛𝗢𝗗", "✗ Cancelled":"✗ Отменено",
  "SETTINGS BOT MASKYY":"НАСТРОЙКИ БОТА MASKYY", "Account Management Center":"Центр управления аккаунтом", "CPM ACCOUNT":"АККАУНТ CPM", "ACCOUNT CONTROL CENTER":"ЦЕНТР УПРАВЛЕНИЯ АККАУНТОМ", "Update account name":"Изменить имя аккаунта", "Manage Player ID":"Управить ID игрока", "Change account email":"Изменить email аккаунта", "Change account password":"Изменить пароль аккаунта", "Clone account":"Клонировать аккаунт", "Update wins / losses":"Изменить победы / поражения", "Repair account data":"Исправить данные аккаунта", "SELECT AN OPTION BELOW":"ВЫБЕРИТЕ ВАРИАНТ НИЖЕ", "Manage your CPM account settings using the buttons below.":"Управляйте настройками аккаунта CPM с помощью кнопок ниже.",
  "UNBANNED":"РАЗБЛОКИРОВАН", "No pending requests.":"Нет ожидающих запросов.", "Send the user IDs (one per line).":"Отправьте ID пользователей (по одному в строке).", "Send /cancel to cancel.":"Отправьте /cancel для отмены.", "ADDED":"ДОБАВЛЕН", "No admin access.":"Нет доступа администратора.", "Bulk add cancelled.":"Массовое добавление отменено.", "Empty submission. Send one user ID per line, or /cancel to cancel.":"Пустая отправка. Отправьте по одному ID в строке или /cancel для отмены.", "BULK_ADDED":"ДОБАВЛЕНО МАССОВО", "⚠ Storage write failed. The IDs were added in memory, but saving to disk failed. Check the bot logs.":"⚠ Не удалось сохранить данные. ID добавлены в память, но запись на диск не удалась. Проверьте логи бота.",
  "BANNED":"ЗАБЛОКИРОВАН", "KICKED":"ИСКЛЮЧЁН", "𝗞𝗜𝗖𝗞 ALL":"𝗜𝗦𝗞𝗟𝗬𝗨𝗖𝗛𝗜𝗧𝗕 𝗩𝗦𝗘𝗛", "No ordinary users to kick.":"Нет обычных пользователей для исключения.", "KICKED_ALL":"ВСЕ ИСКЛЮЧЕНЫ", "All ordinary users have been removed from bot access.":"Все обычные пользователи удалены из доступа к боту.",
  "⚠️ Sudah expired":"⚠️ Срок истёк", "⚠️ Data expiry tidak valid":"⚠️ Неверные данные срока", "♾️ Tidak ada expiry":"♾️ Без срока", "Pilih masa akses:":"Выберите срок доступа:", "Masukkan jumlah hari custom.":"Введите количество дней.", "Contoh:":"Пример:", "untuk 45 hari.":"для 45 дней.", "Masukkan":"Введите", "untuk menghapus expiry.":"для удаления срока.", "Expiry berhasil disimpan.":"Срок действия сохранён.", "Expiry berhasil dihapus.":"Срок действия удалён.", "Custom expiry berhasil disimpan.":"Пользовательский срок сохранён.",
  "USER PROFILE":"ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ", "💎 Yes":"💎 Да", "🚫 Banned":"🚫 Заблокирован", "✔ Allowed":"✔ Разрешён", "⏳ Pending":"⏳ Ожидает", "None":"Нет",
  "ADD_VIP":"ДОБАВИТЬ VIP", "REM VIP":"УДАЛИТЬ VIP", "You are now VIP!":"Теперь вы VIP!", "UPDATE_PHOTO":"ОБНОВИТЬ ФОТО", "Current photo is set.":"Текущее фото установлено.", "Send a new photo to update it.":"Отправьте новое фото для обновления.", "This photo shows on welcome screen.":"Это фото будет показано на экране приветствия.", "Bot welcome photo updated!":"Фото приветствия бота обновлено!", "It will show for new users.":"Оно будет показано новым пользователям.", "TEXT BROADCAST MASKY":"ТЕКСТОВАЯ РАССЫЛКА MASKY", "VIP BROADCAST MASKY":"VIP-РАССЫЛКА MASKY", "PHOTO BROADCAST MASKY":"ФОТО-РАССЫЛКА MASKY", "Send a photo:":"Отправьте фото:", "Photo received!":"Фото получено!", "Type caption:":"Введите подпись:", "URL set!":"URL установлен!",
  "ADD ADMIN":"ДОБАВИТЬ АДМИНИСТРАТОРА", "REM ADMIN":"УДАЛИТЬ АДМИНИСТРАТОРА", "Select role for":"Выберите роль для", "Cannot remove owner!":"Нельзя удалить владельца!", "demoted!":"роль понижена!", "Maintenance:":"Обслуживание:", "OFF":"ВЫКЛ", "Stats reset!":"Статистика сброшена!", "▸ Home":"▸ Главная", "◂ Home":"◂ Главная", "◂ Admin Panel":"◂ Панель администратора", "◂ Back":"◂ Назад", "◂ BACK TO DASHBOARD":"◂ НАЗАД К ПАНЕЛИ",
 },
 "ar": {
  "✗ Sign in first!":"✗ سجّل الدخول أولاً!", "𝗦𝗜𝗚𝗡 𝗢𝗨𝗧":"تسجيل الخروج", "✗ Cancelled":"✗ تم الإلغاء",
  "SETTINGS BOT MASKYY":"إعدادات بوت MASKYY", "Account Management Center":"مركز إدارة الحساب", "CPM ACCOUNT":"حساب CPM", "ACCOUNT CONTROL CENTER":"مركز التحكم بالحساب", "Update account name":"تحديث اسم الحساب", "Manage Player ID":"إدارة معرّف اللاعب", "Change account email":"تغيير بريد الحساب", "Change account password":"تغيير كلمة مرور الحساب", "Clone account":"نسخ الحساب", "Update wins / losses":"تحديث الانتصارات / الخسائر", "Repair account data":"إصلاح بيانات الحساب", "SELECT AN OPTION BELOW":"اختر خياراً أدناه", "Manage your CPM account settings using the buttons below.":"أدر إعدادات حساب CPM باستخدام الأزرار أدناه.",
  "UNBANNED":"تم إلغاء الحظر", "No pending requests.":"لا توجد طلبات معلقة.", "Send the user IDs (one per line).":"أرسل معرّفات المستخدمين (واحداً في كل سطر).", "Send /cancel to cancel.":"أرسل /cancel للإلغاء.", "ADDED":"تمت الإضافة", "No admin access.":"لا توجد صلاحية مسؤول.", "Bulk add cancelled.":"تم إلغاء الإضافة الجماعية.", "Empty submission. Send one user ID per line, or /cancel to cancel.":"الإرسال فارغ. أرسل معرّفاً واحداً في كل سطر أو /cancel للإلغاء.", "BULK_ADDED":"تمت الإضافة دفعة واحدة", "⚠ Storage write failed. The IDs were added in memory, but saving to disk failed. Check the bot logs.":"⚠ فشل حفظ البيانات. تمت إضافة المعرّفات في الذاكرة، لكن تعذر الحفظ على القرص. تحقق من سجلات البوت.",
  "BANNED":"محظور", "KICKED":"تم الطرد", "𝗞𝗜𝗖𝗞 ALL":"𝗧𝗥𝗗 𝗔𝗟𝗝𝗠𝗜𝗔", "No ordinary users to kick.":"لا يوجد مستخدمون عاديون للطرد.", "KICKED_ALL":"تم طرد الجميع", "All ordinary users have been removed from bot access.":"تمت إزالة جميع المستخدمين العاديين من الوصول إلى البوت.",
  "⚠️ Sudah expired":"⚠️ انتهت الصلاحية", "⚠️ Data expiry tidak valid":"⚠️ بيانات انتهاء الصلاحية غير صالحة", "♾️ Tidak ada expiry":"♾️ بدون انتهاء", "Pilih masa akses:":"اختر مدة الوصول:", "Masukkan jumlah hari custom.":"أدخل عدد الأيام المخصص.", "Contoh:":"مثال:", "untuk 45 hari.":"لمدة 45 يوماً.", "Masukkan":"أدخل", "untuk menghapus expiry.":"لإزالة انتهاء الصلاحية.", "Expiry berhasil disimpan.":"تم حفظ مدة الصلاحية بنجاح.", "Expiry berhasil dihapus.":"تم حذف مدة الصلاحية بنجاح.", "Custom expiry berhasil disimpan.":"تم حفظ مدة الصلاحية المخصصة.",
  "USER PROFILE":"ملف المستخدم", "💎 Yes":"💎 نعم", "🚫 Banned":"🚫 محظور", "✔ Allowed":"✔ مسموح", "⏳ Pending":"⏳ معلق", "None":"لا يوجد",
  "ADD_VIP":"إضافة VIP", "REM VIP":"إزالة VIP", "You are now VIP!":"أصبحت الآن VIP!", "UPDATE_PHOTO":"تحديث الصورة", "Current photo is set.":"تم تعيين الصورة الحالية.", "Send a new photo to update it.":"أرسل صورة جديدة لتحديثها.", "This photo shows on welcome screen.":"ستظهر هذه الصورة على شاشة الترحيب.", "Bot welcome photo updated!":"تم تحديث صورة ترحيب البوت!", "It will show for new users.":"ستظهر للمستخدمين الجدد.", "TEXT BROADCAST MASKY":"بث نصي MASKY", "VIP BROADCAST MASKY":"بث VIP MASKY", "PHOTO BROADCAST MASKY":"بث صور MASKY", "Send a photo:":"أرسل صورة:", "Photo received!":"تم استلام الصورة!", "Type caption:":"اكتب الوصف:", "URL set!":"تم تعيين الرابط!",
  "ADD ADMIN":"إضافة مسؤول", "REM ADMIN":"إزالة مسؤول", "Select role for":"اختر الدور لـ", "Cannot remove owner!":"لا يمكن إزالة المالك!", "demoted!":"تم خفض الرتبة!", "Maintenance:":"الصيانة:", "OFF":"متوقف", "Stats reset!":"تمت إعادة ضبط الإحصائيات!", "▸ Home":"▸ الرئيسية", "◂ Home":"◂ الرئيسية", "◂ Admin Panel":"◂ لوحة المسؤول", "◂ Back":"◂ رجوع", "◂ BACK TO DASHBOARD":"◂ العودة إلى لوحة التحكم",
 }
}
for _lg, _vals in _ADMIN_FEATURE_EXACT.items():
    MANUAL_UI.setdefault(_lg, {}).update(_vals)

# Custom-time localization. The same source keys are used by runtime translation.
_CUSTOM_TIME_UI = {
    "id": {
        "Custom Time":"Waktu Kustom", "Custom Day":"Waktu Kustom",
        "Masukkan durasi kustom.":"Masukkan durasi kustom.",
        "Contoh: 30 minutes, 7 days, 2 months, lifetime.":"Contoh: 30 menit, 7 hari, 2 bulan, lifetime.",
        "Masukkan lifetime untuk akses tanpa batas.":"Masukkan lifetime untuk akses tanpa batas.",
        "Format tidak valid.":"Format tidak valid.",
        "Durasi harus lebih dari 0.":"Durasi harus lebih dari 0.",
        "Lifetime access":"Akses seumur hidup", "Lifetime":"Seumur Hidup",
        "minute":"menit", "minutes":"menit", "day":"hari", "days":"hari", "month":"bulan", "months":"bulan",
    },
    "en": {
        "Custom Time":"Custom Time", "Custom Day":"Custom Time",
        "Masukkan durasi kustom.":"Enter a custom duration.",
        "Contoh: 30 minutes, 7 days, 2 months, lifetime.":"Example: 30 minutes, 7 days, 2 months, lifetime.",
        "Masukkan lifetime untuk akses tanpa batas.":"Enter lifetime for unlimited access.",
        "Format tidak valid.":"Invalid format.",
        "Durasi harus lebih dari 0.":"Duration must be greater than 0.",
        "Lifetime access":"Lifetime access", "Lifetime":"Lifetime",
    },
    "ru": {
        "Custom Time":"Пользовательский срок", "Custom Day":"Пользовательский срок",
        "Masukkan durasi kustom.":"Введите пользовательский срок.",
        "Contoh: 30 minutes, 7 days, 2 months, lifetime.":"Пример: 30 минут, 7 дней, 2 месяца, lifetime.",
        "Masukkan lifetime untuk akses tanpa batas.":"Введите lifetime для бессрочного доступа.",
        "Format tidak valid.":"Неверный формат.",
        "Durasi harus lebih dari 0.":"Срок должен быть больше 0.",
        "Lifetime access":"Бессрочный доступ", "Lifetime":"Бессрочно",
    },
    "ar": {
        "Custom Time":"مدة مخصصة", "Custom Day":"مدة مخصصة",
        "Masukkan durasi kustom.":"أدخل مدة مخصصة.",
        "Contoh: 30 minutes, 7 days, 2 months, lifetime.":"مثال: 30 دقيقة، 7 أيام، شهران، lifetime.",
        "Masukkan lifetime untuk akses tanpa batas.":"أدخل lifetime للوصول غير المحدود.",
        "Format tidak valid.":"تنسيق غير صالح.",
        "Durasi harus lebih dari 0.":"يجب أن تكون المدة أكبر من 0.",
        "Lifetime access":"وصول مدى الحياة", "Lifetime":"مدى الحياة",
    },
}
for _lg, _vals in _CUSTOM_TIME_UI.items():
    MANUAL_UI.setdefault(_lg, {}).update(_vals)


# ═══════════════════════════════════════════
# 🔎 FINAL WHOLE-BOT AUDIT PHRASES
# Covers /start → access → login → dashboard → money/coins/features/settings
# → admin → broadcast → commands → logout. Dynamic IDs/names/values are untouched.
# ═══════════════════════════════════════════
_AUDIT_TRANSLATIONS = {
 "id": {
  "SELECT LANGUAGE":"PILIH BAHASA", "Silakan pilih bahasa terlebih dahulu.":"Silakan pilih bahasa terlebih dahulu.", "Please select your language first.":"Silakan pilih bahasa terlebih dahulu.",
  "LANGUAGE SELECTED":"BAHASA DIPILIH", "Loading...":"Memuat...", "Access expired.":"Akses telah kedaluwarsa.", "Your access has ended.":"Masa akses Anda telah berakhir.", "Request Access":"Minta Akses",
  "Request pending. Wait for admin.":"Permintaan sedang menunggu. Tunggu admin.", "Request sent!":"Permintaan terkirim!", "You'll be notified.":"Anda akan diberi tahu.",
  "No permission":"Tidak memiliki izin", "No access!":"Tidak memiliki akses!", "Request declined.":"Permintaan ditolak.",
  "Still pending.":"Masih menunggu.", "Your ID:":"ID Anda:", "Invalid language.":"Bahasa tidak valid.", "Failed to save language.":"Gagal menyimpan bahasa.",
  "Are you sure?":"Apakah Anda yakin?", "Successfully signed out.":"Berhasil keluar.", "Sign in first!":"Masuk terlebih dahulu!",
  "Wait ":"Tunggu ", "Max:":"Maks:", "Enter amount (1 —":"Masukkan jumlah (1 —", "Setting $":"Mengatur $", "Setting ":"Mengatur ",
  "Enter 1 —":"Masukkan 1 —", "Refreshing...":"Menyegarkan...", "Refreshed!":"Diperbarui!", "Try again.":"Coba lagi.",
  "Login success":"Login berhasil", "Tap Refresh to load data.":"Tekan Segarkan untuk memuat data.",
  "Sign in first!":"Masuk terlebih dahulu!", "Enter user ID:":"Masukkan User ID:", "Invalid user ID.":"User ID tidak valid.", "Invalid ID.":"ID tidak valid.",
  "No admin access.":"Tidak memiliki akses admin.", "No admin permission.":"Tidak memiliki izin admin.", "Admin only!":"Khusus Admin!", "Owner only!":"Khusus Owner!",
  "Cannot ban owner!":"Tidak dapat memblokir Owner!", "Cannot kick owner!":"Tidak dapat mengeluarkan Owner!", "Cannot remove owner!":"Tidak dapat menghapus Owner!",
  "Access removed.":"Akses dihapus.", "No users to kick.":"Tidak ada user untuk dikeluarkan.", "All ordinary users have been removed from bot access.":"Semua user biasa telah dihapus dari akses bot.",
  "Kicked:":"Dikeluarkan:", "Admins kept:":"Admin dipertahankan:", "No ordinary users to kick.":"Tidak ada user biasa untuk dikeluarkan.",
  "Invalid expiry.":"Masa berlaku tidak valid.", "Durasi tidak tersedia.":"Durasi tidak tersedia.", "day expiry set.":"hari masa berlaku ditetapkan.",
  "Masukkan jumlah hari yang valid, contoh: 45.":"Masukkan jumlah hari yang valid, contoh: 45.", "User ID tidak ditemukan.":"User ID tidak ditemukan.",
  "Expiry berhasil disimpan.":"Masa berlaku berhasil disimpan.", "Expiry berhasil dihapus.":"Masa berlaku berhasil dihapus.", "Custom expiry berhasil disimpan.":"Masa berlaku kustom berhasil disimpan.",
  "Pilih masa akses:":"Pilih masa akses:", "Masukkan jumlah hari custom.":"Masukkan jumlah hari kustom.", "untuk 45 hari.":"untuk 45 hari.", "untuk menghapus expiry.":"untuk menghapus masa berlaku.",
  "No pending requests.":"Tidak ada permintaan yang menunggu.", "pending:":"menunggu:", "No activity yet.":"Belum ada aktivitas.", "User tersebut sudah tidak diban.":"User tersebut sudah tidak diblokir.",
  "berhasil di-unban.":"berhasil dibuka blokirnya.", "Invalid user ID.":"User ID tidak valid.", "User not found.":"User tidak ditemukan.",
  "Send the user IDs (one per line).":"Kirim User ID (satu per baris).", "Send /cancel to cancel.":"Kirim /cancel untuk membatalkan.", "Bulk add cancelled.":"Tambah massal dibatalkan.",
  "Empty submission. Send one user ID per line, or /cancel to cancel.":"Input kosong. Kirim satu User ID per baris, atau /cancel untuk membatalkan.",
  "Added:":"Ditambahkan:", "Already existed:":"Sudah ada:", "Invalid IDs:":"ID tidak valid:", "Total processed:":"Total diproses:", "Duplicates ignored:":"Duplikat diabaikan:",
  "Storage write failed.":"Gagal menyimpan data.", "The IDs were added in memory, but saving to disk failed. Check the bot logs.":"ID ditambahkan di memori, tetapi gagal disimpan ke disk. Periksa log bot.",
  "Bulk Add Complete":"Tambah Massal Selesai", "... and ":"... dan ", " more":" lainnya",
  "Cannot ban owner!":"Tidak dapat memblokir Owner!", "banned!":"diblokir!", "unbanned!":"dibuka blokirnya!", "kicked!":"dikeluarkan!", "added!":"ditambahkan!",
  "Current photo is set.":"Foto saat ini sudah terpasang.", "Send a new photo to update it.":"Kirim foto baru untuk memperbaruinya.", "This photo shows on welcome screen.":"Foto ini akan tampil di layar sambutan.",
  "Bot welcome photo updated!":"Foto sambutan bot berhasil diperbarui!", "It will show for new users.":"Foto akan tampil untuk user baru.",
  "Message to all":"Pesan untuk semua", "Message to":"Pesan untuk", "VIPs:":"VIP:", "Send a photo:":"Kirim foto:", "Photo received!":"Foto diterima!", "Type caption:":"Ketik caption:", "URL set!":"URL ditetapkan!",
  "Done!":"Selesai!", "sent":"terkirim", "failed":"gagal", "Select role for":"Pilih role untuk", "Use /admin":"Gunakan /admin", "demoted!":"diturunkan rolenya!",
  "Maintenance:":"Maintenance:", "Stats reset!":"Statistik direset!", "You are now VIP!":"Anda sekarang VIP!", "VIP removed for":"VIP dihapus untuk",
  "UPDATE BOT PHOTO":"PERBARUI FOTO BOT", "PHOTO UPDATED":"FOTO DIPERBARUI", "ADD ADMIN":"TAMBAH ADMIN", "REM ADMIN":"HAPUS ADMIN",
  "𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟 𝗠𝗔𝗦𝗞𝗬":"𝗣𝗔𝗡𝗘𝗟 𝗔𝗗𝗠𝗜𝗡 𝗠𝗔𝗦𝗞𝗬", "𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟":"𝗣𝗔𝗡𝗘𝗟 𝗔𝗗𝗠𝗜𝗡", "𝗔𝗖𝗖𝗘𝗣𝗧𝗘𝗗":"𝗗ITERIMA", "𝗥𝗘𝗝𝗘𝗖𝗧𝗘𝗗":"𝗗𝗜𝗧𝗢𝗟𝗔𝗞",
  "𝗦𝗜𝗚𝗡 𝗢𝗨𝗧":"𝗞𝗘𝗟𝗨𝗔𝗥", "𝗦𝗜𝗚𝗡𝗘𝗗 𝗢𝗨𝗧":"𝗕𝗘𝗥𝗛𝗔𝗦𝗜𝗟 𝗞𝗘𝗟𝗨𝗔𝗥", "𝗘𝗫𝗣𝗜𝗥𝗬 𝗦𝗘𝗧":"𝗠𝗔𝗦𝗔 𝗕𝗘𝗥𝗟𝗔𝗞𝗨 𝗗𝗜𝗧𝗘𝗧𝗔𝗣𝗞𝗔𝗡", "𝗘𝗫𝗣𝗜𝗥𝗬 𝗥𝗘𝗠𝗢𝗩𝗘𝗗":"𝗠𝗔𝗦𝗔 𝗕𝗘𝗥𝗟𝗔𝗞𝗨 𝗗𝗜𝗛𝗔𝗣𝗨𝗦",
  "𝗞𝗜𝗖𝗞 ALL":"𝗞𝗘𝗟𝗨𝗔𝗥𝗞𝗔𝗡 𝗦𝗘𝗠𝗨𝗔", "𝗨𝗦𝗘𝗥 𝗣𝗥𝗢𝗙𝗜𝗟𝗘":"𝗣𝗥𝗢𝗙𝗜𝗟 𝗨𝗦𝗘𝗥", "𝗔𝗗𝗗 𝗩𝗜𝗣":"𝗧𝗔𝗠𝗕𝗔𝗛 𝗩𝗜𝗣", "𝗥𝗘𝗠 𝗩𝗜𝗣":"𝗛𝗔𝗣𝗨𝗦 𝗩𝗜𝗣",
  "𝗨𝗣𝗗𝗔𝗧𝗘 𝗕𝗢𝗧 𝗣𝗛𝗢𝗧𝗢":"𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜 𝗙𝗢𝗧𝗢 𝗕𝗢𝗧", "𝗧𝗘𝗫𝗧 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗠𝗔𝗦𝗞𝗬":"𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗧𝗘𝗞𝗦 𝗠𝗔𝗦𝗞𝗬", "𝗩𝗜𝗣 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗠𝗔𝗦𝗞𝗬":"𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗩𝗜𝗣 𝗠𝗔𝗦𝗞𝗬", "𝗣𝗛𝗢𝗧𝗢 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗠𝗔𝗦𝗞𝗬":"𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗙𝗢𝗧𝗢 𝗠𝗔𝗦𝗞𝗬",
  "𝗖𝗨𝗦𝗧𝗢𝗠 𝗘𝗫𝗣𝗜𝗥𝗬":"𝗠𝗔𝗦𝗔 𝗕𝗘𝗥𝗟𝗔𝗞𝗨 𝗞𝗨𝗦𝗧𝗢𝗠", "𝗔𝗖𝗖𝗘𝗦𝗦 𝗘𝗫𝗣𝗜𝗥𝗬":"𝗠𝗔𝗦𝗔 𝗕𝗘𝗥𝗟𝗔𝗞𝗨 𝗔𝗞𝗦𝗘𝗦", "𝗘𝗡𝗧𝗘𝗥 𝗘𝗠𝗔𝗜𝗟":"𝗠𝗔𝗦𝗨𝗞𝗞𝗔𝗡 𝗘𝗠𝗔𝗜𝗟", "𝗟𝗢𝗚𝗜𝗡 𝗙𝗔𝗜𝗟𝗘𝗗":"𝗟𝗢𝗚𝗜𝗡 𝗚𝗔𝗚𝗔𝗟",
  "𝗟𝗢𝗚𝗜𝗡 𝗦𝗨𝗖𝗖𝗘𝗦𝗦":"𝗟𝗢𝗚𝗜𝗡 𝗕𝗘𝗥𝗛𝗔𝗦𝗜𝗟", "𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘":"𝗦𝗘𝗟𝗘𝗦𝗔𝗜", "𝗙𝗘𝗔𝗧𝗨𝗥𝗘𝗦 𝗕𝗢𝗧 𝗠𝗔𝗦𝗞𝗬":"𝗙𝗜𝗧𝗨𝗥 𝗕𝗢𝗧 𝗠𝗔𝗦𝗞𝗬", "𝗨𝗡𝗟𝗢𝗖𝗞𝗜𝗡𝗚 𝗔𝗟𝗟":"𝗠𝗘𝗠𝗕𝗨𝗞𝗔 𝗦𝗘𝗠𝗨𝗔",
  "𝗖𝗛𝗔𝗡𝗚𝗘 𝗡𝗔𝗠𝗘":"𝗨𝗕𝗔𝗛 𝗡𝗔𝗠𝗔", "𝗡𝗔𝗠𝗘 𝗨𝗣𝗗𝗔𝗧𝗘𝗗":"𝗡𝗔𝗠𝗔 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜", "𝗣𝗟𝗔𝗬𝗘𝗥 𝗜𝗗":"𝗣𝗟𝗔𝗬𝗘𝗥 𝗜𝗗", "𝗜𝗗 𝗨𝗣𝗗𝗔𝗧𝗘𝗗":"𝗜𝗗 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜",
  "𝗦𝗘𝗧 𝗪𝗜𝗡𝗦":"𝗔𝗧𝗨𝗥 𝗠𝗘𝗡𝗔𝗡𝗚", "𝗪𝗜𝗡𝗦 𝗨𝗣𝗗𝗔𝗧𝗘𝗗":"𝗠𝗘𝗡𝗔𝗡𝗚 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜", "𝗦𝗘𝗧 𝗟𝗢𝗦𝗦𝗘𝗦":"𝗔𝗧𝗨𝗥 𝗞𝗔𝗟𝗔𝗛", "𝗟𝗢𝗦𝗦𝗘𝗦 𝗨𝗣𝗗𝗔𝗧𝗘𝗗":"𝗞𝗔𝗟𝗔𝗛 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜",
  "𝗖𝗛𝗔𝗡𝗚𝗘 𝗘𝗠𝗔𝗜𝗟":"𝗨𝗕𝗔𝗛 𝗘𝗠𝗔𝗜𝗟", "𝗘𝗠𝗔𝗜𝗟 𝗨𝗣𝗗𝗔𝗧𝗘𝗗":"𝗘𝗠𝗔𝗜𝗟 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜", "𝗖𝗛𝗔𝗡𝗚𝗘 𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗":"𝗨𝗕𝗔𝗛 𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗", "𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗨𝗣𝗗𝗔𝗧𝗘𝗗":"𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗥𝗨𝗜",
  "𝗖𝗟𝗢𝗡𝗘 𝗔𝗖𝗖𝗢𝗨𝗡𝗧":"𝗞𝗟𝗢𝗡𝗜𝗡𝗚 𝗔𝗞𝗨𝗡", "𝗖𝗟𝗢𝗡𝗘 𝗙𝗔𝗜𝗟𝗘𝗗":"𝗞𝗟𝗢𝗡𝗜𝗡𝗚 𝗚𝗔𝗚𝗔𝗟", "𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗙𝗜𝗫𝗘𝗗":"𝗔𝗞𝗨𝗡 𝗗𝗜𝗣𝗘𝗥𝗕𝗔𝗜𝗞𝗜",
  "𝗦𝗧𝗔𝗧𝗦 𝗢𝗩𝗘𝗥𝗩𝗜𝗘𝗪":"𝗥𝗜𝗡𝗚𝗞𝗔𝗦𝗔𝗡 𝗦𝗧𝗔𝗧𝗜𝗦𝗧𝗜𝗞", "𝗤𝗨𝗜𝗖𝗞 𝗠𝗘𝗡𝗨":"𝗠𝗘𝗡𝗨 𝗖𝗘𝗣𝗔𝗧", "DASBOARD BOT MASKYY":"DASHBOARD BOT MASKYY",
 },
 "en": {
  "SELECT LANGUAGE":"SELECT LANGUAGE", "Silakan pilih bahasa terlebih dahulu.":"Please select a language first.", "LANGUAGE SELECTED":"LANGUAGE SELECTED", "Loading...":"Loading...", "Access expired.":"Access expired.", "Your access has ended.":"Your access has ended.", "Request Access":"Request Access",
  "Request pending. Wait for admin.":"Request pending. Please wait for an admin.", "Request sent!":"Request sent!", "You'll be notified.":"You'll be notified.", "No permission":"No permission", "No access!":"No access!", "Request declined.":"Request declined.", "Still pending.":"Still pending.", "Your ID:":"Your ID:", "Invalid language.":"Invalid language.", "Failed to save language.":"Failed to save language.",
  "Are you sure?":"Are you sure?", "Successfully signed out.":"Successfully signed out.", "Sign in first!":"Sign in first!", "Wait ":"Wait ", "Max:":"Max:", "Enter amount (1 —":"Enter amount (1 —", "Setting $":"Setting $", "Setting ":"Setting ", "Enter 1 —":"Enter 1 —", "Refreshing...":"Refreshing...", "Refreshed!":"Refreshed!", "Try again.":"Try again.",
  "Enter user ID:":"Enter user ID:", "Invalid user ID.":"Invalid user ID.", "Invalid ID.":"Invalid ID.", "No admin access.":"No admin access.", "No admin permission.":"No admin permission.", "Admin only!":"Admin only!", "Owner only!":"Owner only!", "Cannot ban owner!":"Cannot ban owner!", "Cannot kick owner!":"Cannot kick owner!", "Cannot remove owner!":"Cannot remove owner!", "Access removed.":"Access removed.", "No users to kick.":"No users to kick!", "All ordinary users have been removed from bot access.":"All ordinary users have been removed from bot access.", "Kicked:":"Kicked:", "Admins kept:":"Admins kept:", "No ordinary users to kick.":"No ordinary users to kick.",
  "Pilih masa akses:":"Choose access duration:", "Masukkan jumlah hari custom.":"Enter a custom number of days.", "untuk 45 hari.":"for 45 days.", "untuk menghapus expiry.":"to remove expiry.", "Expiry berhasil disimpan.":"Expiry saved successfully.", "Expiry berhasil dihapus.":"Expiry removed successfully.", "Custom expiry berhasil disimpan.":"Custom expiry saved successfully.", "Durasi tidak tersedia.":"Duration unavailable.",
  "No pending requests.":"No pending requests.", "pending:":"pending:", "No activity yet.":"No activity yet.", "Send the user IDs (one per line).":"Send user IDs (one per line).", "Send /cancel to cancel.":"Send /cancel to cancel.", "Bulk add cancelled.":"Bulk add cancelled.", "Empty submission. Send one user ID per line, or /cancel to cancel.":"Empty submission. Send one user ID per line, or /cancel to cancel.", "Added:":"Added:", "Already existed:":"Already existed:", "Invalid IDs:":"Invalid IDs:", "Total processed:":"Total processed:", "Duplicates ignored:":"Duplicates ignored:", "Bulk Add Complete":"Bulk Add Complete", "... and ":"... and ", " more":" more",
  "Current photo is set.":"Current photo is set.", "Send a new photo to update it.":"Send a new photo to update it.", "This photo shows on welcome screen.":"This photo shows on the welcome screen.", "Bot welcome photo updated!":"Bot welcome photo updated!", "It will show for new users.":"It will show for new users.", "Message to all":"Message to all", "Message to":"Message to", "VIPs:":"VIPs:", "Send a photo:":"Send a photo:", "Photo received!":"Photo received!", "Type caption:":"Type a caption:", "URL set!":"URL set!", "Done!":"Done!", "Select role for":"Select role for", "Use /admin":"Use /admin", "demoted!":"demoted!", "Maintenance:":"Maintenance:", "Stats reset!":"Stats reset!", "You are now VIP!":"You are now VIP!", "VIP removed for":"VIP removed for",
  "𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟 𝗠𝗔𝗦𝗞𝗬":"𝗠𝗔𝗦𝗞𝗬 𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟", "𝗞𝗜𝗖𝗞 ALL":"𝗞𝗜𝗖𝗞 ALL", "𝗨𝗦𝗘𝗥 𝗣𝗥𝗢𝗙𝗜𝗟𝗘":"𝗨𝗦𝗘𝗥 𝗣𝗥𝗢𝗙𝗜𝗟𝗘", "𝗔𝗖𝗖𝗘𝗦𝗦 𝗘𝗫𝗣𝗜𝗥𝗬":"𝗔𝗖𝗖𝗘𝗦𝗦 𝗘𝗫𝗣𝗜𝗥𝗬", "𝗙𝗘𝗔𝗧𝗨𝗥𝗘𝗦 𝗕𝗢𝗧 𝗠𝗔𝗦𝗞𝗬":"𝗙𝗘𝗔𝗧𝗨𝗥𝗘𝗦 𝗕𝗢𝗧 𝗠𝗔𝗦𝗞𝗬", "𝗨𝗡𝗟𝗢𝗖𝗞𝗜𝗡𝗚 𝗔𝗟𝗟":"𝗨𝗡𝗟𝗢𝗖𝗞𝗜𝗡𝗚 𝗔𝗟𝗟", "𝗖𝗛𝗔𝗡𝗚𝗘 𝗡𝗔𝗠𝗘":"𝗖𝗛𝗔𝗡𝗚𝗘 𝗡𝗔𝗠𝗘", "𝗟𝗢𝗚𝗜𝗡 𝗙𝗔𝗜𝗟𝗘𝗗":"𝗟𝗢𝗚𝗜𝗡 𝗙𝗔𝗜𝗟𝗘𝗗", "𝗟𝗢𝗚𝗜𝗡 𝗦𝗨𝗖𝗖𝗘𝗦𝗦":"𝗟𝗢𝗚𝗜𝗡 𝗦𝗨𝗖𝗖𝗘𝗦𝗦", "𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘":"𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘", "𝗦𝗜𝗚𝗡 𝗢𝗨𝗧":"𝗦𝗜𝗚𝗡 OUT", "𝗦𝗜𝗚𝗡𝗘𝗗 𝗢𝗨𝗧":"𝗦𝗜𝗚𝗡ED OUT", "DASBOARD BOT MASKYY":"DASHBOARD BOT MASKYY",
 },
 "ru": {
  "SELECT LANGUAGE":"ВЫБЕРИТЕ ЯЗЫК", "Silakan pilih bahasa terlebih dahulu.":"Сначала выберите язык.", "Please select your language first.":"Сначала выберите язык.", "LANGUAGE SELECTED":"ЯЗЫК ВЫБРАН", "Loading...":"Загрузка...", "Access expired.":"Срок доступа истёк.", "Your access has ended.":"Срок вашего доступа закончился.", "Request Access":"Запросить доступ",
  "Request pending. Wait for admin.":"Запрос ожидает обработки. Подождите администратора.", "Request sent!":"Запрос отправлен!", "You'll be notified.":"Вы получите уведомление.", "No permission":"Нет разрешения", "No access!":"Нет доступа!", "Request declined.":"Запрос отклонён.", "Still pending.":"Всё ещё ожидается.", "Your ID:":"Ваш ID:", "Invalid language.":"Неверный язык.", "Failed to save language.":"Не удалось сохранить язык.",
  "Are you sure?":"Вы уверены?", "Successfully signed out.":"Вы успешно вышли.", "Sign in first!":"Сначала войдите!", "Wait ":"Подождите ", "Max:":"Макс.:", "Enter amount (1 —":"Введите сумму (1 —", "Setting $":"Установка $", "Setting ":"Установка ", "Enter 1 —":"Введите 1 —", "Refreshing...":"Обновление...", "Refreshed!":"Обновлено!", "Try again.":"Попробуйте снова.",
  "Enter user ID:":"Введите ID пользователя:", "Invalid user ID.":"Неверный ID пользователя.", "Invalid ID.":"Неверный ID.", "No admin access.":"Нет доступа администратора.", "No admin permission.":"Нет прав администратора.", "Admin only!":"Только администратор!", "Owner only!":"Только владелец!", "Cannot ban owner!":"Нельзя заблокировать владельца!", "Cannot kick owner!":"Нельзя исключить владельца!", "Cannot remove owner!":"Нельзя удалить владельца!", "Access removed.":"Доступ удалён.", "No users to kick.":"Нет пользователей для исключения.", "All ordinary users have been removed from bot access.":"Все обычные пользователи удалены из доступа к боту.", "Kicked:":"Исключено:", "Admins kept:":"Администраторов сохранено:", "No ordinary users to kick.":"Нет обычных пользователей для исключения.",
  "Pilih masa akses:":"Выберите срок доступа:", "Masukkan jumlah hari custom.":"Введите количество дней.", "untuk 45 hari.":"на 45 дней.", "untuk menghapus expiry.":"для удаления срока.", "Expiry berhasil disimpan.":"Срок действия сохранён.", "Expiry berhasil dihapus.":"Срок действия удалён.", "Custom expiry berhasil disimpan.":"Пользовательский срок сохранён.", "Durasi tidak tersedia.":"Срок недоступен.",
  "No pending requests.":"Нет ожидающих запросов.", "pending:":"ожидают:", "No activity yet.":"Активности пока нет.", "Send the user IDs (one per line).":"Отправьте ID пользователей по одному в строке.", "Send /cancel to cancel.":"Отправьте /cancel для отмены.", "Bulk add cancelled.":"Массовое добавление отменено.", "Empty submission. Send one user ID per line, or /cancel to cancel.":"Пустая отправка. Отправьте по одному ID в строке или /cancel для отмены.", "Added:":"Добавлено:", "Already existed:":"Уже существовали:", "Invalid IDs:":"Неверные ID:", "Total processed:":"Всего обработано:", "Duplicates ignored:":"Дубликаты пропущены:", "Bulk Add Complete":"Массовое добавление завершено", "... and ":"... и ", " more":" ещё",
  "Current photo is set.":"Текущее фото установлено.", "Send a new photo to update it.":"Отправьте новое фото для обновления.", "This photo shows on welcome screen.":"Это фото будет показано на экране приветствия.", "Bot welcome photo updated!":"Фото приветствия бота обновлено!", "It will show for new users.":"Оно будет показано новым пользователям.", "Message to all":"Сообщение всем", "Message to":"Сообщение для", "VIPs:":"VIP:", "Send a photo:":"Отправьте фото:", "Photo received!":"Фото получено!", "Type caption:":"Введите подпись:", "URL set!":"URL установлен!", "Done!":"Готово!", "Select role for":"Выберите роль для", "Use /admin":"Используйте /admin", "demoted!":"роль понижена!", "Maintenance:":"Обслуживание:", "Stats reset!":"Статистика сброшена!", "You are now VIP!":"Теперь вы VIP!", "VIP removed for":"VIP удалён для",
  "𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟 𝗠𝗔𝗦𝗞𝗬":"𝗔𝗗𝗠𝗜𝗡-ПАНЕЛЬ MASKYY", "𝗞𝗜𝗖𝗞 ALL":"𝗜𝗦𝗞𝗟𝗬𝗨𝗖𝗛𝗜𝗧Ь 𝗩𝗦𝗘𝗛", "𝗨𝗦𝗘𝗥 𝗣𝗥𝗢𝗙𝗜𝗟𝗘":"ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ", "𝗔𝗖𝗖𝗘𝗦𝗦 𝗘𝗫𝗣𝗜𝗥𝗬":"СРОК ДОСТУПА", "𝗙𝗘𝗔𝗧𝗨𝗥𝗘𝗦 𝗕𝗢𝗧 𝗠𝗔𝗦𝗞𝗬":"ФУНКЦИИ БОТА MASKYY", "𝗨𝗡𝗟𝗢𝗖𝗞𝗜𝗡𝗚 𝗔𝗟𝗟":"ОТКРЫТИЕ ВСЕХ ФУНКЦИЙ", "𝗖𝗛𝗔𝗡𝗚𝗘 𝗡𝗔𝗠𝗘":"ИЗМЕНЕНИЕ ИМЕНИ", "𝗟𝗢𝗚𝗜𝗡 𝗙𝗔𝗜𝗟𝗘𝗗":"ОШИБКА ВХОДА", "𝗟𝗢𝗚𝗜𝗡 𝗦𝗨𝗖𝗖𝗘??𝗦":"УСПЕШНЫЙ ВХОД", "𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘":"ЗАВЕРШЕНО", "𝗦𝗜𝗚𝗡 𝗢𝗨𝗧":"ВЫХОД", "𝗦𝗜𝗚𝗡𝗘𝗗 𝗢𝗨𝗧":"ВЫШЛИ УСПЕШНО", "DASBOARD BOT MASKYY":"ПАНЕЛЬ БОТА MASKYY",
 },
 "ar": {
  "SELECT LANGUAGE":"اختر اللغة", "Silakan pilih bahasa terlebih dahulu.":"يرجى اختيار اللغة أولاً.", "Please select your language first.":"يرجى اختيار اللغة أولاً.", "LANGUAGE SELECTED":"تم اختيار اللغة", "Loading...":"جارٍ التحميل...", "Access expired.":"انتهت صلاحية الوصول.", "Your access has ended.":"انتهت مدة وصولك.", "Request Access":"طلب الوصول",
  "Request pending. Wait for admin.":"الطلب قيد الانتظار. انتظر المسؤول.", "Request sent!":"تم إرسال الطلب!", "You'll be notified.":"سيتم إشعارك.", "No permission":"لا توجد صلاحية", "No access!":"لا يوجد وصول!", "Request declined.":"تم رفض الطلب.", "Still pending.":"لا يزال قيد الانتظار.", "Your ID:":"معرّفك:", "Invalid language.":"اللغة غير صالحة.", "Failed to save language.":"تعذر حفظ اللغة.",
  "Are you sure?":"هل أنت متأكد؟", "Successfully signed out.":"تم تسجيل الخروج بنجاح.", "Sign in first!":"سجّل الدخول أولاً!", "Wait ":"انتظر ", "Max:":"الحد الأقصى:", "Enter amount (1 —":"أدخل المبلغ (1 —", "Setting $":"جارٍ ضبط $", "Setting ":"جارٍ الضبط ", "Enter 1 —":"أدخل 1 —", "Refreshing...":"جارٍ التحديث...", "Refreshed!":"تم التحديث!", "Try again.":"حاول مرة أخرى.",
  "Enter user ID:":"أدخل معرّف المستخدم:", "Invalid user ID.":"معرّف المستخدم غير صالح.", "Invalid ID.":"المعرّف غير صالح.", "No admin access.":"لا توجد صلاحية مسؤول.", "No admin permission.":"لا توجد صلاحية إدارية.", "Admin only!":"للمسؤول فقط!", "Owner only!":"للمالك فقط!", "Cannot ban owner!":"لا يمكن حظر المالك!", "Cannot kick owner!":"لا يمكن طرد المالك!", "Cannot remove owner!":"لا يمكن إزالة المالك!", "Access removed.":"تمت إزالة الوصول.", "No users to kick.":"لا يوجد مستخدمون للطرد.", "All ordinary users have been removed from bot access.":"تمت إزالة جميع المستخدمين العاديين من الوصول إلى البوت.", "Kicked:":"تم الطرد:", "Admins kept:":"المسؤولون المحفوظون:", "No ordinary users to kick.":"لا يوجد مستخدمون عاديون للطرد.",
  "Pilih masa akses:":"اختر مدة الوصول:", "Masukkan jumlah hari custom.":"أدخل عدد الأيام المخصص.", "untuk 45 hari.":"لمدة 45 يوماً.", "untuk menghapus expiry.":"لإزالة انتهاء الصلاحية.", "Expiry berhasil disimpan.":"تم حفظ مدة الصلاحية.", "Expiry berhasil dihapus.":"تم حذف مدة الصلاحية.", "Custom expiry berhasil disimpan.":"تم حفظ مدة الصلاحية المخصصة.", "Durasi tidak tersedia.":"المدة غير متاحة.",
  "No pending requests.":"لا توجد طلبات معلقة.", "pending:":"معلقة:", "No activity yet.":"لا يوجد نشاط بعد.", "Send the user IDs (one per line).":"أرسل معرّفات المستخدمين، واحداً في كل سطر.", "Send /cancel to cancel.":"أرسل /cancel للإلغاء.", "Bulk add cancelled.":"تم إلغاء الإضافة الجماعية.", "Empty submission. Send one user ID per line, or /cancel to cancel.":"الإرسال فارغ. أرسل معرّفاً واحداً في كل سطر أو /cancel للإلغاء.", "Added:":"تمت الإضافة:", "Already existed:":"موجود مسبقاً:", "Invalid IDs:":"معرّفات غير صالحة:", "Total processed:":"إجمالي المعالجة:", "Duplicates ignored:":"تم تجاهل التكرارات:", "Bulk Add Complete":"اكتملت الإضافة الجماعية", "... and ":"... و", " more":" أخرى",
  "Current photo is set.":"تم تعيين الصورة الحالية.", "Send a new photo to update it.":"أرسل صورة جديدة للتحديث.", "This photo shows on welcome screen.":"ستظهر هذه الصورة على شاشة الترحيب.", "Bot welcome photo updated!":"تم تحديث صورة ترحيب البوت!", "It will show for new users.":"ستظهر للمستخدمين الجدد.", "Message to all":"رسالة للجميع", "Message to":"رسالة إلى", "VIPs:":"VIP:", "Send a photo:":"أرسل صورة:", "Photo received!":"تم استلام الصورة!", "Type caption:":"اكتب الوصف:", "URL set!":"تم تعيين الرابط!", "Done!":"تم!", "Select role for":"اختر الدور لـ", "Use /admin":"استخدم /admin", "demoted!":"تم خفض الرتبة!", "Maintenance:":"الصيانة:", "Stats reset!":"تمت إعادة ضبط الإحصائيات!", "You are now VIP!":"أصبحت الآن VIP!", "VIP removed for":"تمت إزالة VIP لـ",
  "𝗔𝗗𝗠𝗜𝗡 𝗣𝗔𝗡𝗘𝗟 𝗠𝗔𝗦𝗞𝗬":"𝗟𝗢𝗡𝗔𝗡𝗔 𝗠𝗔𝗦𝗞𝗬", "𝗞𝗜𝗖𝗞 ALL":"𝗧𝗥𝗗 𝗔𝗟𝗝𝗠𝗜𝗔", "𝗨𝗦𝗘𝗥 𝗣𝗥𝗢𝗙𝗜𝗟𝗘":"ملف المستخدم", "𝗔𝗖𝗖𝗘𝗦𝗦 𝗘𝗫𝗣𝗜𝗥𝗬":"صلاحية الوصول", "𝗙𝗘𝗔𝗧𝗨𝗥𝗘𝗦 𝗕𝗢𝗧 𝗠𝗔𝗦𝗞𝗬":"ميزات بوت MASKYY", "𝗨𝗡𝗟𝗢𝗖𝗞𝗜𝗡𝗚 𝗔𝗟𝗟":"فتح جميع الميزات", "𝗖𝗛𝗔𝗡𝗚𝗘 𝗡𝗔𝗠𝗘":"تغيير الاسم", "𝗟𝗢𝗚𝗜𝗡 𝗙𝗔𝗜𝗟𝗘𝗗":"فشل تسجيل الدخول", "𝗟𝗢𝗚𝗜𝗡 𝗦𝗨𝗖𝗖𝗘𝗦𝗦":"تم تسجيل الدخول بنجاح", "𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘":"اكتمل", "𝗦𝗜𝗚𝗡 𝗢𝗨𝗧":"تسجيل الخروج", "𝗦𝗜𝗚𝗡𝗘𝗗 𝗢𝗨𝗧":"تم تسجيل الخروج", "DASBOARD BOT MASKYY":"لوحة تحكم بوت MASKYY",
 }
}
for _lg, _vals in _AUDIT_TRANSLATIONS.items():
    MANUAL_UI.setdefault(_lg, {}).update(_vals)

def _lang_for(uid):
    try:
        return get_user_language(int(uid)) or "id"
    except Exception:
        return "id"

def manual_translate_text(uid, text):
    if text is None:
        return text
    raw = str(text)
    lang = _lang_for(uid)
    table = dict(MANUAL_UI.get(lang, MANUAL_UI["id"]))
    # Audit patch has priority for phrases found in actual UI handlers.
    for source, variants in AUDIT_TRANSLATIONS.items():
        target = variants.get(lang)
        if target is not None:
            table[source] = target
    for source, variants in AUDIT_TRANSLATIONS_MORE.items():
        target = variants.get(lang)
        if target is not None:
            table[source] = target
    # Longest first avoids replacing a fragment before its complete phrase.
    for source, target in sorted(table.items(), key=lambda kv: len(kv[0]), reverse=True):
        if source and source != target:
            raw = raw.replace(source, target)
    return raw

# Runtime translation fallback for every user-facing string.
# Manual translations are always preferred; only remaining text is sent to
# Google Translate so hard-coded UI strings cannot leak in another language.
_TRANSLATION_CACHE = {}
_TRANSLATION_CACHE_MAX = 2000
_TRANSLATION_TIMEOUT = aiohttp.ClientTimeout(total=4)

def _protect_markup(text):
    protected = []
    def repl(m):
        protected.append(m.group(0))
        return f" __MASKYY_TOKEN_{len(protected)-1}__ "
    # Protect Telegram HTML, URLs, code blocks and command tokens.
    pattern = r"<[^>]+>|https?://\S+|@[A-Za-z0-9_]+|`[^`]*`|/\w+"
    return re.sub(pattern, repl, str(text)), protected

def _restore_markup(text, protected):
    out = str(text)
    for i, value in enumerate(protected):
        out = out.replace(f"__MASKYY_TOKEN_{i}__", value)
        out = out.replace(f" __MASKYY_TOKEN_{i}__ ", value)
    return out

def _needs_runtime_translation(text, lang):
    # After the manual dictionary pass, send any human-readable text through
    # the runtime translator. This is what closes the last hard-coded-string
    # gap for ID/EN as well as mixed-language messages.
    return bool(text and lang in {"id", "en", "ru", "ar"} and
                re.search(r"[A-Za-z\u0400-\u04ff\u0600-\u06ff]", str(text)))

async def _google_runtime_translate(text, target_lang):
    if not text or target_lang not in {"id", "en", "ru", "ar"}:
        return text
    protected_text, protected = _protect_markup(text)
    # Do not translate text consisting only of symbols/numbers.
    if not re.search(r"[A-Za-z\u0400-\u04ff\u0600-\u06ff]", protected_text):
        return text
    cache_key = (target_lang, protected_text)
    cached = _TRANSLATION_CACHE.get(cache_key)
    if cached is not None:
        return _restore_markup(cached, protected)
    url = "https://translate.googleapis.com/translate_a/single"
    params = {"client":"gtx", "sl":"auto", "tl":target_lang, "dt":"t", "q":protected_text}
    try:
        async with aiohttp.ClientSession(timeout=_TRANSLATION_TIMEOUT) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return text
                data = await resp.json(content_type=None)
        translated = "".join(part[0] for part in (data[0] or []) if part and part[0])
        if not translated:
            return text
        if len(_TRANSLATION_CACHE) >= _TRANSLATION_CACHE_MAX:
            _TRANSLATION_CACHE.pop(next(iter(_TRANSLATION_CACHE)))
        _TRANSLATION_CACHE[cache_key] = translated
        return _restore_markup(translated, protected)
    except Exception as e:
        log.debug("Runtime translation unavailable: %s", e)
        return text

async def translate_for_user(uid, text):
    if text is None:
        return text
    # Before language selection, never alter the multilingual selector.
    saved_lang = get_user_language(uid)
    if not saved_lang:
        return text
    translated = manual_translate_text(uid, text)
    # The manual table is authoritative. Runtime translation fills only
    # phrases that remain in a different language.
    if _needs_runtime_translation(translated, saved_lang):
        translated = await _google_runtime_translate(translated, saved_lang)
    return translated

async def _translate_inline_keyboard(uid, markup):
    if markup is None or not isinstance(markup, InlineKeyboardMarkup):
        return markup
    rows=[]
    lang=_lang_for(uid)
    for row in markup.inline_keyboard:
        new_row=[]
        for button in row:
            cb=getattr(button,"callback_data",None)
            if cb and str(cb).startswith("lang_"):
                new_row.append(button); continue
            label=getattr(button,"text",None)
            if label:
                label=await translate_for_user(uid,label)
            try:
                new_row.append(button.model_copy(update={"text":label or ""}))
            except Exception:
                new_row.append(button)
        rows.append(new_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)

# Bot transport interception: catches direct bot.send_* and edits.
if not getattr(Bot, "_manual_admin_features_translation", False):
    _send_message = Bot.send_message
    _send_photo = Bot.send_photo
    _send_document = getattr(Bot,"send_document",None)
    _send_video = getattr(Bot,"send_video",None)
    _send_animation = getattr(Bot,"send_animation",None)
    _edit_text = Bot.edit_message_text
    _edit_caption = getattr(Bot,"edit_message_caption",None)

    async def _sm(self, chat_id, text, *args, **kwargs):
        if not _TRANSLATION_ACTIVE.get():
            text=await translate_for_user(chat_id,text)
            if kwargs.get("reply_markup") is not None: kwargs["reply_markup"]=await _translate_inline_keyboard(chat_id,kwargs["reply_markup"])
        return await _send_message(self,chat_id,text,*args,**kwargs)
    async def _sp(self, chat_id, photo, *args, **kwargs):
        if not _TRANSLATION_ACTIVE.get():
            if kwargs.get("caption") is not None: kwargs["caption"]=await translate_for_user(chat_id,kwargs["caption"])
            if kwargs.get("reply_markup") is not None: kwargs["reply_markup"]=await _translate_inline_keyboard(chat_id,kwargs["reply_markup"])
        return await _send_photo(self,chat_id,photo,*args,**kwargs)
    async def _set(self, chat_id, message_id, text, *args, **kwargs):
        if not _TRANSLATION_ACTIVE.get():
            text=await translate_for_user(chat_id,text)
            if kwargs.get("reply_markup") is not None: kwargs["reply_markup"]=await _translate_inline_keyboard(chat_id,kwargs["reply_markup"])
        return await _edit_text(self,chat_id,message_id,text,*args,**kwargs)
    Bot.send_message=_sm; Bot.send_photo=_sp; Bot.edit_message_text=_set
    if _send_document:
        async def _sd(self,chat_id,document,*args,**kwargs):
            if not _TRANSLATION_ACTIVE.get():
                if kwargs.get("caption") is not None: kwargs["caption"]=await translate_for_user(chat_id,kwargs["caption"])
                if kwargs.get("reply_markup") is not None: kwargs["reply_markup"]=await _translate_inline_keyboard(chat_id,kwargs["reply_markup"])
            return await _send_document(self,chat_id,document,*args,**kwargs)
        Bot.send_document=_sd
    if _send_video:
        async def _sv(self,chat_id,video,*args,**kwargs):
            if not _TRANSLATION_ACTIVE.get():
                if kwargs.get("caption") is not None: kwargs["caption"]=await translate_for_user(chat_id,kwargs["caption"])
                if kwargs.get("reply_markup") is not None: kwargs["reply_markup"]=await _translate_inline_keyboard(chat_id,kwargs["reply_markup"])
            return await _send_video(self,chat_id,video,*args,**kwargs)
        Bot.send_video=_sv
    if _send_animation:
        async def _sa(self,chat_id,animation,*args,**kwargs):
            if not _TRANSLATION_ACTIVE.get():
                if kwargs.get("caption") is not None: kwargs["caption"]=await translate_for_user(chat_id,kwargs["caption"])
                if kwargs.get("reply_markup") is not None: kwargs["reply_markup"]=await _translate_inline_keyboard(chat_id,kwargs["reply_markup"])
            return await _send_animation(self,chat_id,animation,*args,**kwargs)
        Bot.send_animation=_sa
    if _edit_caption:
        async def _ec(self,chat_id,message_id,*args,**kwargs):
            if not _TRANSLATION_ACTIVE.get():
                if kwargs.get("caption") is not None: kwargs["caption"]=await translate_for_user(chat_id,kwargs["caption"])
                if kwargs.get("reply_markup") is not None: kwargs["reply_markup"]=await _translate_inline_keyboard(chat_id,kwargs["reply_markup"])
            return await _edit_caption(self,chat_id,message_id,*args,**kwargs)
        Bot.edit_message_caption=_ec
    Bot._manual_admin_features_translation=True

# Message shortcuts: catches msg.answer / answer_photo / edit_text / edit_caption.
if not getattr(Message, "_manual_admin_features_translation", False):
    _ma=Message.answer; _map=Message.answer_photo; _me=Message.edit_text; _mec=getattr(Message,"edit_caption",None)
    async def _answer(self,text=None,*args,**kwargs):
        uid=self.chat.id; text=await translate_for_user(uid,text)
        if kwargs.get("reply_markup") is not None: kwargs["reply_markup"]=await _translate_inline_keyboard(uid,kwargs["reply_markup"])
        token=_TRANSLATION_ACTIVE.set(True)
        try: return await _ma(self,text,*args,**kwargs)
        finally: _TRANSLATION_ACTIVE.reset(token)
    async def _answer_photo(self,photo,*args,**kwargs):
        uid=self.chat.id
        if kwargs.get("caption") is not None: kwargs["caption"]=await translate_for_user(uid,kwargs["caption"])
        if kwargs.get("reply_markup") is not None: kwargs["reply_markup"]=await _translate_inline_keyboard(uid,kwargs["reply_markup"])
        token=_TRANSLATION_ACTIVE.set(True)
        try: return await _map(self,photo,*args,**kwargs)
        finally: _TRANSLATION_ACTIVE.reset(token)
    async def _edit(self,text,*args,**kwargs):
        uid=self.chat.id; text=await translate_for_user(uid,text)
        if kwargs.get("reply_markup") is not None: kwargs["reply_markup"]=await _translate_inline_keyboard(uid,kwargs["reply_markup"])
        token=_TRANSLATION_ACTIVE.set(True)
        try: return await _me(self,text,*args,**kwargs)
        finally: _TRANSLATION_ACTIVE.reset(token)
    Message.answer=_answer; Message.answer_photo=_answer_photo; Message.edit_text=_edit
    if _mec:
        async def _editcap(self,*args,**kwargs):
            uid=self.chat.id
            if kwargs.get("caption") is not None: kwargs["caption"]=await translate_for_user(uid,kwargs["caption"])
            if kwargs.get("reply_markup") is not None: kwargs["reply_markup"]=await _translate_inline_keyboard(uid,kwargs["reply_markup"])
            token=_TRANSLATION_ACTIVE.set(True)
            try: return await _mec(self,*args,**kwargs)
            finally: _TRANSLATION_ACTIVE.reset(token)
        Message.edit_caption=_editcap
    Message._manual_admin_features_translation=True

# CallbackQuery.answer is an alert/toast and does NOT travel through Bot.send_message,
# so it needs its own translation hook.
if not getattr(CallbackQuery, "_manual_admin_features_translation", False):
    _cba=CallbackQuery.answer
    async def _cb_answer(self,text=None,*args,**kwargs):
        if text is not None:
            text=await translate_for_user(self.from_user.id,text)
        return await _cba(self,text,*args,**kwargs)
    CallbackQuery.answer=_cb_answer
    CallbackQuery._manual_admin_features_translation=True

# ═══════════════════════════════════════════
#  🤖 BOT
# ═══════════════════════════════════════════

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp  = Dispatcher(storage=MemoryStorage())
rt  = Router()
dp.include_router(rt)
START_TIME = time.time()


async def notify_admins(text, markup=None):
    for uid, role in ADMINS.items():
        if ADMIN_LEVELS.get(role,0) >= 10:
            try: await bot.send_message(uid, text, reply_markup=markup)
            except: pass


async def safe_edit_callback(cb: CallbackQuery, text: str, reply_markup=None):
    """
    Safely change a callback message.
    Telegram photo messages cannot be edited with edit_text().
    If the current message contains a photo, remove it and send a
    fresh text message instead. This prevents 'message can't be edited'
    errors when Dashboard/Welcome uses a photo card.
    """
    msg = cb.message
    try:
        if getattr(msg, "photo", None):
            try:
                await msg.delete()
            except Exception:
                pass
            return await bot.send_message(
                cb.from_user.id,
                text,
                reply_markup=reply_markup,
            )
        return await msg.edit_text(text, reply_markup=reply_markup)
    except Exception as e:
        log.warning(f"safe_edit_callback failed: {e}")
        try:
            return await bot.send_message(
                cb.from_user.id,
                text,
                reply_markup=reply_markup,
            )
        except Exception:
            return None


async def result_msg(msg, ok, title, detail="", kb=None):
    icon  = "✅" if ok else "❌"
    final = f"{B}\n  {icon}  {title}\n{B}"
    if detail: final += f"\n\n  {detail}"
    try: await msg.edit_text(final, reply_markup=kb)
    except: pass


async def send_welcome(target, caption, reply_markup=None):
    """Send the welcome card with the configured bot photo above the text."""
    photo = get_bot_photo()

    if isinstance(target, Message):
        if photo:
            try:
                return await target.answer_photo(
                    photo=photo,
                    caption=caption,
                    reply_markup=reply_markup,
                )
            except Exception as e:
                log.warning(f"Welcome photo send failed: {e}")
        return await target.answer(caption, reply_markup=reply_markup)

    # Callback messages may already contain a text message. If a welcome
    # photo is configured, replace that message with a photo card so the
    # layout becomes: PHOTO -> CAPTION -> BUTTONS.
    if isinstance(target, CallbackQuery):
        if photo:
            try:
                await target.message.delete()
                return await bot.send_photo(
                    target.from_user.id,
                    photo=photo,
                    caption=caption,
                    reply_markup=reply_markup,
                )
            except Exception as e:
                log.warning(f"Welcome callback photo failed: {e}")
        try:
            return await target.message.edit_text(caption, reply_markup=reply_markup)
        except Exception:
            return None



async def send_dashboard_photo(uid, photo, caption, reply_markup=None):
    """Send dashboard with the configured photo without losing it on long captions."""
    if not photo:
        return await bot.send_message(uid, caption, reply_markup=reply_markup)
    # Telegram limits photo captions to 1024 characters. Keep the photo visible
    # and move an oversized dashboard body into a normal text message.
    if len(caption) <= 1024:
        return await bot.send_photo(uid, photo=photo, caption=caption, reply_markup=reply_markup)
    await bot.send_photo(
        uid, photo=photo,
        caption="👑 <b>DASHBOARD BOT MASKYY</b>\n✦ <i>Premium Control Center</i>"
    )
    return await bot.send_message(uid, caption, reply_markup=reply_markup)

async def show_home(target, uid):
    td = nuker.get_token_data(uid)
    if not td:
        txt = T.welcome("","",uid); kb = K.login()
        if isinstance(target, (Message, CallbackQuery)):
            return await send_welcome(target, txt, kb)
    else:
        email  = td.get("email","")
        record = nuker.get_record(uid, email)
        if record and record.get("Name"):
            txt = T.dashboard(record, email, uid)
        else:
            txt = f"{B}\n  🏠  𝗗𝗔𝗦𝗛𝗕𝗢𝗔𝗥𝗗 𝗕𝗢𝗧 𝗠𝗔𝗦𝗞𝗬\n{B}\n\n  📧 {email}\n\n  ▸ Tap Refresh to load data"
        kb = K.home(uid)
    if isinstance(target, CallbackQuery):
        # Dashboard can be a photo message. Never call edit_text() on it.
        if getattr(target.message, "photo", None):
            photo = get_bot_photo()
            try:
                await target.message.delete()
            except Exception:
                pass
            if photo and td:
                try:
                    return await send_dashboard_photo(
                        target.from_user.id, photo, txt, reply_markup=kb
                    )
                except Exception as e:
                    log.warning(f"Dashboard photo send failed: {e}")
            return await bot.send_message(
                target.from_user.id,
                txt,
                reply_markup=kb,
            )
        try:
            return await target.message.edit_text(txt, reply_markup=kb)
        except Exception:
            try:
                return await bot.send_message(target.from_user.id, txt, reply_markup=kb)
            except Exception:
                return None
    elif isinstance(target, Message):
        # Logged-in dashboard is also shown with the same configured photo.
        if td:
            photo = get_bot_photo()
            if photo:
                try:
                    return await target.answer_photo(
                        photo=photo,
                        caption=txt,
                        reply_markup=kb,
                    )
                except Exception as e:
                    log.warning(f"Dashboard photo send failed: {e}")
        return await target.answer(txt, reply_markup=kb)


# ═══════════════════════════════════════════
#  🔐 GLOBAL EXPIRY PROTECTION
# ═══════════════════════════════════════════

# These callbacks are still allowed after expiry because they are the
# access/re-access flow, not protected bot features.
EXPIRY_PUBLIC_CALLBACKS = {"send_request", "msg_admin", "check_status", "language_menu"}

async def revoke_expired_access(uid: int, notify: bool = True):
    """Immediately revoke an expired user's access and clear active state."""
    global ALLOWED_USERS, VIP_USERS, EXPIRY, EXPIRY_NOTIFIED, STORE
    uid = int(uid)

    # Owner and admins are never affected by customer expiry.
    if uid == OWNER_ID or has_admin(uid, "moderator"):
        return False

    changed = False
    if uid in ALLOWED_USERS:
        ALLOWED_USERS = [x for x in ALLOWED_USERS if x != uid]
        STORE["allowed_users"] = list(ALLOWED_USERS)
        changed = True
    if uid in VIP_USERS:
        VIP_USERS = [x for x in VIP_USERS if x != uid]
        STORE["vip_users"] = list(VIP_USERS)
        changed = True

    try:
        nuker.delete_token(uid)
    except Exception as e:
        log.warning("Expired token cleanup failed for %s: %s", uid, e)

    # Keep the expiry record long enough for the watcher to know that this
    # user has already been notified. A later approval overwrites it.
    EXPIRY_NOTIFIED[str(uid)] = True
    STORE["expiry_notified"] = EXPIRY_NOTIFIED
    save_store(STORE)

    if notify:
        try:
            await bot.send_message(
                uid,
                f"{B}\n  ⏰  <b>ACCESS EXPIRED</b>\n{B}\n\n"
                f"  {tr(uid, 'Access expired.')}\n"
                f"  {tr(uid, 'Your access has ended.')}\n\n"
                f"  {tr(uid, 'Request Access')} untuk mendapatkan akses kembali.",
                reply_markup=K.no_access(uid),
            )
        except Exception as e:
            log.warning("Expiry notification failed for %s: %s", uid, e)

    return changed

class ExpiryProtectionMiddleware(BaseMiddleware):
    """Block expired users before ANY protected message/callback handler runs."""
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        uid = getattr(user, "id", None)
        if uid is None or uid == OWNER_ID or has_admin(uid, "moderator"):
            return await handler(event, data)

        # Let /start rebuild the Access screen. Also permit only the access
        # recovery callbacks after expiry. Everything else is blocked.
        if isinstance(event, Message) and getattr(event, "text", ""):
            if event.text.startswith("/start"):
                return await handler(event, data)

        if isinstance(event, CallbackQuery):
            cb_data = event.data or ""
            if cb_data in EXPIRY_PUBLIC_CALLBACKS:
                return await handler(event, data)

        if is_expired(uid):
            state = data.get("state")
            if state is not None:
                try:
                    await state.clear()
                except Exception:
                    pass

            await revoke_expired_access(uid, notify=False)

            text = (
                f"{B}\n  ⏰  <b>ACCESS EXPIRED</b>\n{B}\n\n"
                f"  {tr(uid, 'Access expired.')}\n"
                f"  {tr(uid, 'Your access has ended.') }"
            )
            if isinstance(event, CallbackQuery):
                try:
                    await safe_edit_callback(event, text, reply_markup=K.no_access(uid))
                except Exception:
                    pass
                try:
                    await event.answer(tr(uid, "Access expired."), show_alert=True)
                except Exception:
                    pass
            else:
                try:
                    await event.answer(text, reply_markup=K.no_access(uid))
                except Exception:
                    pass
            return

        return await handler(event, data)

async def expiry_watcher():
    """Check expiry independently of user activity (including idle users)."""
    global EXPIRY_NOTIFIED, STORE
    while True:
        try:
            now = datetime.now()
            for uid_text, exp_text in list(EXPIRY.items()):
                try:
                    uid = int(uid_text)
                    exp_dt = datetime.fromisoformat(exp_text)
                except Exception:
                    continue
                if uid == OWNER_ID or has_admin(uid, "moderator"):
                    continue
                if exp_dt <= now and not EXPIRY_NOTIFIED.get(uid_text, False):
                    # Mark first to prevent duplicate messages if Telegram
                    # retries or the watcher loops while a send is pending.
                    EXPIRY_NOTIFIED[uid_text] = True
                    STORE["expiry_notified"] = EXPIRY_NOTIFIED
                    save_store(STORE)
                    await revoke_expired_access(uid, notify=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Expiry watcher error: %s", e)
        await asyncio.sleep(5)

# Register BEFORE the handlers. Outer middleware runs before every handler.
expiry_protection = ExpiryProtectionMiddleware()
rt.message.outer_middleware(expiry_protection)
rt.callback_query.outer_middleware(expiry_protection)

# ═══════════════════════════════════════════
#  🚀 /start
# ═══════════════════════════════════════════

@rt.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    """Require language selection on the first /start."""
    await state.clear()
    uid  = msg.from_user.id
    name = msg.from_user.full_name
    un   = msg.from_user.username or ""

    # Language must be selected before entering the bot.
    if str(uid) not in STORE.get("user_languages", {}):
        await msg.answer(language_prompt(), reply_markup=language_keyboard())
        return


    STORE.setdefault("users", {})[str(uid)] = {
        "name": name, "username": un, "last_seen": datetime.now().isoformat()
    }
    save_store(STORE)

    # Language is selected only when no language is saved. After that, continue normally.
    await continue_start(msg, uid, name, un)
    return


async def continue_start(msg: Message, uid: int, name: str, un: str):
    """Original /start flow, executed after language is selected."""
    await set_commands_for_user(uid)

    if is_banned(uid):
        await msg.answer(T.banned(uid))
        return

    if is_maintenance() and not has_admin(uid, "moderator"):
        await msg.answer(T.maintenance(uid))
        return

    if is_expired(uid):
        store_remove_user(uid)
        await msg.answer(
            f"{B}\n  ⏰  𝗘𝗫𝗣𝗜𝗥𝗘𝗗\n{B}\n\n  Access expired.",
            reply_markup=K.no_access()
        )
        return

    if not is_allowed(uid):
        await msg.answer(T.no_access(uid), reply_markup=K.no_access())
        return

    td = nuker.get_token_data(uid)
    if td:
        await show_home(msg, uid)
    else:
        await send_welcome(msg, T.welcome(name, un, uid), K.login())


@rt.callback_query(F.data.startswith("lang_"))
async def cb_select_language(cb: CallbackQuery):
    uid = cb.from_user.id
    lang = cb.data.split("_", 1)[1]

    if lang not in SUPPORTED_LANGUAGES:
        await cb.answer("Invalid language.", show_alert=True)
        return

    if not set_user_language(uid, lang):
        await cb.answer("Failed to save language.", show_alert=True)
        return

    await set_commands_for_user(uid)
    await cb.answer(f"Language: {SUPPORTED_LANGUAGES[lang]}")

    # Remove the selector and continue directly into the normal /start flow.
    try:
        await cb.message.edit_text(
            f"{B}\n  ✅  <b>LANGUAGE SELECTED</b>\n{B}\n\n"
            f"  {SUPPORTED_LANGUAGES[lang]}\n\n"
            "  Loading..."
        )
    except Exception:
        pass

    name = cb.from_user.full_name
    un = cb.from_user.username or ""

    if is_banned(uid):
        await cb.message.answer(T.banned(uid))
        return

    if is_maintenance() and not has_admin(uid, "moderator"):
        await cb.message.answer(T.maintenance(uid))
        return

    if is_expired(uid):
        store_remove_user(uid)
        await cb.message.answer(
            f"{B}\n  ⏰  𝗘𝗫𝗣𝗜𝗥𝗘𝗗\n{B}\n\n  Access expired.",
            reply_markup=K.no_access()
        )
        return

    if not is_allowed(uid):
        await cb.message.answer(T.no_access(uid), reply_markup=K.no_access())
        return

    td = nuker.get_token_data(uid)
    if td:
        await show_home(cb, uid)
    else:
        await send_welcome(cb, T.welcome(name, un, uid), K.login())


# ═══════════════════════════════════════════
#  🔑 ACCESS
# ═══════════════════════════════════════════

@rt.callback_query(F.data == "send_request")
async def cb_send_request(cb: CallbackQuery):
    uid  = cb.from_user.id
    name = cb.from_user.full_name
    un   = cb.from_user.username or ""
    if is_banned(uid):
        await safe_edit_callback(cb, T.banned(uid)); await cb.answer(); return
    if is_allowed(uid):
        await cb.answer("✅ Already approved!", show_alert=True); return
    if is_pending(uid):
        await safe_edit_callback(cb, 
            f"{B}\n  ⏳  𝗣𝗘𝗡𝗗𝗜𝗡𝗚\n{B}\n\n  Request pending. Wait for admin.",
            reply_markup=K.after_request()); await cb.answer(); return

    store_add_pending(uid, name, un)
    request_time = PENDING.get(str(uid), {}).get("time")
    await notify_admins(
        T.request_to_admin(name, un, uid, request_time),
        markup=K.request_actions(uid)
    )
    await safe_edit_callback(cb, 
        f"{B}\n  📩  𝗦𝗘𝗡𝗧\n{B}\n\n  ✔ Request sent!\n  You'll be notified.",
        reply_markup=K.after_request())
    await cb.answer("📩 Sent!")


@rt.callback_query(F.data.startswith("rq_accept_"))
async def cb_rq_accept(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"admin"):
        await cb.answer("✗ No permission", show_alert=True); return
    uid = int(cb.data.split("_")[2])
    info = PENDING.get(str(uid), {})
    if not info:
        await cb.answer("✗ Request sudah tidak tersedia.", show_alert=True)
        return

    name = info.get("name", f"User {uid}")
    await safe_edit_callback(
        cb,
        f"  ✅ <b>ACCEPT REQUEST</b>\n\n"
        f"  👤 {name}\n"
        f"  🆔 <code>{uid}</code>\n\n"
        "  ⏳ <b>Pilih durasi akses bot:</b>",
        reply_markup=K.accept_duration_options(uid)
    )
    await cb.answer("Pilih durasi akses")


@rt.callback_query(F.data.startswith("rq_duration_back_"))
async def cb_rq_duration_back(cb: CallbackQuery):
    if not has_admin(cb.from_user.id, "admin"):
        await cb.answer("✗ No permission", show_alert=True); return
    uid = int(cb.data.split("_")[-1])
    if str(uid) not in PENDING:
        await cb.answer("✗ Request sudah tidak tersedia.", show_alert=True)
        return
    await safe_edit_callback(
        cb,
        T.request_to_admin(
            PENDING[str(uid)].get("name", f"User {uid}"),
            PENDING[str(uid)].get("username", ""),
            uid,
            PENDING[str(uid)].get("time")
        ),
        reply_markup=K.request_actions(uid)
    )
    await cb.answer()


@rt.callback_query(F.data.startswith("rq_duration_"))
async def cb_rq_duration(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id, "admin"):
        await cb.answer("✗ No permission", show_alert=True); return

    parts = cb.data.split("_")
    if len(parts) < 4:
        await cb.answer("✗ Invalid duration.", show_alert=True); return

    mode = parts[2]
    try:
        uid = int(parts[3])
    except Exception:
        await cb.answer("✗ Invalid ID.", show_alert=True); return

    info = PENDING.get(str(uid), {})
    if not info:
        await cb.answer("✗ Request sudah tidak tersedia.", show_alert=True)
        return

    if mode == "custom":
        await state.update_data(target=uid, request_accept=True)
        await state.set_state(SAdmin.expiry_dy)
        await safe_edit_callback(
            cb,
            hdr("⚙️", "𝗖𝗨𝗦𝗧𝗢𝗠 𝗧𝗜𝗠𝗘") +
            f"\n\n  👤 {info.get('name', f'User {uid}')}" +
            f"\n  🆔 User ID: <code>{uid}</code>\n\n"
            "  ⏱️ Masukkan durasi kustom.\n"
            "  Contoh: <code>30 minutes</code>, <code>7 days</code>, <code>2 months</code>.\n"
            "  ♾️ Ketik <code>lifetime</code> untuk akses tanpa batas.\n\n"
            "  ℹ️ Untuk Accept, durasi harus lebih dari 0 atau lifetime.",
            reply_markup=K.back_admin()
        )
        await cb.answer()
        return

    try:
        days = int(mode)
    except Exception:
        await cb.answer("✗ Invalid duration.", show_alert=True); return
    if days not in (1, 7, 14, 30):
        await cb.answer("✗ Durasi tidak tersedia.", show_alert=True); return

    name = info.get("name", f"User {uid}")
    un = info.get("username", "")
    store_allow(uid, name)
    store_remove_pending(uid)
    store_set_expiry(uid, days)
    admin_log(cb.from_user.id, f"APPROVED_{days}d", str(uid))

    expiry_dt = datetime.fromisoformat(EXPIRY[str(uid)])
    expiry_txt = expiry_dt.strftime("%d %b %Y • %H:%M")

    try:
        if not get_user_language(uid):
            await bot.send_message(
                uid,
                language_prompt() + f"\n\n⏰ Access aktif selama <b>{days} hari</b>.\n📅 Expiry: <b>{expiry_txt}</b>",
                reply_markup=K.language()
            )
        else:
            photo = get_bot_photo()
            caption = T.welcome(name, un, uid) + f"\n\n⏰ <b>Access aktif {days} hari</b>\n📅 Expiry: <b>{expiry_txt}</b>"
            if photo:
                await bot.send_photo(uid, photo=photo, caption=caption, reply_markup=K.login())
            else:
                await bot.send_message(uid, caption, reply_markup=K.login())
    except Exception as e:
        log.warning(f"Welcome send to accepted user failed: {e}")

    await safe_edit_callback(
        cb,
        f"  ✅ <b>ACCEPTED</b>\n\n"
        f"  👤 {name}\n"
        f"  🆔 <code>{uid}</code>\n"
        f"  ⏰ Duration: <b>{days} Day{'s' if days != 1 else ''}</b>\n"
        f"  📅 Expires: <b>{expiry_txt}</b>\n"
        f"  ✔ By {cb.from_user.full_name}"
    )
    await cb.answer(f"✅ Approved {days} days!")


@rt.callback_query(F.data.startswith("rq_reject_"))
async def cb_rq_reject(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"admin"):
        await cb.answer("✗ No permission", show_alert=True); return
    uid  = int(cb.data.split("_")[2])
    name = PENDING.get(str(uid),{}).get("name",f"User {uid}")
    store_remove_pending(uid)
    admin_log(cb.from_user.id,"REJECTED",str(uid))
    try: await bot.send_message(uid, f"{B}\n  ❌  𝗥𝗘𝗝𝗘𝗖𝗧𝗘𝗗\n{B}\n\n  Request declined.")
    except: pass
    try: await safe_edit_callback(cb, f"  ❌ <b>REJECTED</b>\n\n  👤 {name}\n  🆔 <code>{uid}</code>")
    except: pass
    await cb.answer("❌ Rejected")


@rt.callback_query(F.data.startswith("rq_ban_"))
async def cb_rq_ban(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"admin"):
        await cb.answer("✗ No permission", show_alert=True); return
    uid  = int(cb.data.split("_")[2])
    name = PENDING.get(str(uid),{}).get("name",f"User {uid}")
    store_ban(uid); store_remove_pending(uid)
    admin_log(cb.from_user.id,"BANNED_REQUEST",str(uid))
    try: await bot.send_message(uid, T.banned(uid))
    except: pass
    try: await safe_edit_callback(cb, f"  🚫 <b>BANNED</b>\n\n  👤 {name}\n  🆔 <code>{uid}</code>")
    except: pass
    await cb.answer("🚫 Banned")


@rt.callback_query(F.data == "msg_admin")
async def cb_msg_admin(cb: CallbackQuery):
    try:
        owner = await bot.get_chat(OWNER_ID)
        txt   = f"{B}\n  💬  𝗖𝗢𝗡𝗧𝗔𝗖𝗧\n{B}\n\n  ▸ @{owner.username}\n  ▸ Your ID: <code>{cb.from_user.id}</code>"
    except:
        txt = f"  Your ID: <code>{cb.from_user.id}</code>"
    await safe_edit_callback(cb, txt, reply_markup=K.after_request())
    await cb.answer()


@rt.callback_query(F.data == "check_status")
async def cb_check_status(cb: CallbackQuery):
    uid = cb.from_user.id
    if is_allowed(uid):   await show_home(cb, uid); await cb.answer("✅ Approved!")
    elif is_banned(uid):  await safe_edit_callback(cb, T.banned(uid)); await cb.answer("🚫")
    else:
        await safe_edit_callback(cb, 
            f"{B}\n  ⏳  𝗣𝗘𝗡𝗗𝗜𝗡𝗚\n{B}\n\n  Still pending.",
            reply_markup=K.after_request())
        await cb.answer("⏳")


# ═══════════════════════════════════════════
#  🔐 LOGIN
# ═══════════════════════════════════════════

@rt.callback_query(F.data == "login")
async def cb_login(cb: CallbackQuery, state: FSMContext):
    """Start login from the welcome card.

    The welcome card can be a Telegram photo message. A photo message has a
    caption, not text, so edit_text() must NOT be used here. We acknowledge
    the callback and send a fresh text message for the login FSM instead.
    """
    uid = cb.from_user.id

    # Always acknowledge the button immediately so Telegram does not leave
    # the button spinning while the next message is being sent.
    await cb.answer()

    if is_banned(uid):
        await bot.send_message(uid, T.banned(uid))
        return
    if not is_allowed(uid):
        await bot.send_message(uid, T.no_access(uid), reply_markup=K.no_access())
        return
    if is_maintenance() and not has_admin(uid, "moderator"):
        await bot.send_message(uid, T.maintenance(uid))
        return

    await state.clear()
    await state.set_state(SLogin.email)
    await bot.send_message(
        uid,
        f"{B}\n  📧  𝗘𝗡𝗧𝗘𝗥 𝗘𝗠𝗔𝗜𝗟\n{B}\n\n  {tr(uid, "email")}",
        reply_markup=K.cancel(),
    )


@rt.message(SLogin.email)
async def p_email(msg: Message, state: FSMContext):
    em = msg.text.strip()
    if "@" not in em or "." not in em:
        await msg.answer(f"  ✗ {tr(msg.from_user.id, "invalid_email")}", reply_markup=K.cancel()); return
    await state.update_data(email=em)
    await state.set_state(SLogin.password)
    await msg.answer(f"{B}\n  🔑  𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗\n{B}\n\n  {tr(msg.from_user.id, "password")}\n  🔒 {tr(msg.from_user.id, "deleted")}", reply_markup=K.cancel())


@rt.message(SLogin.password)
async def p_pass(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    pw  = msg.text.strip()
    try: await msg.delete()
    except: pass
    data = await state.get_data()
    em   = data.get("email","")
    ld   = await msg.answer(f"  ⏳ {tr(msg.from_user.id, 'signing')}")
    try:
        r = await nuker.login(em, pw)
        if r.get("ok"):
            nuker.save_token(uid, r["auth"], em, pw, r.get("refresh_token",""), r.get("firebase_uid",""))
            await ld.edit_text(f"  ⏳ {tr(msg.from_user.id, 'account_loading')}")
            loaded = await nuker.load(uid, force=True)
            STORE["stats"]["total_logins"] = STORE["stats"].get("total_logins",0)+1
            save_store(STORE); update_daily_stats("logins")
            await state.clear()
            if loaded:
                record = nuker.get_record(uid, em)
                dashboard = T.dashboard(record, em, uid)
                photo = get_bot_photo()
                try:
                    await ld.delete()
                except Exception:
                    pass
                if photo:
                    try:
                        await send_dashboard_photo(
                            uid, photo, dashboard, reply_markup=K.home(uid)
                        )
                    except Exception as e:
                        log.warning(f"Login dashboard photo failed: {e}")
                        await bot.send_message(uid, dashboard, reply_markup=K.home(uid))
                else:
                    await bot.send_message(uid, dashboard, reply_markup=K.home(uid))
            else:
                await ld.edit_text(
                    f"{B}\n  ✅  𝗟𝗢𝗚𝗜𝗡 𝗦𝗨𝗖𝗖𝗘𝗦𝗦\n{B}\n\n  📧 {em}\n\n  ⚠ Tap Refresh to load data.",
                    reply_markup=K.home(uid))
        else:
            await state.clear()
            await ld.edit_text(T.login_fail(r.get("message","LOGIN_FAILED")), reply_markup=K.login())
    except Exception as e:
        log.error(f"Login handler: {e}\n{traceback.format_exc()}")
        await state.clear()
        await ld.edit_text(T.login_fail("NETWORK_ERROR"), reply_markup=K.login())


# ═══════════════════════════════════════════
#  🏠 NAV
# ═══════════════════════════════════════════

@rt.callback_query(F.data == "back_home")
async def cb_back_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_home(cb, cb.from_user.id)
    await cb.answer()


@rt.callback_query(F.data == "refresh")
async def cb_refresh(cb: CallbackQuery):
    uid = cb.from_user.id
    td  = nuker.get_token_data(uid)
    if not td: await show_home(cb, uid); await cb.answer(); return
    # If Dashboard is a photo card, don't try to edit it as text.
    if getattr(cb.message, "photo", None):
        try:
            await cb.message.delete()
        except Exception:
            pass
        loading = await bot.send_message(uid, "  ⏳ Refreshing...")
    else:
        try:
            loading = await cb.message.edit_text("  ⏳ Refreshing...")
        except Exception:
            loading = await bot.send_message(uid, "  ⏳ Refreshing...")

    await nuker.load(uid, force=True)
    email  = td.get("email","")
    record = nuker.get_record(uid, email)

    if record and record.get("Name"):
        dashboard = T.dashboard(record, email, uid)
        photo = get_bot_photo()
        if photo:
            try:
                await loading.delete()
            except Exception:
                pass
            try:
                await send_dashboard_photo(uid, photo, dashboard, reply_markup=K.home(uid))
            except Exception as e:
                log.warning(f"Refresh dashboard photo failed: {e}")
                await bot.send_message(uid, dashboard, reply_markup=K.home(uid))
        else:
            try:
                await loading.edit_text(dashboard, reply_markup=K.home(uid))
            except Exception:
                await bot.send_message(uid, dashboard, reply_markup=K.home(uid))
    else:
        try:
            await loading.edit_text(
                f"{B}\n  ⚠  𝗖𝗢𝗨𝗟𝗗 𝗡𝗢𝗧 𝗟𝗢𝗔𝗗\n{B}\n\n  Try again.",
                reply_markup=K.home(uid),
            )
        except Exception:
            await bot.send_message(
                uid,
                f"{B}\n  ⚠  𝗖𝗢𝗨𝗟𝗗 𝗡𝗢𝗧 𝗟𝗢𝗔𝗗\n{B}\n\n  Try again.",
                reply_markup=K.home(uid),
            )
    await cb.answer("🔄 Refreshed!")


@rt.callback_query(F.data == "cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_home(cb, cb.from_user.id)
    await cb.answer("✗ Cancelled")


@rt.callback_query(F.data == "logout")
async def cb_logout(cb: CallbackQuery):
    await safe_edit_callback(cb, hdr("🚪","𝗦𝗜𝗚𝗡 𝗢𝗨𝗧")+"\n\n  Are you sure?", reply_markup=K.confirm_logout())
    await cb.answer()


@rt.callback_query(F.data == "do_logout")
async def cb_do_logout(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    nuker.delete_token(cb.from_user.id)
    await safe_edit_callback(cb, hdr("✅","𝗦𝗜𝗚𝗡𝗘𝗗 𝗢𝗨𝗧")+"\n\n  Successfully signed out.", reply_markup=K.login())
    await cb.answer("✅")


# ═══════════════════════════════════════════
#  💰 MONEY
# ═══════════════════════════════════════════

@rt.callback_query(F.data == "menu_money")
async def cb_money_menu(cb: CallbackQuery):
    if not nuker.get_token(cb.from_user.id): await cb.answer("✗ Sign in first!", show_alert=True); return
    ok,w = check_rate_limit(cb.from_user.id)
    if not ok: await cb.answer(f"⏳ Wait {w}s", show_alert=True); return
    await safe_edit_callback(cb, f"{B}\n  💰  𝗠𝗢𝗡𝗘𝗬\n{B}\n\n  Max: $50,000,000", reply_markup=K.money())
    await cb.answer()


@rt.callback_query(F.data.startswith("m_"))
async def cb_money(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    v   = cb.data[2:]
    if v == "custom":
        await state.set_state(SMoney.amount)
        await safe_edit_callback(cb, hdr("💰","𝗖𝗨𝗦𝗧𝗢𝗠")+f"\n\n  Enter amount (1 — {fmt(MAX_MONEY)}):", reply_markup=K.cancel())
        await cb.answer(); return
    m = await safe_edit_callback(cb, f"  ⏳ Setting ${fmt(int(v))}...")
    await cb.answer()
    r = await nuker.set_money(uid, int(v))
    await result_msg(m, r.get("ok"), "𝗠𝗢𝗡𝗘𝗬 𝗦𝗘𝗧" if r.get("ok") else "𝗙𝗔𝗜𝗟𝗘𝗗",
        f"💰 ${fmt(int(v))}" if r.get("ok") else r.get("message",""), K.back_home())


@rt.message(SMoney.amount)
async def p_money(msg: Message, state: FSMContext):
    try:
        a = int(msg.text.strip().replace(",","").replace(" ",""))
        assert 1 <= a <= MAX_MONEY
    except:
        await msg.answer(f"  ✗ Enter 1 — {fmt(MAX_MONEY)}", reply_markup=K.cancel()); return
    await state.clear()
    ld = await msg.answer(f"  ⏳ Setting ${fmt(a)}...")
    r  = await nuker.set_money(msg.from_user.id, a)
    await result_msg(ld, r.get("ok"), "𝗠𝗢𝗡𝗘𝗬 𝗦𝗘𝗧" if r.get("ok") else "𝗙𝗔𝗜𝗟𝗘𝗗",
        f"💰 ${fmt(a)}" if r.get("ok") else "", K.back_home())


# ═══════════════════════════════════════════
#  🪙 COINS
# ═══════════════════════════════════════════

@rt.callback_query(F.data == "menu_coins")
async def cb_coins_menu(cb: CallbackQuery):
    if not nuker.get_token(cb.from_user.id): await cb.answer("✗ Sign in first!", show_alert=True); return
    await safe_edit_callback(cb, f"{B}\n  🪙  𝗖𝗢𝗜𝗡𝗦\n{B}\n\n  Max: 500,000", reply_markup=K.coins())
    await cb.answer()


@rt.callback_query(F.data.startswith("c_"))
async def cb_coins(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    v   = cb.data[2:]
    if v == "custom":
        await state.set_state(SCoins.amount)
        await safe_edit_callback(cb, hdr("🪙","𝗖𝗨𝗦𝗧𝗢𝗠")+f"\n\n  Enter amount (1 — {fmt(MAX_COIN)}):", reply_markup=K.cancel())
        await cb.answer(); return
    m = await safe_edit_callback(cb, f"  ⏳ Setting {fmt(int(v))} coins...")
    await cb.answer()
    r = await nuker.set_coin(uid, int(v))
    await result_msg(m, r.get("ok"), "𝗖𝗢𝗜𝗡𝗦 𝗦𝗘𝗧" if r.get("ok") else "𝗙𝗔𝗜𝗟𝗘𝗗",
        f"🪙 {fmt(int(v))} coins" if r.get("ok") else "", K.back_home())


@rt.message(SCoins.amount)
async def p_coins(msg: Message, state: FSMContext):
    try:
        a = int(msg.text.strip().replace(",","").replace(" ",""))
        assert 1 <= a <= MAX_COIN
    except:
        await msg.answer(f"  ✗ Enter 1 — {fmt(MAX_COIN)}", reply_markup=K.cancel()); return
    await state.clear()
    ld = await msg.answer(f"  ⏳ Setting {fmt(a)} coins...")
    r  = await nuker.set_coin(msg.from_user.id, a)
    await result_msg(ld, r.get("ok"), "𝗖𝗢𝗜𝗡𝗦 𝗦𝗘𝗧" if r.get("ok") else "𝗙𝗔𝗜𝗟𝗘𝗗",
        f"🪙 {fmt(a)} coins" if r.get("ok") else "", K.back_home())


# ═══════════════════════════════════════════
#  ⚡ FEATURES BOT MASKY
# ═══════════════════════════════════════════

def set_feature_status(uid, feature_key, active=True, save=True):
    """Simpan status fitur per user agar tetap terlihat setelah kembali ke menu."""
    feature_status = STORE.setdefault("feature_status", {})
    user_status = feature_status.setdefault(str(uid), {})
    user_status[feature_key] = bool(active)
    if save:
        save_store(STORE)


def get_feature_status(uid, feature_key):
    return STORE.get("feature_status", {}).get(str(uid), {}).get(feature_key, False)


FEAT_MAP = {
    "f_w16":       ("🚗 W16 Engine",     nuker.unlock_w16),
    "f_horns":     ("🔊 Horns",          nuker.unlock_horns),
    "f_damage":    ("🛡 No Damage",      nuker.disable_damage),
    "f_fuel":      ("⛽ Unlimited Fuel", nuker.unlimited_fuel),
    "f_smoke":     ("💨 Smoke",          nuker.unlock_smoke),
    "f_anims":     ("🎭 Animations",     nuker.unlock_animations),
    "f_wheels":    ("🛞 Wheels",         nuker.unlock_wheels),
    "f_houses":    ("🏠 Houses",         nuker.unlock_houses),
    "f_levels":    ("🎮 All Levels",     nuker.complete_all_levels),
    "f_rank":      ("🏅 Max Rank",       nuker.set_rank),
    "f_siren":     ("🚨 Siren/Lights",   nuker.unlock_sirens),
    "f_headlights":("💡 Headlights",     nuker.unlock_headlights),
    "f_clothes":   ("👕 All Clothes",    nuker.unlock_all_clothes),
}


@rt.callback_query(F.data == "menu_feat")
async def cb_feat_menu(cb: CallbackQuery):
    if not nuker.get_token(cb.from_user.id): await cb.answer("✗ Sign in first!", show_alert=True); return
    uid = cb.from_user.id
    status = STORE.get("feature_status", {}).get(str(uid), {})

    opened = [
        name for key, (name, _) in FEAT_MAP.items()
        if status.get(key, False)
    ]
    locked = [
        name for key, (name, _) in FEAT_MAP.items()
        if not status.get(key, False)
    ]

    opened_text = "\n".join(
        f"  ✅ {i}. {name}"
        for i, name in enumerate(opened, 1)
    ) or "  — Belum ada fitur yang terbuka"

    locked_text = "\n".join(
        f"  🔒 {i}. {name}"
        for i, name in enumerate(locked, len(opened) + 1)
    ) or "  — Semua fitur sudah terbuka"

    txt = (
        f"{B}\n"
        f"  ⚡  𝗙𝗘𝗔𝗧𝗨𝗥𝗘𝗦 𝗕𝗢𝗧 𝗠𝗔𝗦𝗞𝗬\n"
        f"{B}\n\n"
        f"  ✦ <b>PREMIUM FEATURE CENTER</b>\n"
        f"  ├─ 🎯 {len(FEAT_MAP)} Features Available\n"
        f"  ├─ ⚡ Fast & Easy Unlock\n"
        f"  └─ 🔐 Account Protection Active\n\n"
        f"  📊 <b>STATUS FITUR DALAM AKUN CPM</b>\n"
        f"  ├─ 🟢 <b>TELAH TERBUKA</b> ({len(opened)}/{len(FEAT_MAP)})\n"
        f"{opened_text}\n\n"
        f"  └─ 🔴 <b>BELUM TERBUKA</b> ({len(locked)}/{len(FEAT_MAP)})\n"
        f"{locked_text}\n\n"
        f"  <b>SELECT A FEATURE</b>\n"
        f"  Choose an option below or use\n"
        f"  🚀 <b>UNLOCK ALL FEATURES</b> at once."
    )
    await safe_edit_callback(cb, txt, reply_markup=K.feat(uid))
    await cb.answer()


@rt.callback_query(F.data == "f_unlock_cars")
async def cb_unlock_cars(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    td = nuker.get_token_data(uid) or {}
    if not td.get("auth_token") or not td.get("firebase_uid"):
        await cb.answer("✗ Sign in first!", show_alert=True)
        return

    await cb.answer()
    source_email, source_password = SOURCE_ACCOUNT

    if not source_email or not source_password:
        await state.clear()
        await state.set_state(SUnlockCars.source_email)
        await safe_edit_callback(
            cb,
            hdr("🚗", "𝗨𝗡𝗟𝗢𝗖𝗞 𝗖𝗔𝗥𝗦") +
            "\n\n  Enter SOURCE/Donor email:" +
            "\n  <i>The source account must contain the cars you want to unlock.</i>",
            reply_markup=K.cancel(),
        )
        return

    loading = await bot.send_message(
        uid,
        f"{B}\\n  🚗  𝗨𝗡𝗟𝗢𝗖𝗞 𝗖𝗔𝗥𝗦\\n{B}\\n\\n  ⏳ Validating SOURCE..."
    )
    await _run_unlock_cars(uid, source_email, source_password, loading)


@rt.message(SUnlockCars.source_email)
async def p_unlock_cars_source_email(msg: Message, state: FSMContext):
    email = (msg.text or "").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        await msg.answer("  ✗ Invalid SOURCE email.", reply_markup=K.cancel())
        return
    await state.update_data(source_email=email)
    await state.set_state(SUnlockCars.source_pass)
    await msg.answer("  🔐 Send SOURCE/Donor password:", reply_markup=K.cancel())


@rt.message(SUnlockCars.source_pass)
async def p_unlock_cars_source_pass(msg: Message, state: FSMContext):
    data = await state.get_data()
    source_email = (data.get("source_email") or "").strip()
    source_password = (msg.text or "").strip()
    await state.clear()
    try:
        await msg.delete()
    except Exception:
        pass

    loading = await msg.answer(
        f"{B}\n  🚗  𝗨𝗡𝗟𝗢𝗖𝗞 𝗖𝗔𝗥𝗦\n{B}\n\n  ⏳ Validating SOURCE..."
    )
    await _run_unlock_cars(msg.from_user.id, source_email, source_password, loading)


async def _run_unlock_cars(uid, source_email, source_password, message):
    try:
        td = nuker.get_token_data(uid) or {}
        target_token = td.get("auth_token", "")
        target_uid = td.get("firebase_uid", "")
        if not target_token or not target_uid:
            await _edit_unlock_message(message, "❌ TARGET authentication data is unavailable.", K.back_home())
            return

        source_token, source_uid = await asyncio.to_thread(verify_user, source_email, source_password)
        if not source_token or not source_uid:
            await _edit_unlock_message(message,
                f"{B}\n  ❌  𝗨𝗡𝗟𝗢𝗖𝗞 𝗖𝗔𝗥𝗦 𝗙𝗔𝗜𝗟𝗘𝗗\n{B}\n\n  SOURCE login failed.",
                K.back_home())
            return

        if str(source_uid) == str(target_uid):
            await _edit_unlock_message(message,
                f"{B}\n  ⚠️  𝗨𝗡𝗟𝗢𝗖𝗞 𝗖𝗔𝗥𝗦 𝗔𝗕𝗢𝗥𝗧𝗘𝗗\n{B}\n\n  SOURCE and TARGET are the same account.",
                K.back_home())
            return

        source_cars = await asyncio.to_thread(cpm1_get_cars, source_token) or []
        source_cars = [c for c in source_cars if isinstance(c, dict)]
        if not source_cars:
            await _edit_unlock_message(message,
                f"{B}\n  ⚠️  𝗡𝗢 𝗖𝗔𝗥𝗦\n{B}\n\n  SOURCE account contains 0 detectable cars.",
                K.back_home())
            return

        await _edit_unlock_message(message,
            f"{B}\n  🚗  𝗨𝗡𝗟𝗢𝗖𝗞 𝗖𝗔𝗥𝗦\n{B}\n\n"
            f"  SOURCE cars detected: <b>{len(source_cars)}</b>\n"
            "  ⏳ Every car will be imported and verified...")

        report = await cpm1_clone_all_cars_strict(
            source_token, target_token, target_uid,
            max_retries=3, retry_delay=1.0, progress_message=message
        )
        total = report.get("source_total", len(source_cars))
        success = report.get("success", 0)
        failed = report.get("failed", [])
        missing = report.get("missing_after_verify", [])

        if report.get("complete"):
            set_feature_status(uid, "f_unlock_cars", True, save=False)
            STORE["stats"]["total_unlocks"] = STORE["stats"].get("total_unlocks", 0) + 1
            save_store(STORE)
            update_daily_stats("unlocks")
            await _edit_unlock_message(
                message,
                f"{B}\n  🎉  𝗨𝗡𝗟𝗢𝗖𝗞 𝗖𝗔𝗥𝗦 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘\n{B}\n\n"
                f"  🚗 SOURCE: <b>{total}</b>\n"
                f"  ✅ VERIFIED: <b>{success}/{total}</b>\n"
                f"  🔄 Retries: <b>{sum(report.get('retries', {}).values())}</b>\n\n"
                "  ✔ Every detected SOURCE car is present on TARGET.",
                K.feat(uid)
            )
        else:
            details = []
            for item in failed[:10]:
                details.append(f"• #{item.get('index')} {item.get('car_key')} — {escape(str(item.get('error', 'CLONE_FAILED')))}")
            for item in missing[:10]:
                details.append(f"• Missing after verify: #{item.get('index')} {item.get('car_key')}")
            await _edit_unlock_message(
                message,
                f"{B}\n  ⚠️  𝗨𝗡𝗟𝗢𝗖𝗞 𝗖𝗔𝗥𝗦 𝗣𝗔𝗥𝗧𝗜𝗔𝗟\n{B}\n\n"
                f"  🚗 SOURCE: <b>{total}</b>\n"
                f"  ✅ VERIFIED: <b>{success}</b>\n"
                f"  ❌ FAILED/MISSING: <b>{total-success}</b>\n\n"
                f"{chr(10).join(details) if details else 'No specific server error returned.'}\n\n"
                "  ⚠️ The feature is not marked complete until every car is verified.",
                K.feat(uid)
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.error("Unlock cars error for %s: %s\n%s", uid, exc, traceback.format_exc())
        await _edit_unlock_message(message,
            f"{B}\n  ❌  𝗨𝗡𝗟𝗢𝗖𝗞 𝗖𝗔𝗥𝗦 𝗘𝗥𝗥𝗢𝗥\n{B}\n\n  {escape(str(exc))}",
            K.back_home())


async def _edit_unlock_message(message, text, reply_markup=None):
    try:
        if isinstance(message, CallbackQuery):
            await safe_edit_callback(message, text, reply_markup=reply_markup)
        else:
            await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        pass


@rt.callback_query(F.data.in_(set(FEAT_MAP.keys())))
async def cb_feat(cb: CallbackQuery):
    uid       = cb.from_user.id
    fname, fn = FEAT_MAP[cb.data]
    m = await safe_edit_callback(cb, f"  ⏳ Loading account & applying {fname}...")
    await cb.answer()
    r = await fn(uid)
    if r.get("ok"):
        set_feature_status(uid, cb.data, True, save=False)
        STORE["stats"]["total_unlocks"] = STORE["stats"].get("total_unlocks",0)+1
        save_store(STORE); update_daily_stats("unlocks")
    await result_msg(m, r.get("ok"),
        f"{fname} ✔" if r.get("ok") else f"{fname} ✗",
        "" if r.get("ok") else r.get("message",""), K.feat(uid))


@rt.callback_query(F.data == "f_all")
async def cb_feat_all(cb: CallbackQuery):
    uid = cb.from_user.id
    if not nuker.get_token(uid): await cb.answer("✗ Sign in first!", show_alert=True); return
    await cb.answer()
    m = await safe_edit_callback(cb, f"{B}\n  🚀  𝗨𝗡𝗟𝗢𝗖𝗞𝗜𝗡𝗚 𝗔𝗟𝗟\n{B}\n\n  ⏳ Loading account...")
    await nuker.load(uid, force=True)
    ALL    = list(FEAT_MAP.items())
    total  = len(ALL)
    done   = 0; failed = 0; results = []
    for i,(feature_key,(name,fn)) in enumerate(ALL):
        pct    = int(((i+1)/total)*100)
        bar    = "▰"*int(pct/7) + "▱"*(15-int(pct/7))
        try:
            await m.edit_text(
                f"{B}\n  🚀  𝗨𝗡𝗟𝗢𝗖𝗞𝗜𝗡𝗚 𝗔𝗟𝗟\n{B}\n\n"
                f"  [{bar}] {pct}%\n"
                f"  ✔ {done}  ✗ {failed}  ▸ {i+1}/{total}\n\n"
                f"  ⏳ {name}")
        except: pass
        r = await fn(uid)
        if r.get("ok"):
            done += 1
            set_feature_status(uid, feature_key, True, save=False)
            results.append(f"  ✔ {name}")
        else:
            failed += 1
            results.append(f"  ✗ {name}")
        await asyncio.sleep(0.3)
    STORE["stats"]["total_unlocks"] = STORE["stats"].get("total_unlocks",0)+done
    save_store(STORE)
    try:
        await m.edit_text(
            f"{B}\n  🎉  𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘\n{B}\n\n"
            f"  [▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰] 100%\n\n"
            f"  ✔ {done}/{total}  ✗ {failed}/{total}\n\n"
            + "\n".join(results), reply_markup=K.back_home())
    except: pass


# ═══════════════════════════════════════════
#  🔧 SETTINGS BOT MASKY
# ═══════════════════════════════════════════

@rt.callback_query(F.data == "menu_set")
async def cb_set_menu(cb: CallbackQuery):
    uid = cb.from_user.id
    if not nuker.get_token(uid):
        await cb.answer("✗ Sign in first!", show_alert=True)
        return

    # Ambil data akun CPM yang sedang login agar informasi akun tampil rapi.
    td = nuker.get_token_data(uid) or {}
    email = td.get("email", "—")
    record = nuker.get_record(uid, email) or {}
    cpm_name = str(record.get("Name", "Unknown")).strip()[:28] or "—"
    cpm_id = str(record.get("localID", "—")).strip()[:18] or "—"
    rank_value = str(
        record.get("Rank") or record.get("rank") or record.get("Rating") or "—"
    ).strip()[:24] or "—"

    # Layout dibuat compact agar tidak muncul literal "\n" dan tidak berantakan
    # pada layar Telegram yang kecil.
    settings_text = (
        "╭━━━━━━━━━━━━━━━━━━━━━━━━╮\n"
        "│  ⚙️ <b>SETTINGS BOT MASKYY</b>  │\n"
        "│  ✨ <i>Account Management Center</i> │\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "╭─────── 👤 <b>CPM ACCOUNT</b> ───────╮\n"
        f"│ 📧 <b>Email</b>      : <code>{escape(email)}</code>\n"
        f"│ 👤 <b>Nama Akun</b>  : <b>{escape(cpm_name)}</b>\n"
        f"│ 🆔 <b>Player ID</b>  : <code>{escape(cpm_id)}</code>\n"
        f"│ 🏅 <b>Rank CPM</b>   : <b>{escape(rank_value)}</b>\n"
        "╰──────────────────────────╯\n\n"
        "⚙️ <b>ACCOUNT CONTROL CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✏️  Update account name\n"
        "🆔  Manage Player ID\n"
        "📧  Change account email\n"
"🔐  Change account password\n"
        "👥  Clone account\n"
        "🏆  Update wins / losses\n"
        "🔧  Repair account data\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>SELECT AN OPTION BELOW</b>\n"
        "<i>Manage your CPM account settings using the buttons below.</i>"
    )
    await safe_edit_callback(cb, settings_text, reply_markup=K.sett())
    await cb.answer()



@rt.callback_query(F.data == "change_language")
async def cb_change_language(cb: CallbackQuery):
    await safe_edit_callback(cb, language_prompt(), reply_markup=language_keyboard())
    await cb.answer()

@rt.callback_query(F.data == "s_name")
async def cb_s_name(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SName.name)
    await safe_edit_callback(cb, hdr("✏","𝗖𝗛𝗔𝗡𝗚𝗘 𝗡𝗔𝗠𝗘")+"\n\n  Enter new name:", reply_markup=K.cancel())
    await cb.answer()


@rt.message(SName.name)
async def p_name(msg: Message, state: FSMContext):
    name = msg.text.strip()
    if not name or len(name) > 100:
        await msg.answer("  ✗ 1-100 characters.", reply_markup=K.cancel()); return
    await state.clear()
    ld = await msg.answer("  ⏳ Setting name...")
    r  = await nuker.set_player_name(msg.from_user.id, name)
    await result_msg(ld, r.get("ok"), "𝗡𝗔𝗠𝗘 𝗨𝗣𝗗𝗔𝗧𝗘𝗗" if r.get("ok") else "𝗙𝗔𝗜𝗟𝗘𝗗",
        f"✔ {name}" if r.get("ok") else r.get("message",""), K.back_home())


@rt.callback_query(F.data == "s_pid")
async def cb_s_pid(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SPID.pid)
    await safe_edit_callback(cb, hdr("🆔","𝗣𝗟𝗔𝗬𝗘𝗥 𝗜𝗗")+"\n\n  Enter new Player ID:", reply_markup=K.cancel())
    await cb.answer()


@rt.message(SPID.pid)
async def p_pid(msg: Message, state: FSMContext):
    pid   = msg.text.strip()
    clean = re.sub(r'\[\w+\]','',pid)
    if not clean or len(clean) < 4 or len(clean) > 100:
        await msg.answer("  ✗ 4-100 characters.", reply_markup=K.cancel()); return
    await state.clear()
    ld = await msg.answer("  ⏳ Setting ID...")
    r  = await nuker.set_player_id(msg.from_user.id, pid)
    await result_msg(ld, r.get("ok"), "𝗜𝗗 𝗨𝗣𝗗𝗔𝗧𝗘𝗗" if r.get("ok") else "𝗙𝗔𝗜𝗟𝗘𝗗",
        f"✔ {pid.upper()}" if r.get("ok") else r.get("message",""), K.back_home())


@rt.callback_query(F.data == "s_wins")
async def cb_s_wins(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SWins.val)
    await safe_edit_callback(cb, hdr("🏆","𝗦𝗘𝗧 𝗪𝗜𝗡𝗦")+"\n\n  Enter win count:", reply_markup=K.cancel())
    await cb.answer()


@rt.message(SWins.val)
async def p_wins(msg: Message, state: FSMContext):
    try: v = int(msg.text.strip()); assert v >= 0
    except: await msg.answer("  ✗ Invalid number.", reply_markup=K.cancel()); return
    await state.clear()
    ld = await msg.answer("  ⏳ Setting wins...")
    r  = await nuker.set_race_wins(msg.from_user.id, v)
    await result_msg(ld, r.get("ok"), "𝗪𝗜𝗡𝗦 𝗨𝗣𝗗𝗔𝗧𝗘𝗗" if r.get("ok") else "𝗙𝗔𝗜𝗟𝗘𝗗",
        f"🏆 {fmt(v)} wins" if r.get("ok") else r.get("message",""), K.back_home())


@rt.callback_query(F.data == "s_loses")
async def cb_s_loses(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SLoses.val)
    await safe_edit_callback(cb, hdr("😞","𝗦𝗘𝗧 𝗟𝗢𝗦𝗘𝗦")+"\n\n  Enter loss count:", reply_markup=K.cancel())
    await cb.answer()


@rt.message(SLoses.val)
async def p_loses(msg: Message, state: FSMContext):
    try: v = int(msg.text.strip()); assert v >= 0
    except: await msg.answer("  ✗ Invalid number.", reply_markup=K.cancel()); return
    await state.clear()
    ld = await msg.answer("  ⏳ Setting loses...")
    r  = await nuker.set_race_loses(msg.from_user.id, v)
    await result_msg(ld, r.get("ok"), "𝗟𝗢𝗦𝗘𝗦 𝗨𝗣𝗗𝗔𝗧𝗘𝗗" if r.get("ok") else "𝗙𝗔𝗜𝗟𝗘𝗗",
        f"😞 {fmt(v)} loses" if r.get("ok") else r.get("message",""), K.back_home())


@rt.callback_query(F.data == "s_email")
async def cb_s_email(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SChangeEmail.email)
    await safe_edit_callback(cb, hdr("📧","𝗖𝗛𝗔𝗡𝗚𝗘 𝗘𝗠𝗔𝗜𝗟")+"\n\n  Enter new CPM email:", reply_markup=K.cancel())
    await cb.answer()

@rt.message(SChangeEmail.email)
async def p_change_email(msg: Message, state: FSMContext):
    new_email = (msg.text or "").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", new_email):
        await msg.answer(f"  ✗ {tr(msg.from_user.id, "invalid_email")}", reply_markup=K.cancel()); return
    await state.clear()
    ld = await msg.answer("  ⏳ Updating email...")
    r = await nuker.change_email(msg.from_user.id, new_email)
    await result_msg(ld, r.get("ok"), "𝗘𝗠𝗔𝗜𝗟 𝗨𝗣𝗗𝗔𝗧𝗘𝗗" if r.get("ok") else "𝗙𝗔𝗜𝗟𝗘𝗗",
        f"✔ {new_email}" if r.get("ok") else r.get("message",""), K.back_home())

@rt.callback_query(F.data == "s_password")
async def cb_s_password(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SChangePassword.password)
    await safe_edit_callback(cb, hdr("🔐","𝗖𝗛𝗔𝗡𝗚𝗘 𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗")+"\n\n  Enter new password (minimum 6 characters):", reply_markup=K.cancel())
    await cb.answer()

@rt.message(SChangePassword.password)
async def p_change_password(msg: Message, state: FSMContext):
    new_password = msg.text or ""
    if len(new_password) < 6 or len(new_password) > 256:
        await msg.answer("  ✗ Password must be 6-256 characters.", reply_markup=K.cancel()); return
    await state.clear()
    ld = await msg.answer("  ⏳ Updating password...")
    r = await nuker.change_password(msg.from_user.id, new_password)
    try: await msg.delete()
    except: pass
    await result_msg(ld, r.get("ok"), "𝗣𝗔𝗦𝗦𝗪𝗢𝗥𝗗 𝗨𝗣𝗗𝗔𝗧𝗘𝗗" if r.get("ok") else "𝗙𝗔𝗜𝗟𝗘𝗗",
        "✔ Password changed" if r.get("ok") else r.get("message",""), K.back_home())

@rt.callback_query(F.data == "s_clone")
async def cb_s_clone(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SClone.source_email)
    await safe_edit_callback(
        cb,
        hdr("🧬", "𝗙𝗨𝗟𝗟 𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗖𝗟𝗢𝗡𝗘") + "\n\n  Send SOURCE email:",
        reply_markup=K.cancel(),
    )
    await cb.answer()


@rt.message(SClone.source_email)
async def p_clone_se(msg: Message, state: FSMContext):
    await state.update_data(se=msg.text.strip())
    await state.set_state(SClone.source_pass)
    await msg.answer("  Send SOURCE password:")


@rt.message(SClone.source_pass)
async def p_clone_sp(msg: Message, state: FSMContext):
    await state.update_data(sp=msg.text.strip())
    await state.set_state(SClone.target_email)
    await msg.answer("  Send TARGET email:")


@rt.message(SClone.target_email)
async def p_clone_te(msg: Message, state: FSMContext):
    await state.update_data(te=msg.text.strip())
    await state.set_state(SClone.target_pass)
    await msg.answer("  Send TARGET password:")


@rt.message(SClone.target_pass)
async def p_clone_tp(msg: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    se, sp, te, tp = d.get("se"), d.get("sp"), d.get("te"), msg.text.strip()

    m = await msg.answer(
        f"{B}\n  🧬  𝗙𝗨𝗟𝗟 𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗖𝗟𝗢𝗡𝗘\n{B}\n\n  ⏳ Validating SOURCE..."
    )

    source_token, source_uid = await asyncio.to_thread(verify_user, se, sp)
    if not source_token or not source_uid:
        await m.edit_text(
            f"{B}\n  ❌  𝗖𝗟𝗢𝗡𝗘 𝗙𝗔𝗜𝗟𝗘𝗗\n{B}\n\n  Source login failed",
            reply_markup=K.back_home(),
        )
        return

    await m.edit_text(f"{B}\n  🧬  𝗙𝗨𝗟𝗟 𝗖𝗟𝗢𝗡𝗘\n{B}\n\n  ⏳ Reading complete SOURCE account...")
    source_record, source_err = await asyncio.to_thread(
        cpm1_get_full_account_record, source_token, source_uid, sp, se
    )
    if not source_record:
        await m.edit_text(
            f"{B}\n  ❌  𝗖𝗟𝗢𝗡𝗘 𝗙𝗔𝗜𝗟𝗘𝗗\n{B}\n\n  Source record unavailable\n  {source_err or ''}",
            reply_markup=K.back_home(),
        )
        return

    await m.edit_text(f"{B}\n  🧬  𝗙𝗨𝗟𝗟 𝗖𝗟𝗢𝗡𝗘\n{B}\n\n  ⏳ Validating TARGET...")
    target_token, target_uid = await asyncio.to_thread(verify_user, te, tp)
    if not target_token or not target_uid:
        await m.edit_text(
            f"{B}\n  ❌  𝗖𝗟𝗢𝗡𝗘 𝗙𝗔𝗜𝗟𝗘𝗗\n{B}\n\n  Target login failed",
            reply_markup=K.back_home(),
        )
        return

    # Never allow an accidental self-clone.
    if str(source_uid) == str(target_uid):
        await m.edit_text(
            f"{B}\n  ⚠️  𝗖𝗟𝗢𝗡𝗘 𝗔𝗕𝗢𝗥𝗧𝗘𝗗\n{B}\n\n  Source and target are the same account.",
            reply_markup=K.back_home(),
        )
        return

    # Read TARGET first so TARGET-owned FriendsID is preserved.
    target_record, target_record_err = await asyncio.to_thread(
        cpm1_get_full_account_record, target_token, target_uid, tp, te
    )
    if not target_record:
        await m.edit_text(
            f"{B}\n  ❌  𝗖𝗟𝗢𝗡𝗘 𝗙𝗔𝗜𝗟𝗘𝗗\n{B}\n\n  Target record unavailable\n  {target_record_err or ''}",
            reply_markup=K.back_home(),
        )
        return

    target_record = cpm1_clone_record_for_target(source_record, target_uid, target_record)
    total_fields = len(target_record)

    await m.edit_text(
        f"{B}\n  🧬  𝗙𝗨𝗟𝗟 𝗖𝗟𝗢𝗡𝗘\n{B}\n\n"
        f"  ✔ Source detected\n  ✔ Target detected\n"
        f"  📦 {total_fields} account fields found\n\n"
        f"  ⏳ Writing account record..."
    )

    saved, save_msg = await asyncio.to_thread(
        cpm1_native_full_save, target_token, target_uid, tp, te, target_record
    )
    if not saved:
        await m.edit_text(
            f"{B}\n  ❌  𝗙𝗨𝗟𝗟 𝗖𝗟𝗢𝗡𝗘 𝗙𝗔𝗜𝗟𝗘𝗗\n{B}\n\n  {save_msg}",
            reply_markup=K.back_home(),
        )
        return

    # Verify the account record, but ignore target-owned identity/friends.
    await m.edit_text(f"{B}\n  🔎  𝗩𝗘𝗥𝗜𝗙𝗬𝗜𝗡𝗚\n{B}\n\n  ⏳ Reloading TARGET...")
    verified_record, verify_err = await asyncio.to_thread(
        cpm1_get_full_account_record, target_token, target_uid, tp, te
    )
    if not verified_record:
        await m.edit_text(
            f"{B}\n  ❌  𝗖𝗟𝗢𝗡𝗘 𝗙𝗔𝗜𝗟𝗘𝗗\n{B}\n\n"
            f"  TARGET record could not be verified.\n  {verify_err or ''}",
            reply_markup=K.back_home(),
        )
        return

    diffs = cpm1_record_diff(source_record, verified_record)
    await m.edit_text(f"{B}\n  🚗  𝗖𝗟𝗢𝗡𝗜𝗡𝗚 𝗔𝗟𝗟 𝗖𝗔𝗥𝗦\n{B}\n\n  ⏳ Detecting SOURCE garage...")

    source_cars = await asyncio.to_thread(cpm1_get_cars, source_token) or []
    source_cars = [c for c in source_cars if isinstance(c, dict)]
    await m.edit_text(
        f"{B}\n  🚗  𝗦𝗧𝗥𝗜𝗖𝗧 𝗔𝗟𝗟-𝗖𝗔𝗥𝗦 𝗖𝗟𝗢𝗡𝗘\n{B}\n\n"
        f"  SOURCE cars detected: {len(source_cars)}\n"
        f"  ⏳ Every car will be cloned and re-checked..."
    )

    car_report = await cpm1_clone_all_cars_strict(
        source_token, target_token, target_uid, 3, 1.0, m
    )

    car_ok = car_report.get("success", 0)
    car_total = car_report.get("source_total", len(source_cars))
    missing = car_report.get("missing_after_verify", [])

    if not car_report.get("complete"):
        failed = car_report.get("failed", [])
        details = []
        for item in failed[:10]:
            details.append(f"• #{item.get('index')} {item.get('car_key')} — {item.get('error')}")
        for item in missing[:10]:
            details.append(f"• Missing after verify: #{item.get('index')} {item.get('car_key')}")
        detail_text = "\n".join(details) if details else "No specific error returned by server."
        await m.edit_text(
            f"{B}\n  ❌  𝗖𝗟𝗢𝗡𝗘 𝗜𝗦 𝗣𝗔𝗥𝗧𝗜𝗔𝗟\n{B}\n\n"
            f"  🚗 SOURCE: {car_total}\n"
            f"  ✔ VERIFIED: {car_ok}\n"
            f"  ✗ FAILED/MISSING: {car_total - car_ok}\n\n"
            f"{detail_text}\n\n"
            f"⚠️ Clone is NOT marked complete until every SOURCE car is verified on TARGET.",
            reply_markup=K.back_home(),
        )
        return

    status = "✅ VERIFIED" if not diffs else "⚠️ ACCOUNT DATA DIFFERENCE"
    diff_text = ", ".join(diffs[:12]) if diffs else "none"
    if len(diffs) > 12:
        diff_text += f" (+{len(diffs)-12} more)"

    await m.edit_text(
        f"{B}\n  🧬  𝗙𝗨𝗟𝗟 𝗖𝗟𝗢𝗡𝗘 𝗥𝗘𝗦𝗨𝗟𝗧\n{B}\n\n"
        f"  {status}\n"
        f"  📦 Account fields : {total_fields}\n"
        f"  🚗 Cars           : {car_ok}/{car_total}\n"
        f"  🔎 Differences    : {diff_text}\n\n"
        f"  Source UID: <code>{escape(str(source_uid))}</code>\n"
        f"  Target UID: <code>{escape(str(target_uid))}</code>",
        reply_markup=K.back_home(),
    )

@rt.callback_query(F.data == "s_fix")
async def cb_s_fix(cb: CallbackQuery):
    uid = cb.from_user.id
    m   = await safe_edit_callback(cb, "  ⏳ Loading & fixing account...")
    await cb.answer()
    r = await nuker.fix_account(uid)
    await result_msg(m, r.get("ok"),
        "𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗙𝗜𝗫𝗘𝗗" if r.get("ok") else "𝗙𝗔𝗜𝗟𝗘𝗗",
        f"✔ {r.get('bugs_fixed',0)} bugs fixed" if r.get("ok") else r.get("message",""),
        K.back_home())


# ═══════════════════════════════════════════
#  👑 ADMIN PANEL IKYY
# ═══════════════════════════════════════════

@rt.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    if not has_admin(uid,"moderator"): await msg.answer("  ✗ No admin access."); return
    await msg.answer(T.admin_panel(uid), reply_markup=K.admin(uid))


async def expire_bulkadd_prompt(user_id: int, chat_id: int, state: FSMContext):
    await asyncio.sleep(BULKADD_TIMEOUT_SECONDS)
    try:
        if await state.get_state() == SAdmin.bulkadd.state:
            data = await state.get_data()
            if data.get("bulkadd_user") == user_id:
                await state.clear()
                await bot.send_message(chat_id, "  ⌛ Bulk add cancelled: timed out waiting for user IDs.", reply_markup=K.back_admin())
    except Exception as e:
        log.error(f"Bulk add timeout error: {e}")


@rt.message(Command("bulkadd"))
async def cmd_bulkadd(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    if not has_admin(uid,"admin"):
        await msg.answer("  ✗ No admin access.")
        return
    await state.clear()
    await state.set_state(SAdmin.bulkadd)
    await state.update_data(bulkadd_user=uid)
    await msg.answer(
        hdr("📥","𝗕𝗨𝗟𝗞 𝗔𝗗𝗗") +
        "\n\n  Send the user IDs (one per line)."
        "\n\n  Send /cancel to cancel.",
        reply_markup=K.back_admin()
    )
    asyncio.create_task(expire_bulkadd_prompt(uid, msg.chat.id, state))


@rt.callback_query(F.data == "admin_menu")
async def cb_admin_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = cb.from_user.id
    if not has_admin(uid,"moderator"): await cb.answer("✗ No access!", show_alert=True); return
    await safe_edit_callback(cb, T.admin_panel(uid), reply_markup=K.admin(uid))
    await cb.answer()


@rt.callback_query(F.data == "a_stats")
async def cb_a_stats(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"moderator"): await cb.answer("✗",show_alert=True); return
    await safe_edit_callback(cb, T.stats(), reply_markup=K.back_admin())
    await cb.answer()


@rt.callback_query(F.data == "a_log")
async def cb_a_log(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"moderator"): await cb.answer("✗",show_alert=True); return
    logs = STORE.get("admin_log",[])[:10]
    txt  = f"{B}\n  📋  𝗔𝗖𝗧𝗜𝗩𝗜𝗧𝗬 𝗟𝗢𝗚\n{B}\n\n"
    if not logs: txt += "  No activity yet."
    else:
        for e in logs:
            t = e.get("time","")[:16].replace("T"," ")
            txt += f"  ◆ {t}\n    {e.get('action','')} → {e.get('target','')}\n\n"
    await safe_edit_callback(cb, txt, reply_markup=K.back_admin())
    await cb.answer()


@rt.callback_query(F.data == "a_users")
async def cb_a_users(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"moderator"):
        await cb.answer("✗",show_alert=True)
        return

    await safe_edit_callback(cb, T.role_users(), reply_markup=K.back_admin())
    await cb.answer()


@rt.callback_query(F.data == "a_banned")
async def cb_a_banned(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"moderator"):
        await cb.answer("✗", show_alert=True)
        return

    await safe_edit_callback(cb, 
        T.banned_users(0),
        reply_markup=K.banned_list(0)
    )
    await cb.answer()


@rt.callback_query(F.data.startswith("a_banned_page_"))
async def cb_a_banned_page(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"moderator"):
        await cb.answer("✗", show_alert=True)
        return

    try:
        page = int(cb.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        page = 0

    await safe_edit_callback(cb, 
        T.banned_users(page),
        reply_markup=K.banned_list(page)
    )
    await cb.answer()


@rt.callback_query(F.data.startswith("a_unban_"))
async def cb_a_unban_from_list(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"admin"):
        await cb.answer("✗ Admin only!", show_alert=True)
        return

    try:
        uid = int(cb.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await cb.answer("✗ Invalid user ID.", show_alert=True)
        return

    if uid not in BANNED:
        await cb.answer("User tersebut sudah tidak diban.", show_alert=True)
        await safe_edit_callback(cb, T.banned_users(0), reply_markup=K.banned_list(0))
        return

    store_unban(uid)
    admin_log(cb.from_user.id, "UNBANNED", str(uid))

    await safe_edit_callback(cb, 
        T.banned_users(0),
        reply_markup=K.banned_list(0)
    )
    await cb.answer(f"🔓 {uid} berhasil di-unban.")


@rt.callback_query(F.data == "a_pend")
async def cb_a_pend(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"admin"): await cb.answer("✗",show_alert=True); return
    if not PENDING:
        await safe_edit_callback(cb, hdr("✅","𝗡𝗢 𝗣𝗘𝗡𝗗𝗜𝗡𝗚")+"\n\n  No pending requests.", reply_markup=K.back_admin())
    else:
        await safe_edit_callback(cb, hdr("⏳","𝗣𝗘𝗡𝗗𝗜𝗡𝗚")+f"\n\n  {len(PENDING)} pending:", reply_markup=K.pending_list())
    await cb.answer()


# ── User management ───────────────────────

@rt.callback_query(F.data == "a_bulkadd")
async def cb_a_bulkadd(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"admin"): await cb.answer("✗",show_alert=True); return
    await state.set_state(SAdmin.bulkadd)
    await state.update_data(bulkadd_user=cb.from_user.id)
    await safe_edit_callback(cb, 
        hdr("📥","𝗕𝗨𝗟𝗞 𝗔𝗗𝗗") +
        "\n\n  Send the user IDs (one per line)."
        "\n\n  Send /cancel to cancel.",
        reply_markup=K.back_admin()
    )
    asyncio.create_task(expire_bulkadd_prompt(cb.from_user.id, cb.message.chat.id, state))
    await cb.answer()


@rt.callback_query(F.data == "a_adduser")
async def cb_a_adduser(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"admin"): await cb.answer("✗",show_alert=True); return
    await state.set_state(SAdmin.adduser)
    await safe_edit_callback(cb, hdr("➕","𝗔𝗗𝗗 𝗨𝗦𝗘𝗥")+"\n\n  Enter user ID:", reply_markup=K.back_admin())
    await cb.answer()


@rt.message(SAdmin.adduser)
async def p_adduser(msg: Message, state: FSMContext):
    try: uid = int(msg.text.strip())
    except: await msg.answer("  ✗ Invalid ID."); return
    await state.clear()
    store_allow(uid); store_remove_pending(uid)
    admin_log(msg.from_user.id,"ADDED",str(uid))
    name = STORE.get("users",{}).get(str(uid),{}).get("name","User")
    un   = STORE.get("users",{}).get(str(uid),{}).get("username","")
    try: await bot.send_message(uid, T.welcome(name,un,uid), reply_markup=K.login())
    except: pass
    await msg.answer(f"  ✔ <code>{uid}</code> added!", reply_markup=K.back_admin())


@rt.message(SAdmin.bulkadd)
async def p_bulkadd(msg: Message, state: FSMContext):
    actor_id = msg.from_user.id
    if not has_admin(actor_id,"admin"):
        await state.clear()
        await msg.answer("  ✗ No admin access.")
        return

    text = (msg.text or "").strip()
    if text.lower() in {"/cancel", "cancel"}:
        await state.clear()
        await msg.answer("  ✗ Bulk add cancelled.", reply_markup=K.back_admin())
        return

    raw_lines = [line.strip() for line in (msg.text or "").splitlines() if line.strip()]
    if not raw_lines:
        await msg.answer("  ✗ Empty submission. Send one user ID per line, or /cancel to cancel.", reply_markup=K.back_admin())
        return

    seen = set()
    added_ids = []
    already_ids = []
    invalid_ids = []
    duplicate_count = 0

    for raw in raw_lines:
        if raw in seen:
            duplicate_count += 1
            continue
        seen.add(raw)
        if not raw.isdigit():
            invalid_ids.append(raw)
            continue
        uid = int(raw)
        if uid in ALLOWED_USERS:
            already_ids.append(uid)
            continue
        if store_allow(uid, save=False):
            added_ids.append(uid)
            PENDING.pop(str(uid), None)
        else:
            already_ids.append(uid)

    STORE["pending"] = PENDING
    save_ok = True
    if added_ids:
        save_ok = save_store(STORE)
        if save_ok:
            admin_log(actor_id,"BULK_ADDED",f"{len(added_ids)} users")

    await state.clear()

    total_processed = len(seen)
    detail = (
        f"Added: {len(added_ids)}\n"
        f"Already existed: {len(already_ids)}\n"
        f"Invalid IDs: {len(invalid_ids)}\n"
        f"Total processed: {total_processed}"
    )
    if duplicate_count:
        detail += f"\nDuplicates ignored: {duplicate_count}"
    if not save_ok:
        detail += "\n\n⚠ Storage write failed. The IDs were added in memory, but saving to disk failed. Check the bot logs."
    if invalid_ids:
        invalid_preview = "\n".join(escape(x[:80]) for x in invalid_ids[:50])
        if len(invalid_ids) > 50:
            invalid_preview += f"\n... and {len(invalid_ids)-50} more"
        detail += f"\n\nInvalid IDs:\n<pre>{invalid_preview}</pre>"

    await msg.answer(
        f"{B}\n  📥  Bulk Add Complete\n{B}\n\n  {detail}",
        reply_markup=K.back_admin()
    )


@rt.callback_query(F.data == "a_ban")
async def cb_a_ban(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"admin"): await cb.answer("✗",show_alert=True); return
    await state.set_state(SAdmin.ban)
    await safe_edit_callback(cb, hdr("🚫","𝗕𝗔𝗡")+"\n\n  Enter user ID:", reply_markup=K.back_admin())
    await cb.answer()


@rt.message(SAdmin.ban)
async def p_ban(msg: Message, state: FSMContext):
    try: uid = int(msg.text.strip())
    except: await msg.answer("  ✗ Invalid ID."); return
    if uid == OWNER_ID: await msg.answer("  ✗ Cannot ban owner!", reply_markup=K.back_admin()); await state.clear(); return
    await state.clear()
    store_ban(uid); nuker.delete_token(uid)
    admin_log(msg.from_user.id,"BANNED",str(uid))
    try: await bot.send_message(uid, T.banned(uid))
    except: pass
    await msg.answer(f"  🚫 <code>{uid}</code> banned!", reply_markup=K.back_admin())


@rt.callback_query(F.data == "a_unban")
async def cb_a_unban(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"admin"): await cb.answer("✗",show_alert=True); return
    await state.set_state(SAdmin.unban)
    await safe_edit_callback(cb, hdr("🔓","𝗨𝗡𝗕𝗔𝗡")+"\n\n  Enter user ID:", reply_markup=K.back_admin())
    await cb.answer()


@rt.message(SAdmin.unban)
async def p_unban(msg: Message, state: FSMContext):
    try: uid = int(msg.text.strip())
    except: await msg.answer("  ✗ Invalid ID."); return
    await state.clear()
    store_unban(uid); admin_log(msg.from_user.id,"UNBANNED",str(uid))
    await msg.answer(f"  🔓 <code>{uid}</code> unbanned!", reply_markup=K.back_admin())


@rt.callback_query(F.data == "a_kick")
async def cb_a_kick(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"admin"): await cb.answer("✗",show_alert=True); return
    await state.set_state(SAdmin.kick)
    await safe_edit_callback(cb, hdr("👢","𝗞𝗜𝗖𝗞")+"\n\n  Enter user ID:", reply_markup=K.back_admin())
    await cb.answer()


@rt.message(SAdmin.kick)
async def p_kick(msg: Message, state: FSMContext):
    try: uid = int(msg.text.strip())
    except: await msg.answer("  ✗ Invalid ID."); return
    if uid == OWNER_ID: await msg.answer("  ✗ Cannot kick owner!", reply_markup=K.back_admin()); await state.clear(); return
    await state.clear()
    store_remove_user(uid); nuker.delete_token(uid)
    admin_log(msg.from_user.id,"KICKED",str(uid))
    try: await bot.send_message(uid, hdr("👢","𝗞𝗜𝗖𝗞𝗘𝗗")+"\n\n  Access removed.")
    except: pass
    await msg.answer(f"  👢 <code>{uid}</code> kicked!", reply_markup=K.back_admin())


@rt.callback_query(F.data == "a_kickall")
async def cb_a_kickall(cb: CallbackQuery):
    if not has_admin(cb.from_user.id, "admin"):
        await cb.answer("✗", show_alert=True)
        return

    global ALLOWED_USERS, VIP_USERS, STORE

    # Keep Owner/Admin accounts safe; only ordinary allowed users are kicked.
    admin_ids = set(ADMINS.keys()) | {OWNER_ID}
    targets = [uid for uid in ALLOWED_USERS if uid not in admin_ids]

    if not targets:
        await safe_edit_callback(cb, 
            hdr("👢", "𝗞𝗜𝗖𝗞 ALL") + "\n\n  No ordinary users to kick.",
            reply_markup=K.back_admin()
        )
        await cb.answer("No users to kick.")
        return

    # Remove access in one operation.
    ALLOWED_USERS = [uid for uid in ALLOWED_USERS if uid in admin_ids]
    STORE["allowed_users"] = list(ALLOWED_USERS)

    # Remove VIP status/expiry for kicked users so they do not retain stale privileges.
    target_set = set(targets)
    VIP_USERS = [uid for uid in VIP_USERS if uid not in target_set]
    STORE["vip_users"] = list(VIP_USERS)

    expiry = STORE.get("expiry", {})
    for uid in targets:
        expiry.pop(str(uid), None)
    STORE["expiry"] = expiry

    # Remove stored game tokens/cache for kicked users.
    for uid in targets:
        try:
            nuker.delete_token(uid)
        except Exception as e:
            log.warning(f"Kick-all token cleanup failed for {uid}: {e}")

    save_store(STORE)
    admin_log(cb.from_user.id, "KICKED_ALL", str(len(targets)))

    await safe_edit_callback(cb, 
        hdr("👢", "𝗞𝗜𝗖𝗞 ALL") +
        f"\n\n  ✔ Kicked: <b>{len(targets)}</b> users" +
        f"\n  🛡 Admins kept: <b>{len(admin_ids)}</b>" +
        "\n\n  All ordinary users have been removed from bot access.",
        reply_markup=K.back_admin()
    )
    await cb.answer(f"✔ {len(targets)} users kicked.")

@rt.callback_query(F.data == "a_expiry")
async def cb_a_expiry(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id, "admin"):
        await cb.answer("✗", show_alert=True)
        return

    await state.set_state(SAdmin.expiry_id)
    await safe_edit_callback(cb, 
        hdr("⏰", "𝗦𝗘𝗧 𝗘𝗫𝗣𝗜𝗥𝗬") +
        "\n\n  Enter user ID:",
        reply_markup=K.back_admin()
    )
    await cb.answer()


@rt.message(SAdmin.expiry_id)
async def p_expiry_id(msg: Message, state: FSMContext):
    try:
        uid = int(msg.text.strip())
    except:
        await msg.answer("  ✗ Invalid ID.")
        return

    await state.clear()

    current = EXPIRY.get(str(uid))
    if current:
        try:
            dt = datetime.fromisoformat(current)
            status = dt.strftime("⏰ %d %b %Y • %H:%M") if dt > datetime.now() else "⚠️ Sudah expired"
        except Exception:
            status = "⚠️ Data expiry tidak valid"
    else:
        status = "♾️ Tidak ada expiry"

    await msg.answer(
        hdr("⏰", "𝗦𝗘𝗧 𝗘𝗫𝗣𝗜𝗥𝗬") +
        f"\n\n  🆔 User ID: <code>{uid}</code>" +
        f"\n  📌 Status: {status}\n\n" +
        "  📅 <b>Pilih masa akses:</b>\n"
        "  ├─ 🟢 1 Day\n"
        "  ├─ 🔵 7 Days\n"
        "  ├─ 🟣 14 Days\n"
        "  ├─ 🟡 30 Days\n"
        "  └─ ⚙️ Custom Time",
        reply_markup=K.expiry_options(uid)
    )


@rt.callback_query(F.data.startswith("expiry_set_"))
async def cb_expiry_set(cb: CallbackQuery):
    if not has_admin(cb.from_user.id, "admin"):
        await cb.answer("✗", show_alert=True)
        return

    parts = cb.data.split("_")
    if len(parts) != 4:
        await cb.answer("✗ Invalid expiry.", show_alert=True)
        return

    try:
        days = int(parts[2])
        uid = int(parts[3])
    except:
        await cb.answer("✗ Invalid expiry.", show_alert=True)
        return

    if days not in (1, 7, 14, 30):
        await cb.answer("✗ Durasi tidak tersedia.", show_alert=True)
        return

    store_set_expiry(uid, days)
    admin_log(cb.from_user.id, f"EXPIRY_{days}d", str(uid))

    expiry_dt = datetime.fromisoformat(EXPIRY[str(uid)])
    expiry_txt = expiry_dt.strftime("%d %b %Y • %H:%M")

    try:
        await bot.send_message(
            uid,
            f"{B}\n  ⏰  <b>𝗔𝗖𝗖𝗘𝗦𝗦 𝗘𝗫𝗣𝗜𝗥𝗬</b>\n{B}\n\n"
            f"  ✔ Access aktif selama <b>{days} hari</b>.\n"
            f"  📅 Expiry: <b>{expiry_txt}</b>"
        )
    except:
        pass

    await safe_edit_callback(cb, 
        hdr("⏰", "𝗘𝗫𝗣𝗜𝗥𝗬 𝗦𝗘𝗧") +
        f"\n\n  🆔 User ID: <code>{uid}</code>" +
        f"\n  ✅ Duration: <b>{days} Day{'s' if days != 1 else ''}</b>" +
        f"\n  📅 Expires: <b>{expiry_txt}</b>\n\n"
        "  💾 Expiry berhasil disimpan.",
        reply_markup=K.back_admin()
    )
    await cb.answer(f"✔ {days} day expiry set.")


@rt.callback_query(F.data.startswith("expiry_custom_"))
async def cb_expiry_custom(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id, "admin"):
        await cb.answer("✗", show_alert=True)
        return

    try:
        uid = int(cb.data.split("_")[-1])
    except:
        await cb.answer("✗ Invalid ID.", show_alert=True)
        return

    await state.update_data(target=uid)
    await state.set_state(SAdmin.expiry_dy)

    await safe_edit_callback(cb, 
        hdr("⚙️", "𝗖𝗨𝗦𝗧𝗢𝗠 𝗧𝗜𝗠𝗘") +
        f"\n\n  🆔 User ID: <code>{uid}</code>\n\n"
        "  ⏱️ Masukkan durasi kustom.\n"
        "  Contoh: <code>30 minutes</code>, <code>7 days</code>, <code>2 months</code>.\n"
        "  ♾️ Ketik <code>lifetime</code> untuk akses tanpa batas.",
        reply_markup=K.back_admin()
    )
    await cb.answer()


@rt.message(SAdmin.expiry_dy)
async def p_expiry_dy(msg: Message, state: FSMContext):
    try:
        parsed = parse_custom_duration(msg.text)
    except Exception:
        await msg.answer(
            "  ✗ Format tidak valid.\n\n"
            "  ⏱️ Gunakan salah satu:\n"
            "  • <code>30 minutes</code>\n"
            "  • <code>7 days</code>\n"
            "  • <code>2 months</code>\n"
            "  • <code>lifetime</code>",
            reply_markup=K.back_admin()
        )
        return

    data = await state.get_data()
    uid = data.get("target")
    request_accept = bool(data.get("request_accept"))

    if not uid:
        await state.clear()
        await msg.answer("  ✗ User ID tidak ditemukan.", reply_markup=K.back_admin())
        return

    if parsed["kind"] == "lifetime":
        if not request_accept:
            store_set_lifetime(uid)
            admin_log(msg.from_user.id, "EXPIRY_LIFETIME", str(uid))
        else:
            info = PENDING.get(str(uid), {})
            if not info:
                await state.clear()
                await msg.answer("  ✗ Request sudah tidak tersedia.", reply_markup=K.back_admin())
                return
            name = info.get("name", f"User {uid}")
            un = info.get("username", "")
            store_allow(uid, name)
            store_remove_pending(uid)
            store_set_lifetime(uid)
            admin_log(msg.from_user.id, "APPROVED_LIFETIME", str(uid))
            try:
                if not get_user_language(uid):
                    await bot.send_message(uid, language_prompt(), reply_markup=K.language())
                else:
                    photo = get_bot_photo()
                    caption = T.welcome(name, un, uid) + "\n\n♾️ <b>Lifetime access</b>"
                    if photo:
                        await bot.send_photo(uid, photo=photo, caption=caption, reply_markup=K.login())
                    else:
                        await bot.send_message(uid, caption, reply_markup=K.login())
            except Exception as e:
                log.warning(f"Welcome send to lifetime accepted user failed: {e}")
            await state.clear()
            await msg.answer(
                hdr("♾️", "𝗟𝗜𝗙𝗘𝗧𝗜𝗠𝗘 𝗔𝗖𝗖𝗘𝗦𝗦") +
                f"\n\n  👤 {name}" +
                f"\n  🆔 User ID: <code>{uid}</code>" +
                "\n  ♾️ Duration: <b>Lifetime</b>" +
                f"\n  ✔ By {msg.from_user.full_name}",
                reply_markup=K.back_admin()
            )
            return

        await state.clear()
        await msg.answer(
            hdr("♾️", "𝗟𝗜𝗙𝗘𝗧𝗜𝗠𝗘 𝗔𝗖𝗖𝗘𝗦𝗦") +
            f"\n\n  🆔 User ID: <code>{uid}</code>" +
            "\n  ♾️ Duration: <b>Lifetime</b>" +
            "\n  ✔ Expiry removed; access is now unlimited.",
            reply_markup=K.back_admin()
        )
        return

    amount = parsed["amount"]
    unit = parsed["unit"]
    if amount <= 0:
        await msg.answer("  ✗ Durasi harus lebih dari 0.", reply_markup=K.back_admin())
        return

    if request_accept:
        info = PENDING.get(str(uid), {})
        if not info:
            await state.clear()
            await msg.answer("  ✗ Request sudah tidak tersedia.", reply_markup=K.back_admin())
            return
        name = info.get("name", f"User {uid}")
        un = info.get("username", "")
        store_allow(uid, name)
        store_remove_pending(uid)
        store_set_expiry(uid, amount, unit)
        admin_log(msg.from_user.id, f"APPROVED_{amount}{unit[0]}", str(uid))
        expiry_dt = datetime.fromisoformat(EXPIRY[str(uid)])
        expiry_txt = expiry_dt.strftime("%d %b %Y • %H:%M")
        duration_txt = format_duration(amount, unit)
        try:
            if not get_user_language(uid):
                await bot.send_message(
                    uid,
                    language_prompt() + f"\n\n⏱️ Access aktif selama <b>{duration_txt}</b>.\n📅 Expiry: <b>{expiry_txt}</b>",
                    reply_markup=K.language()
                )
            else:
                photo = get_bot_photo()
                caption = T.welcome(name, un, uid) + f"\n\n⏱️ <b>Access aktif {duration_txt}</b>\n📅 Expiry: <b>{expiry_txt}</b>"
                if photo:
                    await bot.send_photo(uid, photo=photo, caption=caption, reply_markup=K.login())
                else:
                    await bot.send_message(uid, caption, reply_markup=K.login())
        except Exception as e:
            log.warning(f"Welcome send to custom accepted user failed: {e}")
        await state.clear()
        await msg.answer(
            hdr("✅", "𝗔𝗖𝗖𝗘𝗣𝗧𝗘𝗗") +
            f"\n\n  👤 {name}" +
            f"\n  🆔 User ID: <code>{uid}</code>" +
            f"\n  ⏱️ Duration: <b>{duration_txt}</b>" +
            f"\n  📅 Expires: <b>{expiry_txt}</b>" +
            f"\n  ✔ By {msg.from_user.full_name}",
            reply_markup=K.back_admin()
        )
        return

    store_set_expiry(uid, amount, unit)
    admin_log(msg.from_user.id, f"EXPIRY_CUSTOM_{amount}{unit[0]}", str(uid))
    expiry_dt = datetime.fromisoformat(EXPIRY[str(uid)])
    expiry_txt = expiry_dt.strftime("%d %b %Y • %H:%M")
    duration_txt = format_duration(amount, unit)
    try:
        await bot.send_message(
            uid,
            f"{B}\n  ⏰  <b>𝗔𝗖𝗖𝗘𝗦𝗦 𝗘𝗫𝗣𝗜𝗥𝗬</b>\n{B}\n\n"
            f"  ✔ Access aktif selama <b>{duration_txt}</b>.\n"
            f"  📅 Expiry: <b>{expiry_txt}</b>"
        )
    except:
        pass

    await state.clear()
    await msg.answer(
        hdr("⚙️", "𝗖𝗨𝗦𝗧𝗢𝗠 𝗧𝗜𝗠𝗘") +
        f"\n\n  🆔 User ID: <code>{uid}</code>" +
        f"\n  ⏱️ Duration: <b>{duration_txt}</b>" +
        f"\n  📅 Expires: <b>{expiry_txt}</b>\n\n"
        "  💾 Custom time berhasil disimpan.",
        reply_markup=K.back_admin()
    )

@rt.callback_query(F.data.startswith("expiry_remove_"))
async def cb_expiry_remove(cb: CallbackQuery):
    if not has_admin(cb.from_user.id, "admin"):
        await cb.answer("✗", show_alert=True)
        return

    try:
        uid = int(cb.data.split("_")[-1])
    except:
        await cb.answer("✗ Invalid ID.", show_alert=True)
        return

    store_remove_expiry(uid)
    admin_log(cb.from_user.id, "EXPIRY_REMOVE", str(uid))

    await safe_edit_callback(cb, 
        hdr("♾️", "𝗘𝗫𝗣𝗜𝗥𝗬 𝗥𝗘𝗠𝗢𝗩𝗘𝗗") +
        f"\n\n  🆔 User ID: <code>{uid}</code>\n"
        "  ✔ Expiry berhasil dihapus.",
        reply_markup=K.back_admin()
    )
    await cb.answer("✔ Expiry removed.")


@rt.callback_query(F.data == "a_profile")
async def cb_a_profile(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"admin"): await cb.answer("✗",show_alert=True); return
    await state.set_state(SAdmin.profile_id)
    await safe_edit_callback(cb, hdr("ℹ","𝗨𝗦𝗘𝗥 𝗣𝗥𝗢𝗙𝗜𝗟𝗘")+"\n\n  Enter user ID:", reply_markup=K.back_admin())
    await cb.answer()


@rt.message(SAdmin.profile_id)
async def p_profile_id(msg: Message, state: FSMContext):
    try: uid = int(msg.text.strip())
    except: await msg.answer("  ✗ Invalid ID."); return
    await state.clear()
    info  = STORE.get("users",{}).get(str(uid),{})
    name  = info.get("name","Unknown")
    un    = info.get("username","N/A")
    last  = info.get("last_seen","N/A")[:16].replace("T"," ")
    role  = user_role_label(uid)
    vip   = "💎 Yes" if uid in VIP_USERS else "No"
    st    = "🚫 Banned" if uid in BANNED else ("✔ Allowed" if uid in ALLOWED_USERS else "⏳ Pending")
    exp   = EXPIRY.get(str(uid),"None")
    if exp != "None":
        try: exp = datetime.fromisoformat(exp).strftime("%d %b %Y")
        except: pass
    warns = store_get_warnings(uid)
    note  = store_get_note(uid)
    txt   = (
        f"{B}\n  ℹ  𝗣𝗥𝗢𝗙𝗜𝗟𝗘 𝗕𝗢𝗧 ILIJA\n{B}\n\n"
        f"  👤 Name:     {name}\n"
        f"  📱 Username: @{un}\n"
        f"  🆔 ID:       <code>{uid}</code>\n"
        f"  📊 Status:   {st}\n"
        f"  🛡 Role:     {role}\n"
        f"  💎 VIP:      {vip}\n"
        f"  ⏰ Expiry:   {exp}\n"
        f"  📅 Last:     {last}\n"
        f"  ⚠ Warns:    {len(warns)}/3"
    )
    if note: txt += f"\n  📝 Note: {note}"
    await msg.answer(txt, reply_markup=K.back_admin())


# ── VIP ───────────────────────────────────
# VIP membership remains stored separately for broadcasts.
# The UI uses user_role(): Admin > VIP > User Biasa.

@rt.callback_query(F.data == "a_addvip")
async def cb_a_addvip(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"superadmin"): await cb.answer("✗",show_alert=True); return
    await state.set_state(SAdmin.addvip)
    await safe_edit_callback(cb, hdr("💎","𝗔𝗗𝗗 𝗩𝗜𝗣")+"\n\n  Enter user ID:", reply_markup=K.back_admin())
    await cb.answer()


@rt.message(SAdmin.addvip)
async def p_addvip(msg: Message, state: FSMContext):
    try: uid = int(msg.text.strip())
    except: await msg.answer("  ✗ Invalid ID."); return
    await state.clear()
    store_add_vip(uid); admin_log(msg.from_user.id,"ADD_VIP",str(uid))
    try: await bot.send_message(uid, "  💎 You are now VIP!")
    except: pass
    await msg.answer(f"  💎 <code>{uid}</code> is now VIP!", reply_markup=K.back_admin())


@rt.callback_query(F.data == "a_rmvip")
async def cb_a_rmvip(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"superadmin"): await cb.answer("✗",show_alert=True); return
    await state.set_state(SAdmin.rmvip)
    await safe_edit_callback(cb, hdr("💎","𝗥𝗘𝗠 𝗩𝗜𝗣")+"\n\n  Enter user ID:", reply_markup=K.back_admin())
    await cb.answer()


@rt.message(SAdmin.rmvip)
async def p_rmvip(msg: Message, state: FSMContext):
    try: uid = int(msg.text.strip())
    except: await msg.answer("  ✗ Invalid ID."); return
    await state.clear()
    store_remove_vip(uid)
    await msg.answer(f"  ✔ VIP removed for <code>{uid}</code>", reply_markup=K.back_admin())


# ═══════════════════════════════════════════
#  🖼 UPLOAD PHOTO (Owner only)
# ═══════════════════════════════════════════

@rt.callback_query(F.data == "a_photo")
async def cb_a_photo(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"owner"):
        await cb.answer("✗ Owner only!", show_alert=True); return
    await state.set_state(SAdmin.upload_photo)
    current = get_bot_photo()
    txt = f"{B}\n  🖼  𝗨𝗣𝗗𝗔𝗧𝗘 𝗕𝗢𝗧 𝗣𝗛𝗢𝗧𝗢\n{B}\n\n"
    if current:
        txt += "  ◆ Current photo is set.\n\n"
    txt += "  Send a new photo to update it.\n  This photo shows on welcome screen."
    await safe_edit_callback(cb, txt, reply_markup=K.back_admin())
    await cb.answer()


@rt.message(SAdmin.upload_photo, F.photo)
async def p_upload_photo(msg: Message, state: FSMContext):
    if not has_admin(msg.from_user.id,"owner"):
        await msg.answer("  ✗ Owner only!"); await state.clear(); return
    file_id = msg.photo[-1].file_id
    set_bot_photo(file_id)
    admin_log(msg.from_user.id,"UPDATE_PHOTO")
    await state.clear()
    await msg.answer(
        f"{B}\n  ✅  𝗣𝗛𝗢𝗧𝗢 𝗨𝗣𝗗𝗔𝗧𝗘𝗗\n{B}\n\n"
        "  ✔ Bot welcome photo updated!\n"
        "  ▸ It will show for new users.",
        reply_markup=K.back_admin()
    )


# ═══════════════════════════════════════════
#  📢 BROADCAST @ILIJASELLOFFC
# ═══════════════════════════════════════════

@rt.callback_query(F.data == "a_bcast_menu")
async def cb_bcast_menu(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"superadmin"): await cb.answer("✗",show_alert=True); return
    await safe_edit_callback(cb, 
        f"{B}\n  📢  𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 ILIJA\n{B}\n\n"
        f"  👥 All: {len(ALLOWED_USERS)}  💎 VIP: {len(VIP_USERS)}",
        reply_markup=K.broadcast_menu())
    await cb.answer()


@rt.callback_query(F.data == "bcast_text")
async def cb_bcast_text(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"superadmin"): await cb.answer("✗",show_alert=True); return
    await state.update_data(bcast_target="all")
    await state.set_state(SAdmin.bcast_text)
    await safe_edit_callback(cb, hdr("📢","𝗧𝗘𝗫𝗧 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 ILIJA")+f"\n\n  Message to all {len(ALLOWED_USERS)} users:", reply_markup=K.back_admin())
    await cb.answer()


@rt.callback_query(F.data == "bcast_vip")
async def cb_bcast_vip(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"superadmin"): await cb.answer("✗",show_alert=True); return
    await state.update_data(bcast_target="vip")
    await state.set_state(SAdmin.bcast_text)
    await safe_edit_callback(cb, hdr("💎","𝗩𝗜𝗣 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 ILIJA")+f"\n\n  Message to {len(VIP_USERS)} VIPs:", reply_markup=K.back_admin())
    await cb.answer()


@rt.callback_query(F.data == "bcast_photo")
async def cb_bcast_photo(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"superadmin"): await cb.answer("✗",show_alert=True); return
    await state.update_data(bcast_target="all")
    await state.set_state(SAdmin.bcast_photo)
    await safe_edit_callback(cb, hdr("🖼","𝗣𝗛𝗢𝗧𝗢 𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 ILIJA")+"\n\n  Send a photo:", reply_markup=K.back_admin())
    await cb.answer()


@rt.message(SAdmin.bcast_photo, F.photo)
async def p_bcast_photo_file(msg: Message, state: FSMContext):
    await state.update_data(bcast_photo_id=msg.photo[-1].file_id)
    await state.set_state(SAdmin.bcast_photo_cap)
    await msg.answer("  ✔ Photo received!\n  Type caption:", reply_markup=K.back_admin())


@rt.message(SAdmin.bcast_photo, F.text)
async def p_bcast_photo_url(msg: Message, state: FSMContext):
    await state.update_data(bcast_photo_id=msg.text.strip())
    await state.set_state(SAdmin.bcast_photo_cap)
    await msg.answer("  ✔ URL set!\n  Type caption:", reply_markup=K.back_admin())


@rt.message(SAdmin.bcast_photo_cap)
async def p_bcast_photo_cap(msg: Message, state: FSMContext):
    d = await state.get_data(); await state.clear()
    caption = msg.text.strip()
    photo   = d.get("bcast_photo_id","")
    target  = d.get("bcast_target","all")
    targets = VIP_USERS if target=="vip" else ALLOWED_USERS
    bc_cap  = f"{B}\n  📢  𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 ILIJA\n{B}\n\n  {caption}"
    s=f=0
    for uid in list(targets):
        try: await bot.send_photo(uid, photo=photo, caption=bc_cap); s+=1
        except:
            try: await bot.send_message(uid, bc_cap); s+=1
            except: f+=1
        await asyncio.sleep(0.05)
    admin_log(msg.from_user.id,f"BCAST_PHOTO s={s} f={f}")
    add_broadcast_history(msg.from_user.id,"photo",caption,s,f)
    await msg.answer(f"  📢 Done!\n  ✔ {s} sent  ✗ {f} failed", reply_markup=K.back_admin())


@rt.message(SAdmin.bcast_text)
async def p_bcast_text(msg: Message, state: FSMContext):
    d = await state.get_data(); await state.clear()
    txt     = msg.text.strip()
    target  = d.get("bcast_target","all")
    targets = VIP_USERS if target=="vip" else ALLOWED_USERS
    bc = f"{B}\n  📢  𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 ILIJA\n{B}\n\n  {txt}"
    s=f=0
    for uid in list(targets):
        try: await bot.send_message(uid, bc); s+=1
        except: f+=1
        await asyncio.sleep(0.05)
    admin_log(msg.from_user.id,f"BCAST_TEXT s={s} f={f}")
    add_broadcast_history(msg.from_user.id,"text",txt,s,f)
    await msg.answer(f"  📢 Done!\n  ✔ {s} sent  ✗ {f} failed", reply_markup=K.back_admin())


# ── Owner: Add/Remove Admin, Maintenance, Reset ───

@rt.callback_query(F.data == "a_addadm")
async def cb_a_addadm(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"owner"): await cb.answer("✗ Owner only!",show_alert=True); return
    await state.set_state(SAdmin.addadm_id)
    await safe_edit_callback(cb, hdr("➕","𝗔𝗗𝗗 𝗔𝗗𝗠𝗜𝗡")+"\n\n  Enter user ID:", reply_markup=K.back_admin())
    await cb.answer()


@rt.message(SAdmin.addadm_id)
async def p_addadm_id(msg: Message, state: FSMContext):
    try: uid = int(msg.text.strip())
    except: await msg.answer("  ✗ Invalid ID."); return
    await state.update_data(target=uid)
    await state.set_state(SAdmin.addadm_lv)
    await msg.answer(
        f"  Select role for <code>{uid}</code>:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👮 Moderator",  callback_data="sl_moderator")],
            [InlineKeyboardButton(text="🛡 Admin",      callback_data="sl_admin")],
            [InlineKeyboardButton(text="⭐ Super Admin", callback_data="sl_superadmin")],
            [InlineKeyboardButton(text="◂ Cancel",      callback_data="admin_menu")],
        ]))


@rt.callback_query(F.data.startswith("sl_"))
async def cb_sl(cb: CallbackQuery, state: FSMContext):
    role = cb.data[3:]
    d    = await state.get_data(); t = d.get("target")
    if not t: await cb.answer("✗"); await state.clear(); return
    await state.clear()
    store_add_admin(t, role)
    admin_log(cb.from_user.id,f"ADD_ADMIN_{role}",str(t))
    try: await safe_edit_callback(cb, f"  ✔ <code>{t}</code> → {role}", reply_markup=K.back_admin())
    except: pass
    try: await bot.send_message(t, f"  🎉 You are now {role}!\n  Use /admin")
    except: pass
    await cb.answer()


@rt.callback_query(F.data == "a_rmadm")
async def cb_a_rmadm(cb: CallbackQuery, state: FSMContext):
    if not has_admin(cb.from_user.id,"owner"): await cb.answer("✗ Owner only!",show_alert=True); return
    await state.set_state(SAdmin.rmadm)
    await safe_edit_callback(cb, hdr("➖","𝗥𝗘𝗠 𝗔𝗗𝗠𝗜𝗡")+"\n\n  Enter user ID:", reply_markup=K.back_admin())
    await cb.answer()


@rt.message(SAdmin.rmadm)
async def p_rmadm(msg: Message, state: FSMContext):
    try: uid = int(msg.text.strip())
    except: await msg.answer("  ✗ Invalid ID."); return
    if uid == OWNER_ID: await msg.answer("  ✗ Cannot remove owner!", reply_markup=K.back_admin()); await state.clear(); return
    await state.clear()
    store_remove_admin(uid); admin_log(msg.from_user.id,"REM_ADMIN",str(uid))
    await msg.answer(f"  ✔ <code>{uid}</code> demoted!", reply_markup=K.back_admin())


@rt.callback_query(F.data == "a_maint")
async def cb_a_maint(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"owner"): await cb.answer("✗ Owner only!",show_alert=True); return
    STORE["maintenance"] = not STORE.get("maintenance",False)
    save_store(STORE)
    st = "🔴 ON" if STORE["maintenance"] else "🟢 OFF"
    admin_log(cb.from_user.id,f"MAINTENANCE_{st}")
    await safe_edit_callback(cb, f"  🔧 Maintenance: {st}", reply_markup=K.back_admin())
    await cb.answer()


@rt.callback_query(F.data == "a_reset")
async def cb_a_reset(cb: CallbackQuery):
    if not has_admin(cb.from_user.id,"owner"): await cb.answer("✗ Owner only!",show_alert=True); return
    STORE["stats"] = {"total_logins":0,"total_actions":0,"total_unlocks":0}
    STORE["daily_stats"] = {}
    save_store(STORE); admin_log(cb.from_user.id,"RESET_STATS")
    await safe_edit_callback(cb, "  ✔ Stats reset!", reply_markup=K.back_admin())
    await cb.answer()


# ═══════════════════════════════════════════
#  📋 COMMANDS
# ═══════════════════════════════════════════

@rt.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        f"{B}\n  ❓  𝗛𝗘𝗟𝗣\n{B}\n\n"
        "  /start  — Start bot\n"
        "  /admin  — Admin panel\n"
        "  /bulkadd — Bulk add users (admin)\n"
        "  /help   — Help\n"
        "  /status — Status\n"
        "  /ping   — Ping\n\n"
    )


@rt.message(Command("status"))
async def cmd_status(msg: Message):
    uid   = msg.from_user.id
    td    = nuker.get_token_data(uid)
    up    = time.strftime('%H:%M:%S', time.gmtime(time.time()-START_TIME))
    maint = "🔴" if is_maintenance() else "🟢"
    txt   = f"{B}\n  🤖  𝗦𝗧𝗔𝗧𝗨𝗦\n{B}\n\n"
    txt  += f"  Logged:  {'✔' if td else '✗'}\n"
    if td: txt += f"  Email:   {td.get('email','—')}\n"
    txt  += f"  Users:   {len(ALLOWED_USERS)}\n  Maint:   {maint}\n  Uptime:  {up}"
    await msg.answer(txt)


@rt.message(Command("ping"))
async def cmd_ping(msg: Message):
    t = time.time()
    m = await msg.answer("  🏓 ...")
    await m.edit_text(f"  🏓 Pong! {(time.time()-t)*1000:.0f}ms")


# ═══════════════════════════════════════════
#  🚀 MAIN
# ═══════════════════════════════════════════


# ═══════════════════════════════════════════
# 📋 PER-USER BOT COMMANDS (4 LANGUAGES)
# ═══════════════════════════════════════════

COMMAND_DESCRIPTIONS = {
    "id": {
        "start": "🎮 Mulai bot", "admin": "👑 Panel admin", "bulkadd": "📥 Tambah banyak user",
        "help": "❓ Bantuan", "status": "📊 Status bot", "ping": "🏓 Cek ping"
    },
    "en": {
        "start": "🎮 Start bot", "admin": "👑 Admin panel", "bulkadd": "📥 Bulk add users",
        "help": "❓ Help", "status": "📊 Bot status", "ping": "🏓 Check ping"
    },
    "ru": {
        "start": "🎮 Запустить бота", "admin": "👑 Панель администратора", "bulkadd": "📥 Массовое добавление",
        "help": "❓ Помощь", "status": "📊 Статус бота", "ping": "🏓 Проверить пинг"
    },
    "ar": {
        "start": "🎮 تشغيل البوت", "admin": "👑 لوحة المسؤول", "bulkadd": "📥 إضافة مستخدمين دفعة واحدة",
        "help": "❓ المساعدة", "status": "📊 حالة البوت", "ping": "🏓 فحص الاتصال"
    },
}

async def set_commands_for_user(uid):
    """Set the Telegram command menu specifically for this user's language."""
    lang = get_user_language(uid) or "id"
    desc = COMMAND_DESCRIPTIONS.get(lang, COMMAND_DESCRIPTIONS["id"])
    commands = [
        BotCommand(command="start", description=desc["start"]),
        BotCommand(command="admin", description=desc["admin"]),
        BotCommand(command="bulkadd", description=desc["bulkadd"]),
        BotCommand(command="help", description=desc["help"]),
        BotCommand(command="status", description=desc["status"]),
        BotCommand(command="ping", description=desc["ping"]),
    ]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=uid))
    except Exception as e:
        log.warning("Could not set commands for %s: %s", uid, e)

async def main():
    global START_TIME
    START_TIME = time.time()

    log.info("━"*40)
    log.info("  🔥 𝗕𝗢𝗧 ILIJASELL 🔥")
    log.info(f"  Owner:  {OWNER_ID}")
    log.info(f"  Users:  {len(ALLOWED_USERS)}")
    log.info(f"  Brotli: {'✔' if HAS_BROTLI else '✗ pip install brotli'}")
    log.info(f"  Crypto: {'✔' if HAS_CRYPTO else '✗ pip install pycryptodome'}")
    log.info("━"*40)

    # Global fallback menu. Individual users receive a language-specific menu below.
    fallback = COMMAND_DESCRIPTIONS["en"]
    await bot.set_my_commands([
        BotCommand(command="start", description=fallback["start"]),
        BotCommand(command="admin", description=fallback["admin"]),
        BotCommand(command="bulkadd", description=fallback["bulkadd"]),
        BotCommand(command="help", description=fallback["help"]),
        BotCommand(command="status", description=fallback["status"]),
        BotCommand(command="ping", description=fallback["ping"]),
    ])
    for _uid in list(ALLOWED_USERS):
        try:
            if get_user_language(_uid):
                await set_commands_for_user(_uid)
        except Exception:
            pass

    expiry_task = asyncio.create_task(expiry_watcher(), name="expiry-watcher")
    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        expiry_task.cancel()
        try:
            await expiry_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Stopped.")
    except Exception as e:
        log.error(f"Fatal: {e}\n{traceback.format_exc()}")
