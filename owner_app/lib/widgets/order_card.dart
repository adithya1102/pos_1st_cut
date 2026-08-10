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
          ItemUnavailableChecklist(order: order),
          const Divider(height: 24),
          VerifyBox(orderId: order.orderId),
          const Divider(height: 24),
          NotifySection(order: order),
        ],
      ),
    );
  }
}

/// Payment state + the one human gate on an order.
///
/// There is no "Mark Payment Received" any more, and no "Accept" either. The
/// gateway webhook confirms payment and the order moves to RECEIVED on its own,
/// so staff are never the thing an order waits on. What they get instead is the
/// ability to pull an order they cannot make — an opt-OUT, not an opt-in.
class _PaymentAction extends StatefulWidget {
  final Order order;
  const _PaymentAction({required this.order});

  @override
  State<_PaymentAction> createState() => _PaymentActionState();
}

class _PaymentActionState extends State<_PaymentAction> {
  bool _busy = false;

  /// Mirrors the server's REJECTABLE_STATUSES. Once the food is made and
  /// waiting on the counter, "we can't do this one" is no longer true.
  static const _rejectable = {'PAID', 'RECEIVED', 'PREPARING'};

  bool get _canReject =>
      widget.order.isPaid && _rejectable.contains(widget.order.status.toUpperCase());

  Future<void> _reject() async {
    final controller = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Reject this order?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'The customer has already paid. They will be told the order was '
              'cancelled and that a refund is being arranged.',
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              maxLength: 300,
              decoration: const InputDecoration(
                labelText: 'Reason (optional, for your records)',
                hintText: 'Kitchen closed early',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Keep it')),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(c).colorScheme.error,
            ),
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Reject order'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _busy = true);
    final err = await context
        .read<OrdersState>()
        .reject(widget.order.orderId, reason: controller.text);
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(err ?? 'Order rejected. The customer has been notified.'),
      ));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final status = widget.order.status.toUpperCase();

    if (status == 'CANCELLED') {
      return Row(
        children: [
          Icon(Icons.cancel, size: 18, color: theme.colorScheme.error),
          const SizedBox(width: 8),
          Text('Rejected',
              style: theme.textTheme.labelLarge
                  ?.copyWith(color: theme.colorScheme.error)),
        ],
      );
    }

    if (!widget.order.isPaid) {
      // Unpaid orders are simply not actionable now: nothing here can make them
      // paid, and the gateway will say so when it happens.
      return Row(
        children: [
          Icon(Icons.hourglass_empty, size: 18, color: theme.colorScheme.outline),
          const SizedBox(width: 8),
          Expanded(
            child: Text('Awaiting payment — confirms automatically.',
                style: theme.textTheme.bodySmall),
          ),
        ],
      );
    }

    return Row(
      children: [
        Icon(Icons.verified, size: 18, color: theme.colorScheme.primary),
        const SizedBox(width: 8),
        Text('Paid',
            style: theme.textTheme.labelLarge
                ?.copyWith(color: theme.colorScheme.primary)),
        const Spacer(),
        if (_canReject)
          TextButton.icon(
            onPressed: _busy ? null : _reject,
            icon: _busy
                ? const SizedBox(
                    height: 16, width: 16,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : Icon(Icons.block, size: 18, color: theme.colorScheme.error),
            label: Text('Reject',
                style: TextStyle(color: theme.colorScheme.error)),
          )
        else
          Text('Too late to reject', style: theme.textTheme.bodySmall),
      ],
    );
  }
}

/// Tick several items, mark them all unavailable in one action.
///
/// The server writes one event and fires one push PER item, so the customer is
/// told exactly which dish is off. Does NOT change the order total — the paid
/// order stands, and the customer's remedy is a fresh order for replacements.
class ItemUnavailableChecklist extends StatefulWidget {
  final Order order;
  const ItemUnavailableChecklist({super.key, required this.order});

  @override
  State<ItemUnavailableChecklist> createState() => _ItemUnavailableChecklistState();
}

class _ItemUnavailableChecklistState extends State<ItemUnavailableChecklist> {
  final Set<String> _selected = {};
  bool _busy = false;

  Future<void> _submit() async {
    if (_selected.isEmpty) return;
    final n = _selected.length;
    setState(() => _busy = true);
    final err = await context
        .read<OrdersState>()
        .markItemsUnavailable(widget.order.orderId, _selected.toList());
    if (!mounted) return;
    setState(() {
      _busy = false;
      if (err == null) _selected.clear();
    });
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(err ??
            (n == 1
                ? 'Item marked unavailable. Customer notified.'
                : '$n items marked unavailable. Customer notified for each.')),
      ));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final items = widget.order.items;
    if (items.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("Can't make something?", style: theme.textTheme.titleSmall),
        const SizedBox(height: 2),
        Text(
          'Tick the items you cannot prepare. The customer is told which ones, '
          'and can reorder separately.',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: 4),
        ...items.map((it) => CheckboxListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: _selected.contains(it.id),
              onChanged: _busy
                  ? null
                  : (v) => setState(() {
                        if (v == true) {
                          _selected.add(it.id);
                        } else {
                          _selected.remove(it.id);
                        }
                      }),
              title: Text('${it.quantity}x  ${it.name}'),
            )),
        Align(
          alignment: Alignment.centerRight,
          child: FilledButton.tonalIcon(
            onPressed: (_busy || _selected.isEmpty) ? null : _submit,
            icon: _busy
                ? const SizedBox(
                    height: 16, width: 16,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.remove_shopping_cart_outlined, size: 18),
            label: Text(_selected.isEmpty
                ? 'Mark unavailable'
                : 'Mark ${_selected.length} unavailable'),
          ),
        ),
      ],
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
