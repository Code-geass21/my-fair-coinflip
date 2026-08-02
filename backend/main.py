import secrets
import json
import asyncio
import hashlib
import hmac
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI()
app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")

print("=== my-fair-coinflip backend starting — BUILD: Phase 1 (Data & IST) ===", flush=True)

MAX_TOSSES = 10
WIN_THRESHOLD = (MAX_TOSSES // 2) + 1

DB_DIR = os.environ.get("DB_DIR", "/app/data")
DB_PATH = os.path.join(DB_DIR, "game.db")

# Set timezone explicitly to Indian Standard Time (IST)
IST = ZoneInfo("Asia/Kolkata")

def get_ist_now():
    return datetime.now(IST)

# ---------- Database ----------

def get_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()

    # 1. Users table (Base schema)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            ties INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Phase 1 Upgrade: Force-add the play time column to old databases
    try:
        conn.execute("ALTER TABLE users ADD COLUMN total_play_time_seconds INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass # The column already exists, safe to ignore

    # 2. Transactions table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            winner TEXT NOT NULL,
            loser TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            amount REAL NOT NULL,
            timestamp_ist TEXT NOT NULL
        )
    """)

    # 3. Sessions table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            login_time_ist TEXT NOT NULL,
            logout_time_ist TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def hash_password(password: str, salt: bytes | None = None):
    if salt is None:
        salt = secrets.token_bytes(16)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return salt.hex(), pw_hash.hex()

def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    _, candidate_hash = hash_password(password, salt)
    return hmac.compare_digest(candidate_hash, hash_hex)

def create_user(username: str, password: str) -> bool:
    salt_hex, hash_hex = hash_password(password)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, salt, password_hash) VALUES (?, ?, ?)",
            (username, salt_hex, hash_hex),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def check_login(username: str, password: str) -> bool:
    conn = get_db()
    row = conn.execute("SELECT salt, password_hash FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row is None:
        return False
    return verify_password(password, row["salt"], row["password_hash"])

def get_user_stats(username: str):
    conn = get_db()
    row = conn.execute("SELECT wins, losses, ties, total_play_time_seconds FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row is None:
        return {"wins": 0, "losses": 0, "ties": 0, "total_play_time_seconds": 0}
    return dict(row)

def record_result(winner: str | None, loser: str | None, tie: bool = False):
    conn = get_db()
    if tie:
        conn.execute("UPDATE users SET ties = ties + 1 WHERE username IN (?, ?)", (winner, loser))
    else:
        conn.execute("UPDATE users SET wins = wins + 1 WHERE username = ?", (winner,))
        conn.execute("UPDATE users SET losses = losses + 1 WHERE username = ?", (loser,))
    conn.commit()
    conn.close()

def record_transaction(winner: str, loser: str, stock_name: str, amount: float):
    conn = get_db()
    timestamp = get_ist_now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO transactions (winner, loser, stock_name, amount, timestamp_ist) VALUES (?, ?, ?, ?, ?)",
        (winner, loser, stock_name, amount, timestamp)
    )
    conn.commit()
    conn.close()

def record_session(username: str, start_time: datetime, end_time: datetime, duration: int):
    conn = get_db()
    start_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO sessions (username, login_time_ist, logout_time_ist, duration_seconds) VALUES (?, ?, ?, ?)",
        (username, start_str, end_str, duration)
    )
    conn.execute(
        "UPDATE users SET total_play_time_seconds = total_play_time_seconds + ? WHERE username = ?",
        (duration, username)
    )
    conn.commit()
    conn.close()

init_db()

# ---------- Auth API ----------

class AuthRequest(BaseModel):
    username: str
    password: str

@app.post("/api/register")
async def register(req: AuthRequest):
    username = req.username.strip()
    password = req.password
    if not username or not password:
        return _error(400, "Username and password are required.")
    if len(password) < 4:
        return _error(400, "Password must be at least 4 characters.")
    if not create_user(username, password):
        return _error(400, "That username is already taken.")
    return {"username": username, "stats": get_user_stats(username)}

@app.post("/api/login")
async def login(req: AuthRequest):
    username = req.username.strip()
    password = req.password
    if not check_login(username, password):
        return _error(401, "Invalid username or password.")
    return {"username": username, "stats": get_user_stats(username)}

@app.get("/api/transactions/{username}")
async def get_transactions(username: str):
    conn = get_db()
    # Fetch all transactions where the user was either the winner or the loser
    rows = conn.execute(
        "SELECT * FROM transactions WHERE winner = ? OR loser = ? ORDER BY id DESC",
        (username, username)
    ).fetchall()
    conn.close()

    # Convert SQLite rows to a list of dictionaries for JSON
    return [dict(row) for row in rows]

def _error(status_code: int, detail: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status_code, content={"detail": detail})

# ---------- Game state ----------

class GameState:
    def __init__(self):
        self.players = {}        # ws -> username
        self.session_starts = {} # ws -> datetime (IST)
        self.scores = {}
        self.roles = {}
        self.current_toss = 0
        self.pending_guess = None
        self.game_started = False
        self.game_over = False
        self.resolution_pending = False
        self.current_winner = None
        self.current_loser = None

    def new_round_setup(self):
        import random
        names = list(self.players.values())
        random.shuffle(names)
        self.roles = {names[0]: "guesser", names[1]: "flipper"}
        self.scores = {n: 0 for n in names}
        self.current_toss = 0
        self.pending_guess = None
        self.game_started = True
        self.game_over = False
        self.resolution_pending = False
        self.current_winner = None
        self.current_loser = None

game = GameState()

async def broadcast(msg):
    for ws in list(game.players.keys()):
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            pass

async def broadcast_state():
    await broadcast({
        "type": "state",
        "scores": game.scores,
        "roles": game.roles,
        "current_toss": game.current_toss,
        "max_tosses": MAX_TOSSES,
        "game_started": game.game_started,
        "game_over": game.game_over,
        "resolution_pending": game.resolution_pending,
        "awaiting_guess": game.game_started and not game.game_over and game.pending_guess is None,
    })

async def broadcast_lifetime_stats():
    stats = {name: get_user_stats(name) for name in game.players.values()}
    await broadcast({"type": "lifetime_stats", "stats": stats})

def try_start_game():
    if len(game.players) == 2 and not game.game_started:
        game.new_round_setup()

async def finish_game(winner: str | None, tie: bool = False):
    game.game_over = True
    names = list(game.scores.keys())
    if tie:
        record_result(names[0], names[1], tie=True)
    else:
        loser = next(n for n in names if n != winner)
        record_result(winner, loser, tie=False)
    await broadcast_lifetime_stats()

async def handle_flip(ws):
    result_int = secrets.randbelow(2)
    result = "heads" if result_int == 0 else "tails"
    guess = game.pending_guess

    guesser = next((p for p, r in game.roles.items() if r == "guesser"), None)
    flipper = next((p for p, r in game.roles.items() if r == "flipper"), None)
    correct = (guess == result)

    if correct:
        game.scores[guesser] = game.scores.get(guesser, 0) + 1
    else:
        game.scores[flipper] = game.scores.get(flipper, 0) + 1

    game.current_toss += 1
    game.pending_guess = None

    await broadcast({
        "type": "flip_result",
        "result": result,
        "guess": guess,
        "correct": correct,
        "flipper": flipper,
        "guesser": guesser,
        "toss": game.current_toss,
    })

    await asyncio.sleep(5)

    clinched = next((p for p, s in game.scores.items() if s >= WIN_THRESHOLD), None)

    # Game Over Logic Modified for Resolution Phase
    if clinched is not None:
        early = game.current_toss < MAX_TOSSES
        game.current_winner = clinched
        game.current_loser = next(p for p in game.scores.keys() if p != clinched)
        game.resolution_pending = True
        await broadcast({
            "type": "game_over", "scores": game.scores, "winner": clinched,
            "early_finish": early, "resolution_pending": True, "loser": game.current_loser
        })
    elif game.current_toss >= MAX_TOSSES:
        top_score = max(game.scores.values())
        winners = [p for p, s in game.scores.items() if s == top_score]
        if len(winners) == 1:
            game.current_winner = winners[0]
            game.current_loser = next(p for p in game.scores.keys() if p != winners[0])
            game.resolution_pending = True
            await broadcast({
                "type": "game_over", "scores": game.scores, "winner": winners[0],
                "early_finish": False, "resolution_pending": True, "loser": game.current_loser
            })
        else:
            await broadcast({"type": "game_over", "scores": game.scores, "winner": "tie", "early_finish": False, "resolution_pending": False})
            await finish_game(winner=None, tie=True)

    await broadcast_state()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            mtype = message.get("type")

            if mtype == "join":
                player_id = message.get("player_id", "").strip()
                if not player_id:
                    continue
                if len(game.players) < 2 and player_id not in game.players.values():
                    game.players[websocket] = player_id
                    game.session_starts[websocket] = get_ist_now() # Track session start
                    game.scores.setdefault(player_id, 0)
                    await broadcast({"type": "status", "message": f"{player_id} joined the room!"})
                    try_start_game()
                    if game.game_started and game.current_toss == 0:
                        await broadcast({"type": "roles", "roles": game.roles})
                    await broadcast_state()
                    await broadcast_lifetime_stats()
                else:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Room full or that account is already in the room"}))
                    await websocket.close()

            elif mtype == "guess":
                if not game.game_started or game.game_over:
                    continue
                player_id = game.players.get(websocket)
                if player_id and game.roles.get(player_id) == "guesser" and game.pending_guess is None:
                    choice = message.get("choice")
                    if choice in ("heads", "tails"):
                        game.pending_guess = choice
                        await broadcast({"type": "guess_locked", "guesser": player_id})
                        await broadcast_state()

            elif mtype == "flip":
                if not game.game_started or game.game_over:
                    continue
                player_id = game.players.get(websocket)
                if player_id and game.roles.get(player_id) == "flipper" and game.pending_guess is not None:
                    asyncio.create_task(handle_flip(websocket))

            # --- NEW: Resolving the Stock Bet ---
            elif mtype == "resolve_bet":
                if game.resolution_pending:
                    player_id = game.players.get(websocket)
                    if player_id == game.current_loser:
                        stock_name = message.get("stock_name", "UNKNOWN").upper()
                        try:
                            amount = float(message.get("amount", 0))
                        except ValueError:
                            amount = 0.0

                        record_transaction(game.current_winner, game.current_loser, stock_name, amount)
                        await finish_game(winner=game.current_winner)

                        game.resolution_pending = False

                        # 💸 Updated messaging to show the loser is paying the winner!
                        await broadcast({
                            "type": "resolution_complete",
                            "message": f"💸 {game.current_loser} paid ₹{amount} to {game.current_winner} for a share of {stock_name}!"
                        })
                        await broadcast_state()

            elif mtype == "play_again":
                if len(game.players) == 2 and game.game_over and not game.resolution_pending:
                    game.new_round_setup()
                    await broadcast({"type": "roles", "roles": game.roles})
                    await broadcast({"type": "status", "message": "New game! Roles have been reshuffled."})
                    await broadcast_state()

    except Exception:
        pass
    finally:
        if websocket in game.players:
            player_id = game.players[websocket]

            # --- NEW: Calculate Time Spent on Disconnect ---
            start_time = game.session_starts.pop(websocket, get_ist_now())
            end_time = get_ist_now()
            duration = int((end_time - start_time).total_seconds())
            record_session(player_id, start_time, end_time, duration)

            del game.players[websocket]
            dropped_mid_game = game.game_started and not game.game_over

            remaining_players = dict(game.players)
            game.scores = {}
            game.roles = {}
            game.current_toss = 0
            game.pending_guess = None
            game.game_started = False
            game.game_over = False
            game.resolution_pending = False
            game.players = remaining_players

            if dropped_mid_game:
                await broadcast({"type": "opponent_dropped", "message": f"🚨 {player_id} left the game early! The match has been reset."})
            else:
                await broadcast({"type": "status", "message": f"{player_id} left the room. Waiting for a player to join..."})

            await broadcast_state()
            await broadcast_lifetime_stats()
