import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/auth_state.dart';

/// Public owner self-signup. On success, shows a "pending verification" notice
/// and returns to the login screen — it does not log the user in.
class SignupScreen extends StatefulWidget {
  const SignupScreen({super.key});

  @override
  State<SignupScreen> createState() => _SignupScreenState();
}

class _SignupScreenState extends State<SignupScreen> {
  final _formKey = GlobalKey<FormState>();
  final _restaurant = TextEditingController();
  // Free-text city entry is gone: it is what let "Bangalore" and "Bengaluru"
  // both into the database. The owner now picks from the approved list, or
  // explicitly requests a new city for admin approval.
  final _newCity = TextEditingController();
  final _locality = TextEditingController();
  final _phone = TextEditingController();
  final _email = TextEditingController();

  List<String>? _cities;      // null = still loading
  String? _citiesError;
  String? _selectedCity;      // chosen from the approved list
  bool _requestingNewCity = false;
  final _upi = TextEditingController();
  final _username = TextEditingController();
  final _password = TextEditingController();
  bool _obscure = true;

  static final _vpaRe = RegExp(r'^[^@\s]+@[^@\s]+$');
  static final _emailRe = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _restaurant.dispose();
    _newCity.dispose();
    _locality.dispose();
    _phone.dispose();
    _email.dispose();
    _upi.dispose();
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    _loadCities();
  }

  Future<void> _loadCities() async {
    setState(() => _citiesError = null);
    try {
      final cities = await context.read<AuthState>().fetchCities();
      if (!mounted) return;
      setState(() {
        _cities = cities;
        // Drop a selection that is no longer approved.
        if (_selectedCity != null && !cities.contains(_selectedCity)) {
          _selectedCity = null;
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _cities = const [];
        _citiesError = 'Could not load cities.';
      });
    }
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _submitting = true;
      _error = null;
    });
    final err = await context.read<AuthState>().register(
          restaurantName: _restaurant.text,
          // Exactly one of the two, matching the server's rule.
          city: _requestingNewCity ? null : _selectedCity,
          requestedCity: _requestingNewCity ? _newCity.text : null,
          locality: _locality.text,
          phoneNumber: _phone.text,
          email: _email.text,
          username: _username.text,
          password: _password.text,
          upiId: _upi.text,
        );
    if (!mounted) return;
    setState(() => _submitting = false);
    if (err == null) {
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Registration submitted'),
          content: const Text(
            'Your restaurant is pending admin verification. Once approved, log '
            'in with your username and password to manage your menu.',
          ),
          actions: [
            FilledButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('OK'),
            ),
          ],
        ),
      );
      if (mounted) Navigator.of(context).pop();
    } else {
      setState(() => _error = err);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Register your restaurant')),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    TextFormField(
                      controller: _restaurant,
                      textCapitalization: TextCapitalization.words,
                      decoration: const InputDecoration(
                        labelText: 'Restaurant name',
                        prefixIcon: Icon(Icons.storefront_outlined),
                      ),
                      validator: (v) => (v == null || v.trim().length < 2)
                          ? 'Enter your restaurant name'
                          : null,
                    ),
                    const SizedBox(height: 16),
                    // ---- City: approved list, or an explicit request -------
                    if (_cities == null)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 20),
                        child: Center(child: CircularProgressIndicator()),
                      )
                    else if (_requestingNewCity) ...[
                      TextFormField(
                        controller: _newCity,
                        textCapitalization: TextCapitalization.words,
                        decoration: const InputDecoration(
                          labelText: 'Request a new city',
                          helperText:
                              'An admin reviews this before it becomes selectable.',
                          prefixIcon: Icon(Icons.add_location_alt_outlined),
                        ),
                        validator: (v) => (v == null || v.trim().length < 2)
                            ? 'Enter the city name'
                            : null,
                      ),
                      TextButton(
                        onPressed: () =>
                            setState(() => _requestingNewCity = false),
                        child: const Text('Pick from the list instead'),
                      ),
                    ] else ...[
                      DropdownButtonFormField<String>(
                        initialValue: _selectedCity,
                        isExpanded: true,
                        decoration: InputDecoration(
                          labelText: 'City',
                          errorText: _citiesError,
                          prefixIcon: const Icon(Icons.location_city_outlined),
                        ),
                        items: [
                          for (final city in _cities!)
                            DropdownMenuItem(value: city, child: Text(city)),
                        ],
                        onChanged: (v) => setState(() => _selectedCity = v),
                        // Required now: a free-text city is what allowed the
                        // duplicate-spelling problem this dropdown removes.
                        validator: (v) =>
                            (v == null || v.isEmpty) ? 'Select your city' : null,
                      ),
                      TextButton(
                        onPressed: () => setState(() {
                          _requestingNewCity = true;
                          _selectedCity = null;
                        }),
                        child: const Text("My city isn't listed"),
                      ),
                    ],
                    const SizedBox(height: 16),
                    // Area within the city (migration 012). REQUIRED server-side
                    // since locality became part of the (city, name, locality)
                    // duplicate check admin approval enforces — and it is what
                    // customers see under the restaurant name, so two branches
                    // of one chain stay distinguishable.
                    //
                    // Free text, not a dropdown: cities are a short curated list
                    // an admin can maintain, localities are not.
                    TextFormField(
                      controller: _locality,
                      textCapitalization: TextCapitalization.words,
                      decoration: const InputDecoration(
                        labelText: 'Area / locality',
                        helperText: 'e.g. Koramangala, HSR Layout',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.map_outlined),
                      ),
                      validator: (v) {
                        final s = (v ?? '').trim();
                        if (s.isEmpty) return 'Enter the area within your city';
                        return s.length < 2 ? 'Enter a valid area' : null;
                      },
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _phone,
                      keyboardType: TextInputType.phone,
                      decoration: const InputDecoration(
                        labelText: 'Contact phone',
                        hintText: '+91 98765 43210',
                        prefixIcon: Icon(Icons.phone_outlined),
                      ),
                      // REQUIRED as of this change, matching RegisterIn: blank
                      // is no longer accepted, and the 6-char floor mirrors the
                      // server's min_length so the error surfaces here first.
                      validator: (v) {
                        final s = (v ?? '').trim();
                        if (s.isEmpty) return 'Enter a contact phone number';
                        return s.length < 6 ? 'Enter a valid phone number' : null;
                      },
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _email,
                      autocorrect: false,
                      enableSuggestions: false,
                      keyboardType: TextInputType.emailAddress,
                      decoration: const InputDecoration(
                        labelText: 'Email',
                        helperText: 'Used to recover your account if you forget '
                            'your password.',
                        prefixIcon: Icon(Icons.email_outlined),
                      ),
                      // Required (migration 015) — forgot-password depends on
                      // it. Same shape check as the server, so the error shows
                      // here before a round trip.
                      validator: (v) {
                        final s = (v ?? '').trim();
                        if (s.isEmpty) return 'Enter your email';
                        return _emailRe.hasMatch(s)
                            ? null
                            : 'Enter a valid email address';
                      },
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _upi,
                      autocorrect: false,
                      enableSuggestions: false,
                      keyboardType: TextInputType.emailAddress,
                      decoration: const InputDecoration(
                        labelText: 'Restaurant UPI ID',
                        hintText: 'name@bank',
                        prefixIcon: Icon(Icons.account_balance_wallet_outlined),
                      ),
                      validator: (v) => (v == null || !_vpaRe.hasMatch(v.trim()))
                          ? 'Enter a valid UPI ID (e.g. name@bank)'
                          : null,
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _username,
                      autocorrect: false,
                      enableSuggestions: false,
                      decoration: const InputDecoration(
                        labelText: 'Choose a username',
                        prefixIcon: Icon(Icons.person_outline),
                      ),
                      validator: (v) => (v == null || v.trim().length < 3)
                          ? 'At least 3 characters'
                          : null,
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _password,
                      obscureText: _obscure,
                      decoration: InputDecoration(
                        labelText: 'Choose a password',
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                          icon: Icon(_obscure
                              ? Icons.visibility_outlined
                              : Icons.visibility_off_outlined),
                          onPressed: () => setState(() => _obscure = !_obscure),
                        ),
                      ),
                      validator: (v) => (v == null || v.length < 8)
                          ? 'At least 8 characters'
                          : null,
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 16),
                      Text(_error!,
                          style: TextStyle(color: Theme.of(context).colorScheme.error)),
                    ],
                    const SizedBox(height: 24),
                    FilledButton(
                      onPressed: _submitting ? null : _submit,
                      style: FilledButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                      ),
                      child: _submitting
                          ? const SizedBox(
                              height: 20, width: 20,
                              child: CircularProgressIndicator(strokeWidth: 2))
                          : const Text('Register'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
