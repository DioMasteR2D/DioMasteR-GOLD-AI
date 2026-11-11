package com.diomaster.goldai;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

import org.json.JSONArray;
import org.json.JSONObject;

public final class GoldBackgroundService extends Service {
    private static final String CHANNEL = "diomaster_monitor";
    private static final int FOREGROUND_ID = 7301;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private volatile boolean polling = false;
    private String base = "";
    private String token = "";
    private String symbol = "XAUUSD";
    private boolean initialized = false;
    private PowerManager.WakeLock wakeLock;

    @Override public void onCreate() {
        super.onCreate();
        createChannel();
        startForegroundCompat(buildStatus("DioMasteR ενεργό · σύνδεση MT5 DEMO"));
        PowerManager pm = (PowerManager)getSystemService(POWER_SERVICE);
        if (pm != null) {
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "DioMasteR:GOLDBackgroundMonitor");
            wakeLock.setReferenceCounted(false);
            // Renewed on each poll; timeout prevents an accidental permanent CPU lock.
            wakeLock.acquire(10 * 60 * 1000L);
        }
        SharedPreferences p = getSharedPreferences("diomaster_mt5_demo", MODE_PRIVATE);
        base = p.getString("base", "https://diomaster-gold-ai-metaapi-demo.onrender.com");
        token = p.getString("token", "");
        symbol = p.getString("symbol", "XAUUSD");
        handler.post(pollLoop);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null) {
            if (intent.hasExtra("base")) base = intent.getStringExtra("base");
            if (intent.hasExtra("token")) token = intent.getStringExtra("token");
            if (intent.hasExtra("symbol")) symbol = intent.getStringExtra("symbol");
        }
        renewWakeLock();
        return START_STICKY;
    }

    private final Runnable pollLoop = new Runnable() {
        @Override public void run() {
            if (!polling) {
                polling = true;
                new Thread(() -> pollOnce(), "DioMasteR-background-monitor").start();
            }
            handler.postDelayed(this, 20000L);
        }
    };

    private void renewWakeLock() {\n        try { if (wakeLock != null && !wakeLock.isHeld()) wakeLock.acquire(10 * 60 * 1000L); }\n        catch (Exception ignored) {}\n    }\n\n    private void pollOnce() {
        try {
            if (base == null || base.isEmpty() || token == null || token.trim().isEmpty())
                throw new IllegalStateException("Δεν έχει αποθηκευτεί σύνδεση MT5 DEMO");
            Mt5DemoClient client = new Mt5DemoClient(base, token);
            JSONObject status = client.status();
            if (!"DEMO".equals(status.optString("account_mode")) || !status.optBoolean("terminal_connected"))
                throw new IllegalStateException("MT5 DEMO αποσυνδεδεμένο");
            JSONObject quote = client.quote(symbol);
            double bid = quote.optDouble("bid", 0);
            double ask = quote.optDouble("ask", 0);
            long stamp = (long)(quote.optDouble("time", 0) * 1000L);
            if (!"tickerall_live_websocket_tick".equals(quote.optString("quote_source"))
                    || bid <= 0 || ask < bid || stamp <= 0
                    || System.currentTimeMillis() - stamp > 15000L)
                throw new IllegalStateException("Δεν υπάρχει φρέσκο LIVE tick TickerAll");
            JSONObject positionsResponse = client.positions();
            JSONArray positions = positionsResponse.optJSONArray("positions");
            if (positions == null) positions = new JSONArray();
            JSONObject historyResponse = client.history(symbol, 50);
            JSONArray history = historyResponse.optJSONArray("history");
            if (history == null) history = new JSONArray();
            SharedPreferences prefs = getSharedPreferences("diomaster_background_monitor", MODE_PRIVATE);
            JSONObject previous = null;
            try { previous = new JSONObject(prefs.getString("open_positions", "{}")); } catch (Exception ignored) {}
            JSONObject current = new JSONObject();
            for (int i=0; i<positions.length(); i++) {
                JSONObject p = positions.optJSONObject(i);
                if (p == null) continue;
                String ticket = String.valueOf(p.optLong("ticket"));
                JSONObject meta = new JSONObject();
                meta.put("side", p.optInt("type") == 0 ? "BUY" : "SELL");
                meta.put("symbol", p.optString("symbol", symbol));
                meta.put("sl", p.optDouble("sl", p.optDouble("stopLoss", 0)));
                meta.put("tp", p.optDouble("tp", p.optDouble("takeProfit", 0)));
                meta.put("volume", p.optDouble("volume", 0));
                current.put(ticket, meta);
                if (initialized && (previous == null || !previous.has(ticket))) {
                    notifyEvent("ΝΕΑ ΘΕΣΗ " + meta.optString("side"),
                            meta.optString("symbol") + " · #" + ticket + " · " + meta.optDouble("volume") + " lot");
                }
            }
            if (initialized && previous != null) {
                java.util.Iterator<String> keys = previous.keys();
                while (keys.hasNext()) {
                    String ticket = keys.next();
                    if (current.has(ticket)) continue;
                    JSONObject old = previous.optJSONObject(ticket);
                    JSONObject closed = findHistory(history, ticket);
                    String pnlText = closed == null ? "Η θέση δεν εμφανίζεται πλέον στις ανοιχτές θέσεις." :
                            "Αποτέλεσμα: " + String.format(java.util.Locale.US, "%.2f", closed.optDouble("profit", 0)) + " USD";
                    String reason = "ΚΛΕΙΣΙΜΟ ΘΕΣΗΣ";
                    if (closed != null && old != null) {
                        double closePrice = closed.optDouble("closePrice", closed.optDouble("close_price", 0));
                        double tp = old.optDouble("tp", 0), sl = old.optDouble("sl", 0);
                        if (closePrice > 0 && tp > 0 && Math.abs(closePrice-tp) < 0.03) reason = "TAKE PROFIT";
                        else if (closePrice > 0 && sl > 0 && Math.abs(closePrice-sl) < 0.03) reason = "STOP LOSS";
                    }
                    notifyEvent(reason, old == null ? "#" + ticket + " · " + pnlText :
                            old.optString("side") + " " + old.optString("symbol") + " · #" + ticket + " · " + pnlText);
                }
            }
            prefs.edit().putString("open_positions", current.toString()).apply();
            initialized = true;
            getSharedPreferences("diomaster_background_monitor", MODE_PRIVATE).edit().putBoolean("offline", false).apply();
            updateForeground("Συνδεδεμένο · " + symbol + " · " + positions.length() + " ανοιχτές θέσεις · LIVE TickerAll");
            getSharedPreferences("diomaster_mt5_demo", MODE_PRIVATE).edit()
                    .putString("status", "DEMO · TickerAll LIVE").apply();
        } catch (Exception e) {
            String msg = e.getMessage() == null ? "Σφάλμα σύνδεσης" : e.getMessage();
            updateForeground("ΠΡΟΒΛΗΜΑ ΣΥΝΔΕΣΗΣ · " + msg);
            SharedPreferences p = getSharedPreferences("diomaster_background_monitor", MODE_PRIVATE);
            boolean wasOffline = p.getBoolean("offline", false);
            if (!wasOffline) notifyEvent("ΣΥΝΔΕΣΗ LOST", msg);
            p.edit().putBoolean("offline", true).apply();
        } finally {
            polling = false;
        }
    }

    private JSONObject findHistory(JSONArray rows, String ticket) {
        for (int i=0; i<rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i);
            if (row != null && ticket.equals(String.valueOf(row.optLong("ticket")))) return row;
        }
        return null;
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel c = new NotificationChannel(CHANNEL, "DioMasteR GOLD AI", NotificationManager.IMPORTANCE_DEFAULT);
            c.setDescription("Σύνδεση MT5 DEMO, TickerAll και ενημερώσεις θέσεων");
            getSystemService(NotificationManager.class).createNotificationChannel(c);
        }
    }

    private Notification buildStatus(String text) {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        return b.setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("DioMasteR GOLD AI")
                .setContentText(text)
                .setContentIntent(pi).setOngoing(true).setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_SERVICE).build();
    }

    private void startForegroundCompat(Notification n) {
        if (Build.VERSION.SDK_INT >= 34)
            startForeground(FOREGROUND_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(FOREGROUND_ID, n);
    }

    private void updateForeground(String text) {
        NotificationManager nm = (NotificationManager)getSystemService(NOTIFICATION_SERVICE);
        nm.notify(FOREGROUND_ID, buildStatus(text));
    }

    private void notifyEvent(String title, String body) {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        b.setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("DioMasteR · " + title)
                .setContentText(body).setStyle(new Notification.BigTextStyle().bigText(body))
                .setAutoCancel(true).setCategory(Notification.CATEGORY_STATUS);
        ((NotificationManager)getSystemService(NOTIFICATION_SERVICE))
                .notify((int)(System.currentTimeMillis() & 0x7fffffff), b.build());
    }

    @Override public void onDestroy() {
        handler.removeCallbacks(pollLoop);
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
