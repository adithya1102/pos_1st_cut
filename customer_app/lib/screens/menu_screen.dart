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
import '../widgets/theme_toggle_button.dart';
import 'cart_screen.dart';
import 'dish_detail_screen.dart';

/// Step 5: menu browse with horizontal category chips + item list.
class MenuScreen extends StatefulWidget {
  const MenuScreen({super.key, required this.outlet});
  final Outlet outlet;

  @override
  State<MenuScreen> createState() => _MenuScreenState();
}

class _MenuScreenState extends State<MenuScreen> {
  late Future<MenuResponse> _future;
  int _selectedCategory = 0;

  @override
  void initState() {
    super.initState();
    // Bind the cart to this outlet (clears cart if switching restaurants).
    context.read<CartState>().setOutlet(widget.outlet);
    _future = _load();
  }

  Future<MenuResponse> _load() =>
      context.read<CatalogService>().fetchMenu(widget.outlet.id);

  void _retry() => setState(() => _future = _load());

  void _openItem(MenuItem item) {
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
        actions: const [
          Padding(padding: EdgeInsets.only(right: 16), child: ThemeToggleButton()),
        ],
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
            final safeIndex = _selectedCategory.clamp(0, categories.length - 1);
            final activeCategory = categories[safeIndex];

            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  height: 58,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    itemCount: categories.length,
                    separatorBuilder: (_, _) => const SizedBox(width: 10),
                    itemBuilder: (_, i) => NeoChip(
                      label: categories[i].name,
                      selected: i == safeIndex,
                      onTap: () => setState(() => _selectedCategory = i),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 4),
                  child: Text(activeCategory.name, style: textTheme.headlineSmall),
                ),
                Expanded(
                  child: activeCategory.items.isEmpty
                      ? Center(
                          child: Text('No items in this section.',
                              style: textTheme.bodyLarge),
                        )
                      : ListView.separated(
                          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                          itemCount: activeCategory.items.length,
                          separatorBuilder: (_, _) => const SizedBox(height: 14),
                          itemBuilder: (_, i) => MenuItemCard(
                            item: activeCategory.items[i],
                            onTap: () => _openItem(activeCategory.items[i]),
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
