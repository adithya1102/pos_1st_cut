// Pins the v2 palette and its contrast rules.
//
// These are not style preferences — each assertion encodes a decision that is
// expensive to rediscover: which colour is allowed where, and why. In
// particular the accent FAILS contrast on the ticket stock, so a future change
// that "brightens up the ticket" with it would ship unreadable text.
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:customer_app/theme/app_colors.dart';
import 'package:customer_app/theme/widgets/ticket_card.dart';

/// WCAG relative luminance.
double _lum(Color c) {
  double ch(double v) =>
      v <= 0.03928 ? v / 12.92 : math.pow((v + 0.055) / 1.055, 2.4).toDouble();
  return 0.2126 * ch(c.r) + 0.7152 * ch(c.g) + 0.0722 * ch(c.b);
}

double _ratio(Color a, Color b) {
  final la = _lum(a), lb = _lum(b);
  final hi = math.max(la, lb), lo = math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

void main() {
  const paperCenter = Color(0xFFB5783A);
  const slate = Color(0xFF3A77B5);
  const vibrant = Color(0xFF00D4FF);
  const dark = Color(0xFF0B1B2B);

  group('palette values', () {
    test('the four specified colours are exactly as given', () {
      expect(AppColors.paperCenter, paperCenter);
      expect(AppColors.contrastSlate, slate);
      expect(AppColors.contrastVibrant, vibrant);
      expect(AppColors.contrastDark, dark);
    });

    test('the app shell is the dark colour, not a pale surface', () {
      expect(AppColors.v2.background, dark);
    });

    test('vibrant is the single accent; slate is secondary', () {
      expect(AppColors.v2.primary, vibrant);
      expect(AppColors.v2.accent, slate);
    });
  });

  group('single theme', () {
    test('light and dark schemes are the same object — no pale variant left',
        () {
      expect(AppColors.light, same(AppColors.v2));
      expect(AppColors.dark, same(AppColors.v2));
    });

    // NOTE: deliberately asserted at the SCHEME level, not by building
    // ThemeData. AppTheme._build calls GoogleFonts, which cannot fetch a
    // webfont under `flutter test` and throws — so a ThemeData-level assertion
    // would fail for a reason that has nothing to do with the palette. Since
    // both AppTheme entry points feed on AppColors.v2, pinning the scheme
    // pins the theme.
    test('there is no pale surface left anywhere in the scheme', () {
      // Every surface role must sit on the dark side; a stray cream value here
      // is what a half-finished migration looks like.
      for (final c in [
        AppColors.v2.background,
        AppColors.v2.surface,
        AppColors.v2.surfaceAlt,
      ]) {
        expect(_lum(c), lessThan(0.15),
            reason: '$c is too light to be an app surface in v2');
      }
    });
  });

  group('ticket stock stays paper, not another dark panel', () {
    test('ticket paper is paperCenter and is NOT the app shell', () {
      final t = TicketColors.of(_ctx());
      expect(t.paper, paperCenter);
      expect(t.paper, isNot(dark),
          reason: 'a navy ticket would erase the physical-object metaphor');
    });

    test('ticket ink on stock is readable', () {
      final t = TicketColors.of(_ctx());
      expect(_ratio(t.ink, t.paper), greaterThanOrEqualTo(4.5),
          reason: 'ticket body text must meet normal-text contrast');
    });
  });

  group('contrast rules that constrain where colours may be used', () {
    test('vibrant is text-safe on the shell', () {
      expect(_ratio(vibrant, dark), greaterThanOrEqualTo(4.5));
    });

    test('dark text on a vibrant fill is text-safe (so it works as a button)',
        () {
      expect(_ratio(dark, vibrant), greaterThanOrEqualTo(4.5));
    });

    test('VIBRANT ON THE TICKET FAILS — it must never be used there', () {
      // 2.08:1. This is the assertion that matters most: the accent looks
      // inviting on the tan stock and is completely unreadable on it.
      expect(_ratio(vibrant, paperCenter), lessThan(3.0));
    });

    test('slate is large/UI only on the shell, never body text', () {
      final r = _ratio(slate, dark);
      expect(r, greaterThanOrEqualTo(3.0));
      expect(r, lessThan(4.5),
          reason: 'documents WHY slate is not allowed to carry body text');
    });

    test('white on slate is text-safe, so filled slate can carry a label', () {
      expect(_ratio(const Color(0xFFFFFFFF), slate), greaterThanOrEqualTo(4.5));
    });

    test('secondary ink is readable on the shell', () {
      expect(_ratio(AppColors.v2.inkSoft, AppColors.v2.background),
          greaterThanOrEqualTo(4.5));
    });

    test('primary body ink is readable on the shell', () {
      expect(_ratio(AppColors.v2.ink, AppColors.v2.background),
          greaterThanOrEqualTo(4.5));
    });
  });
}

/// TicketColors.of ignores the context (single scheme), so a throwaway element
/// is enough — this avoids pumping a whole widget tree for a colour lookup.
BuildContext _ctx() => _FakeContext();

class _FakeContext extends StatelessElement {
  _FakeContext() : super(const _Nothing());
}

class _Nothing extends StatelessWidget {
  const _Nothing();
  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}
