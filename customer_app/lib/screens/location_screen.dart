import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/catalog_service.dart';
import '../services/location_service.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/neo_chip.dart';
import 'outlets_screen.dart';
import '../widgets/account_button.dart';

/// Step 3: location permission request WITH a manual city/area fallback.
class LocationScreen extends StatefulWidget {
  const LocationScreen({super.key});

  @override
  State<LocationScreen> createState() => _LocationScreenState();
}

class _LocationScreenState extends State<LocationScreen> {
  // Areas come from GET /customer/areas — cities that actually have an
  // orderable outlet. The previous hardcoded Bangalore list could offer a
  // location with no restaurants behind it, and selecting one filtered nothing.
  List<AreaOption>? _areas;
  String? _areasError;

  bool _locating = false;
  String? _selectedArea;

  @override
  void initState() {
    super.initState();
    _loadAreas();
  }

  Future<void> _loadAreas() async {
    setState(() => _areasError = null);
    try {
      final areas = await context.read<CatalogService>().fetchAreas();
      if (!mounted) return;
      setState(() {
        _areas = areas;
        // Drop a stale selection if that city no longer has outlets.
        if (_selectedArea != null &&
            !areas.any((a) => a.city == _selectedArea)) {
          _selectedArea = null;
        }
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _areas = const [];
        _areasError = e.message;
      });
    }
  }

  Future<void> _useMyLocation() async {
    setState(() => _locating = true);
    final result = await context.read<LocationService>().getCurrentLocation();
    if (!mounted) return;
    setState(() => _locating = false);

    if (result.outcome == LocationOutcome.granted && result.hasCoordinates) {
      _goToOutlets(lat: result.latitude, lng: result.longitude);
    } else {
      final reason = switch (result.outcome) {
        LocationOutcome.serviceDisabled => 'Location services are off. Pick your area below.',
        LocationOutcome.denied => 'Permission denied. Pick your area below.',
        _ => 'Could not get your location. Pick your area below.',
      };
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(reason)));
    }
  }

  void _goToOutlets({double? lat, double? lng, String? areaLabel}) {
    Navigator.of(context).push(
      MaterialPageRoute(
        // areaLabel doubles as the `city` filter: OutletsScreen forwards it to
        // GET /customer/outlets?city=..., so the choice actually narrows the
        // list rather than only relabelling it.
        builder: (_) => OutletsScreen(lat: lat, lng: lng, areaLabel: areaLabel),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Location'),
        actions: careVoActions(),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Task 3 — header/title overlap.
              // Bevan (the display font) has tall ascenders, and the theme sets
              // displaySmall to height: 1.1, TIGHTER than the font's natural
              // line box. Flutter then lets the first line's glyphs overflow
              // ABOVE the text widget's top edge, where they collided with the
              // app bar across the previous 8px gap.
              //
              // applyHeightToFirstAscent: false makes the first line use the
              // font's real ascent instead of the compressed one, so glyphs sit
              // inside their box; the larger gap adds separation on top of that.
              const SizedBox(height: 20),
              Text(
                'Where are\nyou?',
                style: textTheme.displaySmall,
                textHeightBehavior: const TextHeightBehavior(
                  applyHeightToFirstAscent: false,
                ),
              ),
              const SizedBox(height: 12),
              Text(
                'We use your location to find restaurants near you for pickup.',
                style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
              ),
              const SizedBox(height: 24),
              NeoCard(
                color: c.primary,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(Icons.my_location, color: c.onPrimary, size: 30),
                    const SizedBox(height: 12),
                    Text(
                      'Use my current location',
                      style: textTheme.titleLarge?.copyWith(color: c.onPrimary),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Fastest way to see the closest outlets.',
                      style: textTheme.bodyMedium?.copyWith(
                        color: c.onPrimary.withValues(alpha: 0.85),
                      ),
                    ),
                    const SizedBox(height: 16),
                    NeoButton(
                      label: 'Allow location',
                      icon: Icons.gps_fixed,
                      variant: NeoButtonVariant.accent,
                      loading: _locating,
                      onPressed: _useMyLocation,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 28),
              Row(
                children: [
                  Expanded(child: Divider(color: c.border, thickness: 2)),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: Text('OR CHOOSE AREA', style: textTheme.labelLarge),
                  ),
                  Expanded(child: Divider(color: c.border, thickness: 2)),
                ],
              ),
              const SizedBox(height: 20),
              _AreaPicker(
                areas: _areas,
                error: _areasError,
                selected: _selectedArea,
                onSelect: (city) => setState(() => _selectedArea = city),
                onRetry: _loadAreas,
              ),
              const SizedBox(height: 24),
              NeoButton(
                label: _selectedArea == null
                    ? 'Select an area to continue'
                    : 'Show outlets in $_selectedArea',
                icon: Icons.arrow_forward,
                variant: NeoButtonVariant.neutral,
                onPressed: _selectedArea == null
                    ? null
                    : () => _goToOutlets(areaLabel: _selectedArea),
              ),
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: c.surfaceAlt,
                  borderRadius: BorderRadius.circular(AppTheme.radius),
                  border: Border.all(color: c.border, width: 2),
                ),
                child: Row(
                  children: [
                    Icon(Icons.storefront_outlined, size: 18, color: c.inkSoft),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'All orders are self-pickup — no delivery, no waiting.',
                        style: textTheme.bodySmall,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// City chips built from live outlet data.
///
/// Renders one of four states rather than an unconditional chip row: loading,
/// load-failed (with retry), genuinely no serviceable cities, or the chips. A
/// city only reaches here if it has >=1 orderable outlet, so tapping one can
/// never land on an empty restaurant list.
class _AreaPicker extends StatelessWidget {
  const _AreaPicker({
    required this.areas,
    required this.error,
    required this.selected,
    required this.onSelect,
    required this.onRetry,
  });

  final List<AreaOption>? areas;
  final String? error;
  final String? selected;
  final ValueChanged<String> onSelect;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final list = areas;

    if (list == null) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Center(child: CircularProgressIndicator()),
      );
    }

    if (error != null) {
      return Row(
        children: [
          Expanded(
            child: Text(
              'Could not load areas.',
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
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

    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: [
        for (final a in list)
          NeoChip(
            label: '${a.city}  ·  ${a.subtitle}',
            icon: Icons.place_outlined,
            selected: selected == a.city,
            onTap: () => onSelect(a.city),
          ),
      ],
    );
  }
}
