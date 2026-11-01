// Admin: users, 17TRACK quota, server settings and approvals.
import 'package:flutter/material.dart';

import '../models.dart';
import '../state.dart';
import '../widgets/common.dart';
import 'detail.dart' show outcomeText;

class AdminScreen extends StatelessWidget {
  const AdminScreen({super.key});
  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 3,
        child: Scaffold(
          appBar: AppBar(
            title: const Text('Admin'),
            bottom: const TabBar(tabs: [Tab(text: 'Quota'), Tab(text: 'Users'), Tab(text: 'Approvals')]),
          ),
          body: const TabBarView(children: [_QuotaTab(), _UsersTab(), _ApprovalsTab()]),
        ),
      );
}

class _QuotaTab extends StatefulWidget {
  const _QuotaTab();
  @override
  State<_QuotaTab> createState() => _QuotaTabState();
}

class _QuotaTabState extends State<_QuotaTab> {
  Map<String, dynamic>? _q;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final q = await app.api.quota();
      if (mounted) setState(() => _q = q);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _set(String key, Object value) async {
    try {
      await app.api.patchSettings({key: value});
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _pollNow() async {
    setState(() => _busy = true);
    try {
      final r = await app.api.pollNow();
      app.packagesChanged();
      if (mounted) toast(context, 'Checked ${r['refreshed'] ?? 0}, archived ${r['auto_archived'] ?? 0}, stopped ${r['stopped'] ?? 0}');
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _number(String key, String title, int current, String help) async {
    final c = TextEditingController(text: '$current');
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text(title),
        content: TextField(
            controller: c, keyboardType: TextInputType.number, decoration: InputDecoration(helperText: help)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(d, true), child: const Text('Save')),
        ],
      ),
    );
    final v = int.tryParse(c.text.trim());
    if (ok == true && v != null) await _set(key, v);
  }

  @override
  Widget build(BuildContext context) {
    final q = _q;
    if (q == null) return const Center(child: CircularProgressIndicator());
    final live = (q['seventeen_track'] as Map?)?.cast<String, dynamic>();
    final server = (q['server'] as Map).cast<String, dynamic>();
    final settings = (q['settings'] as Map).cast<String, dynamic>();
    final total = (live?['quota_total'] ?? 0) as int;
    final remain = (live?['quota_remain'] ?? 0) as int;
    final theme = Theme.of(context);
    final byUser = (server['quota_used_by_user'] as Map?)?.cast<String, dynamic>() ?? {};
    return RefreshIndicator(
      onRefresh: _load,
      child: Constrained(
        child: ListView(padding: const EdgeInsets.only(bottom: 24), children: [
          const SectionHeader('17TRACK quota'),
          if (live == null)
            Padding(padding: const EdgeInsets.all(16), child: Text('Could not read the quota: ${q['error']}'))
          else
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text('$remain', style: const TextStyle(fontSize: 56, fontWeight: FontWeight.w300, height: 1)),
                  Padding(
                    padding: const EdgeInsets.only(left: 8, bottom: 6),
                    child: Text('of $total numbers left', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w300)),
                  ),
                ]),
                const SizedBox(height: 10),
                ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                      minHeight: 10, value: total == 0 ? 0 : (total - remain) / total, color: theme.colorScheme.primary),
                ),
                const SizedBox(height: 6),
                Text('Used today: ${live['today_used'] ?? 0}. Checking numbers that are already registered is free.'),
              ]),
            ),
          const SectionHeader('This server'),
          _kv('Numbers on the server', server['shipments_total']),
          _kv('Registered with 17TRACK', server['shipments_registered']),
          _kv('Stopped (delivered and archived)', server['shipments_stopped']),
          _kv('Quota used by this server', server['quota_used_by_this_server']),
          for (final e in byUser.entries) _kv('  used by ${e.key}', e.value),
          _kv('Waiting for approval', server['packages_awaiting_approval']),
          Padding(
            padding: const EdgeInsets.all(16),
            child: OutlinedButton.icon(
                onPressed: _busy ? null : _pollNow,
                icon: const Icon(Icons.sync),
                label: const Text('Check everything now (free)')),
          ),
          const SectionHeader('Quota rules'),
          SwitchListTile(
            value: settings['require_approval'] == true,
            onChanged: (v) => _set('require_approval', v),
            title: const Text('Approve new numbers'),
            subtitle: const Text('Numbers from non-admins wait for your approval before they use quota'),
          ),
          ListTile(
            title: const Text('Monthly new numbers per user'),
            subtitle: Text(settings['monthly_new_limit'] == 0 ? 'No limit' : '${settings['monthly_new_limit']} per month'),
            trailing: const Icon(Icons.edit),
            onTap: () => _number('monthly_new_limit', 'Monthly new numbers per user',
                (settings['monthly_new_limit'] ?? 0) as int, '0 = no limit. Admins are never limited.'),
          ),
          ListTile(
            title: const Text('Move delivered packages to History after'),
            subtitle: Text('${settings['auto_archive_days']} days'),
            trailing: const Icon(Icons.edit),
            onTap: () => _number('auto_archive_days', 'Days before History', (settings['auto_archive_days'] ?? 7) as int,
                '0 = never move them automatically'),
          ),
          SwitchListTile(
            value: settings['allow_signup'] == true,
            onChanged: (v) => _set('allow_signup', v),
            title: const Text('Allow sign-up'),
            subtitle: const Text('Anyone who can reach the server can create an account'),
          ),
        ]),
      ),
    );
  }

  Widget _kv(String k, Object? v) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 3),
        child: Row(children: [Expanded(child: Text(k)), Text('${v ?? 0}', style: const TextStyle(fontWeight: FontWeight.w700))]),
      );
}

