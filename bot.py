"""Territorial.io friend-bot.

Drives the REAL territorial.io and plays on its own by reading the game canvas
pixels and dispatching real mouse/keyboard input.

Strategy (smart economy):
  * It NEVER dumps 100% of its balance. Each tick it computes an attack power
    (% of balance per attack) from its situation and sets the bottom power bar.
  * Attacks are made with hover+Space at that exact power, on only a few of the
    most open fronts, so plenty of troops stay home for defence (and to earn
    interest). When there is nothing good to take it SAVES (skips attacking) and
    lets the balance + interest grow.
  * When boxed in by water it crosses the sea with boats (B key) to reach new
    land, and it zooms out so it can see and expand across the whole map.
  * A friend colour, if given, is treated as un-attackable (never targeted).

Browser: connects to an existing Chrome over CDP when $TIO_CDP (or cfg["cdp"]) is
set; otherwise it launches its own Chromium (used by the Windows desktop app).

Usage:
    python bot.py '{"name":"DevinBot","mode":"custom_br","players":24,"secs":150}'
"""
import asyncio, sys, json, time, os, pathlib
# Playwright is imported lazily inside play() so this module can be imported
# (for config validation, tests, the --bot worker dispatch) without it.

GAME_URL = "https://territorial.io/"

STATE = pathlib.Path(os.environ.get("TIO_STATE") or pathlib.Path(__file__).with_name("bot_state.json"))
def report(**kw):
    try:
        cur = json.loads(STATE.read_text()) if STATE.exists() else {}
    except Exception:
        cur = {}
    cur.update(kw); cur["ts"] = time.time()
    STATE.write_text(json.dumps(cur))

# ---------------------------------------------------------------- canvas vision
FIND_SPAWN_JS = """() => {
  const c=document.getElementById('canvasA');const ctx=c.getContext('2d');
  const W=c.width,H=c.height;const d=ctx.getImageData(0,0,W,H).data;
  function isLand(x,y){const i=(y*W+x)*4;const r=d[i],g=d[i+1],b=d[i+2];
    if(b>r+25 && b>g+5) return false;
    if(r<40&&g<40&&b<40) return false;
    return (g>70 || r>70);
  }
  const cx=W>>1, cy=H>>1; let best=null;
  for(let rad=0; rad<Math.min(W,H)/2-60; rad+=8){
    for(let a=0;a<360;a+=12){
      const x=Math.round(cx+rad*Math.cos(a*Math.PI/180));
      const y=Math.round(cy+rad*Math.sin(a*Math.PI/180));
      if(x<80||y<80||x>W-80||y>H-80) continue;
      let ok=true;
      for(let ddx=-30;ddx<=30&&ok;ddx+=15)for(let ddy=-30;ddy<=30&&ok;ddy+=15){if(!isLand(x+ddx,y+ddy))ok=false;}
      if(ok){best={x,y};break;}
    }
    if(best)break;
  }
  const r=c.getBoundingClientRect();
  return best?{x:best.x,y:best.y,W,H,cssW:r.width,cssH:r.height}:null;
}"""

