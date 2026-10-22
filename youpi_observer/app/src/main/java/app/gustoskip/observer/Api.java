package app.gustoskip.observer;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * Talks to two documented gateway endpoints and nothing else.
 *
 *   POST /api/v1/pollers/android/pair
 *     in : {enrollmentToken, deviceName, version:"v1"}
 *     out: {paired:true, deviceId, signingKey}
 *
 *   POST /api/v1/observers/sms
 *     headers: X-Device-Id, X-Timestamp, X-Signature
 *     signature: hex HMAC-SHA256 of "<raw body>:<timestamp>" keyed on signingKey
 *     in : {deviceId, amountPaise, amount, bankReferenceNumber, senderVpa, observedAt}
 *
 * Written from that contract. No gateway source was copied.
 *
 * The request body is built here and signed from the exact same String that is
 * written to the socket: re-serialising between signing and sending would
 * change the bytes and the server's HMAC check would reject every delivery.
 */
final class Api {

    private final Prefs prefs;

    Api(Context ctx) {
        this.prefs = new Prefs(ctx);
    }

    boolean isPaired() {
        return prefs.deviceId() != null && prefs.signingKey() != null;
    }

    /** @return null on success, otherwise a short human-readable reason. */
    String pair(String baseUrl, String enrollmentToken, String deviceName) {
        try {
            JSONObject body = new JSONObject();
            body.put("enrollmentToken", enrollmentToken);
            body.put("deviceName", deviceName);
            body.put("version", "v1");

            Response r = post(baseUrl + "/api/v1/pollers/android/pair",
                    body.toString(), null, null, null);

            if (r.code == 401) return "Enrollment token rejected.";
            if (r.code == 404) return "Not reachable at that URL (404).";
            if (r.code < 200 || r.code >= 300) return "Gateway returned " + r.code + ".";

            JSONObject out = new JSONObject(r.body);
            String deviceId = out.optString("deviceId", null);
            String signingKey = out.optString("signingKey", null);
            if (deviceId == null || signingKey == null) return "Gateway did not return a device id.";

            prefs.save(baseUrl, deviceId, signingKey);
            return null;
        } catch (Exception e) {
            // Deliberately the class name only: an exception message can quote
            // the request, and the request carries the enrollment token.
            return "Pairing failed (" + e.getClass().getSimpleName() + ").";
        }
    }

    /**
     * Sends ONE parsed credit. Takes the structured fields, never the message.
     *
     * @return null on success, otherwise a short reason
     */
    String report(CreditParser.Credit credit, long observedAtMillis) {
        if (!isPaired()) return "Not paired.";
        try {
            JSONObject body = new JSONObject();
            body.put("deviceId", prefs.deviceId());
            body.put("amountPaise", credit.amountPaise);
            body.put("amount", String.format(java.util.Locale.ROOT, "%d.%02d",
                    credit.amountPaise / 100, credit.amountPaise % 100));
            if (credit.bankReferenceNumber != null) {
                body.put("bankReferenceNumber", credit.bankReferenceNumber);
            }
            if (credit.senderVpa != null) {
                body.put("senderVpa", credit.senderVpa);
            }
            body.put("observedAt", observedAtMillis);

            // Sign the exact bytes that go out.
            final String wire = body.toString();
            final String ts = Long.toString(System.currentTimeMillis());
            final String sig = hmacHex(wire + ":" + ts, prefs.signingKey());

            Response r = post(prefs.baseUrl() + "/api/v1/observers/sms",
                    wire, prefs.deviceId(), ts, sig);

            if (r.code >= 200 && r.code < 300) return null;
            return "Gateway returned " + r.code + ".";
        } catch (Exception e) {
            return "Send failed (" + e.getClass().getSimpleName() + ").";
        }
    }

    // ------------------------------------------------------------------ plumbing

    private static final class Response {
        final int code;
        final String body;
        Response(int code, String body) { this.code = code; this.body = body; }
    }

    private static Response post(String url, String body, String deviceId,
                                 String timestamp, String signature) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setRequestMethod("POST");
            c.setConnectTimeout(15000);
            c.setReadTimeout(15000);
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            if (deviceId != null) c.setRequestProperty("X-Device-Id", deviceId);
            if (timestamp != null) c.setRequestProperty("X-Timestamp", timestamp);
            if (signature != null) c.setRequestProperty("X-Signature", signature);

            byte[] out = body.getBytes(StandardCharsets.UTF_8);
            try (OutputStream os = c.getOutputStream()) {
                os.write(out);
            }

            int code = c.getResponseCode();
            InputStream in = (code >= 200 && code < 300) ? c.getInputStream() : c.getErrorStream();
            return new Response(code, in == null ? "" : readAll(in));
        } finally {
            c.disconnect();
        }
    }

    private static String readAll(InputStream in) throws Exception {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
        return bos.toString(StandardCharsets.UTF_8.name());
    }

    static String hmacHex(String payload, String keyHex) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(keyHex.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        byte[] d = mac.doFinal(payload.getBytes(StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder(d.length * 2);
        for (byte b : d) sb.append(Character.forDigit((b >> 4) & 0xF, 16))
                           .append(Character.forDigit(b & 0xF, 16));
        return sb.toString();
    }
}
