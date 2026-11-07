import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/payment_settings.dart';
import '../services/api_client.dart';
import '../services/outlet_service.dart';
import '../strings/payment_strings.dart';

/// Which of the three cards is mid-save, or none.
enum _SavingMode { none, pickup, upi, gateway }

/// The Payment tab (bottom nav, between Menu and Offers).
///
/// Three independent switches, one per payment method. Unlike the older
/// [PaymentModesScreen] (still reachable from Outlet settings, unchanged),
/// EACH SWITCH SAVES ITSELF the moment it is flipped — there is no separate
/// Save button for the toggles, because a switch that visibly moved but
/// silently did not save is a worse bug than one extra network call.
///
/// On any server error the switch snaps back to its previous value and the
/// server's own sentence is shown — never a guess at what went wrong.
class PaymentTabScreen extends StatefulWidget {
  const PaymentTabScreen({super.key});

  static const routeName = '/payment-tab';

  @override
  State<PaymentTabScreen> createState() => _PaymentTabScreenState();
}

class _PaymentTabScreenState extends State<PaymentTabScreen> {
  PaymentSettings? _settings;
  bool _loading = true;
  bool _forbidden = false;
  String? _loadError;
  String? _saveError;
  _SavingMode _saving = _SavingMode.none;

  final _vpa = TextEditingController();
  final _payee = TextEditingController();
  bool _attested = false;

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
      _loadError = null;
    });
    try {
      final s = await context.read<OutletService>().getPaymentSettings();
      if (!mounted) return;
      setState(() {
        _settings = s;
        _vpa.text = s.upiVpa ?? '';
        _payee.text = s.upiPayeeName ?? '';
        _attested = s.upiAttested;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _forbidden = e.statusCode == 403;
        _loadError = e.serverMessage ?? e.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadError = PaymentStrings.couldNotLoad;
      });
    }
  }

  bool get _vpaChanged =>
      _vpa.text.trim() != (_settings?.upiVpa ?? '').trim();

  /// Sends the FULL desired state — the server requires it, and this screen
  /// is no exception to that even though each switch looks independent.
  Future<bool> _patch({
    bool? prepaid,
    bool? payAtPickup,
    bool? upiManual,
    bool? upiAttested,
  }) async {
    final s = _settings;
    if (s == null) return false;
    try {
      final next = await context.read<OutletService>().setPaymentSettings(
            prepaid: prepaid ?? s.prepaid,
            payAtPickup: payAtPickup ?? s.payAtPickup,
            upiManual: upiManual ?? s.upiManual,
            upiVpa: _vpa.text.trim().isEmpty ? null : _vpa.text.trim(),
            upiPayeeName: _payee.text.trim().isEmpty ? null : _payee.text.trim(),
            upiAttested: upiAttested ?? _attested,
          );
      if (!mounted) return true;
      setState(() {
        _settings = next;
        _vpa.text = next.upiVpa ?? '';
        _payee.text = next.upiPayeeName ?? '';
        _attested = next.upiAttested;
        _saveError = null;
      });
      return true;
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _forbidden = _forbidden || e.statusCode == 403;
          _saveError = e.serverMessage ?? e.message;
        });
      }
      return false;
    } catch (_) {
      if (mounted) setState(() => _saveError = PaymentStrings.couldNotSave);
      return false;
    }
  }

  Future<void> _togglePickup(bool v) async {
    setState(() => _saving = _SavingMode.pickup);
    final ok = await _patch(payAtPickup: v);
    if (mounted) setState(() => _saving = _SavingMode.none);
    // A failed PATCH already left `_settings` (and therefore the switch's
    // bound value) untouched, which IS the revert — nothing further to do.
    if (!ok) return;
  }

  Future<void> _toggleUpi(bool v) async {
    setState(() => _saving = _SavingMode.upi);
    final ok = await _patch(upiManual: v, upiAttested: _attested);
    if (mounted) setState(() => _saving = _SavingMode.none);
    if (!ok) return;
  }

  Future<void> _toggleGateway(bool v) async {
    setState(() => _saving = _SavingMode.gateway);
    final ok = await _patch(prepaid: v);
    if (mounted) setState(() => _saving = _SavingMode.none);
    if (!ok) return;
  }

  /// Saves only the VPA/payee/attestation — used by the "Save UPI details"
  /// button so a VPA can be set up BEFORE the switch is flipped on, exactly
  /// as the reused attestation flow has always worked.
  Future<void> _saveUpiDetails() async {
    setState(() => _saving = _SavingMode.upi);
    await _patch(upiManual: _settings?.upiManual, upiAttested: _attested);
    if (mounted) setState(() => _saving = _SavingMode.none);
  }

  /// No own Scaffold/AppBar — this is a TAB BODY, shown inside home_screen's
  /// IndexedStack under its own AppBar, the same shape as OffersScreen and
  /// the inline _DishesTab.
  @override
  Widget build(BuildContext context) {
    final s = _settings;
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (s == null) {
      return _LoadFailure(
        forbidden: _forbidden,
        message: _loadError,
        onRetry: _load,
      );
    }
    return _buildCards(context, s);
  }

  Widget _buildCards(BuildContext context, PaymentSettings s) {
    final theme = Theme.of(context);
    final offered = s.effectiveMethods;

    return ListView(
      key: const Key('payment_tab_list'),
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 28),
      children: [
        _PickupCard(
          value: s.payAtPickup,
          saving: _saving == _SavingMode.pickup,
          locked: _forbidden,
          onChanged: _togglePickup,
        ),
        const SizedBox(height: 16),
        _UpiCard(
          value: s.upiManual,
          saving: _saving == _SavingMode.upi,
          locked: _forbidden,
          vpa: _vpa,
          payee: _payee,
          attested: _attested,
          vpaChanged: _vpaChanged,
          onToggle: _toggleUpi,
          onAttestedChanged: (v) => setState(() {
            _attested = v;
          }),
          onVpaChanged: () => setState(() {
            if (_vpaChanged) _attested = false;
          }),
          onSaveDetails: _saveUpiDetails,
        ),
        const SizedBox(height: 16),
        _GatewayCard(
          value: s.prepaid,
          available: s.gatewayAvailable,
          saving: _saving == _SavingMode.gateway,
          locked: _forbidden,
          onChanged: _toggleGateway,
        ),
        const SizedBox(height: 20),
        if (_saveError != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Row(
              key: const Key('payment_tab_error'),
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.error_outline,
                    size: 18, color: theme.colorScheme.error),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(_saveError!,
                      style: theme.textTheme.bodyMedium
                          ?.copyWith(color: theme.colorScheme.error)),
                ),
              ],
            ),
          ),
        _SummaryLine(offered: offered),
      ],
    );
  }
}

