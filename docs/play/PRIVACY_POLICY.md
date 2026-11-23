# Privacy Policy — Gusto Skip (CareVo)

**DRAFT ONLY — not published, not live, not linked from any app.** Written
for the Google Play Data Safety / privacy-policy requirement, covering the
two CareVo apps on this account: **Gusto Skip** (customer_app) and **Gusto
Restaurant** (owner_app). Every bracketed `[placeholder]` is a fact this
draft does not have — see the full list at the end. Do not host this file
or reference its URL in Play Console until every placeholder is replaced
and the content has been reviewed by someone who can speak for the company
legally.

**Company:** CareVo
**Contact:** adithya@carevo.co.in
**Registered address:** [REGISTERED ADDRESS]
**Grievance / Data Protection contact:** [GRIEVANCE OFFICER NAME AND CONTACT]
**Last updated:** [DATE OF ACTUAL PUBLICATION]

---

## 1. What this covers

This policy covers two apps published by CareVo:

- **Gusto Skip** (package `com.carevo.customer_app`) — the customer-facing
  app for browsing a restaurant's menu, ordering, and pickup.
- **Gusto Restaurant** (package `com.carevo.owner_app`) — the staff/owner
  app used by a restaurant to manage orders, menu, and (new) to generate a
  one-time code that links the restaurant's Native Gusto POS installation
  to its Gusto Skip account.

## 2. Data we collect

This list is drawn directly from what the apps' own code collects, not a
generic template. Each item names which app(s) it applies to.

| Data | Collected by | Why |
|---|---|---|
| Name | Gusto Skip, Gusto Restaurant | Customer profile / staff account identity |
| Phone number | Gusto Skip, Gusto Restaurant | OTP sign-in (customer); order contact (restaurant) |
| Email address | Gusto Skip, Gusto Restaurant | Account recovery, sign-in |
| Order history and contents | Gusto Skip, Gusto Restaurant | Placing and fulfilling orders |
| Payment transaction metadata (gateway order id, UPI VPA, payee name, pickup code) — **never full card/UPI PIN/CVV** | Gusto Skip, Gusto Restaurant | Processing payment and pickup |
| Loyalty points balance, premium/plan status | Gusto Skip | Loyalty program |
| Device location (fine/coarse), when permission is granted | Gusto Skip, Gusto Restaurant | Finding nearby outlets (customer); confirming the restaurant's own location (owner, one-time "use current location" action) |
| Push notification token | Gusto Skip, Gusto Restaurant | Order status and staff alerts |
| **Registration ID flow (new, 2026-11-24):** a one-time code and its expiry only — no personal data crosses this specific call | Gusto Restaurant | Linking a restaurant's Native Gusto POS installation to its Gusto Skip account. The POS backend separately receives the restaurant's own name, owner name, owner email, and owner phone at the moment of linking — this is data about the restaurant/owner, transferred between two systems the same business operates, not collected from end users. |

We do **not** collect: payment card numbers, UPI PINs, government ID
numbers, or precise location when permission is denied.

## 3. How data is used

- To operate the ordering, payment, and pickup flow.
- To let restaurant staff fulfill and manage orders.
- To send order-status and staff-alert push notifications.
- To link a restaurant's Native Gusto POS installation to its Gusto Skip
  account (Registration ID flow).

We do not sell personal data. We do not use it for advertising.

## 4. Data sharing

- Payment processors ([PAYMENT GATEWAY PROVIDER NAME, e.g. Razorpay/Cashfree])
  receive what is needed to process a transaction.
- The Native Gusto POS software the restaurant itself runs receives the
  restaurant/owner identity at the moment a Registration ID is redeemed (see
  row above). This is restaurant-operated software, not a third party.
- We do not share data with any other third party except as required by law.

## 5. Data retention

[RETENTION PERIOD — e.g. "for as long as the account is active, plus N days after deletion for backup purge"]

## 6. Your rights — account deletion

You can delete your account:
- **In-app:** Gusto Skip has an in-app "Delete my account" control (Profile
  → Delete account).
- **On the web**, including if you no longer have the app installed: see
  the account deletion request page, drafted alongside this policy at
  `docs/play/ACCOUNT_DELETION_REQUEST.html` (also not yet published).

Gusto Restaurant (the staff/owner app) has no self-service account creation
— restaurant accounts are provisioned by the CareVo team — so account
deletion for a restaurant is handled by contacting us directly at
adithya@carevo.co.in. **[LEGAL CONFIRMATION NEEDED: this draft assumes that
because Gusto Restaurant never creates its own accounts, it is outside
Play's in-app-or-web account-deletion requirement — a human/legal reviewer
should confirm this before publishing, not just this document's own
reasoning.]**

## 7. Security

Passwords are stored hashed, never in plain text. [ADD ANY FURTHER SECURITY
CLAIMS ONLY IF TRUE AND VERIFIED — e.g. encryption at rest/in transit,
specific certifications.]

## 8. Children's privacy

[STATEMENT ON WHETHER THE SERVICE IS DIRECTED AT OR KNOWINGLY COLLECTS DATA
FROM CHILDREN — needs a real answer, not a placeholder guess.]

## 9. Changes to this policy

[HOW CHANGES WILL BE COMMUNICATED]

## 10. Contact us

CareVo
adithya@carevo.co.in
[REGISTERED ADDRESS]

---

## Placeholders in this draft (fill in before publishing)

1. `[REGISTERED ADDRESS]` (appears twice) — company's registered/business address.
2. `[GRIEVANCE OFFICER NAME AND CONTACT]` — required in some jurisdictions (e.g. India's DPDP framework); needs a named person/contact.
3. `[DATE OF ACTUAL PUBLICATION]` — set when this is actually hosted.
4. `[PAYMENT GATEWAY PROVIDER NAME, e.g. Razorpay/Cashfree]` — name the actual live gateway(s) in production.
5. `[RETENTION PERIOD — ...]` — needs a real, decided retention policy, not a guess.
6. `[LEGAL CONFIRMATION NEEDED: ...]` — the account-deletion-scope reasoning for Gusto Restaurant needs a human/legal sign-off, not just this document asserting it.
7. `[ADD ANY FURTHER SECURITY CLAIMS ONLY IF TRUE AND VERIFIED ...]` — do not add claims (e.g. "encrypted at rest") unless verified true.
8. `[STATEMENT ON WHETHER THE SERVICE IS DIRECTED AT OR KNOWINGLY COLLECTS DATA FROM CHILDREN]` — needs a real policy decision.
9. `[HOW CHANGES WILL BE COMMUNICATED]` — needs a real decided process (e.g. in-app notice, email).
