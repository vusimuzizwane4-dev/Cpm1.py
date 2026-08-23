import asyncio
import aiohttp
import json
import re
import sqlite3
import time
import struct
import hashlib
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional, List

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

# ═══════════════════════════════════════════
#  ⚙️  CONFIG & ENDPOINTS
# ═══════════════════════════════════════════

FK       = "AIzaSyAe_aOVT1gSfmHKBrorFvX4fRwN5nODXVA"
LOAD_URL = "https://europe-west1-cp-multiplayer.cloudfunctions.net/GetPlayerRecords3"
SAVE_URL = "https://europe-west1-cp-multiplayer.cloudfunctions.net/SavePlayerRecordsPartially8"
RANK_URL = "https://us-central1-cp-multiplayer.cloudfunctions.net/SetUserRating1"

MAX_MONEY = 50_000_000
MAX_COIN  = 500_000

logging.basicConfig(level=logging.ERROR)
log = logging.getLogger("CPM_TERMUX")

# ═══════════════════════════════════════════
#  🔐 CRYPTO & DECRYPTION
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
            "hair": self.read_list(self.read_int), "face": self.read_list(self.read_int),
            "beard": self.read_list(self.read_int), "cap": self.read_list(self.read_int),
            "mask": self.read_list(self.read_int), "top": self.read_list(self.read_int),
            "gloves": self.read_list(self.read_int), "bag": self.read_list(self.read_int),
            "pants": self.read_list(self.read_int), "shoes": self.read_list(self.read_int),
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
        if not data: self.write_byte(0); return
        self.write_byte(13)
        for k in ["hair","face","beard","cap","mask","top","gloves","bag","pants","shoes","glasses","SelectedEquipments"]:
            self.write_list(data.get(k, []), self.write_int)
        self.write_int(data.get("Gender", 0))

    def write_plates(self, data):
        if not data: self.write_byte(0); return
        self.write_byte(1)
        plates = data.get("allPlates", [])
        self._p.append(struct.pack("<i", len(plates)))
        for plate in plates:
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
    (1,"localID"),(2,"money"),(3,"Name"),(4,"coin"),(5,"allData"),
    (6,"boughtFsos"),(7,"boughtPoliceLights"),(8,"boughtPoliceSirens"),
    (9,"FriendsID"),(10,"LevelsDoneTime"),(11,"floats"),(12,"integers"),
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
#  🎮 CPM ENGINE
# ═══════════════════════════════════════════

