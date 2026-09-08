// Cart storage is scoped to the signed-in customer (2026-08-25).
//
// The bug: `carevo_cart_v1` was ONE global SharedPreferences key. Logout
// cleared the session token and nothing else, so the next account to sign in on
// the device — a brand-new one included — inherited the previous customer's
// basket, the outlet it was bound to, and the "Continue where you left off"
// banner naming that restaurant.
//
// These tests assert the BEHAVIOUR (no basket ever crosses an identity), not
// the shape of the fix, except where the key scheme itself is the thing being
// pinned — a future "simplification" back to a single key is exactly what this
// file exists to stop.
//
// The five identity-change paths are tested SEPARATELY and each drives the real
// AuthState method, because they do not share a call site: two of them
// (Google-over-a-live-session, and 401 session loss) never touch logout() at
// all, which is why clearing the cart inside logout() would have looked correct
// and still leaked.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/customer.dart';
import 'package:customer_app/models/menu.dart';
import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/screens/home_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/google_auth_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/services/otp_auth_service.dart';
import 'package:customer_app/services/push_service.dart';
import 'package:customer_app/state/auth_state.dart';
import 'package:customer_app/state/cart_identity_sync.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

const String idA = 'customer-A';
const String idB = 'customer-B';

http.Response _json(Object body, {int status = 200}) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

Map<String, dynamic> _customerJson(String id, String name) => {
      'id': id,
      'name': name,
      'phone_number': '+9190000000${id.characters.last}',
    };

/// Signs whoever asks in as [id]; everything else answers `{}`.
///
/// [override] lets one test make `/customer/orders` answer 401, so the
/// session-loss path is driven by a real failing request rather than simulated.
ApiClient _api(
  String id, {
  String name = 'Asha',
  http.Response? Function(http.Request)? override,
}) =>
    ApiClient(client: MockClient((req) async {
      final o = override?.call(req);
      if (o != null) return o;
      if (req.url.path.endsWith('/customer/auth/request-otp')) {
        return _json({'request_id': 'r1'});
      }
      if (req.url.path.endsWith('/customer/auth/verify-otp')) {
        return _json({
          'access_token': 'token-$id',
          'customer': _customerJson(id, name),
          'is_new_account': false,
        });
      }
      if (req.url.path.endsWith('/customer/me')) {
        return _json(_customerJson(id, name));
      }
      if (req.url.path.endsWith('/customer/orders')) return _json(const []);
      return _json(const {});
    }));

/// Drives [AuthState.signInWithGoogle] without the Google plugin.
///
/// Only the plugin round trip is faked — the AuthState path under test
/// (`_customer = result.customer; notifyListeners()`) is the real one, which is
/// the whole point: this scenario escapes logout-based fixes.
class _FakeGoogleAuth extends GoogleAuthService {
  _FakeGoogleAuth(this.client, this.id, this.name) : super(client);

  final ApiClient client;
  final String id;
  final String name;

  @override
  Future<AuthResult?> signIn() async {
    await client.setToken('token-$id');
    return AuthResult(
      accessToken: 'token-$id',
      customer: Customer.fromJson(_customerJson(id, name)),
      isNewAccount: false,
    );
  }

  @override
  Future<void> signOut() async {}
}

final Outlet meenakshiBhavan = Outlet.fromJson({
  'id': 'outlet-meenakshi',
  'name': 'Meenakshi Bhavan',
  'address': 'T Nagar, Chennai',
  'is_open': true,
});

final Outlet goldenWok = Outlet.fromJson({
  'id': 'outlet-wok',
  'name': 'Golden Wok',
  'address': 'Anna Nagar, Chennai',
  'is_open': true,
});

MenuItem _dosa() => MenuItem.fromJson({
      'id': 'item-dosa',
      'name': 'Masala Dosa',
      'base_price': 90.0,
      'is_veg': true,
      'is_available': true,
      'prep_time_minutes': 10,
      'tags': const <String>[],
      'customizations': const [],
    });

/// A cart + auth pair wired exactly as `main()` wires them.
class Rig {
  Rig(this.api, this.auth, this.cart, this.sync);
  final ApiClient api;
  final AuthState auth;
  final CartState cart;
  final CartIdentitySync sync;

  Future<void> signInAsA() async {
    await auth.requestOtp('+919000000001');
    await auth.verifyOtp('000000');
    await sync.settled;
  }

