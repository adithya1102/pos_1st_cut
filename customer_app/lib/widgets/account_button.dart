import 'package:flutter/material.dart';

import '../screens/profile_screen.dart';

/// The account entry point, defined ONCE and reused by every top-level screen.
///
/// Why an AppBar action rather than a bottom navigation bar: this app is a plain
/// `Navigator` push stack — there is no shell/`IndexedStack` route host — and
/// `bottomNavigationBar` is already occupied on the browsing screens (the cart
/// bar on the menu, the primary CTA on cart/checkout/dish detail). Adding a
/// global bottom nav would mean either evicting those CTAs or rebuilding
/// navigation around a shell, both far beyond this change. See
/// [careVoActions] for the shared action list.
class AccountButton extends StatelessWidget {
  const AccountButton({super.key});

  @override
  Widget build(BuildContext context) {
    return IconButton(
      icon: const Icon(Icons.person_outline),
      tooltip: 'Account',
      onPressed: () {
        // Avoid stacking a second Account screen on top of itself when the
        // button is tapped from within the profile flow.
        if (ModalRoute.of(context)?.settings.name == ProfileScreen.routeName) {
          return;
        }
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => const ProfileScreen(),
            settings: const RouteSettings(name: ProfileScreen.routeName),
          ),
        );
      },
    );
  }
}

/// Standard trailing actions for every top-level screen's AppBar: account, then
/// the theme toggle. One definition, so the set can never drift per screen.
///
/// Pass `account: false` on screens where an account link makes no sense
/// (login/OTP), and on the Account screen itself.
/// v2 is single-theme, so the light/dark toggle was removed rather than left
/// as a control that visibly does nothing. ThemeProvider itself is retained —
/// it still persists a preference a future variant could read.
List<Widget> careVoActions({bool account = true}) => [
      if (account) const AccountButton(),
      const SizedBox(width: 8),
    ];
