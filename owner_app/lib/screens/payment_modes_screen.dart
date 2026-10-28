import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/payment_settings.dart';
import '../services/api_client.dart';
import '../services/outlet_service.dart';

/// Where the owner chooses how their restaurant gets paid.
///
/// THREE THINGS THIS SCREEN IS CAREFUL ABOUT
/// -----------------------------------------
/// 1. CASHFREE IS INVISIBLE UNTIL ACTIVATED. When `cashfree_unlocked` is false
///    the row is not rendered at all — no greyed switch, no explanatory text,
///    no hint. A control for something the owner cannot act on is worse than
///    nothing: it generates a support question with no answer. When it is
///    true the toggle behaves normally.
///
/// 2. THE WARNINGS SIT WITH THE THING THEY WARN ABOUT. Pay-at-pickup's
///    no-show risk and direct UPI's check-the-amount instruction are printed
///    directly beneath their own toggles, not collected in a footnote — the
///    moment to read "customers may not show up" is while deciding to accept
///    that risk.
///
/// 3. IT NEVER LETS ALL THREE BE OFF. Enforced locally so the owner gets an
///    immediate sentence, and again by the server, and again by a database
///    CHECK. The local check is a courtesy; the other two are the rule.
///
/// The screen shows the SERVER's error text rather than inventing its own.
/// Those messages are written for an owner — "Send yourself Rs 1 using this
/// UPI ID, confirm you received it, then turn this on" — and paraphrasing them
/// here would mean two places to keep in step.
class PaymentModesScreen extends StatefulWidget {
  const PaymentModesScreen({super.key});

  static const routeName = '/payment-modes';

  @override
  State<PaymentModesScreen> createState() => _PaymentModesScreenState();
}

class _PaymentModesScreenState extends State<PaymentModesScreen> {
  PaymentSettings? _settings;
  bool _loading = true;
  bool _saving = false;
  String? _error;

