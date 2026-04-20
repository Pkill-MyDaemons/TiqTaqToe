from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
import random
import string
from typing import Optional

app = FastAPI()

# ─── Room storage ─────────────────────────────────────────────────────────────
# rooms[code] = { "host": WebSocket|None, "guest": WebSocket|None, "state": dict|None }
rooms: dict[str, dict] = {}


def generate_code() -> str:
    chars = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
    while True:
        code = "".join(random.choices(chars, k=6))
        if code not in rooms:
            return code


async def safe_send(ws: Optional[WebSocket], msg: dict):
    if ws is None:
        return
    try:
        await ws.send_text(json.dumps(msg))
    except Exception:
        pass


# ─── WebSocket ────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    role: Optional[str] = None
    code: Optional[str] = None

    try:
        async for raw in websocket.iter_text():
            msg = json.loads(raw)
            t = msg.get("type")

            # HOST: create a new room
            if t == "host":
                code = generate_code()
                rooms[code] = {"host": websocket, "guest": None, "state": None}
                role = "host"
                await safe_send(websocket, {"type": "room_created", "code": code})

            # GUEST: join existing room
            elif t == "join":
                code = msg.get("code", "").strip().upper()
                room = rooms.get(code)
                if not room:
                    await safe_send(websocket, {"type": "error", "msg": "Room not found. Check the code."})
                    continue
                if room["guest"] is not None:
                    await safe_send(websocket, {"type": "error", "msg": "Room is already full."})
                    continue
                room["guest"] = websocket
                role = "guest"
                await safe_send(websocket, {"type": "joined", "code": code})
                await safe_send(room["host"], {"type": "guest_joined"})

            # HOST: start the game
            elif t == "start":
                if not code or code not in rooms:
                    continue
                room = rooms[code]
                state = init_state()
                room["state"] = state
                await safe_send(room["host"], {"type": "start", "symbol": "X", "state": state})
                await safe_send(room["guest"], {"type": "start", "symbol": "O", "state": state})

            # MOVE: place quantum move (two cells)
            elif t == "move":
                if not code or code not in rooms:
                    continue
                room = rooms[code]
                if not room["state"]:
                    continue
                result = apply_move(room["state"], msg["cells"])
                room["state"] = result["state"]
                payload = {"type": "state", "state": result["state"], "event": result["event"]}
                await safe_send(room["host"], payload)
                await safe_send(room["guest"], payload)

            # COLLAPSE: choose which cell collapses
            elif t == "collapse":
                if not code or code not in rooms:
                    continue
                room = rooms[code]
                if not room["state"]:
                    continue
                result = apply_collapse(room["state"], msg["cell"])
                room["state"] = result["state"]
                payload = {"type": "state", "state": result["state"], "event": result["event"]}
                await safe_send(room["host"], payload)
                await safe_send(room["guest"], payload)

            # RESET: play again
            elif t == "reset":
                if not code or code not in rooms:
                    continue
                room = rooms[code]
                state = init_state()
                room["state"] = state
                payload = {"type": "state", "state": state, "event": "reset"}
                await safe_send(room["host"], payload)
                await safe_send(room["guest"], payload)

    except WebSocketDisconnect:
        pass
    finally:
        if code and code in rooms:
            room = rooms[code]
            if role == "host":
                await safe_send(room.get("guest"), {"type": "opponent_left"})
                del rooms[code]
            elif role == "guest":
                room["guest"] = None
                await safe_send(room.get("host"), {"type": "opponent_left"})


# ─── Game logic (authoritative on server) ────────────────────────────────────

def init_state() -> dict:
    return {
        "board": [[] for _ in range(9)],
        "classical": [None] * 9,
        "moveNum": 1,
        "currentTurn": "X",
        "phase": "placing",       # "placing" | "collapse"
        "collapseInfo": None,
        "entanglements": [],
        "winner": None,
        "winLine": None,
    }


