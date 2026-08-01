import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/location_service.dart';
import '../services/order_service.dart';
import '../services/payment_service.dart';
import '../services/places_service.dart';
import '../state/cart_state.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../widgets/price_text.dart';
import '../widgets/theme_toggle_button.dart';
import 'payment_processing_screen.dart';
import 'pickup_screen.dart';
import 'place_search_screen.dart';

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

  Future<void> _payNow() async {
    final cart = context.read<CartState>();
    final outlet = cart.outlet;
    setState(() => _placing = true);
    try {
      final order = await context.read<OrderService>().createOrder(
            cart.toOrderPayload(
              customerNotes: widget.customerNotes,
              transportMode: _transport.wire,
              originLat: _originLat,
              originLng: _originLng,
              originSource: _originSource,
            ),
          );
      if (!mounted) return;

      // UPI-intent MVP: go to the pickup screen, which shows a tappable
      // "Pay via UPI" button that opens the user's UPI app with the amount
      // locked. Staff then confirm the payment manually.
      if (_method == PaymentMethod.upi) {
        cart.clear();
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

    return Scaffold(
      appBar: AppBar(
        title: const Text('Checkout'),
        actions: const [
          Padding(padding: EdgeInsets.only(right: 16), child: ThemeToggleButton()),
        ],
      ),
      bottomNavigationBar: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
          child: NeoButton(
            label: 'Pay ${formatRupees(cart.subtotal)}  •  ${_method.label}',
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
            _TotalRow(subtotal: cart.subtotal),
          ],
        ),
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

class _TotalRow extends StatelessWidget {
  const _TotalRow({required this.subtotal});
  final double subtotal;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
      decoration: const BoxDecoration(),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text('Amount payable', style: textTheme.titleMedium),
          PriceText(subtotal,
              style: textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}
