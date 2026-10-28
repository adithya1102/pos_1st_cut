import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config/app_config.dart';

/// "New restaurant? Join Gusto Skip" — what a prospective owner sees.
///
/// DELIBERATELY NOT A FORM. There is no sign-up endpoint behind this and no
/// native form in this app: registration is a conversation CareVo's team
/// finishes by phone, and this screen says so and hands off to whatever form
/// they are currently using.
///
/// Building a native form would mean inventing a backend endpoint, validating
/// fields nobody has agreed on, and shipping a store release every time the
/// questions change. A link costs none of that, and the honest promise — "our
/// team will call you shortly" — is the one the team can actually keep.
///
/// THE BUTTON IS HIDDEN WHEN THE URL IS EMPTY, not disabled. The URL arrives
/// as a --dart-define with no default, so a build that forgot to set it shows
/// the explanation and no dead control. A greyed button would invite a tap and
/// then do nothing, which is the worst of the three options.
class OnboardingScreen extends StatelessWidget {
  const OnboardingScreen({super.key, this.formUrl});

  static const routeName = '/onboarding';

  /// Overridable for tests. Defaults to the compile-time define.
  final String? formUrl;

  String get _url => (formUrl ?? AppConfig.onboardingFormUrl).trim();
  bool get _hasUrl => _url.isNotEmpty;

  Future<void> _open(BuildContext context) async {
    final uri = Uri.tryParse(_url);
    if (uri == null) return;
    // externalApplication: this is a web form the owner will fill in at
    // leisure, quite possibly while on the phone to the team, so it belongs in
    // a real browser rather than a webview inside a POS app.
    final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open the form.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(title: const Text('Join Gusto Skip')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 24, 24, 32),
          children: [
            Text(
              'Get orders on Gusto Skip',
              key: const Key('onboarding_title'),
              style: theme.textTheme.headlineSmall
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 12),
            Text(
              'Tell us about your restaurant. Our team will call you shortly '
              'and finish the registration in about 10 minutes.',
              key: const Key('onboarding_body'),
              style: theme.textTheme.bodyLarge,
            ),
            const SizedBox(height: 28),
            if (_hasUrl)
              FilledButton.icon(
                key: const Key('onboarding_register_button'),
                onPressed: () => _open(context),
                icon: const Icon(Icons.open_in_new),
                label: const Text('Register your restaurant'),
              )
            else
              // No URL configured in this build. Says what to do instead of
              // showing a control that cannot work.
              Text(
                'Registration is not available in this build. Please contact '
                'the Gusto Skip team directly.',
                key: const Key('onboarding_no_url'),
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: theme.colorScheme.outline),
              ),
          ],
        ),
      ),
    );
  }
}
