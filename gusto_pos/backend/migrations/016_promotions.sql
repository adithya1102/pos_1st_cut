-- Migration 016: promotions (CareVo Campaigns + Restaurant Offers)
--
-- Additive and idempotent throughout (CREATE TABLE IF NOT EXISTS /
-- CREATE INDEX IF NOT EXISTS), so re-running is a no-op. Nothing existing is
-- rewritten and no pre-existing column changes type or nullability.
--
-- WHY A NEW TABLE AND NOT `coupons` (migration 010) -----------------------------
-- `coupons` is a SINGLE-USE, per-customer instrument and its whole design says
-- so: one `status` column that flips ACTIVE -> REDEEMED on the first redemption,
-- one `redeemed_order_id`, one `redeemed_at`, one nullable `customer_id` owner.
-- The burn in CarevoService._consume_points_coupon is a single UPDATE guarded on
-- `status = 'ACTIVE'` — deliberately so two concurrent redemptions cannot both
-- win. That is exactly the wrong shape for a promotion: a promo code is ONE row
-- that MANY customers redeem MANY times, which `coupons` cannot express without
-- gutting the single-use guarantee that points redemption depends on.
--
-- So the two live side by side and never mix:
--   coupons      -> loyalty instrument, one customer, one order, then spent.
--   promotions   -> marketing instrument, shared, redeemed until a cap is hit.
--
-- SCOPE OF V1 ------------------------------------------------------------------
-- Deliberately NOT here: buy-X-get-Y / item-linked rules, cashback or
-- future-order credit, tiered spend-more ladders, subscription awareness,
-- scheduling (start/end timestamps — activation is a manual is_active toggle),
-- and stacking. One promotion per order, enforced below by a unique index.

-- 1. The promotion itself ------------------------------------------------------
CREATE TABLE IF NOT EXISTS promotions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- NULL is a first-class value: a Restaurant Offer is normally auto-surfaced
    -- on the outlet card and needs no code at all. A code exists only when the
    -- promotion is meant to be typed in (creator campaigns, shareable offers).
    code          varchar(24),

    -- Customer-facing one-liner: "20% off, up to Rs.60".
    label         varchar(120) NOT NULL,

    -- The ONLY funding switch. There is deliberately no separate funded_by
    -- column: CAREVO_CAMPAIGN is always funded by CareVo, RESTAURANT_OFFER is
    -- always funded by its outlet. A second column could disagree with this one.
    scope         varchar(20) NOT NULL,

    -- CAREVO_CAMPAIGN: NULL = platform-wide, set = campaign targeted at one
    -- restaurant. RESTAURANT_OFFER: always set (CHECK below) — an offer funded
    -- by a restaurant that names no restaurant is meaningless.
    outlet_id     uuid REFERENCES outlets(id) ON DELETE CASCADE,

    discount_type  varchar(10) NOT NULL,          -- PERCENT | FLAT
    -- PERCENT -> 0 < value <= 100. FLAT -> rupees off.
    discount_value numeric(10, 2) NOT NULL,

    -- The cap on a percentage discount. REQUIRED for a percentage Restaurant
    -- Offer (CHECK below) so an owner cannot ship "50% off" uncapped and
    -- discover it applied to a Rs.4000 party order. Optional for CareVo
    -- Campaigns, which CareVo funds and can therefore choose to leave uncapped.
    max_discount_amount numeric(10, 2),

    -- Minimum basket for the promotion to apply at all. NULL = no minimum.
    min_order_value     numeric(10, 2),

    -- Attribution for influencer/creator codes. CareVo Campaigns only (CHECK
    -- below) — a restaurant's own offer has no external creator to credit.
    creator_name  varchar(80),

    -- NULL = unlimited. Both caps are enforced in the service; the per-customer
    -- one additionally has DB teeth for the default case (see index 4 below).
    max_redemptions_total        integer,
    max_redemptions_per_customer integer NOT NULL DEFAULT 1,

    -- DEFAULT false on purpose: a promotion is drafted, reviewed, then switched
    -- on. Nothing goes live merely by being created. Manual toggle only — V1 has
    -- no scheduler, so there is no window during which "active" is a lie.
    is_active     boolean NOT NULL DEFAULT false,

    -- The admin (campaign) or owner (offer) who created it. SET NULL rather than
    -- CASCADE: deleting a staff account must not erase the promotion that
    -- customers already redeemed against.
    created_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT promotions_scope_valid
        CHECK (scope IN ('CAREVO_CAMPAIGN', 'RESTAURANT_OFFER')),
    CONSTRAINT promotions_discount_type_valid
        CHECK (discount_type IN ('PERCENT', 'FLAT')),
    CONSTRAINT promotions_discount_value_positive
        CHECK (discount_value > 0),
    -- A percentage over 100 would pay the customer to order.
    CONSTRAINT promotions_percent_within_100
        CHECK (discount_type <> 'PERCENT' OR discount_value <= 100),

    -- A restaurant-funded offer must name the restaurant funding it.
    CONSTRAINT promotions_offer_requires_outlet
        CHECK (scope <> 'RESTAURANT_OFFER' OR outlet_id IS NOT NULL),

    -- THE GUARDRAIL, in the schema and not only in the API: a percentage
    -- Restaurant Offer cannot exist without a cap. Expressible cleanly because
    -- it only references columns of this row.
    CONSTRAINT promotions_percent_offer_requires_cap
        CHECK (
            NOT (scope = 'RESTAURANT_OFFER' AND discount_type = 'PERCENT')
            OR max_discount_amount IS NOT NULL
        ),

    CONSTRAINT promotions_creator_is_campaign_only
        CHECK (creator_name IS NULL OR scope = 'CAREVO_CAMPAIGN'),
    CONSTRAINT promotions_caps_sane
        CHECK (
            max_redemptions_per_customer >= 1
            AND (max_redemptions_total IS NULL OR max_redemptions_total >= 1)
            AND (max_discount_amount IS NULL OR max_discount_amount > 0)
            AND (min_order_value IS NULL OR min_order_value >= 0)
        )
);

