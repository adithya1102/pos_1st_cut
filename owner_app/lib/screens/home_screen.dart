import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/menu_item.dart';
import '../models/outlet.dart';
import '../state/auth_state.dart';
import '../state/home_state.dart';
import '../state/orders_state.dart';
import '../widgets/dish_row.dart';
import 'dish_edit_screen.dart';
import 'orders_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _index = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<HomeState>().load();
      context.read<OrdersState>().load();
    });
  }

  @override
  Widget build(BuildContext context) {
    final pages = const [_DishesTab(), OrdersScreen()];

    return Scaffold(
      appBar: AppBar(
        title: Text(_index == 0 ? 'Menu & Outlet' : 'Orders'),
        actions: [
          if (_index == 0) const _OutletVisibilityToggle(),
          IconButton(
            tooltip: 'Log out',
            icon: const Icon(Icons.logout),
            onPressed: () => context.read<AuthState>().logout(),
          ),
        ],
      ),
      body: IndexedStack(index: _index, children: pages),
      floatingActionButton: _index == 0
          ? FloatingActionButton.extended(
              onPressed: () => _openDishEditor(context, null),
              icon: const Icon(Icons.add),
              label: const Text('Add dish'),
            )
          : null,
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.restaurant_menu_outlined),
            selectedIcon: Icon(Icons.restaurant_menu),
            label: 'Menu',
          ),
          NavigationDestination(
            icon: Icon(Icons.receipt_long_outlined),
            selectedIcon: Icon(Icons.receipt_long),
            label: 'Orders',
          ),
        ],
      ),
    );
  }
}

/// Top-right outlet visibility switch, bound to GET /pos/outlet.is_visible.
class _OutletVisibilityToggle extends StatelessWidget {
  const _OutletVisibilityToggle();

  @override
  Widget build(BuildContext context) {
    final Outlet? outlet = context.select<HomeState, Outlet?>((s) => s.outlet);
    if (outlet == null) {
      return const SizedBox.shrink();
    }
    return Row(
      children: [
        Text(
          outlet.isVisible ? 'Open' : 'Hidden',
          style: Theme.of(context).textTheme.labelMedium,
        ),
        Switch(
          value: outlet.isVisible,
          onChanged: (v) async {
            final ok = await context.read<HomeState>().toggleVisibility(v);
            if (!ok && context.mounted) {
              _showError(context, 'Could not update outlet visibility.');
            }
          },
        ),
      ],
    );
  }
}

class _DishesTab extends StatelessWidget {
  const _DishesTab();

  @override
  Widget build(BuildContext context) {
    final state = context.watch<HomeState>();

    if (state.loading && state.items.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    if (state.error != null && state.items.isEmpty) {
      return _ErrorRetry(
        message: state.error!,
        onRetry: () => context.read<HomeState>().load(),
      );
    }

    return RefreshIndicator(
      onRefresh: () => context.read<HomeState>().load(),
      child: ListView(
        padding: const EdgeInsets.symmetric(vertical: 8),
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: Text(
              'Dishes',
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
          if (state.items.isEmpty)
            const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: Text('No dishes found.')),
            )
          else
            // FLAT list — deliberately no categories.
            ...state.items.map(
              (item) => DishRow(
                item: item,
                onTap: () => _openDishEditor(context, item),
                onChanged: (next) async {
                  final ok = await context
                      .read<HomeState>()
                      .toggleItemAvailability(item.id, next);
                  if (!ok && context.mounted) {
                    _showError(context, 'Could not update "${item.name}".');
                  }
                },
              ),
            ),
        ],
      ),
    );
  }
}

class _ErrorRetry extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _ErrorRetry({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off, size: 40),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton.tonal(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

void _showError(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}

/// Opens the add (item == null) / edit dish screen. HomeState reloads itself
/// on a successful save, so no extra refresh is needed here.
Future<void> _openDishEditor(BuildContext context, MenuItem? item) async {
  await Navigator.of(context).push<bool>(
    MaterialPageRoute(builder: (_) => DishEditScreen(item: item)),
  );
}
