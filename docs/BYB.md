# BYB orders — separate branch

`feature/byb-orders` builds on `feature/clock-apps`. Only this branch has
`record_order`, `announce_orders` and the order ledger. Generic upstream work
can be reviewed/merged without any BYB-specific code.

The BYB release is **1.3.0b3**, built from `feature/byb-orders`. It includes
the generic 1.3.0b2 Bluetooth settings fix. Deployments can now receive orders
directly on Home Assistant; there is no Mac dependency for order delivery.

## One created order

Use Developer tools → Actions for a test with a unique synthetic ID and a
current ISO timestamp (including timezone):

```yaml
action: glance_clock.record_order
data:
  id: test:order:1
  amount_minor: 59978
  currency: USD
  occurred_at: 'REPLACE_WITH_CURRENT_ISO_TIMESTAMP'
  display_name: Example University
```

Optional `entry_id` selects one of multiple clocks. The order announces
**$599.78 Example University**, with orange/gold rings and Bells. No extra
“new order” wording. Display name is optional and limited to 40 characters;
send institution or name, never addresses/email/payment data. This ledger
counts **created orders**, not paid sales or revenue. Refund/cancellation
adjustments are not implemented.

Repeated identical IDs are ignored; a reused ID with different data is
rejected. Amounts stay in integer cents and totals are separate per currency
(USD/EUR/GBP/CAD/AUD). Zero-value orders are valid. Events older than seven days
or more than five minutes in the future are rejected. Only events from the
last five minutes are announced; older orders can contribute to today's total.
Announcements are best-effort when the clock is offline or the queue is full.

HA stores the ledger in private `.storage/glance_clock.byb_orders.<entry_id>`.
Deduplication survives restarts. The optional authenticated receiver is described below. The ledger keeps
up to 10,000 orders and prunes entries older than seven days on new insertion;
if no new orders arrive, existing records remain until the next insertion.
The summary uses HA's timezone. Synthetic tests count in this ledger too; use
a separate test instance for end-to-end forwarding tests.

## Daily total

```yaml
action: glance_clock.announce_orders
data:
  sound: none
  duration: 20
```

Text: `0 orders`, `1 order: $599.78`, or `2 orders: $650.00`. Use the shared
scheduled-app blueprint for an interval or times such as `10:00, 14:00, 18:00`.

## Private receiver

Store the existing forwarder's bearer token (at least 32 characters) in
`/config/.storage/glance_clock.orders_token`, mode 0600, then restart HA.
Without that file the receiver stays disabled. This token grants only order
submission, not general Home Assistant API access. Keep it out of Git and logs.

The receiver is `POST /api/glance_clock/orders`. It accepts the same JSON as
`record_order`, with `Authorization: Bearer <token>`. It returns HTTP 200 and
`{"accepted":true}` only after durable persistence or an identical duplicate.
Authenticated GET is a side-effect-free readiness probe. Invalid auth is 401,
invalid data 400, oversized bodies 413, and persistence/unavailability errors
503 so the background sender can retry. Requests are limited to 4 KiB and four
concurrent submissions. The clock may be offline while orders are counted.

Use private Tailscale Serve HTTPS on ha-byb. Do not enable Funnel. Point the
existing API background forwarder at
`https://ha-byb.<tailnet>.ts.net/api/glance_clock/orders` using the same token.
Its bounded queue, outbox, timeouts and customer-handler isolation remain intact.
No customer checkout or Shopify webhook should wait for HA or Bluetooth.

Before switching, migrate previously delivered order IDs and values into the
HA ledger to preserve totals/deduplication, probe auth and malformed input,
verify a clock-only orange/gold preview, and test duplicate delivery across a
reload. Synthetic orders count in the ledger: use unit/integration tests or a
separate test ledger instead of inserting fake sales into production totals.
Keep the old route configuration as rollback until the private HA route is
verified, then stop the Mac receiver.