-- Codes are compared case-insensitively (the API upper-cases on the way in), so
-- uniqueness has to be too — otherwise "SAVE20" and "save20" both exist and the
-- lookup at checkout picks one arbitrarily. Partial so the many code-less
-- Restaurant Offers do not collide with each other on NULL.
CREATE UNIQUE INDEX IF NOT EXISTS idx_promotions_code_upper
    ON promotions (upper(code))
    WHERE code IS NOT NULL;

-- Backs GET /customer/offers, which is the hot read: active rows for one outlet
-- plus active platform-wide campaigns (outlet_id IS NULL).
CREATE INDEX IF NOT EXISTS idx_promotions_active_lookup
    ON promotions (is_active, outlet_id, scope);

-- 2. The redemption ledger -----------------------------------------------------
-- One row per (promotion, order). This is the source of truth for both caps and
-- for the redemption count the admin screen shows; nothing is counted off a
-- cached column that could drift.
CREATE TABLE IF NOT EXISTS promotion_redemptions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    promotion_id    uuid NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
    customer_id     uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    order_id        uuid NOT NULL REFERENCES customer_orders(id) ON DELETE CASCADE,
    -- Rupees actually taken off THIS order, after the percentage cap and after
    -- clamping to the basket. Not derivable from the promotion alone once
    -- discount_value is later edited, which is why it is stored.
    discount_amount numeric(10, 2) NOT NULL,
    -- Snapshot of promotions.max_redemptions_per_customer at redemption time.
    -- Exists ONLY so the partial unique index below can reference it: a partial
    -- index predicate can read columns of this table and nothing else.
    per_customer_cap integer NOT NULL DEFAULT 1,
    redeemed_at     timestamptz NOT NULL DEFAULT now()
);

-- 3. No stacking, with DB teeth ------------------------------------------------
-- Directly analogous to idx_point_txn_one_accrual_per_order: an order can carry
-- at most one promotion, whatever the service layer does. Not a partial index
-- because there is no exempt case — order_id is NOT NULL here.
CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_redemption_one_per_order
    ON promotion_redemptions (order_id);

-- 4. Per-customer cap ----------------------------------------------------------
-- Same pattern as idx_point_txn_one_accrual_per_order: a partial unique index
-- that closes the check-then-insert race the service layer cannot close alone
-- (two concurrent checkouts both count 0 prior redemptions and both proceed).
--
-- Covers max_redemptions_per_customer = 1, which is the default and the case
-- every V1 promotion is expected to use. Caps above 1 fall outside the
-- predicate and are enforced by the counted guard in the service — a partial
-- unique index cannot express "at most N" for a per-row N.
--
-- KNOWN CAVEAT: per_customer_cap is a snapshot. Raising a live promotion's cap
-- from 1 to 3 does NOT release customers who already redeemed under cap 1 —
-- their existing rows still carry 1 and still occupy the index. Deliberate for
-- V1 (caps are set at creation and left alone); revisit if editing caps
-- mid-campaign becomes a real workflow.
CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_redemption_one_per_customer
    ON promotion_redemptions (promotion_id, customer_id)
    WHERE per_customer_cap = 1;

-- Counting redemptions per promotion (admin screen) and per customer (cap check).
CREATE INDEX IF NOT EXISTS idx_promo_redemption_promotion
    ON promotion_redemptions (promotion_id, customer_id);

-- 5. Order-side record ---------------------------------------------------------
-- customer_orders.discount_amount already exists (migration 010) and stays the
-- single "rupees off this order" figure regardless of which instrument produced
-- it. promotion_id is the parallel of coupon_id: without it, a promotion-
-- discounted order is indistinguishable from a coupon-discounted one.
ALTER TABLE customer_orders
    ADD COLUMN IF NOT EXISTS promotion_id uuid REFERENCES promotions(id) ON DELETE SET NULL;
