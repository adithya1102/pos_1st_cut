import 'package:flutter/material.dart';

/// Drop the app's current focus, which closes the IME and stops the caret.
///
/// Three separately-reported bugs were one piece of state — focus was never
/// released — so there is one function that releases it and two callers that
/// cover the two ways a field stops being the thing you are using:
///
///  * tapping somewhere else on the screen ([NeoTextField.onTapOutside]);
///  * leaving the screen entirely ([FocusReleasingObserver]).
///
/// The blinking caret is not a third bug. It is the visible rendering of "this
/// field still has focus", so it stops exactly when the other two are fixed.
void releaseFocus() => FocusManager.instance.primaryFocus?.unfocus();

/// Releases focus on every route transition.
///
/// An observer rather than an `unfocus()` at each `Navigator.pop` call site:
/// the leak happens on the system back gesture and the AppBar back button too,
/// neither of which goes through app code. This sees all of them, including
/// pushes — a new screen should never inherit the previous one's keyboard.
class FocusReleasingObserver extends NavigatorObserver {
  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      releaseFocus();

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      releaseFocus();

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) =>
      releaseFocus();
}
