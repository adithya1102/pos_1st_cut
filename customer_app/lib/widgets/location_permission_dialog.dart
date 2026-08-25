import 'package:flutter/material.dart';

import '../services/location_service.dart';

/// Explains a PERMANENTLY denied location permission, and offers the only
/// thing that can actually fix it.
///
/// ## Why a dialog and not the SnackBar this replaced
///
/// Both entry points previously answered `deniedForever` with a SnackBar
/// carrying a "Settings" action. That was wrong for this specific state:
///
///  * it disappears after a few seconds, so the one control that can resolve a
///    permanent denial is on a timer;
///  * there is no room in it to say WHY the app cannot simply ask again, so
///    the customer is left thinking the button is broken — they tapped
///    "Near me", nothing happened, and a toast flashed past.
///
/// A permanent denial is not a transient failure, so it does not get transient
/// UI. The other outcomes (service off, a plain denial the customer just made
/// deliberately, a lookup error) stay on SnackBars — those are momentary and
/// self-explanatory.
///
/// ## The Settings hand-off
///
/// `openAppSettings()` comes from geolocator, which is already the app's
/// location dependency — `permission_handler` is not in pubspec.yaml and is not
/// worth adding for one call that geolocator already exposes. It lands on this
/// app's permission page, not the global settings root.
///
/// The app does NOT need to do anything when the customer returns: the
/// lifecycle observer in `main.dart` calls
/// [LocationService.refreshPermission] on resume, so a grant made in Settings
/// is picked up without a restart.
Future<void> showLocationBlockedDialog(
  BuildContext context, {
  required LocationService service,

  /// What the customer was trying to do, e.g. "find restaurants near you".
  /// Named so the explanation is about their goal rather than about a
  /// permission flag.
  required String purpose,
}) {
  return showDialog<void>(
    context: context,
    builder: (c) => AlertDialog(
      key: const Key('location_blocked_dialog'),
      title: const Text('Location is turned off for CareVo'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('CareVo needs your location to $purpose.'),
          const SizedBox(height: 12),
          // States plainly that re-asking is not on the table, so the missing
          // "try again" button does not read as an oversight.
          const Text(
            'Location was blocked for this app, so we can no longer ask you '
            'here — it has to be turned back on in your device settings.',
            style: TextStyle(fontSize: 12),
          ),
          const SizedBox(height: 12),
          const Text(
            'You can keep going without it by picking your city instead.',
            style: TextStyle(fontSize: 12),
          ),
        ],
      ),
      actions: [
        TextButton(
          key: const Key('location_blocked_dismiss'),
          onPressed: () => Navigator.pop(c),
          child: const Text('Not now'),
        ),
        FilledButton(
          key: const Key('location_blocked_open_settings'),
          onPressed: () {
            // Popped first: the OS settings screen comes up over the app, and
            // leaving a dialog underneath it means returning to a modal the
            // customer has already dealt with.
            Navigator.pop(c);
            service.openSettings();
          },
          child: const Text('Open settings'),
        ),
      ],
    ),
  );
}
