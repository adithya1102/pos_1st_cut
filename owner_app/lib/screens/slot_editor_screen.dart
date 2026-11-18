import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/meal_slot.dart';
import '../models/menu_item.dart';
import '../state/home_state.dart';

/// Define one meal time: its display range, and which dishes it switches on.
///
/// The times here are DISPLAY ONLY and the screen says so, because an owner
/// who believes they are scheduling something would stop checking — nothing
/// applies a slot automatically, every switch is a tap on the chip.
class SlotEditorScreen extends StatefulWidget {
  final String slotKey;

  const SlotEditorScreen({super.key, required this.slotKey});

  static const saveKey = Key('slot_editor_save');
  static const selectAllKey = Key('slot_editor_select_all');
  static const clearKey = Key('slot_editor_clear');
  static const startKey = Key('slot_editor_start');
  static const endKey = Key('slot_editor_end');

  @override
  State<SlotEditorScreen> createState() => _SlotEditorScreenState();
}

class _SlotEditorScreenState extends State<SlotEditorScreen> {
  TimeOfDay? _start;
  TimeOfDay? _end;
  Set<String> _picked = <String>{};
  bool _initialised = false;
  bool _saving = false;

  static TimeOfDay? _parse(String? hhmm) {
    final raw = (hhmm ?? '').trim();
    if (raw.isEmpty) return null;
    final parts = raw.split(':');
    if (parts.length < 2) return null;
    final h = int.tryParse(parts[0]);
    final m = int.tryParse(parts[1]);
    if (h == null || m == null || h < 0 || h > 23 || m < 0 || m > 59) {
      return null;
    }
    return TimeOfDay(hour: h, minute: m);
  }

  static String _fmt(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  MealSlot _slot(HomeState home) => home.slots.firstWhere(
        (s) => s.slotKey == widget.slotKey,
        orElse: () => MealSlot(slotKey: widget.slotKey),
      );

  Future<void> _pick(BuildContext context, {required bool isStart}) async {
    final initial =
        (isStart ? _start : _end) ?? const TimeOfDay(hour: 9, minute: 0);
    final chosen = await showTimePicker(context: context, initialTime: initial);
    if (chosen == null) return;
    setState(() {
      if (isStart) {
        _start = chosen;
      } else {
        _end = chosen;
      }
    });
  }

  Future<void> _save(BuildContext context, List<MenuItem> dishes) async {
    setState(() => _saving = true);
    // Only ids that still exist on the menu. A dish deleted while this screen
    // was open would otherwise be sent and rejected with a flat 404 naming
    // nothing the owner could act on.
    final live = dishes.map((d) => d.id).toSet();
    final ids = _picked.where(live.contains).toList(growable: false);

    final error = await context.read<HomeState>().saveSlot(
          widget.slotKey,
          startTime: _start == null ? null : _fmt(_start!),
          endTime: _end == null ? null : _fmt(_end!),
          itemIds: ids,
        );
    if (!context.mounted) return;
    setState(() => _saving = false);
    if (error != null) {
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(
          key: const Key('slot_editor_error'),
          content: Text(error),
        ));
      return;
    }
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(const SnackBar(content: Text('Meal time saved.')));
    Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final home = context.watch<HomeState>();
    final slot = _slot(home);
    final dishes = home.items.where((d) => d.isActive).toList();

    if (!_initialised) {
      _start = _parse(slot.startTime);
      _end = _parse(slot.endTime);
      _picked = slot.itemIds.toSet();
      _initialised = true;
    }

    // Grouped by category for scanning. A dish with no category falls into
    // "Other" rather than vanishing from the list.
    final grouped = <String, List<MenuItem>>{};
    for (final d in dishes) {
      final key = (d.categoryName ?? '').trim().isEmpty
          ? 'Other'
          : d.categoryName!.trim();
      grouped.putIfAbsent(key, () => []).add(d);
    }
    final categories = grouped.keys.toList()..sort();

    return Scaffold(
      appBar: AppBar(
        title: Text(slot.label),
        actions: [
          if (_saving)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 20),
              child: Center(
                child: SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            )
          else
            // NOT hidden for a non-owner. The app has no role field at all —
            // see the payment-modes row on OutletSettingsScreen for the same
            // decision — so hiding this would mean guessing. The server is the
            // authority: a waiter's save comes back 403 and its message is
            // shown verbatim.
            TextButton(
              key: SlotEditorScreen.saveKey,
              onPressed: () => _save(context, dishes),
              child: const Text('Save'),
            ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('Times shown to you', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(
            'A label for this chip only. Nothing switches automatically — you '
            'tap the chip when you want these dishes on.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 12),
          _TimeRow(
            rowKey: SlotEditorScreen.startKey,
            label: 'Starts',
            value: _start,
            onTap: () => _pick(context, isStart: true),
          ),
          const SizedBox(height: 8),
          _TimeRow(
            rowKey: SlotEditorScreen.endKey,
            label: 'Ends',
            value: _end,
            onTap: () => _pick(context, isStart: false),
          ),
          const Divider(height: 32),
          Row(
            children: [
              Expanded(
                child: Text('Dishes (${_picked.length} of ${dishes.length})',
                    style: Theme.of(context).textTheme.titleMedium),
              ),
              TextButton(
                key: SlotEditorScreen.selectAllKey,
                onPressed: dishes.isEmpty
                    ? null
                    : () => setState(
                        () => _picked = dishes.map((d) => d.id).toSet()),
                child: const Text('Select all'),
              ),
              TextButton(
                key: SlotEditorScreen.clearKey,
                onPressed: _picked.isEmpty
                    ? null
                    : () => setState(() => _picked = <String>{}),
                child: const Text('Clear'),
              ),
            ],
          ),
          if (dishes.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 24),
              child: Text('Add some dishes first, then group them here.'),
            )
          else
            for (final category in categories) ...[
              Padding(
                padding: const EdgeInsets.only(top: 12, bottom: 4),
                child: Text(category,
                    style: Theme.of(context).textTheme.labelLarge),
              ),
              for (final dish in grouped[category]!)
                CheckboxListTile(
                  key: Key('slot_dish_${dish.id}'),
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  value: _picked.contains(dish.id),
                  title: Text(dish.name),
                  // The live count, so an owner is not surprised when a dish
                  // they ticked is skipped at apply time for being sold out.
                  subtitle: dish.isStockTracked
                      ? Text('${dish.stockRemaining} left')
                      : null,
                  onChanged: (on) => setState(() {
                    if (on == true) {
                      _picked.add(dish.id);
                    } else {
                      _picked.remove(dish.id);
                    }
                  }),
                ),
            ],
          const SizedBox(height: 12),
          Text(
            'A dish can be in more than one meal time.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _TimeRow extends StatelessWidget {
  final Key rowKey;
  final String label;
  final TimeOfDay? value;
  final VoidCallback onTap;

  const _TimeRow({
    required this.rowKey,
    required this.label,
    required this.value,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(
      key: rowKey,
      onPressed: onTap,
      child: Row(
        children: [
          Expanded(child: Text(label)),
          Text(value == null ? 'Not set' : value!.format(context)),
          const SizedBox(width: 8),
          const Icon(Icons.schedule_outlined, size: 18),
        ],
      ),
    );
  }
}
