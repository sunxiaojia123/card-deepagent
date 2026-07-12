---
name: order-guide
description: 现货下单、查持仓、查订单。用户提到买卖、持仓、订单时使用。
allowed-tools: query_positions, query_orders, place_spot_order
---

# 下单引导

## 流程

1. 确认用户交易意图（币种、方向、数量）
2. 若信息不完整，调用 `confirm_popup` 询问用户
3. 用户确认后，调用 `place_spot_order` 执行下单
4. 下单完成后展示交易卡片

## 查询持仓

用户询问持仓情况时，调用 `query_positions` 获取数据。

## 查询订单

用户询问历史订单时，调用 `query_orders` 获取数据。
