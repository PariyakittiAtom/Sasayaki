import 'package:flutter/material.dart';
import 'package:just_audio_background/just_audio_background.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'app_config.dart';
import 'library_api.dart';
import 'pages/library_page.dart';
import 'pages/login_page.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await JustAudioBackground.init(
    androidNotificationChannelId: 'app.sasayaki.audio',
    androidNotificationChannelName: 'Sasayaki playback',
    androidNotificationOngoing: true,
  );
  final config = await AppConfig.load();
  if (config.isConfigured) {
    await Supabase.initialize(url: config.url, publishableKey: config.anonKey);
  }
  runApp(SasayakiApp(config: config));
}

class SasayakiApp extends StatelessWidget {
  const SasayakiApp({super.key, required this.config});

  final AppConfig config;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Sasayaki',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: _Gate(config: config),
    );
  }
}

/// Shows the library while signed in, the login screen otherwise (also after signing out).
class _Gate extends StatefulWidget {
  const _Gate({required this.config});

  final AppConfig config;

  @override
  State<_Gate> createState() => _GateState();
}

class _GateState extends State<_Gate> {
  bool _ready = false; // Supabase initialised (at startup or from the login screen)

  @override
  void initState() {
    super.initState();
    _ready = widget.config.isConfigured;
  }

  @override
  Widget build(BuildContext context) {
    if (!_ready) {
      return LoginPage(config: widget.config, onConnected: () => setState(() => _ready = true));
    }
    final auth = Supabase.instance.client.auth;
    return StreamBuilder<AuthState>(
      stream: auth.onAuthStateChange,
      builder: (context, _) {
        if (auth.currentSession == null) {
          return LoginPage(config: widget.config, onConnected: () => setState(() {}));
        }
        return LibraryPage(api: LibraryApi(Supabase.instance.client), config: widget.config);
      },
    );
  }
}
