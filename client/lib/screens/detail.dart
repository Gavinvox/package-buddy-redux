// Package details: summary grid, notes, actions and the event timeline.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models.dart';
import '../state.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/package_row.dart';

class DetailScreen extends StatelessWidget {
  const DetailScreen({super.key, required this.packageId});
  final int packageId;
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Package details')),
        body: DetailView(packageId: packageId, onDeleted: () => Navigator.pop(context)),
      );
}

class DetailView extends StatefulWidget {
  const DetailView({super.key, required this.packageId, this.embedded = false, this.onDeleted});
  final int packageId;
  final bool embedded;
  final VoidCallback? onDeleted;
  @override
  State<DetailView> createState() => _DetailViewState();
}

class _DetailViewState extends State<DetailView> {
  Pkg? _p;
  Object? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final p = await app.api.package(widget.packageId);
      if (mounted) setState(() => _p = p);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e);
      showError(context, e);
    }
  }

  Future<void> _run(Future<void> Function() f) async {
    setState(() => _busy = true);
    try {
      await f();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _refresh() => _run(() async {
        final p = await app.api.refreshPackage(_p!.id);
        setState(() => _p = p);
        app.packagesChanged();
      });

  Future<void> _archive(bool archived) => _run(() async {
        final p = await app.api.updatePackage(_p!.id, {'archived': archived});
        setState(() => _p = p);
        app.packagesChanged();
        if (mounted) toast(context, archived ? 'Moved to History' : 'Restored to the active list');
      });

  Future<void> _delete() async {
    final ok = await confirm(context, 'Delete package?',
        'Remove ${_p!.description.isEmpty ? _p!.number : '"${_p!.description}"'} from your list? This cannot be undone.',
        ok: 'Delete', danger: true);
    if (!ok) return;
    await _run(() async {
      await app.api.deletePackage(_p!.id);
      app.packagesChanged();
      if (mounted) toast(context, 'Package deleted');
      widget.onDeleted?.call();
    });
  }

  Future<void> _track() async {
    final ok = await confirm(
        context,
        'Start tracking?',
        'If nobody on this server tracks this number yet, it is registered with 17TRACK and uses 1 of the shared quota. '
            'Numbers already on the account are free.',
        ok: 'Start tracking');
    if (!ok) return;
    await _run(() async {
      final (p, outcome) = await app.api.startTracking(_p!.id);
      setState(() => _p = p);
      app.packagesChanged();
      if (mounted) toast(context, outcomeText(outcome));
    });
  }

  Future<void> _edit() async {
    final p = _p!;
    final ctrl = TextEditingController(text: p.description);
    var dir = p.direction;
    final r = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => AlertDialog(
          title: const Text('Edit package'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: ctrl, autofocus: true, decoration: const InputDecoration(labelText: 'Description')),
            const SizedBox(height: 16),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'receiving', label: Text('Receiving'), icon: Icon(Icons.arrow_back)),
                ButtonSegment(value: 'sending', label: Text('Sending'), icon: Icon(Icons.arrow_forward)),
              ],
              selected: {dir},
              onSelectionChanged: (s) => set(() => dir = s.first),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Save')),
          ],
        ),
      ),
    );
    if (r != true) return;
    await _run(() async {
      final np = await app.api.updatePackage(p.id, {'description': ctrl.text.trim(), 'direction': dir});
      setState(() => _p = np);
      app.packagesChanged();
    });
  }

  @override
  Widget build(BuildContext context) {
    final p = _p;
    if (p == null) {
      return Center(
          child: _error == null
              ? const CircularProgressIndicator()
              : TextButton(onPressed: _load, child: const Text('Could not load. Try again')));
    }
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.only(bottom: 32),
        children: [
          if (_busy) const LinearProgressIndicator(minHeight: 3) else const SizedBox(height: 3),
          CarrierBand(pkg: p, height: 40, big: true),
          _headerNumber(p),
          if (p.unsupported || p.carrierLimited || (p.note ?? '').isNotEmpty) _noteCard(p),
          _actions(p),
          LayoutBuilder(builder: (context, c) => _summary(p, c.maxWidth >= 640)),
          _Timeline(pkg: p),
        ],
      ),
    );
  }

  Widget _headerNumber(Pkg p) {
    final theme = Theme.of(context);
    return Container(
      color: theme.colorScheme.surfaceContainerHigh,
      padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (p.description.isNotEmpty)
              Text(p.description, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
            SelectableText(p.number,
                style: TextStyle(
                    fontSize: p.description.isEmpty ? 22 : 16,
                    fontWeight: p.description.isEmpty ? FontWeight.w700 : FontWeight.w400,
                    letterSpacing: 0.5)),
          ]),
        ),
        IconButton(
            tooltip: 'Copy tracking number',
            icon: const Icon(Icons.copy),
            onPressed: () {
              Clipboard.setData(ClipboardData(text: p.number));
              toast(context, 'Tracking number copied');
            }),
      ]),
    );
  }

  Widget _noteCard(Pkg p) {
    final theme = Theme.of(context);
    final dark = theme.brightness == Brightness.dark;
    final String title;
    final String body;
    if (p.unsupported) {
      title = 'Carrier not available via 17TRACK';
      body = (p.note?.isNotEmpty ?? false)
          ? p.note!
          : '17TRACK does not provide tracking for this carrier right now. Use the carrier\'s own site.';
    } else if (p.carrierLimited) {
      title = 'Limited tracking for this carrier';
      body = p.note ?? '17TRACK has limited or no data for this carrier. The server keeps trying.';
    } else {
      title = 'Note';
      body = p.note!;
    }
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 0),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: dark ? const Color(0xFF3A3017) : const Color(0xFFFFF4D6),
        border: Border.all(color: dark ? const Color(0xFF8D7330) : const Color(0xFFE0B54A)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(Icons.info_outline, color: dark ? const Color(0xFFFFD27A) : const Color(0xFF8A5A00)),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
            const SizedBox(height: 4),
            Text(body),
            const SizedBox(height: 8),
            OutlinedButton.icon(
                onPressed: () => openUrl(context, p.siteUrl),
                icon: const Icon(Icons.open_in_new, size: 18),
                label: const Text('Open on carrier site')),
          ]),
        ),
      ]),
    );
  }

  Widget _actions(Pkg p) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
      child: Wrap(spacing: 8, runSpacing: 8, children: [
        FilledButton.icon(
            onPressed: () => openUrl(context, p.siteUrl),
            icon: const Icon(Icons.open_in_new, size: 18),
            label: const Text('Open on carrier site')),
        if (p.mode == 'tracked')
          OutlinedButton.icon(
              onPressed: _busy ? null : _refresh, icon: const Icon(Icons.sync, size: 18), label: const Text('Refresh')),
        if (p.mode == 'not_tracked' || p.mode == 'rejected')
          OutlinedButton.icon(
              onPressed: _busy ? null : _track,
              icon: const Icon(Icons.play_arrow, size: 18),
              label: const Text('Start tracking')),
        OutlinedButton.icon(onPressed: _busy ? null : _edit, icon: const Icon(Icons.edit, size: 18), label: const Text('Edit')),
        OutlinedButton.icon(
            onPressed: _busy ? null : () => _archive(!p.archived),
            icon: Icon(p.archived ? Icons.unarchive_outlined : Icons.archive_outlined, size: 18),
            label: Text(p.archived ? 'Restore' : 'Archive')),
        OutlinedButton.icon(
          onPressed: _busy ? null : _delete,
          style: OutlinedButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
          icon: const Icon(Icons.delete_outline, size: 18),
          label: const Text('Delete'),
        ),
      ]),
    );
  }

  Widget _summary(Pkg p, bool wide) {
    final b = Theme.of(context).brightness;
    final rows = <(String, String, Color?)>[
      ('Carrier', p.carrierName, null),
      ('Status', p.stateLabel, stateColor(p.state, b)),
      if ((p.statusText ?? '').isNotEmpty) ('Latest', p.statusText!, null),
      if ((p.lastLocation ?? '').isNotEmpty) ('Location', p.lastLocation!, null),
      if ((p.lastEventTime ?? '').isNotEmpty) ('Last update', fmtWhen(p.lastEventTime), null),
      if ((p.eta ?? '').isNotEmpty) ('Estimated delivery', fmtWhen(p.eta, time: false), null),
      if ((p.deliveredAt ?? '').isNotEmpty) ('Delivered', fmtWhen(p.deliveredAt), stateColor('delivered', b)),
      if (p.days != null) ('Days in transit', '${p.days}', null),
      ('Direction', p.sending ? 'Sending' : 'Receiving', null),
      ('Tracking', _modeText(p.mode), null),
      ('Checked by server', fmtServerTime(p.lastChecked), null),
      if (p.source.startsWith('import')) ('Added from', _sourceText(p.source), null),
    ];
    final theme = Theme.of(context);
    final label = TextStyle(color: theme.colorScheme.onSurface.withValues(alpha: 0.7), fontFamily: 'RobotoCondensed');
    Widget cell((String, String, Color?) r) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: 140, child: Text(r.$1, style: label)),
            Expanded(
                child: Text(r.$2,
                    textAlign: TextAlign.right,
                    style: TextStyle(fontWeight: FontWeight.w500, color: r.$3 ?? theme.colorScheme.primary))),
          ]),
        );
    final half = (rows.length / 2).ceil();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const SectionHeader('Package summary'),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: wide
            ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(child: Column(children: rows.take(half).map(cell).toList())),
                const SizedBox(width: 32),
                Expanded(child: Column(children: rows.skip(half).map(cell).toList())),
              ])
            : Column(children: rows.map(cell).toList()),
      ),
    ]);
  }

  String _modeText(String m) => switch (m) {
        'tracked' => 'Tracked by the server',
        'not_tracked' => 'Saved only (not tracked)',
        'awaiting_approval' => 'Waiting for admin approval',
        'rejected' => 'Not approved',
        _ => m,
      };

  String _sourceText(String s) => switch (s) {
        'import_xml' => 'Old app backup file',
        'import_db' => 'Old app database',
        'mira' || 'api' => 'API',
        _ => s,
      };
}