  Future<void> addTwoDosasAt(Outlet outlet) async {
    cart.setOutlet(outlet);
    cart.addItem(_dosa(), quantity: 2);
    await cart.flush();
  }
}

Future<Rig> buildRig({
  String id = idA,
  GoogleAuthService? google,
  http.Response? Function(http.Request)? override,
}) async {
  final api = _api(id, override: override);
  await api.loadToken();
  final cart = CartState();
  await cart.restore();
  final auth = AuthState(
    api,
    StubOtpService(api),
    google ?? _FakeGoogleAuth(api, id, 'Asha'),
    PushService(api),
  );
  final sync = CartIdentitySync(auth, cart)..start();
  await sync.settled;
  return Rig(api, auth, cart, sync);
}

Future<Map<String, Object?>> dumpPrefs() async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.reload();
  return {
    for (final k in prefs.getKeys()) k: prefs.get(k),
  };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  // =========================================================================
  // 1 — the key scheme
  // =========================================================================
  group('key scheme: one blob per identity', () {
    test('a signed-in cart writes to a key carrying the customer id', () async {
      SharedPreferences.setMockInitialValues({});
      final rig = await buildRig();
      await rig.signInAsA();
      await rig.addTwoDosasAt(meenakshiBhavan);

      final prefs = await dumpPrefs();
      expect(rig.cart.scope, idA);
      expect(prefs.containsKey('carevo_cart_v1_$idA'), isTrue);
      // The old global key must never be written again.
      expect(prefs.containsKey(CartState.legacyGlobalKey), isFalse);
    });

    test('the logged-out cart uses a separate guest key', () async {
      SharedPreferences.setMockInitialValues({});
      final cart = CartState();
      await cart.restore();
      cart.setOutlet(meenakshiBhavan);
      cart.addItem(_dosa());
      await cart.flush();

      final prefs = await dumpPrefs();
      expect(cart.scope, CartState.guestScope);
      expect(prefs.containsKey('carevo_cart_v1_guest'), isTrue);
      expect(prefs.containsKey(CartState.legacyGlobalKey), isFalse);
    });

    test('a legacy global blob is DELETED at restore, never adopted', () async {
      // A device upgrading from a pre-scoping build. The blob records no owner,
      // so it cannot be attributed — adopting it into whoever opens the app
      // next is the bug itself.
      SharedPreferences.setMockInitialValues({
        CartState.legacyGlobalKey: jsonEncode({
          'outlet': meenakshiBhavan.toJson(),
          'items': const [],
          'line_counter': 0,
        }),
      });

      final cart = CartState();
      await cart.restore();

      expect(cart.isEmpty, isTrue);
      expect(cart.outlet, isNull);
      final prefs = await dumpPrefs();
      expect(prefs.containsKey(CartState.legacyGlobalKey), isFalse,
          reason: 'the unattributable blob is removed, not left to be found');
    });
  });

  // =========================================================================
  // 2 — the five identity-change paths
  // =========================================================================
  group('identity change re-scopes the cart', () {
    test('1/5 sign-in: the account does NOT inherit the guest basket',
        () async {
      SharedPreferences.setMockInitialValues({});
      final rig = await buildRig();

      // Built while logged out.
      await rig.addTwoDosasAt(meenakshiBhavan);
      expect(rig.cart.scope, CartState.guestScope);
      expect(rig.cart.totalQuantity, 2);

      await rig.signInAsA();

      expect(rig.cart.scope, idA);
      expect(rig.cart.isEmpty, isTrue,
          reason: 'guest basket is discarded at sign-in, not merged');
      expect(rig.cart.outlet, isNull);
    });

    test('2/5 logout: the basket leaves with the session', () async {
      SharedPreferences.setMockInitialValues({});
      final rig = await buildRig();
      await rig.signInAsA();
      await rig.addTwoDosasAt(meenakshiBhavan);

      await rig.auth.logout();
      await rig.sync.settled;

      expect(rig.cart.scope, CartState.guestScope);
      expect(rig.cart.isEmpty, isTrue);
      expect(rig.cart.outlet, isNull);
      // A's own basket is preserved under A's key — scoping, not deletion.
      final prefs = await dumpPrefs();
      expect(prefs['carevo_cart_v1_$idA'].toString(), contains('Meenakshi'));
    });

    test('3/5 Google sign-in OVER a live session — never touches logout()',
        () async {
      SharedPreferences.setMockInitialValues({});
      // Signs in as A by OTP, then a Google sign-in returns B without anyone
      // logging out. This is the path the diagnostic found escaping every
      // logout-based fix.
      final api = _api(idA);
      await api.loadToken();
      final cart = CartState();
      await cart.restore();
      final auth = AuthState(
        api,
        StubOtpService(api),
        _FakeGoogleAuth(api, idB, 'Bala'),
        PushService(api),
      );
      final sync = CartIdentitySync(auth, cart)..start();
      await sync.settled;

      await auth.requestOtp('+919000000001');
      await auth.verifyOtp('000000');
      await sync.settled;
      cart.setOutlet(meenakshiBhavan);
      cart.addItem(_dosa(), quantity: 2);
      await cart.flush();
      expect(cart.scope, idA);

      // No logout anywhere in here.
      final ok = await auth.signInWithGoogle();
      await sync.settled;

      expect(ok, isTrue);
      expect(auth.customer?.id, idB);
      expect(cart.scope, idB, reason: 'the switch re-scoped without a logout');
      expect(cart.isEmpty, isTrue);
      expect(cart.outlet, isNull);
    });

    test('4/5 account deletion', () async {
      SharedPreferences.setMockInitialValues({});
      final rig = await buildRig();
      await rig.signInAsA();
      await rig.addTwoDosasAt(meenakshiBhavan);

      // The real screen calls deleteAccount() then logout().
      await CustomerService(rig.api).deleteAccount();
      await rig.auth.logout();
      await rig.sync.settled;

      expect(rig.cart.scope, CartState.guestScope);
      expect(rig.cart.isEmpty, isTrue);
    });

    test('5/5 session loss: a 401 from a background request re-scopes',
        () async {
      SharedPreferences.setMockInitialValues({});
      final rig = await buildRig(
        override: (req) => req.url.path.endsWith('/customer/orders')
            ? _json({'detail': 'Not authenticated'}, status: 401)
            : null,
      );
      await rig.signInAsA();
      await rig.addTwoDosasAt(meenakshiBhavan);
      expect(rig.cart.scope, idA);

      // No screen involved, no logout called — just a request that 401s.
      await expectLater(
        CustomerService(rig.api).orders(),
        throwsA(isA<AuthExpiredException>()),
      );
      await rig.sync.settled;

      expect(rig.auth.customer, isNull);
      expect(rig.cart.scope, CartState.guestScope);
      expect(rig.cart.isEmpty, isTrue);
    });
  });

  // =========================================================================
  // 3 — the original two-account reproduction
  // =========================================================================
  group('two accounts on one device (the reported bug)', () {
    test("B's cold start does not adopt A's cart from disk", () async {
      SharedPreferences.setMockInitialValues({});
      final rig = await buildRig();
      await rig.signInAsA();
      await rig.addTwoDosasAt(meenakshiBhavan);
      await rig.auth.logout();
      await rig.sync.settled;

      // B signs in on a fresh process (new CartState, same device).
      final apiB = _api(idB, name: 'Bala');
      await apiB.loadToken();
      final cartB = CartState();
      await cartB.restore();
      final authB = AuthState(
          apiB, StubOtpService(apiB), _FakeGoogleAuth(apiB, idB, 'Bala'), PushService(apiB));
      final syncB = CartIdentitySync(authB, cartB)..start();
      await authB.requestOtp('+919000000002');
      await authB.verifyOtp('000000');
      await syncB.settled;

      expect(cartB.scope, idB);
      expect(cartB.isEmpty, isTrue);
      expect(cartB.outlet, isNull);
      expect(cartB.totalQuantity, 0);
    });

    test('A signing back in still finds A\'s basket', () async {
      SharedPreferences.setMockInitialValues({});
      final rig = await buildRig();
      await rig.signInAsA();
      await rig.addTwoDosasAt(meenakshiBhavan);
      await rig.auth.logout();
      await rig.sync.settled;
      expect(rig.cart.isEmpty, isTrue);

      await rig.signInAsA();

      expect(rig.cart.scope, idA);
      expect(rig.cart.totalQuantity, 2,
          reason: 'scoping must not mean losing your own cart');
      expect(rig.cart.outlet?.name, 'Meenakshi Bhavan');
    });

    testWidgets("B's Home shows no resume banner and no trace of A's outlet",
        (tester) async {
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.reset);

      SharedPreferences.setMockInitialValues({});
      // A orders at Meenakshi Bhavan, then logs out.
      final rig = await buildRig();
      await rig.signInAsA();
      await rig.addTwoDosasAt(meenakshiBhavan);
      await rig.auth.logout();
      await rig.sync.settled;

      // B signs in on the SAME process — the CartState instance survives a
      // logout in the real app, so this reuses it deliberately.
      final apiB = _api(idB, name: 'Bala');
      await apiB.loadToken();
      final authB = AuthState(
          apiB, StubOtpService(apiB), _FakeGoogleAuth(apiB, idB, 'Bala'), PushService(apiB));
      final syncB = CartIdentitySync(authB, rig.cart)..start();
      await authB.requestOtp('+919000000002');
      await authB.verifyOtp('000000');
      await syncB.settled;

      await tester.pumpWidget(MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: apiB),
          Provider<CustomerService>(create: (_) => CustomerService(apiB)),
          Provider<CatalogService>(create: (_) => CatalogService(apiB)),
          Provider<OrderService>(create: (_) => OrderService(apiB)),
          ChangeNotifierProvider<LocationService>(create: (_) => LocationService()),
          ChangeNotifierProvider<CartState>.value(value: rig.cart),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
          ChangeNotifierProvider<AuthState>.value(value: authB),
        ],
        child: MaterialApp(theme: AppTheme.light(), home: const HomeScreen()),
      ));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('home_first_run')), findsOneWidget,
          reason: 'B has never ordered');
      expect(find.byKey(const Key('home_resume_cart')), findsNothing);
      expect(find.text('Continue where you left off'), findsNothing);
      expect(find.textContaining('Meenakshi Bhavan'), findsNothing);
    });
  });

  // =========================================================================
  // 4 — guest cart policy
  // =========================================================================
  group('guest cart is discarded at sign-in, never merged', () {
    test('the guest blob is removed when a real identity takes over', () async {
      SharedPreferences.setMockInitialValues({});
      final rig = await buildRig();
      await rig.addTwoDosasAt(meenakshiBhavan);
      expect((await dumpPrefs()).containsKey('carevo_cart_v1_guest'), isTrue);

      await rig.signInAsA();

      final prefs = await dumpPrefs();
      expect(prefs.containsKey('carevo_cart_v1_guest'), isFalse,
          reason: 'a discarded guest basket must not linger for the next '
              'logged-out person on this device');
      expect(prefs.containsKey('carevo_cart_v1_$idA'), isFalse,
          reason: 'and it must not have been copied into the account either');
    });

    test('logging out lands on an EMPTY guest cart, not the account\'s',
        () async {
      SharedPreferences.setMockInitialValues({});
      final rig = await buildRig();
      await rig.signInAsA();
      await rig.addTwoDosasAt(goldenWok);
      await rig.auth.logout();
      await rig.sync.settled;

      expect(rig.cart.scope, CartState.guestScope);
      expect(rig.cart.isEmpty, isTrue);
      expect(rig.cart.outlet?.name, isNot('Golden Wok'));
    });
  });

  // =========================================================================
  // 5 — a write in flight cannot cross the boundary
  // =========================================================================
  test('a queued write lands under the scope that produced it', () async {
    SharedPreferences.setMockInitialValues({});
    final rig = await buildRig();
    await rig.signInAsA();

    // Mutate and switch identity WITHOUT awaiting the write: this is the real
    // ordering when someone taps add and immediately signs out.
    rig.cart.setOutlet(meenakshiBhavan);
    rig.cart.addItem(_dosa(), quantity: 2);
    await rig.cart.setIdentity(idB);
    await rig.cart.flush();

    final prefs = await dumpPrefs();
    expect(prefs['carevo_cart_v1_$idA'].toString(), contains('Meenakshi'),
        reason: 'the in-flight write belongs to A');
    expect(prefs.containsKey('carevo_cart_v1_$idB'), isFalse,
        reason: "and must never be filed under B's identity");
    expect(rig.cart.isEmpty, isTrue);
  });
}
