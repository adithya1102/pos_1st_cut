// Owner-facing hours + "temporarily closed" toggle (migration 024).
//
// The owner sets their own restaurant's hours here — owner_app, alongside the
// visibility and storefront-photo controls that already talk to /pos/outlet.
// These drive the real HomeState/OutletService over a MockClient, so the JSON
// contract and the state layer are exercised together: the request log is the
// proof the toggle and Save actually hit the endpoints, which a screen
// assertion alone would not show.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/screens/outlet_settings_screen.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/menu_service.dart';
import 'package:owner_app/services/outlet_service.dart';
import 'package:owner_app/state/home_state.dart';

late List<String> requestLog;
late Map<String, dynamic> lastBody;

const _outletId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

/// A backend for one outlet. Hours/closed mutate a little in-memory record so
/// the returned outlet reflects the change, like the real endpoint.
http.Client _backend({
  String? opening = '09:00',
  String? closing = '22:00',
  bool manuallyClosed = false,
  String orderStatus = 'open',
}) {
  var open = opening, close = closing, closed = manuallyClosed, status = orderStatus;
  Map<String, dynamic> outletJson() => {
        'id': _outletId,
        'location_name': 'Anand Bhavan',
        'is_visible': true,
        'image_url': null,
        'opening_time': open,
        'closing_time': close,
        'is_manually_closed': closed,
        'order_status': status,
      };
  http.Response json(Object b) => http.Response(jsonEncode(b), 200,
      headers: {'content-type': 'application/json'});

  return MockClient((req) async {
    final path = req.url.path;
    final body = req.body.isEmpty
        ? <String, dynamic>{}
        : jsonDecode(req.body) as Map<String, dynamic>;
    requestLog.add('${req.method} $path');
    if (req.method != 'GET') lastBody = body;

    if (path.endsWith('/pos/menu-items')) return json(const <dynamic>[]);
    if (path.endsWith('/pos/outlet/hours')) {
      open = body['opening_time'] as String?;
      close = body['closing_time'] as String?;
      return json(outletJson());
    }
    if (path.endsWith('/pos/outlet/closed')) {
      closed = body['is_manually_closed'] as bool? ?? false;
      status = closed ? 'closed' : 'open';
      return json(outletJson());
    }
    if (path.endsWith('/pos/outlet')) return json(outletJson());
    return http.Response(jsonEncode({'detail': 'unexpected ${req.url}'}), 404,
        headers: {'content-type': 'application/json'});
  });
}

Future<HomeState> _loadedHome(http.Client backend) async {
  SharedPreferences.setMockInitialValues({'gusto_owner_access_token': 'staff'});
  final api = ApiClient(httpClient: backend);
  final home = HomeState(OutletService(api), MenuService(api));
  await home.load();
  return home;
}

Widget _host(HomeState home) => ChangeNotifierProvider<HomeState>.value(
      value: home,
      child: const MaterialApp(home: OutletSettingsScreen()),
    );

int _count(String entry) => requestLog.where((e) => e == entry).length;

const _hours = 'PATCH /api/v1/pos/outlet/hours';
const _closed = 'POST /api/v1/pos/outlet/closed';

void main() {
  setUp(() {
    requestLog = [];
    lastBody = {};
  });

  testWidgets('shows the current status the customer would see', (tester) async {
    final home = await _loadedHome(_backend(orderStatus: 'closing_soon'));
    await tester.pumpWidget(_host(home));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('settings_status_label')), findsOneWidget);
    expect(find.text('Closing soon'), findsWidgets);
  });

  testWidgets('toggling "temporarily closed" calls the endpoint and updates',
      (tester) async {
    final home = await _loadedHome(_backend());
    await tester.pumpWidget(_host(home));
    await tester.pumpAndSettle();

    expect(find.text('Open'), findsWidgets);

    await tester.tap(find.byKey(OutletSettingsScreen.manualToggleKey));
    await tester.pumpAndSettle();

    expect(_count(_closed), 1, reason: 'the toggle must hit /pos/outlet/closed');
    expect(lastBody['is_manually_closed'], isTrue);
    // The screen reflects the server's recomputed status.
    expect(find.text('Closed'), findsWidgets);
    expect(home.outlet!.isManuallyClosed, isTrue);
  });

  testWidgets('Save hours sends the schedule to /pos/outlet/hours',
      (tester) async {
    final home = await _loadedHome(_backend(opening: '08:00', closing: '20:00'));
    await tester.pumpWidget(_host(home));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(OutletSettingsScreen.saveHoursKey));
    await tester.pumpAndSettle();

    expect(_count(_hours), 1, reason: 'Save must hit /pos/outlet/hours');
    expect(lastBody['opening_time'], '08:00');
    expect(lastBody['closing_time'], '20:00');
    expect(find.text('Hours saved.'), findsOneWidget);
  });

  testWidgets('the toggle is independent of the hours — one Save, one toggle',
      (tester) async {
    final home = await _loadedHome(_backend());
    await tester.pumpWidget(_host(home));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(OutletSettingsScreen.manualToggleKey));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(OutletSettingsScreen.saveHoursKey));
    await tester.pumpAndSettle();

    // Each control hit only its OWN endpoint — they do not bleed into each
    // other (a combined settings blob would have made this impossible to tell).
    expect(_count(_closed), 1);
    expect(_count(_hours), 1);
  });
}
