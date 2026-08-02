import secrets
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI()

# Mount the frontend directory
app.mount("/game", StaticFiles(directory="frontend", html=True), name="frontend")

class GameState:
    def __init__(self):
        self.players = {}  
        self.scores = {} # Dynamically tracks actual names
        self.current_toss = 0
        self.last_result = None

game = GameState()

async def broadcast_state():
    state_msg = {
        "type": "state",
        "scores": game.scores,
        "current_toss": game.current_toss,
        "last_result": game.last_result
    }
    # Safely iterate over a copy of the keys
    for ws in list(game.players.keys()):
        try:
            await ws.send_text(json.dumps(state_msg))
        except:
            pass

async def handle_flip(ws, client_seed):
    if ws not in game.players:
        return
        
    game.current_toss += 1
    result_int = secrets.randbelow(2)
    result = "heads" if result_int == 0 else "tails"
    
    game.last_result = result
    player = game.players[ws]
    game.scores[player] += 1 # Works perfectly with dynamic names now

    flip_msg = {
        "type": "flip_result",
        "result": result,
        "player": player,
        "client_seed": client_seed
    }
    for client_ws in list(game.players.keys()):
        try:
            await client_ws.send_text(json.dumps(flip_msg))
        except:
            pass
    
    await asyncio.sleep(3) # Wait for UI animation
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
                    game.scores[player_id] = 0 # Initialize their score properly
                    
                    # Notify everyone that someone joined
                    notify_msg = {"type": "status", "message": f"{player_id} joined the room!"}
                    for client_ws in list(game.players.keys()):
                        try:
                            await client_ws.send_text(json.dumps(notify_msg))
                        except:
                            pass
                            
                    await broadcast_state()
                else:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Room full"}))
                    await websocket.close()

            elif message["type"] == "flip":
                client_seed = message.get("client_seed", "default_seed")
                await handle_flip(websocket, client_seed)

    except WebSocketDisconnect:
        if websocket in game.players:
            player_id = game.players[websocket]
            del game.players[websocket]
            
            # Notify the remaining player
            notify_msg = {"type": "status", "message": f"{player_id} disconnected."}
            for client_ws in list(game.players.keys()):
                try:
                    await client_ws.send_text(json.dumps(notify_msg))
                except:
                    pass
            await broadcast_state()
