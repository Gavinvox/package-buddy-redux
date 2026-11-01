// Main screen: three swipeable tabs; on wide screens the details open on the right.
import 'dart:async';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import '../models.dart';
import '../state.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/package_row.dart';
import 'add.dart';
import 'admin.dart';
import 'detail.dart';
import 'settings.dart';

const wideBreakpoint = 900.0;

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, this.initialTab = 0});
  final int initialTab;
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int? _selected; // selected package (wide layout)
  bool _refreshing = false;

  Future<void> _add() async {
    final created = await Navigator.push<Pkg>(context, MaterialPageRoute(builder: (_) => const AddScreen()));
    if (created != null && mounted && MediaQuery.sizeOf(context).width >= wideBreakpoint) {
      setState(() => _selected = created.id);
    }
  }

  Future<void> _refreshAll() async {
    setState(() => _refreshing = true);
    try {
      final r = await app.api.refreshAll();
      final n = (r['refreshed'] ?? 0) as int;
      final recent = (r['skipped_recent'] ?? 0) as int;
      if (mounted) toast(context, n == 0 && recent > 0 ? 'Everything was checked less than a minute ago' : 'Checked $n package(s) with 17TRACK');
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      app.packagesChanged();
      if (mounted) setState(() => _refreshing = false);
    }
  }

  void _open(Pkg p) {
    if (MediaQuery.sizeOf(context).width >= wideBreakpoint) {
      setState(() => _selected = p.id);
    } else {
      Navigator.push(context, MaterialPageRoute(builder: (_) => DetailScreen(packageId: p.id)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= wideBreakpoint;
    final lists = TabBarView(children: [
      PackageList(view: 'active', direction: 'receiving', selected: wide ? _selected : null, onOpen: _open),
      PackageList(view: 'active', direction: 'sending', selected: wide ? _selected : null, onOpen: _open),
      PackageList(view: 'history', selected: wide ? _selected : null, onOpen: _open),
    ]);
    return DefaultTabController(
      length: 3,
      initialIndex: widget.initialTab,
      child: Scaffold(
        appBar: AppBar(
          titleSpacing: 12,
          title: const Row(children: [
            AppLogo(size: 40),
            SizedBox(width: 10),
            Flexible(
              child: FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Package Buddy', style: TextStyle(fontSize: 21, height: 1.1)),
                  Text('Redux',
                      style: TextStyle(fontSize: 14, height: 1.1, fontStyle: FontStyle.italic, fontWeight: FontWeight.w500, color: tanLight)),
                ]),
              ),
            ),
          ]),
          actions: [
            IconButton(tooltip: 'Add package', icon: const Icon(Icons.add, size: 30), onPressed: _add),
            IconButton(
              tooltip: 'Check all with 17TRACK now',
              icon: _refreshing
                  ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white))
                  : const Icon(Icons.sync),
              onPressed: _refreshing ? null : _refreshAll,
            ),
            if (app.user?.isAdmin ?? false)
              IconButton(
                  tooltip: 'Admin: users and quota',
                  icon: const Icon(Icons.admin_panel_settings_outlined),
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const AdminScreen()))),
            IconButton(
                tooltip: 'Settings',
                icon: const Icon(Icons.settings_outlined),
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SettingsScreen()))),
            const SizedBox(width: 4),
          ],
          bottom: const TabBar(tabs: [
            Tab(text: 'Receiving'),
            Tab(text: 'Sending'),
            Tab(text: 'History'),
          ]),
        ),
        body: wide
            ? Row(children: [
                SizedBox(width: 440, child: lists),
                VerticalDivider(width: 3, thickness: 3, color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.7)),
                Expanded(
                  child: _selected == null
                      ? const _NoSelection()
                      : DetailView(
                          key: ValueKey(_selected),
                          packageId: _selected!,
                          embedded: true,
                          onDeleted: () => setState(() => _selected = null)),
                ),
              ])
            : lists,
        floatingActionButton: wide
            ? null
            : FloatingActionButton(tooltip: 'Add package', onPressed: _add, child: const Icon(Icons.add)),
      ),
    );
  }
}

