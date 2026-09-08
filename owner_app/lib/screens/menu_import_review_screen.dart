import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../models/menu_candidate.dart';
import '../state/home_state.dart';

/// Review what OCR read off the menu photos, then approve what is right.
///
/// ## Nothing here is real yet
/// Every row is a GUESS. The parse is a line-and-regex heuristic over OCR
/// output; it mis-reads prices, splits dishes and picks up headings. So the
/// screen is built around correcting rather than confirming: both fields are
/// editable in place, everything arrives ticked (the common case is "most of
/// this is right"), and only ticked rows are ever created.
///
/// ## Candidates live only here
/// They are not persisted anywhere — not on the server, not on the device. The
/// source of truth is the photograph the owner still has, and re-running OCR
/// reproduces the list. Leaving mid-review loses the list and costs one more
/// upload, which is why the back gesture asks first.
///
/// ## Approval reuses the ordinary path
/// Each approved candidate goes through [HomeState.createDish] →
/// `POST /pos/menu-items`, exactly what the Add-dish form calls. No parallel
/// creation route exists.
class MenuImportReviewScreen extends StatefulWidget {
  const MenuImportReviewScreen({
    super.key,
    required this.result,
    required this.categoryId,
  });

  final MenuOcrResult result;

  /// Where approved dishes land. Menus always have categories — a new outlet
  /// is seeded with a default set at signup — so the picker upstream always
  /// had something to offer.
  final String categoryId;

  static const listKey = Key('review_list');
  static const approveSelectedKey = Key('review_approve_selected');
  static const rejectSelectedKey = Key('review_reject_selected');
  static const approveAllKey = Key('review_approve_all');
  static const rejectAllKey = Key('review_reject_all');
  static const emptyKey = Key('review_empty');

  static Key checkboxKey(int i) => Key('review_check_$i');
  static Key nameKey(int i) => Key('review_name_$i');
  static Key priceKey(int i) => Key('review_price_$i');

  @override
  State<MenuImportReviewScreen> createState() => _MenuImportReviewScreenState();
}

class _MenuImportReviewScreenState extends State<MenuImportReviewScreen> {
  late List<MenuCandidate> _candidates;
  final Map<int, TextEditingController> _nameControllers = {};
  final Map<int, TextEditingController> _priceControllers = {};
  bool _working = false;

  /// How many were actually written, so the closing message can be honest
  /// about a partial failure rather than claiming everything landed.
  int _created = 0;

  @override
  void initState() {
    super.initState();
    _candidates = List.of(widget.result.candidates);
    for (var i = 0; i < _candidates.length; i++) {
      _nameControllers[i] = TextEditingController(text: _candidates[i].name);
      _priceControllers[i] = TextEditingController(
        // Trailing ".0" on every price would be noise on a menu of round
        // rupee amounts, so integers are shown as integers.
        text: _formatPrice(_candidates[i].price),
      );
    }
  }

  static String _formatPrice(double v) =>
      v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toString();

