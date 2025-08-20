
import os, time, re, hashlib, jwt, asyncio
from typing import Dict, Any, List, Optional, Tuple
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Body, Header, Query, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------- JWT ----------------
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALG = "HS256"
TOKEN_TTL = int(os.environ.get("TOKEN_TTL", str(60*60*24*30)))  # 30 days

def now_ms() -> int: return int(time.time()*1000)

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def create_token(username: str) -> str:
    exp = int(time.time()) + TOKEN_TTL
    return jwt.encode({"sub": username, "exp": exp}, JWT_SECRET, algorithm=JWT_ALG)

def decode_token(token: str) -> str:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])["sub"]

def bearer_user(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    tok = authorization.split(" ", 1)[1].strip()
    try:
        return decode_token(tok)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Expired token")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

# ---------------- DB (Postgres or SQLite) ----------------
import sqlite3
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_IS_PG = DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")
if DB_IS_PG:
    import psycopg2
    import psycopg2.extras

def _pg_connect():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    # autocommit so INSERT/UPDATE persist without explicit commit
    conn.autocommit = True
    return conn

def get_db():
    if DB_IS_PG:
        return _pg_connect()
    path = os.path.join(APP_DIR, os.environ.get("SQLITE_PATH", "chat.db"))
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        pass
    return conn

def _prep(sql: str) -> str:
    # Convert sqlite-style '?' placeholders to '%s' for postgres
    if DB_IS_PG:
        return "".join("%s" if c=="?" else c for c in sql)
    return sql

def db_execute(conn, sql: str, params=()):
    cur = conn.cursor()
    cur.execute(_prep(sql), params)
    return cur

def ensure_schema():
    conn = get_db()
    cur = conn.cursor()
    if DB_IS_PG:
        cur.execute("""CREATE TABLE IF NOT EXISTS users(
            username TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            pass_sha256 TEXT,
            created_at BIGINT NOT NULL
        );""")
        cur.execute("""CREATE TABLE IF NOT EXISTS messages(
            id BIGSERIAL PRIMARY KEY,
            from_user TEXT NOT NULL,
            to_user TEXT NOT NULL,
            text TEXT NOT NULL,
            ts BIGINT NOT NULL
        );""")
        cur.execute("""CREATE TABLE IF NOT EXISTS room_messages(
            id BIGSERIAL PRIMARY KEY,
            room TEXT NOT NULL,
            from_user TEXT NOT NULL,
            text TEXT NOT NULL,
            ts BIGINT NOT NULL
        );""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_dm ON messages((LEAST(from_user,to_user)),(GREATEST(from_user,to_user)), ts);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_room ON room_messages(room, ts);")
    else:
        cur.execute("""CREATE TABLE IF NOT EXISTS users(
            username TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            pass_sha256 TEXT,
            created_at INTEGER NOT NULL
        );""")
        cur.execute("""CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user TEXT NOT NULL,
            to_user TEXT NOT NULL,
            text TEXT NOT NULL,
            ts INTEGER NOT NULL
        );""")
        cur.execute("""CREATE TABLE IF NOT EXISTS room_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT NOT NULL,
            from_user TEXT NOT NULL,
            text TEXT NOT NULL,
            ts INTEGER NOT NULL
        );""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_dm ON messages(from_user, to_user, ts);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_room ON room_messages(room, ts);")
        conn.commit()
    conn.close()

def _column_exists_pg(cur, table, column):
    cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s", (table, column))
    return cur.fetchone() is not None

def _column_exists_sqlite(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())

def migrate_users_hash_column():
    """Ensure users table has 'pass_sha256'. If only 'pwd_hash' exists, add/migrate values."""
    conn = get_db(); cur = conn.cursor()
    try:
        if DB_IS_PG:
            has_pass = _column_exists_pg(cur, "users", "pass_sha256")
            has_pwd  = _column_exists_pg(cur, "users", "pwd_hash")
            if not has_pass and has_pwd:
                cur.execute("ALTER TABLE users ADD COLUMN pass_sha256 TEXT")
                cur.execute("UPDATE users SET pass_sha256 = pwd_hash WHERE pass_sha256 IS NULL")
            elif not has_pass and not has_pwd:
                cur.execute("ALTER TABLE users ADD COLUMN pass_sha256 TEXT")
        else:
            has_pass = _column_exists_sqlite(cur, "users", "pass_sha256")
            has_pwd  = _column_exists_sqlite(cur, "users", "pwd_hash")
            if not has_pass and has_pwd:
                cur.execute("ALTER TABLE users ADD COLUMN pass_sha256 TEXT")
                cur.execute("UPDATE users SET pass_sha256 = pwd_hash WHERE pass_sha256 IS NULL")
            elif not has_pass and not has_pwd:
                cur.execute("ALTER TABLE users ADD COLUMN pass_sha256 TEXT")
            conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