# Re-learns the own colour from a centre patch (camera keeps us centred), finds
# own pixels + their centroid, then casts rays outward. Each ray yields either a
# LAND target (neutral/enemy land just past our frontier) or, if it meets the
# sea, a BOAT target (the first land found across the water). Friend colour is
# never crossed or targeted.
# args: [nAngles, friendColorOrNull, maxWaterCross]
ANALYZE_JS = """([nAngles, fc, maxW]) => {
  const c=document.getElementById('canvasA');
  const W=c.width,H=c.height; const SC=4; const w=(W/SC)|0, h=(H/SC)|0;
  let off=window.__off; if(!off||off.width!==w){off=window.__off=document.createElement('canvas');off.width=w;off.height=h;}
  const octx=off.getContext('2d'); octx.drawImage(c,0,0,w,h);
  const d=octx.getImageData(0,0,w,h).data;
  const r=c.getBoundingClientRect();const sx=r.width/W, sy=r.height/H;
  function idx(x,y){return ((y|0)*w+(x|0))*4;}
  // water = blue OR cyan/teal: blue clearly above red, and not a green land.
  function water(x,y){const i=idx(x,y);return d[i]<d[i+2]-14 && d[i+2]>80;}
  function dark(x,y){const i=idx(x,y);return d[i]<58&&d[i+1]<58&&d[i+2]<58;}
  function ui(x,y){const i=idx(x,y);const R=d[i],G=d[i+1],B=d[i+2];
    return dark(x,y) || (R>205&&G>205&&B>205);}
  function friend(x,y){if(!fc)return false;const i=idx(x,y);
    return Math.abs(d[i]-fc[0])+Math.abs(d[i+1]-fc[1])+Math.abs(d[i+2]-fc[2])<40;}
  const cx0=(w/2)|0, cy0=(h/2)|0; const hist={};
  for(let yy=cy0-18;yy<=cy0+18;yy++)for(let xx=cx0-18;xx<=cx0+18;xx++){
    if(xx<0||yy<0||xx>=w||yy>=h)continue; if(water(xx,yy)||ui(xx,yy))continue;
    const i=idx(xx,yy); const k=(d[i]>>3)+','+(d[i+1]>>3)+','+(d[i+2]>>3); hist[k]=(hist[k]||0)+1;
  }
  let bk=null,bc=0; for(const k in hist){if(hist[k]>bc){bc=hist[k];bk=k;}}
  if(!bk) return {n:0, land:[], boats:[], oc:null};
  const oc=bk.split(',').map(n=>+n*8+4);
  function own(x,y){if(x<0||y<0||x>=w||y>=h)return false;const i=idx(x,y);return Math.abs(d[i]-oc[0])+Math.abs(d[i+1]-oc[1])+Math.abs(d[i+2]-oc[2])<34;}
  let sumx=0,sumy=0,n=0;
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){if(own(x,y)){sumx+=x;sumy+=y;n++;}}
  if(n<5) return {n, land:[], boats:[], oc};
  const ccx=sumx/n, ccy=sumy/n;
  const land=[], boats=[];
  const toCss=(tx,ty)=>({cx: tx*SC*sx, cy: ty*SC*sy});
  for(let k=0;k<nAngles;k++){
    const ang=k*2*Math.PI/nAngles; const dx=Math.cos(ang), dy=Math.sin(ang);
    let last=-1, gap=0, hitFriend=false;
    for(let t=1;t<Math.max(w,h);t++){const x=ccx+dx*t, y=ccy+dy*t; if(x<1||y<1||x>w-2||y>h-2)break;
      if(friend(x,y)){hitFriend=true;break;}
      if(own(x,y)||ui(x,y)){last=t;gap=0;} else {gap++; if(gap>4)break;}}
    if(last<1||hitFriend) continue;
    // (a) land frontier: a few px past our edge, onto capturable land
    const t2=last+4; const lp=toCss(ccx+dx*t2, ccy+dy*t2);
    const lx=ccx+dx*t2, ly=ccy+dy*t2;
    if(lx>1&&ly>1&&lx<w-2&&ly<h-2 && !own(lx,ly)&&!water(lx,ly)&&!ui(lx,ly)&&!friend(lx,ly)){
      land.push({cx:lp.cx, cy:lp.cy, r:last});
    } else {
      // (b) boat: walk from our edge across the sea to the first land beyond
      let t=last+1, sawWater=0;
      for(; t<last+maxW && (ccx+dx*t)>1 && (ccy+dy*t)>1 && (ccx+dx*t)<w-2 && (ccy+dy*t)<h-2; t++){
        const x=ccx+dx*t, y=ccy+dy*t;
        if(water(x,y)){sawWater++;continue;}
        if(ui(x,y)) continue;
        if(friend(x,y)) break;
        if(sawWater>=2 && !own(x,y)){ const bp=toCss(x+dx*1.5,y+dy*1.5); boats.push({cx:bp.cx,cy:bp.cy,r:t}); break; }
      }
    }
  }
  return {n, oc, ccx:ccx*SC*sx, ccy:ccy*SC*sy, land, boats};
}"""

