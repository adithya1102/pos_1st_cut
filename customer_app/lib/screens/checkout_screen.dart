import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/offer.dart';
import '../services/api_client.dart';
import '../services/location_service.dart';
import '../services/order_service.dart';
import '../services/payment_service.dart';
import '../services/places_service.dart';
import '../state/cart_state.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../widgets/offer_sheet.dart';
import '../widgets/price_text.dart';
import 'payment_processing_screen.dart';
import 'pickup_screen.dart';
import 'place_search_screen.dart';
import '../widgets/account_button.dart';

/// PE Step 3 (FR-C1) — how the customer will travel to the outlet. Values map
/// 1:1 to the backend MODE_SPEED_MPS keys used by the travel predictor.
enum TransportMode {
  walk('walk', 'Walk', Icons.directions_walk),
  bike('bike', 'Bike', Icons.two_wheeler),
  car('car', 'Car', Icons.directions_car),
  auto('auto', 'Auto', Icons.local_taxi),
  bus('bus', 'Bus', Icons.directions_bus);

  const TransportMode(this.wire, this.label, this.icon);
  final String wire;
  final String label;
  final IconData icon;
}

/// Step 8: checkout with UPI / Card / Net Banking ONLY (no pay-at-counter).
class CheckoutScreen extends StatefulWidget {
  const CheckoutScreen({super.key, this.customerNotes});
  final String? customerNotes;

  @override
  State<CheckoutScreen> createState() => _CheckoutScreenState();
}

class _CheckoutScreenState extends State<CheckoutScreen> {
  PaymentMethod _method = PaymentMethod.upi;
  bool _placing = false;

  /// Optional points-discount coupon code. Validated server-side at order
  /// creation — the app deliberately does no local check, so there is exactly
  /// one place that decides whether a code is spendable.
  final _coupon = TextEditingController();

  /// The offer the customer picked from the restaurant's list (migration 016).
  ///
  /// Mutually exclusive with [_coupon] because V1 does not stack: the server
  /// rejects an order carrying both, so the UI disables one when the other is
  /// in play rather than letting them build a basket that cannot be paid for.
  Offer? _offer;

  @override
  void dispose() {
    _coupon.dispose();
    super.dispose();
  }

  /// Local preview of the saving, for the struck-through price. The server
  /// recomputes and is the authority — the order response carries the real
  /// original / discount / final figures.
  double _previewDiscount(double subtotal) =>
      _offer?.previewSaving(subtotal) ?? 0;

  // FR-C1/C2: travel context captured before the order is placed.
  TransportMode _transport = TransportMode.bike;
  double? _originLat;
  double? _originLng;
  String _originSource = 'none'; // none | gps | places_autocomplete
  String? _originLabel;
  bool _locating = false;

  Future<void> _useMyLocation() async {
    setState(() => _locating = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final res = await context.read<LocationService>().getCurrentLocation();
      if (!mounted) return;
      if (res.hasCoordinates) {
        setState(() {
          _originLat = res.latitude;
          _originLng = res.longitude;
          _originSource = 'gps';
          _originLabel = 'Current location';
        });
      } else {
        // FR-C6: denial degrades gracefully — the order still goes through,
        // the estimate is just wider/approximate.
        setState(() {
          _originLat = null;
          _originLng = null;
          _originSource = 'none';
          _originLabel = null;
        });
        messenger.showSnackBar(const SnackBar(
          content: Text('Location off — we\'ll show an approximate wait.'),
        ));
      }
    } finally {
      if (mounted) setState(() => _locating = false);
    }
  }

  Future<void> _searchLocation() async {
    // FR-C2: Places Autocomplete origin (one Google session per search flow).
    final loc = await Navigator.of(context).push<PlaceLocation>(
      MaterialPageRoute(builder: (_) => const PlaceSearchScreen()),
    );
    if (!mounted || loc == null) return;
    setState(() {
      _originLat = loc.lat;
      _originLng = loc.lng;
      _originSource = 'places_autocomplete';
      _originLabel = loc.label;
    });
  }

