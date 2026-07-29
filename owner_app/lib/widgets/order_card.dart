import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/order.dart';
import '../state/orders_state.dart';
import 'notify_section.dart';
import 'verify_box.dart';

/// A single order in the queue. Anchored by order_id (short form shown).
/// Tapping the header expands the detail IN PLACE — no navigation.
class OrderCard extends StatefulWidget {
  final Order order;

  const OrderCard({super.key, required this.order});

  @override
  State<OrderCard> createState() => _OrderCardState();
}

class _OrderCardState extends State<OrderCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final order = widget.order;
    final theme = Theme.of(context);
    final itemCount = order.items.fold<int>(0, (sum, i) => sum + i.quantity);

    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // --- header row (tap to expand) ---
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Text(
                              '#${order.shortId}',
                              style: theme.textTheme.titleMedium
                                  ?.copyWith(fontWeight: FontWeight.w700),
                            ),
                            const SizedBox(width: 8),
                            _StatusChip(
                                status: order.status, locked: order.isLocked),
                            const SizedBox(width: 6),
                            _PayChip(paid: order.isPaid),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '$itemCount item${itemCount == 1 ? '' : 's'}'
                          '  •  ₹${order.totalAmount.toStringAsFixed(0)}',
                          style: theme.textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                  Icon(_expanded ? Icons.expand_less : Icons.expand_more),
                ],
              ),
            ),
          ),

          // --- expanded detail ---
          AnimatedCrossFade(
            duration: const Duration(milliseconds: 180),
            crossFadeState: _expanded
                ? CrossFadeState.showSecond
                : CrossFadeState.showFirst,
            firstChild: const SizedBox(width: double.infinity),
            secondChild: _Detail(order: order),
          ),
        ],
      ),
    );
  }
}

class _Detail extends StatelessWidget {
  final Order order;

  const _Detail({required this.order});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: theme.colorScheme.outlineVariant)),
      ),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _PaymentAction(order: order),
          const Divider(height: 24),
          Text('Items', style: theme.textTheme.labelLarge),
          const SizedBox(height: 6),
          ...order.items.map(
            (item) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                children: [
                  Expanded(child: Text(item.name)),
                  Text('× ${item.quantity}',
                      style: theme.textTheme.bodyMedium),
                ],
              ),
            ),
          ),
          const Divider(height: 24),
          VerifyBox(orderId: order.orderId),
          const Divider(height: 24),
          NotifySection(order: order),
        ],
      ),
    );
  }
}

/// Front-and-center manual payment confirmation for the UPI-intent MVP.
/// Unpaid → a prominent "Mark Payment Received" button; paid → a confirmation.
class _PaymentAction extends StatefulWidget {
  final Order order;
  const _PaymentAction({required this.order});

  @override
  State<_PaymentAction> createState() => _PaymentActionState();
}

class _PaymentActionState extends State<_PaymentAction> {
  bool _busy = false;

  Future<void> _confirm() async {
    setState(() => _busy = true);
    final err = await context.read<OrdersState>().markPaid(widget.order.orderId);
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(err ?? 'Payment received — order confirmed.'),
      ));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (widget.order.isPaid) {
      return Row(
        children: [
          Icon(Icons.verified, size: 18, color: theme.colorScheme.primary),
          const SizedBox(width: 8),
          Text('Payment received',
              style: theme.textTheme.labelLarge
                  ?.copyWith(color: theme.colorScheme.primary)),
        ],
      );
    }
    return FilledButton.icon(
      onPressed: _busy ? null : _confirm,
      icon: _busy
          ? const SizedBox(
              height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
          : const Icon(Icons.payments_outlined),
      label: const Text('Mark Payment Received'),
    );
  }
}

/// Small PAID/UNPAID indicator in the card header.
class _PayChip extends StatelessWidget {
  final bool paid;
  const _PayChip({required this.paid});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = paid ? theme.colorScheme.primary : const Color(0xFFB26A00);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        paid ? 'PAID' : 'UNPAID',
        style: theme.textTheme.labelSmall
            ?.copyWith(color: color, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  final String status;
  final bool locked;

  const _StatusChip({required this.status, required this.locked});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final label = locked ? 'LOCKED' : status.toUpperCase();
    final color = locked
        ? theme.colorScheme.error
        : theme.colorScheme.primary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: theme.textTheme.labelSmall?.copyWith(
          color: color,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}
