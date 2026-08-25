import 'package:flutter/material.dart';

import '../screens/pickup_screen.dart';
import '../services/customer_service.dart';
import '../theme/widgets/ticket_card.dart';

/// One in-progress order: outlet name and pickup code, both readable without
/// tapping anything. Tapping opens the full pickup screen for live status.
///
/// Shared by Home and by the restaurant list. It lived privately inside the
/// outlets screen until Home needed the same thing; copying it would have meant
/// two definitions of what an active order looks like, free to drift, on the
/// two screens most likely to be compared side by side.
///
/// The v2 §2 ticket visual matches the pickup screen it opens, so the card and
/// the screen behind it read as the same piece of paper.
class ActiveOrderCard extends StatelessWidget {
  const ActiveOrderCard({
    super.key,
    required this.order,
    required this.onChanged,
  });

  final OrderHistoryEntry order;

  /// Called after returning from the pickup screen — the order may have been
  /// collected in there, in which case it should leave the caller's list.
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    final t = TicketColors.of(context);
    final code = order.pickupCode;
    final hasCode = code != null && code.isNotEmpty;

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
          TicketRow(label: 'STATUS', value: statusLabel(order.status)),
        ],
      ),
    );
  }

  /// Customer-facing wording for a raw order status.
  static String statusLabel(String status) {
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
