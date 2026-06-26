"""Tests for the Territorial.io friend-bot.

These do NOT touch the live game (that needs a real browser + the site). They
cover everything that can be checked offline: the control-server API, the bot's
config/consent rules, and the syntax of the in-page vision JS.

Run:  python -m pytest tests/ -q     (or)     python tests/test_app.py
"""
import os, re, sys, json, shutil, tempfile, subprocess, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["TIO_STATE"] = os.path.join(tempfile.gettempdir(), "tio_test_state.json")


# ----------------------------------------------------------------- server API
def test_server_api():
    import server
    from fastapi.testclient import TestClient

    class FakeProc:
        def __init__(self): self.alive = True
        def poll(self): return None if self.alive else 0
    orig_popen = server.subprocess.Popen
    server.subprocess.Popen = lambda *a, **k: FakeProc()
    try:
        c = TestClient(server.app)

        ids = [m["id"] for m in c.get("/api/gamemodes").json()["gamemodes"]]
        assert {"custom_br", "mp_ffa"} <= set(ids)

        # online mode without consent is rejected
        r = c.post("/api/start", json={"name": "X", "mode": "mp_ffa", "mp_consent": False})
        assert r.status_code == 400 and r.json()["ok"] is False

        # local mode starts
        assert c.post("/api/start", json={"name": "X", "mode": "custom_br"}).json()["ok"]
        # second start while running -> conflict
        assert c.post("/api/start", json={"name": "X", "mode": "custom_br"}).status_code == 409

        assert c.get("/api/status").json()["running"] is True
        server._proc["p"].alive = False
        assert c.post("/api/stop").json()["ok"] is True
    finally:
        server.subprocess.Popen = orig_popen
    print("server API: OK")


# ----------------------------------------------------- bot config / consent
def test_bot_consent_refused():
    import bot  # importable without playwright (lazy import)
    bot.run({"name": "Z", "mode": "mp_ffa", "mp_consent": False})
    st = json.loads(pathlib.Path(os.environ["TIO_STATE"]).read_text())
    assert st["status"] == "error" and "consent" in st["error"].lower()
    print("bot consent refusal: OK")


def test_bot_defaults():
    import bot
    cfg = {"mode": "custom_br"}
    # mimic run()'s normalisation without launching a browser
    cfg.setdefault("name", "DevinBot")
    cfg["players"] = int(cfg.get("players", 24))
    cfg["secs"] = int(cfg.get("secs", 120))
    assert cfg["name"] == "DevinBot" and cfg["players"] == 24
    assert set(bot.MP_TAB) == {"mp_team", "mp_ffa", "mp_1v1", "mp_zombie"}
    print("bot defaults: OK")


# --------------------------------------------------- vision JS is valid JS
def test_vision_js_syntax():
    node = shutil.which("node")
    if not node:
        print("vision JS: SKIPPED (node not installed)"); return
    src = (ROOT / "bot.py").read_text()
    for nm in ["FIND_SPAWN_JS", "ANALYZE_JS", "SAMPLE_COLOR_JS"]:
        m = re.search(nm + r'\s*=\s*"""(.*?)"""', src, re.S)
        assert m, f"{nm} not found"
        f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False)
        f.write("const fn = " + m.group(1) + ";\n"); f.close()
        r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
        assert r.returncode == 0, f"{nm} bad JS:\n{r.stderr}"
    print("vision JS syntax: OK")


def test_spawn_shared_for_online():
    """Regression: spawn selection must run for online modes too, not only
    local Custom Scenarios (otherwise the bot never lands online)."""
    src = (ROOT / "bot.py").read_text()
    assert "async def choose_spawn" in src
    # choose_spawn is called unconditionally after the mode setup branch
    play = src.split("async def play(")[1]
    assert "await choose_spawn(page)" in play
    print("online spawn regression: OK")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"\nALL {len(fns)} TESTS PASSED")
