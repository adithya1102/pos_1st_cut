import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'api_client.dart';

/// What went wrong, in the only terms the customer needs.
///
/// The categories are chosen by what the customer can DO about them, not by
/// what the stack trace says: being offline is something they can fix, a 500 is
/// something they can only wait out, and an empty result is not a failure at
/// all. Anything unrecognised lands in [unknown] rather than leaking a raw
/// exception onto the screen.
enum AppErrorKind {
  offline,
  timeout,
  server,
  request,
  empty,
  unknown,
}

/// A classified failure: friendly copy for the screen, technical cause for the
/// log, and never the two mixed up.
///
/// ## Why this exists
///
/// Screens used to render `ApiException.message` directly, and that message was
/// built by interpolating the raw exception —
/// `'Network error: unable to reach server. (TimeoutException after 0:00:20)'`
/// went straight in front of a customer. Worse, it was assembled per screen, so
/// the same failure was worded differently depending on where you hit it.
///
/// [AppError.from] is now the single place a thrown object becomes something
/// showable, and [technical] is deliberately kept OFF the screen — it goes to
/// the log via [logTo], for whoever is debugging.
@immutable
class AppError {
  const AppError({
    required this.kind,
    required this.title,
    required this.message,
    required this.technical,
  });

  final AppErrorKind kind;

  /// Headline. Short, warm, never blaming the customer.
  final String title;

  /// The line under it: what is happening, or what to do.
  final String message;

  /// The real error. For [debugPrint] and bug reports; NOT for the UI.
  final String technical;

  /// True when a "Try Again" button makes sense.
  ///
  /// False only for [AppErrorKind.empty], where there is nothing to retry —
  /// the request worked and the answer was genuinely "nothing here". Offering
  /// Try Again there would suggest the app doubted its own correct result.
  bool get canRetry => kind != AppErrorKind.empty;

  /// Classify any thrown object.
  ///
  /// Ordering matters: [AuthExpiredException] and [NetworkException] are both
  /// subclasses of [ApiException], so they are matched BEFORE it or a session
  /// expiry would be reported as a generic request failure.
  factory AppError.from(Object error) {
    // ---- transport: never reached the server ----
    if (error is NetworkException) return AppError._fromCause(error.cause);
    if (error is TimeoutException) return AppError._timeout(error);
    if (error is SocketException) return AppError._offline(error);

    if (error is ApiException) {
      final code = error.statusCode;
      if (code != null && code >= 500) return AppError._server(error);
      if (code != null && code >= 400) return AppError._request(error);
      // No status: the server never gave one, so treat it as transport.
      return AppError._unknown(error);
    }
    return AppError._unknown(error);
  }

  /// A transport failure, split by what actually happened underneath. This is
  /// why [NetworkException.cause] is preserved instead of stringified: offline
  /// and timeout need different copy, and only the original type can tell them
  /// apart.
  factory AppError._fromCause(Object cause) {
    if (cause is TimeoutException) return AppError._timeout(cause);
    if (cause is SocketException) return AppError._offline(cause);
    // http throws ClientException for a dropped connection; its message is the
    // only signal available, so match on it rather than guess.
    final text = cause.toString().toLowerCase();
    if (text.contains('timeout') || text.contains('timed out')) {
      return AppError._timeout(cause);
    }
    if (text.contains('socket') ||
        text.contains('failed host lookup') ||
        text.contains('network is unreachable') ||
        text.contains('connection refused') ||
        text.contains('connection closed')) {
      return AppError._offline(cause);
    }
    return AppError._unknown(cause);
  }

  factory AppError._offline(Object e) => AppError(
        kind: AppErrorKind.offline,
        title: "Looks like you're offline.",
        message: "Get connected and we'll bring the menu right back.",
        technical: e.toString(),
      );

  factory AppError._timeout(Object e) => AppError(
        kind: AppErrorKind.timeout,
        title: 'Almost there...',
        message: 'The menu took a little longer than expected.',
        technical: e.toString(),
      );

  factory AppError._server(Object e) => AppError(
        kind: AppErrorKind.server,
        title: 'We hit a little roadblock.',
        message: 'Your menu is just a moment away. Please try again.',
        technical: e.toString(),
      );

  factory AppError._request(Object e) => AppError(
        kind: AppErrorKind.request,
        title: 'The menu is taking a little longer than expected.',
        message: 'Hang tight and try again.',
        technical: e.toString(),
      );

  factory AppError._unknown(Object e) => AppError(
        kind: AppErrorKind.unknown,
        title: "We won't keep you hungry for long.",
        message: "You're just one tap away from exploring the menu.",
        technical: e.toString(),
      );

  /// Not a failure: the request succeeded and there was nothing to show.
  ///
  /// A constructor rather than something [from] can produce, because only the
  /// caller knows an empty list is expected here and a problem there.
  factory AppError.empty() => const AppError(
        kind: AppErrorKind.empty,
        title: 'Nothing here yet.',
        message: 'Try another location or explore a different menu.',
        technical: 'empty result (not an error)',
      );

  /// Send the technical detail where developers can see it, and only there.
  ///
  /// Debug builds only: a release build must not print internals to logcat,
  /// and the customer-facing copy already said everything they need.
  void logTo(String context) {
    if (kDebugMode) debugPrint('[$context] ${kind.name}: $technical');
  }

  @override
  String toString() => 'AppError(${kind.name}: $title)';
}
