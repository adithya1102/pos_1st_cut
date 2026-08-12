import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/outlet.dart';
import '../services/api_client.dart';
import '../services/catalog_service.dart';
import '../services/customer_service.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/neo_chip.dart';
import '../theme/widgets/neo_text_field.dart';
import '../theme/widgets/ticket_card.dart';
import 'menu_screen.dart';
import 'pickup_screen.dart';
import '../widgets/account_button.dart';
import '../widgets/offer_sheet.dart';

/// Step 4: nearby restaurant discovery.
class OutletsScreen extends StatefulWidget {
  const OutletsScreen({super.key, this.lat, this.lng, this.areaLabel});

  final double? lat;
  final double? lng;
  final String? areaLabel;

  @override
  State<OutletsScreen> createState() => _OutletsScreenState();
}

class _OutletsScreenState extends State<OutletsScreen> {
  late Future<List<Outlet>> _future;

  // v2 §1 screen 5 — search + filter chips over the already-fetched list.
  //
  // Filtering client-side, not server-side: the list is one small page the app
  // already holds, so a round trip per keystroke would add latency and offline
  // fragility for no benefit.
  final _search = TextEditingController();
  bool _nearestFirst = false;
  bool _offersOnly = false;
  bool _openOnly = false;

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  /// Apply search + chips. Kept pure and separate from build so the ordering
  /// rules are readable in one place.
  List<Outlet> _apply(List<Outlet> all) {
    final q = _search.text.trim().toLowerCase();
    var out = all.where((o) {
      if (_offersOnly && !o.hasOffers) return false;
      if (_openOnly && !o.isOpen) return false;
      if (q.isEmpty) return true;
      return o.name.toLowerCase().contains(q) ||
          (o.locality ?? '').toLowerCase().contains(q) ||
          o.address.toLowerCase().contains(q);
    }).toList();

    if (_nearestFirst) {
      // Outlets with no distance (no GPS origin, or no pin) sort last rather
      // than being treated as distance 0 — claiming an unknown outlet is the
      // closest would be a lie the customer acts on.
      out.sort((a, b) {
        final ad = a.distanceKm, bd = b.distanceKm;
        if (ad == null && bd == null) return 0;
        if (ad == null) return 1;
        if (bd == null) return -1;
        return ad.compareTo(bd);
      });
    }
    return out;
  }

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<List<Outlet>> _load() {
    return context.read<CatalogService>().fetchOutlets(
          lat: widget.lat,
          lng: widget.lng,
          // areaLabel IS the city filter. It previously only fed the subtitle,
          // so every area showed the identical full outlet list.
          city: widget.areaLabel,
        );
  }

  void _retry() => setState(() => _future = _load());

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final subtitle = widget.areaLabel != null
        ? 'Near ${widget.areaLabel}'
        : (widget.lat != null ? 'Closest to you' : 'All restaurants');

