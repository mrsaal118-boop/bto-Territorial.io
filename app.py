"""Territorial.io friend-bot — Windows desktop app.

A single window (pywebview) showing the control panel. It starts the local
FastAPI control server in a background thread and points the window at it, so
you get a real desktop application (no browser, no website) that opens the game,
plays on its own and shows live status.

The same packaged .exe doubles as the bot worker: when the control server starts
a game it relaunches this exe with `--bot <json>` and that path runs the bot.

Run from source:   python app.py
Build a Windows .exe is done in CI (.github/workflows/build-windows.yml).
"""
import os, sys, json, time, socket, tempfile, threading, contextlib

# Share one writable state file between the UI server and the bot worker.
os.environ.setdefault("TIO_STATE", os.path.join(tempfile.gettempdir(), "tio_bot_state.json"))
# When frozen, Playwright browsers are bundled inside the package.
if getattr(sys, "frozen", False):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

def _run_bot_worker():
    """Frozen-exe worker mode: `app.exe --bot '<cfg json>'`."""
    i = sys.argv.index("--bot")
    cfg = json.loads(sys.argv[i + 1]) if len(sys.argv) > i + 1 else {}
    import bot
    bot.run(cfg)

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]; s.close(); return port

def _wait_up(port, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        with contextlib.suppress(Exception):
            socket.create_connection(("127.0.0.1", port), 0.3).close(); return True
        time.sleep(0.1)
    return False

def main():
    if "--bot" in sys.argv:
        _run_bot_worker(); return

    port = int(os.environ.get("TIO_PORT", "0")) or _free_port()
    import uvicorn
    from server import app as fastapi_app
    threading.Thread(
        target=lambda: uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_level="warning"),
        daemon=True,
    ).start()
    _wait_up(port)

    url = f"http://127.0.0.1:{port}/"
    try:
        import webview  # pywebview -> native desktop window
        webview.create_window("بوت Territorial.io الصديق", url, width=660, height=940)
        webview.start()
    except Exception as e:
        # Fallback if no native webview runtime: open in the default browser.
        print("pywebview unavailable (%s); opening in browser: %s" % (e, url))
        import webbrowser; webbrowser.open(url)
        while True:
            time.sleep(3600)

if __name__ == "__main__":
    main()
