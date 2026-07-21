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
class LocationService {
  /// Requests permission (if needed) and returns the current position.
  /// On any denial/failure the caller falls back to manual city/area select.
  Future<LocationResult> getCurrentLocation() async {
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        return const LocationResult(LocationOutcome.serviceDisabled);
      }

      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }

      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
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
