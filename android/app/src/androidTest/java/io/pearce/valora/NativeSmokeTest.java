package io.pearce.valora;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.core.app.ActivityScenario;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import android.util.Base64;
import com.chaquo.python.Python;
import org.json.JSONObject;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import android.os.Handler;
import android.os.Looper;
import android.view.WindowInsets;
import android.os.Build;
import java.util.concurrent.atomic.AtomicReference;

@RunWith(AndroidJUnit4.class)
public class NativeSmokeTest {
    @Test public void keystoreEncryptsAndDecryptsOnAndroid() throws Exception {
        SecureStore store = new SecureStore();
        String plain = Base64.encodeToString("private mobile session".getBytes("UTF-8"), Base64.NO_WRAP);
        String encrypted = store.encrypt(plain);
        assertNotEquals(plain, encrypted);
        assertEquals(plain, store.decrypt(encrypted));
    }
    @Test public void embeddedGameModulePersistsRegionWithNativeCipher() throws Exception {
        assertTrue(Python.isStarted());
        String raw = Python.getInstance().getModule("valbot.mobile").callAttr("dispatch", "region", "{\"region\":\"ap\"}").toString();
        assertTrue(raw, new JSONObject(raw).getBoolean("ok"));
        JSONObject status = new JSONObject(Python.getInstance().getModule("valbot.mobile").callAttr("dispatch", "status", "{}").toString());
        assertEquals("ap", status.getJSONObject("data").getString("region"));
        assertFalse(status.getJSONObject("data").getBoolean("logged_in"));
    }
    @Test public void webContentStaysBelowStatusBar() throws Exception {
        CountDownLatch measured = new CountDownLatch(1);
        AtomicReference<String> failure = new AtomicReference<>();
        Handler handler = new Handler(Looper.getMainLooper());
        long deadline = System.currentTimeMillis() + 10000;
        try (ActivityScenario<MainActivity> activity = ActivityScenario.launch(MainActivity.class)) {
            activity.onActivity(value -> handler.postDelayed(new Runnable() {
                @Override public void run() {
                    WindowInsets insets = value.getWindow().getDecorView().getRootWindowInsets();
                    if ((insets == null || value.testWebView().getHeight() == 0) && System.currentTimeMillis() < deadline) {
                        handler.postDelayed(this, 100); return;
                    }
                    if (insets == null) failure.set("System bar insets were unavailable");
                    else {
                        int top = Build.VERSION.SDK_INT >= 30
                            ? insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout()).top
                            : insets.getSystemWindowInsetTop();
                        int[] location = new int[2];
                        value.testWebView().getLocationOnScreen(location);
                        if (location[1] < top) failure.set("HTML begins at " + location[1] + " but status bar ends at " + top);
                    }
                    measured.countDown();
                }
            }, 100));
            assertTrue("Layout did not finish", measured.await(12, TimeUnit.SECONDS));
            assertNull(failure.get(), failure.get());
        }
    }
    @Test public void activityCanStartWithoutExternalServer() throws Exception {
        CountDownLatch rendered = new CountDownLatch(1);
        Handler handler = new Handler(Looper.getMainLooper());
        long deadline = System.currentTimeMillis() + 18000;
        try (ActivityScenario<MainActivity> activity = ActivityScenario.launch(MainActivity.class)) {
            activity.onActivity(value -> handler.postDelayed(new Runnable() {
                @Override public void run() {
                    value.testWebView().evaluateJavascript("document.querySelectorAll('.feature').length", count -> {
                        if ("4".equals(count)) rendered.countDown();
                        else if (System.currentTimeMillis() < deadline) handler.postDelayed(this, 500);
                    });
                }
            }, 500));
            assertTrue("Welcome cards did not render in Android WebView", rendered.await(20, TimeUnit.SECONDS));
        }
    }
}