    return Scaffold(
      appBar: AppBar(
        title: const Text('Nearby'),
        actions: careVoActions(),
      ),
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 4, 20, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Pick a\nspot.', style: textTheme.displaySmall),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Icon(Icons.place, size: 16, color: c.primary),
                      const SizedBox(width: 4),
                      Text(subtitle,
                          style: textTheme.titleSmall?.copyWith(color: c.inkSoft)),
                    ],
                  ),
                ],
              ),
            ),
            const _ActiveOrderBanner(),
            // ---- search + filters (v2) ----
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 10),
              child: NeoTextField(
                key: const Key('outlet_search'),
                controller: _search,
                hintText: 'Search restaurants or areas',
                prefixIcon: Icons.search,
                onChanged: (_) => setState(() {}),
              ),
            ),
            SizedBox(
              height: 44,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 20),
                children: [
                  NeoChip(
                    key: const Key('chip_nearest'),
                    label: 'Nearest first',
                    icon: Icons.near_me_outlined,
                    selected: _nearestFirst,
                    onTap: () => setState(() => _nearestFirst = !_nearestFirst),
                  ),
                  const SizedBox(width: 8),
                  NeoChip(
                    key: const Key('chip_offers'),
                    label: 'Offers',
                    icon: Icons.local_offer_outlined,
                    selected: _offersOnly,
                    onTap: () => setState(() => _offersOnly = !_offersOnly),
                  ),
                  const SizedBox(width: 8),
                  NeoChip(
                    key: const Key('chip_open'),
                    label: 'Open now',
                    icon: Icons.schedule,
                    selected: _openOnly,
                    onTap: () => setState(() => _openOnly = !_openOnly),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: FutureBuilder<List<Outlet>>(
                future: _future,
                builder: (context, snap) {
                  if (snap.connectionState == ConnectionState.waiting) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snap.hasError) {
                    return _ErrorState(
                      message: snap.error is ApiException
                          ? (snap.error as ApiException).message
                          : 'Could not load restaurants.',
                      onRetry: _retry,
                    );
                  }
                  final outlets = _apply(snap.data ?? const []);
                  if (outlets.isEmpty && (snap.data ?? const []).isNotEmpty) {
                    // Filtered to nothing — distinct from "no restaurants
                    // here", because the fix is different: clear a chip.
                    return _ErrorState(
                      message: 'No restaurants match those filters.',
                      onRetry: () => setState(() {
                        _search.clear();
                        _nearestFirst = _offersOnly = _openOnly = false;
                      }),
                    );
                  }
                  if (outlets.isEmpty) {
                    return _ErrorState(
                      message: widget.areaLabel != null
                          ? 'No restaurants in ${widget.areaLabel} yet.'
                          : 'No restaurants found here yet.',
                    );
                  }
                  return RefreshIndicator(
                    onRefresh: () async => _retry(),
                    child: ListView.separated(
                      padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
                      itemCount: outlets.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 16),
                      itemBuilder: (_, i) => _OutletCard(outlet: outlets[i]),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _OutletCard extends StatelessWidget {
  const _OutletCard({required this.outlet});
  final Outlet outlet;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return NeoCard(
      key: Key('outlet_card_${outlet.id}'),
      onTap: outlet.isOpen
          ? () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => MenuScreen(outlet: outlet)),
              )
          : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Storefront photo (migration 011) fills the box that previously
              // always showed a generic glyph. Falls back to that glyph when the
              // outlet has no photo, or when the image fails to load.
              Container(
                width: 52,
                height: 52,
                decoration: BoxDecoration(
                  color: c.accent,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: c.border, width: 3),
                ),
                clipBehavior: Clip.antiAlias,
                child: outlet.imageUrl == null
                    ? Icon(Icons.restaurant, color: c.onAccent)
                    : Image.network(
                        outlet.imageUrl!,
                        fit: BoxFit.cover,
                        errorBuilder: (_, _, _) =>
                            Icon(Icons.restaurant, color: c.onAccent),
                        loadingBuilder: (context, child, progress) =>
                            progress == null
                                ? child
                                : Icon(Icons.restaurant, color: c.onAccent),
                      ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // "{Restaurant Name} · {Locality}" — two branches of the
                    // same chain can no longer look identical in the list.
                    Text(outlet.displayName, style: textTheme.titleLarge),
                    const SizedBox(height: 2),
                    Text(
                      outlet.address,
                      style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    // Inline offer line, in the same box as the name so it
                    // reads as part of the restaurant rather than as an ad
                    // bolted onto the card. Only rendered when the outlet
                    // actually has an active offer.
                    if (outlet.hasOffers) ...[
                      const SizedBox(height: 8),
                      _OfferChip(outlet: outlet),
                    ],
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              _Pill(
                label: outlet.isOpen ? 'OPEN' : 'CLOSED',
                bg: outlet.isOpen ? c.accent : c.surfaceAlt,
                fg: outlet.isOpen ? c.onAccent : c.inkSoft,
              ),
              if (outlet.distanceKm != null) ...[
                const SizedBox(width: 8),
                _Pill(
                  label: '${outlet.distanceKm!.toStringAsFixed(1)} km',
                  bg: c.surfaceAlt,
                  fg: c.ink,
                  icon: Icons.directions_walk,
                ),
              ],
              const Spacer(),
              // Direct call (v2 §3.6). Rendered ONLY when the outlet actually
              // has a number — 5 of the 6 visible outlets in prod have none, so
              // a always-present button would be dead most of the time.
              if (outlet.canCall) ...[
                _CallButton(outlet: outlet),
                const SizedBox(width: 8),
              ],
              if (outlet.isOpen)
                Icon(Icons.arrow_forward, color: c.primary)
              else
                Text('Unavailable', style: textTheme.bodySmall),
            ],
          ),
        ],
      ),
    );
  }
}

