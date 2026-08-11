# Privacy Policy — CareVo

**Last updated:** 10 August 2026

This policy explains what the CareVo customer app (`com.carevo.customer_app`)
collects, why, and who it is shared with.

> **Before publishing:** replace every `[…]` placeholder below with real values,
> then host this at a public URL and paste that URL into Play Console →
> App content → Privacy policy. Play requires a working link on a page that is
> publicly reachable without logging in.
>
> The contents below describe what the app **actually does today**, derived from
> its declared Android permissions, its dependencies, and the data its backend
> stores. If you change what the app collects, change this page too — a policy
> that overstates or understates collection is a compliance problem either way.

---

## 1. Who we are

CareVo is operated by **[LEGAL ENTITY NAME]**, [ADDRESS], India.
Privacy contact: **[privacy@yourdomain.com]**

## 2. What we collect

### 2.1 Account and identity
Depending on how you sign in, we collect **one or both** of:

- **Phone number** — when you sign in with a one-time SMS code. Verification is
  performed by Google Firebase Authentication; we receive the verified number.
- **Email address, name and Google account identifier** — when you sign in with
  Google.

You may also optionally provide a **display name**.

We do **not** collect or store your password. We never receive your Google
password, and SMS codes are verified by Firebase, not by us.

### 2.2 Location
The app requests **approximate and precise location** (`ACCESS_COARSE_LOCATION`,
`ACCESS_FINE_LOCATION`) and uses it to:

- sort nearby restaurants by distance;
- estimate your travel time to a restaurant so food is ready when you arrive;
- detect arrival at the restaurant during an active order.

Location is used **only while you are using the app or have a live order**.
Granting location is **optional** — declining it still lets you browse, order
and pay; you will simply see a wider, approximate wait estimate.

You can revoke location access at any time in Android Settings → Apps → CareVo
→ Permissions.

### 2.3 Orders and usage
- Items ordered, quantities, customisations and order notes
- Order status history and timestamps
- Pickup verification codes
- Loyalty points balance and any offers or coupons you redeem
- The restaurant you ordered from

### 2.4 Payments
Payments are processed by **Cashfree Payments** (`cashfree.com`). You enter your
payment details in Cashfree's checkout, not in CareVo.

**We never see, receive or store your full card number, UPI PIN, CVV, or bank
credentials.** Our servers store only a payment reference, the amount, the
method type (e.g. "upi"), and whether the payment succeeded.

### 2.5 Notifications
If you allow notifications (`POST_NOTIFICATIONS`), we store a **Firebase Cloud
Messaging device token** to send order updates — order confirmed, being prepared,
ready for pickup, item unavailable, order cancelled — and occasional reminders
about restaurants you have ordered from. Declining notifications does not affect
your ability to order.

### 2.6 Technical data
Standard server logs (IP address, timestamps, error diagnostics) retained for
security and debugging.

## 3. What we do NOT do

- We do **not** sell your personal data.
- We do **not** share your data with advertisers or data brokers.
- We do **not** track you across other apps or websites.
- We do **not** collect contacts, photos, microphone, camera, SMS content, or
  call logs.
- We do **not** track your location in the background when the app is closed.

## 4. Who your data is shared with

| Recipient | What they receive | Why |
|---|---|---|
| **The restaurant you order from** | Your order contents, order ID, pickup code | To prepare and hand over your order |
| **Cashfree Payments** | Payment amount, order reference, contact details you enter at checkout | To process payment |
| **Google Firebase** (Authentication, Cloud Messaging) | Phone number or Google account identifier; device notification token | Sign-in verification and notification delivery |
| **Google Maps Platform** | Coarse location / place searches you perform | Distance and travel-time estimates |
| **[HOSTING PROVIDER, e.g. Render / Neon]** | All of the above, at rest | Application and database hosting |

Each processes data under its own privacy policy. We share the minimum needed
for the service to function, and for no other purpose.

## 5. How long we keep it

- **Account data** — until you ask us to delete your account.
- **Order history** — retained for business and tax records.
- **Location points** — retained only for the life of the relevant order, then
  discarded or aggregated.
- **Notification tokens** — until you disable notifications or uninstall.

## 6. Your rights

You may request **access to**, **correction of**, or **deletion of** your
personal data, and you may withdraw consent for location or notifications at any
time through Android's permission settings.

To request deletion of your account and associated personal data, email
**[privacy@yourdomain.com]**. We will respond within 30 days.

> **Note:** Play Store policy requires an in-app or web-based account deletion
> route for apps that let users create accounts. If you do not add an in-app
> "Delete my account" control, you must provide a publicly reachable deletion
> request page and declare its URL in Play Console.

## 7. Children

CareVo is not directed at children under 13, and we do not knowingly collect
data from them.

## 8. Security

Data is transmitted over HTTPS. Access to production data is restricted to
authorised personnel. No system is perfectly secure, and we do not claim
otherwise; we will notify affected users of a breach that puts their data at
risk, as required by law.

## 9. Changes

Material changes will be reflected here with an updated "Last updated" date.

## 10. Contact

**[LEGAL ENTITY NAME]** — **[privacy@yourdomain.com]** — [ADDRESS], India
