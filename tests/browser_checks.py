# Browser checks (42) used to verify the website. Needs: pip install playwright; a server on :8801 (normal) and :8802 (invalid AI key); big.jpg test photo.
import asyncio, time
from playwright.async_api import async_playwright
U="http://localhost:8801/"; U2="http://localhost:8802/"
R=[]
def ok(c,m): R.append((c,m)); print(("PASS " if c else "FAIL ")+m)
async def tab(p,t): await p.click(f'nav.tabs button[data-v="{t}"]'); await p.wait_for_timeout(80)
async def txt(p,sel): return await p.evaluate(f"document.querySelector('{sel}').textContent")
async def main():
  async with async_playwright() as pw:
    b=await pw.chromium.launch()
    ctx=await b.new_context(viewport={"width":390,"height":844}); p=await ctx.new_page(); errs=[]; failed=[]
    p.on("pageerror",lambda e:errs.append(str(e))); p.on("requestfailed",lambda r: failed.append(r.url) if "fonts.g" not in r.url else None)
    t0=time.time(); await p.goto(U); await p.wait_for_load_state("networkidle"); load=time.time()-t0
    ok(load<3,f"page loads in {load:.2f}s")
    # ---- NOW
    ok("−48%" in await txt(p,"#defBig"),"Now: IMD −48% alert shown")
    ok(await p.locator("#rainbars .rb").count()==2,"Now: 2 district rain bars")
    ok(await p.locator("#v-now .status .pill").count()==3,"Now: 3 signals (rain, reservoirs, groundwater)")
    ok(await p.locator("#v-now .fact").count()==6,"Now: 6 sourced facts")
    ok("No community reports yet" in await txt(p,"#hotspots"),"Now: empty hotspots message")
    await p.click("#v-now details summary"); ok(await p.locator("#aiPill").is_visible() and (await txt(p,"#aiPill"))=="AI off","Now: roadmap opens, AI status 'AI off'")
    ok((await txt(p,"#srvBadge")).startswith("Live"),"Header: live server badge")
    # ---- REPORT: every type
    await tab(p,"report")
    for ty,area,note in [("dry","Whitefield","dry since Monday"),("low","Whitefield","yield halved"),("sewage","Bellandur","foam at inlet"),("quality","HSR Layout","yellow water")]:
        await p.select_option("#rType",ty); await p.select_option("#rArea",area); await p.fill("#rNote",note); await p.click("#repBtn"); await p.wait_for_timeout(500)
    ok(await p.locator("#reports .item").count()==4,"Report: all 4 non-tanker types saved")
    await p.select_option("#rType","tanker"); ok(await p.locator("#priceWrap").is_visible() and await p.locator("#litresWrap").is_visible(),"Report: tanker shows price + size fields")
    await p.fill("#rPrice","2400"); await p.select_option("#rLitres","12000"); await p.set_input_files("#rPhoto","big.jpg"); await p.click("#repBtn"); await p.wait_for_timeout(1200)
    ok(await p.locator("#reports img").count()==1,"Report: tanker report with photo saved, photo displayed")
    ok(await p.locator("#priceWrap").is_hidden(),"Report: form resets after submit")
    ok("₹200" in await txt(p,"#tankerStats"),"Report: tanker average ₹2,400/12,000 L = ₹200 per 1,000 L")
    ok("just now" in await txt(p,"#reports"),"Report: time shown ('just now')")
    await tab(p,"now"); hs=await txt(p,"#hotspots"); ok("Whitefield" in hs and hs.index("Whitefield")<hs.index("Bellandur"),"Now: hotspots ranked (Whitefield 2 before Bellandur 1)")
    # ---- SHARE
    await tab(p,"share")
    async def add(kind,area,name,q):
        await p.select_option("#lKind",kind); await p.select_option("#lArea",area); await p.fill("#lName",name); await p.fill("#lQty",q); await p.click('#listForm button[type=submit]'); await p.wait_for_timeout(400)
    await add("supply","Marathahalli","Lakeview STP","80"); await add("supply","Whitefield","Palm Grove STP","20")
    await add("demand","Whitefield","Metro site","60"); await add("demand","Hebbal","Road works","50")
    ok(await p.locator("#supplyList .item").count()==2 and await p.locator("#demandList .item").count()==2,"Share: 2 supply + 2 demand listed")
    await p.click("#runMatch"); await p.wait_for_timeout(400); m=await txt(p,"#matches")
    ok("Palm Grove STP → Metro site" in m,"Share: nearest supply used first (same-area Palm Grove)")
    ok("still unmet" in m,"Share: unmet demand reported")
    ok("₹" in await txt(p,"#matchSum"),"Share: daily saving calculated")
    await p.fill("#freshPrice","0"); await p.click("#runMatch"); await p.wait_for_timeout(300); ok("₹0" in await txt(p,"#matchSum"),"Share: fresh price 0 gives ₹0 saving, no error")
    await p.fill("#lName",""); await p.fill("#lQty","5"); await p.click('#listForm button[type=submit]'); await p.wait_for_timeout(200)
    ok(await p.locator("#supplyList .item").count()+await p.locator("#demandList .item").count()==4,"Share: blank name rejected")
    ctx2=await b.new_context(viewport={"width":390,"height":844}); q=await ctx2.new_page(); await q.goto(U); await q.wait_for_timeout(600); await tab(q,"share")
    ok(await q.locator("#v-share button[data-del]").count()==0,"Share: another user sees listings but no delete buttons")
    n0=await p.locator("#v-share button[data-del]").count(); await p.locator("#v-share button[data-del]").first.click(); await p.wait_for_timeout(500)
    ok(n0==4 and await p.locator("#v-share button[data-del]").count()==3,"Share: owner deletes own listing")
    # ---- QUALITY
    await tab(p,"quality")
    safe={"pH":7.2,"tds":300,"turb":0.5,"hard":150,"alk":120,"ca":40,"mg":20,"cl":100,"so4":50,"no3":10,"f":0.6,"fe":0.1,"mn":0.05,"nh3":0.1,"as":0.001,"pb":0.001,"tc":0,"ec":0}
    for k,v in safe.items(): await p.fill(f"#q-{k}",str(v))
    ok("All 18 values" in await txt(p,"#qVerdict"),"Quality: all 18 parameters safe")
    over={"pH":9,"tds":2500,"turb":6,"hard":700,"alk":700,"ca":250,"mg":120,"cl":1100,"so4":450,"no3":50,"f":2,"fe":0.5,"mn":0.4,"nh3":0.6,"as":0.06,"pb":0.02,"tc":2,"ec":1}
    allbad=True
    for k,v in over.items():
        await p.fill(f"#q-{k}",str(v)); st=await txt(p,f"#qs-{k}")
        allbad&= st=="Unsafe"; await p.fill(f"#q-{k}",str(safe[k]))
    ok(allbad,"Quality: every one of 18 parameters turns Unsafe above its max limit")
    await p.fill("#q-tds","800"); ok(await txt(p,"#qs-tds")=="High","Quality: TDS 800 = High (between limits)")
    for k in safe: await p.fill(f"#q-{k}","")
    ok((await txt(p,"#qVerdict"))=="","Quality: clearing all values clears the verdict")
    ok(await p.locator("#labAI").is_hidden(),"Quality: AI lab upload hidden when AI is off")
    # ---- RECHARGE
    await tab(p,"recharge")
    ok(await p.locator("#rwhOut .months .c").count()==12,"Recharge: 12-month harvest chart")
    await p.fill("#bill","0"); await p.dispatch_event("#bill","input"); ok("penalty" not in (await txt(p,"#rwhOut")).lower(),"Recharge: no penalty card when bill is 0")
    await p.fill("#bill","800"); await p.dispatch_event("#bill","input"); ok("₹8,400" in await txt(p,"#rwhOut"),"Recharge: penalty ₹800×(0.5×3+9) = ₹8,400")
    # ---- GENERAL
    good=True
    for t in ["now","report","share","quality","recharge"]:
        await tab(p,t); vis=await p.evaluate("[...document.querySelectorAll('section.view')].filter(s=>getComputedStyle(s).display!=='none').map(s=>s.id)"); good&=vis==["v-"+t]
    ok(good,"Tabs: each shows only its own screen")
    for w in (320,768,1366):
        c3=await b.new_context(viewport={"width":w,"height":900},color_scheme="dark"); r=await c3.new_page(); await r.goto(U); await r.wait_for_timeout(300)
        wide=False
        for t in ["now","report","share","quality","recharge"]:
            await tab(r,t); wide|= await r.evaluate("document.documentElement.scrollWidth")>w
        ok(not wide,f"Layout: no sideways scroll at {w}px (dark mode)"); await c3.close()
    # Real keyboard use from a fresh page load: Tab through everything reachable, check each focused element shows an outline
    ck=await b.new_context(viewport={"width":390,"height":844}); kp=await ck.new_page(); await kp.goto(U); await kp.wait_for_timeout(600)
    seen=[]; noring=[]
    for _ in range(80):
        await kp.keyboard.press("Tab")
        info=await kp.evaluate("(()=>{const e=document.activeElement;if(!e||e===document.body)return null;const s=getComputedStyle(e);return {tag:e.tagName,txt:(e.textContent||e.id||'').trim().slice(0,20),v:e.dataset.v||'',ring:s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>0}})()")
        if info is None: break
        seen.append(info)
        if not info["ring"]: noring.append(info["tag"]+" "+info["txt"])
    navs={x["v"] for x in seen if x["v"]}
    ok(len(seen)>10 and not noring and navs=={"now","report","share","quality","recharge"},f"Keyboard: Tab reached {len(seen)} items incl. all 5 tabs; every one shows a focus outline {noring or ''}")
    await ck.close()
    ok(not errs,"No JavaScript errors "+str(errs)); ok(not failed,"No failed requests to the server "+str(failed[:3]))
    await ctx.close(); await ctx2.close()
    # ---- server with broken AI key
    c4=await b.new_context(viewport={"width":390,"height":844}); a=await c4.new_page(); await a.goto(U2); await a.wait_for_timeout(700)
    ok((await txt(a,"#aiPill"))=="AI on" and "checked by AI" in await txt(a,"#rPhotoLabel"),"AI server: AI shown as on, photo label says 'checked by AI'")
    await tab(a,"report"); await a.set_input_files("#rPhoto","big.jpg"); await a.click("#repBtn"); await a.wait_for_timeout(9000)
    ok("Photo not checked" in await txt(a,"#reports"),"AI failure: report still saved, marked 'Photo not checked'")
    await tab(a,"quality"); ok(await a.locator("#labAI").is_visible(),"AI server: lab upload box visible")
    await a.set_input_files("#labPhoto","big.jpg"); await a.wait_for_timeout(9000); ln=await txt(a,"#labNote")
    ok("couldn't read" in ln,"AI failure: lab upload shows clear message: "+ln)
    await c4.close(); await b.close()
    f=[m for c,m in R if not c]; print(f"\n{len(R)-len(f)}/{len(R)} passed"); [print(" FAIL:",x) for x in f]
asyncio.run(main())
