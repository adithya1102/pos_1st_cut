// Keyboard dismissal on the checkout (payment) screen.
//
// The screen's one text input is the COUPON field. It is a raw TextField
// rather than a NeoTextField — it needs the label + prefix-icon decoration —
// which is exactly how it missed the dismissal handling NeoTextField already
// carries. See NeoTextField.onTapOutside for the underlying Android behaviour:
// a TextField with a null onTapOutside keeps focus when you tap away, so the
// IME stays up AND the caret keeps blinking.
//
// Three ways a field stops being the thing you are using, all asserted here:
// its own confirm key, the phone's back button, and a tap somewhere else.
//
// Each also asserts checkout is RESUMABLE afterwards — the typed code survives
// and the Pay button still works — because a dismissal that quietly resets the
// screen would be a worse bug than the one being fixed.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/menu.dart';
import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/screens/checkout_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/cashfree_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/services/places_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

const _couponKey = Key('checkout_coupon_field');

Outlet _outlet() => Outlet.fromJson({
      'id': 'o1',
      'location_name': 'Test Kitchen',
      'name': 'Test Kitchen',
      'address': 'Somewhere',
      'is_open': true,
    });

MenuItem _menuItem() => MenuItem.fromJson({
      'id': 'm1',
      'name': 'Masala Dosa',
      'base_price': 120,
      'is_veg': true,
      'is_available': true,
    });

CartState _cartWithItems() {
  final cart = CartState();
  cart.setOutlet(_outlet());
  cart.addItem(_menuItem(), quantity: 2);
  return cart;
}

ApiClient _api() {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
  return ApiClient(client: MockClient((req) async => http.Response(
        jsonEncode(const {}), 200,
        headers: {'content-type': 'application/json'},
      )));
}

final _navKey = GlobalKey<NavigatorState>();

/// Checkout pushed ON TOP of a base route, so there is something to pop back
/// to. With checkout as `home:` the back button can never succeed, which would
/// make "back does not leave checkout" pass for the wrong reason.
Widget _host(CartState cart) {
  final api = _api();
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<OrderService>(create: (_) => OrderService(api)),
      Provider<CashfreeService>(create: (_) => CashfreeService()),
      Provider<LocationService>(create: (_) => LocationService()),
      Provider<PlacesService>(create: (_) => PlacesService()),
      ChangeNotifierProvider<CartState>.value(value: cart),
      ChangeNotifierProvider(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      navigatorKey: _navKey,
      home: const Scaffold(body: Center(child: Text('base route'))),
    ),
  );
}

/// True when the COUPON FIELD holds focus — which is the state that keeps the
/// soft keyboard up.
///
/// Deliberately the field's own node, not `FocusManager.primaryFocus`: that
/// falls back to the enclosing scope, which reports hasFocus even when no
/// editable is focused, so it reads "keyboard up" on a screen nobody has
/// touched. Asserting focus rather than "is the IME visible" is the point —
/// the IME is the platform's rendering of this flag, and this flag is the bug.
String _couponText(WidgetTester tester) =>
    tester.widget<TextField>(find.byKey(_couponKey)).controller?.text ?? '';

bool _keyboardUp(WidgetTester tester) =>
    tester.widget<TextField>(find.byKey(_couponKey)).focusNode?.hasFocus ??
    false;

Future<void> _openKeyboard(WidgetTester tester) async {
  await tester.tap(find.byKey(_couponKey));
  await tester.pump();
  expect(_keyboardUp(tester), isTrue,
      reason: 'precondition: the field took focus');
}

