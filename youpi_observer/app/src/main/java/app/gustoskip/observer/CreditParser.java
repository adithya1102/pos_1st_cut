package app.gustoskip.observer;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Turns a bank SMS into the four structured fields the gateway accepts, or
 * nothing at all.
 *
 * This class is the whole privacy boundary of the app. Everything it does not
 * return is discarded: {@link #parse} takes the message text as an argument and
 * returns only numbers and an identifier, so no caller can forward the original
 * text even by accident. Nothing here logs, stores, or hashes the input.
 *
 * It fails closed. A message is dropped unless it positively looks like an
 * incoming credit, so OTPs, debit alerts, balance statements and marketing all
 * produce null and never leave the device. Dropping a real payment is a visible
 * failure the operator can retry; uploading an OTP is not recoverable.
 *
 * Written against YOUPI's documented request shape for POST /api/v1/observers/sms
 * (amountPaise, bankReferenceNumber, senderVpa, observedAt). No gateway source
 * was copied.
 */
public final class CreditParser {

    private CreditParser() {}

    /** The only thing that may leave the device. */
    public static final class Credit {
        public final long amountPaise;
        public final String bankReferenceNumber;   // nullable
        public final String senderVpa;             // nullable

        Credit(long amountPaise, String bankReferenceNumber, String senderVpa) {
            this.amountPaise = amountPaise;
            this.bankReferenceNumber = bankReferenceNumber;
            this.senderVpa = senderVpa;
        }
    }

    // A credit must be positively indicated. "credit" alone also covers
    // "credited"; kept as a word-ish match so "credit card" style noise still
    // needs one of the other guards to pass.
    private static final Pattern CREDIT = Pattern.compile(
            "\\b(credited|credit of|received|deposited|has been credited)\\b");

    // Anything that is plainly money leaving, or a one-time code, is refused
    // before the credit check even runs.
    private static final Pattern DEBIT = Pattern.compile(
            "\\b(debited|debit of|withdrawn|spent|paid to|sent to|transferred to|purchase)\\b");

    private static final Pattern OTP = Pattern.compile(
            "\\b(otp|one[- ]time password|verification code|do not share|never share)\\b");

    // Rs.1,234.50 | INR 1234 | ₹1,234.50
    private static final Pattern AMOUNT = Pattern.compile(
            "(?:inr|rs\\.?|₹)\\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\\.[0-9]{1,2})?|[0-9]+(?:\\.[0-9]{1,2})?)");

    // UPI Ref No 123456789012 | Ref: 123456789012 | RRN 123456789012
    private static final Pattern REF = Pattern.compile(
            "(?:upi\\s*ref(?:erence)?(?:\\s*no\\.?)?|ref(?:erence)?(?:\\s*no\\.?)?|rrn|txn\\s*id)"
                    + "[:\\s#]*([0-9]{6,22})");

    private static final Pattern VPA = Pattern.compile(
            "\\b([a-z0-9._-]{2,64}@[a-z][a-z0-9.-]{1,30})\\b");

    /**
     * @param body raw message text; never retained by this method
     * @return structured credit, or null if this is not an incoming credit
     */
    public static Credit parse(String body) {
        if (body == null || body.isEmpty()) return null;

        final String s = body.toLowerCase(Locale.ROOT);

        // Refuse first, match second. An SMS that mentions both a credit and an
        // OTP is far more likely to be an OTP message than a payment.
        if (OTP.matcher(s).find()) return null;
        if (DEBIT.matcher(s).find()) return null;
        if (!CREDIT.matcher(s).find()) return null;

        Matcher am = AMOUNT.matcher(s);
        if (!am.find()) return null;

        final long paise;
        try {
            BigDecimal rupees = new BigDecimal(am.group(1).replace(",", ""));
            // Integer paise via BigDecimal: binary floating point cannot hold
            // 0.01 exactly and the gateway matches on an exact paise equality.
            paise = rupees.movePointRight(2).setScale(0, RoundingMode.HALF_UP).longValueExact();
        } catch (ArithmeticException | NumberFormatException e) {
            return null;
        }
        if (paise <= 0) return null;

        String ref = null;
        Matcher rm = REF.matcher(s);
        if (rm.find()) ref = rm.group(1);

        String vpa = null;
        Matcher vm = VPA.matcher(s);
        if (vm.find()) vpa = vm.group(1);

        return new Credit(paise, ref, vpa);
    }
}
