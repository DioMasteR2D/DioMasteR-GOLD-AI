"""Mobile web chat and OpenAI Responses API proxy for the read-only GOLD AI assistant."""
import hmac
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

router = APIRouter()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-astra").strip()
ASSISTANT_ACCESS_TOKEN = os.getenv("DIO_ASSISTANT_ACCESS_TOKEN", "").strip()
BRIDGE_TOKEN = os.getenv("DIO_BRIDGE_TOKEN", "").strip()
MCP_URL = os.getenv("DIO_ASSISTANT_MCP_URL", "https://diomaster-gold-ai-metaapi-demo.onrender.com/mcp").strip()
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

SYSTEM_INSTRUCTIONS = """You are the DioMasteR GOLD AI DEMO trading analyst.
You may ONLY read and analyze Vantage MT5 DEMO data using the provided read-only MCP tools.
Never claim this is a LIVE-money account. Never suggest that you executed, modified, opened, or closed a trade.
Never provide personalized guarantees or promise profit. Distinguish broker facts from estimates.
The current strategy must not be changed based on a small sample. Explain sample size, deal-vs-trade limitations,
missing BUY/SELL/HOLD signal audit, and the absence of out-of-sample backtesting where relevant.
Do not expose credentials, tokens, account identifiers, or sensitive broker details.
No tool is available to place or close orders. All recommendations are analysis-only.
Answer in the language used by the user, preferably Greek when the user writes Greek."""

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=6000)
    previous_response_id: Optional[str] = Field(default=None, max_length=200)

def assistant_auth(value: Optional[str]):
    if not ASSISTANT_ACCESS_TOKEN:
        raise HTTPException(503, "DIO_ASSISTANT_ACCESS_TOKEN is not configured")
    got = (value or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got.encode(), ASSISTANT_ACCESS_TOKEN.encode()):
        raise HTTPException(401, "Unauthorized")

@router.get("/assistant", response_class=HTMLResponse)
async def assistant_page():
    return HTMLResponse("""<!doctype html>
<html lang="el"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#101827"><title>DioMasteR GOLD AI Assistant</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0b1220;color:#eef2ff;font:16px system-ui,sans-serif}
main{max-width:760px;margin:auto;padding:18px;min-height:100dvh;display:flex;flex-direction:column;gap:14px}
header{padding:12px 0}h1{font-size:22px;margin:0 0 5px}.sub{color:#a8b3c7;font-size:13px}
.panel{background:#121d30;border:1px solid #28364d;border-radius:14px;padding:13px}
input,textarea,button{font:inherit;border-radius:10px;border:1px solid #34445e;padding:12px;background:#0c1729;color:#fff;width:100%}
textarea{min-height:90px;resize:vertical}button{background:#d8a943;color:#101827;font-weight:700;border:0;cursor:pointer}
#chat{display:flex;flex-direction:column;gap:10px;flex:1}.msg{white-space:pre-wrap;overflow-wrap:anywhere;padding:13px;border-radius:12px;line-height:1.5}
.user{background:#1b3655;align-self:flex-end;max-width:92%}.bot{background:#172337;border:1px solid #2a3a52;align-self:stretch}
form{display:grid;gap:9px}.warning{font-size:12px;color:#f3c96b;line-height:1.5}
</style></head><body><main><header><h1>DioMasteR GOLD AI</h1><div class="sub">MT5 Vantage DEMO · Ανάλυση μόνο · Χωρίς εντολές συναλλαγών</div></header>
<section class="panel"><label for="token">Προσωπικό κλειδί πρόσβασης</label><input id="token" type="password" autocomplete="off" placeholder="DIO_ASSISTANT_ACCESS_TOKEN">
<div class="warning">Το κλειδί δεν αποθηκεύεται. Μην το κοινοποιείς.</div></section>
<section id="chat" aria-live="polite"><div class="msg bot">Σύνδεσε το κλειδί πρόσβασης και ρώτησέ με για την κατάσταση, τις θέσεις ή την απόδοση του DEMO bot.</div></section>
<form id="form"><textarea id="message" maxlength="6000" placeholder="π.χ. Έλεγξε τις τελευταίες συναλλαγές και εξήγησε την απόδοση..." required></textarea><button id="send">Αποστολή για ανάλυση</button></form>
<div class="sub">Η ανάλυση χρησιμοποιεί τα διαθέσιμα δεδομένα του broker. Δεν εκτελεί ούτε αλλάζει συναλλαγές.</div></main>
<script>
const chat=document.getElementById('chat'), token=document.getElementById('token'), form=document.getElementById('form'), msg=document.getElementById('message'), send=document.getElementById('send');
let previous=null;
function bubble(text,cls){const d=document.createElement('div');d.className='msg '+cls;d.textContent=text;chat.appendChild(d);d.scrollIntoView({behavior:'smooth',block:'end'});return d;}
form.addEventListener('submit',async e=>{e.preventDefault();const message=msg.value.trim(),key=token.value.trim();if(!key||!message)return;
bubble(message,'user');msg.value='';send.disabled=true;send.textContent='Αναμονή...';const wait=bubble('Γίνεται ανάκτηση των DEMO δεδομένων και ανάλυση...','bot');
try{const r=await fetch('/assistant/chat',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+key},body:JSON.stringify({message,previous_response_id:previous})});const data=await r.json();if(!r.ok)throw new Error(data.detail||'Η σύνδεση απέτυχε');wait.textContent=data.answer||'Δεν επιστράφηκε απάντηση.';previous=data.previous_response_id||previous;}
catch(err){wait.textContent='Σφάλμα: '+err.message;}
finally{send.disabled=false;send.textContent='Αποστολή για ανάλυση';}});
</script></body></html>""")

