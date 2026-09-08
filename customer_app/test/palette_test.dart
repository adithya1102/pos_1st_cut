// Pins the v2 palette and its contrast rules.
//
// These are not style preferences — each assertion encodes a decision that is
// expensive to rediscover: which colour is allowed where, and why.
//
// The app is single-theme LIGHT. An earlier iteration shipped a dark navy shell
// with a cyan accent; it was reviewed and dropped. The "no dark surface" group
// below is the guard against it coming back by accident — a stray dark value in
// a surface role is what a half-finished migration looks like.
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
  const paper = Color(0xFFFFF8F3); // app shell
  const brand = Color(0xFF53089B); // wordmark / link purple
  const purple = Color(0xFF6B2FB3); // primary button fill
  const mint = Color(0xFFAAF2CA); // accent fill
  const ink = Color(0xFF171512); // borders + hard shadows

  const ticketStock = Color(0xFFFAEEDA);
  const ticketInk = Color(0xFF412402);

  group('palette values', () {
    test('the brand colours are exactly as given', () {
      expect(AppColors.brand, brand);
      expect(AppColors.purple, purple);
      expect(AppColors.mint, mint);
      expect(AppColors.ink, ink);
      expect(AppColors.paper, paper);
    });

    test('the app shell is the warm white, not a dark surface', () {
      expect(AppColors.v2.background, paper);
    });

    test('purple is the primary fill; mint is the accent', () {
      expect(AppColors.v2.primary, purple);
      expect(AppColors.v2.accent, mint);
    });
  });

  group('single theme', () {
    test('light and dark schemes are the same object — no second variant', () {
      expect(AppColors.light, same(AppColors.v2));
      expect(AppColors.dark, same(AppColors.v2));
    });

    // NOTE: deliberately asserted at the SCHEME level, not by building
    // ThemeData. AppTheme._build calls GoogleFonts, which cannot fetch a
    // webfont under `flutter test` and throws — so a ThemeData-level assertion
    // would fail for a reason that has nothing to do with the palette. Since
    // both AppTheme entry points feed on AppColors.v2, pinning the scheme
    // pins the theme.
    test('every surface role is light — the dark shell must not return', () {
      for (final c in [
        AppColors.v2.background,
        AppColors.v2.surface,
        AppColors.v2.surfaceAlt,
      ]) {
        expect(_lum(c), greaterThan(0.6),
            reason: '$c is too dark to be an app surface in v2');
      }
    });

    test('ink roles are dark, so they can be read on those surfaces', () {
      expect(_lum(AppColors.v2.ink), lessThan(0.1));
      expect(_lum(AppColors.v2.border), lessThan(0.1));
    });
  });

  group('ticket stock is cream paper, distinct from the shell', () {
    test('ticket paper is the cream stock and is NOT the app background', () {
      final t = TicketColors.of(_ctx());
      expect(t.paper, ticketStock);
      expect(t.ink, ticketInk);
      expect(t.paper, isNot(AppColors.v2.background),
          reason: 'a ticket the same colour as the screen stops reading as an '
              'object placed on it');
    });

    test('ticket ink on stock is readable', () {
      final t = TicketColors.of(_ctx());
      expect(_ratio(t.ink, t.paper), greaterThanOrEqualTo(4.5),
          reason: 'ticket body text must meet normal-text contrast');
    });

    test('ticket secondary ink is readable too', () {
      final t = TicketColors.of(_ctx());
      // 5.86:1. Deliberately darker than the prototype's #8A6A2E, which is
      // 4.38:1 on the stock and would fail normal text.
      expect(_ratio(t.inkSoft, t.paper), greaterThanOrEqualTo(4.5));
    });
  });

  group('contrast rules that constrain where colours may be used', () {
    test('body ink is readable on the shell', () {
      expect(_ratio(AppColors.v2.ink, AppColors.v2.background),
          greaterThanOrEqualTo(4.5));
    });

    test('secondary ink is readable on the shell and on the muted band', () {
      expect(_ratio(AppColors.v2.inkSoft, AppColors.v2.background),
          greaterThanOrEqualTo(4.5));
      expect(_ratio(AppColors.v2.inkSoft, AppColors.v2.surfaceAlt),
          greaterThanOrEqualTo(4.5));
    });

    test('brand purple is text-safe on the shell, so links may use it', () {
      expect(_ratio(brand, paper), greaterThanOrEqualTo(4.5));
    });

    test('white on the primary fill is text-safe (so it works as a button)', () {
      expect(_ratio(AppColors.v2.onPrimary, AppColors.v2.primary),
          greaterThanOrEqualTo(4.5));
    });

    test('dark text on the mint accent is text-safe', () {
      expect(_ratio(AppColors.v2.onAccent, AppColors.v2.accent),
          greaterThanOrEqualTo(4.5));
    });

    test('MINT AS TEXT FAILS EVERYWHERE — it is a fill colour only', () {
      // 1.23:1 on the shell, 1.13:1 on ticket stock. Mint reads as the
      // "positive" colour and is tempting for success copy; as type on either
      // pale surface it is invisible. It may only appear as a FILL behind dark
      // text.
      expect(_ratio(mint, paper), lessThan(3.0));
      expect(_ratio(mint, ticketStock), lessThan(3.0));
    });

    test('the deeper mint is no better as text', () {
      expect(_ratio(AppColors.mintDeep, paper), lessThan(3.0));
    });

    test('the mint chip label colour IS readable on mint', () {
      // #2A7151 exists precisely because mint-on-mint needed a legible label.
      expect(_ratio(AppColors.mintInk, mint), greaterThanOrEqualTo(4.5));
    });
  });

  group('known exception, asserted so it cannot drift silently', () {
    test('the danger button pair is large-text only', () {
      // cream on tomato is 3.08:1 — pre-existing, deliberately unchanged, and
      // only ever used on a chunky uppercase button label. Pinned here so a
      // future change that reuses this pair for body text has to confront it.
      final r = _ratio(AppColors.cream, AppColors.tomato);
      expect(r, greaterThanOrEqualTo(3.0));
      expect(r, lessThan(4.5));
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
