package app.gustoskip.observer;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.provider.Telephony;
import android.telephony.SmsMessage;

/**
 * Parses each incoming SMS on the device and forwards only the structured
 * result.
 *
 * What happens to the raw text: it exists as a local variable inside
 * {@link #onReceive} for the duration of the parse and nothing else. It is
 * never written to disk, never put in SharedPreferences, never logged, and
 * never placed in any object that reaches {@link Api}. When onReceive returns
 * the reference is gone. {@link Api#report} accepts a parsed Credit, so there
 * is no parameter through which message text could travel even by mistake.
 *
 * Messages that are not an incoming credit -- OTPs above all -- produce null
 * from the parser and are dropped here without any network call at all.
 */
public class SmsReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !Telephony.Sms.Intents.SMS_RECEIVED_ACTION.equals(intent.getAction())) {
            return;
        }

        final Api api = new Api(context);
        if (!api.isPaired()) return;

        SmsMessage[] parts = Telephony.Sms.Intents.getMessagesFromIntent(intent);
        if (parts == null || parts.length == 0) return;

        // Multipart messages arrive split; the credit details can straddle the
        // boundary, so parse the joined text rather than each part.
        StringBuilder joined = new StringBuilder();
        long observedAt = System.currentTimeMillis();
        for (SmsMessage m : parts) {
            if (m == null) continue;
            String b = m.getMessageBody();
            if (b != null) joined.append(b);
            if (m.getTimestampMillis() > 0) observedAt = m.getTimestampMillis();
        }

        final CreditParser.Credit credit = CreditParser.parse(joined.toString());
        if (credit == null) return;   // not a credit: discarded, nothing sent

        final long at = observedAt;
        new Thread(new Runnable() {
            @Override public void run() {
                api.report(credit, at);
            }
        }).start();
    }
}