  @override
  void dispose() {
    for (final c in _nameControllers.values) {
      c.dispose();
    }
    for (final c in _priceControllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  int get _selectedCount => _candidates.where((c) => c.selected).length;

  void _setAllSelected(bool value) {
    setState(() {
      _candidates = [
        for (final c in _candidates) c.copyWith(selected: value),
      ];
    });
  }

  /// Drops rows from the review list. Rejecting writes NOTHING and undoes
  /// nothing — a rejected candidate never existed as far as the menu is
  /// concerned, so this is a pure list operation.
  void _rejectSelected() {
    // BEFORE the kept list is built, not inside _replaceAll. The list below
    // captures candidate objects, so syncing afterwards would update
    // `_candidates` while `kept` still held the pre-edit copies — an in-flight
    // rename silently reverted on every reject.
    _syncFromControllers();

    final removed = _selectedCount;
    if (removed == 0) {
      _snack('Nothing is selected.');
      return;
    }
    final kept = <MenuCandidate>[];
    for (final c in _candidates) {
      if (!c.selected) kept.add(c);
    }
    _replaceAll(kept);
    _snack('Discarded $removed suggestion${removed == 1 ? '' : 's'}.');
  }

  void _rejectAll() {
    if (_candidates.isEmpty) return;
    final removed = _candidates.length;
    _replaceAll(const []);
    _snack('Discarded all $removed suggestions.');
  }

  /// Rebuilds the controller map around a new list.
  ///
  /// The controllers are keyed by INDEX, so removing a row would otherwise
  /// leave every row below it editing the text of its old neighbour.
  ///
  /// [next] must ALREADY carry any pending edits — callers sync first, because
  /// they build their list from `_candidates` and a sync in here would land
  /// after that snapshot was taken.
  void _replaceAll(List<MenuCandidate> next) {
    final rebuilt = List.of(next);
    for (final c in _nameControllers.values) {
      c.dispose();
    }
    for (final c in _priceControllers.values) {
      c.dispose();
    }
    _nameControllers.clear();
    _priceControllers.clear();
    for (var i = 0; i < rebuilt.length; i++) {
      _nameControllers[i] = TextEditingController(text: rebuilt[i].name);
      _priceControllers[i] =
          TextEditingController(text: _formatPrice(rebuilt[i].price));
    }
    setState(() => _candidates = rebuilt);
  }

  /// Pulls the edited text into the model. Called before any bulk action so
  /// an in-progress edit is never silently dropped.
  void _syncFromControllers() {
    for (var i = 0; i < _candidates.length; i++) {
      final name = _nameControllers[i]?.text ?? _candidates[i].name;
      final priceText = _priceControllers[i]?.text ?? '';
      final price = double.tryParse(priceText.trim());
      _candidates[i] = _candidates[i].copyWith(
        name: name,
        price: price ?? _candidates[i].price,
      );
    }
  }

  Future<void> _approveAll() async {
    _setAllSelected(true);
    await _approveSelected();
  }

  Future<void> _approveSelected() async {
    _syncFromControllers();

    final approved = _candidates.where((c) => c.selected).toList();
    if (approved.isEmpty) {
      _snack('Nothing is selected.');
      return;
    }

    final invalid = approved.where((c) => !c.isValid).toList();
    if (invalid.isNotEmpty) {
      // Caught here rather than by a string of failed POSTs, so the owner is
      // told which row to fix instead of watching a partial import.
      _snack('Fix ${invalid.length} row${invalid.length == 1 ? '' : 's'} first '
          '— a name is empty or a price is not a number.');
      return;
    }

    setState(() => _working = true);
    final home = context.read<HomeState>();

    final failures = <String>[];
    var created = 0;
    for (final candidate in approved) {
      final err = await home.createDish(
        name: candidate.name.trim(),
        basePrice: candidate.price,
        categoryId: widget.categoryId,
        // OCR cannot tell veg from non-veg off a photo, and guessing wrong is
        // worse than defaulting: the owner edits it on the dish afterwards.
        isVeg: true,
      );
      if (err == null) {
        created++;
      } else {
        failures.add(candidate.name);
      }
    }

    if (!mounted) return;
    _created += created;

    // Approved rows are gone from the list whether or not they were created,
    // EXCEPT the failures — those stay so they can be retried.
    final remaining = <MenuCandidate>[];
    for (final c in _candidates) {
      if (!c.selected) {
        remaining.add(c);
      } else if (failures.contains(c.name)) {
        remaining.add(c);
      }
    }
    _replaceAll(remaining);
    setState(() => _working = false);

    if (failures.isEmpty) {
      if (_candidates.isEmpty) {
        Navigator.of(context).pop(_created);
        return;
      }
      _snack('Added $created dish${created == 1 ? '' : 'es'}.');
    } else {
      _snack('Added $created, but ${failures.length} could not be saved. '
          'They are still listed — try again.');
    }
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<bool> _confirmDiscard() async {
    if (_candidates.isEmpty) return true;
    final leave = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Discard these suggestions?'),
        // Says what is actually lost. Nothing was saved, so the cost is one
        // more upload, not any real data.
        content: const Text(
          'They are not saved anywhere. You would need to photograph the menu '
          'again to get them back.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Keep reviewing'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Discard'),
          ),
        ],
      ),
    );
    return leave ?? false;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final unread = widget.result.imagesUnread;

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        // Resolved before the dialog await: a State.mounted check does not
        // vouch for a BuildContext captured from build's parameter.
        final navigator = Navigator.of(context);
        if (await _confirmDiscard()) navigator.pop(_created);
      },
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Review menu items'),
          bottom: PreferredSize(
            preferredSize: const Size.fromHeight(28),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Row(
                children: [
                  Icon(Icons.info_outline,
                      size: 15, color: theme.colorScheme.outline),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      // Stated up front, not buried: these are read off a
                      // photo and are frequently wrong.
                      'Read from your photos — check every name and price.',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.outline),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        body: Column(
          children: [
            if (unread > 0)
              Container(
                width: double.infinity,
                color: theme.colorScheme.errorContainer,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                child: Text(
                  // Explains a short list, instead of leaving the owner to
                  // wonder whether OCR ran at all.
                  '$unread of ${widget.result.imagesReceived} photos could not '
                  'be read. Anything on them is missing below.',
                  style: TextStyle(color: theme.colorScheme.onErrorContainer),
                ),
              ),
            Expanded(
              child: _candidates.isEmpty
                  ? _EmptyReview(created: _created)
                  : ListView.separated(
                      key: MenuImportReviewScreen.listKey,
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      itemCount: _candidates.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (context, i) => _CandidateRow(
                        index: i,
                        candidate: _candidates[i],
                        nameController: _nameControllers[i]!,
                        priceController: _priceControllers[i]!,
                        enabled: !_working,
                        onSelected: (v) => setState(() {
                          _candidates[i] =
                              _candidates[i].copyWith(selected: v);
                        }),
                      ),
                    ),
            ),
            _Actions(
              selectedCount: _selectedCount,
              total: _candidates.length,
              working: _working,
              onApproveSelected: _approveSelected,
              onRejectSelected: _rejectSelected,
              onApproveAll: _approveAll,
              onRejectAll: _rejectAll,
            ),
          ],
        ),
      ),
    );
  }
}

