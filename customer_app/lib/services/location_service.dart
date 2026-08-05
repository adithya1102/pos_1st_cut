import 'dart:async';

import 'package:geolocator/geolocator.dart';

/// Outcome of a location request.
enum LocationOutcome { granted, denied, serviceDisabled, error }

class LocationResult {
  const LocationResult(this.outcome, {this.latitude, this.longitude});
  final LocationOutcome outcome;
  final double? latitude;
  final double? longitude;

  bool get hasCoordinates => latitude != null && longitude != null;
}

/// Wraps geolocator so screens don't touch the plugin directly.
///
/// FOREGROUND ONLY. Everything here maps to ACCESS_FINE/COARSE_LOCATION —
/// "while using the app". Background ("allow all the time") location is
/// deliberately not requested: no feature reads location while the app is
/// backgrounded (the en-route pings in PickupScreen run off a Timer that only
/// ticks while the screen is alive), so asking for it would be a scary prompt
/// bought for nothing.
///
/// Registered once in main.dart, so the prompt bookkeeping below is app-wide:
/// the permission dialog is shown at most once per app session and every later
/// caller reuses the cached status instead of re-asking.
class LocationService {
  /// Last status read from the OS. Refreshed on every call so a grant made in
  /// system settings mid-session is picked up without an app restart.
  LocationPermission? _permission;
  LocationPermission? get permission => _permission;

  /// Whether the OS dialog has already been raised this session. Without this,
  /// a denial on one screen made every later screen ask again — the duplicate
  /// prompt. (Android also auto-denies repeat asks, so re-asking mostly just
  /// produced a silent no.)
  bool _prompted = false;

  /// De-dups overlapping calls — e.g. the 60s en-route timer firing while the
  /// departure request is still waiting on a GPS fix. Two concurrent
  /// `requestPermission` calls throw on Android, and two dialogs is exactly the
  /// bug this class is fixing.
  Future<LocationResult>? _inFlight;

  static bool _isGranted(LocationPermission p) =>
      p == LocationPermission.whileInUse || p == LocationPermission.always;

  /// True when location can be read without showing the user anything.
  bool get hasPermission => _isGranted(_permission ?? LocationPermission.denied);

  /// Requests permission (at most once per session) and returns the position.
  /// On any denial/failure the caller falls back to manual city/area select.
  ///
  /// Set [allowPrompt] to false for automatic/background-ish callers (polling
  /// timers, prefetches) so they can use an existing grant but can never be the
  /// thing that raises a dialog the user didn't ask for.
  Future<LocationResult> getCurrentLocation({bool allowPrompt = true}) {
    final pending = _inFlight;
    if (pending != null) return pending;

    late final Future<LocationResult> call;
    call = _resolve(allowPrompt: allowPrompt).whenComplete(() {
      if (identical(_inFlight, call)) _inFlight = null;
    });
    _inFlight = call;
    return call;
  }

  Future<LocationResult> _resolve({required bool allowPrompt}) async {
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        return const LocationResult(LocationOutcome.serviceDisabled);
      }

      var permission = await Geolocator.checkPermission();

      // Only ask when we've never asked. `deniedForever` is never re-asked —
      // the OS suppresses that dialog entirely, so it would be a no-op wait.
      if (permission == LocationPermission.denied && allowPrompt && !_prompted) {
        _prompted = true;
        // Foreground grant only; we never follow up with a background upgrade.
        permission = await Geolocator.requestPermission();
      }
      _permission = permission;

      if (!_isGranted(permission)) {
        return const LocationResult(LocationOutcome.denied);
      }

      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.medium),
      );
      return LocationResult(
        LocationOutcome.granted,
        latitude: position.latitude,
        longitude: position.longitude,
      );
    } catch (_) {
      return const LocationResult(LocationOutcome.error);
    }
  }
}
