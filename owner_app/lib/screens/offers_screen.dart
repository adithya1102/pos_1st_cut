import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/offer.dart';
import '../state/offers_state.dart';
import 'offer_edit_screen.dart';

/// The Offers tab: this restaurant's own discounts, each with a live switch.
///
/// CareVo's own campaigns are NOT listed here even when they apply to this
/// restaurant — the owner did not create them, does not fund them, and cannot
/// switch them off, so showing them beside their own offers would imply
/// control they do not have.
class OffersScreen extends StatelessWidget {
  const OffersScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = context.watch<OffersState>();

    if (state.loading && state.offers.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    if (state.error != null && state.offers.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off, size: 40),
              const SizedBox(height: 12),
              Text(state.error!, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton.tonal(
                onPressed: () => context.read<OffersState>().load(),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () => context.read<OffersState>().load(),
      child: ListView(
        padding: const EdgeInsets.symmetric(vertical: 8),
        children: [
          if (state.offers.isEmpty)
            const _EmptyState()
          else
            ...state.offers.map((o) => _OfferCard(offer: o)),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(32, 48, 32, 32),
      child: Column(
        children: [
          Icon(Icons.local_offer_outlined,
              size: 44, color: Theme.of(context).colorScheme.outline),
          const SizedBox(height: 14),
          Text('No offers yet', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 6),
          Text(
            'An offer shows on your restaurant card in the CareVo app, so '
            'customers see it before they pick where to order.',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _OfferCard extends StatelessWidget {
  const _OfferCard({required this.offer});
  final Offer offer;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => _openEditor(context, offer),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 6, 12),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      offer.benefitText.isEmpty ? offer.label : offer.benefitText,
                      style: theme.textTheme.titleMedium,
                    ),
                    const SizedBox(height: 4),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        if (offer.code != null)
                          _Tag(text: offer.code!, mono: true)
                        else
                          const _Tag(text: 'Shown on your card'),
                        _Tag(
                          text: offer.redemptionCount == 1
                              ? '1 use'
                              : '${offer.redemptionCount} uses',
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              Column(
                children: [
                  Switch(
                    value: offer.isActive,
                    onChanged: (v) async {
                      final ok = await context
                          .read<OffersState>()
                          .toggleActive(offer.id, v);
                      if (!ok && context.mounted) {
                        ScaffoldMessenger.of(context)
                          ..hideCurrentSnackBar()
                          ..showSnackBar(const SnackBar(
                            content: Text('Could not update the offer.'),
                          ));
                      }
                    },
                  ),
                  Text(
                    offer.isActive ? 'Live' : 'Off',
                    style: theme.textTheme.labelSmall,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag({required this.text, this.mono = false});
  final String text;
  final bool mono;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        text,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              fontFamily: mono ? 'monospace' : null,
              color: scheme.onSurfaceVariant,
            ),
      ),
    );
  }
}

/// Opens the create (offer == null) / edit screen. OffersState reloads itself
/// on a successful save, so no extra refresh is needed here.
Future<void> openOfferEditor(BuildContext context, Offer? offer) =>
    _openEditor(context, offer);

Future<void> _openEditor(BuildContext context, Offer? offer) async {
  await Navigator.of(context).push<bool>(
    MaterialPageRoute(builder: (_) => OfferEditScreen(offer: offer)),
  );
}