  // Local edit state, seeded from the server once loaded.
  bool _prepaid = false;
  bool _pickup = false;
  bool _upi = false;
  bool _attested = false;
  final _vpa = TextEditingController();
  final _payee = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _vpa.dispose();
    _payee.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final s = await context.read<OutletService>().getPaymentSettings();
      if (!mounted) return;
      setState(() {
        _settings = s;
        _prepaid = s.prepaid;
        _pickup = s.payAtPickup;
        _upi = s.upiManual;
        _attested = s.upiAttested;
        _vpa.text = s.upiVpa ?? '';
        _payee.text = s.upiPayeeName ?? '';
        _loading = false;
      });
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e.serverMessage ?? e.message;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'Could not load your payment settings.';
        });
      }
    }
  }

  /// True when the VPA in the box differs from the one the server has.
  ///
  /// Changing it voids the attestation server-side, so the checkbox is reset
  /// locally too — otherwise the owner would see a ticked box for a string
  /// nobody has proven they control.
  bool get _vpaChanged =>
      _vpa.text.trim() != (_settings?.upiVpa ?? '').trim();

  Future<void> _save() async {
    // The local half of rule 3. The server and the database enforce it too.
    if (!_prepaid && !_pickup && !_upi) {
      setState(() => _error =
          'Your restaurant must accept at least one payment method.');
      return;
    }

    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final s = await context.read<OutletService>().setPaymentSettings(
            prepaid: _prepaid,
            payAtPickup: _pickup,
            upiManual: _upi,
            upiVpa: _vpa.text.trim().isEmpty ? null : _vpa.text.trim(),
            upiPayeeName:
                _payee.text.trim().isEmpty ? null : _payee.text.trim(),
            upiAttested: _attested,
          );
      if (!mounted) return;
      setState(() {
        _settings = s;
        _prepaid = s.prepaid;
        _pickup = s.payAtPickup;
        _upi = s.upiManual;
        _attested = s.upiAttested;
        _vpa.text = s.upiVpa ?? '';
        _payee.text = s.upiPayeeName ?? '';
        _saving = false;
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(const SnackBar(content: Text('Payment modes saved')));
    } on ApiException catch (e) {
      // The SERVER's sentence, verbatim. See the class docstring.
      //
      // `serverMessage`, not `message`: the latter is a .toString() of
      // whatever `detail` was, which for a structured error is Dart's debug
      // form of a Map.
      if (mounted) {
        setState(() {
          _saving = false;
          _error = e.serverMessage ?? e.message;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = 'Could not save. Check your connection and try again.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = _settings;

    return Scaffold(
      appBar: AppBar(title: const Text('Payment modes')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : (s == null
              ? Center(
                  key: const Key('payment_modes_load_error'),
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.cloud_off, size: 40),
                        const SizedBox(height: 12),
                        Text(_error ?? 'Could not load your settings.',
                            textAlign: TextAlign.center),
                        const SizedBox(height: 16),
                        FilledButton.tonal(
                          key: const Key('payment_modes_retry'),
                          onPressed: _load,
                          child: const Text('Retry'),
                        ),
                      ],
                    ),
                  ),
                )
              : ListView(
                  key: const Key('payment_modes_list'),
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 28),
                  children: [
                    Text('How do you want to be paid?',
                        style: theme.textTheme.titleMedium),
                    const SizedBox(height: 4),
                    Text(
                      'You can turn more than one on. Customers choose at '
                      'checkout.',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.outline),
                    ),
                    const SizedBox(height: 16),

                    // ---------------------- 1. Cashfree --------------------
                    // RENDERED ONLY WHEN UNLOCKED. See the class docstring.
                    if (s.showCashfreeRow) ...[
                      SwitchListTile(
                        key: const Key('toggle_cashfree'),
                        value: _prepaid,
                        onChanged: _saving
                            ? null
                            : (v) => setState(() => _prepaid = v),
                        title: const Text('Online payment (Cashfree)'),
                        subtitle: const Text(
                            'Customers pay by UPI, card or net banking before '
                            'they arrive.'),
                      ),
                      const Divider(height: 8),
                    ],

                    // ------------------- 2. Pay at pickup ------------------
                    SwitchListTile(
                      key: const Key('toggle_pay_at_pickup'),
                      value: _pickup,
                      onChanged:
                          _saving ? null : (v) => setState(() => _pickup = v),
                      title: const Text('Pay at pickup'),
                      subtitle: const Text(
                          'Customers order first and pay when they collect.'),
                    ),
                    // The warning sits directly beneath its own toggle.
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                      child: Text(
                        'Customers may order and not show up. You will call '
                        'each customer to confirm before you start cooking.',
                        key: const Key('pay_at_pickup_note'),
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.outline),
                      ),
                    ),
                    const Divider(height: 8),

                    // ---------------------- 3. Direct UPI ------------------
                    SwitchListTile(
                      key: const Key('toggle_upi_manual'),
                      value: _upi,
                      onChanged: _saving
                          ? null
                          : (v) => setState(() => _upi = v),
                      title: const Text('Pay directly to your UPI'),
                      subtitle: const Text(
                          'Customers pay your UPI ID from their own app. No '
                          'commission.'),
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                      child: Text(
                        'Accept an order only after you have checked that the '
                        'exact amount has reached your UPI app.',
                        key: const Key('upi_manual_note'),
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.outline),
                      ),
                    ),

                    // The UPI details. Always editable, so an owner can set
                    // them up before switching the method on.
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          TextField(
                            key: const Key('upi_vpa_field'),
                            controller: _vpa,
                            enabled: !_saving,
                            autocorrect: false,
                            enableSuggestions: false,
                            decoration: const InputDecoration(
                              labelText: 'Your UPI ID',
                              hintText: 'restaurant@okaxis',
                            ),
                            onChanged: (_) => setState(() {
                              // A new string has no proof attached to it.
                              if (_vpaChanged) _attested = false;
                            }),
                          ),
                          const SizedBox(height: 8),
                          TextField(
                            key: const Key('upi_payee_field'),
                            controller: _payee,
                            enabled: !_saving,
                            decoration: const InputDecoration(
                              labelText: 'Name on the UPI account',
                              hintText: 'Test Kitchen',
                            ),
                          ),
                          CheckboxListTile(
                            key: const Key('upi_attested_checkbox'),
                            value: _attested,
                            onChanged: _saving
                                ? null
                                : (v) =>
                                    setState(() => _attested = v ?? false),
                            contentPadding: EdgeInsets.zero,
                            controlAffinity:
                                ListTileControlAffinity.leading,
                            title: const Text(
                                'I sent myself Rs 1 using this UPI ID and '
                                'received it'),
                          ),
                          if (_vpaChanged && _vpa.text.trim().isNotEmpty)
                            Text(
                              'You changed your UPI ID, so please confirm the '
                              'Rs 1 test again.',
                              key: const Key('upi_reattest_hint'),
                              style: theme.textTheme.bodySmall?.copyWith(
                                  color: theme.colorScheme.error),
                            ),
                        ],
                      ),
                    ),

                    const SizedBox(height: 20),

                    if (_error != null)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: Row(
                          key: const Key('payment_modes_error'),
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(Icons.error_outline,
                                size: 18, color: theme.colorScheme.error),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(_error!,
                                  style: theme.textTheme.bodyMedium?.copyWith(
                                      color: theme.colorScheme.error)),
                            ),
                          ],
                        ),
                      ),

                    // A standing warning when nothing is on offer, which is
                    // the state a newly joined restaurant starts in.
                    if (s.acceptsNothing && !_saving)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: Text(
                          'You are not accepting any payments yet, so '
                          'customers cannot order.',
                          key: const Key('payment_modes_accepts_nothing'),
                          style: theme.textTheme.bodyMedium
                              ?.copyWith(color: theme.colorScheme.error),
                        ),
                      ),

                    FilledButton(
                      key: const Key('payment_modes_save'),
                      onPressed: _saving ? null : _save,
                      child: _saving
                          ? const SizedBox(
                              height: 18,
                              width: 18,
                              child:
                                  CircularProgressIndicator(strokeWidth: 2))
                          : const Text('Save'),
                    ),
                  ],
                )),
    );
  }
}
