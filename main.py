import os, secrets, urllib.parse, json, hmac, hashlib
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse, PlainTextResponse
from supabase import create_client
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

SUPABASE_URL=os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY=os.environ["SUPABASE_SECRET_KEY"]
OLX_CLIENT_ID=os.getenv("OLX_CLIENT_ID","")
OLX_CLIENT_SECRET=os.getenv("OLX_CLIENT_SECRET","")
OLX_CALLBACK_URL=os.getenv("OLX_CALLBACK_URL","https://gawor-radar-pro.onrender.com/auth/olx/callback")
OLX_BASE="https://www.olx.pl"
META_APP_SECRET=os.getenv("META_APP_SECRET","")
META_VERIFY_TOKEN=os.getenv("META_VERIFY_TOKEN","")
META_PAGE_ACCESS_TOKEN=os.getenv("META_PAGE_ACCESS_TOKEN","")
META_GRAPH_VERSION=os.getenv("META_GRAPH_VERSION","v25.0")
META_WEBHOOK_PATH=os.getenv("META_WEBHOOK_PATH","/webhooks/meta/leadgen")

sb=create_client(SUPABASE_URL,SUPABASE_SECRET_KEY)
app=FastAPI(title="Gawor Agro Radar PRO Web")
scheduler=AsyncIOScheduler()

def setting(k,v=None):
    q=sb.table("radar_settings")
    if v is None:
        r=q.select("value").eq("key",k).limit(1).execute()
        return r.data[0]["value"] if r.data else None
    return q.upsert({"key":k,"value":v,"updated_at":datetime.now(timezone.utc).isoformat()}).execute()

def oauth_url():
    state=secrets.token_urlsafe(32); setting("olx_oauth_state",state)
    return f"{OLX_BASE}/oauth/authorize/?"+urllib.parse.urlencode({"client_id":OLX_CLIENT_ID,"response_type":"code","state":state,"scope":os.getenv("OLX_SCOPE","read write v2"),"redirect_uri":OLX_CALLBACK_URL})

async def token_refresh():
    row=sb.table("olx_tokens").select("*").eq("id",1).limit(1).execute().data
    if not row:return None
    t=row[0]
    if datetime.fromisoformat(t["expires_at"].replace("Z","+00:00")).timestamp()>datetime.now(timezone.utc).timestamp():return t["access_token"]
    data={"grant_type":"refresh_token","client_id":OLX_CLIENT_ID,"client_secret":OLX_CLIENT_SECRET,"refresh_token":t["refresh_token"]}
    async with httpx.AsyncClient(timeout=30) as h:
        r=await h.post(f"{OLX_BASE}/api/open/oauth/token",json=data)
        if r.status_code>=400:return None
        tok=r.json()
    exp=datetime.now(timezone.utc).timestamp()+int(tok.get("expires_in",86400))-60
    sb.table("olx_tokens").upsert({"id":1,"access_token":tok["access_token"],"refresh_token":tok["refresh_token"],"expires_at":datetime.fromtimestamp(exp,timezone.utc).isoformat(),"scope":tok.get("scope",""),"updated_at":datetime.now(timezone.utc).isoformat()}).execute()
    return tok["access_token"]

async def olx_get(path,params=None):
    token=await token_refresh()
    if not token:raise HTTPException(401,"OLX niepołączony")
    headers={"Authorization":f"Bearer {token}","Version":"2.0","Accept-Language":"pl"}
    async with httpx.AsyncClient(timeout=30) as h:
        r=await h.get(f"{OLX_BASE}/api/partner{path}",headers=headers,params=params)
        r.raise_for_status();return r.json()

