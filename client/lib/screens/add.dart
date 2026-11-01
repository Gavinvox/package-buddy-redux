// Add a package: number, description, carrier (auto-detect + searchable override), direction.
import 'dart:async';

import 'package:flutter/material.dart';

import '../models.dart';
import '../state.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'detail.dart' show outcomeText;

class AddScreen extends StatefulWidget {
  const AddScreen({super.key});
  @override
  State<AddScreen> createState() => _AddScreenState();
}

class _AddScreenState extends State<AddScreen> {
  final _number = TextEditingController();
  final _desc = TextEditingController();
  String _direction = 'receiving';
  bool _track = true;
  Detection? _detected;
  Carrier? _override;
  Timer? _debounce;
  bool _saving = false;

  @override
  void dispose() {
    _debounce?.cancel();
    _number.dispose();
    _desc.dispose();
    super.dispose();
  }

  void _numberChanged(String v) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), () async {
      final n = v.trim();
      if (n.length < 6) {
        setState(() => _detected = null);
        return;
      }
      try {
        final d = await app.api.detect(n);
        if (mounted && _number.text.trim() == n) setState(() => _detected = d);
      } catch (_) {}
    });
  }

  Future<void> _pickCarrier() async {
    final c = await showDialog<Carrier>(context: context, builder: (_) => const CarrierPicker());
    if (c != null) setState(() => _override = c);
  }

  Future<void> _save() async {
    final n = _number.text.trim();
    if (n.length < 3) {
      toast(context, 'Enter a tracking number');
      return;
    }
    setState(() => _saving = true);
    try {
      // Only a confident local match or the user's choice is sent; otherwise 17TRACK decides.
      final carrier = _override?.code ?? (_detected?.confident == true ? _detected!.code : null);
      final (p, outcome) = await app.api.addPackage(
          number: n, carrier: carrier, description: _desc.text.trim(), direction: _direction, track: _track);
      app.packagesChanged();
      if (!mounted) return;
      toast(context, outcomeText(outcome));
      Navigator.pop(context, p);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final carrierName = _override?.name ?? _detected?.name;
    final limited = _override?.limited ?? _detected?.limited ?? false;
    final band = carrierBand(_override?.code ?? _detected?.code, carrierName);
    return Scaffold(
      appBar: AppBar(title: const Text('Add package'), actions: [
        IconButton(
            tooltip: 'Save',
            onPressed: _saving ? null : _save,
            icon: _saving
                ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white))
                : const Icon(Icons.check, size: 30)),
      ]),
      body: Constrained(
        maxWidth: 640,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          TextField(
            controller: _number,
            autofocus: true,
            onChanged: _numberChanged,
            onSubmitted: (_) => _save(),
            style: const TextStyle(fontSize: 20, letterSpacing: 0.5),
            decoration: const InputDecoration(
                labelText: 'Tracking number', prefixIcon: Icon(Icons.qr_code_2), hintText: 'e.g. 1Z999AA10123456784'),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _desc,
            textCapitalization: TextCapitalization.sentences,
            decoration: const InputDecoration(labelText: 'Description (optional)', prefixIcon: Icon(Icons.label_outline)),
          ),
          const SectionHeader('Carrier'),
          Card(
            margin: EdgeInsets.zero,
            clipBehavior: Clip.antiAlias,
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Container(height: 8, color: carrierName == null ? theme.dividerColor : band.bg),
              ListTile(
                title: Text(carrierName ?? 'Detect automatically'),
                subtitle: Text(_override != null
                    ? 'Chosen by you'
                    : _detected == null
                        ? 'Type the number; 17TRACK will work out the carrier if we can\'t'
                        : _detected!.confident
                            ? 'Detected from the number format'
                            : (_detected!.code == null
                                ? '17TRACK will detect it'
                                : 'Best guess only; 17TRACK will confirm it')),
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  if (_override != null)
                    IconButton(
                        tooltip: 'Back to auto-detect',
                        icon: const Icon(Icons.close),
                        onPressed: () => setState(() => _override = null)),
                  TextButton(onPressed: _pickCarrier, child: const Text('Change')),
                ]),
              ),
              if (limited)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                  child: Text(
                      'Note: 17TRACK has limited or no data for this carrier right now (carrier not available via 17TRACK). '
                      'You can still save it and open it on the carrier\'s site.',
                      style: TextStyle(color: stateColor('out_for_delivery', theme.brightness))),
                ),
            ]),
          ),
          const SectionHeader('Direction'),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'receiving', label: Text('Receiving'), icon: Icon(Icons.arrow_back)),
              ButtonSegment(value: 'sending', label: Text('Sending'), icon: Icon(Icons.arrow_forward)),
            ],
            selected: {_direction},
            onSelectionChanged: (s) => setState(() => _direction = s.first),
          ),
          const SizedBox(height: 12),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: _track,
            onChanged: (v) => setState(() => _track = v),
            title: const Text('Track it now'),
            subtitle: const Text('A number new to this server uses 1 of the shared 17TRACK quota. '
                'Turn off to just save it.'),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _saving ? null : _save,
            icon: const Icon(Icons.add),
            label: const Padding(padding: EdgeInsets.all(12), child: Text('Add package', style: TextStyle(fontSize: 16))),
          ),
        ]),
      ),
    );
  }
}

/// Searchable carrier list (featured carriers first, then all ~3,500 17TRACK carriers).
class CarrierPicker extends StatefulWidget {
  const CarrierPicker({super.key});
  @override
  State<CarrierPicker> createState() => _CarrierPickerState();
}

class _CarrierPickerState extends State<CarrierPicker> {
  List<Carrier> _items = [];
  Timer? _debounce;
  String _q = '';

  @override
  void initState() {
    super.initState();
    _search('');
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  Future<void> _search(String q) async {
    _q = q;
    try {
      final r = await app.api.carriers(q);
      if (mounted && q == _q) setState(() => _items = r);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 480, maxHeight: 600),
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: TextField(
              autofocus: true,
              decoration: const InputDecoration(prefixIcon: Icon(Icons.search), labelText: 'Search carriers'),
              onChanged: (v) {
                _debounce?.cancel();
                _debounce = Timer(const Duration(milliseconds: 250), () => _search(v.trim()));
              },
            ),
          ),
          Expanded(
            child: ListView.builder(
              itemCount: _items.length,
              itemBuilder: (_, i) {
                final c = _items[i];
                final band = carrierBand(c.code, c.name);
                return ListTile(
                  leading: Container(width: 10, height: 36, color: band.bg),
                  title: Text(c.name),
                  subtitle: Text([
                    if (c.featured) 'Popular',
                    if (c.country != null && c.country != '0') c.country!,
                    if (c.limited) 'limited via 17TRACK',
                  ].join(' · ')),
                  onTap: () => Navigator.pop(context, c),
                );
              },
            ),
          ),
          Align(
              alignment: Alignment.centerRight,
              child: Padding(
                  padding: const EdgeInsets.all(8),
                  child: TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')))),
        ]),
      ),
    );
  }
}
