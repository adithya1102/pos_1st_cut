// Release signing is wired to a gitignored key.properties, with a debug
// fallback, and no secret is committed.
//
// These assertions are about BUILD CONFIGURATION, which no other test in this
// suite touches. They are cheap and they guard three things whose failure modes
// are all silent or expensive:
//
//   * the keystore patterns leaving .gitignore — a committed .jks in a PUBLIC
//     repository is an unrecoverable key compromise, and the only fix is a new
//     upload key via Play support;
//   * the debug fallback being removed — a clone without the secret then fails
//     at Gradle sync rather than building, which looks like a broken checkout;
//   * the signingConfig being hardcoded back to debug — Play rejects a
//     debug-signed bundle, so this surfaces at upload rather than at build.
//
// Read as text on purpose. Running Gradle in a unit test is not viable, and the
// invariants here are textual: which file the config reads, and which patterns
// .gitignore carries.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Resolved from the test's own location rather than the process CWD, which
/// differs between `flutter test` and an IDE run.
File _androidFile(String relative) {
  final here = File.fromUri(Platform.script).parent.path;
  for (final base in <String>[
    'android/$relative',
    '../android/$relative',
    '$here/../android/$relative',
  ]) {
    final f = File(base);
    if (f.existsSync()) return f;
  }
  fail('could not locate android/$relative from ${Directory.current.path}');
}

void main() {
  group('release signing', () {
    late String gradle;
    late String gitignore;

    setUpAll(() {
      gradle = _androidFile('app/build.gradle.kts').readAsStringSync();
      gitignore = _androidFile('.gitignore').readAsStringSync();
    });

    test('the upload key is read from key.properties', () {
      expect(gradle, contains('key.properties'),
          reason: 'signing is no longer wired to an external properties file');
      for (final key in ['storeFile', 'storePassword', 'keyAlias', 'keyPassword']) {
        expect(gradle, contains(key), reason: '$key is not read from the file');
      }
    });

    test('a missing key.properties falls back to debug signing', () {
      // The fallback is what lets `flutter run --release` work on a machine
      // without the secret, and what keeps Gradle sync working on a fresh
      // clone. Both branches must be present.
      expect(gradle, contains('signingConfigs.getByName("upload")'));
      expect(gradle, contains('signingConfigs.getByName("debug")'));
      expect(gradle, contains('if (keystoreProperties != null)'),
          reason: 'the release signingConfig is no longer conditional, so it '
              'is pinned to one of the two rather than falling back');
    });

    test('the signing config is not unconditionally debug', () {
      // The regression this exists for: "make the build work again" by
      // hardcoding debug. It builds, it runs, and Play rejects the bundle.
      final release = RegExp(r'release\s*\{(.*?)\n\s{8}\}', dotAll: true)
          .firstMatch(gradle)
          ?.group(1);
      expect(release, isNotNull, reason: 'no release buildType block found');
      expect(
        RegExp(r'signingConfig\s*=\s*signingConfigs\.getByName\("debug"\)\s*$',
                multiLine: true)
            .hasMatch(release!),
        isFalse,
        reason: 'release signing is hardcoded to debug',
      );
    });

    test('no keystore or key.properties can be committed', () {
      // The patterns, not the absence of a file: a repository that merely
      // happens to have no .jks today is one `git add` away from a leak.
      for (final pattern in ['key.properties', '**/*.jks', '**/*.keystore']) {
        expect(
          gitignore.split('\n').map((l) => l.trim()),
          contains(pattern),
          reason: '$pattern is not gitignored — this repository is PUBLIC, so '
              'committing it is an unrecoverable key compromise',
        );
      }
    });

    test('no keystore is actually present in the repository', () {
      // Belt and braces for the case where one was committed BEFORE the
      // ignore patterns went in — .gitignore does not untrack an existing file.
      final androidDir = _androidFile('.gitignore').parent;
      final offenders = androidDir
          .listSync(recursive: true)
          .whereType<File>()
          .map((f) => f.path)
          .where((p) =>
              p.endsWith('.jks') ||
              p.endsWith('.keystore') ||
              p.endsWith('key.properties'))
          .toList();
      expect(offenders, isEmpty,
          reason: 'signing material is present on disk inside the repo: '
              '$offenders — move it outside and confirm it is untracked');
    });
  });
}
