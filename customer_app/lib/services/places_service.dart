import 'package:flutter_google_places_sdk/flutter_google_places_sdk.dart' as gp;

import '../config/app_config.dart';

/// One autocomplete suggestion (cheap — no lat/lng until [selectPlace]).
class PlaceSuggestion {
  const PlaceSuggestion(this.placeId, this.primary, this.secondary);
  final String placeId;
  final String primary;
  final String secondary;
}

/// A resolved place with coordinates (the paid "Place Details" call).
class PlaceLocation {
  const PlaceLocation({
    required this.lat,
    required this.lng,
    this.name,
    this.address,
  });
  final double lat;
  final double lng;
  final String? name;
  final String? address;

  String get label => name ?? address ?? 'Selected location';
}

/// Wraps the native Google Places SDK (flutter_google_places_sdk). The native
/// SDK attaches the app's package + signing cert, so the Android-restricted key
/// works on-device without a server round-trip.
///
/// Session-token billing (Google): every predictions()→…→selectPlace() flow
/// shares ONE session token. Call [startSession] when the search field opens;
/// the first predictions() call mints a fresh token, and selectPlace() closes
/// it — so autocomplete keystrokes + the final details lookup bill as a single
/// session rather than per keystroke.
class PlacesService {
  gp.FlutterGooglePlacesSdk? _sdk;
  bool _tokenOpen = false;

  bool get isEnabled => AppConfig.hasMapsKey;

  gp.FlutterGooglePlacesSdk? get _client {
    if (!isEnabled) return null;
    // useNewApi:true -> Places.initializeWithNewPlacesApiEnabled, i.e. the
    // "Places API (New)" surface. The legacy Places API is disabled for
    // new Google Cloud projects; the native SDK still authenticates with the
    // Android package+SHA-1 restricted key.
    return _sdk ??= gp.FlutterGooglePlacesSdk(AppConfig.mapsApiKey, useNewApi: true);
  }

  /// Begin a new search-to-selection flow. The next [predictions] call opens a
  /// fresh session token.
  void startSession() => _tokenOpen = false;

  Future<List<PlaceSuggestion>> predictions(String query) async {
    final client = _client;
    if (client == null || query.trim().length < 3) return const [];
    final resp = await client.findAutocompletePredictions(
      query,
      countries: const ['in'], // India-only deploy
      newSessionToken: !_tokenOpen, // mint a token on the first keystroke
    );
    _tokenOpen = true;
    return resp.predictions
        .map((p) => PlaceSuggestion(p.placeId, p.primaryText, p.secondaryText))
        .toList();
  }

  /// Resolve a suggestion to coordinates. Closes the current session token, so
  /// the next [predictions] starts a new (separately billed) session.
  Future<PlaceLocation?> selectPlace(String placeId) async {
    final client = _client;
    if (client == null) return null;
    final resp = await client.fetchPlace(placeId, fields: const [
      gp.PlaceField.Location,
      gp.PlaceField.Name,
      gp.PlaceField.Address,
    ]);
    _tokenOpen = false; // fetchPlace ends the session
    final place = resp.place;
    final ll = place?.latLng;
    if (ll == null) return null;
    return PlaceLocation(
      lat: ll.lat,
      lng: ll.lng,
      name: place?.name,
      address: place?.address,
    );
  }
}
