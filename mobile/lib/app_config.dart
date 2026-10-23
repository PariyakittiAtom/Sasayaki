import 'package:shared_preferences/shared_preferences.dart';

/// Connection details and display preferences, kept on the device. The anon key is public by design;
/// the account password is never stored (Supabase keeps the session token).
class AppConfig {
  AppConfig(this._prefs);

  final SharedPreferences _prefs;

  static Future<AppConfig> load() async => AppConfig(await SharedPreferences.getInstance());

  String get url => _prefs.getString('url') ?? '';
  String get anonKey => _prefs.getString('anonKey') ?? '';
  String get email => _prefs.getString('email') ?? '';
  bool get isConfigured => url.isNotEmpty && anonKey.isNotEmpty;

  Future<void> saveConnection(String url, String anonKey, String email) async {
    await _prefs.setString('url', url);
    await _prefs.setString('anonKey', anonKey);
    await _prefs.setString('email', email);
  }

  // playback display
  String get displayMode => _prefs.getString('displayMode') ?? 'both'; // en | both | src
  double get fontSize => _prefs.getDouble('fontSize') ?? 22;
  int get offsetMs => _prefs.getInt('offsetMs') ?? 0;

  Future<void> setDisplayMode(String v) => _prefs.setString('displayMode', v);
  Future<void> setFontSize(double v) => _prefs.setDouble('fontSize', v);
  Future<void> setOffsetMs(int v) => _prefs.setInt('offsetMs', v);
}
