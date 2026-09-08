import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/customer.dart';
import '../services/api_client.dart';
import '../services/customer_service.dart';
import '../state/auth_state.dart';
import 'login_screen.dart';
import 'order_history_screen.dart';
import '../widgets/account_button.dart';

/// Account screen: identity, loyalty points, coupon redemption, and logout.
///
/// Everything shown is fetched from `/customer/me` and `/customer/points`,
/// which are scoped to the bearer token — this screen never asks for a
/// customer by id.
class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  /// Used to avoid pushing Account on top of itself from the shared AppBar action.
  static const routeName = '/account';

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  Customer? _customer;
  PointsSummary? _points;
  String? _error;
  bool _loading = true;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final svc = context.read<CustomerService>();
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      // Both are independent reads; fetch together so the screen paints once.
      final results = await Future.wait([svc.me(), svc.points()]);
      if (!mounted) return;
      setState(() {
        _customer = results[0] as Customer;
        _points = results[1] as PointsSummary;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _loading = false;
      });
    }
  }

  // ------------------------------ Name edit --------------------------------
  Future<void> _editName() async {
    // Providers resolved up front, before any await: reading them off `context`
    // after the dialog closes is an async-gap use of BuildContext.
    final svc = context.read<CustomerService>();
    final auth = context.read<AuthState>();

    final controller = TextEditingController(text: _customer?.name ?? '');
    final newName = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Your name'),
        content: TextField(
          controller: controller,
          autofocus: true,
          textCapitalization: TextCapitalization.words,
          decoration: const InputDecoration(hintText: 'Name'),
          onSubmitted: (v) => Navigator.pop(c, v),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(c, controller.text),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (newName == null || newName.trim().isEmpty) return;

    setState(() => _busy = true);
    try {
      final updated = await svc.updateName(newName.trim());
      if (!mounted) return;
      setState(() {
        _customer = updated;
        _busy = false;
      });
      // Keep the session's cached customer in step, so other screens that read
      // it don't show the old name until the next login.
      auth.setCustomer(updated);
      _toast('Name updated.');
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      _toast(e.message);
    }
  }

  // --------------------------- Points redemption ---------------------------
  Future<void> _redeemPoints() async {
    final p = _points;
    if (p == null) return;
    setState(() => _busy = true);
    try {
      final coupon = await context.read<CustomerService>().redeemPoints();
      if (!mounted) return;
      setState(() => _busy = false);
      await _showCouponDialog(coupon);
      await _load();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      _toast(e.message);
    }
  }

  Future<void> _showCouponDialog(CouponEntry coupon) => showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Coupon ready'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Worth ₹${coupon.discountAmount.toStringAsFixed(0)} '
                  'on your next order.'),
              const SizedBox(height: 12),
              SelectableText(
                coupon.code,
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.5,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Enter this code at checkout.',
                style: TextStyle(fontSize: 12),
              ),
            ],
          ),
          actions: [
            FilledButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Got it'),
            ),
          ],
        ),
      );

  // ------------------------- Premium trial coupon --------------------------
  Future<void> _redeemTrialCode() async {
    final svc = context.read<CustomerService>();
    final controller = TextEditingController();
    final code = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Have a code?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Enter a trial code to unlock premium free.'),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              autofocus: true,
              textCapitalization: TextCapitalization.characters,
              decoration: const InputDecoration(hintText: 'e.g. TRY-ABCD2345'),
              onSubmitted: (v) => Navigator.pop(c, v),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(c, controller.text),
            child: const Text('Redeem'),
          ),
        ],
      ),
    );
    if (code == null || code.trim().isEmpty) return;

    setState(() => _busy = true);
    try {
      final result = await svc.redeemTrialCode(code);
      if (!mounted) return;
      setState(() => _busy = false);
      _toast(result.message);
      await _load();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      _toast(e.message);
    }
  }

  // -------------------------------- Logout ---------------------------------
  /// Irreversible account closure (Play Store requires an in-app route).
  ///
  /// Two-step on purpose: a plain "are you sure" is too easy to tap through for
  /// something with no undo, so the second step requires typing DELETE.
  ///
  /// ## The copy describes anonymisation, because that is what happens
  ///
  /// `CarevoService.delete_account` does NOT delete the customer row, and that
  /// is forced by the schema rather than chosen: `customer_orders.customer_id`
  /// is RESTRICT, so a row DELETE fails outright for anyone who has ever
  /// ordered, and cascading it would take the restaurants' revenue records with
  /// it. What the server actually does is null out name / email / phone /
  /// fcm_token, zero the points balance, replace `google_uid` with a
  /// `deleted:<id>` tombstone, and hard-delete coupons and push notifications.
  /// The row survives, unusable, holding the orders together.
  ///
  /// So the dialog must not promise erasure. "We will permanently erase" was
  /// wrong in the direction that matters — it is the claim someone would rely
  /// on when deciding, and the one they would be right to complain about after
  /// finding their orders still on a restaurant's books. It says "removed from
  /// your account" and "kept, with your name detached", both of which are
  /// literally what the UPDATE above does.
  Future<void> _deleteAccount() async {
    final warned = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        key: const Key('confirm_delete_account'),
        title: const Text('Delete your account?'),
        content: const Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Your account will be closed and you will not be able to '
                'sign in again. Removed from it:'),
            SizedBox(height: 8),
            Text('•  your name, phone number and email\n'
                '•  your saved sign-in\n'
                '•  your points balance and any unused coupons'),
            SizedBox(height: 12),
            Text(
              'Your past orders are NOT deleted. They stay on record for the '
              'restaurants\' tax and accounting obligations, with your name '
              'and contact details detached so the orders can no longer be '
              'traced back to you.',
              style: TextStyle(fontSize: 12),
            ),
            SizedBox(height: 8),
            Text(
              'This cannot be undone, and the account cannot be reopened.',
              style: TextStyle(fontSize: 12),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Keep my account')),
          TextButton(
            onPressed: () => Navigator.pop(c, true),
            style: TextButton.styleFrom(
              foregroundColor: Theme.of(context).colorScheme.error,
            ),
            child: const Text('Continue'),
          ),
        ],
      ),
    );
    if (warned != true || !mounted) return;

    final typed = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        key: const Key('confirm_delete_account_typed'),
        title: const Text('Type DELETE to confirm'),
        content: TextField(
          controller: typed,
          autofocus: true,
          autocorrect: false,
          decoration: const InputDecoration(hintText: 'DELETE'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          ValueListenableBuilder<TextEditingValue>(
            valueListenable: typed,
            builder: (_, v, _) => TextButton(
              // Enabled only on an exact match — no near-misses.
              onPressed: v.text.trim().toUpperCase() == 'DELETE'
                  ? () => Navigator.pop(c, true)
                  : null,
              style: TextButton.styleFrom(
                foregroundColor: Theme.of(context).colorScheme.error,
              ),
              child: const Text('Delete my account'),
            ),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _busy = true);
    try {
      final res = await context.read<CustomerService>().deleteAccount();
      if (!mounted) return;
      await context.read<AuthState>().logout();
      if (!mounted) return;
      // Same hard stack clear as logout: nothing authenticated is reachable
      // by going back, and the token is gone anyway.
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginScreen()),
        (route) => false,
      );
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(res.message)));
    } on ApiException catch (e) {
      if (mounted) _toast(e.message);
    } catch (_) {
      if (mounted) _toast('Could not reach the server. Try again.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _logout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Log out?'),
        content: const Text(
          "You'll need to sign in again to place an order.",
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(c, true),
            style: TextButton.styleFrom(
              foregroundColor: Theme.of(context).colorScheme.error,
            ),
            child: const Text('Log out'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    await context.read<AuthState>().logout();
    if (!mounted) return;
    // Clear the whole stack: no back-navigation into an authenticated screen
    // after the token is gone.
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (route) => false,
    );
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final c = _customer;
    final p = _points;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Account'),
        actions: careVoActions(account: false),
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : RefreshIndicator(
                onRefresh: _load,
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
                  children: [
                    if (_error != null) ...[
                      _ErrorBanner(message: _error!, onRetry: _load),
                      const SizedBox(height: 16),
                    ],

                    // ---------------------------- Identity ----------------
                    Text('Profile', style: theme.textTheme.titleMedium),
                    const SizedBox(height: 8),
                    Card(
                      child: Column(
                        children: [
                          ListTile(
                            title: const Text('Name'),
                            subtitle: Text(
                              (c?.name.isNotEmpty ?? false) ? c!.name : '—',
                            ),
                            trailing: IconButton(
                              icon: const Icon(Icons.edit_outlined),
                              onPressed: _busy ? null : _editName,
                              tooltip: 'Edit name',
                            ),
                          ),
                          const Divider(height: 1),
                          // ONE identifier row, not a Phone row and an Email
                          // row. An account has one or the other, so the second
                          // row was always a permanent "—" — which reads as
                          // missing data rather than as not-applicable. The
                          // label follows the value; see
                          // Customer.identifierDisplay for the both-populated
                          // tie-break.
                          //
                          // Read-only: it comes from a verified sign-in, so the
                          // app must not let the client assert it.
                          ListTile(
                            key: const Key('account_identifier'),
                            title: Text(c?.identifierLabel ?? 'Phone/Email'),
                            subtitle: Text(c?.identifierDisplay ?? '—'),
                          ),
                          const Divider(height: 1),
                          ListTile(
                            title: const Text('Plan'),
                            subtitle: Text(c?.plan ?? 'Free'),
                          ),
                        ],
                      ),
                    ),

                    const SizedBox(height: 24),

                    // ----------------------------- Points -----------------
                    Text('Rewards', style: theme.textTheme.titleMedium),
                    const SizedBox(height: 8),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Text('Points', style: theme.textTheme.bodyLarge),
                                Text(
                                  (p?.balance ?? 0).toStringAsFixed(2),
                                  style: theme.textTheme.headlineSmall,
                                ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            LinearProgressIndicator(value: p?.progress ?? 0),
                            const SizedBox(height: 8),
                            Text(
                              (p?.canRedeem ?? false)
                                  ? 'You can redeem now.'
                                  : '${(p?.threshold ?? 50).toStringAsFixed(0)} points '
                                      'unlocks a ₹${(p?.valueRupees ?? 100).toStringAsFixed(0)} coupon.',
                              style: theme.textTheme.bodySmall,
                            ),
                            const SizedBox(height: 12),
                            SizedBox(
                              width: double.infinity,
                              child: FilledButton(
                                onPressed: (_busy || !(p?.canRedeem ?? false))
                                    ? null
                                    : _redeemPoints,
                                child: Text(
                                  'Redeem ₹${(p?.valueRupees ?? 100).toStringAsFixed(0)} coupon',
                                ),
                              ),
                            ),
                            const SizedBox(height: 8),
                            SizedBox(
                              width: double.infinity,
                              child: OutlinedButton(
                                onPressed: _busy ? null : _redeemTrialCode,
                                child: const Text('Redeem a trial code'),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),

                    const SizedBox(height: 24),

                    // ---------------------------- History -----------------
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.receipt_long_outlined),
                        title: const Text('Order history'),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => const OrderHistoryScreen(),
                          ),
                        ),
                      ),
                    ),

                    const SizedBox(height: 32),

                    // ----------------------------- Logout -----------------
                    // Text-style, not a primary button: destructive-ish and
                    // deliberately not the visual focus of the screen.
                    Center(
                      child: Column(
                        children: [
                          TextButton(
                            onPressed: _busy ? null : _logout,
                            style: TextButton.styleFrom(
                              foregroundColor: theme.colorScheme.error,
                            ),
                            child: const Text('Log out'),
                          ),
                          const SizedBox(height: 4),
                          // Set apart and understated: irreversible, so it
                          // should never sit next to Log out looking like a
                          // peer of it.
                          TextButton(
                            key: const Key('delete_account_entry'),
                            onPressed: _busy ? null : _deleteAccount,
                            style: TextButton.styleFrom(
                              foregroundColor: theme.colorScheme.outline,
                            ),
                            child: const Text('Delete my account'),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: scheme.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              message,
              style: TextStyle(color: scheme.onErrorContainer),
            ),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}
