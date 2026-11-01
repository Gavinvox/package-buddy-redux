// Settings: theme, server, account, import from the old app, export.
import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../notify.dart';
import '../platform/save_file.dart';
import '../state.dart';
import '../widgets/common.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListenableBuilder(
        listenable: app,
        builder: (context, _) => Constrained(
          child: ListView(padding: const EdgeInsets.only(bottom: 32), children: [
            const SectionHeader('Theme'),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: SegmentedButton<ThemeMode>(
                segments: const [
                  ButtonSegment(value: ThemeMode.dark, label: Text('Dark'), icon: Icon(Icons.dark_mode_outlined)),
                  ButtonSegment(value: ThemeMode.light, label: Text('Light'), icon: Icon(Icons.light_mode_outlined)),
                  ButtonSegment(value: ThemeMode.system, label: Text('System'), icon: Icon(Icons.brightness_auto_outlined)),
                ],
                selected: {app.themeMode},
                onSelectionChanged: (s) => app.setTheme(s.first),
              ),
            ),
            if (notificationsSupported) ...[
              const SectionHeader('Notifications'),
              const NotificationSettings(),
            ],
            const SectionHeader('Server'),
            ListTile(
              leading: const Icon(Icons.dns_outlined),
              title: Text(app.serverUrl.isEmpty ? 'Not set' : app.serverUrl),
              subtitle: Text(kIsWeb ? 'This web app always uses the server it was opened from' : 'Your Package Buddy Redux server'),
              trailing: kIsWeb ? null : TextButton(onPressed: () => editServerUrl(context), child: const Text('Change')),
            ),
            const SectionHeader('Account'),
            ListTile(
              leading: const Icon(Icons.person_outline),
              title: Text(app.user?.username ?? ''),
              subtitle: Text(app.user?.isAdmin ?? false ? 'Administrator' : 'User'),
            ),
            ListTile(
              leading: const Icon(Icons.password),
              title: const Text('Change password'),
              onTap: () => _changePassword(context),
            ),
            ListTile(
              leading: const Icon(Icons.logout),
              title: const Text('Log out'),
              onTap: () async {
                if (await confirm(context, 'Log out?', 'You can log in again with your username and password.', ok: 'Log out')) {
                  await app.logout();
                  if (context.mounted) Navigator.of(context).popUntil((r) => r.isFirst);
                }
              },
            ),
            const SectionHeader('Data'),
            ListTile(
              leading: const Icon(Icons.download),
              title: const Text('Export my packages'),
              subtitle: const Text('Download everything as a JSON file'),
              onTap: () => _export(context),
            ),
            Theme(
              data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                leading: const Icon(Icons.tune),
                title: const Text('Advanced'),
                children: [
                  ListTile(
                    leading: const Icon(Icons.upload_file),
                    title: const Text('Import from the old Package Buddy app'),
                    subtitle: const Text('Only if you want to bring over an old list (.ab backup, XML or database)'),
                    onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ImportScreen())),
                  ),
                ],
              ),
            ),
            const SectionHeader('About'),
            const ListTile(
              leading: AppLogo(size: 36),
              title: Text('Package Buddy Redux (self-hosted)'),
              subtitle: Text('Client 0.3.0 · tracking data from 17TRACK via your own server'),
            ),
          ]),
        ),
      ),
    );
  }

  Future<void> _export(BuildContext context) async {
    try {
      final bytes = await app.api.exportJson();
      final d = DateTime.now();
      final name = 'packagebuddy-export-${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}.json';
      final where = await saveBytes(name, bytes, 'application/json');
      if (where != null && context.mounted) toast(context, 'Saved $name to $where');
    } catch (e) {
      if (context.mounted) showError(context, e);
    }
  }

  Future<void> _changePassword(BuildContext context) async {
    final cur = TextEditingController();
    final next = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Change password'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: cur, obscureText: true, decoration: const InputDecoration(labelText: 'Current password')),
          const SizedBox(height: 12),
          TextField(
              controller: next,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'New password', helperText: 'At least 8 characters')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Change')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await app.api.changePassword(cur.text, next.text);
      if (context.mounted) toast(context, 'Password changed. Other devices were logged out.');
    } catch (e) {
      if (context.mounted) showError(context, e);
    }
  }
}

