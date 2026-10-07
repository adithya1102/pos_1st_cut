import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../models/category.dart';
import '../models/menu_item.dart';
import '../services/cloudinary_service.dart';
import '../state/home_state.dart';

/// Add (item == null) or edit (item != null) a dish.
class DishEditScreen extends StatefulWidget {
  final MenuItem? item;
  const DishEditScreen({super.key, this.item});

  bool get isEdit => item != null;

  @override
  State<DishEditScreen> createState() => _DishEditScreenState();
}

class _DishEditScreenState extends State<DishEditScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _price;
  late final TextEditingController _prep;

  final _cloudinary = CloudinaryService();

  String? _categoryId;
  bool _isVeg = true;
  String? _imageUrl;
  bool _uploading = false;
  bool _saving = false;
  List<Category> _categories = const [];
  bool _loadingCategories = true;
  String? _error;

  /// Limited quantity (migration 033). Separate from the form's other fields
  /// because it is written by its own endpoint rather than by _save — stock is
  /// a live number the kitchen changes during service, not an attribute of the
  /// dish, and bundling it into Save would make an unrelated edit (a price
  /// typo, say) silently reset the count.
  late final TextEditingController _stock;
  bool _stockTracked = false;
  bool _savingStock = false;

  @override
  void initState() {
    super.initState();
    final it = widget.item;
    _name = TextEditingController(text: it?.name ?? '');
    _price = TextEditingController(
      text: it != null ? it.basePrice.toStringAsFixed(0) : '',
    );
    _prep = TextEditingController(text: it?.prepTimeMinutes?.toString() ?? '');
    _isVeg = it?.isVeg ?? true;
    _imageUrl = it?.imageUrl;
    _categoryId = it?.categoryId;
    _stockTracked = it?.isStockTracked ?? false;
    _stock = TextEditingController(text: it?.stockRemaining?.toString() ?? '');
    _loadCategories();
  }

  /// Turning the switch ON does NOT write anything yet — it reveals the field
  /// so the owner can type a number and press Update. Turning it OFF writes
  /// immediately, because "unlimited" needs no number and making them press
  /// Update to un-limit a dish would be a pointless second tap.
  Future<void> _onStockToggled(BuildContext context, bool on) async {
    if (on) {
      setState(() => _stockTracked = true);
      return;
    }
    setState(() => _savingStock = true);
    final ok = await context.read<HomeState>().setItemStock(widget.item!.id, null);
    if (!mounted) return;
    setState(() {
      _savingStock = false;
      if (ok) {
        _stockTracked = false;
        _stock.clear();
      }
    });
    if (!ok && context.mounted) {
      _showStockError(context);
    }
  }

  Future<void> _saveStock(BuildContext context) async {
    final raw = _stock.text.trim();
    final qty = int.tryParse(raw);
    if (qty == null || qty < 0) {
      setState(() => _error = 'Enter a whole number of portions (0 or more).');
      return;
    }
    setState(() => _savingStock = true);
    final ok = await context.read<HomeState>().setItemStock(widget.item!.id, qty);
    if (!mounted) return;
    setState(() => _savingStock = false);
    if (!context.mounted) return;
    if (ok) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(qty == 0
            // Said plainly: 0 does not just stop orders, it takes the dish off
            // the customer's menu, and an owner needs to know that before they
            // wonder why it vanished.
            ? 'Marked sold out — customers can no longer see it.'
            : '$qty left today.'),
      ));
    } else {
      _showStockError(context);
    }
  }

  void _showStockError(BuildContext context) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Could not update the quantity.')),
    );
  }

  Future<void> _loadCategories() async {
    try {
      final cats = await context.read<HomeState>().ensureCategories();
      if (!mounted) return;
      setState(() {
        _categories = cats;
        // Default the picker to the item's category, else the first available.
        _categoryId ??= cats.isNotEmpty ? cats.first.id : null;
        _loadingCategories = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loadingCategories = false;
        _error = 'Could not load categories.';
      });
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _price.dispose();
    _prep.dispose();
    _stock.dispose();
    super.dispose();
  }

  Future<void> _pickImage() async {
    if (!_cloudinary.configured) {
      _snack('Image upload is not configured.');
      return;
    }
    final XFile? picked = await ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1600,
      imageQuality: 85,
    );
    if (picked == null) return;
    setState(() => _uploading = true);
    try {
      final url = await _cloudinary.uploadImage(picked.path);
      if (!mounted) return;
      setState(() => _imageUrl = url);
    } catch (_) {
      if (mounted) _snack('Image upload failed.');
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (_categoryId == null) {
      _snack('Pick a category first.');
      return;
    }
    setState(() => _saving = true);
    final home = context.read<HomeState>();
    final name = _name.text.trim();
    final price = double.parse(_price.text.trim());
    final prep = _prep.text.trim().isEmpty ? null : int.tryParse(_prep.text.trim());

    final String? err;
    if (widget.isEdit) {
      err = await home.updateDish(
        widget.item!.id,
        name: name,
        basePrice: price,
        categoryId: _categoryId,
        isVeg: _isVeg,
        prepTimeMinutes: prep,
        imageUrl: _imageUrl,
      );
    } else {
      err = await home.createDish(
        name: name,
        basePrice: price,
        categoryId: _categoryId!,
        isVeg: _isVeg,
        prepTimeMinutes: prep,
        imageUrl: _imageUrl,
      );
    }
    if (!mounted) return;
    setState(() => _saving = false);
    if (err == null) {
      Navigator.of(context).pop(true);
    } else {
      _snack(err);
    }
  }

  Future<void> _delete() async {
    final home = context.read<HomeState>();  // capture before the dialog await
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Delete dish?'),
        content: Text('"${widget.item!.name}" will be removed from the menu.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _saving = true);
    final err = await home.deleteDish(widget.item!.id);
    if (!mounted) return;
    setState(() => _saving = false);
    if (err == null) {
      Navigator.of(context).pop(true);
    } else {
      _snack(err);
    }
  }

  void _snack(String msg) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.isEdit ? 'Edit dish' : 'Add dish'),
        actions: [
          if (widget.isEdit)
            IconButton(
              tooltip: 'Delete',
              icon: const Icon(Icons.delete_outline),
              onPressed: _saving ? null : _delete,
            ),
        ],
      ),
      body: _loadingCategories
          ? const Center(child: CircularProgressIndicator())
          : Form(
              key: _formKey,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text(_error!, style: const TextStyle(color: Colors.red)),
                    ),
                  _imagePicker(),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _name,
                    decoration: const InputDecoration(labelText: 'Dish name'),
                    textCapitalization: TextCapitalization.words,
                    validator: (v) =>
                        (v == null || v.trim().isEmpty) ? 'Enter a name' : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _price,
                    decoration: const InputDecoration(labelText: 'Price (₹)', prefixText: '₹ '),
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    validator: (v) {
                      final d = double.tryParse((v ?? '').trim());
                      if (d == null || d < 0) return 'Enter a valid price';
                      return null;
                    },
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: _categoryId,
                    decoration: const InputDecoration(labelText: 'Category'),
                    items: _categories
                        .map((c) => DropdownMenuItem(value: c.id, child: Text(c.name)))
                        .toList(),
                    onChanged: (v) => setState(() => _categoryId = v),
                    validator: (v) => v == null ? 'Pick a category' : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _prep,
                    decoration: const InputDecoration(
                      labelText: 'Prep time (minutes, optional)',
                    ),
                    keyboardType: TextInputType.number,
                  ),
                  const SizedBox(height: 8),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Vegetarian'),
                    subtitle: Text(_isVeg ? 'Veg' : 'Non-veg'),
                    value: _isVeg,
                    onChanged: (v) => setState(() => _isVeg = v),
                  ),

                  // LIMITED QUANTITY (migration 033). Edit-only: stock is set
                  // against an existing dish through its own endpoint, not
                  // carried in the create payload. Offering it on the add form
                  // would imply the number is saved with the dish, and it is
                  // not — a separate call writes it, and that call needs the
                  // id this form does not have yet.
                  if (widget.isEdit) ...[
                    SwitchListTile(
                      key: const Key('dish_limited_quantity_toggle'),
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Limited quantity today'),
                      subtitle: Text(
                        _stockTracked
                            ? 'Customers cannot order more than the number below.'
                            : 'Off — unlimited, as usual.',
                      ),
                      value: _stockTracked,
                      onChanged: _savingStock
                          ? null
                          : (v) => _onStockToggled(context, v),
                    ),
                    if (_stockTracked)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Row(
                          children: [
                            Expanded(
                              child: TextFormField(
                                key: const Key('dish_stock_field'),
                                controller: _stock,
                                decoration: const InputDecoration(
                                  labelText: 'Remaining today',
                                  // Named "remaining", not "quantity": this is
                                  // the LIVE count and it goes down as orders
                                  // land. An owner who reads it as "how many I
                                  // started with" would re-type the original
                                  // number and silently restock.
                                  helperText:
                                      'Live count — drops as orders come in.',
                                ),
                                keyboardType: TextInputType.number,
                              ),
                            ),
                            const SizedBox(width: 12),
                            FilledButton(
                              key: const Key('dish_stock_save'),
                              onPressed: _savingStock
                                  ? null
                                  : () => _saveStock(context),
                              child: _savingStock
                                  ? const SizedBox(
                                      height: 18, width: 18,
                                      child: CircularProgressIndicator(
                                          strokeWidth: 2))
                                  : const Text('Update'),
                            ),
                          ],
                        ),
                      ),
                  ],

                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: _saving ? null : _save,
                    child: _saving
                        ? const SizedBox(
                            height: 20, width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : Text(widget.isEdit ? 'Save changes' : 'Add dish'),
                  ),
                ],
              ),
            ),
    );
  }

  Widget _imagePicker() {
    return Row(
      children: [
        Container(
          width: 88,
          height: 88,
          decoration: BoxDecoration(
            color: Colors.grey.shade200,
            borderRadius: BorderRadius.circular(12),
            image: _imageUrl != null
                ? DecorationImage(image: NetworkImage(_imageUrl!), fit: BoxFit.cover)
                : null,
          ),
          child: _imageUrl == null
              ? const Icon(Icons.restaurant, color: Colors.grey)
              : null,
        ),
        const SizedBox(width: 16),
        Expanded(
          child: OutlinedButton.icon(
            onPressed: _uploading ? null : _pickImage,
            icon: _uploading
                ? const SizedBox(
                    height: 16, width: 16, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.image_outlined),
            label: Text(_uploading
                ? 'Uploading…'
                : (_imageUrl == null ? 'Add photo' : 'Change photo')),
          ),
        ),
      ],
    );
  }
}