class _UsersTab extends StatefulWidget {
  const _UsersTab();
  @override
  State<_UsersTab> createState() => _UsersTabState();
}

class _UsersTabState extends State<_UsersTab> {
  List<UserInfo>? _users;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final u = await app.api.users();
      if (mounted) setState(() => _users = u);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _edit([UserInfo? u]) async {
    final name = TextEditingController(text: u?.username ?? '');
    final pass = TextEditingController();
    final limit = TextEditingController(text: u?.monthlyLimit?.toString() ?? '');
    var admin = u?.isAdmin ?? false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => StatefulBuilder(
        builder: (d, set) => AlertDialog(
          title: Text(u == null ? 'New user' : 'Edit ${u.username}'),
          content: SizedBox(
            width: 380,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              if (u == null) TextField(controller: name, decoration: const InputDecoration(labelText: 'Username')),
              const SizedBox(height: 12),
              TextField(
                  controller: pass,
                  obscureText: true,
                  decoration: InputDecoration(
                      labelText: u == null ? 'Password' : 'New password (optional)', helperText: 'At least 8 characters')),
              const SizedBox(height: 12),
              TextField(
                  controller: limit,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                      labelText: 'Monthly new numbers (optional)', helperText: 'Empty = server default, 0 = no limit')),
              CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  value: admin,
                  onChanged: (v) => set(() => admin = v ?? false),
                  title: const Text('Administrator')),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(d, true), child: const Text('Save')),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final lim = int.tryParse(limit.text.trim());
    try {
      if (u == null) {
        await app.api.createUser(name.text.trim(), pass.text, admin, lim);
      } else {
        await app.api.patchUser(u.id, {
          if (pass.text.isNotEmpty) 'password': pass.text,
          'is_admin': admin,
          if (lim != null) 'monthly_new_limit': lim else 'clear_monthly_limit': true,
        });
      }
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _delete(UserInfo u) async {
    if (!await confirm(context, 'Delete ${u.username}?', 'This deletes the account and its ${u.packageCount} package(s).',
        ok: 'Delete', danger: true)) {
      return;
    }
    try {
      await app.api.deleteUser(u.id);
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final users = _users;
    return Scaffold(
      floatingActionButton:
          FloatingActionButton.extended(onPressed: () => _edit(), icon: const Icon(Icons.person_add), label: const Text('Add user')),
      body: users == null
          ? const Center(child: CircularProgressIndicator())
          : Constrained(
              child: ListView(padding: const EdgeInsets.only(bottom: 88), children: [
                for (final u in users)
                  ListTile(
                    leading: CircleAvatar(child: Text(u.username.substring(0, 1).toUpperCase())),
                    title: Text(u.username + (u.id == app.user?.id ? ' (you)' : '')),
                    subtitle: Text('${u.isAdmin ? 'Admin · ' : ''}${u.packageCount} packages · '
                        '${u.newThisMonth} new this month${u.monthlyLimit != null ? ' (limit ${u.monthlyLimit == 0 ? 'none' : u.monthlyLimit})' : ''}'),
                    onTap: () => _edit(u),
                    trailing: u.id == app.user?.id
                        ? null
                        : IconButton(tooltip: 'Delete user', icon: const Icon(Icons.delete_outline), onPressed: () => _delete(u)),
                  ),
              ]),
            ),
    );
  }
}

class _ApprovalsTab extends StatefulWidget {
  const _ApprovalsTab();
  @override
  State<_ApprovalsTab> createState() => _ApprovalsTabState();
}

class _ApprovalsTabState extends State<_ApprovalsTab> {
  List<Pkg>? _items;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await app.api.approvals();
      if (mounted) setState(() => _items = r);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _act(Pkg p, bool approve) async {
    try {
      if (approve) {
        final o = await app.api.approve(p.id);
        if (mounted) toast(context, outcomeText(o));
      } else {
        await app.api.reject(p.id);
      }
      app.packagesChanged();
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = _items;
    if (items == null) return const Center(child: CircularProgressIndicator());
    if (items.isEmpty) {
      return const Center(child: Text('Nothing waiting for approval.', style: TextStyle(fontWeight: FontWeight.w300, fontSize: 18)));
    }
    return Constrained(
      child: ListView(children: [
        for (final p in items)
          ListTile(
            title: Text(p.description.isEmpty ? p.number : '${p.description} · ${p.number}'),
            subtitle: Text(p.carrierName),
            trailing: Row(mainAxisSize: MainAxisSize.min, children: [
              TextButton(onPressed: () => _act(p, false), child: const Text('Reject')),
              FilledButton(onPressed: () => _act(p, true), child: const Text('Approve (1 quota)')),
            ]),
          ),
      ]),
    );
  }
}
