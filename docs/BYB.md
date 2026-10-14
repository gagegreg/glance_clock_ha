# BYB orders — separate branch

`feature/byb-orders` builds on `feature/clock-apps`. Only this branch has
`record_order`, `announce_orders` and the order ledger. Generic upstream work
can be reviewed/merged without any BYB-specific code.

This is a prepared HA destination. **The production API forwarder is still
pointed at the Mac.** No checkout/webhook/API-service configuration was changed
by this HA port. Test the BLE connection and these actions before switching.

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
Deduplication survives restarts. There is no public webhook listener. It keeps
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

## Private forwarder handoff (later)

HA's authenticated REST action endpoint is
`POST /api/services/glance_clock/record_order` on **ha-byb**, reachable from
**api** over Tailscale. It accepts the same order payload keys as the Mac
receiver. It needs an HA access token with authorization to invoke the action,
not the Mac receiver's bearer token. Keep that token only in the forwarder's
protected environment; never in this repo, automation YAML, or a URL.

Before switching, verify TLS/network access from `api` to `ha-byb`, auth,
duplicate delivery across an HA restart, BLE acknowledgments, clock behavior,
and total/date boundaries. Keep the existing bounded background outbox and
timeouts. Nothing in checkout or the customer webhook handler should wait for
HA, Bluetooth, or the clock. Leave the Mac route available as a rollback.

This branch does not activate the route, migrate the Mac ledger, backfill real
orders, or modify any production API code.
