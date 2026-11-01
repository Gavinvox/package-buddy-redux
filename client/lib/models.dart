// Data classes matching the server's JSON.
class TrackEvent {
  TrackEvent({this.time, this.description = '', this.location, this.stage});
  final String? time;
  final String description;
  final String? location;
  final String? stage;
  factory TrackEvent.fromJson(Map<String, dynamic> j) => TrackEvent(
      time: j['time'] as String?,
      description: (j['description'] ?? '') as String,
      location: j['location'] as String?,
      stage: j['stage'] as String?);
}

class Pkg {
  Pkg(this.j)
      : events = (j['events'] as List?)?.map((e) => TrackEvent.fromJson((e as Map).cast<String, dynamic>())).toList();
  final Map<String, dynamic> j;
  final List<TrackEvent>? events;

  factory Pkg.fromJson(dynamic j) => Pkg((j as Map).cast<String, dynamic>());

  int get id => j['id'] as int;
  String get number => j['tracking_number'] as String;
  int? get carrierCode => j['carrier_code'] as int?;
  String get carrierName => (j['carrier_name'] as String?) ?? 'Unknown carrier';
  String get description => (j['description'] ?? '') as String;
  String get direction => j['direction'] as String;
  bool get sending => direction == 'sending';
  bool get archived => j['archived'] as bool;
  String get mode => j['tracking_mode'] as String;
  String get state => j['state'] as String;
  String get stateLabel => j['state_label'] as String;
  String? get statusText => j['status_text'] as String?;
  String? get eta => j['eta'] as String?;
  String? get lastLocation => j['last_location'] as String?;
  String? get lastEventTime => j['last_event_time'] as String?;
  String? get deliveredAt => j['delivered_at'] as String?;
  int? get days => j['days_in_transit'] as int?;
  int get eventCount => (j['event_count'] ?? 0) as int;
  String? get note => j['note'] as String?;
  bool get carrierLimited => (j['carrier_limited'] ?? false) as bool;
  String get siteUrl => j['carrier_site_url'] as String;
  String get source => (j['source'] ?? '') as String;
  String? get lastChecked => j['last_checked_at'] as String?;
  String? get createdAt => j['created_at'] as String?;
  bool get delivered => state == 'delivered';
  bool get unsupported => state == 'carrier_unsupported';
}

class Carrier {
  Carrier(this.code, this.name, {this.country, this.featured = false, this.limited = false});
  final int code;
  final String name;
  final String? country;
  final bool featured;
  final bool limited;
  factory Carrier.fromJson(dynamic j) => Carrier(j['code'] as int, j['name'] as String,
      country: j['country']?.toString(), featured: (j['featured'] ?? false) as bool, limited: (j['limited'] ?? false) as bool);
}

class Detection {
  Detection(this.code, this.name, this.confident, this.limited, this.note);
  final int? code;
  final String? name;
  final bool confident;
  final bool limited;
  final String? note;
  factory Detection.fromJson(dynamic j) => Detection(j['carrier_code'] as int?, j['carrier_name'] as String?,
      (j['confident'] ?? false) as bool, (j['limited'] ?? false) as bool, j['note'] as String?);
}

class UserInfo {
  UserInfo(this.j);
  final Map<String, dynamic> j;
  factory UserInfo.fromJson(dynamic j) => UserInfo((j as Map).cast<String, dynamic>());
  int get id => j['id'] as int;
  String get username => j['username'] as String;
  bool get isAdmin => j['is_admin'] as bool;
  int? get monthlyLimit => j['monthly_new_limit'] as int?;
  int get newThisMonth => (j['new_numbers_this_month'] ?? 0) as int;
  int get packageCount => (j['package_count'] ?? 0) as int;
}
