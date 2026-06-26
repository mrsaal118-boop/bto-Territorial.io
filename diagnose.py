"""Live diagnostic for the Territorial.io friend-bot — run this on YOUR machine.

It opens the REAL https://territorial.io/ in a visible browser and checks that
everything the bot relies on actually matches the live site: the name input,
the menu buttons (Single Player / Custom Scenario / Multiplayer / the mode tabs
/ Ready / Play), and the game canvas (#canvasA, 2D, readable pixels). It writes a
report and screenshots so we can calibrate the bot to what the site really is.

Why a separate tool: the cloud session that wrote the bot cannot reach
territorial.io (its network is locked down), so the live check has to run where
you are. Send me the printed REPORT (and the screenshots in ./diag/) and I'll
fix any selector that doesn't match.

Usage:
    pip install -r requirements.txt
    python -m playwright install chromium
    python diagnose.py            # visible window, full report
    python diagnose.py --headless # no window (just the report + screenshots)
"""
import asyncio, os, sys, json, pathlib
from playwright.async_api import async_playwright

GAME_URL = "https://territorial.io/"
OUT = pathlib.Path(__file__).with_name("diag"); OUT.mkdir(exist_ok=True)
HEADLESS = "--headless" in sys.argv

# the exact strings the bot clicks, grouped by the screen they belong to
MENU_TEXTS = ["Single Player", "Custom Scenario", "Multiplayer",
              "Battle Royale", "Teams", "Team", "1v1", "Zombie",
              "Play", "Ready"]


async def dump(page, label):
    """List the interactive DOM (inputs / buttons / p / a) on the current screen."""
    info = await page.evaluate("""() => {
      const grab = sel => [...document.querySelectorAll(sel)]
        .map(e => (e.textContent||e.placeholder||'').trim()).filter(Boolean).slice(0,60);
      const canvases = [...document.querySelectorAll('canvas')].map(c => {
        let two=false; try{ two=!!c.getContext('2d'); }catch(e){}
        let readable=false;
        if(two){ try{ c.getContext('2d').getImageData(0,0,1,1); readable=true; }catch(e){} }
        return {id:c.id, w:c.width, h:c.height, ctx2d:two, pixelsReadable:readable};
      });
      return {
        inputs: [...document.querySelectorAll('input')].map(i=>({type:i.type,id:i.id,ph:i.placeholder})),
        buttons: grab('button'),
        paragraphs: grab('p'),
        links: grab('a'),
        canvases,
      };
    }""")
    print(f"\n=== {label} ===")
    print(json.dumps(info, indent=1, ensure_ascii=False))
    await page.screenshot(path=str(OUT / f"{label}.png"))
    return info


async def can_click(page, text):
    """Does a clickable element with this exact text exist? (no actual click)"""
    try:
        loc = page.locator(f"button:has-text('{text}'), p:has-text('{text}'), a:has-text('{text}')")
        return await loc.count() > 0
    except Exception:
        return False


async def main():
    report = {"url": GAME_URL, "checks": {}}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS, args=["--start-maximized"])
        ctx = await browser.new_context(no_viewport=True)
        page = await ctx.new_page()
        await page.goto(GAME_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        home = await dump(page, "01_home")

        # 1. name input present?
        report["checks"]["name_input"] = any(i["type"] in ("text", "") for i in home["inputs"])
        # 2. canvasA present + 2D + readable?
        ca = next((c for c in home["canvases"] if c["id"] == "canvasA"), None)
        report["checks"]["canvasA_present"] = ca is not None
        report["checks"]["canvasA_2d_readable"] = bool(ca and ca["ctx2d"] and ca["pixelsReadable"])
        report["canvasA"] = ca
        # 3. which menu texts are reachable as HTML elements on the home screen?
        report["checks"]["menu_texts_found"] = {t: await can_click(page, t) for t in MENU_TEXTS}

        # try to walk into Single Player -> Custom Scenario so we can see those screens
        for step in ["Single Player", "Custom Scenario"]:
            if await can_click(page, step):
                try:
                    await page.locator(f"button:has-text('{step}'), p:has-text('{step}')").first.click(timeout=4000)
                    await page.wait_for_timeout(2000)
                    await dump(page, "02_" + step.replace(" ", "_"))
                except Exception as e:
                    print(f"could not click '{step}':", e)

        print("\n\n================  REPORT  ================")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        verdict = (report["checks"]["name_input"]
                   and report["checks"]["canvasA_2d_readable"])
        print("\nBOTTOM LINE:",
              "core assumptions hold ✅" if verdict else "MISMATCH — bot needs adjusting ⚠️")
        print("Menu texts NOT found as HTML (bot would mis-click these):",
              [t for t, ok in report["checks"]["menu_texts_found"].items() if not ok])
        print(f"\nScreenshots + this report are in: {OUT}")
        (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

        if not HEADLESS:
            print("\nLeaving the window open 20s so you can look around...")
            await page.wait_for_timeout(20000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
