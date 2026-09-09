import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/order.dart';
import '../services/order_service.dart';
import '../state/orders_state.dart';

/// Three staff notifications for an order. "Ready now" and "Delayed 10 min"
/// fire immediately. "Item unavailable" reveals an inline picker of THIS
/// order's items and only sends once a specific item is chosen.
class NotifySection extends StatefulWidget {
  final Order order;

  const NotifySection({super.key, required this.order});

  @override
  State<NotifySection> createState() => _NotifySectionState();
}

class _NotifySectionState extends State<NotifySection> {
  bool _busy = false;
  bool _showItemPicker = false;
  String? _confirmation;

  Future<void> _send(NotifyType type, {String? itemId}) async {
    setState(() {
      _busy = true;
      _confirmation = null;
    });
    try {
      await context
          .read<OrdersState>()
          .notify(widget.order.orderId, type, itemId: itemId);
      if (!mounted) return;
      setState(() {
        _showItemPicker = false;
        _confirmation = _confirmationText(type);
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _confirmation = 'Could not send. Try again.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _confirmationText(NotifyType type) {
    switch (type) {
      case NotifyType.readyNow:
        return 'Sent: order is ready now.';
      case NotifyType.delayed10:
        return 'Sent: delayed by 10 minutes.';
      case NotifyType.itemUnavailable:
        return 'Sent: item marked unavailable.';
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Notify', style: theme.textTheme.labelLarge),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            FilledButton.tonalIcon(
              onPressed: _busy ? null : () => _send(NotifyType.readyNow),
              icon: const Icon(Icons.check, size: 18),
              label: const Text('Ready now'),
            ),
            FilledButton.tonalIcon(
              onPressed: _busy ? null : () => _send(NotifyType.delayed10),
              icon: const Icon(Icons.timer_outlined, size: 18),
              label: const Text('Delayed 10 min'),
            ),
            OutlinedButton.icon(
              onPressed: _busy
                  ? null
                  : () => setState(
                      () => _showItemPicker = !_showItemPicker),
              icon: Icon(
                _showItemPicker ? Icons.close : Icons.no_meals_outlined,
                size: 18,
              ),
              label: const Text('Item unavailable'),
            ),
          ],
        ),

        // Inline item picker — only THIS order's items.
        if (_showItemPicker) ...[
          const SizedBox(height: 10),
          Text(
            'Which item is unavailable?',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: widget.order.items
                .map(
                  (item) => ActionChip(
                    label: Text(item.name),
                    onPressed: _busy
                        ? null
                        : () => _send(
                              NotifyType.itemUnavailable,
                              itemId: item.id,
                            ),
                  ),
                )
                .toList(),
          ),
        ],

        if (_confirmation != null) ...[
          const SizedBox(height: 10),
          Row(
            children: [
              Icon(Icons.check_circle_outline,
                  size: 18, color: theme.colorScheme.primary),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  _confirmation!,
                  style: TextStyle(color: theme.colorScheme.primary),
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }
}
