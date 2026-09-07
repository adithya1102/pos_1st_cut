// "Use current location" on the outlet settings screen.
//
// The owner stands in their own restaurant and pins it. Customers sort outlets
// by distance, so an unpinned or wrongly-pinned outlet is either invisible to
// that sort or is advertised at the wrong place — which is why the pin is
// saved the moment a fix arrives rather than behind a second Save.
//
// LocationService is customer_app's file, copied VERBATIM (byte-identical), so
// the plugin is faked the same way that app fakes it: by swapping
// GeolocatorPlatform.instance. That keeps the real service — its permission
// latch, its bounded fix, its outcome mapping — inside the test rather than
// mocked away, which is the whole reason for reusing the file.
//
// The request log is the proof the pin actually reaches /pos/outlet/location;
// a screen assertion alone would pass on local state that was never saved.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/screens/outlet_settings_screen.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/location_service.dart';
import 'package:owner_app/services/menu_service.dart';
import 'package:owner_app/services/outlet_service.dart';
import 'package:owner_app/state/home_state.dart';

late List<String> requestLog;
late Map<String, dynamic> lastBody;

const _outletId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
const _location = 'PATCH /api/v1/pos/outlet/location';

/// A backend for one outlet whose pin mutates, like the real endpoint.
http.Client _backend({
  double? latitude,
  double? longitude,
  bool locationFails = false,
}) {
  var lat = latitude, lng = longitude;
  Map<String, dynamic> outletJson() => {
        'id': _outletId,
        'location_name': 'Anand Bhavan',
        'is_visible': true,
        'image_url': null,
        // Carried through so the "one control does not clobber another" test
        // has something to observe.
        'opening_time': '09:00',
        'closing_time': '22:00',
        'is_manually_closed': false,
        'order_status': 'open',
        'latitude': lat,
        'longitude': lng,
      };
  http.Response json(Object b, [int code = 200]) => http.Response(
      jsonEncode(b), code, headers: {'content-type': 'application/json'});

  return MockClient((req) async {
    final path = req.url.path;
    final body = req.body.isEmpty
        ? <String, dynamic>{}
        : jsonDecode(req.body) as Map<String, dynamic>;
    requestLog.add('${req.method} $path');
    if (req.method != 'GET') lastBody = body;

    if (path.endsWith('/pos/menu-items')) return json(const <dynamic>[]);
    if (path.endsWith('/pos/outlet/location')) {
      if (locationFails) return json({'detail': 'boom'}, 500);
      lat = (body['latitude'] as num?)?.toDouble();
      lng = (body['longitude'] as num?)?.toDouble();
      return json(outletJson());
    }
    if (path.endsWith('/pos/outlet')) return json(outletJson());
    return json({'detail': 'unexpected ${req.url}'}, 404);
  });
}

Future<HomeState> _loadedHome(http.Client backend) async {
  SharedPreferences.setMockInitialValues({'gusto_owner_access_token': 'staff'});
  final api = ApiClient(httpClient: backend);
  final home = HomeState(OutletService(api), MenuService(api));
  await home.load();
  return home;
}

Widget _host(HomeState home, LocationService location) => MultiProvider(
      providers: [
        ChangeNotifierProvider<HomeState>.value(value: home),
        ChangeNotifierProvider<LocationService>.value(value: location),
      ],
      child: const MaterialApp(home: OutletSettingsScreen()),
    );

/// Brings the location section into view.
///
/// It sits below the hours block in a lazy ListView, so on the default test
/// surface its widgets are not built at all until scrolled to — `find.byKey`
/// returns nothing rather than something off-screen.
Future<void> _showLocation(WidgetTester tester) async {
  await tester.scrollUntilVisible(
    find.byKey(OutletSettingsScreen.useLocationKey),
    200,
    scrollable: find.byType(Scrollable).first,
  );
  await tester.pumpAndSettle();
}

Future<void> _tapUseLocation(WidgetTester tester) async {
  await _showLocation(tester);
  await tester.tap(find.byKey(OutletSettingsScreen.useLocationKey));
  await tester.pumpAndSettle();
}

/// Lets the result SnackBar time out.
///
/// It is anchored to the bottom of the screen, directly over the location
/// controls, so anything tapped after a first attempt lands on the snackbar
/// instead of the button. Only a test concern — on a phone the owner simply
/// waits or swipes it away.
Future<void> _dismissSnack(WidgetTester tester) async {
  await tester.pump(const Duration(seconds: 5));
  await tester.pumpAndSettle();
}

int _count(String entry) => requestLog.where((e) => e == entry).length;

