import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/customer_service.dart';
import '../widgets/account_button.dart';
import '../theme/widgets/ticket_card.dart';
import 'pickup_screen.dart';

/// The signed-in customer's past orders.
///
/// Backed by `GET /customer/orders`, which scopes to the customer resolved from
/// the bearer token — there is no id parameter, so this can only ever show the
/// caller's own orders.
class OrderHistoryScreen extends StatefulWidget {
  const OrderHistoryScreen({super.key});

  @override
  State<OrderHistoryScreen> createState() => _OrderHistoryScreenState();
}

class _OrderHistoryScreenState extends State<OrderHistoryScreen> {
  List<OrderHistoryEntry>? _orders;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final orders = await context.read<CustomerService>().orders();
      if (!mounted) return;
      setState(() => _orders = orders);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _orders = const [];
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final orders = _orders;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Order history'),
        actions: careVoActions(account: false),
      ),
      body: SafeArea(
        child: orders == null
            ? const Center(child: CircularProgressIndicator())
            : RefreshIndicator(
                onRefresh: _load,
                child: orders.isEmpty
                    ? ListView(
                        // A ListView (not a bare Center) so pull-to-refresh
                        // still works when the list is empty.
                        children: [
                          const SizedBox(height: 120),
                          Center(
                            child: Text(
                              _error ?? 'No orders yet.',
                              style: theme.textTheme.bodyMedium,
                              textAlign: TextAlign.center,
                            ),
                          ),
                        ],
                      )
                    : Builder(builder: (context) {
                        // Active orders float to the top and stay reachable —
                        // they are the ones with a pickup code still to show.
                        final active =
                            orders.where((o) => o.isActive).toList();
                        final past =
                            orders.where((o) => !o.isActive).toList();
                        return ListView(
                          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                          children: [
                            if (active.isNotEmpty) ...[
                              Text('In progress',
                                  style: theme.textTheme.titleMedium),
                              const SizedBox(height: 8),
                              ...active.map((o) => Padding(
                                    padding: const EdgeInsets.only(bottom: 12),
                                    child: _OrderCard(order: o),
                                  )),
                              const SizedBox(height: 12),
                            ],
                            if (past.isNotEmpty) ...[
                              Text(active.isEmpty ? 'Orders' : 'Past orders',
                                  style: theme.textTheme.titleMedium),
                              const SizedBox(height: 8),
                              ...past.map((o) => Padding(
                                    padding: const EdgeInsets.only(bottom: 12),
                                    child: _OrderCard(order: o),
                                  )),
                            ],
                          ],
                        );
                      }),
              ),
      ),
    );
  }
}

class _OrderCard extends StatelessWidget {
  const _OrderCard({required this.order});
  final OrderHistoryEntry order;

  String _date(DateTime? d) {
    if (d == null) return '—';
    final local = d.toLocal();
    final dd = local.day.toString().padLeft(2, '0');
    final mm = local.month.toString().padLeft(2, '0');
    final hh = local.hour.toString().padLeft(2, '0');
    final mi = local.minute.toString().padLeft(2, '0');
    return '$dd/$mm/${local.year} $hh:$mi';
  }

  @override
  Widget build(BuildContext context) {
    final t = TicketColors.of(context);
    final collected = !order.isActive;

    // v2 §2 — history is the same paper as the live ticket, just stamped.
    // Using the ticket visual here (rather than a plain Card) is what makes an
    // order feel like one continuous object from payment through collection.
    return TicketCard(
      key: Key('history_order_${order.orderId}'),
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      // Only in-progress orders open the live screen. A completed order has no
      // code left to show and nothing to poll, so tapping it would open a
      // screen that just says "picked up" — worse than not being tappable.
      onTap: order.isActive
          ? () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => PickupScreen(
                  orderId: order.orderId,
                  amount: order.totalAmount,
                  // Gives it a back button and stops "Order more" nuking the stack.
                  fromHistory: true,
                ),
              ))
          : null,
      // Collected orders carry the stamp, so the list reads at a glance without
      // needing to parse a status chip on every row.
      stampText: collected ? 'COLLECTED' : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  order.outletName ?? 'Outlet',
                  style: TextStyle(
                    color: t.ink,
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Text(
                '₹${order.totalAmount.toStringAsFixed(2)}',
                style: TextStyle(
                    color: t.ink, fontSize: 16, fontWeight: FontWeight.w800),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(_date(order.createdAt),
              style: TextStyle(color: t.inkSoft, fontSize: 12)),
          const TicketDivider(verticalPadding: 10),
          Text(order.itemSummary,
              style: TextStyle(color: t.ink, fontSize: 13)),
          if (order.discountAmount > 0) ...[
            const SizedBox(height: 6),
            Text(
              'Coupon saved ₹${order.discountAmount.toStringAsFixed(2)}',
              style: TextStyle(color: t.inkSoft, fontSize: 12),
            ),
          ],
          const TicketDivider(verticalPadding: 10),
          TicketRow(label: 'STATUS', value: order.status),
          if (order.pickupCode != null) ...[
            const SizedBox(height: 6),
            TicketRow(
              label: 'PICKUP CODE',
              value: order.pickupCode!,
              emphasize: order.isActive,
              // A collected order keeps its code as a record, struck through
              // because it can no longer be used.
              strikethrough: collected,
            ),
          ],
          if (order.isActive) ...[
            const SizedBox(height: 10),
            Row(
              children: [
                Icon(Icons.touch_app_outlined, size: 14, color: t.inkSoft),
                const SizedBox(width: 6),
                Text('Tap to track this order',
                    style: TextStyle(color: t.inkSoft, fontSize: 12)),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
