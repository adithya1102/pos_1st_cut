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

/// True when a `git` we can actually run is on PATH.
bool get _gitAvailable {
  try {
    return Process.runSync('git', ['--version']).exitCode == 0;
  } on ProcessException {
    return false;
  }
}

ProcessResult _git(List<String> args, String cwd) =>
    Process.runSync('git', args, workingDirectory: cwd);

/// Is [path] (relative to [root]) tracked in git's index?
bool _isTracked(String root, String path) =>
    _git(['ls-files', '--', path], root).stdout.toString().trim().isNotEmpty;

/// Would git ignore [path]? Note this is a question about the IGNORE RULES,
/// not about the file: it answers for a path that does not exist, which is
/// exactly what we want — the rule has to be in place before the file shows
/// up, not after.
bool _isIgnored(String root, String path) =>
    _git(['check-ignore', '-q', '--', path], root).exitCode == 0;

/// THE GUARD. Returns one string per problem; empty means clean.
///
/// WHAT THIS PROTECTS, AND WHAT IT DELIBERATELY NO LONGER CLAIMS
/// ------------------------------------------------------------
/// The risk that matters is signing material entering the repository's
/// HISTORY. This repository is public, and a committed upload key cannot be
/// un-leaked — the only remedy is a new key via Play support.
///
/// The previous version of this guard asserted that no `key.properties`
/// existed anywhere on disk under android/. That is not the same property,
/// and it is unsatisfiable: Gradle reads the file from exactly one place,
/// `rootProject.file("key.properties")` — i.e. `owner_app/android/` — so any
/// machine able to produce a Play-signed bundle necessarily tripped it. It
/// was a permanent red that told you nothing, and a permanent red is a guard
/// nobody reads.
///
/// So the question changed from "is the file here?" to "can the file reach a
/// commit?", which is checked against git itself rather than inferred from the
/// filesystem:
///
///   * `key.properties` must be untracked AND covered by an ignore rule;
///   * no `.jks`/`.keystore` may be tracked, and any that exists on disk must
///     be ignored.
///
/// Strictly stronger than the old check on the thing that matters: the old one
/// could not see a file that was already tracked from a directory it did not
/// walk, and said nothing about `.gitignore` actually covering a real path.
List<String> auditSigningMaterial(String root) {
  final problems = <String>[];

  // ---- (a) key.properties ------------------------------------------------
  const keyProps = 'android/key.properties';
  if (_isTracked(root, keyProps)) {
    problems.add(
      '$keyProps is TRACKED by git. It holds the keystore passwords in '
      'plaintext. `git rm --cached` it, then rotate the key — assume the '
      'passwords are compromised if this ever reached a push.',
    );
  }
  if (!_isIgnored(root, keyProps)) {
    problems.add(
      '$keyProps is not covered by any ignore rule, so it is one `git add .` '
      'away from being committed.',
    );
  }

  // ---- (b) keystores -----------------------------------------------------
  final tracked = _git(['ls-files'], root)
      .stdout
      .toString()
      .split('\n')
      .map((l) => l.trim())
      .where((l) => l.endsWith('.jks') || l.endsWith('.keystore'));
  for (final f in tracked) {
    problems.add(
      '$f is TRACKED by git. A committed keystore in a public repository is '
      'an unrecoverable compromise of the upload key.',
    );
  }

  final dir = Directory(root);
  if (dir.existsSync()) {
    for (final f in dir.listSync(recursive: true).whereType<File>()) {
      final rel = f.path
          .substring(root.length)
          .replaceAll(r'\', '/')
          .replaceFirst(RegExp('^/'), '');
      if (!(rel.endsWith('.jks') || rel.endsWith('.keystore'))) continue;
      if (!_isIgnored(root, rel)) {
        problems.add(
          '$rel is on disk and NOT ignored — it can be committed by accident.',
        );
      }
    }
  }

  return problems;
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

    test('no signing material can reach a commit', () {
      // Asks git, not the filesystem. key.properties MUST exist here for a
      // signed build (Gradle reads rootProject.file("key.properties")), so its
      // presence is not the fault — being committable is.
      final root = _androidFile('.gitignore').parent.parent.path;
      expect(auditSigningMaterial(root), isEmpty,
          reason: 'signing material can reach a commit in this repository');
    }, skip: _gitAvailable ? null : 'git is not on PATH, so the guard cannot '
        'inspect the index or the ignore rules. Install git and re-run — this '
        'check is NOT optional before a release.');
  });

  // The guard above passes. On its own that proves nothing: a function that
  // returns [] unconditionally would also pass it. These drive it against
  // throwaway repositories built to be exactly wrong, so a future refactor
  // that neuters the audit fails HERE instead of going quiet.
  group('the guard actually fails when it should', () {
    late Directory tmp;

    setUp(() {
      tmp = Directory.systemTemp.createTempSync('signing_guard_');
      // -c so a developer's global init.defaultBranch/hooks cannot affect it.
      _git(['-c', 'init.defaultBranch=main', 'init', '-q'], tmp.path);
    });

    tearDown(() => tmp.deleteSync(recursive: true));

    void write(String relative, String body) {
      final f = File('${tmp.path}/$relative')
        ..parent.createSync(recursive: true);
      f.writeAsStringSync(body);
    }

    test('key.properties present with no ignore rule is a problem', () {
      write('android/key.properties', 'storeFile=/nowhere/x.jks\n');

      final problems = auditSigningMaterial(tmp.path);

      expect(problems, isNotEmpty);
      expect(problems.join('\n'), contains('not covered by any ignore rule'));
    });

    test('key.properties tracked is a problem even when ignored', () {
      // The case .gitignore cannot save you from: already in the index, where
      // an ignore rule has no effect at all.
      write('.gitignore', 'key.properties\n');
      write('android/key.properties', 'storeFile=/nowhere/x.jks\n');
      _git(['add', '-f', 'android/key.properties'], tmp.path);

      final problems = auditSigningMaterial(tmp.path);

      expect(problems, isNotEmpty);
      expect(problems.join('\n'), contains('is TRACKED by git'));
      expect(problems.join('\n'), contains('rotate the key'));
    });

    test('a tracked keystore is a problem', () {
      write('.gitignore', 'key.properties\n');
      write('android/upload.jks', 'not-a-real-keystore');
      _git(['add', '-f', 'android/upload.jks'], tmp.path);

      final problems = auditSigningMaterial(tmp.path);

      expect(problems.join('\n'), contains('android/upload.jks is TRACKED'));
      expect(problems.join('\n'), contains('unrecoverable compromise'));
    });

    test('an unignored keystore on disk is a problem', () {
      write('.gitignore', 'key.properties\n');
      write('android/upload.keystore', 'not-a-real-keystore');

      final problems = auditSigningMaterial(tmp.path);

      expect(problems.join('\n'),
          contains('android/upload.keystore is on disk and NOT ignored'));
    });

    test('ignored-and-untracked signing material is clean', () {
      // The shape this repository is actually in, and the one the old guard
      // called a failure: the file is present because Gradle needs it, and
      // it cannot be committed.
      write('.gitignore', 'key.properties\n*.jks\n*.keystore\n');
      write('android/key.properties', 'storeFile=/nowhere/x.jks\n');
      write('android/upload.jks', 'not-a-real-keystore');

      expect(auditSigningMaterial(tmp.path), isEmpty);
    });
  },
      skip: _gitAvailable
          ? null
          : 'git is not on PATH, so a scratch repository cannot be created');
}