class _NoSelection extends StatelessWidget {
  const _NoSelection();
  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurface.withValues(alpha: 0.6);
    return Center(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.inventory_2_outlined, size: 72, color: muted),
        const SizedBox(height: 12),
        Text('No package selected.', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w300, color: muted)),
        const SizedBox(height: 6),
        Text('Pick a package on the left.', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w300, color: muted)),
      ]),
    );
  }
}

/// Lets a mouse drag the list too, so pull-to-refresh works on desktop and the web.
class _DragAll extends MaterialScrollBehavior {
  const _DragAll();
  @override
  Set<PointerDeviceKind> get dragDevices =>
      {PointerDeviceKind.touch, PointerDeviceKind.mouse, PointerDeviceKind.trackpad, PointerDeviceKind.stylus};
}

class PackageList extends StatefulWidget {
  const PackageList({super.key, required this.view, this.direction, required this.onOpen, this.selected});
  final String view;
  final String? direction;
  final void Function(Pkg) onOpen;
  final int? selected;
  @override
  State<PackageList> createState() => _PackageListState();
}

class _PackageListState extends State<PackageList> with AutomaticKeepAliveClientMixin {
  List<Pkg>? _items;
  Object? _error;
  Timer? _timer;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
    app.revision.addListener(_load);
    // The server polls 17TRACK; re-read its cached results every 5 minutes (no quota involved).
    _timer = Timer.periodic(const Duration(minutes: 5), (_) => _load());
  }

  @override
  void dispose() {
    app.revision.removeListener(_load);
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final items = await app.api.packages(view: widget.view, direction: widget.direction);
      if (!mounted) return;
      setState(() {
        _items = items;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e);
      showError(context, e);
    }
  }

  Future<void> _pull() async {
    try {
      if (widget.view == 'active') await app.api.refreshAll();
    } catch (e) {
      if (mounted) showError(context, e);
    }
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final items = _items;
    final theme = Theme.of(context);
    Widget child;
    if (items == null && _error == null) {
      child = const Center(child: CircularProgressIndicator());
    } else if (items == null) {
      child = ListView(children: [
        const SizedBox(height: 80),
        Center(child: Text('Could not load packages.\n$_error', textAlign: TextAlign.center)),
        Center(child: TextButton(onPressed: _load, child: const Text('Try again'))),
      ]);
    } else {
      child = ListView.separated(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.only(bottom: 88),
        itemCount: items.length + 1,
        separatorBuilder: (_, i) => SizedBox(height: i == 0 ? 0 : 6),
        itemBuilder: (_, i) {
          if (i == 0) {
            return Container(
              color: theme.colorScheme.surfaceContainerLow,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              alignment: Alignment.centerRight,
              child: items.isEmpty
                  ? Text(_emptyText(), textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w300))
                  : Text('${items.length} PACKAGE${items.length == 1 ? '' : 'S'}',
                      style: const TextStyle(fontWeight: FontWeight.w300, fontSize: 16, letterSpacing: 0.5)),
            );
          }
          final p = items[i - 1];
          return PackageRow(pkg: p, selected: p.id == widget.selected, onTap: () => widget.onOpen(p));
        },
      );
    }
    return ScrollConfiguration(
      behavior: const _DragAll(),
      child: RefreshIndicator(onRefresh: _pull, color: theme.colorScheme.primary, child: child),
    );
  }

  String _emptyText() => switch ((widget.view, widget.direction)) {
        ('history', _) => 'No packages in History yet. Delivered packages move here automatically.',
        (_, 'sending') => 'Nothing being sent. Add a package and choose "Sending".',
        _ => 'No packages yet. Tap + to add a tracking number.',
      };
}
