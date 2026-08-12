import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/catalog_service.dart';
import '../services/location_service.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/page_header.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import 'outlets_screen.dart';
import '../widgets/account_button.dart';
import '../widgets/area_picker.dart';

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
              // The Bevan-ascender fix that used to live here now lives inside
              // PageHeader, which every page title goes through.
              const SizedBox(height: 20),
              // The location affordance is a SMALL control anchored top-right,
              // not the half-screen purple panel it used to be. It was the
              // loudest thing on a screen whose real content is the city list,
              // and it only opens the OS permission dialog — the actual
              // decision surface, which the app cannot style or size.
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Expanded(child: PageHeader('Where are you?')),
                  const SizedBox(width: 12),
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: NeoButton(
                      key: const Key('use_my_location'),
                      label: 'Near me',
                      icon: Icons.my_location,
                      variant: NeoButtonVariant.accent,
                      expand: false,
                      compact: true,
                      loading: _locating,
                      onPressed: _useMyLocation,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                'Pick your city below, or use "Near me" to find the closest '
                'outlets.',
                style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
              ),
              const SizedBox(height: 22),
              AreaPicker(
                areas: _areas,
                error: _areasError,
                selected: _selectedArea,
                onSelect: (city) => setState(() => _selectedArea = city),
                onRetry: _loadAreas,
              ),
              const SizedBox(height: 24),
              // The ONLY thing that navigates. Tapping a city row selects it and
              // nothing more — so a mis-tap while scanning the list costs a
              // second tap to correct, not a screen transition to back out of.
              NeoButton(
                key: const Key('show_outlets_cta'),
                label: _selectedArea == null
                    ? 'Pick a city to continue'
                    : 'Show outlets in $_selectedArea',
                icon: Icons.arrow_forward,
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
