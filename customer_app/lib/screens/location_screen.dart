import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

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
  static const _areas = <String>[
    'Koramangala',
    'Indiranagar',
    'HSR Layout',
    'Whitefield',
    'Jayanagar',
    'MG Road',
    'Electronic City',
    'Marathahalli',
  ];

  bool _locating = false;
  String? _selectedArea;

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
              const SizedBox(height: 8),
              Text('Where are\nyou?', style: textTheme.displaySmall),
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
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: _areas
                    .map((a) => NeoChip(
                          label: a,
                          icon: Icons.place_outlined,
                          selected: _selectedArea == a,
                          onTap: () => setState(() => _selectedArea = a),
                        ))
                    .toList(),
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
