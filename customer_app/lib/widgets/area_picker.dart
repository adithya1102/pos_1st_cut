import 'package:flutter/material.dart';

import '../services/catalog_service.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import 'focus_release.dart';

/// City selector for the Location screen, backed by `GET /customer/areas`.
///
/// Renders one of four states: loading, load-failed (retry), no serviceable
/// cities, or search + list. A city only reaches here if it has at least one
/// orderable outlet, so a selection can never lead to an empty list.
///
/// ## Selection is MULTI and is NOT navigation
/// Cities are checkboxes, not radio buttons: a customer near a city boundary,
/// or choosing between somewhere they live and somewhere they commute to,
/// wants both lists at once rather than having to pick one and come back.
///
/// Tapping a row only toggles it. Nothing moves until the caller's explicit
/// "Show outlets" action fires. Those were always two separate things here;
/// this component has no navigation capability at all — it takes an [onToggle]
/// callback and that is the entirety of what a tap can do.
///
/// ## Always a search field, always a list
/// An earlier version showed chips, and only grew a search field past 8 cities.
/// Both are gone: chips wrap into a shape that is hard to scan and gave the
/// restaurant count no room, and a search box that appears only sometimes means
/// the screen a customer learns is not the screen they get next month. One
/// presentation, at every list size.
///
/// Rows are sorted alphabetically ASCENDING here rather than server-side. The
/// endpoint orders by outlet count for its own reasons and other callers may
/// rely on that; sort order in a picker is a presentation decision.
///
/// Lives in its own file rather than as a private class in location_screen so
/// it can be widget-tested directly — see test/area_picker_test.dart.
class AreaPicker extends StatefulWidget {
  const AreaPicker({
    super.key,
    required this.areas,
    required this.error,
    required this.selected,
    required this.onToggle,
    required this.onRetry,
  });

  /// Null while loading; empty when no city has an orderable outlet.
  final List<AreaOption>? areas;
  final String? error;

  /// Every currently-ticked city. Empty is a legitimate state — the caller
  /// disables its CTA rather than treating it as "all".
  final Set<String> selected;

  /// Fired with the city whose checkbox was hit. The caller owns the set and
  /// decides add-vs-remove, so this widget holds no selection state of its own.
  final ValueChanged<String> onToggle;
  final VoidCallback onRetry;

  /// Alphabetical ascending, case-insensitive so "bengaluru" and "Bengaluru"
  /// cannot land in different halves of the list.
  static List<AreaOption> sortedAlphabetically(List<AreaOption> all) {
    final out = List<AreaOption>.of(all);
    out.sort((a, b) => a.city.toLowerCase().compareTo(b.city.toLowerCase()));
    return out;
  }

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

  List<AreaOption> _visible(List<AreaOption> all) {
    final sorted = AreaPicker.sortedAlphabetically(all);
    final q = _query.trim().toLowerCase();
    if (q.isEmpty) return sorted;
    return sorted.where((a) => a.city.toLowerCase().contains(q)).toList();
  }

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
              'Could not load cities.',
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
        'Try "Near me" to check nearby.',
        style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
      );
    }

    final matches = _visible(list);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _SearchField(
          controller: _search,
          hint: list.length == 1
              ? 'Search cities'
              : 'Search ${list.length} cities',
          query: _query,
          onChanged: (v) => setState(() => _query = v),
          onClear: () {
            _search.clear();
            setState(() => _query = '');
          },
        ),
        const SizedBox(height: 16),
        if (matches.isEmpty)
          Text(
            'No city matches "${_query.trim()}".',
            style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
          )
        else
          for (final a in matches)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: _CityRow(
                area: a,
                selected: widget.selected.contains(a.city),
                onTap: () => widget.onToggle(a.city),
              ),
            ),
      ],
    );
  }
}

class _SearchField extends StatelessWidget {
  const _SearchField({
    required this.controller,
    required this.hint,
    required this.query,
    required this.onChanged,
    required this.onClear,
  });

  final TextEditingController controller;
  final String hint;
  final String query;
  final ValueChanged<String> onChanged;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Container(
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        border: Border.all(color: c.border, width: AppTheme.borderWidth),
        boxShadow: [
          BoxShadow(color: c.shadow, offset: const Offset(3, 3), blurRadius: 0),
        ],
      ),
      child: TextField(
        key: const Key('city_search_field'),
        controller: controller,
        onChanged: onChanged,
        // The SAME focus-release fix every other input already had, not a
        // second mechanism. This one is a raw TextField rather than a
        // NeoTextField (it needs the clear-button suffix), so it never picked
        // up the onTapOutside default that was added to NeoTextField — this
        // was the one input in the app still holding focus on a tap-away.
        //
        // The route-transition half was already covered: FocusReleasingObserver
        // is registered on the app's Navigator, so leaving this screen already
        // dropped focus. Only the tap-outside half was missing here.
        onTapOutside: (_) => releaseFocus(),
        style: Theme.of(context).textTheme.bodyLarge,
        decoration: InputDecoration(
          hintText: hint,
          hintStyle:
              Theme.of(context).textTheme.bodyLarge?.copyWith(color: c.inkSoft),
          prefixIcon: Icon(Icons.search, color: c.inkSoft),
          suffixIcon: query.isEmpty
              ? null
              : IconButton(
                  icon: const Icon(Icons.clear),
                  tooltip: 'Clear search',
                  onPressed: onClear,
                ),
          border: InputBorder.none,
          focusedBorder: InputBorder.none,
          enabledBorder: InputBorder.none,
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 4, vertical: 16),
        ),
      ),
    );
  }
}

/// One city row: name, and how many restaurants are behind it.
///
/// The count is the reason this is a row and not a chip — it is what tells the
/// customer whether a city is worth choosing, and it needs somewhere to live
/// that is not crammed into a pill.
class _CityRow extends StatelessWidget {
  const _CityRow({
    required this.area,
    required this.selected,
    required this.onTap,
  });

  final AreaOption area;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return Semantics(
      // checked + inMutuallyExclusiveGroup:false is what tells a screen reader
      // this is a checkbox rather than a radio — the selection model changed,
      // so the announced role has to change with it.
      checked: selected,
      inMutuallyExclusiveGroup: false,
      button: true,
      child: GestureDetector(
        key: Key('city_row_${area.city}'),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
          decoration: BoxDecoration(
            color: selected ? c.accent : c.surface,
            borderRadius: BorderRadius.circular(AppTheme.radius),
            border: Border.all(color: c.border, width: AppTheme.borderWidth),
            boxShadow: [
              BoxShadow(
                color: c.shadow,
                // The selected row sits "down": the shadow collapses, so
                // selection is legible without relying on colour alone.
                offset: selected ? Offset.zero : const Offset(3, 3),
                blurRadius: 0,
              ),
            ],
          ),
          transform: Matrix4.translationValues(
            selected ? 3 : 0,
            selected ? 3 : 0,
            0,
          ),
          child: Row(
            children: [
              // A square box, not a circle: the shape is the affordance that
              // says "several of these can be on at once".
              Icon(
                selected ? Icons.check_box : Icons.check_box_outline_blank,
                size: 20,
                color: selected ? c.onAccent : c.inkSoft,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  area.city,
                  style: textTheme.titleMedium?.copyWith(
                    color: selected ? c.onAccent : c.ink,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Text(
                area.subtitle,
                style: textTheme.bodyMedium?.copyWith(
                  color: selected ? c.onAccent : c.inkSoft,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
