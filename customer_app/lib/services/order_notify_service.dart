import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:web_socket_channel/status.dart' as ws_status;

import '../config/app_config.dart';
import '../models/order_notify.dart';

/// Read-only WebSocket client for staff → customer "notify" pushes on the
/// order status screen. It listens to `ws://<host>/ws/order/{orderId}` and
/// surfaces ONLY `event == "notify"` messages as [OrderNotify]s. Status
/// updates (and any other frames) on the same socket are ignored — the
/// existing 4s polling keeps driving the stepper.
///
/// This is display-only: nothing is ever sent back to the server.
class OrderNotifyClient {
  OrderNotifyClient(this.orderId);

  final String orderId;

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  final _controller = StreamController<OrderNotify>.broadcast();

  /// Emits one [OrderNotify] per incoming `notify` frame.
  Stream<OrderNotify> get notifications => _controller.stream;

  /// Derive the WS endpoint from [AppConfig.baseUrl]: strip the `/api/v1`
  /// suffix and swap the http(s) scheme for ws(s).
  static Uri buildUri(String orderId) {
    var base = AppConfig.baseUrl;
    if (base.endsWith('/')) base = base.substring(0, base.length - 1);
    const apiSuffix = '/api/v1';
    if (base.endsWith(apiSuffix)) {
      base = base.substring(0, base.length - apiSuffix.length);
    }
    if (base.startsWith('https')) {
      base = base.replaceFirst('https', 'wss');
    } else if (base.startsWith('http')) {
      base = base.replaceFirst('http', 'ws');
    }
    return Uri.parse('$base/ws/order/$orderId');
  }

  void connect() {
    if (_channel != null) return;
    try {
      final channel = WebSocketChannel.connect(buildUri(orderId));
      _channel = channel;
      _sub = channel.stream.listen(
        _onMessage,
        onError: (_) {},
        onDone: () {},
        cancelOnError: false,
      );
    } catch (_) {
      // A failed WS connection must never break the (polling-driven) screen.
    }
  }

  void _onMessage(dynamic raw) {
    if (raw is! String) return;
    Map<String, dynamic> json;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return;
      json = decoded.cast<String, dynamic>();
    } catch (_) {
      return;
    }
    // Only react to notify events; everything else (status updates, etc.) is
    // ignored so the polling loop remains the single source of stepper truth.
    if (json['event'] != 'notify') return;
    if (_controller.isClosed) return;
    _controller.add(OrderNotify.fromJson(json));
  }

  Future<void> dispose() async {
    await _sub?.cancel();
    _sub = null;
    try {
      await _channel?.sink.close(ws_status.normalClosure);
    } catch (_) {}
    _channel = null;
    if (!_controller.isClosed) await _controller.close();
  }
}