class _LoadFailure extends StatelessWidget {
  const _LoadFailure(
      {required this.forbidden, required this.message, required this.onRetry});

  final bool forbidden;
  final String? message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      key: forbidden
          ? const Key('payment_tab_forbidden')
          : const Key('payment_tab_load_error'),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(forbidden ? Icons.lock_outline : Icons.cloud_off, size: 40),
            const SizedBox(height: 12),
            Text(
              message ??
                  (forbidden
                      ? PaymentStrings.forbidden
                      : PaymentStrings.couldNotLoad),
              key: const Key('payment_tab_message'),
              textAlign: TextAlign.center,
            ),
            if (!forbidden) ...[
              const SizedBox(height: 16),
              FilledButton.tonal(
                key: const Key('payment_tab_retry'),
                onPressed: onRetry,
                child: const Text(PaymentStrings.retry),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Shared chrome for the three cards: a card, a title row with the switch (or
/// a trailing spinner while that card is saving), and the note beneath it.
class _ModeCard extends StatelessWidget {
  const _ModeCard({
    required this.cardKey,
    required this.switchKey,
    required this.title,
    required this.note,
    required this.value,
    required this.saving,
    required this.enabled,
    required this.onChanged,
    this.extra,
  });

  final Key cardKey;
  final Key switchKey;
  final String title;
  final String note;
  final bool value;
  final bool saving;
  final bool enabled;
  final ValueChanged<bool>? onChanged;
  final Widget? extra;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      key: cardKey,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(4, 4, 4, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ListTile(
              title: Text(title),
              trailing: saving
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Switch(
                      key: switchKey,
                      value: value,
                      onChanged: enabled ? onChanged : null,
                    ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Text(
                note,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.outline),
              ),
            ),
            if (extra != null) extra!,
          ],
        ),
      ),
    );
  }
}

