# 08 两融交易（融资融券）

> 来源：`docs2/sdk/python/API介绍/两融交易函数.html`
>
> **免费 / 付费**：函数本身免费，需要券商开通两融账户。
>
> 所有 `position_src` 参数取值：`PositionSrc_L1`（普通券源） / `PositionSrc_L2`（专项券源） / `PositionSrc_Unknown`（未指定）

---

## 交易类（开/平仓）

### `credit_buying_on_margin` — 融资买入

```
credit_buying_on_margin(position_src, symbol, volume, price,
                        order_type=OrderType_Limit,
                        order_duration=OrderDuration_Unknown,
                        order_qualifier=OrderQualifier_Unknown, account_id='')
```

```python
credit_buying_on_margin(position_src=PositionSrc_L1, symbol='SHSE.600000',
                        volume=100, price=10.67)
```

### `credit_short_selling` — 融券卖出

```
credit_short_selling(position_src, symbol, volume, price,
                     order_type=OrderType_Limit,
                     order_duration=OrderDuration_Unknown,
                     order_qualifier=OrderQualifier_Unknown, account_id='')
```

### `credit_buying_on_collateral` — 担保品买入

```
credit_buying_on_collateral(symbol, volume, price,
                            order_type=OrderType_Limit,
                            order_duration=OrderDuration_Unknown,
                            order_qualifier=OrderQualifier_Unknown, account_id='')
```

### `credit_selling_on_collateral` — 担保品卖出

```
credit_selling_on_collateral(symbol, volume, price,
                             order_type=OrderType_Limit, ...)
```

### `credit_collateral_in` — 担保品转入
```
credit_collateral_in(symbol, volume, account_id='')
```

### `credit_collateral_out` — 担保品转出
```
credit_collateral_out(symbol, volume, account_id='')
```

---

## 还款 / 还券

### `credit_repay_cash_directly` — 直接还款

```
credit_repay_cash_directly(amount, *, repay_type=0,
                           position_src=PositionSrc_Unknown,
                           contract_id=None, account_id='',
                           sno='', bond_fee_only=False)
```

`bond_fee_only=True` 时只还利息（券商支持时）。

### `credit_repay_share_directly` — 直接还券

```
credit_repay_share_directly(symbol, volume, *,
                            position_src=PositionSrc_Unknown,
                            contract_id=None, account_id='', sno='')
```

### `credit_repay_share_by_buying_share` — 买券还券

```
credit_repay_share_by_buying_share(symbol, volume, price, *,
                                   position_src=PositionSrc_Unknown,
                                   order_type=OrderType_Limit,
                                   order_duration=OrderDuration_Unknown,
                                   order_qualifier=OrderQualifier_Unknown,
                                   contract_id=None, account_id='', sno='')
```

### `credit_repay_cash_by_selling_share` — 卖券还款

```
credit_repay_cash_by_selling_share(symbol, volume, price, *,
                                   repay_type=0,
                                   position_src=PositionSrc_Unknown,
                                   order_type=OrderType_Limit, ...)
```

---

## 查询类

### `credit_get_collateral_instruments(account_id='', df=False)`
查询担保证券（哪些标的可作为担保物）。

### `credit_get_borrowable_instruments(position_src, account_id='', df=False)`
查询可融标的证券。

### `credit_get_borrowable_instruments_positions(position_src, account_id='', df=False)`
查询券商融券账户头寸（每只标的可融券数）。

### `credit_get_contracts(position_src, account_id='', df=False)`
查询融资融券合约（未平合约清单，每条合约有未还金额/未还券）。

### `credit_get_cash(account_id='')`
查询融资融券资金信息（保证金、可用、负债等）。
