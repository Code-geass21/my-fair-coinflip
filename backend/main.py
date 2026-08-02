import secrets
import json
import asyncio
import hashlib
import hmac
import os
import sqlite3
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI()
app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")

print("=== my-fair-coinflip backend starting — BUILD: accounts-v1 ===", flush=True)

MAX_TOSSES = 10
WIN_THRESHOLD = (MAX_TOSSES // 2) + 1  # 6 of 10 — opponent mathematically can't catch up

DB_DIR = os.environ.get("DB_DIR", "/app/data")
DB_PATH = os.path.join(DB_DIR, "game.db")


# ---------- Database ----------

def get_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
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
    row = conn.execute("SELECT wins, losses, ties FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row is None:
        return {"wins": 0, "losses": 0, "ties": 0}
    return {"wins": row["wins"], "losses": row["losses"], "ties": row["ties"]}


def record_result(winner: str | None, loser: str | None, tie: bool = False):
    conn = get_db()
    if tie:
        conn.execute("UPDATE users SET ties = ties + 1 WHERE username IN (?, ?)", (winner, loser))
    else:
        conn.execute("UPDATE users SET wins = wins + 1 WHERE username = ?", (winner,))
        conn.execute("UPDATE users SET losses = losses + 1 WHERE username = ?", (loser,))
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


def _error(status_code: int, detail: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status_code, content={"detail": detail})


# ---------- Game state ----------

class GameState:
    def __init__(self):
        self.players = {}    # ws -> username
        self.scores = {}     # username -> score (this game)
        self.roles = {}      # username -> "guesser" | "flipper"
        self.current_toss = 0
        self.pending_guess = None
        self.game_started = False
        self.game_over = False

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

    await asyncio.sleep(3)

    clinched = next((p for p, s in game.scores.items() if s >= WIN_THRESHOLD), None)
    print(f"[toss {game.current_toss}] scores={game.scores} clinched={clinched}", flush=True)

    if clinched is not None:
        early = game.current_toss < MAX_TOSSES
        await broadcast({"type": "game_over", "scores": game.scores, "winner": clinched, "early_finish": early})
        await finish_game(winner=clinched)
    elif game.current_toss >= MAX_TOSSES:
        top_score = max(game.scores.values())
        winners = [p for p, s in game.scores.items() if s == top_score]
        if len(winners) == 1:
            await broadcast({"type": "game_over", "scores": game.scores, "winner": winners[0], "early_finish": False})
            await finish_game(winner=winners[0])
        else:
            await broadcast({"type": "game_over", "scores": game.scores, "winner": "tie", "early_finish": False})
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

            elif mtype == "play_again":
                if len(game.players) == 2 and game.game_over:
                    game.new_round_setup()
                    await broadcast({"type": "roles", "roles": game.roles})
                    await broadcast({"type": "status", "message": "New game! Roles have been reshuffled."})
                    await broadcast_state()

    except Exception:
        pass
    finally:
        if websocket in game.players:
            player_id = game.players[websocket]
            del game.players[websocket]
            game.__init__()
            await broadcast({"type": "status", "message": f"{player_id} disconnected. Game reset — waiting for players."})
            await broadcast_state()
