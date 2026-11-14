// AppConfig.appVersion is a hand-maintained constant (this app has no
// package_info_plus dependency — a plugin to render a label would be a poor
// trade). The cost of a constant is that it can silently drift from
// pubspec.yaml, which is the one place the Play Store reads, so these two
// tests are what keep it honest. Mirrors owner_app's `group('app version')`
// in test/payment_modes_test.dart.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:customer_app/config/app_config.dart';

void main() {
  group('app version', () {
    test('AppConfig.appVersion matches pubspec.yaml', () {
      final pubspec = File('pubspec.yaml').readAsStringSync();
      final m =
          RegExp(r'^version:\s*(\S+)', multiLine: true).firstMatch(pubspec);
      expect(m, isNotNull, reason: 'pubspec.yaml has no version line');
      expect(AppConfig.appVersion, m!.group(1));
    });

    test('it is the expected build for this release', () {
      expect(AppConfig.appVersion, '1.0.2+9');
    });
  });
}
