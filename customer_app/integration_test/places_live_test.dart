// Live on-device proof that the native Places SDK actually calls Google with
// the Android-restricted key (there is no "fallback" for Places — a non-empty
// result set IS the proof it was called). Billable: runs ~1 Places session.
//
// Run:
//   flutter test integration_test/places_live_test.dart -d emulator-5554 \
//     --dart-define=MAPS_API_KEY=<android key>
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:customer_app/services/places_service.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Places Autocomplete returns real predictions + coordinates',
      (tester) async {
    final places = PlacesService();
    expect(places.isEnabled, isTrue,
        reason: 'MAPS_API_KEY must be passed via --dart-define');

    places.startSession();
    final preds = await places.predictions('Chennai Central');
    // ignore: avoid_print
    print('PLACES_LIVE predictions=${preds.length} '
        'first=${preds.isNotEmpty ? preds.first.primary : "<none>"}');
    expect(preds, isNotEmpty,
        reason: 'A live Places call should return predictions');

    final loc = await places.selectPlace(preds.first.placeId);
    // ignore: avoid_print
    print('PLACES_LIVE resolved lat=${loc?.lat} lng=${loc?.lng} '
        'name=${loc?.name}');
    expect(loc, isNotNull, reason: 'fetchPlace should resolve coordinates');
    expect(loc!.lat, isNot(0.0));
    expect(loc.lng, isNot(0.0));
  });
}
