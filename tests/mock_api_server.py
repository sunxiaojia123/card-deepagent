"""Mock 内部 API 服务器 — 用于测试."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI()

# ── 持有数据 ──

_gift_cards = {
    "GIFT-12345678": {"card_no": "GIFT-12345678", "balance": 500.00, "currency": "USD"},
    "GIFT-87654321": {"card_no": "GIFT-87654321", "balance": 100.00, "currency": "USD"},
}

_positions = [
    {"symbol": "BTC", "amount": 0.52, "current_price": 43500.00},
    {"symbol": "ETH", "amount": 12.5, "current_price": 2310.00},
]

_orders = [
    {"order_id": "ord-001", "symbol": "BTC", "side": "buy", "quantity": 0.1, "status": "filled"},
    {"order_id": "ord-002", "symbol": "ETH", "side": "sell", "quantity": 5.0, "status": "pending"},
]


# ── Gift Card APIs ──

@app.post("/api/v1/gift-card/query")
async def query_gift_card(body: dict):
    card_no = body.get("card_no", "")
    card = _gift_cards.get(card_no)
    if card is None:
        return {"code": 1001, "message": "卡号不存在", "data": None}
    return {"code": 0, "message": "ok", "data": {"card": card}}


@app.post("/api/v1/gift-card/create")
async def create_gift_card(body: dict):
    import uuid
    card_no = f"GIFT-{uuid.uuid4().hex[:8].upper()}"
    card = {"card_no": card_no, "balance": body.get("amount", 0), "currency": body.get("currency", "USD")}
    _gift_cards[card_no] = card
    return {"code": 0, "message": "ok", "data": {"card": card}}


@app.post("/api/v1/gift-card/top-up")
async def top_up_gift_card(body: dict):
    card_no = body.get("card_no", "")
    card = _gift_cards.get(card_no)
    if card is None:
        return {"code": 1001, "message": "卡号不存在", "data": None}
    card["balance"] += body.get("amount", 0)
    return {"code": 0, "message": "ok", "data": {"card": {"card_no": card_no, "balance": card["balance"], "currency": card["currency"]}}}


# ── Trading APIs ──

@app.get("/api/v1/positions")
async def query_positions():
    return {"code": 0, "message": "ok", "data": {"positions": _positions}}


@app.get("/api/v1/orders")
async def query_orders(status: str = "all"):
    filtered = _orders if status == "all" else [o for o in _orders if o["status"] == status]
    return {"code": 0, "message": "ok", "data": {"orders": filtered}}


@app.post("/api/v1/orders")
async def place_order(body: dict):
    return {"code": 0, "message": "ok", "data": {"order": {**body, "order_id": "ord-new", "status": "submitted"}}}


# ── Market APIs ──

@app.get("/api/v1/market/price")
async def query_price(symbol: str):
    prices = {"BTC": 43500.00, "ETH": 2310.00}
    return {"code": 0, "message": "ok", "data": {"symbol": symbol, "price": prices.get(symbol, 0)}}


@app.get("/api/v1/market/info")
async def query_info(symbol: str):
    info = {"BTC": "Bitcoin, 首个加密货币", "ETH": "Ethereum, 智能合约平台"}
    return {"code": 0, "message": "ok", "data": {"symbol": symbol, "info": info.get(symbol, "未知币种")}}
