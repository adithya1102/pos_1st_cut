import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/pos_link_service.dart';

/// "Connect your POS" — mints a one-time Registration ID the owner types
/// into the Native Gusto POS at /register to link it to this outlet.
///
/// Mints a NEW code every time this screen opens (the server does this
/// unconditionally and revokes any earlier unused code for the outlet), so
/// simply navigating back in and out regenerates it — there is no separate
/// "regenerate" button to keep in sync with the countdown.
///
/// NO hardcoded code and NO test flag anywhere in this file: the code comes
/// from the server on every open, full stop.
class ConnectPosScreen extends StatefulWidget {
  const ConnectPosScreen({super.key});

  static const codeKey = Key('connect_pos_code');
  static const copyKey = Key('connect_pos_copy');
  static const countdownKey = Key('connect_pos_countdown');
  static const notApprovedKey = Key('connect_pos_not_approved');
  static const errorKey = Key('connect_pos_error');

  @override
  State<ConnectPosScreen> createState() => _ConnectPosScreenState();
}

class _ConnectPosScreenState extends State<ConnectPosScreen> {
  PosRegistrationCode? _code;
  bool _loading = true;
  bool _notApproved = false;
  String? _error;
  Timer? _ticker;
  Duration _remaining = Duration.zero;
  bool _copied = false;

  @override
  void initState() {
    super.initState();
    _mint();
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  Future<void> _mint() async {
    setState(() {
      _loading = true;
      _notApproved = false;
      _error = null;
      _code = null;
    });
    _ticker?.cancel();

    PosRegistrationCode? code;
    bool notApproved = false;
    String? err;
    try {
      code = await context.read<PosLinkService>().mintCode();
    } on NetworkException catch (e) {
      // Same three-way split used elsewhere in this app (e.g.
      // forgot_password_screen.dart): a cold Render free-tier start looks
      // identical to a dead server from here, so say so rather than
      // reporting a generic connection failure.
      err = e.timedOut
          ? 'Waking the server, this can take up to a minute. Try again.'
          : 'Could not reach the server. Check your internet connection.';
    } on ApiException catch (e) {
      if (e.statusCode == 403) {
        notApproved = true;
      } else {
        err = 'Could not generate a code (${e.statusCode}): '
            '${e.serverMessage ?? e.message}';
      }
    } catch (_) {
      err = 'Something went wrong. Please try again.';
    }

    if (!mounted) return;
    setState(() {
      _loading = false;
      _code = code;
      _notApproved = notApproved;
      _error = err;
      _copied = false;
    });
    if (code != null) _startCountdown(code.expiresAt);
  }

  void _startCountdown(DateTime expiresAt) {
    void tick() {
      final left = expiresAt.difference(DateTime.now());
      setState(() => _remaining = left.isNegative ? Duration.zero : left);
    }

    tick();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) => tick());
  }

  Future<void> _copy() async {
    final code = _code?.code;
    if (code == null) return;
    await Clipboard.setData(ClipboardData(text: code));
    if (!mounted) return;
    setState(() => _copied = true);
  }

  String _formatRemaining(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final expired = _code != null && _remaining == Duration.zero;

    return Scaffold(
      appBar: AppBar(title: const Text('Connect your POS')),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'Enter this code on your POS at Settings > Register to '
                    'link it to this restaurant.',
                    style: theme.textTheme.bodyMedium,
                  ),
                  const SizedBox(height: 28),

                  if (_loading)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 40),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else if (_notApproved)
                    Container(
                      key: ConnectPosScreen.notApprovedKey,
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: theme.colorScheme.surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Icon(Icons.hourglass_top_outlined,
                              size: 20, color: theme.colorScheme.tertiary),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              'This outlet has not been approved yet. '
                              'Registration codes are available once the '
                              'Gusto Skip team has approved your restaurant.',
                              style: theme.textTheme.bodyMedium,
                            ),
                          ),
                        ],
                      ),
                    )
                  else if (_error != null)
                    Text(
                      _error!,
                      key: ConnectPosScreen.errorKey,
                      style: TextStyle(color: theme.colorScheme.error),
                    )
                  else if (_code != null) ...[
                    Container(
                      padding: const EdgeInsets.symmetric(
                          vertical: 24, horizontal: 16),
                      decoration: BoxDecoration(
                        color: theme.colorScheme.primaryContainer,
                        borderRadius: BorderRadius.circular(14),
                      ),
                      child: Column(
                        children: [
                          SelectableText(
                            _code!.code,
                            key: ConnectPosScreen.codeKey,
                            style: theme.textTheme.displaySmall?.copyWith(
                              fontFamily: 'monospace',
                              fontWeight: FontWeight.w700,
                              letterSpacing: 2,
                              color: theme.colorScheme.onPrimaryContainer,
                            ),
                          ),
                          const SizedBox(height: 10),
                          Text(
                            expired
                                ? 'Expired — open this screen again for a new code.'
                                : 'Expires in ${_formatRemaining(_remaining)}',
                            key: ConnectPosScreen.countdownKey,
                            style: theme.textTheme.bodyMedium?.copyWith(
                              color: expired
                                  ? theme.colorScheme.error
                                  : theme.colorScheme.onPrimaryContainer,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    FilledButton.icon(
                      key: ConnectPosScreen.copyKey,
                      onPressed: expired ? null : _copy,
                      icon: Icon(_copied ? Icons.check : Icons.copy_outlined),
                      label: Text(_copied ? 'Copied' : 'Copy code'),
                    ),
                  ],

                  const SizedBox(height: 20),
                  TextButton.icon(
                    onPressed: _loading ? null : _mint,
                    icon: const Icon(Icons.refresh),
                    label: const Text('Get a new code'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
