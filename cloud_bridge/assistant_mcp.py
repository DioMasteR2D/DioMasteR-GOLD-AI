"""Read-only MCP JSON-RPC endpoint for DioMasteR MT5 DEMO assistant.

Requires the existing DIO_BRIDGE_TOKEN. No trade/order tools are exposed.
Mount with app.include_router(router) in cloud_bridge/main.py.
"""
import json
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter()
PROTOCOL_VERSION = "2025-03-26"

def _tool(name, description):
    return {"name": name, "description": description, "inputSchema": {
        "type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
        "additionalProperties": False}}

TOOLS = [
    _tool("get_bot_status", "Read MT5 DEMO connection and account state."),
    _tool("get_open_positions", "Read current MT5 DEMO positions; cannot trade."),
    _tool("get_trade_history", "Read recent closed MT5 DEMO trades."),
    _tool("get_performance", "Summarize recent realized P/L where provided by broker."),
    _tool("analyze_strategy", "Read-only diagnostic summary of recent trades; not a backtest.")
]

@router.post("/mcp")
async def mcp(request: Request, authorization: Optional[str] = Header(default=None)):
    # Import at request time to avoid a circular import with the bridge.
    from main import auth, assistant_snapshot
    auth(authorization)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
        raise HTTPException(400, "Expected JSON-RPC 2.0 object")
    method = data.get("method")
    ident = data.get("id")
    if method == "notifications/initialized":
        return JSONResponse(status_code=202, content={})
    if ident is None:
        raise HTTPException(400, "Request id is required")
    def ok(result):
        return {"jsonrpc": "2.0", "id": ident, "result": result}
    def err(code, message):
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}
    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL_VERSION,
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "diomaster-gold-ai-demo-readonly", "version": "0.1.0"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method != "tools/call":
        return err(-32601, "Method not found")
    params = data.get("params") or {}
    if not isinstance(params, dict):
        return err(-32602, "Invalid params")
    name = params.get("name")
    if name not in {tool["name"] for tool in TOOLS}:
        return err(-32602, "Unknown read-only tool")
    args = params.get("arguments") or {}
    if not isinstance(args, dict) or any(k != "limit" for k in args):
        return err(-32602, "Invalid tool arguments")
    limit = args.get("limit", 50)
    if type(limit) is not int or not 1 <= limit <= 200:
        return err(-32602, "limit must be an integer from 1 to 200")
    try:
        snapshot = await assistant_snapshot(limit=limit, authorization=authorization)
    except HTTPException as exc:
        return ok({"content": [{"type": "text", "text": str(exc.detail)}], "isError": True})
    if name == "get_bot_status":
        result = {k: snapshot[k] for k in ("account_mode", "generated_at", "connection", "account", "open_positions_count")}
    elif name == "get_open_positions":
        result = {"account_mode": "DEMO", "positions": snapshot["open_positions"]}
    elif name == "get_trade_history":
        result = {"account_mode": "DEMO", "history": snapshot["closed_history"]}
    else:
        history = snapshot["closed_history"]
        profits = []
        for item in history:
            if isinstance(item, dict):
                try:
                    profits.append(float(item["profit"]))
                except (KeyError, TypeError, ValueError):
                    continue
        result = {"account_mode": "DEMO", "history_count": len(history),
                  "trades_with_profit_data": len(profits),
                  "realized_profit_sample": round(sum(profits), 2) if profits else None,
                  "wins": sum(p > 0 for p in profits),
                  "losses": sum(p < 0 for p in profits),
                  "win_rate": round(sum(p > 0 for p in profits) / len(profits), 4) if profits else None,
                  "limitations": "Recent broker history only; no HOLD signals, signal audit, or out-of-sample validation. History may contain deals rather than distinct trades."}
        if name == "analyze_strategy":
            result["recommendation"] = "Collect every BUY/SELL/HOLD decision before evaluating or changing strategy."
    return ok({"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
