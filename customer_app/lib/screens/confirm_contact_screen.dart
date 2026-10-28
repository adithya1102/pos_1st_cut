import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/customer_service.dart';
import '../state/auth_state.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/neo_text_field.dart';
import '../widgets/account_button.dart';
import '../widgets/focus_release.dart';

/// Confirm who the restaurant should call, before a non-prepaid order is placed.
///
/// WHY THE PHONE IS READ-ONLY
/// --------------------------
/// This is the one screen where it would be natural to let someone type a
/// different number, and it is the one place the app must not. The restaurant
/// is about to cook food, or to look for a payment, on the strength of this
/// number. Everywhere else in this product a phone is an identity established
/// by a verified sign-in and never asserted by the client — the server refuses
/// a client-supplied phone outright (`UpdateMeIn` takes a name and nothing
/// else), and the order snapshots the ACCOUNT's number rather than anything
/// sent in the request body.
///
/// So the field shows the verified number and offers a route to change it
/// properly rather than a text box. The cost is real: somebody ordering on a
/// friend's behalf cannot redirect the call, and must either sign in as
/// themselves or hand the phone over. That is the trade, and it is the right
/// way round — a typo here is a restaurant ringing a stranger about food it
/// has already started making.
///
/// The NAME is freely editable. It carries no identity weight, it is what gets
/// called out at the counter, and people legitimately order for others.
class ConfirmContactScreen extends StatefulWidget {
  const ConfirmContactScreen({
    super.key,
    required this.onConfirmed,
    this.methodLabel = 'Pay at pickup',
    this.onVerifyPhone,
  });

  /// Called once the name is settled and the customer has confirmed.
  final VoidCallback onConfirmed;

  /// What the customer chose, echoed so this screen is not a context-free
  /// interruption between tapping Pay and anything happening.
  final String methodLabel;

  /// Route to phone verification. Null hides the affordance — which is the
  /// case on a build where re-verification is not reachable, and showing a
  /// dead "Change" link would be worse than showing none.
  final VoidCallback? onVerifyPhone;

  @override
  State<ConfirmContactScreen> createState() => _ConfirmContactScreenState();
}

class _ConfirmContactScreenState extends State<ConfirmContactScreen> {
  late final TextEditingController _name;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(
        text: context.read<AuthState>().customer?.name ?? '');
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _confirm() async {
    final typed = _name.text.trim();
    if (typed.isEmpty) {
      setState(() => _error = 'Please enter a name for the order.');
      return;
    }

    final auth = context.read<AuthState>();
    final existing = auth.customer?.name ?? '';

    // Only PATCH when it actually changed. Confirming an unchanged name should
    // not cost a round trip, and should not fail if the network is flaky.
    if (typed == existing.trim()) {
      widget.onConfirmed();
      return;
    }

    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final updated = await context.read<CustomerService>().updateName(typed);
      auth.setCustomer(updated);
      if (!mounted) return;
      widget.onConfirmed();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Could not save the name. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final customer = context.watch<AuthState>().customer;
    final phone = customer?.phoneNumber?.trim() ?? '';

    return Scaffold(
      appBar: AppBar(
        title: const Text('Confirm your details'),
        actions: careVoActions(),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
          children: [
            Text('Who is this for?', style: textTheme.headlineSmall),
            const SizedBox(height: 6),
            Text(
              '${widget.methodLabel} — the restaurant will use these details.',
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
            const SizedBox(height: 20),

            NeoTextField(
              key: const Key('confirm_contact_name'),
              controller: _name,
              labelText: 'Name for the order',
              onSubmitted: (_) => releaseFocus(),
            ),
            const SizedBox(height: 16),

            // READ-ONLY, by design. See the class docstring.
            NeoCard(
              key: const Key('confirm_contact_phone'),
              child: Row(
                children: [
                  Icon(Icons.phone_outlined, color: c.primary),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Mobile number',
                            style: textTheme.bodySmall
                                ?.copyWith(color: c.inkSoft)),
                        const SizedBox(height: 2),
                        Text(phone.isEmpty ? 'Not verified yet' : phone,
                            key: const Key('confirm_contact_phone_value'),
                            style: textTheme.titleMedium),
                      ],
                    ),
                  ),
                  if (widget.onVerifyPhone != null)
                    TextButton(
                      key: const Key('confirm_contact_change_phone'),
                      onPressed: widget.onVerifyPhone,
                      child: const Text('Change'),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 10),
            Text(
              'This is the number you signed in with, so we know it reaches '
              'you. Changing it means verifying the new one.',
              key: const Key('confirm_contact_phone_note'),
              style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
            ),

            if (_error != null) ...[
              const SizedBox(height: 16),
              Row(
                key: const Key('confirm_contact_error'),
                children: [
                  Icon(Icons.error_outline, size: 18, color: AppColors.tomato),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(_error!,
                        style: textTheme.bodyMedium
                            ?.copyWith(color: AppColors.tomato)),
                  ),
                ],
              ),
            ],

            const SizedBox(height: 24),
            NeoButton(
              key: const Key('confirm_contact_continue'),
              label: 'Confirm and continue',
              icon: Icons.arrow_forward,
              loading: _saving,
              onPressed: _saving ? null : _confirm,
            ),
          ],
        ),
      ),
    );
  }
}