void main() {
  late _FakeGeolocator fake;
  late LocationService location;

  setUp(() {
    requestLog = [];
    lastBody = {};
    fake = _FakeGeolocator();
    GeolocatorPlatform.instance = fake;
    location = LocationService();
  });

  group('pinning the outlet', () {
    testWidgets('a granted fix is sent to /pos/outlet/location',
        (tester) async {
      fake.permission = LocationPermission.whileInUse;
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, location));
      await tester.pumpAndSettle();

      await _tapUseLocation(tester);

      expect(_count(_location), 1, reason: 'the pin must reach the server');
      expect(lastBody['latitude'], closeTo(12.97, 1e-9));
      expect(lastBody['longitude'], closeTo(77.59, 1e-9));
      expect(find.text('Location saved.'), findsOneWidget);
    });

    testWidgets('the saved pin is shown back to the owner', (tester) async {
      fake.permission = LocationPermission.whileInUse;
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, location));
      await tester.pumpAndSettle();
      await _showLocation(tester);
      expect(find.text('Not set'), findsOneWidget);

      await _tapUseLocation(tester);

      expect(find.byKey(OutletSettingsScreen.locationValueKey), findsOneWidget);
      expect(find.text('12.97000, 77.59000'), findsOneWidget);
      expect(home.outlet!.hasLocation, isTrue);
    });

    testWidgets('an already-pinned outlet offers an update instead',
        (tester) async {
      final home = await _loadedHome(_backend(latitude: 1.5, longitude: 2.5));
      await tester.pumpWidget(_host(home, location));
      await tester.pumpAndSettle();
      await _showLocation(tester);

      expect(find.text('Update to current location'), findsOneWidget);
      expect(find.text('Use current location'), findsNothing);
      expect(find.text('1.50000, 2.50000'), findsOneWidget);
    });

    testWidgets('a permission dialog is raised when it can be', (tester) async {
      // userInitiated: the tap IS the request, so the service's one-prompt
      // latch must not swallow it. Without that flag the button would visibly
      // do nothing on a second attempt after a denial.
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.whileInUse;
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, location));
      await tester.pumpAndSettle();

      await _tapUseLocation(tester);
      expect(fake.requestCount, 1);
      expect(_count(_location), 1);
    });

    testWidgets('a second tap after a denial asks again', (tester) async {
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, location));
      await tester.pumpAndSettle();

      await _tapUseLocation(tester);
      await _dismissSnack(tester);
      await _tapUseLocation(tester);

      expect(fake.requestCount, 2,
          reason: 'a deliberate tap re-asks; the latch gates only incidental '
              'callers');
    });

    testWidgets('pinning does not clobber the hours', (tester) async {
      // The endpoint returns the FULL outlet for exactly this reason: a
      // partial response would blank the schedule the owner just saved.
      fake.permission = LocationPermission.whileInUse;
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, location));
      await tester.pumpAndSettle();

      await _tapUseLocation(tester);

      expect(home.outlet!.openingTime, '09:00');
      expect(home.outlet!.closingTime, '22:00');
    });
  });

  group('nothing is saved when there is no fix', () {
    testWidgets('location turned off is reported as such', (tester) async {
      fake.serviceEnabled = false;
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, location));
      await tester.pumpAndSettle();

      await _tapUseLocation(tester);

      expect(_count(_location), 0, reason: 'no fix, nothing to save');
      expect(find.textContaining('turned off'), findsOneWidget);
    });

    testWidgets('a refusal is reported and nothing is sent', (tester) async {
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, location));
      await tester.pumpAndSettle();

      await _tapUseLocation(tester);

      expect(_count(_location), 0);
      expect(find.textContaining('declined'), findsOneWidget);
      expect(home.outlet!.hasLocation, isFalse);
    });

    testWidgets('a permanent refusal offers system settings, not a retry',
        (tester) async {
      // The OS suppresses the dialog entirely once a denial is permanent, so
      // "try again" would be a button guaranteed to do nothing.
      fake.permission = LocationPermission.deniedForever;
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, location));
      await tester.pumpAndSettle();

      await _tapUseLocation(tester);

      expect(fake.requestCount, 0, reason: 'a blocked permission is never re-asked');
      expect(find.byKey(OutletSettingsScreen.openSettingsKey), findsOneWidget);

      await _dismissSnack(tester);
      await tester.ensureVisible(
          find.byKey(OutletSettingsScreen.openSettingsKey));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(OutletSettingsScreen.openSettingsKey));
      await tester.pumpAndSettle();
      expect(fake.openAppSettingsCount, 1);
    });

    testWidgets('a failed save is reported, not silently swallowed',
        (tester) async {
      fake.permission = LocationPermission.whileInUse;
      final home = await _loadedHome(_backend(locationFails: true));
      await tester.pumpWidget(_host(home, location));
      await tester.pumpAndSettle();

      await _tapUseLocation(tester);

      expect(find.textContaining('Could not save the location'), findsOneWidget);
      expect(home.outlet!.hasLocation, isFalse,
          reason: 'a pin that did not save must not be shown as saved');
    });
  });
}

/// A scripted geolocator — the same fake customer_app drives its own copy of
/// LocationService with, since the service under test is that same file.
class _FakeGeolocator extends GeolocatorPlatform {
  LocationPermission permission = LocationPermission.denied;

  /// What the OS dialog answers when raised.
  LocationPermission grantOnRequest = LocationPermission.whileInUse;

  bool serviceEnabled = true;

  int requestCount = 0;
  int positionCount = 0;
  int openAppSettingsCount = 0;

  @override
  Future<LocationPermission> checkPermission() async => permission;

  @override
  Future<LocationPermission> requestPermission() async {
    requestCount++;
    permission = grantOnRequest;
    return permission;
  }

  @override
  Future<bool> isLocationServiceEnabled() async => serviceEnabled;

  @override
  Future<bool> openAppSettings() async {
    openAppSettingsCount++;
    return true;
  }

  @override
  Future<Position> getCurrentPosition({LocationSettings? locationSettings}) async {
    positionCount++;
    return Position(
      latitude: 12.97,
      longitude: 77.59,
      timestamp: DateTime.now(),
      accuracy: 10,
      altitude: 0,
      altitudeAccuracy: 0,
      heading: 0,
      headingAccuracy: 0,
      speed: 0,
      speedAccuracy: 0,
    );
  }
}
