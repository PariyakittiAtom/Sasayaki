import 'package:flutter/material.dart';

/// Same family of colours as the desktop app, a touch deeper for OLED phones.
class Palette {
  static const bg = Color(0xFF0F0E15);
  static const panel = Color(0xFF181721);
  static const panelHi = Color(0xFF22212D);
  static const border = Color(0xFF2B2A38);
  static const text = Color(0xFFEDEBF7);
  static const muted = Color(0xFF9592AB);
  static const accent = Color(0xFFB79CFF);
  static const accentDim = Color(0xFF4A3D7A);
  static const pink = Color(0xFFFF9CC8);
  static const error = Color(0xFFFF7A8A);
  static const ok = Color(0xFF7FD8A6);

  static const accentGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFFB79CFF), Color(0xFF8A7BFF)],
  );

  /// Soft violet glow fading into the background, used behind headers and the player.
  static LinearGradient glow([double strength = 0.55]) => LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [accentDim.withValues(alpha: strength), bg],
        stops: const [0, 0.65],
      );
}

/// Keeps Japanese / Korean text on the system CJK fonts instead of a Latin-only fallback.
const cjkFallback = ['Noto Sans CJK JP', 'Noto Sans JP', 'Noto Sans CJK KR', 'Noto Sans KR', 'sans-serif'];

ThemeData buildTheme() {
  final scheme = ColorScheme.fromSeed(seedColor: Palette.accent, brightness: Brightness.dark).copyWith(
    primary: Palette.accent,
    onPrimary: const Color(0xFF1A1030),
    secondary: Palette.pink,
    surface: Palette.bg,
    onSurface: Palette.text,
    surfaceContainer: Palette.panel,
    surfaceContainerHigh: Palette.panelHi,
    outlineVariant: Palette.border,
    error: Palette.error,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, brightness: Brightness.dark);
  return base.copyWith(
    scaffoldBackgroundColor: Palette.bg,
    textTheme: base.textTheme.apply(bodyColor: Palette.text, displayColor: Palette.text, fontFamilyFallback: cjkFallback),
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
    ),
    cardTheme: CardThemeData(
      color: Palette.panel,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Palette.panel,
      contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: const BorderSide(color: Palette.accent, width: 1.4)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(52),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: Palette.panelHi,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: Palette.panel,
      surfaceTintColor: Colors.transparent,
      showDragHandle: true,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
    ),
    sliderTheme: SliderThemeData(
      trackHeight: 4,
      activeTrackColor: Palette.accent,
      inactiveTrackColor: Palette.border,
      thumbColor: Palette.accent,
      overlayColor: Palette.accent.withValues(alpha: 0.16),
      thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 7),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: Palette.panelHi,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
  );
}