Future<void> editServerUrl(BuildContext context) async {
  final ctrl = TextEditingController(text: app.serverUrl);
  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: const Text('Server address'),
      content: TextField(
        controller: ctrl,
        autofocus: true,
        keyboardType: TextInputType.url,
        decoration: const InputDecoration(labelText: 'URL', hintText: 'http://192.168.1.50:8765'),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Save')),
      ],
    ),
  );
  if (ok == true) await app.setServerUrl(ctrl.text);
}

class ImportScreen extends StatefulWidget {
  const ImportScreen({super.key});
  @override
  State<ImportScreen> createState() => _ImportScreenState();
}

class _ImportScreenState extends State<ImportScreen> {
  String? _name;
  Uint8List? _bytes;
  Map<String, dynamic>? _preview;
  Map<String, dynamic>? _result;
  bool _trackActive = false;
  bool _busy = false;

  Future<void> _pick() async {
    final f = await FilePicker.pickFile();
    if (f == null) return;
    final bytes = await f.readAsBytes();
    setState(() {
      _name = f.name;
      _bytes = bytes;
      _preview = null;
      _result = null;
    });
    await _run(dryRun: true);
  }

  Future<void> _run({required bool dryRun}) async {
    setState(() => _busy = true);
    try {
      final r = await app.api.importFile(
          filename: _name!, bytes: _bytes!, trackActive: _trackActive, dryRun: dryRun);
      setState(() => dryRun ? _preview = r : _result = r);
      if (!dryRun) app.packagesChanged();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final p = _preview;
    final cost = (p?['would_use_quota'] ?? 0) as int;
    return Scaffold(
      appBar: AppBar(title: const Text('Import from old app')),
      body: Constrained(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          const Text(
              'Choose one of these files from the old app:\n'
              '• An Android backup (.ab), recommended. On a computer with adb, connect the phone and run\n'
              '    adb backup -f packagebuddy.ab com.psyrus.packagebuddy\n'
              '  then unlock the phone and tap "Back up my data" (leave the password empty).\n'
              '• The backup file tracking_list_bkp.xml (Settings > Account/Data > Save Data to Device), if you still have one.\n'
              '• The database file packagebuddy_db.\n\n'
              'You will see a preview first; nothing is imported until you press Import. '
              'History items are never sent to 17TRACK.'),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: _busy ? null : _pick,
            icon: const Icon(Icons.folder_open),
            label: Text(_name == null ? 'Choose backup file' : 'Chosen: $_name'),
          ),
          if (_busy) const Padding(padding: EdgeInsets.only(top: 16), child: LinearProgressIndicator()),
          if (p != null && _result == null) ...[
            SectionHeader('Preview${p['file_type'] != null ? ' · ${p['file_type']}' : ''}'),
            _stats(p, preview: true),
            const SizedBox(height: 8),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              value: _trackActive,
              onChanged: (v) => setState(() => _trackActive = v ?? false),
              title: const Text('Track active items'),
              subtitle: Text(cost == 0
                  ? 'No quota needed: active items are already tracked or there are none.'
                  : 'Registers $cost active item(s) with 17TRACK: uses up to $cost of the shared quota. '
                      'Leave unticked to just save them; you can start tracking single packages later.'),
            ),
            if ((p['unmapped_carriers'] as List?)?.isNotEmpty ?? false)
              Text('Carriers with no 17TRACK match (imported without a carrier): ${(p['unmapped_carriers'] as List).join(', ')}',
                  style: TextStyle(color: theme.colorScheme.onSurface.withValues(alpha: 0.7))),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: _busy || (p['imported'] ?? 0) == 0 ? null : () => _run(dryRun: false),
              icon: const Icon(Icons.download_done),
              label: Text((p['imported'] ?? 0) == 0
                  ? 'Nothing new to import'
                  : 'Import ${p['imported']} package(s)'),
            ),
          ],
          if (_result != null) ...[
            const SectionHeader('Done'),
            _stats(_result!, preview: false),
            if ((_result!['note'] ?? '').toString().isNotEmpty)
              Padding(padding: const EdgeInsets.only(top: 8), child: Text(_result!['note'].toString())),
            const SizedBox(height: 16),
            FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Back')),
          ],
        ]),
      ),
    );
  }

  Widget _stats(Map<String, dynamic> r, {required bool preview}) {
    final rows = <(String, Object?)>[
      ('Packages in file', r['total']),
      (preview ? 'Would import' : 'Imported', r['imported']),
      ('Already in your list (skipped)', r['skipped_duplicates']),
      ('History items (never sent to 17TRACK)', r['history']),
      ('Active items', r['active']),
      ('Already tracked on the server (free)', r['linked_free']),
      if (!preview) ('Registered with 17TRACK', r['registered']),
      if (!preview) ('Waiting for approval / queued', r['queued_or_awaiting']),
      ('Quota cost if you track active items', r['would_use_quota']),
    ];
    return Column(
        children: rows
            .map((e) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Row(children: [Expanded(child: Text(e.$1)), Text('${e.$2 ?? 0}', style: const TextStyle(fontWeight: FontWeight.w700))]),
                ))
            .toList());
  }
}

