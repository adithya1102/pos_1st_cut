# YOUPI PG integration

Replaces the Cashfree sandbox for end-to-end testing. Cashfree is **not**
removed — `PAYMENT_GATEWAY` selects, so switching back is one env var.

## How payment confirmation actually works

This is the part that differs from Cashfree and drives every design choice here.

```
customer app ──create order──▶ backend ──create payment──▶ YouPI
     │                                                       │
     └──opens YouPI checkout page──▶ customer's UPI app      │
                                            │                │
                                   pays restaurant's VPA     │
                                            │                │
                                   bank SMS to restaurant    │
                                            │                │
                              Gusto Payment Observer ────────┘
                               (app.gustoskip.observer)
                                            │
                         YouPI ──signed webhook──▶ backend ──▶ order PAID
```

YouPI has no bank relationship. Its only evidence a payment happened is a bank
credit alert observed on the restaurant's phone. **Without the observer app
installed, paired and running there, a real payment debits the customer and the
order never confirms.**

## The observer

`youpi_observer/` — package **`app.gustoskip.observer`**, built in this repo.
**It is the only observer used in this trial.**

Do not install YouPI's own prebuilt SMS gateway (`com.youpi.observer`, served by
the gateway at `/api/v1/admin/sms-gateway/download-apk`). Its reference driver
posts the message text itself (`apps/android-observer-app/driver.js:89` sends a
`text` field), and the ingestion route accepts it — `pollers.routes.js:78` reads
`rawText || text || message || sms || body` and will re-parse it server-side.
Uploading raw bank SMS off the device is not permitted here.

`app.gustoskip.observer` never sends message text. `CreditParser.parse()` takes
the body as an argument and returns only `amountPaise`, `bankReferenceNumber`
and `senderVpa`; `Api.report()` accepts that struct, so there is no parameter
through which text could travel. It requests `RECEIVE_SMS` only — not `READ_SMS`,
so it cannot see the existing inbox — and declares no notification listener.
Non-credits (OTPs above all) are dropped before any network call.

Because the observer sends no text, YouPI's server-side parse path is never
reached: `pollers.routes.js:141` only re-parses when `rawText` is present.

### Pair it

1. Build and install (see **Build** below). Grant the SMS permission.
2. Open the app. Enter:
   - **Gateway URL** — `https://youpi.carevo.co.in`
   - **Enrollment token** — YouPI's `ANDROID_ENROLLMENT_SECRET`, or a token from
     `GET /api/v1/admin/sms-gateway/pair-qr`
3. Tap **Pair this phone**. On success it stores only the `deviceId` and
   `signingKey` the gateway returns; the enrollment token is single-use and is
   cleared from the field either way.

It then POSTs each observed credit to `/api/v1/observers/sms`, signed
`HMAC-SHA256(rawBody + ":" + timestamp)` with the signing key, as
`X-Device-Id` / `X-Timestamp` / `X-Signature`. That matches the server's check at
`pollers.routes.js:284` exactly.

Then in owner_app → Outlet Settings, enter the restaurant's real UPI ID.

## Reachability

Everything reaches YouPI over one public hostname: **`https://youpi.carevo.co.in`**,
fronted by Cloudflare and tunnelled to the loopback listeners.

- **The Render backend** calls `{YOUPI_BASE_URL}/api/v1/payments` from Render's
  network. It cannot route to a private address, so the base URL must be the
  public HTTPS host.
- **The observer phone** is on mobile data or any network, and its manifest sets
  `usesCleartextTraffic="false"` — Android refuses plaintext HTTP from it
  outright. HTTPS to a public host is the only transport it has.
- **The customer's phone** only opens the `checkoutUrl` the gateway returns, in
  an external browser. No host is compiled into that path.

So nothing in the trial needs YouPI bound to a LAN interface, and
`YOUPI_BIND_HOST` stays on loopback. The Cloudflare rule described under
`YOUPI_EDGE_KEY` is what guards the otherwise-unauthenticated
`POST /api/v1/payments`; a LAN bind would put that route on the local network
behind no guard at all.

## What changed

**Backend**

| File | Change |
|---|---|
| `carevo_payments/gateway.py` | `YoupiGateway(PaymentGateway)`; `GatewayOrder.checkout_url` (additive); factory accepts `youpi` |
| `core/config.py` | `YOUPI_BASE_URL`, `YOUPI_WEBHOOK_SECRET`, `YOUPI_MERCHANT_ID`, `YOUPI_RETURN_URL`, `YOUPI_ADMIN_TOKEN`, `YOUPI_EDGE_KEY` |
| `carevo_customer/controller.py` | webhook reads `X-Gateway-Signature` / `X-Gateway-Timestamp` |
| `carevo_customer/schema.py` | `PaymentBlock.checkout_url`; `SetPaymentVpaIn` / `PaymentVpaOut` |
| `carevo_customer/service.py` | `set_payment_vpa()` — registers the VPA with YouPI server-side |
| `carevo_pos/controller.py` | `POST /pos/outlet/payment-vpa` (staff-authed, own outlet only) |