  /// Hard availability gate, run BEFORE payment.
  ///
  /// Returns true when the order may proceed. When items have gone unavailable
  /// since they were added, this prompts to remove them and returns false —
  /// the customer is never charged for a basket the kitchen cannot fulfil, and
  /// never discovers the problem after committing.
  Future<bool> _ensureAvailable(CartState cart) async {
    final outletId = cart.outletId;
    if (outletId == null || cart.isEmpty) return true;

    final orders = context.read<OrderService>();
    final List<String> unavailableIds;
    try {
      unavailableIds = await orders.checkCartAvailability(
        outletId: outletId,
        menuItemIds: cart.items.map((i) => i.item.id).toSet().toList(),
      );
    } on ApiException {
      // The pre-check is a courtesy, not the authority. If it cannot run, let
      // create_order's server-side validation be the gate rather than blocking
      // a legitimate order on a flaky network call.
      return true;
    }
    if (unavailableIds.isEmpty || !mounted) return unavailableIds.isEmpty;

    final names = cart.items
        .where((i) => unavailableIds.contains(i.item.id))
        .map((i) => i.item.name)
        .toSet()
        .toList();

    final removed = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(
          names.length == 1 ? 'An item just sold out' : 'Some items just sold out',
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              names.length == 1
                  ? '${names.first} is no longer available at this restaurant.'
                  : 'These are no longer available at this restaurant:',
            ),
            if (names.length > 1) ...[
              const SizedBox(height: 8),
              ...names.map((n) => Text('•  $n')),
            ],
            const SizedBox(height: 12),
            const Text(
              'Remove them to continue — you have not been charged.',
              style: TextStyle(fontSize: 12),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('Back to cart'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, true),
            child: Text(names.length == 1 ? 'Remove it' : 'Remove them'),
          ),
        ],
      ),
    );

    if (removed == true) {
      cart.removeUnavailable(unavailableIds.toSet());
    }
    // Always false: even after removing, the customer re-confirms the new total
    // rather than having a smaller order silently charged.
    return false;
  }

  Future<void> _payNow() async {
    final cart = context.read<CartState>();
    final outlet = cart.outlet;
    setState(() => _placing = true);
    try {
      if (!await _ensureAvailable(cart)) return;
      if (!mounted) return;
      final order = await context.read<OrderService>().createOrder(
            cart.toOrderPayload(
              customerNotes: widget.customerNotes,
              transportMode: _transport.wire,
              originLat: _originLat,
              originLng: _originLng,
              originSource: _originSource,
              // Never both: an offer takes precedence over a leftover coupon
              // code, matching the mutual exclusion the UI already enforces.
              couponCode: _offer == null ? _coupon.text : null,
              promotionId: _offer?.id,
            ),
          );
      if (!mounted) return;

      // UPI-intent MVP: go to the pickup screen, which shows a tappable
      // "Pay via UPI" button that opens the user's UPI app with the amount
      // locked. Staff then confirm the payment manually.
      if (_method == PaymentMethod.upi) {
        // NOTE: the cart is deliberately NOT cleared here. At this point the
        // order row exists but payment_status is still PENDING — the UPI intent
        // has not even been opened yet. Clearing now loses the basket for
        // anyone who cancels in their UPI app, fails, or never pays.
        // PickupScreen clears it once the order is observed PAID.
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => PickupScreen(
              orderId: order.id,
              upiVpa: outlet?.upiId,
              payeeName: outlet?.name,
              amount: order.totalAmount,
            ),
          ),
        );
        return;
      }

      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => PaymentProcessingScreen(order: order, method: _method),
        ),
      );
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.message)));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not place order. Try again.')),
        );
      }
    } finally {
      if (mounted) setState(() => _placing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<CartState>();
    final textTheme = Theme.of(context).textTheme;
    final c = AppColors.of(context);

    final subtotal = cart.subtotal;
    final discount = _previewDiscount(subtotal);
    final payable = (subtotal - discount).clamp(0.0, subtotal);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Checkout'),
        actions: careVoActions(),
      ),
      bottomNavigationBar: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
          child: NeoButton(
            label: 'Pay ${formatRupees(payable)}  •  ${_method.label}',
            icon: Icons.lock,
            loading: _placing,
            onPressed: cart.isEmpty ? null : _payNow,
          ),
        ),
      ),
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
          children: [
            NeoCard(
              color: c.primary,
              child: Row(
                children: [
                  Icon(Icons.storefront, color: c.onPrimary),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'Self pickup at ${cart.outlet?.name ?? 'the outlet'}',
                      style: textTheme.titleMedium?.copyWith(color: c.onPrimary),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            Text('How are you getting here?', style: textTheme.headlineSmall),
            const SizedBox(height: 6),
            Text('Helps us time your food so it\'s fresh when you arrive.',
                style: textTheme.bodyMedium?.copyWith(color: c.inkSoft)),
            const SizedBox(height: 14),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                for (final mode in TransportMode.values)
                  _TransportChip(
                    mode: mode,
                    selected: _transport == mode,
                    onTap: () => setState(() => _transport = mode),
                  ),
              ],
            ),
            const SizedBox(height: 24),
            Text('Your starting point', style: textTheme.headlineSmall),
            const SizedBox(height: 12),
            _OriginCard(
              originLabel: _originLabel,
              locating: _locating,
              placesEnabled: context.read<PlacesService>().isEnabled,
              onUseLocation: _locating ? null : _useMyLocation,
              onSearch: _searchLocation,
            ),
            const SizedBox(height: 24),
            Text('Offers', style: textTheme.headlineSmall),
            const SizedBox(height: 6),
            Text(
              _offer == null
                  ? 'Pick one offer for this order.'
                  : 'One offer per order.',
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
            const SizedBox(height: 12),
            _OfferPicker(
              offer: _offer,
              // No picker without an outlet — offers are per restaurant, and
              // the cart is always bound to one before checkout is reachable.
              onBrowse: cart.outlet == null
                  ? null
                  : () => showOffersSheet(
                        context,
                        outlet: cart.outlet!,
                        subtotal: subtotal,
                        onApply: (o) => setState(() {
                          _offer = o;
                          // Mutual exclusion, made visible: adopting an offer
                          // clears a half-typed coupon rather than leaving a
                          // field the server would reject.
                          _coupon.clear();
                        }),
                      ),
              onClear: () => setState(() => _offer = null),
            ),
            const SizedBox(height: 24),
            Text('Have a coupon?', style: textTheme.headlineSmall),
            const SizedBox(height: 6),
            Text(
              _offer == null
                  ? 'Redeem points in your account to get a code.'
                  : 'Remove the offer above to use a points coupon instead.',
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _coupon,
              // Disabled, not hidden: the customer can see why it is
              // unavailable and what to do about it.
              enabled: _offer == null,
              autocorrect: false,
              enableSuggestions: false,
              textCapitalization: TextCapitalization.characters,
              decoration: const InputDecoration(
                labelText: 'Coupon code (optional)',
                hintText: 'PTS-ABCD2345',
                prefixIcon: Icon(Icons.confirmation_number_outlined),
              ),
            ),
            const SizedBox(height: 24),
            Text('Payment method', style: textTheme.headlineSmall),
            const SizedBox(height: 6),
            Text('Pay securely online. Counter payment is not available.',
                style: textTheme.bodyMedium?.copyWith(color: c.inkSoft)),
            const SizedBox(height: 16),
            for (final method in PaymentMethod.values) ...[
              _MethodTile(
                method: method,
                selected: _method == method,
                onTap: () => setState(() => _method = method),
              ),
              const SizedBox(height: 12),
            ],
            const SizedBox(height: 12),
            _TotalRow(
              subtotal: subtotal,
              discount: discount,
              payable: payable,
              offerLabel: _offer?.benefitText,
            ),
          ],
        ),
      ),
    );
  }
}

