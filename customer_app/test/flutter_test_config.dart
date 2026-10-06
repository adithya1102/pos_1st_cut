import 'dart:async';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Global setup for every test under `test/`.
///
/// `flutter_test_config.dart` is a convention the Flutter test runner picks up
/// automatically: when this file exists the runner calls [testExecutable] once
/// and every test in the directory runs inside it. Using it rather than adding
/// a `setUp` to each of the 34 test files means a NEW test file cannot forget
/// the mock and hang.
///
/// WHY IT IS NEEDED
/// ----------------
/// ApiClient now stores the customer JWT in flutter_secure_storage (Android
/// Keystore / iOS Keychain) instead of SharedPreferences. That plugin talks
/// over a MethodChannel, and in a widget test there is no platform on the
/// other end — the first `read()` never completes, so the test HANGS rather
/// than failing. A hang is considerably harder to diagnose than an error, and
/// it is what broke the owner_app suite when the same change landed there.
///
/// setMockInitialValues installs an in-memory implementation, so reads and
/// writes behave as they do on a device without a device being involved.
/// Starting empty is the honest default: a fresh install holds no token, and a
/// test that wants one calls setToken().
Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  FlutterSecureStorage.setMockInitialValues({});
  await testMain();
}
