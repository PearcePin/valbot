package io.pearce.valora;

import android.Manifest;
import android.app.Activity;
import android.app.Dialog;
import android.os.Build;
import android.os.Bundle;
import android.graphics.Color;
import android.net.Uri;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.view.View;
import android.view.WindowManager;
import android.view.Window;
import android.view.WindowInsets;
import android.graphics.Insets;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.Button;
import android.widget.TextView;
import com.chaquo.python.Python;
import org.json.JSONObject;
import org.json.JSONArray;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private WebView web;
    private Dialog loginDialog;
    private WebView loginView;
    private String region = "ap";
    private boolean importing = false;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private static final String LOGIN = "https://auth.riotgames.com/authorize?client_id=play-valorant-web-prod&redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in&response_type=token%20id_token&scope=account%20openid&nonce=";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(11,18,32));
        getWindow().setNavigationBarColor(Color.rgb(11,18,32));
        web = new WebView(this); configure(web);
        web.setWebChromeClient(new WebChromeClient());
        web.setBackgroundColor(Color.rgb(11,18,32));
        web.addJavascriptInterface(new Bridge(), "ValoraNative");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) { return true; }
        });
        // Reserve system bars outside WebView: its own padding does not reliably
        // move HTML/fixed navigation away from Android's edge-to-edge overlays.
        FrameLayout safeArea = new FrameLayout(this);
        safeArea.setBackgroundColor(Color.rgb(11,18,32));
        safeArea.addView(web, new FrameLayout.LayoutParams(-1, -1));
        fitSystemBars(getWindow(), safeArea);
        setContentView(safeArea);
        safeArea.requestApplyInsets();
        web.loadUrl("file:///android_asset/index.html");
    }
    private void fitSystemBars(Window window, View content) {
        if (Build.VERSION.SDK_INT >= 30) {
            window.setDecorFitsSystemWindows(false);
        }
        content.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                Insets safe = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                view.setPadding(safe.left, safe.top, safe.right, safe.bottom);
                return WindowInsets.CONSUMED;
            }
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets.consumeSystemWindowInsets();
        });
    }
    private void configure(WebView view) {
        view.getSettings().setJavaScriptEnabled(true);
        view.getSettings().setDomStorageEnabled(true);
        view.getSettings().setAllowFileAccess(false);
        view.getSettings().setAllowContentAccess(false);
        view.getSettings().setMixedContentMode(android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        view.getSettings().setSafeBrowsingEnabled(true);
    }
    WebView testWebView() { return web; }
    private String api(String action, String payload) { return Python.getInstance().getModule("valbot.mobile").callAttr("dispatch", action, payload).toString(); }
    private void deliver(String id, String json) {
        runOnUiThread(() -> web.evaluateJavascript("window.nativeResult(" + JSONObject.quote(id) + "," + JSONObject.quote(json) + ")", null));
    }
    public class Bridge {
        @JavascriptInterface public void request(String id, String action, String payload) {
            if (id.length() > 64 || payload.length() > 12000 || !Arrays.asList("status","command","daily","region","logout").contains(action)) return;
            executor.execute(() -> {
                try {
                    String result = api(action, payload);
                    if (!action.equals("logout")) syncBrowserCookies();
                    if (action.equals("logout")) runOnUiThread(() -> {
                        CookieManager.getInstance().removeAllCookies(null); CookieManager.getInstance().flush();
                        getSharedPreferences("settings", MODE_PRIVATE).edit().putBoolean("daily", false).apply();
                        DailyWorker.schedule(MainActivity.this, false);
                    });
                    deliver(id, result);
                }
                catch (Exception exception) { deliver(id, "{\"ok\":false,\"error\":\"App 無法完成操作，請重新開啟後再試。\"}"); }
            });
        }
        @JavascriptInterface public void login(String selectedRegion) {
            if (!Arrays.asList("ap","na","eu","kr","br","latam").contains(selectedRegion)) return;
            runOnUiThread(() -> openLogin(selectedRegion));
        }
        @JavascriptInterface public void dailyReminder(boolean enabled) {
            runOnUiThread(() -> {
                getSharedPreferences("settings", MODE_PRIVATE).edit().putBoolean("daily", enabled).apply();
                if (enabled && Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 7);
                DailyWorker.schedule(MainActivity.this, enabled);
            });
        }
        @JavascriptInterface public boolean reminderEnabled() { return getSharedPreferences("settings", MODE_PRIVATE).getBoolean("daily", false); }
    }
    private void syncBrowserCookies() {
        try {
            JSONArray cookies = new JSONArray(Python.getInstance().getModule("valbot.mobile").callAttr("browser_cookies").toString());
            runOnUiThread(() -> {
                for (int i=0; i<cookies.length(); i++) {
                    JSONObject cookie = cookies.optJSONObject(i);
                    if (cookie == null) continue;
                    String name = cookie.optString("name"), value = cookie.optString("value");
                    if (!name.matches("[A-Za-z0-9_-]+") || value.contains(";") || value.contains("\r") || value.contains("\n")) continue;
                    CookieManager.getInstance().setCookie("https://auth.riotgames.com/", name + "=" + value + "; Path=/; Secure; HttpOnly");
                }
                CookieManager.getInstance().flush();
            });
        } catch (Exception ignored) { }
    }
    private void openLogin(String selectedRegion) {
        if (loginDialog != null && loginDialog.isShowing()) return;
        region = selectedRegion;
        importing = false;
        loginDialog = new Dialog(this, android.R.style.Theme_Material_NoActionBar);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(11,18,32));
        LinearLayout toolbar = new LinearLayout(this);
        Button close = new Button(this); close.setText("返回 App"); close.setOnClickListener(v -> loginDialog.dismiss());
        TextView origin = new TextView(this); origin.setTextColor(Color.WHITE); origin.setText("Riot 安全登入");
        toolbar.addView(close); toolbar.addView(origin, new LinearLayout.LayoutParams(0, -2, 1)); root.addView(toolbar);
        loginView = new WebView(this); configure(loginView);
        loginView.setWebChromeClient(new WebChromeClient());
        // This WebView has NO JavascriptInterface. Password/2FA stay on Riot's page.
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(loginView, true);
        loginView.setWebViewClient(new WebViewClient() {
            private boolean callback(String url) {
                Uri uri = Uri.parse(url);
                String host = uri.getHost();
                boolean trusted = "https".equals(uri.getScheme()) && ("playvalorant.com".equals(host) || "www.playvalorant.com".equals(host) || "auth.riotgames.com".equals(host));
                if (trusted && url.contains("access_token=")) {
                    importLogin(url); return true;
                }
                return false;
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                return callback(url) || !"https".equals(request.getUrl().getScheme());
            }
            @Override public void onPageFinished(WebView view, String url) {
                origin.setText(Uri.parse(url).getHost()); CookieManager.getInstance().flush(); callback(url);
            }
        });
        root.addView(loginView, new LinearLayout.LayoutParams(-1, 0, 1));
        loginDialog.setContentView(root); loginDialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        loginDialog.setOnDismissListener(dialog -> { loginView.stopLoading(); loginView.destroy(); });
        fitSystemBars(loginDialog.getWindow(), root);
        loginDialog.show(); loginDialog.getWindow().setLayout(-1, -1);
        root.requestApplyInsets();
        loginView.loadUrl(LOGIN + java.util.UUID.randomUUID());
    }
    private void importLogin(String uri) {
        if (importing) return;
        importing = true;
        String cookies = CookieManager.getInstance().getCookie("https://auth.riotgames.com/");
        CookieManager.getInstance().flush();
        executor.execute(() -> {
            try {
                JSONObject payload = new JSONObject(); payload.put("uri", uri); payload.put("cookies", cookies == null ? "" : cookies); payload.put("region", region);
                String result = api("login", payload.toString());
                runOnUiThread(() -> {
                    if (loginDialog.isShowing()) loginDialog.dismiss();
                    web.evaluateJavascript("window.loginResult(" + JSONObject.quote(result) + ")", null);
                    importing = false;
                });
            } catch (Exception exception) { runOnUiThread(() -> { importing = false; if (loginDialog.isShowing()) loginDialog.dismiss(); web.evaluateJavascript("window.loginResult('{\"ok\":false,\"error\":\"登入驗證未完成，請稍後再試\"}')", null); }); }
        });
    }
    @Override public void onBackPressed() { web.evaluateJavascript("window.valoraBack()", null); }
    @Override protected void onDestroy() { if (loginDialog != null && loginDialog.isShowing()) loginDialog.dismiss(); executor.shutdown(); web.destroy(); super.onDestroy(); }
}
