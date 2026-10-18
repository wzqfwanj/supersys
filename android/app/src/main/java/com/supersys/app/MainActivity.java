package com.supersys.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * supersys 手机客户端：套壳 WebView，打开电脑上或云端跑的 supersys 服务。
 * 第一次启动输入服务地址（例如 https://你的域名/supersys/），之后记住。
 */
public class MainActivity extends Activity {
    private static final String PREFS = "supersys";
    private static final String KEY_URL = "server_url";
    private static final String DEFAULT_HINT = "https://example.com/supersys/";

    private SharedPreferences prefs;
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String saved = prefs.getString(KEY_URL, "");
        if (saved.isEmpty()) {
            showSetup(null);
        } else {
            showWeb(saved);
        }
    }

    private int dp(int value) {
        return Math.round(getResources().getDisplayMetrics().density * value);
    }

    /** 设置 / 修改服务地址。 */
    private void showSetup(String preset) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundColor(Color.parseColor("#121212"));
        box.setPadding(dp(24), dp(48), dp(24), dp(24));

        TextView title = new TextView(this);
        title.setText("supersys");
        title.setTextSize(22);
        title.setTextColor(Color.parseColor("#e8e8e8"));
        box.addView(title);

        TextView hint = new TextView(this);
        hint.setText("输入 supersys 服务地址：云端填 https://你的域名/supersys/；本地填电脑上 python server.py 8000 --lan 打印的 http://192.168.x.x:8000。");
        hint.setTextSize(14);
        hint.setTextColor(Color.parseColor("#8f8f8f"));
        hint.setPadding(0, dp(16), 0, dp(20));
        box.addView(hint);

        EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setHint(DEFAULT_HINT);
        input.setText(preset == null ? "" : preset);
        input.setTextColor(Color.parseColor("#e8e8e8"));
        input.setHintTextColor(Color.parseColor("#8f8f8f"));
        box.addView(input);

        Button save = new Button(this);
        save.setText("保存并打开");
        save.setOnClickListener(v -> {
            String url = input.getText().toString().trim();
            if (url.isEmpty()) {
                Toast.makeText(this, "请先输入服务地址", Toast.LENGTH_SHORT).show();
                return;
            }
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                url = "http://" + url;
            }
            prefs.edit().putString(KEY_URL, url).apply();
            showWeb(url);
        });
        LinearLayout.LayoutParams saveParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        saveParams.topMargin = dp(12);
        box.addView(save, saveParams);

        setContentView(box);
    }

    /** 打开页面，右下角有个小按钮可以改服务地址。 */
    private void showWeb(String url) {
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        webView.setBackgroundColor(Color.parseColor("#121212"));
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                Toast.makeText(MainActivity.this,
                        "连不上电脑上的 supersys：\n" + description + "\n请确认电脑已运行 python server.py 8000 --lan",
                        Toast.LENGTH_LONG).show();
            }
        });
        webView.loadUrl(url);

        FrameLayout root = new FrameLayout(this);
        root.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        Button gear = new Button(this);
        gear.setText("⋯");
        gear.setTextSize(16);
        gear.setAlpha(0.4f);
        gear.setBackgroundColor(Color.TRANSPARENT);
        gear.setTextColor(Color.parseColor("#e8e8e8"));
        gear.setOnClickListener(v -> showChangeDialog());
        FrameLayout.LayoutParams gearParams = new FrameLayout.LayoutParams(
                dp(44), dp(44), Gravity.BOTTOM | Gravity.END);
        gearParams.setMargins(0, 0, dp(8), dp(8));
        root.addView(gear, gearParams);

        setContentView(root);
    }

    private void showChangeDialog() {
        EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setText(prefs.getString(KEY_URL, ""));
        new AlertDialog.Builder(this)
                .setTitle("服务器地址")
                .setView(input)
                .setPositiveButton("保存", (dialog, which) -> {
                    String url = input.getText().toString().trim();
                    if (url.isEmpty()) {
                        return;
                    }
                    if (!url.startsWith("http://") && !url.startsWith("https://")) {
                        url = "http://" + url;
                    }
                    prefs.edit().putString(KEY_URL, url).apply();
                    showWeb(url);
                })
                .setNegativeButton("取消", null)
                .show();
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