@router.post("/assistant/chat")
async def assistant_chat(req: ChatRequest, authorization: Optional[str] = Header(default=None)):
    assistant_auth(authorization)
    if not OPENAI_API_KEY:
        raise HTTPException(503, "OPENAI_API_KEY is not configured in Render")
    if not BRIDGE_TOKEN:
        raise HTTPException(503, "DIO_BRIDGE_TOKEN is not configured in Render")
    payload = {
        "model": OPENAI_MODEL,
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": req.message,
        "tools": [{
            "type": "mcp",
            "server_label": "diomaster_gold_ai_demo",
            "server_description": "Read-only Vantage MT5 DEMO account, positions, history and basic performance analysis.",
            "server_url": MCP_URL,
            "headers": {"Authorization": "Bearer " + BRIDGE_TOKEN},
            "allowed_tools": ["get_bot_status", "get_open_positions", "get_trade_history", "get_performance", "analyze_strategy"],
            "require_approval": "never"
        }],
        "tool_choice": "auto"
    }
    if req.previous_response_id:
        payload["previous_response_id"] = req.previous_response_id
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
            response = await client.post(
                OPENAI_RESPONSES_URL,
                headers={"Authorization": "Bearer " + OPENAI_API_KEY, "Content-Type": "application/json"},
                json=payload
            )
        if response.status_code >= 400:
            detail = "OpenAI API request failed"
            try:
                error = response.json().get("error", {})
                detail = str(error.get("message") or detail)[:500]
            except Exception:
                pass
            raise HTTPException(502, detail)
        data = response.json()
        answer = data.get("output_text")
        if not answer:
            chunks = []
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for part in item.get("content", []):
                        if part.get("type") == "output_text":
                            chunks.append(part.get("text", ""))
            answer = "\n".join(chunks).strip()
        return {"ok": True, "answer": answer or "Δεν επιστράφηκε κείμενο από το μοντέλο.",
                "previous_response_id": data.get("id"), "model": OPENAI_MODEL,
                "account_mode": "DEMO", "read_only": True}
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(504, "Η ανάλυση ξεπέρασε το χρονικό όριο. Δοκίμασε ξανά.")
    except httpx.HTTPError:
        raise HTTPException(502, "Δεν ήταν δυνατή η σύνδεση με το OpenAI API.")
