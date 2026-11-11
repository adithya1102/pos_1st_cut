-- docs/ops/predeploy_markers.sql
--
-- READ-ONLY. One SELECT per migration 001-041 that have something checkable
-- (at least one new table or new column). Each row reports the migration
-- number and a boolean that is true only when every table AND every column
-- that migration creates is present in schema public right now.
--
-- Migrations that create no new table and no new column (only an index,
-- constraint, or ALTER COLUMN ... SET DEFAULT/NOT NULL on a column that
-- already existed) are NOT in this file — there is nothing in
-- information_schema that could distinguish "ran" from "did not run" for
-- them. They are listed in the accompanying report as NO_MARKER:
-- 018, 020 (the push_notifications CHECK-widening half only; 020 still gets
-- a row below for outlet_config / declared_arrival_at), 023, 027 (the
-- SET NOT NULL half only; 027 still gets a row below for the new column),
-- 036.
--
-- This file runs NO SQL by itself. It is meant to be executed by hand
-- (or by the predeploy check tooling) against the target database before
-- a deploy, to confirm the schema the new backend expects is actually there.

-- 001_carevo_skip.sql
SELECT '001' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='customer_orders')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='customer_order_items')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='payment_transactions')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='menu_items' AND column_name='is_available')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='menu_items' AND column_name='prep_time_minutes')
    AS present;

-- 002_owner_app.sql
SELECT '002' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='is_visible')
    AS present;

-- 003_admin_dashboard.sql
SELECT '003' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='verification_status')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='admin_audit_logs')
    AS present;

-- 004_menu_item_image.sql
SELECT '004' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='menu_items' AND column_name='image_url')
    AS present;

-- 005_outlet_upi.sql
SELECT '005' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='upi_id')
    AS present;

-- 006_prediction_engine.sql
SELECT '006' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='order_events')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='order_twin')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='prediction_log')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='order_outcome')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='travel_cache')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='travel_bias')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='outlet_reliability')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='menu_items' AND column_name='station')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='menu_items' AND column_name='base_prep_seconds')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='menu_items' AND column_name='occupancy_seconds')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='menu_items' AND column_name='hold_tolerance_seconds')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='menu_items' AND column_name='is_batchable')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='transport_mode')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='origin_lat')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='origin_lng')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='origin_source')
    AS present;

-- 007_outlet_soft_delete.sql
SELECT '007' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='deactivated_at')
    AS present;

-- 008_customer_google_identity.sql
SELECT '008' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customers' AND column_name='email')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customers' AND column_name='google_uid')
    AS present;

-- 009_outlet_phone.sql
SELECT '009' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='phone_number')
    AS present;

-- 010_loyalty_and_coupons.sql
SELECT '010' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customers' AND column_name='points_balance')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customers' AND column_name='premium_until')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='point_transactions')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='coupons')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='discount_amount')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='coupon_id')
    AS present;

-- 011_outlet_image.sql
SELECT '011' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='image_url')
    AS present;

-- 012_outlet_locality.sql
SELECT '012' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='locality')
    AS present;

-- 013_cities.sql
SELECT '013' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='cities')
    AS present;

-- 014_push_notifications.sql
SELECT '014' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customers' AND column_name='fcm_token')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customers' AND column_name='fcm_token_updated_at')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='push_notifications')
    AS present;

-- 015_user_email_and_reset.sql
SELECT '015' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='users' AND column_name='email')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='users' AND column_name='email_verified_at')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='auth_tokens')
    AS present;

-- 016_promotions.sql
SELECT '016' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='promotions')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='promotion_redemptions')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='promotion_id')
    AS present;

-- 017_staff_push_and_rejection.sql
SELECT '017' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='users' AND column_name='fcm_token')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='users' AND column_name='fcm_token_updated_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='push_notifications' AND column_name='user_id')
    AS present;

-- 018_push_kind_staff.sql: NO_MARKER (CHECK-constraint widen only; no new table/column)

-- 019_menu_item_tags.sql
SELECT '019' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='menu_items' AND column_name='tags')
    AS present;

