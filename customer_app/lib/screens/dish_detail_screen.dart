import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/cart_item.dart';
import '../models/menu.dart';
import '../state/cart_state.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/neo_text_field.dart';
import '../widgets/price_text.dart';
import '../widgets/veg_badge.dart';
import '../widgets/account_button.dart';

/// Step 6: dish detail + customization (modifiers, quantity, notes).
class DishDetailScreen extends StatefulWidget {
  const DishDetailScreen({super.key, required this.item});
  final MenuItem item;

  @override
  State<DishDetailScreen> createState() => _DishDetailScreenState();
}

class _DishDetailScreenState extends State<DishDetailScreen> {
  int _quantity = 1;
  final _notesController = TextEditingController();

  /// group name -> selected option names.
  final Map<String, Set<String>> _selections = {};

  @override
  void initState() {
    super.initState();
    // Pre-select the first option of any required single-select group.
    for (final group in widget.item.customizations) {
      if (group.required && !group.multiSelect && group.options.isNotEmpty) {
        _selections[group.name] = {group.options.first.name};
      }
    }
  }

  @override
  void dispose() {
    _notesController.dispose();
    super.dispose();
  }

  void _toggle(CustomizationGroup group, CustomizationOption option) {
    final current = _selections.putIfAbsent(group.name, () => <String>{});
    setState(() {
      if (group.multiSelect) {
        if (current.contains(option.name)) {
          current.remove(option.name);
        } else {
          current.add(option.name);
        }
      } else {
        _selections[group.name] = {option.name};
      }
    });
  }

  List<SelectedOption> _buildSelectedOptions() {
    final result = <SelectedOption>[];
    for (final group in widget.item.customizations) {
      final chosen = _selections[group.name] ?? const {};
      for (final option in group.options) {
        if (chosen.contains(option.name)) {
          result.add(SelectedOption(
            groupName: group.name,
            optionName: option.name,
            priceDelta: option.priceDelta,
          ));
        }
      }
    }
    return result;
  }

  bool get _requiredSatisfied {
    for (final group in widget.item.customizations) {
      if (group.required && (_selections[group.name]?.isEmpty ?? true)) {
        return false;
      }
    }
    return true;
  }

  double get _unitPrice =>
      widget.item.basePrice +
      _buildSelectedOptions().fold(0.0, (sum, o) => sum + o.priceDelta);

  void _addToCart() {
    context.read<CartState>().addItem(
          widget.item,
          quantity: _quantity,
          options: _buildSelectedOptions(),
          notes: _notesController.text,
        );
    Navigator.of(context).pop();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('${widget.item.name} added to cart')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final item = widget.item;
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Customise'),
        actions: careVoActions(),
      ),
      bottomNavigationBar: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
          child: NeoButton(
            label: _requiredSatisfied
                ? 'Add $_quantity  •  ${formatRupees(_unitPrice * _quantity)}'
                : 'Select required options',
            icon: Icons.add_shopping_cart,
            onPressed: _requiredSatisfied ? _addToCart : null,
          ),
        ),
      ),
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          children: [
            Row(
              children: [
                VegBadge(isVeg: item.isVeg, size: 20),
                const SizedBox(width: 10),
                Expanded(child: Text(item.name, style: textTheme.headlineSmall)),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                PriceText(item.basePrice, style: textTheme.titleLarge),
                if (item.prepTimeMinutes > 0) ...[
                  const SizedBox(width: 14),
                  Icon(Icons.schedule, size: 16, color: c.inkSoft),
                  const SizedBox(width: 4),
                  Text('${item.prepTimeMinutes} min', style: textTheme.bodyMedium),
                ],
              ],
            ),
            const SizedBox(height: 20),

            // Customization groups.
            for (final group in item.customizations) ...[
              _GroupHeader(group: group),
              const SizedBox(height: 10),
              NeoCard(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                child: Column(
                  children: [
                    for (final option in group.options)
                      _OptionTile(
                        label: option.name,
                        priceDelta: option.priceDelta,
                        selected:
                            _selections[group.name]?.contains(option.name) ?? false,
                        multiSelect: group.multiSelect,
                        onTap: () => _toggle(group, option),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
            ],

            // Quantity.
            Text('Quantity', style: textTheme.titleMedium),
            const SizedBox(height: 10),
            _QuantityStepper(
              value: _quantity,
              onChanged: (v) => setState(() => _quantity = v),
            ),
            const SizedBox(height: 24),

            // Notes.
            NeoTextField(
              labelText: 'Special instructions (optional)',
              controller: _notesController,
              hintText: 'e.g. Extra spicy, no onions',
              maxLines: 3,
              maxLength: 140,
            ),
          ],
        ),
      ),
    );
  }
}

class _GroupHeader extends StatelessWidget {
  const _GroupHeader({required this.group});
  final CustomizationGroup group;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    return Row(
      children: [
        Text(group.name, style: textTheme.titleMedium),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(
            color: group.required ? AppColors.tomato : c.surfaceAlt,
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: c.border, width: 1.5),
          ),
          child: Text(
            group.required
                ? 'REQUIRED'
                : (group.multiSelect ? 'CHOOSE ANY' : 'PICK ONE'),
            style: textTheme.bodySmall?.copyWith(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              color: group.required ? AppColors.cream : c.inkSoft,
            ),
          ),
        ),
      ],
    );
  }
}

class _OptionTile extends StatelessWidget {
  const _OptionTile({
    required this.label,
    required this.priceDelta,
    required this.selected,
    required this.multiSelect,
    required this.onTap,
  });

  final String label;
  final double priceDelta;
  final bool selected;
  final bool multiSelect;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final icon = multiSelect
        ? (selected ? Icons.check_box : Icons.check_box_outline_blank)
        : (selected ? Icons.radio_button_checked : Icons.radio_button_off);

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 14),
        child: Row(
          children: [
            Icon(icon, color: selected ? c.primary : c.inkSoft, size: 22),
            const SizedBox(width: 12),
            Expanded(child: Text(label, style: textTheme.bodyLarge)),
            if (priceDelta != 0)
              Text(
                priceDelta > 0
                    ? '+${formatRupees(priceDelta)}'
                    : '-${formatRupees(priceDelta.abs())}',
                style: textTheme.titleSmall?.copyWith(color: c.inkSoft),
              ),
          ],
        ),
      ),
    );
  }
}

class _QuantityStepper extends StatelessWidget {
  const _QuantityStepper({required this.value, required this.onChanged});
  final int value;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    Widget button(IconData icon, VoidCallback? onTap) => GestureDetector(
          onTap: onTap,
          child: Container(
            width: 46,
            height: 46,
            decoration: BoxDecoration(
              color: onTap == null ? c.surfaceAlt : c.accent,
              borderRadius: BorderRadius.circular(AppTheme.radius),
              border: Border.all(color: c.border, width: AppTheme.borderWidth),
              boxShadow: [
                BoxShadow(color: c.shadow, offset: const Offset(3, 3), blurRadius: 0),
              ],
            ),
            child: Icon(icon, color: onTap == null ? c.inkSoft : c.onAccent),
          ),
        );

    return Row(
      children: [
        button(Icons.remove, value > 1 ? () => onChanged(value - 1) : null),
        SizedBox(
          width: 56,
          child: Center(child: Text('$value', style: textTheme.headlineSmall)),
        ),
        button(Icons.add, value < 30 ? () => onChanged(value + 1) : null),
      ],
    );
  }
}
