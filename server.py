"""Control website for the Territorial.io friend-bot.

Serves a small control panel (static/index.html) where you type your name,
choose a gamemode and press Start. Start launches bot.py which drives the real
territorial.io in the Chrome running on this machine. Watch it play live via the
Desktop tab.
"""
import json, os, signal, subprocess, sys, time, pathlib
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

HERE = pathlib.Path(__file__).parent
# shared, writable state path (overridable so the desktop app and the bot agree)
STATE = pathlib.Path(os.environ.get("TIO_STATE") or (HERE / "bot_state.json"))
PYTHON = sys.executable  # the venv python running this server
FROZEN = getattr(sys, "frozen", False)  # True inside the packaged .exe

app = FastAPI(title="Territorial.io Friend-Bot")

_proc = {"p": None, "cfg": None}

GAMEMODES = [
    {"id": "custom_br",    "label": "محلي — Battle Royale (آمن، أوفلاين)", "safe": True},
    {"id": "custom_teams", "label": "محلي — Teams (آمن، أوفلاين)",         "safe": True},
    {"id": "mp_ffa",       "label": "أونلاين — Battle Royale (لاعبون حقيقيون)", "safe": False},
    {"id": "mp_team",      "label": "أونلاين — Team (لاعبون حقيقيون)",          "safe": False},
    {"id": "mp_1v1",       "label": "أونلاين — 1v1 (لاعبون حقيقيون)",           "safe": False},
    {"id": "mp_zombie",    "label": "أونلاين — Zombie (لاعبون حقيقيون)",        "safe": False},
]

def _running():
    p = _proc["p"]
    return p is not None and p.poll() is None

@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")

@app.get("/api/gamemodes")
def gamemodes():
    return {"gamemodes": GAMEMODES}

@app.post("/api/start")
async def start(req: Request):
    cfg = await req.json()
    if _running():
        return JSONResponse({"ok": False, "error": "البوت يعمل بالفعل. أوقفه أولاً."}, status_code=409)
    name = (cfg.get("name") or "DevinBot").strip()[:24] or "DevinBot"
    mode = cfg.get("mode", "custom_br")
    players = max(2, min(512, int(cfg.get("players", 24))))
    secs = max(20, min(900, int(cfg.get("secs", 150))))
    consent = bool(cfg.get("mp_consent"))
    botcfg = {"name": name, "mode": mode, "players": players, "secs": secs,
              "mp_consent": consent}
    fn = (cfg.get("friend_name") or "").strip()[:24]
    if fn:
        botcfg["friend_name"] = fn
    fc = cfg.get("friend_color")
    if isinstance(fc, list) and len(fc) == 3:
        botcfg["friend_color"] = [int(c) for c in fc]
    # online modes require explicit consent (player's own responsibility)
    if mode.startswith("mp_") and not consent:
        STATE.write_text(json.dumps({"status": "blocked",
            "error": "الأوضاع الأونلاين تتطلب تفعيل الموافقة (علامة صح).",
            "ts": time.time()}))
        return JSONResponse({"ok": False, "error": "consent_required"}, status_code=400)
    STATE.write_text(json.dumps({"status": "launching", "name": name, "mode": mode, "ts": time.time()}))
    # in the packaged app the exe runs itself as the bot worker (--bot);
    # during development we spawn the python bot.py script.
    if FROZEN:
        cmd = [sys.executable, "--bot", json.dumps(botcfg)]
    else:
        cmd = [PYTHON, str(HERE / "bot.py"), json.dumps(botcfg)]
    p = subprocess.Popen(cmd, cwd=str(HERE), env=os.environ.copy())
    _proc["p"] = p; _proc["cfg"] = botcfg
    return {"ok": True, "config": botcfg}

@app.post("/api/stop")
def stop():
    if _running():
        try:
            _proc["p"].send_signal(signal.SIGINT)
            time.sleep(0.5)
            if _running():
                _proc["p"].terminate()
        except Exception as e:
            return {"ok": False, "error": str(e)}
    STATE.write_text(json.dumps({"status": "stopped", "ts": time.time()}))
    return {"ok": True}

@app.get("/api/status")
def status():
    st = {}
    if STATE.exists():
        try: st = json.loads(STATE.read_text())
        except Exception: st = {}
    st["running"] = _running()
    return st

app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