class _PickupCard extends StatelessWidget {
  const _PickupCard({
    required this.value,
    required this.saving,
    required this.locked,
    required this.onChanged,
  });

  final bool value;
  final bool saving;
  final bool locked;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) => _ModeCard(
        cardKey: const Key('payment_tab_pickup_card'),
        switchKey: const Key('payment_tab_pickup_switch'),
        title: PaymentStrings.pickupTitle,
        note: PaymentStrings.pickupNote,
        value: value,
        saving: saving,
        enabled: !locked,
        onChanged: onChanged,
      );
}

class _GatewayCard extends StatelessWidget {
  const _GatewayCard({
    required this.value,
    required this.available,
    required this.saving,
    required this.locked,
    required this.onChanged,
  });

  final bool value;
  final bool available;
  final bool saving;
  final bool locked;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) => _ModeCard(
        cardKey: const Key('payment_tab_gateway_card'),
        switchKey: const Key('payment_tab_gateway_switch'),
        title: PaymentStrings.gatewayTitle,
        note: available
            ? PaymentStrings.gatewayAvailableNote
            : PaymentStrings.gatewayUnavailableNote,
        value: value,
        saving: saving,
        // Greyed and disabled when unavailable, regardless of `locked` —
        // a switch guaranteed to fail on tap must never look tappable.
        enabled: !locked && available,
        onChanged: onChanged,
      );
}

class _UpiCard extends StatelessWidget {
  const _UpiCard({
    required this.value,
    required this.saving,
    required this.locked,
    required this.vpa,
    required this.payee,
    required this.attested,
    required this.vpaChanged,
    required this.onToggle,
    required this.onAttestedChanged,
    required this.onVpaChanged,
    required this.onSaveDetails,
  });

  final bool value;
  final bool saving;
  final bool locked;
  final TextEditingController vpa;
  final TextEditingController payee;
  final bool attested;
  final bool vpaChanged;
  final ValueChanged<bool> onToggle;
  final ValueChanged<bool> onAttestedChanged;
  final VoidCallback onVpaChanged;
  final VoidCallback onSaveDetails;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final enabled = !locked && !saving;
    return _ModeCard(
      cardKey: const Key('payment_tab_upi_card'),
      switchKey: const Key('payment_tab_upi_switch'),
      title: PaymentStrings.upiTitle,
      note: PaymentStrings.upiNote,
      value: value,
      saving: saving,
      enabled: !locked,
      onChanged: onToggle,
      extra: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              key: const Key('payment_tab_upi_vpa_field'),
              controller: vpa,
              enabled: enabled,
              autocorrect: false,
              enableSuggestions: false,
              decoration: const InputDecoration(
                labelText: PaymentStrings.upiVpaLabel,
                hintText: PaymentStrings.upiVpaHint,
              ),
              onChanged: (_) => onVpaChanged(),
            ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('payment_tab_upi_payee_field'),
              controller: payee,
              enabled: enabled,
              decoration: const InputDecoration(
                labelText: PaymentStrings.upiPayeeLabel,
                hintText: PaymentStrings.upiPayeeHint,
              ),
            ),
            CheckboxListTile(
              key: const Key('payment_tab_upi_attested_checkbox'),
              value: attested,
              onChanged:
                  enabled ? (v) => onAttestedChanged(v ?? false) : null,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              title: const Text(PaymentStrings.upiAttestLabel),
            ),
            if (vpaChanged && vpa.text.trim().isNotEmpty)
              Text(
                PaymentStrings.upiReattestHint,
                key: const Key('payment_tab_upi_reattest_hint'),
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.error),
              ),
            const SizedBox(height: 4),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                key: const Key('payment_tab_upi_save_details'),
                onPressed: enabled ? onSaveDetails : null,
                child: const Text(PaymentStrings.upiSaveDetails),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SummaryLine extends StatelessWidget {
  const _SummaryLine({required this.offered});

  final List<String> offered;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final text = offered.isEmpty
        ? PaymentStrings.summaryNone
        : PaymentStrings.summaryPrefix +
            offered.map(PaymentStrings.methodLabel).join(', ');
    return Text(
      text,
      key: const Key('payment_tab_summary'),
      style: theme.textTheme.bodyMedium?.copyWith(
        color: offered.isEmpty
            ? theme.colorScheme.error
            : theme.colorScheme.outline,
      ),
    );
  }
}
