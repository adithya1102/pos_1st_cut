import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../models/offer.dart';
import '../state/offers_state.dart';

/// Create / edit one Restaurant Offer.
///
/// Deliberately simpler than the admin campaign form, and deliberately not
/// framed as a "coupon code":
///
///  * No scope or funding field. Every offer made here is funded by this
///    restaurant — that is decided by the endpoint, not by anything on screen.
///  * No name field. The label is derived server-side from the numbers, so the
///    text the customer reads can never describe a different offer than the one
///    that will actually be applied.
///  * A code is OPTIONAL and framed as "share it", because the default and
///    expected case is an offer that simply appears on the restaurant's card.
class OfferEditScreen extends StatefulWidget {
  const OfferEditScreen({super.key, this.offer});

  /// Null = creating.
  final Offer? offer;

  @override
  State<OfferEditScreen> createState() => _OfferEditScreenState();
}

class _OfferEditScreenState extends State<OfferEditScreen> {
  final _formKey = GlobalKey<FormState>();

  late bool _isPercent;
  late final TextEditingController _value;
  late final TextEditingController _maxDiscount;
  late final TextEditingController _minOrder;
  late final TextEditingController _code;
  late bool _isActive;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final o = widget.offer;
    _isPercent = o?.isPercent ?? true;
    _value = TextEditingController(text: _fmt(o?.discountValue));
    _maxDiscount = TextEditingController(text: _fmt(o?.maxDiscountAmount));
    _minOrder = TextEditingController(text: _fmt(o?.minOrderValue));
    _code = TextEditingController(text: o?.code ?? '');
    _isActive = o?.isActive ?? false;
  }

  /// Trims the trailing ".0" so an owner sees "20", not "20.0", in a field they
  /// are about to edit.
  static String _fmt(double? v) {
    if (v == null) return '';
    return v == v.roundToDouble() ? v.toInt().toString() : v.toString();
  }

  @override
  void dispose() {
    _value.dispose();
    _maxDiscount.dispose();
    _minOrder.dispose();
    _code.dispose();
    super.dispose();
  }

  double? _num(TextEditingController c) {
    final t = c.text.trim();
    if (t.isEmpty) return null;
    return double.tryParse(t);
  }

  /// Mirrors the server's `benefit_text`, so the owner reads the exact sentence
  /// the customer will. Kept in sync by shipping the same wording; the saved
  /// row's own benefit_text is what the list and the customer app then show.
  String get _preview {
    final v = _num(_value);
    if (v == null || v <= 0) return 'Fill in the amount to see your offer.';
    final cap = _num(_maxDiscount);
    final min = _num(_minOrder);
    var text = _isPercent
        ? '${_fmt(v)}% off${cap != null ? ' up to ₹${_fmt(cap)}' : ''}'
        : '₹${_fmt(v)} off';
    if (min != null && min > 0) text += ' on orders above ₹${_fmt(min)}';
    return text;
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;

    final state = context.read<OffersState>();
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    setState(() => _saving = true);

    final type = _isPercent ? 'PERCENT' : 'FLAT';
    // A flat offer has no percentage to cap, so any leftover value in that
    // field is dropped rather than saved as a meaningless ceiling.
    final cap = _isPercent ? _num(_maxDiscount) : null;
    final code = _code.text.trim().toUpperCase();

    final error = widget.offer == null
        ? await state.create(
            discountType: type,
            discountValue: _num(_value)!,
            maxDiscountAmount: cap,
            minOrderValue: _num(_minOrder),
            code: code.isEmpty ? null : code,
            isActive: _isActive,
          )
        : await state.update(
            widget.offer!.id,
            discountType: type,
            discountValue: _num(_value),
            maxDiscountAmount: cap,
            minOrderValue: _num(_minOrder),
            code: code.isEmpty ? null : code,
            isActive: _isActive,
          );

    if (!mounted) return;
    setState(() => _saving = false);
    if (error != null) {
      messenger.showSnackBar(SnackBar(content: Text(error)));
      return;
    }
    navigator.pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final editing = widget.offer != null;

    return Scaffold(
      appBar: AppBar(title: Text(editing ? 'Edit offer' : 'Create offer')),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: FilledButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox(
                    width: 18, height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : Text(editing ? 'Save offer' : 'Create offer'),
          ),
        ),
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
          children: [
            Text('What are you giving?', style: theme.textTheme.titleMedium),
            const SizedBox(height: 10),
            SegmentedButton<bool>(
              segments: const [
                ButtonSegment(
                  value: true, label: Text('% off'), icon: Icon(Icons.percent),
                ),
                ButtonSegment(
                  value: false,
                  label: Text('Flat ₹ off'),
                  icon: Icon(Icons.currency_rupee),
                ),
              ],
              selected: {_isPercent},
              onSelectionChanged: (v) => setState(() => _isPercent = v.first),
            ),
            const SizedBox(height: 20),

            TextFormField(
              controller: _value,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
              ],
              decoration: InputDecoration(
                labelText: _isPercent ? 'Percent off' : 'Rupees off',
                prefixText: _isPercent ? null : '₹ ',
                suffixText: _isPercent ? '%' : null,
              ),
              onChanged: (_) => setState(() {}),
              validator: (_) {
                final v = _num(_value);
                if (v == null || v <= 0) return 'Enter an amount.';
                if (_isPercent && v > 100) return 'Cannot be more than 100%.';
                return null;
              },
            ),
            const SizedBox(height: 16),

            // The guardrail, in the owner's own terms. Required, not merely
            // suggested — the server and a DB CHECK both refuse an uncapped
            // percentage offer, so allowing it here would only produce a
            // rejection the owner cannot act on.
            if (_isPercent) ...[
              TextFormField(
                controller: _maxDiscount,
                keyboardType:
                    const TextInputType.numberWithOptions(decimal: true),
                inputFormatters: [
                  FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                ],
                decoration: const InputDecoration(
                  labelText: 'Most you will give on one order',
                  prefixText: '₹ ',
                  helperText:
                      'Required. Without it, a large order could take an '
                      'unlimited amount off.',
                  helperMaxLines: 3,
                ),
                onChanged: (_) => setState(() {}),
                validator: (_) {
                  if (!_isPercent) return null;
                  final v = _num(_maxDiscount);
                  if (v == null || v <= 0) return 'Set a maximum.';
                  return null;
                },
              ),
              const SizedBox(height: 16),
            ],

            TextFormField(
              controller: _minOrder,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
              ],
              decoration: const InputDecoration(
                labelText: 'Minimum order (optional)',
                prefixText: '₹ ',
                helperText: 'Leave blank to apply to any order.',
              ),
              onChanged: (_) => setState(() {}),
              validator: (_) {
                if (_minOrder.text.trim().isEmpty) return null;
                final v = _num(_minOrder);
                if (v == null || v < 0) return 'Enter a valid amount.';
                return null;
              },
            ),
            const SizedBox(height: 20),

            _PreviewCard(text: _preview),
            const SizedBox(height: 20),

            Text('Share it (optional)', style: theme.textTheme.titleMedium),
            const SizedBox(height: 6),
            Text(
              'Your offer already shows on your restaurant card in the Gusto '
              'app. Add a code only if you also want to post or print it.',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 10),
            TextFormField(
              controller: _code,
              textCapitalization: TextCapitalization.characters,
              autocorrect: false,
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[A-Za-z0-9\-]')),
                LengthLimitingTextInputFormatter(24),
              ],
              decoration: const InputDecoration(
                labelText: 'Code (optional)',
                hintText: 'LUNCH20',
              ),
              validator: (_) {
                final t = _code.text.trim();
                if (t.isEmpty) return null;
                if (t.length < 3) return 'Use at least 3 characters.';
                return null;
              },
            ),
            const SizedBox(height: 20),

            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: _isActive,
              onChanged: (v) => setState(() => _isActive = v),
              title: const Text('Live now'),
              subtitle: Text(
                _isActive
                    ? 'Customers can use this as soon as you save.'
                    : 'Saved but switched off. Turn it on whenever you like.',
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PreviewCard extends StatelessWidget {
  const _PreviewCard({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: scheme.secondaryContainer,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Icon(Icons.local_offer, color: scheme.onSecondaryContainer),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Customers will see',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: scheme.onSecondaryContainer,
                      ),
                ),
                const SizedBox(height: 2),
                Text(
                  text,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: scheme.onSecondaryContainer,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
