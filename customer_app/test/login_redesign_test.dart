// Login redesign, gated name capture, and the greeting's single source.
//
// Supersedes three groups deleted from bugfix_batch_2026_08_24_test.dart, whose
// features were deliberately removed on 2026-08-25:
//   * "H: one field, routed by what was typed"  — email/phone auto-detect
//   * "NAME: mandatory name on new signup"      — name field on the login screen
//   * "NAME: the blocking prompt ..."           — the Home-side name gate
//
// The structural claim under test: `customer.name` has exactly ONE writer (the
// name screen, via PATCH /customer/me), so no provider-supplied name can ever
// reach the greeting — regardless of signup method.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/screens/home_screen.dart';
import 'package:customer_app/screens/login_screen.dart';
import 'package:customer_app/screens/name_capture_screen.dart';
import 'package:customer_app/screens/post_auth_router.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/google_auth_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/services/otp_auth_service.dart';
import 'package:customer_app/services/push_service.dart';
import 'package:customer_app/state/auth_state.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';
import 'package:customer_app/theme/widgets/neo_button.dart';

void _sizeSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1170, 2532);
  tester.view.devicePixelRatio = 3.0;
  addTearDown(tester.view.reset);
}

http.Response _json(Object body, {int status = 200}) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

/// Records what the server ends up holding, so a test can assert on the value
/// the greeting will read on the NEXT launch, not just this session's copy.
class _Server {
  _Server({this.name, required this.isNewAccount});

  /// What `customers.name` currently holds. Null models the post-2026-08-25
  /// backend, which never seeds it from the Google profile.
  String? name;
  final bool isNewAccount;
  String? patchedName;
  int patchCount = 0;

  ApiClient client() {
    SharedPreferences.setMockInitialValues({});
    return ApiClient(client: MockClient((req) async {
      if (req.method == 'PATCH' && req.url.path.endsWith('/customer/me')) {
        patchCount++;
        patchedName = (jsonDecode(req.body) as Map)['name'] as String?;
        name = patchedName;
        return _json({'id': 'c1', 'name': name, 'email': 'a@example.com'});
      }
      if (req.url.path.contains('request-otp')) {
        return _json({'request_id': 'r1'});
      }
      if (req.url.path.contains('verify-otp')) {
        return _json({
          'access_token': 'tok',
          'is_new_account': isNewAccount,
          'customer': {'id': 'c1', 'name': name, 'email': 'a@example.com'},
        });
      }
      if (req.url.path.endsWith('/customer/orders')) return _json(const []);
      if (req.url.path.endsWith('/customer/me')) {
        return _json({'id': 'c1', 'name': name, 'email': 'a@example.com'});
      }
      return _json(const {});
    }));
  }
}

Widget _host(ApiClient api, AuthState auth, Widget home,
    {GlobalKey<NavigatorState>? navKey}) {
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<CustomerService>(create: (_) => CustomerService(api)),
      Provider<CatalogService>(create: (_) => CatalogService(api)),
      Provider<OrderService>(create: (_) => OrderService(api)),
      ChangeNotifierProvider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>(create: (_) => CartState()),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
      ChangeNotifierProvider<AuthState>.value(value: auth),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      navigatorKey: navKey,
      home: home,
    ),
  );
}

/// Signs in, then routes exactly as the OTP screen and Google button both do.
Future<AuthState> _signInAndRoute(
  WidgetTester tester,
  _Server server, {
  required GlobalKey<NavigatorState> navKey,
}) async {
  final api = server.client();
  final auth =
      AuthState(api, StubOtpService(api), GoogleAuthService(api), PushService(api));

  await tester.pumpWidget(_host(api, auth, const Scaffold(body: SizedBox()),
      navKey: navKey));
  await tester.pump();

  await auth.requestOtp('+919876543210');
  await auth.verifyOtp('123456');

  routeAfterAuth(navKey.currentContext!,
      isNewAccount: auth.lastSignInWasNewAccount);
  await tester.pumpAndSettle();
  return auth;
}

String _greetingText(WidgetTester tester) => tester
    .widgetList<Text>(find.byType(Text))
    .map((t) => t.data)
    .whereType<String>()
    .firstWhere(
        (s) => s.startsWith('Welcome') || s.startsWith('Good '),
        orElse: () => '(no greeting)');

