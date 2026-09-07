import 'package:flutter/material.dart';

import '../services/app_error.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';

/// The one way an API failure is shown to a customer.
///
/// Takes a classified [AppError] and renders its copy — it does no classifying
/// and holds no strings of its own, so the wording lives in exactly one place
/// ([AppError]) and cannot drift screen to screen. The technical cause is not
/// rendered anywhere here; it goes to the log via [AppError.logTo].
///
/// Two shapes, because a failure means different things depending on what is
/// already on screen:
///
///  * [ErrorStateView] — the whole area failed and there is nothing else to
///    show. Centred, with the retry as the primary action.
///  * [ErrorBanner] — content is already visible and a refresh failed. Inline
///    and quiet, because the customer is not blocked.
class ErrorStateView extends StatelessWidget {
  const ErrorStateView({
    super.key,
    required this.error,
    this.onRetry,
    this.retryLabel = 'Try Again',
  });

  final AppError error;

  /// Re-fires the original request. Required in practice for everything except
  /// [AppErrorKind.empty] — see [AppError.canRetry].
  final Future<void> Function()? onRetry;
  final String retryLabel;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final showRetry = error.canRetry && onRetry != null;

    return Center(
      child: SingleChildScrollView(
        // Scrollable so it still works under a keyboard or on a short screen,
        // and so a parent RefreshIndicator keeps a scrollable to attach to.
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(28, 40, 28, 40),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(_icon, size: 46, color: c.inkSoft),
            const SizedBox(height: 18),
            Text(
              error.title,
              key: const Key('error_state_title'),
              textAlign: TextAlign.center,
              style: textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text(
              error.message,
              key: const Key('error_state_message'),
              textAlign: TextAlign.center,
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
            if (showRetry) ...[
              const SizedBox(height: 24),
              NeoButton(
                key: const Key('error_state_retry'),
                label: retryLabel,
                icon: Icons.refresh,
                onPressed: () => onRetry!(),
              ),
            ],
          ],
        ),
      ),
    );
  }

  /// Chosen per category so the state is recognisable before it is read.
  IconData get _icon => switch (error.kind) {
        AppErrorKind.offline => Icons.wifi_off_rounded,
        AppErrorKind.timeout => Icons.hourglass_bottom_rounded,
        AppErrorKind.server => Icons.cloud_off_rounded,
        AppErrorKind.request => Icons.restaurant_menu_rounded,
        AppErrorKind.empty => Icons.search_off_rounded,
        AppErrorKind.unknown => Icons.sentiment_satisfied_alt_rounded,
      };
}

/// The inline form, for when content is already on screen and only a refresh
/// failed. Same copy, same classification — less shouting.
class ErrorBanner extends StatelessWidget {
  const ErrorBanner({super.key, required this.error, this.onRetry});

  final AppError error;
  final Future<void> Function()? onRetry;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return Container(
      key: const Key('error_banner'),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: c.surfaceAlt,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: c.border, width: 2),
      ),
      child: Row(
        children: [
          Icon(Icons.info_outline, size: 18, color: c.inkSoft),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(error.title,
                    key: const Key('error_banner_title'),
                    style: textTheme.bodyMedium),
                Text(
                  error.message,
                  style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                ),
              ],
            ),
          ),
          if (error.canRetry && onRetry != null)
            TextButton(
              key: const Key('error_banner_retry'),
              onPressed: () => onRetry!(),
              child: const Text('Try Again'),
            ),
        ],
      ),
    );
  }
}
