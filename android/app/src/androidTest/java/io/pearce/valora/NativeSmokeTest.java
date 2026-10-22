package io.pearce.valora;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.core.app.ActivityScenario;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import android.util.Base64;
import com.chaquo.python.Python;
import org.json.JSONObject;

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
    @Test public void activityCanStartWithoutExternalServer() {
        try (ActivityScenario<MainActivity> activity = ActivityScenario.launch(MainActivity.class)) {
            activity.onActivity(value -> assertNotNull(value.findViewById(android.R.id.content)));
        }
    }
}
