import secrets
import json
import asyncio
import random
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")

MAX_TOSSES = 10


class GameState:
    def __init__(self):
        self.players = {}    # ws -> player_id
        self.scores = {}     # player_id -> score
        self.roles = {}      # player_id -> "guesser" | "flipper"
        self.current_toss = 0
        self.pending_guess = None   # "heads" | "tails" | None
        self.game_started = False
        self.game_over = False

    def new_round_setup(self):
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


def try_start_game():
    if len(game.players) == 2 and not game.game_started:
        game.new_round_setup()


async def handle_flip(ws):
    player_id = game.players[ws]
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

    await asyncio.sleep(3)  # let the coin animation finish

    if game.current_toss >= MAX_TOSSES:
        game.game_over = True
        top_score = max(game.scores.values())
        winners = [p for p, s in game.scores.items() if s == top_score]
        winner = winners[0] if len(winners) == 1 else "tie"
        await broadcast({"type": "game_over", "scores": game.scores, "winner": winner})

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
                else:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Room full or name already taken"}))
                    await websocket.close()

            elif mtype == "guess":
                if not game.game_started or game.game_over:
                    continue
                player_id = game.players.get(websocket)
                if player_id and game.roles.get(player_id) == "guesser" and game.pending_guess is None:
                    choice = message.get("choice")
                    if choice in ("heads", "tails"):
                        game.pending_guess = choice
                        # Deliberately do NOT reveal the guess to the flipper yet.
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
            game.__init__()  # full reset — a 2-player duel can't continue with one player gone
            await broadcast({"type": "status", "message": f"{player_id} disconnected. Game reset — waiting for players."})
            await broadcast_state()
