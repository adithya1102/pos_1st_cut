import 'package:flutter/material.dart';

import '../services/catalog_service.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_chip.dart';

/// City selector for the Location screen, backed by `GET /customer/areas`.
///
/// Renders one of five states: loading, load-failed (retry), no serviceable
/// cities, chips, or search + chips. A city only reaches here if it has at
/// least one orderable outlet, so a selection can never lead to an empty list.
///
/// ## Why a threshold rather than always-search
/// With a handful of cities, a search box is pure friction — the whole list is
/// already on screen and scannable in one glance. Past a certain count the
/// chips wrap into an unscannable block and typing beats hunting. So the
/// component switches presentation based on how much data there actually is,
/// and the chips themselves are byte-identical in both modes (same
/// [_buildChips]), so crossing the threshold only adds a field above them.
///
/// Lives in its own file rather than as a private class in location_screen so
/// it can be widget-tested directly — see test/area_picker_test.dart.
class AreaPicker extends StatefulWidget {
  const AreaPicker({
    super.key,
    required this.areas,
    required this.error,
    required this.selected,
    required this.onSelect,
    required this.onRetry,
  });

  /// Null while loading; empty when no city has an orderable outlet.
  final List<AreaOption>? areas;
  final String? error;
  final String? selected;
  final ValueChanged<String> onSelect;
  final VoidCallback onRetry;

  /// At or below this many cities the list renders as plain chips. Above it, a
  /// search field appears. Exposed so the threshold is testable and there is
  /// exactly one place to change it.
  static const int searchThreshold = 8;

  /// Whether [count] cities should be presented with a search field.
  /// `count > searchThreshold` — 8 stays chips, 9 switches.
  static bool usesSearch(int count) => count > searchThreshold;

  @override
  State<AreaPicker> createState() => _AreaPickerState();
}

class _AreaPickerState extends State<AreaPicker> {
  final _search = TextEditingController();
  String _query = '';

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(AreaPicker oldWidget) {
    super.didUpdateWidget(oldWidget);
    // If the list shrinks back below the threshold, a stale query would keep
    // filtering chips the customer can now see in full. Drop it.
    final count = widget.areas?.length ?? 0;
    if (!AreaPicker.usesSearch(count) && _query.isNotEmpty) {
      _query = '';
      _search.clear();
    }
  }

  List<AreaOption> _filtered(List<AreaOption> all) {
    final q = _query.trim().toLowerCase();
    if (q.isEmpty) return all;
    return all.where((a) => a.city.toLowerCase().contains(q)).toList();
  }

  /// The chip row. Shared by both modes so switching presentation never
  /// changes how an individual chip looks.
  Widget _buildChips(List<AreaOption> list) => Wrap(
        spacing: 10,
        runSpacing: 10,
        children: [
          for (final a in list)
            NeoChip(
              label: '${a.city}  ·  ${a.subtitle}',
              icon: Icons.place_outlined,
              selected: widget.selected == a.city,
              onTap: () => widget.onSelect(a.city),
            ),
        ],
      );

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final list = widget.areas;

    if (list == null) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Center(child: CircularProgressIndicator()),
      );
    }

    if (widget.error != null) {
      return Row(
        children: [
          Expanded(
            child: Text(
              'Could not load areas.',
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
          ),
          TextButton(onPressed: widget.onRetry, child: const Text('Retry')),
        ],
      );
    }

    if (list.isEmpty) {
      // Honest empty state. The old hardcoded chips would happily offer eight
      // Bangalore areas here and send the customer to a blank list.
      return Text(
        'No restaurants are taking pickup orders yet. '
        'Try "Use my current location" to check nearby.',
        style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
      );
    }

    // Small list: chips only, exactly as before this component existed.
    if (!AreaPicker.usesSearch(list.length)) {
      return _buildChips(list);
    }

    // Large list: search field above the same chips, filtered live.
    final matches = _filtered(list);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextField(
          controller: _search,
          decoration: InputDecoration(
            hintText: 'Search ${list.length} cities',
            prefixIcon: const Icon(Icons.search),
            suffixIcon: _query.isEmpty
                ? null
                : IconButton(
                    icon: const Icon(Icons.clear),
                    tooltip: 'Clear search',
                    onPressed: () {
                      _search.clear();
                      setState(() => _query = '');
                    },
                  ),
          ),
          onChanged: (v) => setState(() => _query = v),
        ),
        const SizedBox(height: 16),
        if (matches.isEmpty)
          Text(
            'No city matches "${_query.trim()}".',
            style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
          )
        else
          _buildChips(matches),
      ],
    );
  }
}
