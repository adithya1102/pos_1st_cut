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
                          // Phone and email are read-only: they come from a
                          // verified sign-in, so the app must not let the
                          // client assert them.
                          ListTile(
                            title: const Text('Phone'),
                            subtitle: Text(c?.phoneDisplay ?? '—'),
                          ),
                          const Divider(height: 1),
                          ListTile(
                            title: const Text('Email'),
                            subtitle: Text(c?.emailDisplay ?? '—'),
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
                      child: TextButton(
                        onPressed: _busy ? null : _logout,
                        style: TextButton.styleFrom(
                          foregroundColor: theme.colorScheme.error,
                        ),
                        child: const Text('Log out'),
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
