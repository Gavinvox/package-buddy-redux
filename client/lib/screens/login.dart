import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../api.dart';
import '../state.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'settings.dart' show editServerUrl;

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _user = TextEditingController();
  final _pass = TextEditingController();
  bool _busy = false;
  String? _error;
  bool _hide = true;

  Future<void> _login() async {
    if (app.serverUrl.isEmpty) {
      setState(() => _error = 'Set the server address first.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await app.login(_user.text.trim(), _pass.text);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = 'Could not reach the server at ${app.serverUrl}.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: Column(children: [
        Container(height: MediaQuery.paddingOf(context).top + 6, color: theme.appBarTheme.backgroundColor),
        Expanded(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 400),
                child: AutofillGroup(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    const Center(child: AppLogo(size: 150)),
                    const SizedBox(height: 16),
                    const Text('Package Buddy Redux',
                        textAlign: TextAlign.center, style: TextStyle(fontSize: 34, fontWeight: FontWeight.w300)),
                    Text('Sign in to your server',
                        textAlign: TextAlign.center,
                        style: TextStyle(fontWeight: FontWeight.w300, color: theme.colorScheme.onSurface.withValues(alpha: 0.7))),
                    const SizedBox(height: 28),
                    if (!kIsWeb) ...[
                      OutlinedButton.icon(
                        onPressed: () async {
                          await editServerUrl(context);
                          setState(() {});
                        },
                        icon: const Icon(Icons.dns_outlined),
                        label: Text(app.serverUrl.isEmpty ? 'Set server address' : app.serverUrl),
                      ),
                      const SizedBox(height: 16),
                    ],
                    TextField(
                      controller: _user,
                      autofillHints: const [AutofillHints.username],
                      decoration: const InputDecoration(labelText: 'Username', prefixIcon: Icon(Icons.person_outline)),
                    ),
                    const SizedBox(height: 14),
                    TextField(
                      controller: _pass,
                      obscureText: _hide,
                      autofillHints: const [AutofillHints.password],
                      onSubmitted: (_) => _login(),
                      decoration: InputDecoration(
                        labelText: 'Password',
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                            tooltip: _hide ? 'Show password' : 'Hide password',
                            icon: Icon(_hide ? Icons.visibility : Icons.visibility_off),
                            onPressed: () => setState(() => _hide = !_hide)),
                      ),
                    ),
                    if (_error != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 12),
                        child: Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
                      ),
                    const SizedBox(height: 20),
                    FilledButton(
                      style: FilledButton.styleFrom(
                          backgroundColor: theme.brightness == Brightness.dark ? const Color(0xFF1976D2) : brandBlue,
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.all(16)),
                      onPressed: _busy ? null : _login,
                      child: _busy
                          ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.5))
                          : const Text('Sign in', style: TextStyle(fontSize: 16)),
                    ),
                    const SizedBox(height: 16),
                    Text('Ask the person who runs the server for an account.',
                        textAlign: TextAlign.center,
                        style: TextStyle(fontSize: 13, color: theme.colorScheme.onSurface.withValues(alpha: 0.6))),
                  ]),
                ),
              ),
            ),
          ),
        ),
      ]),
    );
  }
}
