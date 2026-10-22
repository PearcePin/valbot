package io.pearce.valora;
import android.app.Application;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class ValoraApplication extends Application {
    @Override public void onCreate() {
        super.onCreate();
        if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
        Python.getInstance().getModule("valbot.mobile").callAttr("initialize", getFilesDir().getAbsolutePath() + "/private", new SecureStore());
    }
}
