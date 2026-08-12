import 'dart:math' as math;

import 'package:flutter/material.dart';

/// The "ticket" visual sub-language (v2 prototype §2).
///
/// A deliberate SECOND style layered on the existing neobrutalist system, used
/// only for order-status surfaces — pickup ticket, active orders, collected,
/// order history. Everything else (login, outlets, menu, cart) keeps the flat
/// cards. The split is the point: a ticket is a thing you hold and show
/// someone, and it should not look like the browsing UI it came from.
///
/// The ticket palette is a SINGLE set, matching the app's single light theme.
///
/// The stock (#FAEEDA) is a cream receipt printed in brown ink (#412402) — the
/// prototype's values, unchanged. It reads as warmer and slightly darker than
/// the warm-white shell it sits on, which is the whole point: the ticket has to
/// look like a physical object placed on top of the UI, not like another card.
///
/// Measured contrast:
///   ink     (#412402) on stock  12.39:1  -> body text, comfortably
///   inkSoft (#7A5426) on stock   5.86:1  -> secondary lines, still normal-text
///   mint    (#AAF2CA) on stock   1.13:1  -> FAILS. Mint appears on a ticket
///   only as a FILL behind dark text (the status pill), never as a text colour.
class TicketColors {
  const TicketColors._();

  /// The one scheme. `of(context)` is kept so call sites read uniformly and so
  /// a future variant can be reintroduced without touching every screen.
  static const TicketColors _instance = TicketColors._();
  static TicketColors of(BuildContext context) => _instance;

  /// Ticket stock — cream receipt paper.
  final Color paper = const Color(0xFFFAEEDA);

  /// Slightly deeper stock for the perforated stub band, so the tear-off edge
  /// reads as a separate strip rather than a flat continuation.
  final Color paperDim = const Color(0xFFEFDFC1);

  /// Printed ink.
  final Color ink = const Color(0xFF412402);

  /// Faded ink for secondary lines. Deliberately darker than the prototype's
  /// #8A6A2E, which measures 4.38:1 on the stock and would fail normal text.
  final Color inkSoft = const Color(0xFF7A5426);

  /// Dashed rules and the perforation line. Decorative only — never carries
  /// text, so it is free to sit below text contrast.
  final Color rule = const Color(0xFF8A6A2E);
}

/// A paper ticket: perforated top edge, cream stock, brown ink.
///
/// [stamped] overlays the rotated ghost watermark used on a collected order.
class TicketCard extends StatelessWidget {
  const TicketCard({
    super.key,
    required this.child,
    this.stampText,
    this.padding = const EdgeInsets.fromLTRB(20, 22, 20, 20),
    this.onTap,
  });

  final Widget child;

  /// When non-null, a rotated ghost stamp is drawn across the ticket (e.g.
  /// "COLLECTED"). Non-interactive and behind nothing — it sits above the
  /// content at low opacity, the way a real rubber stamp would.
  final String? stampText;

  final EdgeInsets padding;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final t = TicketColors.of(context);
    final body = ClipRRect(
      borderRadius: BorderRadius.circular(14),
      child: Container(
        decoration: BoxDecoration(
          color: t.paper,
          border: Border.all(color: t.ink, width: 2.5),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // The torn-off edge. Drawn, not an image asset, so it scales to any
            // width and needs no bundling.
            _PerforatedEdge(colors: t),
            Stack(
              children: [
                Padding(padding: padding, child: child),
                if (stampText != null)
                  Positioned.fill(
                    child: IgnorePointer(
                      child: Center(
                          child: _GhostStamp(text: stampText!, colors: t)),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );

    final shadowed = DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        boxShadow: [
          BoxShadow(color: t.ink, offset: const Offset(4, 4), blurRadius: 0),
        ],
      ),
      child: body,
    );

    if (onTap == null) return shadowed;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(14),
      child: shadowed,
    );
  }
}

/// The scalloped tear-off strip along the top of a ticket.
class _PerforatedEdge extends StatelessWidget {
  const _PerforatedEdge({required this.colors});
  final TicketColors colors;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 14,
      width: double.infinity,
      child: CustomPaint(painter: _PerforationPainter(colors)),
    );
  }
}

class _PerforationPainter extends CustomPainter {
  _PerforationPainter(this.colors);
  final TicketColors colors;