class NotificationSettings extends StatefulWidget {
  const NotificationSettings({super.key});
  @override
  State<NotificationSettings> createState() => _NotificationSettingsState();
}

class _NotificationSettingsState extends State<NotificationSettings> with WidgetsBindingObserver {
  bool enabled = true;
  int hours = kDefaultHours;
  bool permission = true;
  bool battery = true;
  bool loaded = false;
  bool checking = false;

  bool get android => defaultTargetPlatform == TargetPlatform.android;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState s) {
    if (s == AppLifecycleState.resumed) _load();
  }

  Future<void> _load() async {
    final (e, h) = await loadNotifySettings();
    final p = await permissionGranted();
    final b = await batteryUnrestricted();
    if (mounted) setState(() {
          enabled = e;
          hours = h;
          permission = p;
          battery = b;
          loaded = true;
        });
  }

  Future<void> _setEnabled(bool v) async {
    if (v && android) {
      permission = await requestPermission();
    }
    await saveNotifySettings(enabled: v);
    _load();
  }

  @override
  Widget build(BuildContext context) {
    if (!loaded) return const SizedBox(height: 56);
    final on = enabled && hours > 0;
    return Column(children: [
      SwitchListTile(
        secondary: const Icon(Icons.notifications_active_outlined),
        title: const Text('Package update notifications'),
        subtitle: Text(android
            ? 'New tracking events, status changes and deliveries'
            : 'Desktop notifications while the app is running'),
        value: enabled,
        onChanged: _setEnabled,
      ),
      ListTile(
        enabled: enabled,
        leading: const Icon(Icons.schedule),
        title: const Text('Check for updates'),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 8),
          child: SegmentedButton<int>(
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: 6, label: Text('6 h')),
              ButtonSegment(value: 12, label: Text('12 h')),
              ButtonSegment(value: 24, label: Text('24 h')),
              ButtonSegment(value: 0, label: Text('Off')),
            ],
            selected: {hours},
            onSelectionChanged: enabled
                ? (s) async {
                    await saveNotifySettings(hours: s.first);
                    _load();
                  }
                : null,
          ),
        ),
      ),
      if (on && android && !permission)
        ListTile(
          leading: const Icon(Icons.notifications_off_outlined, color: Colors.orange),
          title: const Text('Notifications are blocked'),
          subtitle: const Text('Allow notifications for Package Buddy Redux'),
          trailing: TextButton(
              onPressed: () async {
                await requestPermission();
                _load();
              },
              child: const Text('Allow')),
        ),
      if (on && android && !battery)
        ListTile(
          leading: const Icon(Icons.battery_alert_outlined, color: Colors.orange),
          title: const Text('Battery optimization is on'),
          subtitle: const Text('Android may delay or skip background checks. Set the app to "Unrestricted" so updates arrive on time.'),
          trailing: TextButton(onPressed: () async {
            await openBatterySettings();
          }, child: const Text('Fix')),
        ),
      if (on)
        ListTile(
          leading: const Icon(Icons.sync),
          title: const Text('Check now'),
          subtitle: const Text('Refresh all packages and notify about anything new'),
          trailing: checking ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) : null,
          onTap: checking
              ? null
              : () async {
                  setState(() => checking = true);
                  final n = await checkForUpdates();
                  if (mounted) setState(() => checking = false);
                  if (context.mounted) toast(context, n == 0 ? 'No new updates' : '$n package${n == 1 ? '' : 's'} updated');
                },
        ),
    ]);
  }
}