def apply_move(state: dict, cells: list) -> dict:
    c1, c2 = cells
    sym = state["currentTurn"]
    mn = state["moveNum"]

    state["board"][c1].append({"sym": sym, "moveNum": mn})
    state["board"][c2].append({"sym": sym, "moveNum": mn})
    state["entanglements"].append({"moveNum": mn, "sym": sym, "cells": [c1, c2]})

    cycle = detect_cycle(state)
    event = "move"

    if cycle:
        chooser = "O" if sym == "X" else "X"
        state["phase"] = "collapse"
        state["collapseInfo"] = {
            "moveNum": cycle["cycleMove"],
            "chooser": chooser,
            "cells": cycle["cells"],
        }
        event = "collapse_needed"
    else:
        state["moveNum"] += 1
        state["currentTurn"] = "O" if sym == "X" else "X"

    return {"state": state, "event": event}


def apply_collapse(state: dict, cell_index: int) -> dict:
    info = state["collapseInfo"]
    mn = info["moveNum"]

    mark = next((m for m in state["board"][cell_index] if m["moveNum"] == mn), None)
    if not mark and state["board"][cell_index]:
        mark = state["board"][cell_index][0]
    if not mark:
        return {"state": state, "event": "error"}

    _collapse_cell(state, cell_index, mark["sym"], mark["moveNum"])

    state["collapseInfo"] = None
    state["phase"] = "placing"
    state["moveNum"] += 1
    state["currentTurn"] = "O" if state["currentTurn"] == "X" else "X"

    winner = check_winner(state["classical"])
    event = "collapsed"
    if winner:
        state["winner"] = winner["sym"]
        state["winLine"] = winner["line"]
        event = "winner"
    elif all(c is not None for c in state["classical"]):
        state["winner"] = "draw"
        event = "draw"

    return {"state": state, "event": event}


def _collapse_cell(state: dict, idx: int, sym: str, move_num: int):
    state["classical"][idx] = sym
    state["board"][idx] = []
    ent = next((e for e in state["entanglements"] if e["moveNum"] == move_num), None)
    if ent:
        partner = next((c for c in ent["cells"] if c != idx), None)
        if partner is not None:
            state["board"][partner] = [
                m for m in state["board"][partner] if m["moveNum"] != move_num
            ]
        state["entanglements"].remove(ent)


def detect_cycle(state: dict) -> Optional[dict]:
    adj: dict[int, list] = {}
    for ent in state["entanglements"]:
        a, b = ent["cells"]
        if state["classical"][a] is not None or state["classical"][b] is not None:
            continue
        adj.setdefault(a, []).append({"cell": b, "moveNum": ent["moveNum"]})
        adj.setdefault(b, []).append({"cell": a, "moveNum": ent["moveNum"]})

    visited: set[int] = set()
    result: dict = {"found": False, "cells": set(), "cycleMove": None}

    def dfs(node: int, parent: int, parent_move: int) -> bool:
        visited.add(node)
        for nb in adj.get(node, []):
            if nb["cell"] == parent and nb["moveNum"] == parent_move:
                continue
            if nb["cell"] in visited:
                result["found"] = True
                result["cells"].add(node)
                result["cells"].add(nb["cell"])
                result["cycleMove"] = state["entanglements"][-1]["moveNum"]
                return True
            if dfs(nb["cell"], node, nb["moveNum"]):
                result["cells"].add(node)
                return True
        return False

    for i in range(9):
        if i not in visited and i in adj:
            dfs(i, -1, -1)
            if result["found"]:
                break

    if result["found"]:
        return {"cycleMove": result["cycleMove"], "cells": list(result["cells"])}
    return None


def check_winner(classical: list) -> Optional[dict]:
    lines = [
        [0,1,2],[3,4,5],[6,7,8],
        [0,3,6],[1,4,7],[2,5,8],
        [0,4,8],[2,4,6],
    ]
    for line in lines:
        a, b, c = line
        if classical[a] and classical[a] == classical[b] == classical[c]:
            return {"sym": classical[a], "line": line}
    return None


# ─── Serve frontend ───────────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory="public", html=True), name="static")