# ---------------- App & static ----------------
app = FastAPI(title="Chat Full (WS + Refresh)")
ensure_schema()
migrate_users_hash_column()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")

@app.get("/")
def index():
    return FileResponse(os.path.join(APP_DIR, "static", "index.html"))

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/favicon.ico")
def ico():
    return FileResponse(os.path.join(APP_DIR, "static", "favicon.ico"))

# ---------------- API: auth & directory ----------------
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{2,32}$")

@app.post("/api/signup")
def signup(payload: dict = Body(...)):
    # Accept alternate keys too (u/p)
    uname = (payload.get("username") or payload.get("u") or "").strip().lower()
    dname = (payload.get("display_name") or payload.get("name") or uname)[:64]
    pwd = (payload.get("password") or payload.get("p") or "").strip()
    if not USERNAME_RE.match(uname):
        raise HTTPException(400, "Username i pavlefshëm")
    if len(pwd) < 4:
        raise HTTPException(400, "Fjalëkalimi duhet ≥ 4")
    conn = get_db()
    cur = db_execute(conn, "SELECT 1 FROM users WHERE LOWER(username)=LOWER(?)", (uname,))
    if cur.fetchone():
        conn.close()
        raise HTTPException(409, "Username ekziston")
    db_execute(conn, "INSERT INTO users(username, display_name, pass_sha256, created_at) VALUES (?,?,?,?)",
               (uname, dname, sha256_hex(pwd), int(time.time())))
    if not DB_IS_PG:
        conn.commit()
    conn.close()
    return {"ok": True, "username": uname, "token": create_token(uname)}



@app.post("/api/register")
async def register(request: Request):
    try:
        payload = {}
        # Try JSON first
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        # Fallback to form
        if not payload:
            try:
                form = await request.form()
                payload = {
                    "username": (form.get("username") or form.get("u") or "").strip(),
                    "password": (form.get("password") or form.get("p") or "").strip(),
                    "display_name": (form.get("display_name") or form.get("name") or form.get("username") or "").strip(),
                }
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        # delegate to signup logic
        return signup(payload)  # type: ignore
    except HTTPException as he:
        raise he
    except Exception as e:
        # generic safety
        raise HTTPException(400, f"Bad request: {e}")

@app.post("/api/login")
def login(payload: dict = Body(...)):
    uname = (payload.get("username") or payload.get("u") or "").strip().lower()
    pwd = (payload.get("password") or payload.get("p") or "").strip()
    conn = get_db()
    cur = db_execute(conn, "SELECT username, display_name, pass_sha256 FROM users WHERE LOWER(username)=LOWER(?)", (uname,))
    row = cur.fetchone()
    stored = None
    if row:
        stored = (row[2] if DB_IS_PG else row["pass_sha256"])
        if stored is None:
            # Fallback: old column pwd_hash
            try:
                cur2 = db_execute(conn, "SELECT pwd_hash FROM users WHERE LOWER(username)=LOWER(?)", (uname,))
                r2 = cur2.fetchone()
                stored = (r2[0] if (r2 and DB_IS_PG) else (r2["pwd_hash"] if r2 else None))
            except Exception:
                pass
    conn.close()
    if not row or stored != sha256_hex(pwd):
        raise HTTPException(401, "Kredenciale të pasakta")
    return {"ok": True, "username": uname, "token": create_token(uname)}

@app.post("/api/refresh")
def refresh(payload: dict = Body(...)):
    tok = payload.get("token") or ""
    try:
        u = decode_token(tok)
    except Exception:
        raise HTTPException(401, "Token i pavlefshëm")
    return {"ok": True, "token": create_token(u)}