class _CandidateRow extends StatelessWidget {
  const _CandidateRow({
    required this.index,
    required this.candidate,
    required this.nameController,
    required this.priceController,
    required this.enabled,
    required this.onSelected,
  });

  final int index;
  final MenuCandidate candidate;
  final TextEditingController nameController;
  final TextEditingController priceController;
  final bool enabled;
  final ValueChanged<bool> onSelected;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Checkbox(
            key: MenuImportReviewScreen.checkboxKey(index),
            value: candidate.selected,
            onChanged: enabled ? (v) => onSelected(v ?? false) : null,
          ),
          Expanded(
            flex: 3,
            child: TextField(
              key: MenuImportReviewScreen.nameKey(index),
              controller: nameController,
              enabled: enabled,
              decoration: const InputDecoration(
                labelText: 'Dish',
                isDense: true,
                border: OutlineInputBorder(),
              ),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 110,
            child: TextField(
              key: MenuImportReviewScreen.priceKey(index),
              controller: priceController,
              enabled: enabled,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
              ],
              decoration: const InputDecoration(
                labelText: 'Price',
                prefixText: '₹',
                isDense: true,
                border: OutlineInputBorder(),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// The four bulk controls.
///
/// Approve and Reject are deliberately NOT symmetrical in weight: approving
/// writes to the live menu, rejecting only shortens a list that was never
/// saved. So approve is the filled button and reject is the quiet one.
class _Actions extends StatelessWidget {
  const _Actions({
    required this.selectedCount,
    required this.total,
    required this.working,
    required this.onApproveSelected,
    required this.onRejectSelected,
    required this.onApproveAll,
    required this.onRejectAll,
  });

  final int selectedCount;
  final int total;
  final bool working;
  final VoidCallback onApproveSelected;
  final VoidCallback onRejectSelected;
  final VoidCallback onApproveAll;
  final VoidCallback onRejectAll;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final idle = !working && total > 0;

    return Material(
      elevation: 8,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Text('$selectedCount of $total selected',
                      style: theme.textTheme.labelLarge),
                  const Spacer(),
                  if (working)
                    const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.icon(
                      key: MenuImportReviewScreen.approveSelectedKey,
                      onPressed: idle ? onApproveSelected : null,
                      icon: const Icon(Icons.check, size: 18),
                      label: const Text('Approve selected'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton.icon(
                      key: MenuImportReviewScreen.rejectSelectedKey,
                      onPressed: idle ? onRejectSelected : null,
                      icon: const Icon(Icons.close, size: 18),
                      label: const Text('Reject selected'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Row(
                children: [
                  Expanded(
                    child: TextButton(
                      key: MenuImportReviewScreen.approveAllKey,
                      onPressed: idle ? onApproveAll : null,
                      child: const Text('Approve all'),
                    ),
                  ),
                  Expanded(
                    child: TextButton(
                      key: MenuImportReviewScreen.rejectAllKey,
                      onPressed: idle ? onRejectAll : null,
                      child: const Text('Reject all'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EmptyReview extends StatelessWidget {
  const _EmptyReview({required this.created});

  final int created;

  @override
  Widget build(BuildContext context) {
    return Center(
      key: MenuImportReviewScreen.emptyKey,
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.done_all, size: 40),
            const SizedBox(height: 12),
            Text(
              created > 0
                  ? 'Added $created dish${created == 1 ? '' : 'es'}. '
                      'Nothing left to review.'
                  : 'No suggestions left. Go back and try clearer photos.',
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}
