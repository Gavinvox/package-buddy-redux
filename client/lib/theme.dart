// Colors, carrier bands and the light/dark themes.
import 'package:flutter/material.dart';

// Package Buddy Redux palette: blue from the logo's ribbon, warm tan from its box.
const brandBlue = Color(0xFF1565C0); // primary (light mode), light-mode app bar
const blueLight = Color(0xFF64B5F6); // primary on dark surfaces
const navyBar = Color(0xFF13294B); // dark-mode app bar
const boxTan = Color(0xFFD1A353); // secondary: the cardboard box
const tanLight = Color(0xFFFFCF87); // tab indicator / accents on blue
const tanInk = Color(0xFF3A2608); // text and icons on tan
const deliveredLight = Color(0xFF1565C0);
const deliveredDark = Color(0xFF7CC4FA);

class Band {
  const Band(this.bg, this.fg);
  final Color bg;
  final Color fg;
}

// Carrier band colors by 17TRACK carrier code. These are the carriers' public brand colors.
const Map<int, Band> _byCode = {
  100002: Band(Color(0xFF6B4521), Color(0xFFFFB500)), // UPS
  21051: Band(Color(0xFF003297), Colors.white), // USPS
  100003: Band(Color(0xFF4D148C), Colors.white), // FedEx
  100001: Band(Color(0xFFFFCC00), Color(0xFFD40511)), // DHL Express
  7047: Band(Color(0xFFFFCC00), Color(0xFFD40511)), // DHL eCommerce
  100308: Band(Color(0xFF232F3E), Color(0xFFFF9900)), // Amazon
  101392: Band(Color(0xFF232F3E), Color(0xFFFF9900)),
  11031: Band(Color(0xFFDA202A), Colors.white), // Royal Mail
  3041: Band(Color(0xFFD52B1E), Colors.white), // Canada Post
  3011: Band(Color(0xFF00753B), Colors.white), // China Post
  3013: Band(Color(0xFF0B5FA5), Color(0xFFFFC20E)), // China EMS
  190008: Band(Color(0xFF1E50A2), Colors.white), // YunExpress
  190094: Band(Color(0xFF0060B6), Colors.white), // 4PX
  190012: Band(Color(0xFFE60012), Colors.white), // Yanwen
  100012: Band(Color(0xFF222222), Color(0xFFFF3B30)), // SF Express
  190766: Band(Color(0xFF222222), Color(0xFFFF3B30)),
  10021: Band(Color(0xFFCC0000), Colors.white), // Japan Post
  11051: Band(Color(0xFFED1C24), Colors.white), // Korea Post
  11054: Band(Color(0xFFED1C24), Colors.white),
  20011: Band(Color(0xFF00843D), Colors.white), // Chunghwa Post
  20012: Band(Color(0xFF00843D), Colors.white),
};

// Fallback by name, for carriers outside the featured list.
const List<(String, Band)> _byName = [
  ('usps', Band(Color(0xFF003297), Colors.white)),
  ('ups', Band(Color(0xFF6B4521), Color(0xFFFFB500))),
  ('fedex', Band(Color(0xFF4D148C), Colors.white)),
  ('dhl', Band(Color(0xFFFFCC00), Color(0xFFD40511))),
  ('amazon', Band(Color(0xFF232F3E), Color(0xFFFF9900))),
  ('royal mail', Band(Color(0xFFDA202A), Colors.white)),
  ('parcelforce', Band(Color(0xFFDA202A), Colors.white)),
  ('canada post', Band(Color(0xFFD52B1E), Colors.white)),
  ('purolator', Band(Color(0xFFD71920), Colors.white)),
  ('australia post', Band(Color(0xFFDC1928), Colors.white)),
  ('tnt', Band(Color(0xFFFF6600), Colors.white)),
  ('dpd', Band(Color(0xFFDC0032), Colors.white)),
  ('gls', Band(Color(0xFF061AB1), Color(0xFFFFD100))),
  ('ontrac', Band(Color(0xFF0B3D91), Color(0xFFF7A800))),
  ('lasership', Band(Color(0xFFB71C1C), Colors.white)),
  ('hermes', Band(Color(0xFF0091CD), Colors.white)),
  ('evri', Band(Color(0xFF007BC4), Colors.white)),
  ('post', Band(Color(0xFF8D6E00), Colors.white)),
];

const _palette = [
  Color(0xFF00695C), Color(0xFF5D4037), Color(0xFF283593), Color(0xFF6A1B9A),
  Color(0xFF2E7D32), Color(0xFFAD1457), Color(0xFF37474F), Color(0xFF4E342E),
];

Band carrierBand(int? code, String? name) {
  final b = _byCode[code];
  if (b != null) return b;
  final n = (name ?? '').toLowerCase();
  if (n.isEmpty || n.startsWith('unknown')) return const Band(Color(0xFF5F6368), Colors.white);
  for (final (k, v) in _byName) {
    if (RegExp('\\b${RegExp.escape(k)}\\b').hasMatch(n)) return v;
  }
  return Band(_palette[n.hashCode.abs() % _palette.length], Colors.white);
}