/// "1 active order — tap to see your code" strip above the restaurant list.
///
/// Exists because the pickup code was previously reachable only via
/// Profile → Order History, three taps deep, which is exactly where a customer
/// standing at a counter will not think to look. Renders nothing when there is
/// no active order, so the screen is unchanged in the common case.
///
/// Fetches once on build rather than polling: the strip only needs to know an
/// active order EXISTS. Live status belongs on the pickup screen it opens.
class _ActiveOrderBanner extends StatefulWidget {
  const _ActiveOrderBanner();

  @override
  State<_ActiveOrderBanner> createState() => _ActiveOrderBannerState();
}

class _ActiveOrderBannerState extends State<_ActiveOrderBanner> {
  List<OrderHistoryEntry> _active = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final orders = await context.read<CustomerService>().orders(limit: 20);
      if (!mounted) return;
      setState(() => _active = orders.where((o) => o.isActive).toList());
    } catch (_) {
      // Silent: a failed lookup must never block restaurant discovery. The
      // strip simply does not appear.
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_active.isEmpty) return const SizedBox.shrink();
    final textTheme = Theme.of(context).textTheme;

    // ONE CARD PER ORDER, each showing its own outlet and its own code.
    //
    // The previous single banner showed only _active.first's code and counted
    // the rest ("3 orders in progress"), so with more than one order the other
    // codes were reachable only by navigating — which is precisely the moment
    // someone is standing at a counter being asked for one. Collapsing several
    // codes behind a count made the common multi-order case the slowest.
    // Height-capped and internally scrollable.
    //
    // This stack sits ABOVE the outlet list, outside its scroll view, so its
    // height is taken straight out of the list's. Ticket cards are much taller
    // than the single banner they replaced, and three concurrent orders were
    // enough to squeeze the restaurant list down to a few pixels — the orders
    // pushed the thing you came to the screen to do off the bottom. Capping it
    // at ~38% of the viewport keeps both usable no matter how many orders are
    // live; past the cap the stack scrolls on its own.
    final maxH = MediaQuery.sizeOf(context).height * 0.38;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: maxH),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (_active.length > 1) ...[
              Text('${_active.length} orders in progress',
                  style: textTheme.titleSmall),
              const SizedBox(height: 8),
            ],
            Flexible(
              child: ListView.separated(
                shrinkWrap: true,
                padding: EdgeInsets.zero,
                itemCount: _active.length,
                separatorBuilder: (_, _) => const SizedBox(height: 10),
                itemBuilder: (_, i) =>
                    _ActiveOrderCard(order: _active[i], onChanged: _load),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Direct-call action (v2 §3.6).
///
/// Uses the EXISTING outlets.phone_number rather than any new field. Its own
/// gesture sits above the card's, so tapping it dials instead of opening the
/// menu — the same pattern the offer chip already uses.
class _CallButton extends StatelessWidget {
  const _CallButton({required this.outlet});
  final Outlet outlet;

  Future<void> _call(BuildContext context) async {
    // tel: rather than a dialler package — no dependency, and it hands off to
    // whatever the customer's phone already uses.
    final uri = Uri(scheme: 'tel', path: outlet.phoneNumber);
    final ok = await launchUrl(uri);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not start a call to ${outlet.phoneNumber}')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return InkResponse(
      key: Key('call_outlet_${outlet.id}'),
      onTap: () => _call(context),
      radius: 22,
      child: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: c.accent,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: c.border, width: 2),
        ),
        child: Icon(Icons.call, size: 18, color: c.onAccent),
      ),
    );
  }
}