**customer_app**

- `services/youpi_service.dart` — opens YouPI's hosted checkout
- `models/order.dart` — `checkoutUrl`, `isYoupi`, `needsHostedCheckout`
- `screens/checkout_screen.dart`, `screens/pickup_screen.dart` — branch on gateway

**owner_app**

- `screens/outlet_settings_screen.dart` — UPI ID field
- `services/outlet_service.dart`, `state/home_state.dart` — `setPaymentVpa`
- `config/app_config.dart` — `API_BASE_URL` now overridable (default unchanged)

**youpi_observer** (new)

- `app.gustoskip.observer` — `CreditParser`, `SmsReceiver`, `Api`, `Prefs`,
  single pairing screen; 12 parser unit tests

## Three decisions worth keeping

**The app opens YouPI's checkout page, not a raw `upi://` intent.** That page
performs the `select-method` and `payment-done` transitions the gateway
requires before an observed credit can be attributed to the session. A raw
intent skips them and the payment stays `UNRESOLVED` forever.

**The gateway admin token never reaches a device.** The owner app posts the VPA
to this backend, which calls YouPI. A token inside an APK is an extracted token.

**`YoupiService` never reports success.** Returning from a UPI app proves
nothing — the signed webhook is the only authority. It returns the existing
"cannot vouch" outcome, which routes `PickupScreen` into its confirm-and-poll
state. That was already the app's model for Cashfree; it is simply more true here.

## Configuration

Backend `.env`:

```
PAYMENT_GATEWAY=youpi
YOUPI_BASE_URL=https://youpi.carevo.co.in
YOUPI_WEBHOOK_SECRET=<merchant webhook secret>
YOUPI_ADMIN_TOKEN=<YouPI-PG/data/.secrets/admin_api_token>
YOUPI_EDGE_KEY=<same value as the Cloudflare WAF rule's X-Gusto-Edge-Key>
YOUPI_RETURN_URL=https://gusto-pos-backend.onrender.com/api/v1/customer/payment/return
```

`YOUPI_EDGE_KEY` is required, not optional — `YoupiGateway.configured` is false
without it and `create_order` refuses rather than calling a route the edge would
block as an opaque 403.

YouPI `.env`:

```
YOUPI_BIND_HOST=127.0.0.1        # loopback only; the tunnel fronts it
YOUPI_ALLOW_PRIVATE_WEBHOOKS=true
YOUPI_ALLOW_DEV_TOOLS=true
```

Register the webhook (once), against the loopback admin API:

```bash
TOKEN=$(cat YouPI-PG/data/.secrets/admin_api_token)
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"webhookUrl":"https://gusto-pos-backend.onrender.com/api/v1/customer/payment/webhook",
       "webhookSecret":"<same secret>"}' \
  http://127.0.0.1:6100/api/v1/admin/merchant-settings
```

No inbound firewall rule is needed: both listeners are on loopback and the
tunnel dials out.

## Build

Both apps must be pointed at the **trial** Render service. Their compiled-in
default is the LIVE service, so an un-overridden build sends trial traffic —
including real ₹1 payments — to production.

```bash
cd customer_app && flutter build apk --release \
  --dart-define=API_BASE_URL=<TRIAL_RENDER_URL>

cd owner_app && flutter build apk --release \
  --dart-define=API_BASE_URL=<TRIAL_RENDER_URL>
```

`<TRIAL_RENDER_URL>` is the trial service's API base, ending in `/api/v1`.

The define name is `API_BASE_URL` in both apps —
`customer_app/lib/config/app_config.dart:12` and
`owner_app/lib/config/app_config.dart:18` — each defaulting to the live
service at `customer_app/lib/config/app_config.dart:13` and
`owner_app/lib/config/app_config.dart:19`.

The value is compiled in, so changing the trial URL means rebuilding both APKs.

Observer:

```bash
cd youpi_observer && ./gradlew assembleRelease
# app/build/outputs/apk/release/app-release.apk
```

Debug-signed on purpose — it is sideloaded, and the release keystores belong to
the two store apps.

## Install

| Device | Install |
|---|---|
| Customer phone | `customer_app` release APK (`com.carevo.customer_app`) |
| Restaurant phone | `owner_app` release APK (`com.carevo.owner_app`) **and** the observer (`app.gustoskip.observer`) |

Distinct package names, so all three can coexist on one device if you only have
one.

## Reverting to Cashfree

Set `PAYMENT_GATEWAY=cashfree`. No code changes — the Cashfree path is untouched.