# ---------------------------------------------------------------- browser setup
async def open_page(p, cfg):
    cdp = cfg.get("cdp") or os.environ.get("TIO_CDP")
    if cdp:
        browser = await p.chromium.connect_over_cdp(cdp)
        ctx = browser.contexts[0]
        for pg in ctx.pages:
            if "territorial.io" in pg.url:
                return browser, pg
        pg = ctx.pages[0] if ctx.pages else await ctx.new_page()
        return browser, pg
    # launch our own browser (Windows desktop app path)
    browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
    ctx = await browser.new_context(no_viewport=True)
    pg = await ctx.new_page()
    await pg.goto(GAME_URL)
    return browser, pg

async def fill_first(page, selector, value):
    try:
        await page.locator(selector).first.fill(str(value)); return True
    except Exception as e:
        print("fill", selector, e); return False

async def click_text(page, text, timeout=4000):
    try:
        await page.locator(f"button:has-text('{text}'), p:has-text('{text}')").first.click(timeout=timeout)
        return True
    except Exception as e:
        print("click", text, e); return False

async def setup_custom(page, name, players, mode):
    await page.goto(GAME_URL); await page.wait_for_timeout(3500)
    await fill_first(page, "input[type=text]", name)
    await click_text(page, "Custom Scenario"); await page.wait_for_timeout(1200)
    await fill_first(page, "input[type=number]", players)
    if mode == "custom_teams":
        await click_text(page, "Teams", timeout=2000)
    else:
        await click_text(page, "Battle Royale", timeout=2000)
    await page.wait_for_timeout(400)
    await click_text(page, "Play"); await page.wait_for_timeout(2500)

# dominant territory colour in a patch around a fractional canvas point
# (skips white/black name text and water so we get the player's land colour)
SAMPLE_COLOR_JS = """([fx,fy,rf]) => {
  const c=document.getElementById('canvasA');const W=c.width,H=c.height;
  const ctx=c.getContext('2d');
  const cx=Math.round(fx*W), cy=Math.round(fy*H);
  const R=Math.max(8,Math.round(rf*W));
  const x0=Math.max(0,cx-R),y0=Math.max(0,cy-R);
  const w=Math.min(W-x0,2*R),h=Math.min(H-y0,2*R); if(w<=0||h<=0)return null;
  const d=ctx.getImageData(x0,y0,w,h).data; const hist={};
  for(let i=0;i<d.length;i+=4){const r=d[i],g=d[i+1],b=d[i+2];
    if(r>205&&g>205&&b>205)continue;                 // white text
    if(r<45&&g<45&&b<45)continue;                    // black text
    if(r<b-14&&b>80)continue;                         // water
    const k=(r>>3)+','+(g>>3)+','+(b>>3); hist[k]=(hist[k]||0)+1;}
  let bk=null,bc=0;for(const k in hist){if(hist[k]>bc){bc=hist[k];bk=k;}}
  return bk?bk.split(',').map(n=>+n*8+4):null;
}"""

async def resolve_friend_color(page, friend_name, CW, CH):
    """Best-effort: OCR the map, find the friend's name label and read the
    colour of the territory under it. Returns [r,g,b] or None. Needs Tesseract;
    if unavailable it quietly returns None (the colour picker is the fallback)."""
    try:
        import pytesseract
        from pytesseract import Output
    except Exception:
        print("friend-name: pytesseract not available; using colour fallback"); return None
    want = friend_name.strip().casefold()
    path = "/tmp/tio_friend.png" if os.name != "nt" else os.path.join(os.environ.get("TEMP", "."), "tio_friend.png")
    for attempt in range(2):
        try:
            await page.locator("#canvasA").screenshot(path=path)
            d = pytesseract.image_to_data(path, output_type=Output.DICT)
        except Exception as e:
            print("friend-name OCR error:", e); return None
        n = len(d["text"])
        for i in range(n):
            txt = (d["text"][i] or "").strip()
            if not txt:
                continue
            if want in txt.casefold() or txt.casefold() in want:
                fx = (d["left"][i] + d["width"][i]/2) / max(1, CW)
                fy = (d["top"][i] + d["height"][i]/2) / max(1, CH)
                col = await page.evaluate(SAMPLE_COLOR_JS, [fx, fy, 0.035])
                if col:
                    print(f"friend-name: matched '{txt}' -> colour {col}")
                    return [int(c) for c in col]
        await page.wait_for_timeout(2500)
    print(f"friend-name: '{friend_name}' not found on map; using colour fallback")
    return None

