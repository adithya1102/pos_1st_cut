import '../models/meal_slot.dart';
import 'api_client.dart';

/// The three meal-slot routes (backend migration 043).
///
/// Reading and applying are available to any staff account with an outlet;
/// DEFINING a slot is owner/manager only and the server answers that with a
/// 403. This service does not try to predict it — the app has no role field
/// (see the note on OutletSettingsScreen's payment-modes row), so the screen
/// attempts the save and reports what the server said.
class MealSlotService {
  final ApiClient _client;

  MealSlotService(this._client);

  /// `GET /pos/meal-slots` — all four slots, saved or not.
  Future<List<MealSlot>> getSlots() async {
    final data = await _client.get('/pos/meal-slots');
    final list = (data as List<dynamic>?) ?? const [];
    return list
        .map((e) => MealSlot.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// `PUT /pos/meal-slots/{key}` — replace the times and the WHOLE dish set.
  ///
  /// [itemIds] is a replacement, not a delta. A foreign or unknown id fails
  /// the entire request with 404 and writes nothing, so a partial save cannot
  /// leave the slot describing a dish set the owner never ticked.
  Future<MealSlot> saveSlot(
    String slotKey, {
    String? startTime,
    String? endTime,
    required List<String> itemIds,
  }) async {
    final data = await _client.put('/pos/meal-slots/$slotKey', body: {
      // Sent even when null: null CLEARS the time, and omitting the key would
      // make "remove the range" unexpressible.
      'start_time': startTime,
      'end_time': endTime,
      'item_ids': itemIds,
    });
    return MealSlot.fromJson(data as Map<String, dynamic>);
  }

  /// `POST /pos/meal-slots/{key}/apply` — this slot's dishes on, every other
  /// dish of the outlet off, in one transaction.
  ///
  /// Idempotent: a second call reports zeros and changes nothing. An empty
  /// slot is refused with 422 SLOT_EMPTY, which surfaces here as an
  /// ApiException rather than a silent menu wipe.
  Future<ApplySlotResult> applySlot(String slotKey) async {
    final data = await _client.post('/pos/meal-slots/$slotKey/apply');
    return ApplySlotResult.fromJson(data as Map<String, dynamic>);
  }
}
