package com.supersys.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import org.json.JSONObject;

/**
 * supersys 手机客户端：
 *  - 本地存储：数据存在手机 App 内（离线可用）
 *  - 云端存储：手机号验证码登录，数据在服务器上，多设备同步
 * 第一次打开先选择模式，之后记住；右下角「⋯」可以随时切换。
 */
public class MainActivity extends Activity {
    private static final String PREFS = "supersys";
    private static final String PREF_MODE = "storage_mode";
    private static final String PREF_URL = "server_url";
    private static final String CLOUD_HINT = "https://你的域名/supersys/";
    private static final String DARK = "#121212";
    private static final String INK = "#e8e8e8";
    private static final String MUTED = "#8f8f8f";

    private SharedPreferences prefs;
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String mode = prefs.getString(PREF_MODE, "");
        if (mode.isEmpty()) {
            showChooser();
        } else {
            openMode(mode, prefs.getString(PREF_URL, ""));
        }
    }

    private int dp(int value) {
        return Math.round(getResources().getDisplayMetrics().density * value);
    }

    /** 首次启动：选择本地存储还是云端存储。 */
    private void showChooser() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundColor(Color.parseColor(DARK));
        box.setPadding(dp(24), dp(48), dp(24), dp(24));

        TextView title = new TextView(this);
        title.setText("supersys");
        title.setTextSize(22);
        title.setTextColor(Color.parseColor(INK));
        box.addView(title);

        TextView hint = new TextView(this);
        hint.setText("选择数据存在哪里：\n\n本地存储：只存在这台手机上，离线也能用。\n云端存储：邮箱验证码登录，多设备同步。");
        hint.setTextSize(14);
        hint.setTextColor(Color.parseColor(MUTED));
        hint.setPadding(0, dp(16), 0, dp(24));
        box.addView(hint);

        Button local = new Button(this);
        local.setText("本地存储（离线）");
        local.setOnClickListener(v -> {
            prefs.edit().putString(PREF_MODE, "local").apply();
            openLocal();
        });
        box.addView(local, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        Button cloud = new Button(this);
        cloud.setText("云端存储（邮箱登录）");
        cloud.setOnClickListener(v -> {
            String url = builtinCloudUrl();
            if (url.isEmpty()) url = prefs.getString(PREF_URL, "");
            if (url.isEmpty()) {
                showCloudSetup("");
            } else {
                prefs.edit().putString(PREF_MODE, "cloud").putString(PREF_URL, url).apply();
                openCloud(url);
            }
        });
        LinearLayout.LayoutParams cloudParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        cloudParams.topMargin = dp(10);
        box.addView(cloud, cloudParams);

        setContentView(box);
    }

    /** 构建时注入的云端地址（assets/cloud.json）；没有就返回空串。 */
    private String builtinCloudUrl() {
        try (InputStream input = getAssets().open("cloud.json")) {
            byte[] buffer = new byte[input.available()];
            int read = input.read(buffer);
            String text = new String(buffer, 0, Math.max(read, 0), StandardCharsets.UTF_8);
            return new JSONObject(text).optString("url", "");
        } catch (Exception error) {
            return "";
        }
    }
    /** 云端模式：填服务器地址。 */
    private void showCloudSetup(String preset) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundColor(Color.parseColor(DARK));
        box.setPadding(dp(24), dp(48), dp(24), dp(24));

        TextView title = new TextView(this);
        title.setText("supersys 云端");
        title.setTextSize(22);
        title.setTextColor(Color.parseColor(INK));
        box.addView(title);

        TextView hint = new TextView(this);
        hint.setText("输入服务器地址，例如：\n" + CLOUD_HINT);
        hint.setTextSize(14);
        hint.setTextColor(Color.parseColor(MUTED));
        hint.setPadding(0, dp(16), 0, dp(20));
        box.addView(hint);

        EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setHint(CLOUD_HINT);
        input.setText(preset);
        input.setTextColor(Color.parseColor(INK));
        input.setHintTextColor(Color.parseColor(MUTED));
        box.addView(input);

        Button save = new Button(this);
        save.setText("保存并打开");
        save.setOnClickListener(v -> {
            String url = input.getText().toString().trim();
            if (url.isEmpty()) {
                Toast.makeText(this, "请先输入服务器地址", Toast.LENGTH_SHORT).show();
                return;
            }
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                url = "https://" + url;
            }
            prefs.edit().putString(PREF_MODE, "cloud").putString(PREF_URL, url).apply();
            openCloud(url);
        });
        LinearLayout.LayoutParams saveParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        saveParams.topMargin = dp(12);
        box.addView(save, saveParams);

        setContentView(box);
    }

    private WebView createWebView() {
        WebView view = new WebView(this);
        WebSettings settings = view.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        view.setBackgroundColor(Color.parseColor(DARK));
        return view;
    }

    private void openMode(String mode, String url) {
        if ("cloud".equals(mode)) {
            openCloud(url);
        } else {
            openLocal();
        }
    }

    /** 本地存储：加载 App 内置页面，数据用原生文件保存（离线可用）。 */
    private void openLocal() {
        webView = createWebView();
        webView.addJavascriptInterface(new LocalStoreBridge(), "SupersysNative");
        webView.setWebViewClient(new WebViewClient());
        webView.loadUrl("file:///android_asset/www/index.html?local");
        setContentView(withSettingsButton(webView));
    }

    /** 云端存储：加载服务器页面，手机号验证码登录。 */
    private void openCloud(String url) {
        if (url == null || url.isEmpty()) {
            showCloudSetup("");
            return;
        }
        webView = createWebView();
        webView.setWebViewClient(new WebViewClient());
        webView.loadUrl(url);
        setContentView(withSettingsButton(webView));
    }

    /** 页面右下角的小按钮：切换本地 / 云端存储。 */
    private FrameLayout withSettingsButton(WebView view) {
        FrameLayout root = new FrameLayout(this);
        root.addView(view, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        Button gear = new Button(this);
        gear.setText("⋯");
        gear.setTextSize(16);
        gear.setAlpha(0.4f);
        gear.setBackgroundColor(Color.TRANSPARENT);
        gear.setTextColor(Color.parseColor(INK));
        gear.setOnClickListener(v -> showSettingsDialog());
        FrameLayout.LayoutParams gearParams = new FrameLayout.LayoutParams(
                dp(44), dp(44), Gravity.BOTTOM | Gravity.END);
        gearParams.setMargins(0, 0, dp(8), dp(8));
        root.addView(gear, gearParams);
        return root;
    }

    private void showSettingsDialog() {
        String stored = prefs.getString(PREF_MODE, "local");
        String current = "cloud".equals(stored) ? "云端存储" : "本地存储";
        new AlertDialog.Builder(this)
                .setTitle("当前：" + current)
                .setItems(new String[] { "切换到本地存储", "切换到云端存储", "修改云端地址" }, (dialog, which) -> {
                    if (which == 0) {
                        prefs.edit().putString(PREF_MODE, "local").apply();
                        openLocal();
                    } else if (which == 1) {
                        String url = prefs.getString(PREF_URL, "");
                        if (url.isEmpty()) {
                            showCloudSetup("");
                        } else {
                            prefs.edit().putString(PREF_MODE, "cloud").apply();
                            openCloud(url);
                        }
                    } else {
                        showCloudSetup(prefs.getString(PREF_URL, ""));
                    }
                })
                .setNegativeButton("取消", null)
                .show();
    }

    /** 本地存储：把 JSON 数据写到 App 私有目录。 */
    private class LocalStoreBridge {
        private File dataFile() {
            return new File(getFilesDir(), "supersys_local.json");
        }

        @JavascriptInterface
        public String loadData() {
            try {
                File file = dataFile();
                if (!file.exists()) return "";
                byte[] buffer = new byte[(int) file.length()];
                try (FileInputStream input = new FileInputStream(file)) {
                    int read = input.read(buffer);
                    if (read <= 0) return "";
                }
                return new String(buffer, StandardCharsets.UTF_8);
            } catch (Exception error) {
                return "";
            }
        }

        @JavascriptInterface
        public void saveData(String json) {
            try (FileOutputStream output = new FileOutputStream(dataFile())) {
                output.write(json.getBytes(StandardCharsets.UTF_8));
            } catch (Exception ignored) {
                // 存储失败时界面数据仍在内存里
            }
        }
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
