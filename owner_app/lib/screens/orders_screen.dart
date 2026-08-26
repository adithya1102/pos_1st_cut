import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/orders_state.dart';
import '../widgets/order_card.dart';
import '../widgets/pickup_lookup_card.dart';

class OrdersScreen extends StatelessWidget {
  const OrdersScreen({super.key});

  @override
  Widget build(BuildContext context) {
    // The code lookup sits above the queue and outside its loading/error
    // branches: staff at the counter with a customer in front of them need it
    // even when the feed is mid-refresh or failed to load, and it does not
    // read the queue to do its job.
    return Column(
      children: [
        const PickupLookupCard(),
        Expanded(child: _Queue()),
      ],
    );
  }
}

class _Queue extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final state = context.watch<OrdersState>();

    if (state.loading && state.orders.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    if (state.error != null && state.orders.isEmpty) {
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
                onPressed: () => context.read<OrdersState>().load(),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () => context.read<OrdersState>().load(),
      child: state.orders.isEmpty
          ? ListView(
              children: const [
                SizedBox(height: 120),
                Center(child: Text('No active orders.')),
              ],
            )
          : ListView.builder(
              padding: const EdgeInsets.symmetric(vertical: 8),
              itemCount: state.orders.length,
              // Newest first — order preserved from the backend.
              itemBuilder: (context, i) => OrderCard(order: state.orders[i]),
            ),
    );
  }
}
