package app.gustoskip.observer;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import org.junit.Test;

/**
 * The parser is the app's privacy boundary, so the negatives matter more than
 * the positives: anything that is not plainly an incoming credit must produce
 * null and therefore never leave the device.
 */
public class CreditParserTest {

    // ---------------------------------------------------------------- credits

    @Test
    public void parsesUpiCreditWithRefAndVpa() {
        CreditParser.Credit c = CreditParser.parse(
                "Dear Customer, Rs.1.00 credited to your A/c XXXXXX1234 on 21-10-26 "
                        + "by UPI from payer@okhdfcbank. UPI Ref No 123456789012. -Test Bank");
        assertNotNull(c);
        assertEquals(100L, c.amountPaise);
        assertEquals("123456789012", c.bankReferenceNumber);
        assertEquals("payer@okhdfcbank", c.senderVpa);
    }

    @Test
    public void parsesThousandsSeparatorAndPaise() {
        CreditParser.Credit c = CreditParser.parse(
                "INR 1,234.50 credited to your account. RRN 998877665544");
        assertNotNull(c);
        assertEquals(123450L, c.amountPaise);
        assertEquals("998877665544", c.bankReferenceNumber);
    }

    @Test
    public void parsesRupeeSymbolAndSurvivesMissingRefAndVpa() {
        CreditParser.Credit c = CreditParser.parse("₹250 received in your account");
        assertNotNull(c);
        assertEquals(25000L, c.amountPaise);
        assertNull(c.bankReferenceNumber);
        assertNull(c.senderVpa);
    }

    @Test
    public void amountIsExactPaiseNotFloatingPoint() {
        // 0.01 and 0.07 are the classic binary-float casualties; the gateway
        // matches on exact integer paise, so these must be exact.
        assertEquals(1L, CreditParser.parse("Rs.0.01 credited").amountPaise);
        assertEquals(7L, CreditParser.parse("Rs.0.07 credited").amountPaise);
        assertEquals(1999L, CreditParser.parse("Rs.19.99 credited").amountPaise);
    }

    // --------------------------------------------------------------- refusals

    @Test
    public void refusesOtp() {
        assertNull(CreditParser.parse(
                "123456 is your OTP for a transaction of Rs.1.00. Do not share with anyone."));
        assertNull(CreditParser.parse(
                "Your one-time password is 998877. Never share this code."));
    }

    @Test
    public void refusesOtpEvenWhenItAlsoSaysCredited() {
        // The dangerous case: an OTP message that happens to contain credit
        // wording. Refusing first is why this returns null.
        assertNull(CreditParser.parse(
                "OTP 445566 to approve Rs.500 credited to merchant. Do not share."));
    }

    @Test
    public void refusesDebits() {
        assertNull(CreditParser.parse("Rs.1.00 debited from your A/c XXXX1234 on 21-10-26"));
        assertNull(CreditParser.parse("INR 250 paid to merchant@upi via UPI"));
        assertNull(CreditParser.parse("Rs.99 spent on your card ending 1234"));
    }

    @Test
    public void refusesBalanceAndMarketing() {
        assertNull(CreditParser.parse("Your available balance is Rs.5,000.00"));
        assertNull(CreditParser.parse("Get a personal loan of Rs.5,00,000 at low interest!"));
    }

    @Test
    public void refusesCreditWordingWithNoAmount() {
        assertNull(CreditParser.parse("Your salary has been credited. Check your statement."));
    }

    @Test
    public void refusesEmptyAndNull() {
        assertNull(CreditParser.parse(null));
        assertNull(CreditParser.parse(""));
        assertNull(CreditParser.parse("   "));
    }

    @Test
    public void refusesZeroAmount() {
        assertNull(CreditParser.parse("Rs.0.00 credited to your account"));
    }

    // ----------------------------------------------------------- no leakage

    @Test
    public void returnsNoFieldThatCouldCarryMessageText() throws Exception {
        // Structural guard: if someone later adds a `rawText` field to Credit,
        // this fails. The object is the only thing the sender can reach, so
        // keeping it free of free-text fields is what stops a leak.
        for (java.lang.reflect.Field f : CreditParser.Credit.class.getDeclaredFields()) {
            String n = f.getName().toLowerCase();
            if (n.contains("raw") || n.contains("text") || n.contains("body")
                    || n.contains("message") || n.contains("sms")) {
                throw new AssertionError("Credit exposes a free-text field: " + f.getName());
            }
        }
        // senderVpa is the only String, and it is an identifier, not content.
        assertEquals(String.class,
                CreditParser.Credit.class.getDeclaredField("senderVpa").getType());
    }
}
