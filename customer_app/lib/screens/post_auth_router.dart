import 'package:flutter/material.dart';

import 'home_screen.dart';
import 'name_capture_screen.dart';

/// Where a customer goes the moment authentication succeeds.
///
/// THE single decision point for post-auth routing. Both sign-in paths call it
/// — the OTP screen and the Google button — so "what happens after you sign in"
/// is answered in exactly one place rather than duplicated per screen and free
/// to drift.
///
/// ## Exactly one name-entry gate
///
/// A signup is sent through [NameCaptureScreen]; a returning sign-in goes
/// straight to Home.
///
/// This REPLACED a second gate that used to live inside `HomeScreen.build`,
/// which rendered the same screen whenever `customer.name` was empty. Two gates
/// firing on two different conditions is how a customer ends up asked twice, or
/// asked at a moment nothing explains — so the Home one was removed rather than
/// left alongside this. `is_new_account` is the better condition of the two: it
/// says "this account was created seconds ago", which is precisely when asking
/// for a name makes sense, and it does not depend on what the identity provider
/// happened to put in the name field.
///
/// A legacy account with no name is deliberately NOT trapped here — it reaches
/// Home and simply gets the nameless greeting ("Good morning" rather than
/// "Good morning, Asha"), with Account → Your name available whenever they
/// want it. Blocking someone who has been ordering for months, on launch, to
/// collect a nicety is a worse trade than a slightly plainer greeting.
///
/// [isNewAccount] comes from the API's `is_new_account`, which defaults to
/// false — so an older backend that omits it routes everyone to Home rather
/// than trapping returning customers behind a name prompt.
void routeAfterAuth(BuildContext context, {required bool isNewAccount}) {
  // pushAndRemoveUntil, not push: the login/OTP screens behind this are
  // meaningless once a session exists, and a back-press must not return to a
  // half-finished sign-in.
  Navigator.of(context).pushAndRemoveUntil(
    MaterialPageRoute(
      builder: (_) => isNewAccount
          ? NameCaptureScreen(
              key: const Key('name_capture_gate'),
              // Home replaces the name screen once a name exists, rather than
              // being pushed on top of it — nothing should be able to go
              // "back" into a prompt that has already been answered.
              onSaved: () => Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(builder: (_) => const HomeScreen()),
                (route) => false,
              ),
            )
          : const HomeScreen(),
    ),
    (route) => false,
  );
}