async def choose_spawn(page, attempts=6):
    """Find a safe patch of open land and click it to place our starting
    territory. Used in BOTH local and online modes: territorial.io makes you
    pick a spawn on the map when a match starts, so this must run for
    multiplayer too (otherwise the bot never lands and just idles). Retries
    while the map is still loading and returns the spawn info, or None."""
    for i in range(attempts):
        sp = await page.evaluate(FIND_SPAWN_JS)
        if sp:
            sxr = sp['cssW'] / sp['W']; syr = sp['cssH'] / sp['H']
            cssx, cssy = sp['x'] * sxr, sp['y'] * syr
            await page.mouse.click(cssx, cssy); await page.wait_for_timeout(700)
            await page.mouse.click(cssx, cssy); await page.wait_for_timeout(1700)
            print("spawn:", sp, "(attempt", i + 1, ")")
            return sp
        report(status="playing", phase="find_spawn", spawn_try=i + 1)
        await page.wait_for_timeout(1300)
    return None

MP_TAB = {"mp_team": "Team", "mp_ffa": "Battle Royale", "mp_1v1": "1v1", "mp_zombie": "Zombie"}

async def setup_multiplayer(page, name, mode):
    """Enter a real multiplayer lobby, pick the mode tab and press Ready.

    Only ever reached when the user ticked the consent box. Real players are
    involved here; this is the player's own responsibility.
    """
    await page.goto(GAME_URL); await page.wait_for_timeout(3500)
    await fill_first(page, "input[type=text]", name)
    ok_mp = await click_text(page, "Multiplayer"); await page.wait_for_timeout(2500)
    tab = MP_TAB.get(mode, "Battle Royale")
    ok_tab = await click_text(page, tab, timeout=4000); await page.wait_for_timeout(800)
    # the lobby's confirm button is "Ready" in most modes but "Play" in some;
    # try both so we don't stall in the lobby.
    ok_ready = await click_text(page, "Ready", timeout=4000)
    if not ok_ready:
        ok_ready = await click_text(page, "Play", timeout=3000)
    report(status="entering_game", phase="lobby",
           entered_mp=ok_mp, picked_mode=ok_tab, pressed_ready=ok_ready, tab=tab)
    print("multiplayer entry:", {"mp": ok_mp, "tab": (tab, ok_tab), "ready": ok_ready})
    # wait for the match to actually start (lobby countdown)
    await page.wait_for_timeout(8000)