@app.get("/api/search-users")
def search_users(q: str = Query("", alias="q"), user: str = Depends(bearer_user)):
    q = (q or "").strip()
    conn = get_db()
    if q:
        cur = db_execute(conn,
            "SELECT username, display_name FROM users WHERE LOWER(username) LIKE LOWER(?) OR LOWER(display_name) LIKE LOWER(?) ORDER BY username LIMIT 50",
            (f"%{q}%", f"%{q}%")
        )
    else:
        cur = db_execute(conn, "SELECT username, display_name FROM users ORDER BY username LIMIT 50", ())
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        if DB_IS_PG:
            u, d = r[0], r[1]
        else:
            u, d = r["username"], r["display_name"]
        if u != user:
            out.append({"username": u, "display_name": d})
    return {"results": out}

@app.get("/api/dialogs")
def dialogs(user: str = Depends(bearer_user)):
    conn = get_db()
    cur = db_execute(conn, """
        SELECT other as peer, MAX(ts) AS last_ts FROM (
            SELECT CASE WHEN from_user=? THEN to_user ELSE from_user END AS other, ts
            FROM messages
            WHERE from_user=? OR to_user=?
        ) t GROUP BY other
    """, (user, user, user))
    dm = cur.fetchall()
    cur2 = db_execute(conn, "SELECT room, MAX(ts) AS last_ts FROM room_messages GROUP BY room", ())
    rooms = cur2.fetchall()
    conn.close()
    out = {}
    for r in dm:
        peer = r[0] if DB_IS_PG else r["peer"]
        last_ts = int(r[1] if DB_IS_PG else r["last_ts"] or 0)
        out[f"dm:{peer}"] = {"type": "dm", "id": peer, "last_ts": last_ts}
    for r in rooms:
        room = r[0] if DB_IS_PG else r["room"]
        last_ts = int(r[1] if DB_IS_PG else r["last_ts"] or 0)
        out[f"room:{room}"] = {"type": "room", "id": room, "last_ts": last_ts}
    return {"items": out}

@app.get("/api/dm")
def dm_history(with_: str = Query(..., alias="with"), limit: int = Query(200), user: str = Depends(bearer_user)):
    peer = (with_ or "").strip().lower()
    conn = get_db()
    cur = db_execute(conn, """
        SELECT from_user, to_user, text, ts FROM messages
        WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
        ORDER BY ts ASC LIMIT ?
    """, (user, peer, peer, user, limit))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        if DB_IS_PG:
            out.append({"from_user": r[0], "to_user": r[1], "text": r[2], "ts": int(r[3])})
        else:
            out.append({"from_user": r["from_user"], "to_user": r["to_user"], "text": r["text"], "ts": int(r["ts"]) })
    return out

@app.get("/api/room")
def room_history(room: str = Query(...), limit: int = Query(200), user: str = Depends(bearer_user)):
    room = (room or "").strip().lower()
    conn = get_db()
    cur = db_execute(conn, "SELECT from_user, text, ts FROM room_messages WHERE room=? ORDER BY ts ASC LIMIT ?", (room, limit))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        if DB_IS_PG:
            out.append({"from_user": r[0], "text": r[1], "ts": int(r[2])})
        else:
            out.append({"from_user": r["from_user"], "text": r["text"], "ts": int(r["ts"]) })
    return out