GAME_HEADERS = {
    "Accept": "*/*", "Accept-Encoding": "gzip",
    "Content-Type": "application/json",
    "User-Agent": "UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)",
    "X-Unity-Version": "2022.3.62f2",
}

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

    def update_token(self, uid, auth, rt=None):
        exp = time.time()+3600
        with sqlite3.connect(self.db_path) as c:
            if rt: c.execute("UPDATE tokens SET auth_token=?,refresh_token=?,token_expires_at=? WHERE user_id=?",(auth,rt,exp,uid))
            else:  c.execute("UPDATE tokens SET auth_token=?,token_expires_at=? WHERE user_id=?",(auth,exp,uid))
            c.commit()

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
            return None

    async def login(self, email, password):
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FK}"
        p = {"email":email,"password":password,"returnSecureToken":True,"clientType":"CLIENT_TYPE_ANDROID"}
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=False)) as s:
                async with s.post(url, json=p, headers=GAME_HEADERS) as resp:
                    text = await resp.text()
                    try: r = json.loads(text)
                    except: return {"ok":False,"message":"NETWORK_ERROR"}
        except Exception:
            return {"ok":False,"message":"NETWORK_ERROR"}

        if "idToken" in r:
            return {"ok":True,"auth":r["idToken"],"refresh_token":r.get("refreshToken",""),"firebase_uid":r.get("localId","")}
        err = str(r.get("error",{}).get("message","")).upper()
        return {"ok":False,"message":err if err else "LOGIN_FAILED"}

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
                return True
            return False
        except Exception:
            return False

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
            return {"ok":True}
        return {"ok":False,"message":msg2}

    async def _modify(self, uid, mods):
        await self.load(uid)
        td    = self.get_token_data(uid)
        email = td.get("email") if td else None
        d     = deepcopy(self.get_record(uid,email))
        if not d or not d.get("Name"):
            return {"ok":False,"message":"Could not load user data."}
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
            return {"ok":False,"message":"Could not load user data."}
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
            return {"ok":False,"message":"Could not load user data."}
        it = d.get("integers",[])
        max_idx = max(idx for idx,_ in indices_values)
        while len(it) <= max_idx: it.append(0)
        for idx,val in indices_values: it[idx]=int(val)
        d["integers"]=it
        return await self._save(uid,d)

    # ── Actions ───────────────────
    async def set_money(self, uid, amount): return await self._modify(uid, {"money": min(amount, MAX_MONEY)})
    async def set_coin(self, uid, amount): return await self._modify(uid, {"coin": min(amount, MAX_COIN)})
    async def set_player_name(self, uid, name): return await self._modify(uid, {"Name": name})
    async def set_player_id(self, uid, pid): return await self._modify(uid, {"localID": pid.upper()})
    async def set_race_wins(self, uid, amount): return await self._set_floats(uid, [(8, float(amount))])
    async def set_race_loses(self, uid, amount): return await self._set_floats(uid, [(9, float(amount))])
    async def unlock_w16(self, uid): return await self._set_floats(uid, [(32, 1.0)])
    async def unlock_horns(self, uid): return await self._set_floats(uid, [(27,1.0),(28,1.0),(29,1.0),(30,1.0),(31,1.0)])
    async def disable_damage(self, uid): return await self._set_floats(uid, [(34, 1.0)])
    async def unlimited_fuel(self, uid): return await self._set_floats(uid, [(3, 1.0)])
    async def unlock_smoke(self, uid): return await self._set_floats(uid, [(33, 1.0)])

    async def unlock_animations(self, uid):
        await self.load(uid)
        td = self.get_token_data(uid); email = td.get("email") if td else None
        d = deepcopy(self.get_record(uid,email))
        if not d or not d.get("Name"): return {"ok":False,"message":"Failed."}
        d["animations"] = list(set(d.get("animations",[]) + list(range(301))))
        return await self._save(uid,d)

    async def unlock_wheels(self, uid):
        await self.load(uid)
        td = self.get_token_data(uid); email = td.get("email") if td else None
        d = deepcopy(self.get_record(uid,email))
        if not d or not d.get("Name"): return {"ok":False,"message":"Failed."}
        d["wheels"] = list(set(d.get("wheels",[]) + list(range(73,221))))
        it = d.get("integers",[])
        while len(it) < 113: it.append(0)
        for i in [0,1,2,3,4,5,110,111,112]: it[i]=1
        d["integers"]=it
        return await self._save(uid,d)

    async def unlock_houses(self, uid): return await self._set_integers(uid, [(8,1),(110,1),(111,1),(112,1)])

    async def complete_all_levels(self, uid):
        lvl = [0] + [120 if i==43 else 1 for i in range(1,110)]
        return await self._modify(uid, {"LevelsDoneTime": lvl})

    async def set_rank(self, uid):
        await self.load(uid)
        ok,msg,auth = await self.get_auth(uid)
        if not ok: return {"ok":False,"message":msg}
        rd = {"RatingData":{"time":1e22,"cars":1e16,"car_fix":1e13,"car_collided":1e12,
            "car_exchange":1e13,"car_trade":1e13,"car_wash":1e13,"slicer_cut":1e13,
            "drift_max":1e14,"drift":1e14,"cargo":1e5,"delivery":1e5,"race_win":3e20,
            "taxi":1e10,"levels":10000990000,"gifts":1e9,"fuel":1e10,"offroad":1e10,
            "speed_banner":1e9,"reactions":1e17,"run":1e9,"real_estate":1e9,
            "t_distance":1e10,"treasure":1e10,"block_post":1e10,"push_ups":1e12,
            "burnt_tire":1e10,"passanger_distance":1e8}}
        r = await self._post(RANK_URL,{"data":json.dumps(rd)},{**GAME_HEADERS,"Authorization":f"Bearer {auth}"})
        return {"ok":True} if r and self._ok(r) else {"ok":False,"message":"RANK_FAILED"}

    async def fix_account(self, uid):
        await self.load(uid)
        td = self.get_token_data(uid); email = td.get("email") if td else None
        d = deepcopy(self.get_record(uid,email))
        if not d or not d.get("Name"): return {"ok":False,"message":"Failed."}
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

nuker = CPMNuker()

# ═══════════════════════════════════════════
#  💻 CLI MENU INTERFACE
# ═══════════════════════════════════════════

SESSION_UID = 1

def print_header(title):
    print("\n" + "=" * 45)
    print(f"   🔥 CPM TERMUX TOOL — {title}")
    print("=" * 45)

