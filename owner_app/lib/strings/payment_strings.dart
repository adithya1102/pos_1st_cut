/// All user-facing copy for the Payment tab, in one place for translation.
///
/// Nothing here is logic — every string is a constant an owner reads. Keeping
/// them out of the widget tree means a future translation pass touches one
/// file instead of hunting through three card widgets.
class PaymentStrings {
  const PaymentStrings._();

  static const tabLabel = 'Payment';
  static const screenTitle = 'Payment';

  // ------------------------- Pay when collecting --------------------------
  static const pickupTitle = 'Pay when collecting';
  static const pickupNote = 'At your own risk. The customer has not paid '
      'yet, so a no-show leaves you with prepared food.';

  // ------------------------------ Own UPI ----------------------------------
  static const upiTitle = 'Your own UPI';
  static const upiNote = 'The customer pays your UPI ID directly. Payment is '
      'not confirmed automatically: check your bank balance, then accept '
      'the order.';
  static const upiVpaLabel = 'Your UPI ID';
  static const upiVpaHint = 'restaurant@okaxis';
  static const upiPayeeLabel = 'Name on the UPI account';
  static const upiPayeeHint = 'Test Kitchen';
  static const upiAttestLabel =
      'I sent myself Rs 1 using this UPI ID and received it';
  static const upiReattestHint =
      'You changed your UPI ID, so please confirm the Rs 1 test again.';
  static const upiSaveDetails = 'Save UPI details';

  // --------------------------- Payment gateway ------------------------------
  static const gatewayTitle = 'Payment gateway';
  static const gatewayAvailableNote =
      'Customers pay online and it is confirmed automatically.';
  static const gatewayUnavailableNote = 'Temporarily unavailable. Coming '
      'soon.';

  // ------------------------------- summary ---------------------------------
  static const summaryPrefix = 'Customers can pay: ';
  static const summaryNone =
      'Customers cannot pay you anything right now — turn on at least one '
      'method above.';

  static String methodLabel(String wire) => switch (wire) {
        'PAY_AT_PICKUP' => pickupTitle,
        'UPI_MANUAL' => upiTitle,
        'PREPAID' => gatewayTitle,
        _ => wire,
      };

  // ------------------------------- errors -----------------------------------
  static const couldNotLoad = 'Could not load your payment settings.';
  static const couldNotSave =
      'Could not save. Check your connection and try again.';
  static const forbidden =
      'Only the restaurant owner or a manager can change this.';
  static const retry = 'Retry';
}
