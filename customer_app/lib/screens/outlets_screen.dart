import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/outlet.dart';
import '../services/api_client.dart';
import '../services/catalog_service.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import 'menu_screen.dart';
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
                  final outlets = snap.data ?? [];
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
                    Text(outlet.name, style: textTheme.titleLarge),
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
