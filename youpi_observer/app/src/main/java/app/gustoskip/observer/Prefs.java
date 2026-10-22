package app.gustoskip.observer;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Device credentials from pairing.
 *
 * App-private SharedPreferences: readable only by this uid on a non-rooted
 * device. Not EncryptedSharedPreferences -- that needs androidx.security, and
 * for a sideloaded trial the extra dependency buys little, since an attacker
 * with the file also has the device. Worth revisiting before any wider use.
 */
final class Prefs {
    private static final String FILE = "observer";
    private final SharedPreferences p;

    Prefs(Context ctx) {
        this.p = ctx.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    String baseUrl()    { return p.getString("base_url", null); }
    String deviceId()   { return p.getString("device_id", null); }
    String signingKey() { return p.getString("signing_key", null); }

    void save(String baseUrl, String deviceId, String signingKey) {
        p.edit().putString("base_url", baseUrl)
                .putString("device_id", deviceId)
                .putString("signing_key", signingKey)
                .apply();
    }

    void clear() { p.edit().clear().apply(); }
}
