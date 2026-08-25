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
import '../widgets/location_permission_dialog.dart';

/// Discover: choose WHERE to look for restaurants, by GPS or by city.
///
/// No longer the post-login landing screen — [HomeScreen] is. This is reached
/// only by tapping "Find restaurants near you", which is what makes the
/// location question answerable: it is now asked at a moment the customer has
/// just said they want restaurants near them, rather than as the first thing
/// the app says after sign-in.
///
/// The class name is unchanged deliberately; renaming it would churn every
/// import and every test reference for a title string.
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

  /// Ticked cities. Multi-select — see [AreaPicker].
  ///
  /// EMPTY DISABLES the CTA rather than meaning "all". Chosen over
  /// defaulting-to-all because with a default the checkboxes would look
  /// decorative: ticking none and ticking every box would do the same thing,
  /// so nothing on screen would explain what the boxes were for. A disabled
  /// button that says "Pick at least one city" states the requirement instead
  /// of hiding it. "Near me" already covers the "just show me things" case.
  final Set<String> _selectedAreas = <String>{};

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
        // Drop stale selections — cities that no longer have outlets. Done as
        // a set difference so a refresh that removes one city does not clear
        // the others alongside it.
        final live = areas.map((a) => a.city).toSet();
        _selectedAreas.removeWhere((city) => !live.contains(city));
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _areas = const [];
        _areasError = e.message;
      });
    }
  }

  /// "Near me". Re-checks permission from the OS on EVERY tap, and re-prompts
  /// on every tap while the answer is a plain `denied`.
  ///
  /// `userInitiated: true` is what makes the second tap behave like the first.
  /// Without it the service's one-prompt latch stayed set for as long as the
  /// status did not change, so tapping again after a denial did nothing
  /// visible at all — no dialog, no message that explained why.
  Future<void> _useMyLocation() async {
    setState(() => _locating = true);
    final service = context.read<LocationService>();
    final result = await service.getCurrentLocation(userInitiated: true);
    if (!mounted) return;
    setState(() => _locating = false);

    if (result.outcome == LocationOutcome.granted && result.hasCoordinates) {
      _goToOutlets(lat: result.latitude, lng: result.longitude);
      return;
    }

    // Permanently blocked is the one outcome the app cannot re-ask its way out
    // of, so it gets a dialog that says so and offers Settings, rather than a
    // SnackBar that times out. See showLocationBlockedDialog.
    if (result.outcome == LocationOutcome.deniedForever) {
      await showLocationBlockedDialog(
        context,
        service: service,
        purpose: 'find restaurants near you',
      );
      return;
    }

    // Everything else is momentary and self-explanatory. A refusal is
    // respected: the flow does NOT continue to a location-based list, and
    // nothing retries in the background. The city picker below is a complete
    // alternative, so this is a dead end only for GPS.
    final reason = switch (result.outcome) {
      LocationOutcome.serviceDisabled =>
        'Location services are off. Pick your city below.',
      LocationOutcome.denied => 'No problem — pick your city below.',
      _ => 'Could not get your location. Pick your city below.',
    };
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(reason)));
  }

  void _goToOutlets({double? lat, double? lng, Set<String> cities = const {}}) {
    Navigator.of(context).push(
      MaterialPageRoute(
        // `cities` doubles as the filter: OutletsScreen forwards it to
        // GET /customer/outlets?city=A&city=B, so the choice actually narrows
        // the list rather than only relabelling it.
        builder: (_) => OutletsScreen(
          lat: lat,
          lng: lng,
          cities: Set<String>.of(cities),
        ),
      ),
    );
  }

  /// CTA label. Names the cities while there are few enough to read, then
  /// falls back to a count — "Show outlets in Bengaluru, Chennai" is useful,
  /// the same line with nine cities in it is not.
  String get _ctaLabel {
    final picked = _selectedAreas.toList()..sort();
    if (picked.isEmpty) return 'Pick at least one city';
    if (picked.length <= 2) return 'Show outlets in ${picked.join(' & ')}';
    return 'Show outlets in ${picked.length} cities';
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Discover'),
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
                'Pick one or more cities below, or use "Near me" to find the '
                'closest outlets.',
                style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
              ),
              const SizedBox(height: 22),
              AreaPicker(
                areas: _areas,
                error: _areasError,
                selected: _selectedAreas,
                onToggle: (city) => setState(() {
                  // The set is owned here, not in the picker, so the CTA label
                  // and the enabled state read the same source the rows do.
                  if (!_selectedAreas.remove(city)) _selectedAreas.add(city);
                }),
                onRetry: _loadAreas,
              ),
              const SizedBox(height: 24),
              // The ONLY thing that navigates. Tapping a city row toggles it and
              // nothing more — so a mis-tap while scanning the list costs a
              // second tap to correct, not a screen transition to back out of.
              //
              // Disabled on an empty selection. See _selectedAreas for why that
              // beats defaulting to all.
              NeoButton(
                key: const Key('show_outlets_cta'),
                label: _ctaLabel,
                icon: Icons.arrow_forward,
                onPressed: _selectedAreas.isEmpty
                    ? null
                    : () => _goToOutlets(cities: _selectedAreas),
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