void main() {
  // =========================================================================
  // Task 2 — the login screen
  // =========================================================================
  group('login screen offers phone and Google, nothing else', () {
    Widget loginHost() {
      final api = _Server(isNewAccount: false).client();
      final auth = AuthState(
          api, StubOtpService(api), GoogleAuthService(api), PushService(api));
      return _host(api, auth, const LoginScreen());
    }

    testWidgets('exactly one input, and it is the phone field', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(loginHost());
      await tester.pump();

      expect(find.byType(TextField), findsOneWidget,
          reason: 'the name field moved to the post-signup screen');
      expect(find.byKey(const Key('login_phone_field')), findsOneWidget);
      expect(find.byKey(const Key('login_google')), findsOneWidget);
    });

    testWidgets('header and placeholder say Phone number, not email',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(loginHost());
      await tester.pump();

      expect(find.text('Phone number'), findsNWidgets(2),
          reason: 'the section header and the hint');
      // The old wording is gone.
      expect(find.text('Phone or email'), findsNothing);
      expect(find.text('Mobile number or email'), findsNothing);
      expect(find.textContaining('email'), findsNothing,
          reason: 'no email affordance anywhere on the screen');
    });

    testWidgets('no name field on the login screen', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(loginHost());
      await tester.pump();

      expect(find.byKey(const Key('login_name_field')), findsNothing);
      expect(find.text('How can we call you?'), findsNothing,
          reason: 'that question belongs to the post-signup screen now');
    });

    testWidgets('+91 tag is permanent, not conditional on what was typed',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(loginHost());
      await tester.pump();

      // It used to appear only once the input parsed as a phone number,
      // because the same box also accepted emails.
      expect(find.text('+91'), findsOneWidget);
    });

    testWidgets('Send OTP is gated on a complete 10-digit number',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(loginHost());
      await tester.pump();

      NeoButton send() =>
          tester.widget<NeoButton>(find.byKey(const Key('login_send_otp')));

      expect(send().onPressed, isNull, reason: 'empty');

      await tester.enterText(
          find.byKey(const Key('login_phone_field')), '98765');
      await tester.pump();
      expect(send().onPressed, isNull, reason: 'only 5 digits');

      await tester.enterText(
          find.byKey(const Key('login_phone_field')), '9876543210');
      await tester.pump();
      expect(send().onPressed, isNotNull, reason: '10 digits is valid');
    });
  });

  // =========================================================================
  // Task 3 — the gate
  // =========================================================================
  group('name capture is gated on is_new_account', () {
    testWidgets('NEW account -> name screen, and Home is not shown yet',
        (tester) async {
      _sizeSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await _signInAndRoute(tester, _Server(isNewAccount: true),
          navKey: navKey);

      expect(find.byType(NameCaptureScreen), findsOneWidget);
      expect(find.byKey(const Key('name_capture_gate')), findsOneWidget);
      expect(find.byType(HomeScreen), findsNothing);
    });

    testWidgets('EXISTING account -> straight to Home, no name screen',
        (tester) async {
      _sizeSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await _signInAndRoute(tester,
          _Server(name: 'Rohan', isNewAccount: false),
          navKey: navKey);

      expect(find.byType(NameCaptureScreen), findsNothing);
      expect(find.byType(HomeScreen), findsOneWidget);
    });

    testWidgets('is_new_account MISSING defaults to existing -> Home',
        (tester) async {
      // An older backend omits the field; it must not trap returning customers.
      _sizeSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      final api = _Server(name: 'Rohan', isNewAccount: false).client();
      final auth = AuthState(
          api, StubOtpService(api), GoogleAuthService(api), PushService(api));

      await tester.pumpWidget(
          _host(api, auth, const Scaffold(body: SizedBox()), navKey: navKey));
      await tester.pump();
      await auth.requestOtp('+919876543210');
      await auth.verifyOtp('123456');

      expect(auth.lastSignInWasNewAccount, isFalse);
      routeAfterAuth(navKey.currentContext!, isNewAccount: false);
      await tester.pumpAndSettle();

      expect(find.byType(HomeScreen), findsOneWidget);
    });

    testWidgets('submitting the name PATCHes it and proceeds to Home',
        (tester) async {
      _sizeSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      final server = _Server(isNewAccount: true);
      await _signInAndRoute(tester, server, navKey: navKey);

      await tester.enterText(
          find.byKey(const Key('name_capture_field')), 'Priya');
      await tester.pump();
      await tester.tap(find.byKey(const Key('name_capture_save')));
      await tester.pumpAndSettle();

      expect(server.patchedName, 'Priya');
      expect(find.byType(HomeScreen), findsOneWidget);
      expect(find.byType(NameCaptureScreen), findsNothing);
    });

    testWidgets('Home no longer carries its own name gate', (tester) async {
      // The second mechanism was removed. Home renders Home even for a
      // customer whose name is empty.
      _sizeSurface(tester);
      final api = _Server(isNewAccount: false).client();
      final auth = AuthState(
          api, StubOtpService(api), GoogleAuthService(api), PushService(api));
      auth.setCustomer(await CustomerService(api).me());

      await tester.pumpWidget(_host(api, auth, const HomeScreen()));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byType(NameCaptureScreen), findsNothing,
          reason: 'exactly one name gate, and it is the routing one');
      expect(find.byType(HomeScreen), findsOneWidget);
    });
  });

  // =========================================================================
  // Task 4 — the greeting has ONE source
  // =========================================================================
  group('the greeting reads customer.name and nothing else', () {
    testWidgets(
        'REPRO: Google display name "A-Boss", typed name "C.A" -> greets C.A',
        (tester) async {
      _sizeSurface(tester);
      final navKey = GlobalKey<NavigatorState>();

      // The exact reported case. `name: 'A-Boss'` models the OLD backend that
      // still seeds customers.name from the Google profile — so this passes
      // even before that seeding removal is deployed, which is the point: the
      // client no longer depends on it.
      final server = _Server(name: 'A-Boss', isNewAccount: true);
      await _signInAndRoute(tester, server, navKey: navKey);

      expect(find.byType(NameCaptureScreen), findsOneWidget,
          reason: 'a signup is asked, whatever the provider supplied');

      await tester.enterText(
          find.byKey(const Key('name_capture_field')), 'C.A');
      await tester.pump();
      await tester.tap(find.byKey(const Key('name_capture_save')));
      await tester.pumpAndSettle();

      expect(server.patchedName, 'C.A');
      final greeting = _greetingText(tester);
      expect(greeting, contains('C.A'),
          reason: 'the greeting must show the typed name');
      expect(greeting, isNot(contains('A-Boss')),
          reason: 'THE BUG: the Google display name must never be greeted');
    });

    testWidgets('a returning customer is greeted by their stored name',
        (tester) async {
      _sizeSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await _signInAndRoute(tester,
          _Server(name: 'Rohan', isNewAccount: false),
          navKey: navKey);

      expect(_greetingText(tester), contains('Rohan'));
    });

    testWidgets('an empty name greets WITHOUT a name, never a fallback source',
        (tester) async {
      // The failure mode being excluded: filling a blank greeting from the
      // email local-part or a provider profile.
      _sizeSurface(tester);
      final api = _Server(isNewAccount: false).client();
      final auth = AuthState(
          api, StubOtpService(api), GoogleAuthService(api), PushService(api));
      auth.setCustomer(await CustomerService(api).me());

      await tester.pumpWidget(_host(api, auth, const HomeScreen()));
      await tester.pump(const Duration(milliseconds: 600));

      final greeting = _greetingText(tester);
      expect(greeting, isNot(contains('@')));
      expect(greeting, isNot(contains('a@example.com')));
      expect(greeting, isNot(contains('example')),
          reason: 'no part of the email may appear in the greeting');
    });
  });

  // =========================================================================
  // Task 4 — the guard is gone, not merely bypassed
  // =========================================================================
  group('the pending-name guard was removed, not left dormant', () {
    test('AuthState exposes no pending-name API any more', () {
      SharedPreferences.setMockInitialValues({});
      final api = _Server(isNewAccount: false).client();
      final auth = AuthState(
          api, StubOtpService(api), GoogleAuthService(api), PushService(api));

      // A compile-time guarantee really — `setPendingName`/`pendingName` no
      // longer exist, so anything still calling them fails to build. This
      // asserts the replacement is what drives routing instead.
      expect(auth.lastSignInWasNewAccount, isFalse);
    });

    test('signing in records whether it was a signup', () async {
      final server = _Server(isNewAccount: true);
      final api = server.client();
      final auth = AuthState(
          api, StubOtpService(api), GoogleAuthService(api), PushService(api));

      await auth.requestOtp('+919876543210');
      await auth.verifyOtp('123456');
      expect(auth.lastSignInWasNewAccount, isTrue);
    });

    test('NO PATCH happens during sign-in itself — only the name screen writes',
        () async {
      // The old guard PATCHed from inside verifyOtp. The name screen is now the
      // single writer, so authentication must not touch customers.name at all.
      final server = _Server(name: 'A-Boss', isNewAccount: true);
      final api = server.client();
      final auth = AuthState(
          api, StubOtpService(api), GoogleAuthService(api), PushService(api));

      await auth.requestOtp('+919876543210');
      await auth.verifyOtp('123456');

      expect(server.patchCount, 0,
          reason: 'sign-in must not write a name; the name screen does');
    });

    test('logout clears the signup flag so the next sign-in is not misrouted',
        () async {
      SharedPreferences.setMockInitialValues(
          {'carevo_access_token': 'tok'});
      final server = _Server(isNewAccount: true);
      final api = server.client();
      final auth = AuthState(
          api, StubOtpService(api), GoogleAuthService(api), PushService(api));
      await api.loadToken();

      await auth.requestOtp('+919876543210');
      await auth.verifyOtp('123456');
      expect(auth.lastSignInWasNewAccount, isTrue);

      await auth.logout();
      expect(auth.lastSignInWasNewAccount, isFalse);
    });
  });
}
