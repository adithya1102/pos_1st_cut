# docs/play/ — Play-readiness drafts (NOT PUBLISHED)

Both files here are **drafts only**. Neither is hosted, linked from any
app, or referenced in any Play Console listing. Do not publish either
without legal/human review of the placeholders below.

- `PRIVACY_POLICY.md` — draft privacy policy for Gusto Skip (customer_app)
  and Gusto Restaurant (owner_app).
- `ACCOUNT_DELETION_REQUEST.html` — draft web account-deletion-request
  page layout. The form is not wired to any backend (deliberately —
  deleting on an unverified submission would let anyone delete anyone
  else's account by guessing an identifier).

## Every placeholder, across both files

| Placeholder | File(s) | What's needed |
|---|---|---|
| `[REGISTERED ADDRESS]` | PRIVACY_POLICY.md (×2), ACCOUNT_DELETION_REQUEST.html | Company's registered/business address |
| `[GRIEVANCE OFFICER NAME AND CONTACT]` | PRIVACY_POLICY.md | A named grievance/data-protection contact (e.g. for India's DPDP framework) |
| `[DATE OF ACTUAL PUBLICATION]` | PRIVACY_POLICY.md | Set when actually hosted |
| `[PAYMENT GATEWAY PROVIDER NAME, e.g. Razorpay/Cashfree]` | PRIVACY_POLICY.md | Name the actual live gateway(s) in production |
| `[RETENTION PERIOD — ...]` | PRIVACY_POLICY.md | A real, decided data-retention policy |
| `[LEGAL CONFIRMATION NEEDED: ...]` | PRIVACY_POLICY.md | Human/legal sign-off that Gusto Restaurant (no self-service signup) is genuinely outside Play's account-deletion requirement, not just this draft's own reasoning |
| `[ADD ANY FURTHER SECURITY CLAIMS ONLY IF TRUE AND VERIFIED ...]` | PRIVACY_POLICY.md | Do not add claims (e.g. "encrypted at rest") unless verified true |
| `[STATEMENT ON WHETHER THE SERVICE IS DIRECTED AT OR KNOWINGLY COLLECTS DATA FROM CHILDREN]` | PRIVACY_POLICY.md | A real policy decision |
| `[HOW CHANGES WILL BE COMMUNICATED]` | PRIVACY_POLICY.md | A real decided process |
| `[CONFIRM EXACT RETENTION BEHAVIOR — ...]` | ACCOUNT_DELETION_REQUEST.html | Exactly what "delete" does to order/accounting records — must match the real backend's delete-account implementation, not a generic promise |
| `[SLA — e.g. "30 days"]` | ACCOUNT_DELETION_REQUEST.html | A real, decided turnaround time for email-requested deletions |

**11 distinct placeholders, 13 occurrences total.** None of these were
guessed or filled with invented facts — every one is left exactly as a
placeholder per the task instructions.