-- 020_train_transport_mode.sql
SELECT '020' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='outlet_config')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='declared_arrival_at')
    AS present;

-- 021_outlet_relocation_request.sql
SELECT '021' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='pending_locality')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='pending_latitude')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='pending_longitude')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='relocation_is_pending')
    AS present;

-- 022_customer_history_cutoff.sql
SELECT '022' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customers' AND column_name='history_cutoff_at')
    AS present;

-- 023_customer_picked_up.sql: NO_MARKER (index on order_events.event_type only; no new table/column)

-- 024_outlet_hours.sql
SELECT '024' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='opens_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='closes_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='is_manually_closed')
    AS present;

-- 025_testers.sql
SELECT '025' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='testers')
    AS present;

-- 026_contact_labels.sql
SELECT '026' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='contact_labels')
    AS present;

-- 027_testers_identifier.sql
SELECT '027' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='testers' AND column_name='identifier')
    AS present;

-- 028_auto_advance_schedule.sql
SELECT '028' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='auto_advance_schedule')
    AS present;

-- 029_city_transport_profile.sql
SELECT '029' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='cities' AND column_name='city_type')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='cities' AND column_name='has_train')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='cities' AND column_name='transport_updated_at')
    AS present;

-- 030_city_transport_modes.sql
SELECT '030' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='transport_modes')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='city_transport_modes')
    AS present;

-- 031_scheduled_pickup.sql
SELECT '031' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='requested_pickup_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='release_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='auto_advance_schedule' AND column_name='kind')
    AS present;

-- 032_refund_and_manual_acceptance.sql
SELECT '032' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='refund_required')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='refund_reason')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='refund_flagged_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='acceptance_state')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='acceptance_deadline_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='accepted_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='prep_minutes_committed')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='alert_count')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='last_alert_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='acceptance_mode')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='acceptance_timeout_s')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='consecutive_expiries')
    AS present;

-- 033_stock_reservation_and_pickup_uniqueness.sql
SELECT '033' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='menu_items' AND column_name='stock_remaining')
    AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='stock_reservations')
    AS present;

-- 034_pay_at_pickup.sql
SELECT '034' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='payment_mode')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='contact_name')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='contact_phone')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='contact_redacted_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='call_state')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='call_attempts')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='first_call_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='collected_payment_method')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='collected_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='collected_by')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='no_show_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='payment_prepaid_enabled')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='payment_pay_at_pickup_enabled')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='call_window_s')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customers' AND column_name='no_show_count')
    AS present;

-- 035_manual_upi_and_owner_settings.sql
SELECT '035' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='payment_upi_manual_enabled')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='upi_vpa')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='upi_payee_name')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='upi_attested_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='cashfree_unlocked')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='payment_settings_updated_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='outlets' AND column_name='payment_settings_updated_by')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='payment_claimed_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='manual_refund_due')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='manual_refund_reason')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customers' AND column_name='false_claim_count')
    AS present;

-- 036_cashfree_default_locked.sql: NO_MARKER (ALTER COLUMN ... SET DEFAULT on an
-- already-existing column; information_schema.columns.column_default reflects
-- the CURRENT default regardless of whether 035 or 036 set it last, so it
-- cannot distinguish "036 ran" from "036 has not run yet" by itself)

-- 037_outlet_owner_marker.sql
SELECT '037' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='users' AND column_name='is_outlet_owner')
    AS present;

-- 038_payment_amount_mismatch.sql
SELECT '038' AS migration,
    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='payment_amount_mismatch')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='payment_amount_mismatch_at')
    AS present;

-- 039_payment_events.sql
SELECT '039' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='payment_events')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='vendor_payment_confirmed_at')
    AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='customer_orders' AND column_name='vendor_payment_confirmed_amount_paise')
    AS present;

-- 040_outlet_gateway_credentials.sql
SELECT '040' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='outlet_gateway_credentials')
    AS present;

-- 041_service_fee_ledger.sql
SELECT '041' AS migration,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='service_fee_ledger')
    AS present;
