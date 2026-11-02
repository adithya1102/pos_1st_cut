// Guards against an unapproved placeholder shipping silently: scans every
// source file under lib/ for the markers this repo uses to flag copy that is
// awaiting approval ("TODO:") or specifically the refund-copy placeholder
// prefix ("REFUND_COPY"). Fails loudly, naming the file, if either reappears.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('no file under lib/ contains a TODO: or REFUND_COPY marker', () {
    final cwd = Directory.current.path;
    final libDir = Directory('$cwd/lib');
    expect(libDir.existsSync(), isTrue, reason: 'lib/ must exist');

    final offenders = <String>[];
    for (final entity in libDir.listSync(recursive: true)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final contents = entity.readAsStringSync();
      if (contents.contains('TODO:') || contents.contains('REFUND_COPY')) {
        final relative = entity.path.startsWith(cwd)
            ? entity.path.substring(cwd.length + 1)
            : entity.path;
        offenders.add(relative);
      }
    }

    expect(offenders, isEmpty,
        reason: 'placeholder marker(s) found in: ${offenders.join(', ')}');
  });
}
