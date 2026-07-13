"""Mock 内部 API 服务 — 开发阶段模拟业务后端."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI

app = FastAPI(title="Mock Internal API", version="0.1.0")

# ── 数据 ──

_gift_cards: dict[str, dict[str, Any]] = {
    "GIFT-12345678": {"card_no": "GIFT-12345678", "balance": 500.00, "currency": "USD"},
    "GIFT-87654321": {"card_no": "GIFT-87654321", "balance": 100.00, "currency": "USD"},
}

_positions = [
    {"symbol": "BTC", "amount": 0.52, "current_price": 43500.00},
    {"symbol": "ETH", "amount": 12.5, "current_price": 2310.00},
    {"symbol": "USDT", "amount": 50000.00, "current_price": 1.00},
]

_orders = [
    {"order_id": "ord-001", "symbol": "BTC", "side": "buy", "quantity": 0.1, "price": 41800.00, "status": "filled"},
    {"order_id": "ord-002", "symbol": "ETH", "side": "sell", "quantity": 5.0, "price": 2320.00, "status": "filled"},
    {"order_id": "ord-003", "symbol": "BTC", "side": "buy", "quantity": 0.05, "price": 43500.00, "status": "pending"},
]

_prices = {"BTC": 43500.00, "ETH": 2310.00, "USDT": 1.00}

_info = {
    "BTC": "Bitcoin，首个去中心化加密货币，2009 年诞生，总量 2100 万枚。",
    "ETH": "Ethereum，智能合约平台，支持 DeFi、NFT 等去中心化应用。",
    "USDT": "Tether，与美元 1:1 锚定的稳定币。",
}


# ── Gift Card ──

@app.get("/api/v1/gift-card/query")
async def query_gift_card(card_no: str = ""):
    card = _gift_cards.get(card_no)
    if card is None:
        return {"code": 1001, "message": "卡号不存在", "data": None}
    return {"code": 0, "message": "ok", "data": {"card": card}}


@app.post("/api/v1/gift-card/create")
async def create_gift_card(body: dict):
    card_no = f"GIFT-{uuid.uuid4().hex[:8].upper()}"
    amount = body.get("amount", 0)
    currency = body.get("currency", "USD")
    card = {"card_no": card_no, "balance": amount, "currency": currency}
    _gift_cards[card_no] = card
    return {"code": 0, "message": "ok", "data": {"card": card}}


@app.post("/api/v1/gift-card/top-up")
async def top_up(body: dict):
    card = _gift_cards.get(body.get("card_no", ""))
    if card is None:
        return {"code": 1001, "message": "卡号不存在", "data": None}
    card["balance"] += body.get("amount", 0)
    return {"code": 0, "message": "ok", "data": {"card": dict(card)}}


@app.post("/api/v1/gift-card/transfer")
async def transfer(body: dict):
    from_card = _gift_cards.get(body.get("from_card_no", ""))
    to_card = _gift_cards.get(body.get("to_card_no", ""))
    if from_card is None:
        return {"code": 1001, "message": "转出卡号不存在", "data": None}
    if to_card is None:
        return {"code": 1002, "message": "转入卡号不存在", "data": None}
    amount = body.get("amount", 0)
    if from_card["balance"] < amount:
        return {"code": 1003, "message": "余额不足", "data": None}
    from_card["balance"] -= amount
    to_card["balance"] += amount
    return {"code": 0, "message": "ok", "data": {"from": dict(from_card), "to": dict(to_card)}}


# ── Trading ──

@app.get("/api/v1/positions")
async def query_positions():
    return {"code": 0, "message": "ok", "data": {"positions": _positions}}


@app.get("/api/v1/orders")
async def query_orders(status: str = "all"):
    filtered = _orders if status == "all" else [o for o in _orders if o["status"] == status]
    return {"code": 0, "message": "ok", "data": {"orders": filtered}}


@app.post("/api/v1/orders")
async def place_order(body: dict):
    return {"code": 0, "message": "ok", "data": {"order": {**body, "order_id": f"ord-{uuid.uuid4().hex[:8]}", "status": "submitted"}}}


# ── Market ──

@app.get("/api/v1/market/price")
async def query_price(symbol: str = ""):
    return {"code": 0, "message": "ok", "data": {"symbol": symbol, "price": _prices.get(symbol, 0)}}


@app.get("/api/v1/market/info")
async def query_info(symbol: str = ""):
    return {"code": 0, "message": "ok", "data": {"symbol": symbol, "info": _info.get(symbol, "暂无该币种信息")}}


@app.get("/health")
async def health():
    return {"status": "ok"}