# ---------------- WebSocket Hubs ----------------
class Hub:
    def __init__(self):
        self.notify: Dict[str, List[WebSocket]] = {}   # user -> sockets
        self.dm: Dict[Tuple[str,str], List[WebSocket]] = {}  # (user,peer) normalized pair (sorted)
        self.room: Dict[str, List[WebSocket]] = {}     # room -> sockets
        self.lock = asyncio.Lock()

    @staticmethod
    def norm_pair(a: str, b: str) -> Tuple[str,str]:
        return tuple(sorted([a,b]))

    async def add_notify(self, user: str, ws: WebSocket):
        await ws.accept()
        async with self.lock:
            self.notify.setdefault(user, [])
            if ws not in self.notify[user]:
                self.notify[user].append(ws)

    def remove_notify(self, user: str, ws: WebSocket):
        lst = self.notify.get(user, [])
        if ws in lst: lst.remove(ws)

    async def add_dm(self, user: str, peer: str, ws: WebSocket):
        await ws.accept()
        key = self.norm_pair(user, peer)
        async with self.lock:
            self.dm.setdefault(key, [])
            if ws not in self.dm[key]:
                self.dm[key].append(ws)

    def remove_dm(self, user: str, peer: str, ws: WebSocket):
        key = self.norm_pair(user, peer)
        lst = self.dm.get(key, [])
        if ws in lst: lst.remove(ws)

    async def add_room(self, room: str, ws: WebSocket):
        await ws.accept()
        async with self.lock:
            self.room.setdefault(room, [])
            if ws not in self.room[room]:
                self.room[room].append(ws)

    def remove_room(self, room: str, ws: WebSocket):
        lst = self.room.get(room, [])
        if ws in lst: lst.remove(ws)

    async def broadcast_dm(self, user: str, peer: str, payload: Dict[str, Any]):
        key = self.norm_pair(user, peer)
        for ws in list(self.dm.get(key, [])):
            try:
                await ws.send_json(payload)
            except Exception:
                self.remove_dm(user, peer, ws)

    async def broadcast_room(self, room: str, payload: Dict[str, Any]):
        for ws in list(self.room.get(room, [])):
            try:
                await ws.send_json(payload)
            except Exception:
                self.remove_room(room, ws)

    async def notify_users(self, users: List[str], payload: Dict[str, Any]):
        for u in users:
            for ws in list(self.notify.get(u, [])):
                try:
                    await ws.send_json(payload)
                except Exception:
                    self.remove_notify(u, ws)

hub = Hub()

def ws_user_from_token(token: Optional[str]) -> str:
    if not token: raise WebSocketDisconnect(code=4401)
    try:
        return decode_token(token)
    except Exception:
        raise WebSocketDisconnect(code=4401)

@app.websocket("/ws/notify")
async def ws_notify(ws: WebSocket, token: Optional[str] = Query(None)):
    user = ws_user_from_token(token)
    await hub.add_notify(user, ws)
    try:
        while True:
            _ = await ws.receive_text()  # ignore incoming pings
    except WebSocketDisconnect:
        hub.remove_notify(user, ws)

@app.websocket("/ws/dm/{peer}")
async def ws_dm(ws: WebSocket, peer: str, token: Optional[str] = Query(None)):
    user = ws_user_from_token(token)
    await hub.add_dm(user, peer, ws)
    try:
        while True:
            data = await ws.receive_json()
            if isinstance(data, dict) and data.get("type") == "ping":
                continue
            text = (data.get("text") or "").strip()
            if not text:
                continue
            ts = now_ms()
            conn = get_db()
            db_execute(conn, "INSERT INTO messages(from_user,to_user,text,ts) VALUES (?,?,?,?)", (user, peer, text, ts))
            if not DB_IS_PG: conn.commit()
            conn.close()
            payload = {"type":"message","from": user, "to": peer, "text": text, "ts": ts}
            await hub.broadcast_dm(user, peer, payload)
            await hub.notify_users([user, peer], payload)
    except WebSocketDisconnect:
        hub.remove_dm(user, peer, ws)

@app.websocket("/ws/room/{room}")
async def ws_room(ws: WebSocket, room: str, token: Optional[str] = Query(None)):
    user = ws_user_from_token(token)
    room = (room or "").strip().lower()
    await hub.add_room(room, ws)
    try:
        while True:
            data = await ws.receive_json()
            if isinstance(data, dict) and data.get("type") == "ping":
                continue
            text = (data.get("text") or "").strip()
            if not text: continue
            ts = now_ms()
            conn = get_db()
            db_execute(conn, "INSERT INTO room_messages(room,from_user,text,ts) VALUES (?,?,?,?)", (room, user, text, ts))
            if not DB_IS_PG: conn.commit()
            conn.close()
            payload = {"type":"room","room":room,"from":user,"text":text,"ts":ts}
            await hub.broadcast_room(room, payload)
            await hub.notify_users([user], payload)
    except WebSocketDisconnect:
        hub.remove_room(room, ws)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8787"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)


@app.post("/api/signin")
async def signin(request: Request):
    try:
        payload = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not payload:
            try:
                form = await request.form()
                payload = {
                    "username": (form.get("username") or form.get("u") or "").strip(),
                    "password": (form.get("password") or form.get("p") or "").strip(),
                }
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return login(payload)  # type: ignore
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(400, f"Bad request: {e}")