async def sync_olx():
    if not OLX_CLIENT_ID or not OLX_CLIENT_SECRET:return {"ok":False,"reason":"Brak OLX_CLIENT_ID/SECRET"}
    payload=await olx_get("/adverts",{"offset":0,"limit":100})
    items=payload.get("data",[]) if isinstance(payload,dict) else payload
    rows=[]
    for a in items:
        loc=a.get("location") or {}; city=loc.get("city") or {}; price=a.get("price") or {}
        rows.append({"olx_id":str(a.get("id")),"status":a.get("status"),"url":a.get("url"),"title":a.get("title"),"description":a.get("description"),"created_at":a.get("created_at"),"activated_at":a.get("activated_at"),"valid_to":a.get("valid_to"),"category_id":a.get("category_id"),"city_id":city.get("id"),"city_name":city.get("name"),"lat":loc.get("latitude"),"lon":loc.get("longitude"),"price":price.get("value"),"currency":price.get("currency"),"raw_json":a,"last_synced_at":datetime.now(timezone.utc).isoformat()})
    if rows:sb.table("olx_adverts").upsert(rows,on_conflict="olx_id").execute()
    return {"ok":True,"count":len(rows)}

# ---------- Meta / Facebook Lead Ads ----------
def meta_signature_ok(raw:bytes, signature:str|None)->bool:
    if not META_APP_SECRET:return False
    if not signature or not signature.startswith("sha256="):return False
    expected="sha256="+hmac.new(META_APP_SECRET.encode(),raw,hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,signature)

def normalize_field_data(field_data):
    out={}
    for item in field_data or []:
        name=item.get("name","")
        vals=item.get("values") or []
        out[name]=(vals[0] if vals else "").strip()
    return out

def parse_number(value):
    if value is None:return None
    try:return float(str(value).replace(" ","").replace(",","."))
    except:return None

def first_value(d,names):
    for n in names:
        if d.get(n):return d[n]
    return ""

async def fetch_meta_lead(leadgen_id):
    if not META_PAGE_ACCESS_TOKEN:raise HTTPException(500,"Brak META_PAGE_ACCESS_TOKEN")
    url=f"https://graph.facebook.com/{META_GRAPH_VERSION}/{leadgen_id}"
    params={"fields":"id,created_time,field_data,form_id,ad_id,adset_id,campaign_id,platform","access_token":META_PAGE_ACCESS_TOKEN}
    async with httpx.AsyncClient(timeout=30) as h:
        r=await h.get(url,params=params)
        r.raise_for_status();return r.json()

async def process_meta_lead(leadgen_id,page_id=None):
    existing=sb.table("meta_leads").select("id").eq("leadgen_id",leadgen_id).limit(1).execute().data
    if existing:return {"ok":True,"duplicate":True}
    data=await fetch_meta_lead(leadgen_id)
    fields=normalize_field_data(data.get("field_data"))
    full_name=first_value(fields,["full_name","name","imie_nazwisko"])
    phone=first_value(fields,["phone_number","phone","telefon","mobile_phone"])
    email=first_value(fields,["email","e-mail"])
    commodity=first_value(fields,["commodity","towar","zboze","co_masz_na_sprzedaz"])
    qty_raw=first_value(fields,["quantity","qty","ilosc","ilosc_ton","tony"])
    place=first_value(fields,["city","place","miejscowosc","lokalizacja"])
    qty=parse_number(qty_raw) or 0
    row={"leadgen_id":leadgen_id,"page_id":str(page_id or ""),"form_id":str(data.get("form_id") or ""),"ad_id":str(data.get("ad_id") or ""),"adset_id":str(data.get("adset_id") or ""),"campaign_id":str(data.get("campaign_id") or ""),"created_time":data.get("created_time"),"full_name":full_name,"phone":phone,"email":email,"commodity":commodity or "Nieokreślony","quantity_t":qty,"place":place,"raw_json":data}
    sb.table("meta_leads").insert(row).execute()
    # Also create a standard Radar lead so it appears in the normal dashboard.
    lead={"fingerprint":hashlib.sha256(("META|"+leadgen_id).encode()).hexdigest(),"source":"Facebook Lead Ads","url":"","title":full_name or "Facebook Lead","commodity":commodity or "Nieokreślony","qty":qty,"place":place,"distance_km":0,"phone":phone,"buy":0,"transport":0,"sell":0,"moisture":None,"score":55 if qty>=50 else 40,"priority":"DOBRY" if qty>=50 else "SLABY","status":"Nowy","note":"Meta Lead Ads"}
    try:sb.table("leads").insert(lead).execute()
    except Exception:pass
    return {"ok":True,"duplicate":False,"leadgen_id":leadgen_id}