Color stateColor(String state, Brightness b) {
  final dark = b == Brightness.dark;
  switch (state) {
    case 'delivered':
      return dark ? deliveredDark : deliveredLight;
    case 'out_for_delivery':
      return dark ? const Color(0xFFFFB74D) : const Color(0xFFE65100);
    case 'exception':
      return dark ? const Color(0xFFFF8A80) : const Color(0xFFC62828);
    case 'not_found':
    case 'expired':
    case 'carrier_unsupported':
    case 'pending':
      return dark ? const Color(0xFF9E9E9E) : const Color(0xFF757575);
    default:
      return dark ? const Color(0xFFE0E0E0) : const Color(0xFF212121);
  }
}

ThemeData buildTheme(Brightness b) {
  final dark = b == Brightness.dark;
  final scheme = ColorScheme.fromSeed(
    seedColor: brandBlue,
    brightness: b,
    primary: dark ? blueLight : brandBlue,
    onPrimary: dark ? const Color(0xFF07213F) : Colors.white,
    secondary: dark ? boxTan : const Color(0xFF8A5A12),
    onSecondary: dark ? tanInk : Colors.white,
    surface: dark ? const Color(0xFF0F131A) : const Color(0xFFF2F4F7),
  ).copyWith(
    surfaceContainerLowest: dark ? const Color(0xFF0A0D12) : Colors.white,
    surfaceContainerLow: dark ? const Color(0xFF141922) : const Color(0xFFE4E8EE),
    surfaceContainer: dark ? const Color(0xFF181E28) : const Color(0xFFEBEEF2),
    surfaceContainerHigh: dark ? const Color(0xFF1F2632) : const Color(0xFFDFE4EB),
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, brightness: b, fontFamily: 'Roboto');
  final barBg = dark ? navyBar : brandBlue;
  const barFg = Colors.white;
  return base.copyWith(
    scaffoldBackgroundColor: scheme.surface,
    appBarTheme: AppBarTheme(
      backgroundColor: barBg,
      foregroundColor: barFg,
      elevation: 2,
      scrolledUnderElevation: 2,
      titleTextStyle: const TextStyle(fontFamily: 'Roboto', fontWeight: FontWeight.w300, fontSize: 22, color: barFg),
    ),
    tabBarTheme: TabBarThemeData(
      labelColor: Colors.white,
      unselectedLabelColor: Colors.white.withValues(alpha: 0.7),
      indicatorColor: tanLight,
      indicatorSize: TabBarIndicatorSize.tab,
      dividerColor: Colors.transparent,
      labelStyle: const TextStyle(fontFamily: 'Roboto', fontWeight: FontWeight.w500, fontSize: 15),
      unselectedLabelStyle: const TextStyle(fontFamily: 'Roboto', fontWeight: FontWeight.w300, fontSize: 15),
    ),
    floatingActionButtonTheme: const FloatingActionButtonThemeData(backgroundColor: boxTan, foregroundColor: tanInk),
    dividerTheme: DividerThemeData(color: dark ? const Color(0xFF2A3342) : const Color(0xFFCDD3DB), space: 1),
    inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
    snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
    textTheme: base.textTheme.apply(fontFamily: 'Roboto'),
  );
}

// ---- formatting helpers
const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

String _hm(int h, int m) {
  final ap = h >= 12 ? 'PM' : 'AM';
  final h12 = h % 12 == 0 ? 12 : h % 12;
  return '$h12:${m.toString().padLeft(2, '0')} $ap';
}

/// Shows the wall-clock time as written by the carrier (no time-zone conversion).
String fmtWhen(String? s, {bool time = true}) {
  if (s == null || s.isEmpty) return '';
  final m = RegExp(r'^(\d{4})-(\d\d)-(\d\d)(?:[T ](\d\d):(\d\d))?').firstMatch(s);
  if (m == null) return s;
  final mon = int.parse(m[2]!);
  var out = '${_months[mon - 1]} ${int.parse(m[3]!)}, ${m[1]}';
  if (time && m[4] != null) out += ' ${_hm(int.parse(m[4]!), int.parse(m[5]!))}';
  return out;
}

String fmtDayHeader(String? s) {
  final m = RegExp(r'^(\d{4})-(\d\d)-(\d\d)').firstMatch(s ?? '');
  if (m == null) return 'Unknown date';
  final d = DateTime(int.parse(m[1]!), int.parse(m[2]!), int.parse(m[3]!));
  const wd = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  return '${wd[d.weekday - 1]}, ${_months[d.month - 1]} ${d.day}, ${d.year}';
}

String fmtTime(String? s) {
  final m = RegExp(r'[T ](\d\d):(\d\d)').firstMatch(s ?? '');
  return m == null ? '' : _hm(int.parse(m[1]!), int.parse(m[2]!));
}

/// Server timestamps (UTC) shown in the device's local time.
String fmtServerTime(String? s) {
  if (s == null) return 'never';
  var t = DateTime.tryParse(s.endsWith('Z') || s.contains('+') ? s : '${s}Z');
  if (t == null) return s;
  t = t.toLocal();
  return '${_months[t.month - 1]} ${t.day}, ${t.year} ${_hm(t.hour, t.minute)}';
}
