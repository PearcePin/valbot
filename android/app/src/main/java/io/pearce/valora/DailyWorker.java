package io.pearce.valora;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;
import androidx.work.ExistingWorkPolicy;
import androidx.work.Constraints;
import androidx.work.NetworkType;
import com.chaquo.python.Python;
import org.json.JSONObject;
import java.util.Calendar;
import java.util.TimeZone;
import java.util.concurrent.TimeUnit;

public class DailyWorker extends Worker {
    public DailyWorker(Context context, WorkerParameters params) { super(context, params); }
    public static void schedule(Context context, boolean enabled) {
        WorkManager manager = WorkManager.getInstance(context);
        if (!enabled) { manager.cancelUniqueWork("daily-store"); return; }
        Calendar next = Calendar.getInstance(TimeZone.getTimeZone("Asia/Taipei"));
        next.set(Calendar.HOUR_OF_DAY, 8); next.set(Calendar.MINUTE, 5); next.set(Calendar.SECOND, 0); next.set(Calendar.MILLISECOND, 0);
        if (next.getTimeInMillis() <= System.currentTimeMillis()) next.add(Calendar.DATE, 1);
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(DailyWorker.class)
            .setInitialDelay(next.getTimeInMillis() - System.currentTimeMillis(), TimeUnit.MILLISECONDS)
            .setConstraints(new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build();
        manager.enqueueUniqueWork("daily-store", ExistingWorkPolicy.REPLACE, request);
    }
    @Override public Result doWork() {
        Context context = getApplicationContext();
        if (!context.getSharedPreferences("settings", Context.MODE_PRIVATE).getBoolean("daily", false)) return Result.success();
        try {
            JSONObject result = new JSONObject(Python.getInstance().getModule("valbot.mobile").callAttr("dispatch", "daily", "{}").toString());
            String message = result.optBoolean("ok") ? "今日商店、配件、組合包已更新。開啟查看完整圖卡與夜市。" : "Riot 需要驗證或網路暫不可用，開啟 App 查看。";
            NotificationManager notifications = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            notifications.createNotificationChannel(new NotificationChannel("daily", "每日商店", NotificationManager.IMPORTANCE_DEFAULT));
            PendingIntent open = PendingIntent.getActivity(context, 0, new Intent(context, MainActivity.class), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            notifications.notify(805, new Notification.Builder(context, "daily").setSmallIcon(io.pearce.valora.R.drawable.ic_valora)
                .setContentTitle("VALORA · 每日商店").setContentText(message).setStyle(new Notification.BigTextStyle().bigText(message))
                .setContentIntent(open).setAutoCancel(true).build());
        } catch (Exception ignored) { /* Never include private payloads in system logs. */ }
        finally { schedule(context, true); }
        return Result.success();
    }
}
