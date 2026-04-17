# Quantum Tic Tac Toe — FastAPI + Render

Real-time multiplayer Quantum Tic Tac Toe with room codes, deployed on Render.

## Project structure

```
quantum-ttt/
├── main.py            ← FastAPI app (WebSocket + game logic + static file serving)
├── public/
│   └── index.html     ← Frontend
├── render.yaml        ← Render service config
└── requirements.txt
```

## Deploy to Render (free)

1. Push this folder to a GitHub repo (can be private).

2. Go to https://render.com → New → Web Service → connect your repo.

3. Render auto-detects `render.yaml` and fills everything in.
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

4. Hit **Deploy**. You'll get a URL like `https://quantum-ttt.onrender.com`.

That's it — WebSockets work out of the box on Render.

> **Note:** Free tier services spin down after 15 min of inactivity and take ~30s to
> wake up on the next request. Upgrade to a paid plan ($7/mo) to keep it always-on.

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# open http://localhost:8000
```

## How rooms work

1. **Host** clicks HOST ROOM → server generates a 6-char code
2. **Guest** clicks JOIN ROOM → enters the code → connected
3. Host sees **▶ START GAME** button → clicks it → game begins
4. All game state is authoritative on the server — no cheating possible

## Quantum rules

- Each turn: place in **two cells** (superposition). Shown as X₁, O₂…
- When entanglements form a **cycle**, collapse is triggered
- The player who did **NOT** create the cycle picks which cell gets the classical mark
- First to get **three classical marks in a row** wins