String outcomeText(String outcome) => switch (outcome) {
      'shared' => 'Tracking (already on the server, no quota used)',
      'already_registered' => 'Tracking (already on the 17TRACK account, no quota used)',
      'registered' => 'Tracking started (used 1 quota)',
      'awaiting_approval' => 'Saved. Waiting for admin approval before tracking',
      'limit_reached' => 'Saved, but your monthly limit of new numbers is reached',
      'unsupported' => 'Saved. 17TRACK does not support this carrier right now',
      'rejected' => 'Saved. 17TRACK rejected this number',
      'registration_disabled' => 'Saved. New registrations are switched off on this server',
      'queued' => 'Saved. It will be registered on the next check',
      'saved' => 'Saved (not tracked)',
      'error' => 'Saved, but 17TRACK returned an error. The server will retry',
      _ => outcome,
    };

class _Timeline extends StatelessWidget {
  const _Timeline({required this.pkg});
  final Pkg pkg;
  @override
  Widget build(BuildContext context) {
    final events = pkg.events ?? const <TrackEvent>[];
    final theme = Theme.of(context);
    final dark = theme.brightness == Brightness.dark;
    final children = <Widget>[const SectionHeader('Tracking history')];
    if (events.isEmpty) {
      children.add(Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
            pkg.mode == 'tracked'
                ? 'No events yet. The server checks every package regularly; pull down to check now.'
                : 'No events. This package is not being tracked.',
            style: TextStyle(color: theme.colorScheme.onSurface.withValues(alpha: 0.7))),
      ));
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children);
    }
    String? day;
    for (var i = 0; i < events.length; i++) {
      final e = events[i];
      final d = (e.time ?? '').length >= 10 ? e.time!.substring(0, 10) : '';
      if (d != day) {
        day = d;
        children.add(Container(
          margin: const EdgeInsets.only(top: 6),
          color: dark ? const Color(0xFF1B3358) : const Color(0xFF2F6DB5),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
          child: Text(fmtDayHeader(e.time),
              style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w300)),
        ));
      }
      final first = i == 0;
      final dotColor = first ? stateColor(pkg.state == 'in_transit' ? 'delivered' : pkg.state, theme.brightness) : theme.dividerColor;
      children.add(IntrinsicHeight(
        child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SizedBox(
            width: 84,
            child: Padding(
              padding: const EdgeInsets.only(left: 14, top: 10),
              child: Text(fmtTime(e.time),
                  style: TextStyle(fontFamily: 'RobotoCondensed', color: theme.colorScheme.onSurface.withValues(alpha: 0.8))),
            ),
          ),
          SizedBox(
            width: 24,
            child: Column(children: [
              Container(width: 2, height: 12, color: i == 0 ? Colors.transparent : theme.dividerColor),
              Container(
                  width: 12,
                  height: 12,
                  decoration: BoxDecoration(color: dotColor, shape: BoxShape.circle)),
              Expanded(child: Container(width: 2, color: i == events.length - 1 ? Colors.transparent : theme.dividerColor)),
            ]),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 8, 14, 10),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(e.description,
                    style: TextStyle(fontSize: 15.5, fontWeight: first ? FontWeight.w700 : FontWeight.w400)),
                if ((e.location ?? '').isNotEmpty)
                  Text(e.location!.toUpperCase(),
                      style: TextStyle(
                          fontFamily: 'RobotoCondensed',
                          fontSize: 12.5,
                          color: theme.colorScheme.onSurface.withValues(alpha: 0.65))),
              ]),
            ),
          ),
        ]),
      ));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children);
  }
}