/// "Add an offer" / the chosen offer, with a way back out.
class _OfferPicker extends StatelessWidget {
  const _OfferPicker({
    required this.offer,
    required this.onBrowse,
    required this.onClear,
  });

  final Offer? offer;
  final VoidCallback? onBrowse;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final chosen = offer;

    if (chosen == null) {
      return NeoCard(
        onTap: onBrowse,
        child: Row(
          children: [
            Icon(Icons.local_offer_outlined, color: c.primary),
            const SizedBox(width: 14),
            Expanded(
              child: Text('See offers at this restaurant',
                  style: textTheme.titleMedium),
            ),
            Icon(Icons.chevron_right, color: c.inkSoft),
          ],
        ),
      );
    }

    return NeoCard(
      color: c.accent,
      child: Row(
        children: [
          Icon(Icons.local_offer, color: c.onAccent),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(chosen.benefitText,
                    style: textTheme.titleMedium?.copyWith(color: c.onAccent)),
                Text(
                  chosen.isCareVo ? 'CareVo offer' : 'Restaurant offer',
                  style: textTheme.bodySmall?.copyWith(color: c.onAccent),
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: 'Remove offer',
            onPressed: onClear,
            icon: Icon(Icons.close, color: c.onAccent),
          ),
        ],
      ),
    );
  }
}

class _MethodTile extends StatelessWidget {
  const _MethodTile({
    required this.method,
    required this.selected,
    required this.onTap,
  });
  final PaymentMethod method;
  final bool selected;
  final VoidCallback onTap;

  IconData get _icon => switch (method) {
        PaymentMethod.upi => Icons.qr_code_2,
        PaymentMethod.card => Icons.credit_card,
        PaymentMethod.netbanking => Icons.account_balance,
      };

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    return NeoCard(
      onTap: onTap,
      color: selected ? c.accent : c.surface,
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: selected ? c.surface : c.surfaceAlt,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: c.border, width: 2.5),
            ),
            child: Icon(_icon, color: c.ink),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(method.label,
                    style: textTheme.titleMedium?.copyWith(
                        color: selected ? c.onAccent : c.ink)),
                Text(method.subtitle,
                    style: textTheme.bodySmall?.copyWith(
                        color: selected ? c.onAccent : c.inkSoft)),
              ],
            ),
          ),
          Icon(
            selected ? Icons.radio_button_checked : Icons.radio_button_off,
            color: selected ? c.onAccent : c.inkSoft,
          ),
        ],
      ),
    );
  }
}

