"""Local deterministic, read-only analyst for Vantage MT5 DEMO. No paid AI API required."""
import hmac
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

router = APIRouter()
ASSISTANT_ACCESS_TOKEN = os.getenv("DIO_ASSISTANT_ACCESS_TOKEN", "").strip()
BRIDGE_TOKEN = os.getenv("DIO_BRIDGE_TOKEN", "").strip()
SNAPSHOT_URL = os.getenv(
    "DIO_ASSISTANT_SNAPSHOT_URL",
    "https://diomaster-gold-ai-metaapi-demo.onrender.com/assistant/snapshot"
).strip()

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=6000)

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
<meta name="theme-color" content="#101827"><title>DioMasteR GOLD AI</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0b1220;color:#eef2ff;font:16px system-ui,sans-serif}
main{max-width:760px;margin:auto;padding:18px;min-height:100dvh;display:flex;flex-direction:column;gap:14px}
header{padding:12px 0}h1{font-size:22px;margin:0 0 5px}.sub{color:#a8b3c7;font-size:13px}
.panel{background:#121d30;border:1px solid #28364d;border-radius:14px;padding:13px}
input,textarea,button{font:inherit;border-radius:10px;border:1px solid #34445e;padding:12px;background:#0c1729;color:#fff;width:100%}
textarea{min-height:90px;resize:vertical}button{background:#d8a943;color:#101827;font-weight:700;border:0;cursor:pointer}
#chat{display:flex;flex-direction:column;gap:10px;flex:1}.msg{white-space:pre-wrap;overflow-wrap:anywhere;padding:13px;border-radius:12px;line-height:1.5}
.user{background:#1b3655;align-self:flex-end;max-width:92%}.bot{background:#172337;border:1px solid #2a3a52}
form{display:grid;gap:9px}.warning{font-size:12px;color:#f3c96b;line-height:1.5}
</style></head><body><main><header><h1>DioMasteR GOLD AI</h1><div class="sub">MT5 Vantage DEMO · Τοπική ανάλυση · Χωρίς OpenAI API · Χωρίς εντολές</div></header>
<section class="panel"><label for="token">Προσωπικό κλειδί πρόσβασης</label><input id="token" type="password" autocomplete="off" placeholder="DIO_ASSISTANT_ACCESS_TOKEN">
<div class="warning">Το κλειδί δεν αποθηκεύεται. Μην το κοινοποιείς.</div></section>
<section id="chat" aria-live="polite"><div class="msg bot">Σύνδεσε το κλειδί και ζήτησε έλεγχο λογαριασμού, θέσεων, ιστορικού ή απόδοσης. Η ανάλυση γίνεται τοπικά, χωρίς χρέωση AI API.</div></section>
<form id="form"><textarea id="message" maxlength="6000" placeholder="π.χ. Έλεγξε τις τελευταίες συναλλαγές και εξήγησε την απόδοση..." required></textarea><button id="send">Αποστολή για ανάλυση</button></form>
<div class="sub">Μόνο ανάγνωση δεδομένων Vantage MT5 DEMO. Δεν ανοίγει, κλείνει ή αλλάζει συναλλαγές.</div></main>
<script>
const chat=document.getElementById('chat'),token=document.getElementById('token'),form=document.getElementById('form'),msg=document.getElementById('message'),send=document.getElementById('send');
function bubble(text,cls){const d=document.createElement('div');d.className='msg '+cls;d.textContent=text;chat.appendChild(d);d.scrollIntoView({behavior:'smooth',block:'end'});return d;}
form.addEventListener('submit',async e=>{e.preventDefault();const message=msg.value.trim(),key=token.value.trim();if(!key||!message)return;
bubble(message,'user');msg.value='';send.disabled=true;send.textContent='Ανάκτηση δεδομένων...';const wait=bubble('Συνδέομαι με τα δεδομένα του MT5 DEMO και υπολογίζω...','bot');
try{const r=await fetch('/assistant/chat',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+key},body:JSON.stringify({message})});const data=await r.json();if(!r.ok)throw new Error(data.detail||'Η σύνδεση απέτυχε');wait.textContent=data.answer||'Δεν υπάρχουν διαθέσιμα στοιχεία.';}
catch(err){wait.textContent='Σφάλμα: '+err.message;}
finally{send.disabled=false;send.textContent='Αποστολή για ανάλυση';}});
</script></body></html>""")

def num(row, *keys):
    for key in keys:
        try:
            value = row.get(key)
            if value is not None and value != "":
                return float(value)
        except (TypeError, ValueError):
            pass
    return None

def local_report(snapshot: dict, question: str) -> str:
    account = snapshot.get("account") or {}
    connection = snapshot.get("connection") or {}
    positions = snapshot.get("open_positions") or []
    history = snapshot.get("closed_history") or []
    balance = num(account, "balance")
    equity = num(account, "equity")
    currency = account.get("currency") or ""
    lines = [
        "DioMasteR GOLD AI — ΑΝΑΦΟΡΑ MT5 DEMO",
        "Λειτουργία: μόνο ανάγνωση. Δεν εκτελέστηκε καμία εντολή.",
        f"Σύνδεση broker: {'ΕΝΕΡΓΗ' if connection.get('connected') else 'ΜΗ ΕΠΙΒΕΒΑΙΩΜΕΝΗ'}",
        f"Τιμή stream: {connection.get('price_stream_state') or 'μη διαθέσιμη'}",
        f"Σύμβολο: {connection.get('symbol') or 'μη διαθέσιμο'}",
    ]
    if balance is not None: lines.append(f"Υπόλοιπο: {balance:.2f} {currency}")
    if equity is not None:
        lines.append(f"Equity: {equity:.2f} {currency}")
        if balance is not None: lines.append(f"Διαφορά equity - balance: {equity-balance:+.2f} {currency}")
    lines += ["", f"ΑΝΟΙΧΤΕΣ ΘΕΣΕΙΣ ({len(positions)})"]
    if positions:
        floating = 0.0; have_profit = False
        for p in positions[:30]:
            profit = num(p, "profit", "netProfit", "unrealizedProfit")
            if profit is not None: floating += profit; have_profit = True
            lines.append(
                f"#{p.get('ticket','?')} {p.get('symbol','?')} {p.get('side','?')} "
                f"όγκος {p.get('volume','?')} | είσοδος {p.get('entry_price','?')} | "
                f"τρέχουσα {p.get('current_price','?')} | P/L {profit if profit is not None else 'μη διαθέσιμο'}"
            )
        if have_profit: lines.append(f"Σύνολο εμφανιζόμενου floating P/L: {floating:+.2f} {currency}")
    else: lines.append("Δεν υπάρχουν ανοιχτές θέσεις στο snapshot.")
    lines += ["", f"ΙΣΤΟΡΙΚΟ BROKER ({len(history)} εγγραφές που επιστράφηκαν)"]
    profits = [num(x, "profit", "netProfit", "realizedProfit") for x in history if isinstance(x, dict)]
    known = [x for x in profits if x is not None]
    if known:
        wins = sum(x > 0 for x in known); losses = sum(x < 0 for x in known)
        lines.append(f"Εγγραφές με αναγνώσιμο P/L: {len(known)} · θετικές: {wins} · αρνητικές: {losses} · μηδενικές: {len(known)-wins-losses}")
        lines.append(f"Άθροισμα διαθέσιμου P/L εγγραφών: {sum(known):+.2f} {currency}")
    else:
        lines.append("Δεν βρέθηκε ενιαίο αριθμητικό πεδίο P/L στις εγγραφές· δεν υπολογίζεται κέρδος/ζημία.")
    lines.append("Προσοχή: οι εγγραφές ιστορικού μπορεί να είναι deals ή μερικά κλεισίματα, όχι μοναδικές συναλλαγές. Το άθροισμα δεν θεωρείται πλήρες καθαρό αποτέλεσμα χωρίς επιβεβαίωση προμηθειών/swap και δομής ιστορικού.")
    lines += ["", "ΟΡΙΑ ΑΝΑΛΥΣΗΣ", "Αυτή είναι αριθμητική αναφορά από τα δεδομένα που επέστρεψε ο broker, όχι πρόβλεψη ούτε βαθμονομημένη πιθανότητα επιτυχίας. Δεν αλλάζουμε στρατηγική από μικρό δείγμα. Δεν διατίθεται εδώ πλήρες αρχείο σημάτων BUY/SELL/HOLD ή out-of-sample backtest."]
    lines += ["", "Ερώτημα: " + question[:500]]
    return "\n".join(lines)

@router.post("/assistant/chat")
async def assistant_chat(req: ChatRequest, authorization: Optional[str] = Header(default=None)):
    assistant_auth(authorization)
    if not BRIDGE_TOKEN:
        raise HTTPException(503, "DIO_BRIDGE_TOKEN is not configured in Render")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
            response = await client.get(SNAPSHOT_URL, headers={"Authorization": "Bearer " + BRIDGE_TOKEN}, params={"limit": 50})
        if response.status_code >= 400:
            raise HTTPException(502, f"Η ανάκτηση MT5 DEMO απέτυχε (HTTP {response.status_code}).")
        snapshot = response.json()
        if snapshot.get("account_mode") != "DEMO" or snapshot.get("read_only") is not True:
            raise HTTPException(403, "Η πηγή δεν επιβεβαιώθηκε ως read-only DEMO.")
        return {"ok": True, "answer": local_report(snapshot, req.message),
                "account_mode": "DEMO", "read_only": True, "analysis_engine": "local_rules"}
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(504, "Η ανάκτηση δεδομένων MT5 ξεπέρασε το χρονικό όριο.")
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Δεν ήταν δυνατή η ανάκτηση έγκυρων δεδομένων από το MT5 DEMO.")