async def main_menu():
    while True:
        td = nuker.get_token_data(SESSION_UID)
        if not td:
            print_header("LOGIN")
            print("1. Sign In to Account")
            print("0. Exit")
            choice = input("\nSelect an option: ").strip()
            if choice == "1":
                email = input("Enter Email: ").strip()
                password = input("Enter Password: ").strip()
                print("\n⏳ Signing in...")
                res = await nuker.login(email, password)
                if res.get("ok"):
                    nuker.save_token(SESSION_UID, res["auth"], email, password, res.get("refresh_token",""), res.get("firebase_uid",""))
                    print("✅ Login successful! Loading player data...")
                    await nuker.load(SESSION_UID, force=True)
                else:
                    print(f"❌ Login failed: {res.get('message')}")
            elif choice == "0":
                break
        else:
            email = td.get("email")
            record = nuker.get_record(SESSION_UID, email)
            name = record.get("Name", "Unknown") if record else "Not loaded"
            money = record.get("money", 0) if record else 0
            coin = record.get("coin", 0) if record else 0

            print_header(f"DASHBOARD ({name})")
            print(f"📧 Email: {email}")
            print(f"💰 Money: ${money:,} | 🪙 Coins: {coin:,}")
            print("-" * 45)
            print("1.  Set Money")
            print("2.  Set Coins")
            print("3.  Unlock All Features")
            print("4.  Unlock W16 Engine")
            print("5.  Unlock Horns")
            print("6.  Disable Car Damage")
            print("7.  Unlimited Fuel")
            print("8.  Unlock Smoke Effects")
            print("9.  Unlock Animations")
            print("10. Unlock Wheels")
            print("11. Unlock Houses")
            print("12. Complete All Levels")
            print("13. Set Max King Rank")
            print("14. Change Name")
            print("15. Change Player ID")
            print("16. Set Race Wins")
            print("17. Set Race Losses")
            print("18. Fix Account Bugs")
            print("19. Refresh Player Data")
            print("20. Logout")
            print("0.  Exit")

            choice = input("\nSelect an option: ").strip()

            if choice == "1":
                amt = input(f"Enter money amount (Max {MAX_MONEY:,}): ").strip()
                if amt.isdigit():
                    res = await nuker.set_money(SESSION_UID, int(amt))
                    print("✅ Money updated successfully!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "2":
                amt = input(f"Enter coins amount (Max {MAX_COIN:,}): ").strip()
                if amt.isdigit():
                    res = await nuker.set_coin(SESSION_UID, int(amt))
                    print("✅ Coins updated successfully!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "3":
                print("\n⏳ Unlocking all features...")
                feats = [
                    ("W16 Engine", nuker.unlock_w16), ("Horns", nuker.unlock_horns),
                    ("No Damage", nuker.disable_damage), ("Unlimited Fuel", nuker.unlimited_fuel),
                    ("Smoke", nuker.unlock_smoke), ("Animations", nuker.unlock_animations),
                    ("Wheels", nuker.unlock_wheels), ("Houses", nuker.unlock_houses),
                    ("Levels", nuker.complete_all_levels), ("Max Rank", nuker.set_rank)
                ]
                for name_f, fn in feats:
                    r = await fn(SESSION_UID)
                    print(f"  {'✅' if r.get('ok') else '❌'} {name_f}")
                print("🎉 All features process completed!")

            elif choice == "4":
                res = await nuker.unlock_w16(SESSION_UID)
                print("✅ W16 unlocked!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "5":
                res = await nuker.unlock_horns(SESSION_UID)
                print("✅ Horns unlocked!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "6":
                res = await nuker.disable_damage(SESSION_UID)
                print("✅ Car damage disabled!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "7":
                res = await nuker.unlimited_fuel(SESSION_UID)
                print("✅ Unlimited fuel enabled!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "8":
                res = await nuker.unlock_smoke(SESSION_UID)
                print("✅ Smoke effects unlocked!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "9":
                res = await nuker.unlock_animations(SESSION_UID)
                print("✅ Animations unlocked!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "10":
                res = await nuker.unlock_wheels(SESSION_UID)
                print("✅ Wheels unlocked!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "11":
                res = await nuker.unlock_houses(SESSION_UID)
                print("✅ Houses unlocked!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "12":
                res = await nuker.complete_all_levels(SESSION_UID)
                print("✅ All levels completed!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "13":
                res = await nuker.set_rank(SESSION_UID)
                print("✅ King Rank applied!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "14":
                new_name = input("Enter new name: ").strip()
                res = await nuker.set_player_name(SESSION_UID, new_name)
                print("✅ Name updated!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "15":
                new_id = input("Enter new player ID: ").strip()
                res = await nuker.set_player_id(SESSION_UID, new_id)
                print("✅ Player ID updated!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "16":
                w = input("Enter total wins: ").strip()
                if w.isdigit():
                    res = await nuker.set_race_wins(SESSION_UID, int(w))
                    print("✅ Wins updated!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "17":
                l = input("Enter total losses: ").strip()
                if l.isdigit():
                    res = await nuker.set_race_loses(SESSION_UID, int(l))
                    print("✅ Losses updated!" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "18":
                res = await nuker.fix_account(SESSION_UID)
                print(f"✅ Fixed bugs count: {res.get('bugs_fixed', 0)}" if res.get("ok") else f"❌ Error: {res.get('message')}")

            elif choice == "19":
                print("⏳ Refreshing data...")
                await nuker.load(SESSION_UID, force=True)
                print("✅ Data refreshed!")

            elif choice == "20":
                with sqlite3.connect(nuker.db_path) as c:
                    c.execute("DELETE FROM tokens WHERE user_id=?", (SESSION_UID,))
                    c.commit()
                nuker.cache.clear()
                print("🚪 Logged out successfully.")

            elif choice == "0":
                break

if __name__ == "__main__":
    try:
        asyncio.run(main_menu())
    except (KeyboardInterrupt, SystemExit):
        print("\nProgram interrupted.")