class _TransportChip extends StatelessWidget {
  const _TransportChip({
    required this.mode,
    required this.selected,
    required this.onTap,
  });
  final TransportMode mode;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: selected ? c.accent : c.surface,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: c.border, width: 2.5),
          boxShadow: [
            BoxShadow(
              color: c.shadow,
              offset: selected ? const Offset(3, 3) : const Offset(2, 2),
              blurRadius: 0,
            ),
          ],
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(mode.icon, size: 20, color: selected ? c.onAccent : c.ink),
            const SizedBox(width: 8),
            Text(mode.label,
                style: textTheme.titleSmall
                    ?.copyWith(color: selected ? c.onAccent : c.ink)),
          ],
        ),
      ),
    );
  }
}

class _OriginCard extends StatelessWidget {
  const _OriginCard({
    required this.originLabel,
    required this.locating,
    required this.placesEnabled,
    required this.onUseLocation,
    required this.onSearch,
  });
  final String? originLabel;
  final bool locating;
  final bool placesEnabled;
  final VoidCallback? onUseLocation;
  final VoidCallback? onSearch;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final hasOrigin = originLabel != null;
    return NeoCard(
      color: hasOrigin ? c.accent : c.surface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(hasOrigin ? Icons.my_location : Icons.location_searching,
                  color: hasOrigin ? c.onAccent : c.ink),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      hasOrigin ? originLabel! : 'Set your location',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: textTheme.titleMedium
                          ?.copyWith(color: hasOrigin ? c.onAccent : c.ink),
                    ),
                    Text(
                      hasOrigin
                          ? 'We\'ll estimate your travel time.'
                          : 'Optional — skips to an approximate wait if off.',
                      style: textTheme.bodySmall?.copyWith(
                          color: hasOrigin ? c.onAccent : c.inkSoft),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              if (locating)
                const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 8),
                  child: SizedBox(
                      width: 20, height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2)),
                )
              else
                _OriginAction(
                  icon: Icons.gps_fixed,
                  label: hasOrigin ? 'Update GPS' : 'Use GPS',
                  onTap: onUseLocation,
                  onSurface: hasOrigin,
                ),
              if (placesEnabled) ...[
                const SizedBox(width: 8),
                _OriginAction(
                  icon: Icons.search,
                  label: 'Search address',
                  onTap: onSearch,
                  onSurface: hasOrigin,
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }
}

class _OriginAction extends StatelessWidget {
  const _OriginAction({
    required this.icon,
    required this.label,
    required this.onTap,
    required this.onSurface,
  });
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  final bool onSurface;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final fg = onSurface ? c.onAccent : c.primary;
    return TextButton.icon(
      onPressed: onTap,
      icon: Icon(icon, size: 18, color: fg),
      label: Text(label, style: textTheme.labelLarge?.copyWith(color: fg)),
      style: TextButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      ),
    );
  }
}

/// The price breakdown: original struck through, the saving, then what is
/// actually charged.
///
/// Collapses to the single "Amount payable" row it has always been when there
/// is no discount — a struck-through price identical to the final one is noise.
class _TotalRow extends StatelessWidget {
  const _TotalRow({
    required this.subtotal,
    required this.discount,
    required this.payable,
    this.offerLabel,
  });

  final double subtotal;
  final double discount;
  final double payable;
  final String? offerLabel;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final c = AppColors.of(context);
    final hasDiscount = discount > 0;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
      child: Column(
        children: [
          if (hasDiscount) ...[
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Item total',
                    style: textTheme.bodyMedium?.copyWith(color: c.inkSoft)),
                Text(
                  formatRupees(subtotal),
                  style: textTheme.bodyMedium?.copyWith(
                    color: c.inkSoft,
                    decoration: TextDecoration.lineThrough,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Text(
                    offerLabel == null ? 'Offer applied' : 'Offer • $offerLabel',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: textTheme.bodyMedium?.copyWith(color: c.primary),
                  ),
                ),
                const SizedBox(width: 12),
                Text(
                  '− ${formatRupees(discount)}',
                  style: textTheme.bodyMedium?.copyWith(
                      color: c.primary, fontWeight: FontWeight.w700),
                ),
              ],
            ),
            const SizedBox(height: 10),
          ],
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('Amount payable', style: textTheme.titleMedium),
              PriceText(payable,
                  style: textTheme.headlineSmall
                      ?.copyWith(fontWeight: FontWeight.w700)),
            ],
          ),
        ],
      ),
    );
  }
}