  static const double _notchRadius = 6;
  static const double _gap = 18;

  @override
  void paint(Canvas canvas, Size size) {
    // Fill the strip with stock, then punch half-circles out of the top so the
    // card below reads as torn from a perforated roll.
    final bg = Paint()..color = colors.paperDim;
    canvas.drawRect(Offset.zero & size, bg);

    final punch = Paint()
      ..color = Colors.transparent
      ..blendMode = BlendMode.clear;
    canvas.saveLayer(Offset.zero & size, Paint());
    canvas.drawRect(Offset.zero & size, bg);
    for (double x = _gap / 2; x < size.width + _gap; x += _gap) {
      canvas.drawCircle(Offset(x, 0), _notchRadius, punch);
    }
    canvas.restore();

    // The perforation line itself.
    final line = Paint()
      ..color = colors.rule
      ..strokeWidth = 1.2;
    const dash = 5.0, space = 4.0;
    for (double x = 0; x < size.width; x += dash + space) {
      canvas.drawLine(
        Offset(x, size.height - 0.6),
        Offset(math.min(x + dash, size.width), size.height - 0.6),
        line,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _PerforationPainter old) => old.colors != colors;
}

/// Horizontal dashed rule used between ticket sections.
class TicketDivider extends StatelessWidget {
  const TicketDivider({super.key, this.verticalPadding = 12});
  final double verticalPadding;

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.symmetric(vertical: verticalPadding),
        child: SizedBox(
          height: 1,
          width: double.infinity,
          child: CustomPaint(painter: _DashedLinePainter(TicketColors.of(context))),
        ),
      );
}

class _DashedLinePainter extends CustomPainter {
  _DashedLinePainter(this.colors);
  final TicketColors colors;

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = colors.rule
      ..strokeWidth = 1.4;
    const dash = 6.0, space = 5.0;
    for (double x = 0; x < size.width; x += dash + space) {
      canvas.drawLine(
        Offset(x, 0),
        Offset(math.min(x + dash, size.width), 0),
        p,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _DashedLinePainter old) => old.colors != colors;
}

/// The rotated "COLLECTED" watermark.
///
/// Low opacity and rotated so it reads as ink pressed onto the ticket rather
/// than as a UI label — a solid banner would compete with the content it is
/// annotating.
class _GhostStamp extends StatelessWidget {
  const _GhostStamp({required this.text, required this.colors});
  final String text;
  final TicketColors colors;

  @override
  Widget build(BuildContext context) {
    return Transform.rotate(
      angle: -math.pi / 9, // ~ -20°
      child: Opacity(
        opacity: 0.16,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          decoration: BoxDecoration(
            border: Border.all(color: colors.ink, width: 4),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            text,
            style: TextStyle(
              color: colors.ink,
              fontSize: 34,
              fontWeight: FontWeight.w900,
              letterSpacing: 5,
            ),
          ),
        ),
      ),
    );
  }
}

/// A label/value row in ticket typography — monospaced value, so codes and
/// amounts line up down the ticket the way printed ones do.
class TicketRow extends StatelessWidget {
  const TicketRow({
    super.key,
    required this.label,
    required this.value,
    this.emphasize = false,
    this.strikethrough = false,
  });

  final String label;
  final String value;
  final bool emphasize;

  /// Used on a collected ticket's pickup code: it is kept visible as a record
  /// but struck through, because it can no longer be used.
  final bool strikethrough;

  @override
  Widget build(BuildContext context) {
    final t = TicketColors.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: TextStyle(
            color: t.inkSoft,
            fontSize: emphasize ? 14 : 13,
            fontWeight: FontWeight.w600,
            letterSpacing: 1.2,
          ),
        ),
        const Spacer(),
        Flexible(
          child: Text(
            value,
            textAlign: TextAlign.right,
            style: TextStyle(
              color: t.ink,
              fontSize: emphasize ? 18 : 14,
              fontWeight: emphasize ? FontWeight.w900 : FontWeight.w700,
              decoration:
                  strikethrough ? TextDecoration.lineThrough : TextDecoration.none,
              decorationColor: t.ink,
              decorationThickness: 2,
            ),
          ),
        ),
      ],
    );
  }
}
