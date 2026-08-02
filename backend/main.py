import secrets
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI()

# Mount the 'frontend' directory to serve index.html, style.css, script.js
app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")

# Game state
class GameState:
    def __init__(self):
        self.players = {}  # {websocket: player_id}
        self.scores = {"playerA": 0, "playerB": 0}
        self.server_seed = None
        self.client_seed = None
        self.current_toss = 0
        self.last_result = None

game = GameState()

# Message models
class JoinMessage(BaseModel):
    player_id: str

async def broadcast_state():
    state_msg = {
        "type": "state",
        "scores": game.scores,
        "current_toss": game.current_toss,
        "last_result": game.last_result
    }
    for ws in game.players:
        try:
            await ws.send_text(json.dumps(state_msg))
        except:
            pass # Remove disconnected player if needed

async def handle_flip(ws, client_seed):
    game.current_toss += 1
    # Generate a cryptographically secure random number
    # using Python's 'secrets' module. 0=Heads, 1=Tails.
    result_int = secrets.randbelow(2)
    result = "heads" if result_int == 0 else "tails"
    
    game.last_result = result
    # Simplified Best of 10 logic
    player = game.players[ws]
    game.scores[player] += 1

    flip_msg = {
        "type": "flip_result",
        "result": result,
        "player": player,
        "client_seed": client_seed
    }
    for client_ws in game.players:
        await client_ws.send_text(json.dumps(flip_msg))
    
    await asyncio.sleep(3) # Wait for animation to finish
    await broadcast_state()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message["type"] == "join":
                player_id = message["player_id"]
                if len(game.players) < 2:
                    game.players[websocket] = player_id
                    print(f"Player {player_id} joined.")
                    await broadcast_state()
                else:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Room full"}))
                    await websocket.close()

            elif message["type"] == "flip":
                client_seed = message.get("client_seed", "default_seed")
                await handle_flip(websocket, client_seed)

    except WebSocketDisconnect:
        del game.players[websocket]
        print("Player disconnected.")
