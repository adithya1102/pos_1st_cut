import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/home_state.dart';

/// Outlet hours + the "temporarily closed" toggle (migration 024).
///
/// Lives in owner_app, alongside the existing outlet controls (visibility,
/// storefront photo) that already talk to `/pos/outlet`: the OWNER sets their
/// own restaurant's hours, so this is theirs, not the platform admin's.
///
/// Two independent controls:
///   * Manual closure — takes effect immediately (like the visibility switch),
///     because "close now" is an emergency the owner should not have to Save.
///   * Opening/closing times — edited then Saved together, since a half-applied
///     schedule (new open, old close) would briefly be wrong.
class OutletSettingsScreen extends StatefulWidget {
  const OutletSettingsScreen({super.key});

  static const openTimeKey = Key('settings_open_time');
  static const closeTimeKey = Key('settings_close_time');
  static const manualToggleKey = Key('settings_manual_closed');
  static const saveHoursKey = Key('settings_save_hours');

  @override
  State<OutletSettingsScreen> createState() => _OutletSettingsScreenState();
}

class _OutletSettingsScreenState extends State<OutletSettingsScreen> {
  TimeOfDay? _open;
  TimeOfDay? _close;
  bool _initialised = false;
  bool _savingHours = false;

  static TimeOfDay? _parse(String? hhmm) {
    if (hhmm == null) return null;
    final parts = hhmm.split(':');
    if (parts.length < 2) return null;
    final h = int.tryParse(parts[0]);
    final m = int.tryParse(parts[1]);
    if (h == null || m == null || h < 0 || h > 23 || m < 0 || m > 59) {
      return null;
    }
    return TimeOfDay(hour: h, minute: m);
  }

  static String _fmt(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final outlet = context.watch<HomeState>().outlet;

    // Seed the pickers from the loaded outlet once, then let local edits stand.
    if (!_initialised && outlet != null) {
      _open = _parse(outlet.openingTime);
      _close = _parse(outlet.closingTime);
      _initialised = true;
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Hours & availability')),
      body: outlet == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(20),
              children: [
                _StatusBanner(status: outlet.orderStatus),
                const SizedBox(height: 24),

                // --- Manual closure (immediate) ---
                SwitchListTile(
                  key: OutletSettingsScreen.manualToggleKey,
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Temporarily closed'),
                  subtitle: const Text(
                    'Stop taking new orders right now, whatever the hours say. '
                    'Turn off to reopen.',
                  ),
                  value: outlet.isManuallyClosed,
                  onChanged: (v) async {
                    final ok =
                        await context.read<HomeState>().setManuallyClosed(v);
                    if (!ok) _snack('Could not update. Try again.');
                  },
                ),
                const Divider(height: 32),

                // --- Scheduled hours (edit then save) ---
                Text('Daily hours',
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 4),
                Text(
                  'Customers can\'t place orders before you open, or within the '
                  'last 30 minutes before you close.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
                _TimeRow(
                  key: OutletSettingsScreen.openTimeKey,
                  label: 'Opens',
                  value: _open,
                  onTap: () => _pick(context, isOpen: true),
                ),
                const SizedBox(height: 10),
                _TimeRow(
                  key: OutletSettingsScreen.closeTimeKey,
                  label: 'Closes',
                  value: _close,
                  onTap: () => _pick(context, isOpen: false),
                ),
                const SizedBox(height: 20),
                FilledButton.icon(
                  key: OutletSettingsScreen.saveHoursKey,
                  onPressed: _savingHours ? null : () => _saveHours(context),
                  icon: _savingHours
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.save_outlined),
                  label: const Text('Save hours'),
                ),
              ],
            ),
    );
  }

  Future<void> _pick(BuildContext context, {required bool isOpen}) async {
    final picked = await showTimePicker(
      context: context,
      initialTime: (isOpen ? _open : _close) ??
          const TimeOfDay(hour: 9, minute: 0),
    );
    if (picked == null) return;
    setState(() {
      if (isOpen) {
        _open = picked;
      } else {
        _close = picked;
      }
    });
  }

  Future<void> _saveHours(BuildContext context) async {
    setState(() => _savingHours = true);
    final err = await context.read<HomeState>().setHours(
          _open == null ? null : _fmt(_open!),
          _close == null ? null : _fmt(_close!),
        );
    if (!mounted) return;
    setState(() => _savingHours = false);
    _snack(err ?? 'Hours saved.');
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }
}

/// "You are currently: Open / Closing soon / Closed", mirroring the customer
/// view so the owner knows exactly what a customer sees.
class _StatusBanner extends StatelessWidget {
  const _StatusBanner({required this.status});
  final String status;

  @override
  Widget build(BuildContext context) {
    final (String label, Color color, IconData icon) = switch (status) {
      'closed' => ('Closed', Colors.red, Icons.block),
      'closing_soon' => ('Closing soon', Colors.orange, Icons.schedule),
      _ => ('Open', Colors.green, Icons.check_circle),
    };
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color, width: 2),
      ),
      child: Row(
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 12),
          Text('Customers see: ',
              style: Theme.of(context).textTheme.bodyMedium),
          Text(label,
              key: const Key('settings_status_label'),
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(color: color, fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

class _TimeRow extends StatelessWidget {
  const _TimeRow({super.key, required this.label, required this.value, required this.onTap});
  final String label;
  final TimeOfDay? value;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(
      onPressed: onTap,
      child: Row(
        children: [
          Text(label),
          const Spacer(),
          Text(
            value == null
                ? 'Not set'
                : value!.format(context),
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(width: 8),
          const Icon(Icons.edit, size: 18),
        ],
      ),
    );
  }
}
