import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/customer_service.dart';

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
      appBar: AppBar(title: const Text('Order history')),
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
                    : ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                        itemCount: orders.length,
                        separatorBuilder: (_, _) => const SizedBox(height: 12),
                        itemBuilder: (_, i) => _OrderCard(order: orders[i]),
                      ),
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
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    order.outletName ?? 'Outlet',
                    style: theme.textTheme.titleSmall,
                  ),
                ),
                Text(
                  '₹${order.totalAmount.toStringAsFixed(2)}',
                  style: theme.textTheme.titleSmall,
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(_date(order.createdAt), style: theme.textTheme.bodySmall),
            const SizedBox(height: 8),
            Text(order.itemSummary, style: theme.textTheme.bodyMedium),
            // Only shown when a coupon actually reduced this order, so a normal
            // order stays uncluttered.
            if (order.discountAmount > 0) ...[
              const SizedBox(height: 6),
              Text(
                'Coupon saved ₹${order.discountAmount.toStringAsFixed(2)}',
                style: theme.textTheme.bodySmall,
              ),
            ],
            const SizedBox(height: 10),
            Row(
              children: [
                _Chip(label: order.status),
                const SizedBox(width: 8),
                if (order.isPaid) const _Chip(label: 'PAID'),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(label, style: const TextStyle(fontSize: 11)),
    );
  }
}
