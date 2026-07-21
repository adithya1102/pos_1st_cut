# Gusto Owner App — Backend Support

Additive backend support for the **Gusto Owner App** (per-outlet owner control
surface). All endpoints are staff-authenticated (`get_current_staff`) and scoped
to the caller's own outlet (`user.outlet_id`). Mounted under `/api/v1/pos/...`.

## Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET  | `/api/v1/pos/outlet` | Caller's outlet: `{id, location_name, is_visible}` |
| POST | `/api/v1/pos/outlets/{id}/visibility` | Set `outlets.is_visible` (own outlet only, else 403) |
| GET  | `/api/v1/pos/menu-items` | Flat list of the outlet's latest-menu items |
| PATCH| `/api/v1/pos/menu-items/{id}/availability` | Toggle `menu_items.is_available` (own outlet only) |
| GET  | `/api/v1/pos/orders` | ACTIVE `customer_orders` (newest first, **name-free**) |
| POST | `/api/v1/pos/orders/{id}/notify` | Push a customer notification over WS |
| POST | `/api/v1/pos/orders/verify-pickup` | (existing) Verify pickup code |

### Notify types
`ready_now`, `delayed_10`, `item_unavailable`. For `item_unavailable`, `item_id`
is **required** and must be a `customer_order_items` row of that order (else
422/400). Payload broadcast over the existing `/ws/order/{order_id}` socket:

```json
{"event":"notify","order_id":"<uuid>","type":"<type>","item_id":<uuid|null>,
 "item_name":<str|null>,"message":"<human text>","ts":"<iso8601>"}
```

`delivered` in the response is best-effort — it reflects whether any socket was
connected at broadcast time.

### Privacy
The Owner App is **name-free**. `GET /api/v1/pos/orders` never returns customer
name or phone. Do not add them.

## Outlet visibility & customer discovery
`GET /api/v1/customer/outlets` now returns **only** outlets where
`is_visible = true`. Existing outlets default to `true`, so behavior is
unchanged until an owner toggles their outlet off.

## ⚠️ Order lockout is NOT auto-recoverable (deliberate pilot-stage decision)

After 3 failed pickup-code attempts, `customer_orders.is_locked` is set `true`
and `verify-pickup` returns HTTP 423. **v1 has no auto-recovery and no unlock
endpoint.** Unlocking is a direct DB update run by the operator:

```sql
UPDATE customer_orders SET is_locked = false, failed_attempts = 0 WHERE id = '<order_id>';
```

This is a **deliberate pilot-stage decision, not a bug** — during the pilot we
want a human in the loop for any disputed pickup rather than an automated reset
path that could be abused.
