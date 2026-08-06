import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/menu.dart';
import '../models/outlet.dart';
import '../services/api_client.dart';
import '../services/catalog_service.dart';
import '../state/cart_state.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_chip.dart';
import '../widgets/cart_bar.dart';
import '../widgets/menu_item_card.dart';
import 'cart_screen.dart';
import 'dish_detail_screen.dart';
import '../widgets/account_button.dart';

/// Step 5: menu browse with horizontal category chips + item list.
class MenuScreen extends StatefulWidget {
  const MenuScreen({super.key, required this.outlet});
  final Outlet outlet;

  @override
  State<MenuScreen> createState() => _MenuScreenState();
}

/// Veg/non-veg filter applied within the selected category.
enum VegFilter {
  all,
  veg,
  nonVeg;

  bool matches(bool isVeg) => switch (this) {
        VegFilter.all => true,
        VegFilter.veg => isVeg,
        VegFilter.nonVeg => !isVeg,
      };

  String get label => switch (this) {
        VegFilter.all => 'All',
        VegFilter.veg => 'Veg',
        VegFilter.nonVeg => 'Non-veg',
      };
}

class _MenuScreenState extends State<MenuScreen> {
  late Future<MenuResponse> _future;
  // -1 = the cumulative "All" view; 0..n-1 = a specific category.
  int _selectedCategory = -1;
  VegFilter _vegFilter = VegFilter.all;

  @override
  void initState() {
    super.initState();
    // Bind only when it costs nothing. Browsing a different restaurant must NOT
    // silently discard a basket — if it would, the cart stays bound to the old
    // outlet and _confirmOutletSwitch() asks first, on the add-to-cart attempt.
    context.read<CartState>().bindOutletIfSafe(widget.outlet);
    _future = _load();
  }

  /// Gate for adding an item while the cart belongs to another restaurant.
  /// Returns true when the caller may proceed with the add.
  Future<bool> _confirmOutletSwitch() async {
    final cart = context.read<CartState>();
    if (!cart.wouldDiscardCart(widget.outlet)) {
      // Same outlet (or empty cart): bind and add with no interruption.
      cart.bindOutletIfSafe(widget.outlet);
      return true;
    }

    final previous = cart.outlet?.name ?? 'another restaurant';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Start a new order?'),
        content: Text(
          'Your cart has items from $previous. Adding this will empty that '
          'cart and start a new one at ${widget.outlet.name}.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('Keep my cart'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Start new order'),
          ),
        ],
      ),
    );
    if (confirmed != true) return false;
    // setOutlet clears, which is exactly what the customer just agreed to.
    cart.setOutlet(widget.outlet);
    return true;
  }

  Future<MenuResponse> _load() =>
      context.read<CatalogService>().fetchMenu(widget.outlet.id);

  void _retry() => setState(() => _future = _load());

  Future<void> _openItem(MenuItem item) async {
    // Confirm the outlet switch BEFORE the dish opens, so the cart is already
    // bound to this restaurant by the time "Add to cart" is tapped.
    if (!await _confirmOutletSwitch()) return;
    if (!mounted) return;
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => DishDetailScreen(item: item)),
    );
  }

  void _openCart() {
    Navigator.of(context)
        .push(MaterialPageRoute(builder: (_) => const CartScreen()));
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.outlet.name),
        actions: careVoActions(),
      ),
      bottomNavigationBar: CartBar(onView: _openCart),
      body: SafeArea(
        bottom: false,
        child: FutureBuilder<MenuResponse>(
          future: _future,
          builder: (context, snap) {
            if (snap.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              return _MenuError(
                message: snap.error is ApiException
                    ? (snap.error as ApiException).message
                    : 'Could not load the menu.',
                onRetry: _retry,
              );
            }
            final menu = snap.data!;
            final categories = menu.categories;
            if (categories.isEmpty) {
              return const _MenuError(message: 'This menu is empty right now.');
            }
            final isAll =
                _selectedCategory < 0 || _selectedCategory >= categories.length;
            final sourceItems = isAll
                ? categories.expand((cat) => cat.items).toList()
                : categories[_selectedCategory].items;
            final visibleItems = sourceItems
                .where((it) => _vegFilter.matches(it.isVeg))
                .toList();
            final sectionTitle = isAll ? 'All items' : categories[_selectedCategory].name;

            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  height: 58,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    // +1 for the leading cumulative "All" chip.
                    itemCount: categories.length + 1,
                    separatorBuilder: (_, _) => const SizedBox(width: 10),
                    itemBuilder: (_, i) {
                      if (i == 0) {
                        return NeoChip(
                          label: 'All',
                          selected: isAll,
                          onTap: () => setState(() => _selectedCategory = -1),
                        );
                      }
                      final ci = i - 1;
                      return NeoChip(
                        label: categories[ci].name,
                        selected: !isAll && ci == _selectedCategory,
                        onTap: () => setState(() => _selectedCategory = ci),
                      );
                    },
                  ),
                ),
                SizedBox(
                  height: 50,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    children: [
                      for (final f in VegFilter.values) ...[
                        NeoChip(
                          label: f.label,
                          selected: f == _vegFilter,
                          onTap: () => setState(() => _vegFilter = f),
                        ),
                        const SizedBox(width: 10),
                      ],
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 4),
                  child: Text(sectionTitle, style: textTheme.headlineSmall),
                ),
                Expanded(
                  child: visibleItems.isEmpty
                      ? Center(
                          child: Text(
                              _vegFilter == VegFilter.all
                                  ? 'No items in this section.'
                                  : 'No ${_vegFilter.label.toLowerCase()} items here.',
                              style: textTheme.bodyLarge),
                        )
                      : ListView.separated(
                          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                          itemCount: visibleItems.length,
                          separatorBuilder: (_, _) => const SizedBox(height: 14),
                          itemBuilder: (_, i) => MenuItemCard(
                            item: visibleItems[i],
                            onTap: () => _openItem(visibleItems[i]),
                          ),
                        ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _MenuError extends StatelessWidget {
  const _MenuError({required this.message, this.onRetry});
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.restaurant_menu, size: 48),
            const SizedBox(height: 12),
            Text(message,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium),
            if (onRetry != null) ...[
              const SizedBox(height: 18),
              NeoButton(
                label: 'Try again',
                icon: Icons.refresh,
                expand: false,
                variant: NeoButtonVariant.neutral,
                onPressed: onRetry,
              ),
            ],
          ],
        ),
      ),
    );
  }
}