/// One in-progress order: outlet name and pickup code, both readable without
/// tapping anything. Tapping still opens the full pickup screen for live status.
class _ActiveOrderCard extends StatelessWidget {
  const _ActiveOrderCard({required this.order, required this.onChanged});

  final OrderHistoryEntry order;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    final t = TicketColors.of(context);
    final code = order.pickupCode;
    final hasCode = code != null && code.isNotEmpty;

    // v2 §2 ticket visual, matching the pickup screen this opens — the card and
    // the screen behind it are the same object, so they read as the same paper.
    return TicketCard(
      key: Key('active_order_${order.orderId}'),
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
      onTap: () async {
        await Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => PickupScreen(
            orderId: order.orderId,
            amount: order.totalAmount,
            fromHistory: true,
          ),
        ));
        // It may have been collected while they were in there — reload so a
        // finished order leaves the stack.
        onChanged();
      },
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  order.outletName ?? 'Your order',
                  style: TextStyle(
                    color: t.ink,
                    fontSize: 17,
                    fontWeight: FontWeight.w800,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Icon(Icons.chevron_right, color: t.inkSoft),
            ],
          ),
          const TicketDivider(verticalPadding: 10),
          if (hasCode)
            TicketRow(
              key: Key('active_order_code_${order.orderId}'),
              label: 'PICKUP CODE',
              value: code,
              emphasize: true,
            )
          else
            // No code yet (payment still settling). Says so rather than
            // showing a blank slot.
            const TicketRow(label: 'PICKUP CODE', value: 'Code soon'),
          const SizedBox(height: 6),
          TicketRow(label: 'STATUS', value: _statusLabel(order.status)),
        ],
      ),
    );
  }

  static String _statusLabel(String status) {
    switch (status.toUpperCase()) {
      case 'READY':
        return 'Ready to collect';
      case 'PREPARING':
        return 'Being prepared';
      case 'RECEIVED':
        return 'Order received';
      case 'PAID':
        return 'Payment confirmed';
      default:
        return 'In progress';
    }
  }
}

/// The inline "there's an offer here" line on an outlet card.
///
/// Tapping opens the full list (CareVo campaigns aimed at this restaurant plus
/// its own offers, combined). Its own gesture sits above the card's, so a tap
/// here opens offers instead of navigating into the menu — deliberate, since a
/// customer reaching for the offer text wants the offers.
class _OfferChip extends StatelessWidget {
  const _OfferChip({required this.outlet});
  final Outlet outlet;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    // offerCount includes the headline itself, so "+N more" counts the rest.
    final extra = outlet.offerCount - 1;

    return GestureDetector(
      key: const Key('outlet_offer_chip'),
      behavior: HitTestBehavior.opaque,
      onTap: () => showOffersSheet(context, outlet: outlet),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        decoration: BoxDecoration(
          color: c.accent,
          borderRadius: BorderRadius.circular(AppTheme.radius - 2),
          border: Border.all(color: c.border, width: 2),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.local_offer, size: 14, color: c.onAccent),
            const SizedBox(width: 6),
            Flexible(
              child: Text(
                outlet.offerText!,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: textTheme.labelLarge
                    ?.copyWith(color: c.onAccent, fontSize: 12),
              ),
            ),
            if (extra > 0) ...[
              const SizedBox(width: 6),
              Text(
                '+$extra more',
                style: textTheme.labelSmall?.copyWith(color: c.onAccent),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.label, required this.bg, required this.fg, this.icon});
  final String label;
  final Color bg;
  final Color fg;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: c.border, width: 2),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[Icon(icon, size: 13, color: fg), const SizedBox(width: 4)],
          Text(
            label,
            style: Theme.of(context)
                .textTheme
                .labelLarge
                ?.copyWith(color: fg, fontSize: 12),
          ),
        ],
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, this.onRetry});
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.sentiment_dissatisfied, size: 48, color: c.inkSoft),
            const SizedBox(height: 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            if (onRetry != null) ...[
              const SizedBox(height: 18),
              NeoButton(
                label: 'Try again',
                icon: Icons.refresh,
                expand: false,
                variant: NeoButtonVariant.neutral,
                onPressed: onRetry,
              ),
            ],
          ],
        ),
      ),
    );
  }
}
