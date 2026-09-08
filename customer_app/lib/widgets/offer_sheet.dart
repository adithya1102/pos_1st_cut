import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/offer.dart';
import '../models/outlet.dart';
import '../services/api_client.dart';
import '../services/catalog_service.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';

/// Bottom sheet listing every offer usable at [outlet].
///
/// CareVo campaigns and the restaurant's own offers are shown in ONE list, not
/// two sections: the customer is choosing money off their food, and who funds
/// it is a badge, not a category. The list is fetched fresh each time it opens
/// rather than cached, because an owner can switch an offer off at any moment
/// and a stale sheet would promise something checkout then refuses.
Future<void> showOffersSheet(
  BuildContext context, {
  required Outlet outlet,
  double? subtotal,
  ValueChanged<Offer>? onApply,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (_) => _OffersSheet(
      outlet: outlet,
      subtotal: subtotal,
      onApply: onApply,
    ),
  );
}

class _OffersSheet extends StatefulWidget {
  const _OffersSheet({required this.outlet, this.subtotal, this.onApply});

  final Outlet outlet;

  /// When set, each offer shows what it would take off this basket and gains
  /// an "Use this" action. Null on the discovery screen, where there is no
  /// basket yet and the sheet is purely informational.
  final double? subtotal;
  final ValueChanged<Offer>? onApply;

  @override
  State<_OffersSheet> createState() => _OffersSheetState();
}

class _OffersSheetState extends State<_OffersSheet> {
  late Future<List<Offer>> _future;

  @override
  void initState() {
    super.initState();
    _future = context.read<CatalogService>().fetchOffers(widget.outlet.id);
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return DraggableScrollableSheet(
      initialChildSize: 0.55,
      minChildSize: 0.3,
      maxChildSize: 0.9,
      expand: false,
      builder: (context, scrollController) => Container(
        decoration: BoxDecoration(
          color: c.surface,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
          border: Border.all(color: c.border, width: AppTheme.borderWidth),
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(
          children: [
            const SizedBox(height: 10),
            Container(
              width: 44,
              height: 5,
              decoration: BoxDecoration(
                color: c.inkSoft,
                borderRadius: BorderRadius.circular(3),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 14, 20, 6),
              child: Row(
                children: [
                  Icon(Icons.local_offer, color: c.primary),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Offers', style: textTheme.headlineSmall),
                        Text(
                          'at ${widget.outlet.name}',
                          style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: FutureBuilder<List<Offer>>(
                future: _future,
                builder: (context, snap) {
                  if (snap.connectionState == ConnectionState.waiting) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snap.hasError) {
                    return _SheetMessage(
                      text: snap.error is ApiException
                          ? (snap.error as ApiException).message
                          : 'Could not load offers.',
                    );
                  }
                  final offers = snap.data ?? const <Offer>[];
                  if (offers.isEmpty) {
                    return const _SheetMessage(
                      text: 'No offers here right now.',
                    );
                  }
                  return ListView.separated(
                    controller: scrollController,
                    padding: const EdgeInsets.fromLTRB(20, 10, 20, 28),
                    itemCount: offers.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 12),
                    itemBuilder: (_, i) => _OfferTile(
                      offer: offers[i],
                      subtotal: widget.subtotal,
                      onApply: widget.onApply == null
                          ? null
                          : () {
                              Navigator.of(context).pop();
                              widget.onApply!(offers[i]);
                            },
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

class _OfferTile extends StatelessWidget {
  const _OfferTile({required this.offer, this.subtotal, this.onApply});

  final Offer offer;
  final double? subtotal;
  final VoidCallback? onApply;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    // Only computed when there is a basket to compute against.
    final saving = subtotal == null ? null : offer.previewSaving(subtotal!);
    final short = subtotal != null &&
        offer.minOrderValue != null &&
        subtotal! < offer.minOrderValue!;

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: c.surfaceAlt,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        border: Border.all(color: c.border, width: 2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(offer.benefitText, style: textTheme.titleMedium),
              ),
              // Who is behind it. A badge, never a filter — see the sheet doc.
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: offer.isCareVo ? c.primary : c.accent,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: c.border, width: 2),
                ),
                child: Text(
                  offer.isCareVo ? 'CareVo' : 'Restaurant',
                  style: textTheme.labelSmall?.copyWith(
                    color: offer.isCareVo ? c.onPrimary : c.onAccent,
                  ),
                ),
              ),
            ],
          ),
          if (offer.label.isNotEmpty && offer.label != offer.benefitText) ...[
            const SizedBox(height: 4),
            Text(offer.label,
                style: textTheme.bodySmall?.copyWith(color: c.inkSoft)),
          ],
          if (offer.creatorName != null) ...[
            const SizedBox(height: 4),
            Text('with ${offer.creatorName}',
                style: textTheme.bodySmall?.copyWith(color: c.inkSoft)),
          ],
          if (offer.code != null) ...[
            const SizedBox(height: 8),
            Row(
              children: [
                Icon(Icons.confirmation_number_outlined, size: 15, color: c.inkSoft),
                const SizedBox(width: 6),
                Text(offer.code!,
                    style: textTheme.labelLarge?.copyWith(letterSpacing: 1)),
              ],
            ),
          ],
          if (short) ...[
            const SizedBox(height: 8),
            Text(
              'Add a little more to your order to use this.',
              style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
            ),
          ],
          if (onApply != null) ...[
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                // Disabled rather than hidden when the basket is short: the
                // offer stays visible as something to reach for.
                onPressed: short ? null : onApply,
                child: Text(
                  saving != null && !short
                      // Preview only. The server recomputes at checkout.
                      ? 'Use this — save ₹${saving.toStringAsFixed(saving == saving.roundToDouble() ? 0 : 2)}'
                      : 'Use this',
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _SheetMessage extends StatelessWidget {
  const _SheetMessage({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Text(
          text,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.titleSmall,
        ),
      ),
    );
  }
}
