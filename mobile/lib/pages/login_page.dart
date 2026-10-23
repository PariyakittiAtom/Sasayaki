import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../app_config.dart';
import '../theme.dart';

/// Reduces a pasted link to the bare project address, e.g. ".../rest/v1/" -> "https://abc.supabase.co".
String cleanProjectUrl(String raw) {
  var text = raw.trim();
  if (text.isEmpty) return '';
  if (!text.contains('://')) text = 'https://$text';
  final uri = Uri.tryParse(text);
  if (uri == null || uri.host.isEmpty) return text;
  return '${uri.scheme}://${uri.authority}';
}

class LoginPage extends StatefulWidget {
  const LoginPage({super.key, required this.config, required this.onConnected});

  final AppConfig config;
  final VoidCallback onConnected;

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  late final _url = TextEditingController(text: widget.config.url);
  late final _key = TextEditingController(text: widget.config.anonKey);
  late final _email = TextEditingController(text: widget.config.email);
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _url.dispose();
    _key.dispose();
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _signIn() async {
    final url = cleanProjectUrl(_url.text);
    final key = _key.text.trim();
    final email = _email.text.trim();
    if (url.isEmpty || key.isEmpty || email.isEmpty || _password.text.isEmpty) {
      setState(() => _error = 'Fill in every field.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      var initialised = true;
      try {
        Supabase.instance; // throws until Supabase.initialize has run
      } catch (_) {
        initialised = false;
      }
      if (!initialised) {
        await Supabase.initialize(url: url, publishableKey: key);
      } else if (url != widget.config.url || key != widget.config.anonKey) {
        // The client is a process-wide singleton: a different server needs a fresh start.
        await widget.config.saveConnection(url, key, email);
        setState(() => _error = 'Server settings saved. Close and reopen the app, then sign in.');
        return;
      }
      await Supabase.instance.client.auth.signInWithPassword(email: email, password: _password.text);
      await widget.config.saveConnection(url, key, email);
      widget.onConnected();
    } on AuthException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = 'Could not connect: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  bool _showServer = false; // URL + key are collapsed once they are saved

  @override
  Widget build(BuildContext context) {
    final saved = widget.config.isConfigured;
    final showServer = !saved || _showServer;
    return Scaffold(
      body: DecoratedBox(
        decoration: BoxDecoration(gradient: Palette.glow(0.7)),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: AutofillGroup(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Center(
                        child: Container(
                          width: 84,
                          height: 84,
                          decoration: BoxDecoration(
                            gradient: Palette.accentGradient,
                            borderRadius: BorderRadius.circular(26),
                            boxShadow: [BoxShadow(color: Palette.accent.withValues(alpha: 0.35), blurRadius: 28, offset: const Offset(0, 10))],
                          ),
                          alignment: Alignment.center,
                          child: const Text('囁', style: TextStyle(fontSize: 42, fontWeight: FontWeight.w600, color: Color(0xFF1A1030))),
                        ),
                      ),
                      const SizedBox(height: 22),
                      const Text('Sasayaki', textAlign: TextAlign.center, style: TextStyle(fontSize: 32, fontWeight: FontWeight.w700, letterSpacing: -0.5)),
                      const SizedBox(height: 6),
                      const Text('Your subtitled audio library', textAlign: TextAlign.center, style: TextStyle(color: Palette.muted, fontSize: 15)),
                      const SizedBox(height: 32),
                      if (showServer) ...[
                        TextField(
                          controller: _url,
                          keyboardType: TextInputType.url,
                          autocorrect: false,
                          decoration: const InputDecoration(labelText: 'Project URL', hintText: 'https://xxxx.supabase.co', prefixIcon: Icon(Icons.cloud_outlined)),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _key,
                          autocorrect: false,
                          decoration: const InputDecoration(labelText: 'Anon / publishable key', prefixIcon: Icon(Icons.vpn_key_outlined)),
                        ),
                        const SizedBox(height: 12),
                      ],
                      TextField(
                        controller: _email,
                        keyboardType: TextInputType.emailAddress,
                        autofillHints: const [AutofillHints.email],
                        autocorrect: false,
                        decoration: const InputDecoration(labelText: 'Email', prefixIcon: Icon(Icons.mail_outline)),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: _password,
                        obscureText: true,
                        autofillHints: const [AutofillHints.password],
                        onSubmitted: (_) => _signIn(),
                        decoration: const InputDecoration(labelText: 'Password', prefixIcon: Icon(Icons.lock_outline)),
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: 14),
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(color: Palette.error.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)),
                          child: Text(_error!, style: const TextStyle(color: Palette.error)),
                        ),
                      ],
                      const SizedBox(height: 22),
                      FilledButton(
                        onPressed: _busy ? null : _signIn,
                        child: _busy
                            ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2.4))
                            : const Text('Sign in'),
                      ),
                      if (saved)
                        TextButton(
                          onPressed: () => setState(() => _showServer = !_showServer),
                          child: Text(_showServer ? 'Hide server settings' : 'Server settings', style: const TextStyle(color: Palette.muted)),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