# ---------------------------------------------------------------- the game loop
async def play(cfg):
    name = cfg["name"]; mode = cfg["mode"]; players = cfg["players"]; secs = cfg["secs"]
    friend_color = cfg.get("friend_color")
    is_mp = mode.startswith("mp_")
    report(status="starting", name=name, mode=mode, players=players)
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, page = await open_page(p, cfg)
        try: await page.bring_to_front()
        except Exception: pass
        report(status="entering_game")
        if is_mp:
            await setup_multiplayer(page, name, mode)
        else:
            await setup_custom(page, name, players, mode)

        # Pick where to land — required for online modes too (you choose a spawn
        # on the map when the match starts), not just local Custom Scenarios.
        report(status="playing", phase="find_spawn")
        sp = await choose_spawn(page)
        if not sp:
            report(status="error",
                   error="no safe spawn found (map not ready or no open land)")
            return

        rect = await page.evaluate("()=>{const r=document.getElementById('canvasA').getBoundingClientRect();return {l:r.left,t:r.top,w:r.width,h:r.height};}")
        CL, CT, CW, CH = rect['l'], rect['t'], rect['w'], rect['h']
        TOTAL = (await page.evaluate("()=>{const c=document.getElementById('canvasA');return (c.width/4|0)*(c.height/4|0);}"))

        # friend by NAME: if given, find their label and treat that colour as un-attackable
        fname = cfg.get("friend_name")
        if fname and not friend_color:
            report(status="playing", phase="find_friend")
            friend_color = await resolve_friend_color(page, fname, CW, CH)
            report(friend_color=friend_color)

        # --- controls -------------------------------------------------------
        BAR_X0, BAR_X1, BAR_Y = 0.378, 0.622, 0.962   # power bar, fractions of canvas rect
        async def set_power(frac):
            frac = max(0.05, min(0.95, frac))
            x = CL + (BAR_X0 + frac*(BAR_X1-BAR_X0))*CW
            y = CT + BAR_Y*CH
            await page.mouse.click(x, y)
            await page.wait_for_timeout(40)
        async def attack(cx, cy):
            await page.mouse.move(cx, cy); await page.wait_for_timeout(30)
            await page.keyboard.press("Space"); await page.wait_for_timeout(45)
        async def boat(cx, cy):
            await page.mouse.move(cx, cy); await page.wait_for_timeout(30)
            await page.keyboard.press("b"); await page.wait_for_timeout(60)
        async def zoom_out(notches=1):
            await page.mouse.move(CL+CW/2, CT+CH/2)
            for _ in range(notches):
                await page.mouse.wheel(0, 500); await page.wait_for_timeout(160)
            await page.wait_for_timeout(250)
        def ok(t):  # keep clicks off the on-screen UI panels
            x, y = t['cx']-CL, t['cy']-CT
            if y < 0.075*CH or y > 0.86*CH: return False
            if x < 0.16*CW and y < 0.40*CH: return False
            if x > 0.88*CW and y < 0.22*CH: return False
            return True

        report(status="playing", phase="spawn")
        t_end = time.time()+secs; tick=0; zooms=0; stale=0; prev=0
        while time.time() < t_end:
            res = await page.evaluate(ANALYZE_JS, [24, friend_color, 70])
            n = res.get('n', 0)
            land  = [t for t in res.get('land',  []) if ok(t)]
            boats = [t for t in res.get('boats', []) if ok(t)]
            frac = n / TOTAL if TOTAL else 0

            big   = n > 0.34*TOTAL
            stale = stale+1 if (n <= prev+150 and n > 0.12*TOTAL) else 0
            prev  = n

            # zoom out when the view is full or growth has stalled
            if (big or stale >= 4) and zooms < 7:
                await zoom_out(1); zooms += 1; stale = 0; tick += 1
                report(status="playing", phase="zoom", tick=tick, own=n,
                       fronts=len(land), boats=len(boats), zoom=zooms,
                       power=0, remaining=int(t_end-time.time()))
                continue

            # ----- smart economy: choose power + how many fronts -----------
            if frac < 0.04:    power, K = 0.50, 5     # early: grab cheap neutral land fast
            elif frac < 0.15:  power, K = 0.35, 3     # mid: steady expansion, keep reserves
            else:              power, K = 0.22, 2     # large: economical, save & defend

            did = False; pw = 0.0; phase = "save"
            if land:                                  # expand over land frontiers
                phase = "expand"; pw = power
                land.sort(key=lambda t: t['r'], reverse=True)
                await set_power(power)
                for tg in land[:K]:
                    await attack(tg['cx'], tg['cy']); did = True
            if boats:                                 # cross the sea to new land
                phase = "naval" if not land else "expand+naval"; pw = 0.45
                boats.sort(key=lambda t: t['r'])
                await set_power(0.45)
                for tg in boats[:2]:
                    await boat(tg['cx'], tg['cy']); did = True
            if not did:
                # nothing to take -> SAVE: bank balance + interest, then look wider
                phase = "save"
                if zooms < 7:
                    await zoom_out(1); zooms += 1

            report(status="playing", phase=phase, tick=tick, own=n,
                   fronts=len(land), boats=len(boats), zoom=zooms,
                   power=round(pw, 2), remaining=int(t_end-time.time()))
            tick += 1
            await page.wait_for_timeout(350)
        report(status="finished")
        print("done")

def run(cfg):
    cfg.setdefault("name", "DevinBot")
    cfg.setdefault("mode", "custom_br")
    cfg["players"] = int(cfg.get("players", 24))
    cfg["secs"] = int(cfg.get("secs", 120))
    if cfg["mode"].startswith("mp_") and not cfg.get("mp_consent"):
        report(status="error", error="Online mode requires consent (tick the box).")
        print("Refusing online mode without consent."); return
    asyncio.run(play(cfg))

def main():
    cfg = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    run(cfg)

if __name__ == "__main__":
    main()
