package app.gustoskip.observer;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.text.InputType;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import app.gustoskip.observer.R;

/**
 * Pairing and status. The only screen.
 *
 * The enrollment token is typed here, used once for the pair call, and never
 * stored: only the deviceId and signingKey the gateway returns are persisted.
 * The field is a password field so it is not shoulder-readable and not
 * captured in screenshots of the activity by default.
 */
public class MainActivity extends android.app.Activity {

    private EditText urlField;
    private EditText tokenField;
    private TextView status;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText(R.string.app_name);
        title.setTextSize(20);
        root.addView(title);

        urlField = new EditText(this);
        urlField.setHint("https://youpi.example.com");
        urlField.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        root.addView(urlField, lp());

        tokenField = new EditText(this);
        tokenField.setHint("Enrollment token");
        tokenField.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        root.addView(tokenField, lp());

        Button pair = new Button(this);
        pair.setText("Pair this phone");
        pair.setOnClickListener(v -> doPair());
        root.addView(pair, lp());

        status = new TextView(this);
        status.setText(new Api(this).isPaired()
                ? "Paired. Watching for bank credit messages."
                : "Not paired.");
        root.addView(status, lp());

        TextView note = new TextView(this);
        note.setTextSize(12);
        note.setText("Reads incoming SMS on this device, extracts only the amount, "
                + "reference number and payer handle, and sends those. Message text "
                + "is never uploaded, logged or stored. Messages that are not a "
                + "payment credit are ignored.");
        root.addView(note, lp());

        setContentView(root);
        requestSmsPermission();
    }

    private LinearLayout.LayoutParams lp() {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        p.topMargin = (int) (12 * getResources().getDisplayMetrics().density);
        return p;
    }

    private void requestSmsPermission() {
        if (checkSelfPermission(Manifest.permission.RECEIVE_SMS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECEIVE_SMS}, 1);
        }
    }

    private void doPair() {
        final String url = urlField.getText().toString().trim().replaceAll("/+$", "");
        final String token = tokenField.getText().toString().trim();
        if (url.isEmpty() || token.isEmpty()) {
            status.setText("Enter the gateway URL and the enrollment token.");
            return;
        }
        status.setText("Pairing...");
        new Thread(() -> {
            final String err = new Api(MainActivity.this).pair(url, token, android.os.Build.MODEL);
            runOnUiThread(() -> {
                // Clear the token from the field either way; it is single-use
                // and must not linger on screen or in the view hierarchy.
                tokenField.setText("");
                status.setText(err == null
                        ? "Paired. Watching for bank credit messages."
                        : "Pairing failed: " + err);
            });
        }).start();
    }
}