void main() {
  Future<void> pumpCheckout(WidgetTester tester, CartState cart) async {
    // Tall surface so the whole of checkout lays out at once. The screen has
    // more than one Scrollable (the body plus the horizontal transport-mode
    // strip), so scrolling to the field would need to name one; giving it room
    // avoids the ambiguity entirely.
    tester.view.physicalSize = const Size(1400, 7000);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_host(cart));
    await tester.pump();
    unawaited(_navKey.currentState!.push(
        MaterialPageRoute(builder: (_) => const CheckoutScreen())));
    await tester.pumpAndSettle();
    await tester.pump(const Duration(milliseconds: 300));
    await tester.ensureVisible(find.byKey(_couponKey));
    await tester.pump();
  }

  group('checkout keyboard dismissal', () {
    testWidgets('the keyboard opens at all — the baseline the rest rely on',
        (tester) async {
      await pumpCheckout(tester, _cartWithItems());
      expect(_keyboardUp(tester), isFalse, reason: 'nothing focused on arrival');
      await _openKeyboard(tester);
    });

    testWidgets("the keyboard's own confirm key dismisses it", (tester) async {
      await pumpCheckout(tester, _cartWithItems());
      await tester.enterText(find.byKey(_couponKey), 'PTS-ABCD2345');
      await tester.pump();
      expect(_keyboardUp(tester), isTrue);

      // The action key on the IME. TextInputAction.done + onSubmitted is what
      // makes this do anything; without them the key is inert.
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pump();

      expect(_keyboardUp(tester), isFalse, reason: 'confirm must close the keyboard');
      // ...and the work is not thrown away.
      expect(_couponText(tester), 'PTS-ABCD2345');
      expect(find.byKey(const Key('checkout_pay')), findsOneWidget,
          reason: 'checkout must still be usable');
    });

    testWidgets('the back button closes the keyboard instead of leaving',
        (tester) async {
      await pumpCheckout(tester, _cartWithItems());
      await tester.enterText(find.byKey(_couponKey), 'PTS-BACK0001');
      await tester.pump();
      expect(_keyboardUp(tester), isTrue);

      // The real system back, routed through PopScope exactly as Android does.
      await tester.binding.handlePopRoute();
      await tester.pump();

      expect(_keyboardUp(tester), isFalse, reason: 'back must close the keyboard');
      // The screen is STILL checkout — this is the half that would regress if
      // PopScope.canPop were left true.
      expect(find.byType(CheckoutScreen), findsOneWidget,
          reason: 'the first back must not leave checkout');
      expect(_couponText(tester), 'PTS-BACK0001');
    });

    testWidgets('a second back, once the keyboard is down, does leave',
        (tester) async {
      // The counterpart to the test above: consuming back must not TRAP the
      // customer on checkout. Once nothing is focused, back pops normally.
      await pumpCheckout(tester, _cartWithItems());
      await _openKeyboard(tester);

      await tester.binding.handlePopRoute();   // closes the keyboard
      await tester.pump();
      expect(_keyboardUp(tester), isFalse);

      // canPop is true again now that focus is gone.
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(find.byType(CheckoutScreen), findsNothing,
          reason: 'with the keyboard down, back must be free to leave');
      expect(find.text('base route'), findsOneWidget);
    });

    testWidgets('tapping outside the field dismisses the keyboard',
        (tester) async {
      await pumpCheckout(tester, _cartWithItems());
      await tester.enterText(find.byKey(_couponKey), 'PTS-TAPOUT01');
      await tester.pump();
      expect(_keyboardUp(tester), isTrue);

      // Somewhere that is plainly not the field: the Payment heading.
      await tester.tap(find.text('Payment'), warnIfMissed: false);
      await tester.pump();

      expect(_keyboardUp(tester), isFalse,
          reason: 'a tap elsewhere must close the keyboard');
      expect(_couponText(tester), 'PTS-TAPOUT01');
      expect(find.byType(CheckoutScreen), findsOneWidget);
    });

    testWidgets('the coupon field carries the dismissal wiring', (tester) async {
      // Pins the cause rather than only the symptoms. A null onTapOutside is
      // the precise defect NeoTextField documents; this field is a raw
      // TextField and so needs it set explicitly.
      await pumpCheckout(tester, _cartWithItems());
      final field = tester.widget<TextField>(find.byKey(_couponKey));
      expect(field.onTapOutside, isNotNull,
          reason: 'a null onTapOutside is what keeps the IME up on Android');
      expect(field.textInputAction, TextInputAction.done);
      expect(field.onSubmitted, isNotNull);
      expect(field.focusNode, isNotNull,
          reason: 'PopScope needs a focus node to know the keyboard is up');
    });
  });
}