@app.get(META_WEBHOOK_PATH)
async def meta_verify(request:Request):
    p=request.query_params
    if p.get("hub.mode")=="subscribe" and p.get("hub.verify_token")==META_VERIFY_TOKEN:
        return PlainTextResponse(p.get("hub.challenge","") )
    return PlainTextResponse("Forbidden",status_code=403)

@app.post(META_WEBHOOK_PATH)
async def meta_webhook(request:Request):
    raw=await request.body()
    signature=request.headers.get("x-hub-signature-256")
    if not meta_signature_ok(raw,signature):return PlainTextResponse("Invalid signature",status_code=403)
    payload=json.loads(raw.decode("utf-8"))
    processed=0
    for entry in payload.get("entry",[]):
        page_id=entry.get("id")
        for change in entry.get("changes",[]):
            if change.get("field")!="leadgen":continue
            value=change.get("value") or {}
            leadgen_id=str(value.get("leadgen_id") or "")
            if leadgen_id:
                try:
                    await process_meta_lead(leadgen_id,page_id);processed+=1
                except Exception as e:print("Meta lead error:",e)
    return {"ok":True,"processed":processed}

@app.get("/meta/status")
def meta_status():
    count=sb.table("meta_leads").select("id",count="exact").execute().count or 0
    return {"configured":bool(META_APP_SECRET and META_VERIFY_TOKEN and META_PAGE_ACCESS_TOKEN),"leads":count,"webhook":META_WEBHOOK_PATH}

@app.on_event("startup")
async def start():
    scheduler.add_job(sync_job,"interval",minutes=15,id="olx-sync",replace_existing=True);scheduler.start()
@app.on_event("shutdown")
async def stop():scheduler.shutdown()
async def sync_job():
    try:await sync_olx()
    except Exception as e:print("OLX sync:",e)

@app.get("/health")
def health():return {"ok":True,"service":"gawor-radar-pro-web"}
@app.get("/auth/olx/start")
def olx_start():
    if not OLX_CLIENT_ID or not OLX_CLIENT_SECRET:return HTMLResponse("Brak OLX credentials na serwerze.",status_code=503)
    return RedirectResponse(oauth_url())
@app.get("/auth/olx/callback")
async def olx_callback(request:Request):
    code=request.query_params.get("code");state=request.query_params.get("state");saved=setting("olx_oauth_state")
    if not code or state!=saved:return HTMLResponse("Nieprawidłowy OAuth state/code.",status_code=400)
    data={"grant_type":"authorization_code","client_id":OLX_CLIENT_ID,"client_secret":OLX_CLIENT_SECRET,"code":code,"scope":os.getenv("OLX_SCOPE","read write v2"),"redirect_uri":OLX_CALLBACK_URL}
    async with httpx.AsyncClient(timeout=30) as h:
        r=await h.post(f"{OLX_BASE}/api/open/oauth/token",json=data);r.raise_for_status();tok=r.json()
    exp=datetime.now(timezone.utc).timestamp()+int(tok.get("expires_in",86400))-60
    sb.table("olx_tokens").upsert({"id":1,"access_token":tok["access_token"],"refresh_token":tok["refresh_token"],"expires_at":datetime.fromtimestamp(exp,timezone.utc).isoformat(),"scope":tok.get("scope",""),"updated_at":datetime.now(timezone.utc).isoformat()}).execute()
    result=await sync_olx();return HTMLResponse(f"<h2>OLX połączony</h2><p>Zsynchronizowano {result.get('count',0)} własnych ogłoszeń.</p><p><a href='/'>Wróć do Radaru</a></p>")
@app.get("/olx/status")
def olx_status():
    t=sb.table("olx_tokens").select("updated_at,scope").eq("id",1).limit(1).execute().data
    count=sb.table("olx_adverts").select("id",count="exact").execute().count or 0
    return {"connected":bool(t),"adverts":count,"last_token_update":t[0]["updated_at"] if t else None}
@app.post("/olx/sync")
async def olx_sync():return await sync_olx()
@app.get("/olx/adverts")
def olx_adverts(limit:int=200):return sb.table("olx_adverts").select("*").order("last_synced_at",desc=True).limit(limit).execute().data
@app.get("/")
def root():return FileResponse("app/index.html")
