package com.diomaster.goldai;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.Locale;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends Activity {
    private final int BG = 0xFF080A0F;
    private final int PANEL = 0xFF121722;
    private final int GOLD = 0xFFE8B84B;
    private final int MUTED = 0xFFA5ADBA;
    private final int GREEN = 0xFF19E78A;
    private final int RED = 0xFFFF5364;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final GoldPriceClient priceClient = new GoldPriceClient();
    private final ArrayList<Double> chartPrices = new ArrayList<>();
    private JSONArray brokerCandles = new JSONArray();
    private JSONArray mt5OpenPositions = new JSONArray();
    private JSONArray mt5ClosedHistory = new JSONArray();
    private String selectedTimeframe = "M15";
    private boolean brokerChartActive = false;
    private PaperTradingEngine engine;
    private LinearLayout root;
    private ScrollView currentScroll;
    private LinearLayout appShell, bottomNavigation, marketSection, agentSection, tradesSection, positionsSection, historySection, settingsSection;
    private int selectedBottomTab = 0;
    private int homePageEnd = 0, positionsPageStart = 0, positionsPageEnd = 0, historyPageStart = 0, historyPageEnd = 0, settingsPageStart = 0;
    private double price = 0.0;
    private long quoteAt = 0L;
    private boolean fetching = false;
    private boolean pendingRefresh = false;
    private long lastMtfDiagnosticsAt = 0L;
    private boolean activityResumed = false;
    private int fetchSequence = 0;
    private String feedMessage = "Σύνδεση με την τιμή χρυσού…";
    private String mt5Status = "ΜΗ ΣΥΝΔΕΔΕΜΕΝΗ";
    private String mt5BaseUrl = "";
    private String mt5Token = "";
    private String mt5Symbol = "XAUUSD";
    private boolean mt5ExecutionEnabled = false;
    private String mt5Login = "";
    private String mt5Currency = "USD";
    private double mt5Balance = 0.0;
    private double mt5Equity = 0.0;
    private boolean aiEngineStarted = false;
    private boolean autoOrderInFlight = false;
    private long lastAutoSignalBar = 0L;
    private String autoExecutionMessage = "Αυτόματη εκτέλεση DEMO ανενεργή";
    private GoldAiAgent.Signal aiSignal = GoldAiAgent.Signal.waiting("Συλλογή δεδομένων αγοράς…");
    private String multiTimeframeStatus = "ΠΟΛΥΧΡΟΝΙΚΗ ΠΑΡΑΚΟΛΟΥΘΗΣΗ · ΑΝΑΜΟΝΗ";
    private final JSONArray agentActivityLog = new JSONArray();
    private static final String AUDIT_PREFS = "diomaster_ai_audit";
    private static final String AUDIT_EVENTS_KEY = "events";
    private static final int MAX_AUDIT_EVENTS = 300;

    private void restoreAgentActivity() {
        try {
            String saved = getSharedPreferences(AUDIT_PREFS, MODE_PRIVATE).getString(AUDIT_EVENTS_KEY, "[]");
            JSONArray restored = new JSONArray(saved);
            synchronized (agentActivityLog) {
                while (agentActivityLog.length() > 0) agentActivityLog.remove(0);
                int start = Math.max(0, restored.length() - MAX_AUDIT_EVENTS);
                for (int i = start; i < restored.length(); i++) agentActivityLog.put(restored.opt(i));
            }
        } catch (Exception ignored) { }
    }

    private void logAgentActivity(String agent, String action, String reason) {
        try {
            JSONObject event = new JSONObject();
            event.put("at", System.currentTimeMillis());
            event.put("agent", agent);
            event.put("action", action);
            event.put("reason", reason == null ? "" : reason);
            synchronized (agentActivityLog) {
                JSONArray next = new JSONArray();
                next.put(event);
                int keep = Math.min(agentActivityLog.length(), MAX_AUDIT_EVENTS - 1);
                for (int i = 0; i < keep; i++) next.put(agentActivityLog.opt(i));
                while (agentActivityLog.length() > 0) agentActivityLog.remove(0);
                for (int i = 0; i < next.length(); i++) agentActivityLog.put(next.opt(i));
                getSharedPreferences(AUDIT_PREFS, MODE_PRIVATE).edit()
                        .putString(AUDIT_EVENTS_KEY, agentActivityLog.toString()).apply();
            }
        } catch (Exception ignored) { }
    }

    private final Runnable refreshLoop = new Runnable() {
        @Override public void run() {
            if (activityResumed) fetchPrice();
            if (activityResumed) handler.postDelayed(this, 30000L);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        engine = new PaperTradingEngine(this);
        restoreAgentActivity();
        android.content.SharedPreferences mt5Prefs = getSharedPreferences("diomaster_mt5_demo", MODE_PRIVATE);
        mt5BaseUrl = mt5Prefs.getString("base", "https://diomaster-gold-ai-metaapi-demo.onrender.com");
        mt5Token = cleanBridgeToken(mt5Prefs.getString("token", ""));
        mt5Symbol = mt5Prefs.getString("symbol", "XAUUSD");
        lastAutoSignalBar = mt5Prefs.getLong("last_auto_signal_bar", 0L);
        selectedTimeframe = mt5Prefs.getString("timeframe", "M15");
        mt5ExecutionEnabled = mt5Prefs.getBoolean("execution_enabled", false);
        mt5Status = mt5Prefs.getString("status", "ΜΗ ΣΥΝΔΕΔΕΜΕΝΗ");
        mt5Login = mt5Prefs.getString("login", "");
        mt5Currency = mt5Prefs.getString("currency", "USD");
        mt5Balance = Double.longBitsToDouble(mt5Prefs.getLong("balance_bits", Double.doubleToRawLongBits(0.0)));
        mt5Equity = Double.longBitsToDouble(mt5Prefs.getLong("equity_bits", Double.doubleToRawLongBits(0.0)));
        startBackgroundMonitor();
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
                checkSelfPermission("android.permission.POST_NOTIFICATIONS") != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 7302);
        }
        render();
        if (!mt5BaseUrl.isEmpty() && !mt5Token.isEmpty()) autoConnectMt5();
    }


    private void startBackgroundMonitor() {
        if (mt5BaseUrl == null || mt5BaseUrl.isEmpty() || mt5Token == null || mt5Token.isEmpty()) return;
        android.content.Intent monitor = new android.content.Intent(this, GoldBackgroundService.class);
        monitor.putExtra("base", mt5BaseUrl);
        monitor.putExtra("token", mt5Token);
        monitor.putExtra("symbol", mt5Symbol);
        monitor.putExtra("timeframe", selectedTimeframe);
        try {
            if (android.os.Build.VERSION.SDK_INT >= 26) startForegroundService(monitor);
            else startService(monitor);
        } catch (Exception e) {
            logAgentActivity("BACKGROUND MONITOR", "BLOCKED",
                    e.getMessage() == null ? "Δεν ξεκίνησε η υπηρεσία παρασκηνίου" : e.getMessage());
        }
    }

    // Reconnects to the saved DEMO bridge on every app launch; never places orders.
    private void autoConnectMt5() {
        mt5Status = "ΑΥΤΟΜΑΤΗ ΣΥΝΔΕΣΗ DEMO…";
        render();
        new Thread(() -> {
            String message;
            boolean connected = false;
            try {
                JSONObject status = new Mt5DemoClient(mt5BaseUrl, mt5Token).status();
                if (!"DEMO".equals(status.optString("account_mode")) || !status.optBoolean("terminal_connected"))
                    throw new IllegalStateException("Ο server δεν επιβεβαίωσε ενεργό DEMO λογαριασμό.");
                JSONArray allowed = status.optJSONArray("allowed_symbols");
                String symbol = allowed != null && allowed.length() > 0 ? allowed.optString(0, "XAUUSD") : "XAUUSD";
                mt5Symbol = symbol;
                mt5Login=status.optString("account_login",""); mt5Currency=status.optString("currency","USD");
                mt5Balance=status.optDouble("balance",0); mt5Equity=status.optDouble("equity",mt5Balance);
                mt5ExecutionEnabled = status.optBoolean("execution_enabled", false); // server-side DEMO gate is authoritative
                message = "DEMO · " + status.optString("server", "Vantage") + " · #" +
                        status.optString("account_login") + (mt5ExecutionEnabled ? " · DEMO ORDERS ON" : " · READ ONLY");
                connected = true;
                getSharedPreferences("diomaster_mt5_demo", MODE_PRIVATE).edit()
                     .putString("symbol", symbol).putBoolean("execution_enabled", mt5ExecutionEnabled)
                    .putString("login",mt5Login).putString("currency",mt5Currency)
                    .putLong("balance_bits",Double.doubleToRawLongBits(mt5Balance)).putLong("equity_bits",Double.doubleToRawLongBits(mt5Equity))
                    .putString("status", message).apply();
            } catch (Exception e) {
                message = "ΑΥΤΟΜΑΤΗ ΣΥΝΔΕΣΗ: " + (e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
            }
            final String result = message;
            final boolean ok = connected;
            final boolean ordersEnabled = connected && mt5ExecutionEnabled;
            runOnUiThread(() -> {
                mt5Status = result;
                mt5ExecutionEnabled = ordersEnabled;
                render();
                if (ok) { fetchPrice(); loadMt5AccountData(); }
                Toast.makeText(this, result, Toast.LENGTH_LONG).show();
            });
        }).start();
    }

    @Override protected void onResume() {
        super.onResume();
        activityResumed = true;
        handler.removeCallbacks(refreshLoop);
        fetchPrice(true);
        handler.postDelayed(refreshLoop, 30000L);
        if (!mt5BaseUrl.isEmpty() && !mt5Token.isEmpty()
                && (mt5Status == null || !mt5Status.startsWith("DEMO"))) autoConnectMt5();
    }

    @Override protected void onPause() {
        activityResumed = false;
        handler.removeCallbacks(refreshLoop);
        super.onPause();
    }

    @Override protected void onDestroy() {
        activityResumed = false;
        handler.removeCallbacks(refreshLoop);
        super.onDestroy();
    }


    private void startAutoTradingOnLaunch() {
        // Never auto-start trading merely because the APK was opened.
        // Cloud AUTO must be explicitly started by the user.
        new Thread(() -> {
            String result;
            try {
                JSONObject status = new Mt5DemoClient(mt5BaseUrl, mt5Token).autoStatus();
                result = status.optBoolean("running")
                        ? "Cloud AUTO DEMO συνεχίζει ήδη στον server."
                        : "Cloud AUTO παραμένει σταματημένο μέχρι να το ξεκινήσεις.";
            } catch(Exception e) { result = "Cloud AUTO: " + e.getMessage(); }
            final String message = result;
            runOnUiThread(() -> Toast.makeText(this, message, Toast.LENGTH_LONG).show());
        }).start();
    }

    private void fetchPrice() { fetchPrice(false); }

    private void fetchPrice(boolean force) {
        if (!activityResumed && !force) return;
        // Keep one market request in flight. Forced UI refreshes must not spawn overlapping
        // broker requests that can race and leave the feed appearing frozen.
        if (fetching) {
            if (force) pendingRefresh = true;
            return;
        }
        fetching = true;
        pendingRefresh = false;
        final int requestId = ++fetchSequence;
        final String requestTimeframe = selectedTimeframe;
        if (mt5BaseUrl != null && !mt5BaseUrl.isEmpty() && mt5Token != null && !mt5Token.isEmpty()
                && mt5Status != null && mt5Status.startsWith("DEMO")) {
            new Thread(() -> {
                try {
                    Mt5DemoClient client = new Mt5DemoClient(mt5BaseUrl, mt5Token);
                    // Load the selected execution timeframe first, then obtain the freshest broker tick.
                    JSONObject candleData = client.candles(mt5Symbol, requestTimeframe, 48);
                    // Independent strategy feeds: fixed H1 entry timeframe and H4 trend filter.
                    JSONObject strategyH1Data = client.candles(mt5Symbol, "H1", 400);
                    JSONObject strategyH4Data = client.candles(mt5Symbol, "H4", 1200);
                    JSONArray strategyH1 = strategyH1Data.optJSONArray("candles");
                    JSONArray strategyH4 = strategyH4Data.optJSONArray("candles");
                    if (strategyH1 == null || strategyH4 == null)
                        throw new IllegalStateException("Λείπουν τα H1/H4 candles της στρατηγικής.");
                    JSONArray rows = candleData.optJSONArray("candles");
                    if (rows == null || rows.length() < 2)
                        throw new IllegalStateException("Δεν υπάρχουν αρκετά broker OHLC candles.");
                    JSONObject quote = client.quote(mt5Symbol);
                    String quoteSource = quote.optString("quote_source", "");
                    double bid = quote.optDouble("bid", 0);
                    double ask = quote.optDouble("ask", 0);
                    long stamp = (long)(quote.optDouble("time", 0) * 1000L);
                    long quoteAge = System.currentTimeMillis() - stamp;
                    if (!"tickerall_live_websocket_tick".equals(quoteSource))
                        throw new IllegalStateException("Δεν υπάρχει πραγματικό LIVE tick Bid/Ask από τον broker.");
                    if (bid <= 0 || ask < bid || stamp <= 0 || quoteAge < -5000L || quoteAge > 15000L)
                        throw new IllegalStateException("LIVE tick παλιό ή μη έγκυρο (" + Math.max(0, quoteAge/1000L) + "s). Αναμονή νέας τιμής.");
                    double latest = (bid + ask) / 2.0;
                    final JSONArray bars = rows;
                    final JSONArray h1Bars = strategyH1;
                    final JSONArray h4Bars = strategyH4;
                    final String effectiveTimeframe = candleData.optString("effective_timeframe",
                            candleData.optString("timeframe", requestTimeframe));
                    final long receivedAt = stamp;
                    final long fetchElapsed = System.currentTimeMillis() - (stamp - Math.max(0L, quoteAge));
                    runOnUiThread(() -> {
                        if (requestId != fetchSequence) return;
                        fetching = false;
                        if (!activityResumed) return;
                        if (pendingRefresh || !requestTimeframe.equals(selectedTimeframe)) {
                            pendingRefresh = false;
                            handler.post(() -> fetchPrice(true));
                            return;
                        }
                        price = latest; quoteAt = receivedAt;
                        brokerCandles = bars; brokerChartActive = true;
                        chartPrices.clear();
                        for (int i=0;i<bars.length();i++) {
                            JSONObject bar=bars.optJSONObject(i);
                            if(bar!=null && bar.optDouble("close",0)>0) chartPrices.add(bar.optDouble("close"));
                        }
                        feedMessage = "VANTAGE MT5 DEMO · LIVE BID/ASK TICK · " + effectiveTimeframe +
                                ("tickerall_live_ticks".equals(candleData.optString("source")) ? " · LIVE TICK CHART" : "") + " · " +
                                new SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(new Date(receivedAt));
                        aiSignal = GoldAiAgent.analyze(h1Bars, h4Bars, latest);
                        engine.onQuote(latest);
                        // AUTO strategy always uses the original H1 setup; selected chart timeframe is display-only.
                        if (aiEngineStarted) evaluateAutoSignal(h1Bars, h4Bars, receivedAt);
                        render();
                    });
                    // Diagnostic-only MTF scan runs after the selected chart/signal is delivered.
                    // It cannot delay the selected-timeframe analysis or feed the order engine.
                    if (requestTimeframe.equals(selectedTimeframe))
                        runMultiTimeframeDiagnostics(requestId, requestTimeframe, candleData);
                } catch (Exception e) {
                    runOnUiThread(() -> {
                        if (requestId != fetchSequence) return;
                        fetching=false;
                        if (!activityResumed) return;
                        if (pendingRefresh || !requestTimeframe.equals(selectedTimeframe)) {
                            pendingRefresh = false;
                            handler.post(() -> fetchPrice(true));
                            return;
                        }
                        brokerChartActive=false;
                        price=0.0; quoteAt=0L; brokerCandles=new JSONArray(); chartPrices.clear();
                        aiSignal=GoldAiAgent.Signal.waiting("NO LIVE BROKER TICK · "+(e.getMessage()==null?"unknown":e.getMessage()));
                        feedMessage="MT5 DEMO · NO LIVE TICK: "+(e.getMessage()==null?"unknown":e.getMessage());
                        logAgentActivity("MARKET FEED", "BLOCKED", e.getMessage()==null ? "Άγνωστο σφάλμα broker feed" : e.getMessage());
                        render();
                    });
                }
            }).start();
            return;
        }
        new Thread(() -> priceClient.fetch(new GoldPriceClient.Callback() {
            @Override public void onPrice(double value, long receivedAt) {
                runOnUiThread(() -> {
                    if (requestId != fetchSequence) return;
                    fetching = false;
                    if (!activityResumed) return;
                    if (pendingRefresh) {
                        pendingRefresh = false;
                        handler.post(() -> fetchPrice(true));
                        return;
                    }
                    price = value; quoteAt = receivedAt; brokerChartActive=false;
                    brokerCandles = new JSONArray();
                    feedMessage = "Ενδεικτική spot τιμή · όχι broker tick · " +
                            new SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(new Date(receivedAt));
                    chartPrices.add(value); while (chartPrices.size() > 90) chartPrices.remove(0);
                    aiSignal = GoldAiAgent.analyze(chartPrices, value); engine.onQuote(value); render();
                });
            }
            @Override public void onError(String message) {
                runOnUiThread(() -> {
                    if (requestId != fetchSequence) return;
                    fetching=false;
                    if (!activityResumed) return;
                    if (pendingRefresh) {
                        pendingRefresh = false;
                        handler.post(() -> fetchPrice(true));
                        return;
                    }
                    feedMessage="Αδυναμία λήψης τιμής: "+message; render();
                });
            }
        })).start();
    }

    private void runMultiTimeframeDiagnostics(int requestId, String requestTimeframe, JSONObject selectedData) {
        // MTF is diagnostic-only, so avoid repeating its six broker requests on every 30s refresh.
        long now = System.currentTimeMillis();
        if (now - lastMtfDiagnosticsAt < 120000L) return;
        lastMtfDiagnosticsAt = now;
        new Thread(() -> {
            try {
                final String[] scanFrames = {"M1","M5","M15","M30","H1","H4"};
                StringBuilder scan = new StringBuilder("MTF DEMO · ");
                for (String frame : scanFrames) {
                    int lookbackHours = "H4".equals(frame) ? 240 : 48;
                    JSONObject frameData = frame.equalsIgnoreCase(requestTimeframe)
                            ? selectedData : new Mt5DemoClient(mt5BaseUrl, mt5Token)
                                    .candles(mt5Symbol, frame, lookbackHours);
                    JSONArray frameRows = frameData.optJSONArray("candles");
                    ArrayList<Double> framePrices = new ArrayList<>();
                    if (frameRows != null) {
                        for (int k = 0; k < frameRows.length(); k++) {
                            JSONObject bar = frameRows.optJSONObject(k);
                            if (bar != null && bar.optDouble("close", 0) > 0)
                                framePrices.add(bar.optDouble("close"));
                        }
                    }
                    GoldAiAgent.Signal frameSignal = GoldAiAgent.analyze(framePrices,
                            framePrices.isEmpty() ? 0 : framePrices.get(framePrices.size()-1));
                    if (scan.length() > 10) scan.append(" | ");
                    scan.append(frame).append(": ").append(frameSignal.side)
                            .append(" ").append(frameSignal.confidence).append("%")
                            .append(" (").append(framePrices.size()).append(" candles)");
                }
                final String result = scan.toString();
                runOnUiThread(() -> {
                    if (requestId != fetchSequence || !activityResumed
                            || !requestTimeframe.equals(selectedTimeframe)) return;
                    multiTimeframeStatus = result;
                    logAgentActivity("MULTI-TIMEFRAME", "SCAN", result);
                    render();
                });
            } catch (Exception e) {
                logAgentActivity("MULTI-TIMEFRAME", "DIAGNOSTIC_DELAYED",
                        e.getMessage() == null ? "MTF diagnostic unavailable" : e.getMessage());
            }
        }).start();
    }

    private boolean quoteFresh() {
        long age = System.currentTimeMillis() - quoteAt;
        return price > 0 && quoteAt > 0 && age >= -5000L && age <= 15000L;
    }

    private void openTrade(String side) {
        if (mt5ExecutionEnabled && !mt5BaseUrl.isEmpty() && !mt5Token.isEmpty()) {
            String action = "BUY".equals(side) ? "ΑΓΟΡΑ" : "ΠΩΛΗΣΗ";
            new AlertDialog.Builder(this)
                .setTitle("Vantage MT5 DEMO · " + action)
                .setMessage("Θα σταλεί εντολή 0.01 lot με Stop Loss $8 και Take Profit $16. Η εντολή θα σταλεί μόνο αν ο server επιβεβαιώσει ξανά ότι ο λογαριασμός είναι DEMO. Συνέχεια;")
                .setNegativeButton("Ακύρωση", null)
                .setPositiveButton("Επιβεβαίωση", (d,w) -> openMt5Trade(side))
                .show();
            return;
        }
        if (!quoteFresh()) {
            Toast.makeText(this, "Δεν υπάρχει φρέσκια τιμή XAU. Οι νέες συναλλαγές μπλοκαρίστηκαν.", Toast.LENGTH_LONG).show();
            fetchPrice();
            return;
        }
        PaperTradingEngine.Result result = engine.open(side, price, quoteAt);
        Toast.makeText(this, result.message, Toast.LENGTH_LONG).show();
        render();
    }


    private void openMt5Trade(String side) {
        if (mt5BaseUrl.isEmpty() || mt5Token.isEmpty()) { Toast.makeText(this, "Πρώτα σύνδεσε το MT5 Demo.", Toast.LENGTH_LONG).show(); return; }
        Toast.makeText(this, "Αποστολή εντολής στο Vantage MT5 DEMO…", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            String message;
            try {
                Mt5DemoClient client = new Mt5DemoClient(mt5BaseUrl, mt5Token);
                JSONObject status = client.status();
                if (!"DEMO".equals(status.optString("account_mode")) || !status.optBoolean("terminal_connected") || !status.optBoolean("execution_enabled")) throw new IllegalStateException("Το MT5 δεν επιβεβαιώνει ενεργό DEMO execution.");
                JSONArray symbols = status.optJSONArray("allowed_symbols");
                if (symbols != null && symbols.length() > 0) mt5Symbol = symbols.optString(0, mt5Symbol);
                JSONObject q = client.quote(mt5Symbol);
                double bid=q.optDouble("bid"), ask=q.optDouble("ask");
                long tickTime=(long)(q.optDouble("time",0)*1000L);
                long tickAge=System.currentTimeMillis()-tickTime;
                if (!"tickerall_live_websocket_tick".equals(q.optString("quote_source","")))
                    throw new IllegalStateException("Δεν υπάρχει πραγματικό LIVE tick TickerAll. Πιθανή κλειστή αγορά ή feed μη διαθέσιμο.");
                if (bid<=0 || ask<=0 || ask<bid || tickTime<=0 || tickAge < -5000L || tickAge > 15000L)
                    throw new IllegalStateException("Το LIVE tick είναι παλιό ή μη έγκυρο. Δεν αποστέλλεται εντολή.");
                if (!"BUY".equals(side) && !"SELL".equals(side))
                    throw new IllegalStateException("Μη έγκυρη κατεύθυνση εντολής.");
                double entry="BUY".equals(side)?ask:bid;
                double sl="BUY".equals(side)?entry-8.0:entry+8.0;
                double tp="BUY".equals(side)?entry+16.0:entry-16.0;
                JSONObject result=client.manualOrder(mt5Symbol,side,0.01,sl,tp);
                message="VANTAGE DEMO "+side+" · "+mt5Symbol+" · 0.01 lot · order #"+result.optLong("order")+" · "+String.format(Locale.US,"%.2f",result.optDouble("price"));
            } catch(Exception e) { message="Η εντολή δεν εκτελέστηκε: "+e.getMessage(); }
            final String done=message;
            runOnUiThread(() -> { Toast.makeText(this,done,Toast.LENGTH_LONG).show(); render(); });
        }).start();
    }

    private double closeAt(int index) {
        JSONObject b=brokerCandles.optJSONObject(index);
        return b==null?0:b.optDouble("close",0);
    }
    private double calcEma(int period) {
        if(brokerCandles.length()<period) return 0;
        int start=Math.max(0,brokerCandles.length()-period*3);
        double alpha=2.0/(period+1.0), value=closeAt(start);
        for(int i=start+1;i<brokerCandles.length();i++) value=closeAt(i)*alpha+value*(1-alpha);
        return value;
    }
    private double calcRsi14() {
        int n=brokerCandles.length(); if(n<15)return 0;
        double gains=0,losses=0;
        for(int i=n-14;i<n;i++){double d=closeAt(i)-closeAt(i-1);if(d>0)gains+=d;else losses-=d;}
        if(losses==0)return 100;
        double rs=(gains/14.0)/(losses/14.0);return 100.0-(100.0/(1.0+rs));
    }
    private double calcMacd() { return calcEma(12)-calcEma(26); }
    private double calcAtr14() {
        int n=brokerCandles.length();if(n<15)return 0;double sum=0;
        for(int i=n-14;i<n;i++){
            JSONObject b=brokerCandles.optJSONObject(i);double prev=closeAt(i-1);
            if(b==null)continue;
            double high=b.optDouble("high",0),low=b.optDouble("low",0);
            sum+=Math.max(high-low,Math.max(Math.abs(high-prev),Math.abs(low-prev)));
        }
        return sum/14.0;
    }

    private void loadMt5AccountData() {
        if (mt5BaseUrl.isEmpty() || mt5Token.isEmpty() || mt5Status == null || !mt5Status.startsWith("DEMO")) return;
        new Thread(() -> {
            try {
                Mt5DemoClient client=new Mt5DemoClient(mt5BaseUrl,mt5Token);
                JSONObject open=client.positions();
                JSONObject history=client.history(mt5Symbol,50);
                JSONArray openRows=open.optJSONArray("positions");
                JSONArray closedRows=history.optJSONArray("history");
                runOnUiThread(() -> {
                    mt5OpenPositions=openRows==null?new JSONArray():openRows;
                    mt5ClosedHistory=closedRows==null?new JSONArray():closedRows;
                    render();
                });
            } catch(Exception e) {
                runOnUiThread(() -> {
                    feedMessage="MT5 account data: "+(e.getMessage()==null?"unavailable":e.getMessage());
                    render();
                });
            }
        }).start();
    }

    private void showMt5Positions() {
        if (mt5BaseUrl.isEmpty() || mt5Token.isEmpty()) { Toast.makeText(this,"Σύνδεσε πρώτα το MT5 Demo.",Toast.LENGTH_SHORT).show(); return; }
        new Thread(() -> {
            try {
                JSONObject result=new Mt5DemoClient(mt5BaseUrl,mt5Token).positions();
                JSONArray rows=result.optJSONArray("positions");
                ArrayList<JSONObject> positions=new ArrayList<>();
                ArrayList<String> labels=new ArrayList<>();
                if(rows!=null) for(int i=0;i<rows.length();i++) {
                    JSONObject p=rows.optJSONObject(i); if(p==null) continue;
                    positions.add(p);
                    labels.add("#"+p.optLong("ticket")+"  "+p.optString("symbol")+"  "+(p.optInt("type")==0?"BUY":"SELL")+"  "+p.optDouble("volume")+" lot  P/L "+p.optDouble("profit"));
                }
                runOnUiThread(() -> {
                    if(positions.isEmpty()) { new AlertDialog.Builder(this).setTitle("Vantage MT5 DEMO").setMessage("Δεν υπάρχουν ανοιχτές θέσεις.").setPositiveButton("OK",null).show(); return; }
                    new AlertDialog.Builder(this).setTitle("Θέσεις Vantage MT5 DEMO").setItems(labels.toArray(new String[0]),(d,which)->confirmMt5Close(positions.get(which))).setNegativeButton("Κλείσιμο",null).show();
                });
            } catch(Exception e) { runOnUiThread(() -> Toast.makeText(this,"Σφάλμα ανάγνωσης MT5: "+e.getMessage(),Toast.LENGTH_LONG).show()); }
        }).start();
    }

    private void closeAllManualMt5Positions() {
        new Thread(() -> {
            try {
                Mt5DemoClient client = new Mt5DemoClient(mt5BaseUrl, mt5Token);
                JSONObject response = client.positions();
                JSONArray rows = response.optJSONArray("positions");
                java.util.ArrayList<JSONObject> manual = new java.util.ArrayList<>();
                if (rows != null) {
                    for (int i = 0; i < rows.length(); i++) {
                        JSONObject p = rows.optJSONObject(i);
                        if (p != null && p.optString("comment", "").startsWith("DioMasteR MANUAL")) manual.add(p);
                    }
                }
                runOnUiThread(() -> new AlertDialog.Builder(this)
                    .setTitle("Κλείσιμο χειροκίνητων θέσεων")
                    .setMessage("Θα κλείσουν μόνο οι " + manual.size() + " χειροκίνητες θέσεις DioMasteR στο Vantage MT5 DEMO. Οι AUTO θέσεις δεν θα επηρεαστούν.")
                    .setNegativeButton("Ακύρωση", null)
                    .setPositiveButton("Κλείσιμο", (d, w) -> new Thread(() -> {
                        int closedCount = 0;
                        String error = null;
                        for (JSONObject p : manual) {
                            try {
                                JSONObject result = client.close(p.optLong("ticket"));
                                if (result.optBoolean("ok")) closedCount++;
                                else error = "Ο broker δεν επιβεβαίωσε το κλείσιμο #" + p.optLong("ticket");
                            } catch (Exception ex) {
                                error = ex.getMessage();
                                break;
                            }
                        }
                        final int done = closedCount;
                        final String problem = error;
                        try {
                            JSONObject verify = client.positions();
                            JSONArray remain = verify.optJSONArray("positions");
                            int stillManual = 0;
                            if (remain != null) for (int i = 0; i < remain.length(); i++) {
                                JSONObject p = remain.optJSONObject(i);
                                if (p != null && p.optString("comment", "").startsWith("DioMasteR MANUAL")) stillManual++;
                            }
                            final int remaining = stillManual;
                            runOnUiThread(() -> {
                                loadMt5AccountData();
                                String msg = "Έκλεισαν " + done + " χειροκίνητες θέσεις. Παραμένουν " + remaining + ".";
                                if (problem != null) msg += " Σφάλμα: " + problem;
                                Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
                            });
                        } catch (Exception ex) {
                            runOnUiThread(() -> Toast.makeText(this, "Έκλεισαν " + done + " θέσεις, αλλά δεν επιβεβαιώθηκε η ανανέωση: " + ex.getMessage(), Toast.LENGTH_LONG).show());
                        }
                    }).start())
                    .show());
            } catch (Exception ex) {
                runOnUiThread(() -> Toast.makeText(this, "Δεν φορτώθηκαν οι χειροκίνητες θέσεις: " + ex.getMessage(), Toast.LENGTH_LONG).show());
            }
        }).start();
    }

    private void confirmMt5Close(JSONObject position) {
        long ticket=position.optLong("ticket");
        new AlertDialog.Builder(this).setTitle("Κλείσιμο θέσης #"+ticket)
            .setMessage("Θα σταλεί εντολή κλεισίματος στον Vantage MT5 DEMO.")
            .setNegativeButton("Άκυρο",null)
            .setPositiveButton("Κλείσιμο",(d,w)->new Thread(()->{
                String msg;
                try {
                    Mt5DemoClient client=new Mt5DemoClient(mt5BaseUrl,mt5Token);
                    JSONObject r=client.close(ticket);
                    // Verify the ticket disappeared from the broker's open-position list.
                    JSONObject check=client.positions();
                    JSONArray remaining=check.optJSONArray("positions");
                    boolean stillOpen=false;
                    if(remaining!=null) for(int i=0;i<remaining.length();i++){
                        JSONObject p=remaining.optJSONObject(i);
                        if(p!=null && p.optLong("ticket")==ticket){stillOpen=true;break;}
                    }
                    msg=stillOpen ? "Ο broker έλαβε το αίτημα, αλλά η θέση εξακολουθεί να εμφανίζεται ανοικτή. Έλεγξε το MT5." :
                        "Επιβεβαιώθηκε από τον broker: η θέση #"+ticket+" δεν είναι πλέον ανοικτή · deal #"+r.optLong("deal");
                    JSONObject h=client.history(mt5Symbol,50);
                    JSONArray closed=h.optJSONArray("history");
                    JSONArray fresh=closed==null?new JSONArray():closed;
                    runOnUiThread(()->{mt5OpenPositions=remaining==null?new JSONArray():remaining;mt5ClosedHistory=fresh;render();});
                } catch(Exception e) { msg="Δεν επιβεβαιώθηκε το κλείσιμο: "+e.getMessage(); }
                final String done=msg;
                runOnUiThread(()->Toast.makeText(this,done,Toast.LENGTH_LONG).show());
            }).start()).show();
    }

    private void closePosition(int id) {
        if (!quoteFresh()) {
            Toast.makeText(this, "Δεν υπάρχει φρέσκια τιμή. Το κλείσιμο θα γίνει μόλις ανανεωθεί η τιμή.", Toast.LENGTH_LONG).show();
            fetchPrice();
            return;
        }
        PaperTradingEngine.Result result = engine.close(id, price);
        Toast.makeText(this, result.message, Toast.LENGTH_SHORT).show();
        render();
    }

    private void render() {
        final boolean mt5Connected = mt5Status != null && mt5Status.startsWith("DEMO");
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(14), dp(10), dp(14), dp(22));
        root.setBackgroundColor(BG);

        // Keep the existing ScrollView attached to the Activity during data refreshes.
        // Replacing the whole window on every market tick caused visible flashing and lag.
        final boolean firstRender = currentScroll == null;
        final int previousScrollY = firstRender ? 0 : currentScroll.getScrollY();
        final ScrollView scroll;
        if (firstRender) {
            appShell = new LinearLayout(this);
            appShell.setOrientation(LinearLayout.VERTICAL);
            appShell.setBackgroundColor(BG);
            scroll = new ScrollView(this);
            scroll.setFillViewport(true);
            scroll.setBackgroundColor(BG);
            currentScroll = scroll;
            scroll.addView(root);
            appShell.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1f));
            setContentView(appShell);
        } else {
            scroll = currentScroll;
        }

        LinearLayout hero = new LinearLayout(this);
        hero.setOrientation(LinearLayout.HORIZONTAL);
        hero.setGravity(Gravity.CENTER_VERTICAL);
        hero.setPadding(dp(7),dp(7),dp(9),dp(7));
        hero.setBackground(goldShell(0xFF050506,0xFFFFC64A));
        ImageView headerArt = new ImageView(this);
        headerArt.setImageResource(R.drawable.lion_crown_header);
        headerArt.setScaleType(ImageView.ScaleType.FIT_CENTER);
        headerArt.setAdjustViewBounds(true);
        hero.addView(headerArt,new LinearLayout.LayoutParams(dp(126),dp(126)));
        LinearLayout brandText=new LinearLayout(this);
        brandText.setOrientation(LinearLayout.VERTICAL);
        brandText.setGravity(Gravity.CENTER);
        TextView crownMark=text("♛",27,0xFFFFD45A,true);
        crownMark.setGravity(Gravity.CENTER);
        brandText.addView(crownMark);
        TextView brandTitle=text("DioMasteR2D",20,0xFFFFD45A,true);
        brandTitle.setGravity(Gravity.CENTER);
        brandTitle.setLetterSpacing(0.015f);
        brandText.addView(brandTitle);
        TextView goldTitle=text("GOLD AI",30,0xFFFFD45A,true);
        goldTitle.setGravity(Gravity.CENTER);
        brandText.addView(goldTitle);
        TextView terminalTitle=text("TRADING TERMINAL",10,0xFFFFE6A0,true);
        terminalTitle.setGravity(Gravity.CENTER);
        terminalTitle.setLetterSpacing(0.09f);
        brandText.addView(terminalTitle);
        TextView brandSub=text("AI TRADER  ·  MT5 DEMO  ·  XAUUSD",8,0xFFFFD98A,true);
        brandSub.setGravity(Gravity.CENTER);
        brandSub.setPadding(0,dp(4),0,0);
        brandText.addView(brandSub);
        LinearLayout.LayoutParams brandLp=new LinearLayout.LayoutParams(0,-2,1);
        brandLp.leftMargin=dp(2);
        hero.addView(brandText,brandLp);
        LinearLayout heroRight=new LinearLayout(this);
        heroRight.setOrientation(LinearLayout.VERTICAL);
        heroRight.setGravity(Gravity.CENTER);
        boolean liveHeader=quoteFresh();
        TextView statusPill=text(liveHeader?"● LIVE":"OFFLINE",10,liveHeader?0xFF062416:0xFFFFE5A3,true);
        statusPill.setGravity(Gravity.CENTER);
        statusPill.setPadding(dp(10),dp(8),dp(10),dp(8));
        statusPill.setBackground(round(liveHeader?0xFF16E68A:0xFF302515,18,liveHeader?GREEN:GOLD));
        statusPill.setOnClickListener(v -> configureMt5Bridge());
        heroRight.addView(statusPill);
        TextView version=text("v2.0",12,0xFFFFE6A0,true);
        version.setPadding(0,dp(10),0,0);
        heroRight.addView(version);
        hero.addView(heroRight);
        root.addView(hero,new LinearLayout.LayoutParams(-1,dp(150)));
        addSpace(8);

        // Primary navigation is intentionally kept at the bottom of the dashboard.
        addSpace(7);
        LinearLayout statusStrip = new LinearLayout(this);
        statusStrip.setOrientation(LinearLayout.HORIZONTAL);
        statusStrip.setGravity(Gravity.CENTER);
        String[] statusLabels = {"● LIVE", "☁ Render", "✦ AI Agent", "▤ MT5 DEMO"};
        int[] statusColors = {quoteFresh() ? GREEN : RED, 0xFFE8E8EA, aiEngineStarted ? GREEN : GOLD, mt5Connected ? GREEN : RED};
        for (int i=0;i<statusLabels.length;i++) {
            TextView pill = text(statusLabels[i], 9, statusColors[i], true);
            pill.setGravity(Gravity.CENTER);
            pill.setPadding(dp(3), dp(9), dp(3), dp(9));
            pill.setBackground(goldShell(0xFF090909, 0xFF74541B));
            LinearLayout.LayoutParams pl = new LinearLayout.LayoutParams(0, -2, 1);
            pl.setMargins(dp(2), 0, dp(2), 0);
            statusStrip.addView(pill, pl);
        }
        root.addView(statusStrip);
        addSpace(7);

        LinearLayout connection = card();
        GradientDrawable connBg = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{0xFF062B20,0xFF061B18,0xFF092B22});
        connBg.setCornerRadius(dp(18)); connBg.setStroke(dp(2), mt5Status.startsWith("DEMO") ? 0xFF19E78A : 0xFFB98B32);
        connection.setBackground(connBg);
        TextView connTitle = text(mt5Connected ? "✓  ΣΥΝΔΕΣΗ MT5 DEMO: ΕΠΙΒΕΒΑΙΩΜΕΝΗ" : "⚠  MT5 DEMO: ΕΚΤΟΣ ΣΥΝΔΕΣΗΣ",16,mt5Connected?0xFF70F5B4:RED,true);
        connection.addView(connTitle);
        connection.addView(text(mt5Connected ? "MT5 Demo  •  VantageMarkets-Demo  •  XAUUSD" : (mt5Status == null ? "Δεν έχει γίνει σύνδεση" : mt5Status),10,mt5Connected?0xFFE0E8E4:0xFFFFB6A8,false));
        addRow(connection,"Bridge  "+(mt5Connected?"✓":"×"),"Λογαριασμός  "+(mt5Connected?"✓":"—"),mt5Connected?GREEN:RED);
        addRow(connection,"Τιμές  "+(brokerChartActive?"✓":"—"),"Εντολές  "+(mt5ExecutionEnabled?"DEMO ON":"READ ONLY"),brokerChartActive?GREEN:GOLD);
        // Detailed bridge diagnostics remain available in Settings; keep the home screen compact.
        addSpace(5);

        LinearLayout market = card();
        marketSection = market;
        LinearLayout instrument = new LinearLayout(this);
        instrument.setOrientation(LinearLayout.HORIZONTAL);
        instrument.setGravity(Gravity.CENTER_VERTICAL);
        instrument.setPadding(dp(10),dp(9),dp(10),dp(9));
        instrument.setBackground(goldShell(0xFF090909,0xFFFFC83D));
        TextView goldIcon = text("◆",30,GOLD,true);
        goldIcon.setPadding(dp(4),0,dp(10),0);
        instrument.addView(goldIcon);
        LinearLayout instrumentName = new LinearLayout(this);
        instrumentName.setOrientation(LinearLayout.VERTICAL);
        instrumentName.addView(text("XAUUSD",21,Color.WHITE,true));
        instrumentName.addView(text("Gold / US Dollar",11,MUTED,false));
        instrument.addView(instrumentName,new LinearLayout.LayoutParams(0,-2,1));
        TextView priceText = text(price > 0 ? String.format(Locale.US, "%,.2f", price) : "—", 27, GREEN, true);
        priceText.setGravity(Gravity.RIGHT|Gravity.CENTER_VERTICAL);
        instrument.addView(priceText);
        market.addView(instrument);
        TextView feed = text((quoteFresh() ? "● LIVE  " : "● ") + feedMessage, 10, quoteFresh() ? GREEN : RED, false);
        feed.setPadding(dp(4),dp(5),0,dp(7));
        market.addView(feed);
        LinearLayout accountStrip = new LinearLayout(this);
        accountStrip.setOrientation(LinearLayout.HORIZONTAL);
        JSONObject accountSnap = engine.snapshot(quoteFresh() ? price : 0);
        boolean liveAccount = mt5Connected;
        double displayBalance = liveAccount ? mt5Balance : accountSnap.optDouble("equity");
        double displayEquity = liveAccount ? mt5Equity : accountSnap.optDouble("equity") + accountSnap.optDouble("floating");
        double displayPnl = liveAccount ? (mt5Equity - mt5Balance) : accountSnap.optDouble("floating");
        accountStrip.addView(metric("ΥΠΟΛΟΙΠΟ", liveAccount ? money(displayBalance) : PaperTradingEngine.money(displayBalance), GOLD), weight());
        accountStrip.addView(metric("EQUITY", liveAccount ? money(displayEquity) : PaperTradingEngine.money(displayEquity), GOLD), weight());
        accountStrip.addView(metric("P/L", liveAccount ? money(displayPnl) : PaperTradingEngine.money(displayPnl), displayPnl >= 0 ? GREEN : RED), weight());
        market.addView(accountStrip);
        addSpace(5);
        LinearLayout periods = new LinearLayout(this);
        periods.setOrientation(LinearLayout.HORIZONTAL);
        periods.setGravity(Gravity.CENTER);
        String[] frames={"M1","M5","M15","M30","H1","H4"};
        for(String frame:frames) {
            final String tf=frame;
            TextView chip=text(frame,11,selectedTimeframe.equals(frame)?Color.BLACK:0xFFE8E8EA,true);
            chip.setGravity(Gravity.CENTER);
            chip.setMinHeight(dp(48));
            chip.setPadding(dp(8),dp(14),dp(8),dp(14));
            chip.setClickable(true);
            chip.setFocusable(true);
            chip.setBackground(selectedTimeframe.equals(frame)?round(GOLD,9,0xFFFFE18A):round(0xFF171A20,9,0xFF343944));
            chip.setOnClickListener(v->{
                if (!tf.equals(selectedTimeframe)) {
                    selectedTimeframe=tf;
                    getSharedPreferences("diomaster_mt5_demo", MODE_PRIVATE).edit()
                            .putString("timeframe", tf).apply();
                    startBackgroundMonitor();
                    // Update every timeframe chip immediately; do not wait for the broker network response.
                    for (int i=0; i<periods.getChildCount(); i++) {
                        View child=periods.getChildAt(i);
                        if (child instanceof TextView) {
                            TextView item=(TextView)child;
                            boolean active=tf.equals(item.getText().toString());
                            item.setTextColor(active?Color.BLACK:0xFFE8E8EA);
                            item.setBackground(active?round(GOLD,9,0xFFFFE18A):round(0xFF171A20,9,0xFF343944));
                        }
                    }
                    fetchPrice(true);
                }
            });
            periods.addView(chip,new LinearLayout.LayoutParams(0,-2,1));
        }
        market.addView(periods);
        LinearLayout chartLegend=new LinearLayout(this);
        chartLegend.setOrientation(LinearLayout.HORIZONTAL);
        chartLegend.addView(text("● EMA 9",10,0xFF28B8FF,true));
        TextView ema21Legend=text("● EMA 21",10,GOLD,true);
        ema21Legend.setPadding(dp(16),0,0,0); chartLegend.addView(ema21Legend);
        market.addView(chartLegend);
        addSpace(5);
        GoldChartView chart = new GoldChartView(this);
        // Match the reference terminal's tall chart viewport. Empty state stays honest,
        // but keeps the same layout height so indicators and the signal card don't jump.
        chart.setLayoutParams(new LinearLayout.LayoutParams(-1, dp(286)));
        chart.setCandles(brokerChartActive ? brokerCandles : new JSONArray());
        market.addView(chart);
        LinearLayout indicators = new LinearLayout(this);
        indicators.setOrientation(LinearLayout.HORIZONTAL);
        boolean haveOhlc=brokerChartActive && brokerCandles.length()>=26;
        double rsiValue=calcRsi14(), macdValue=calcMacd(), atrValue=calcAtr14();
        double emaFast=calcEma(9), emaSlow=calcEma(21);
        indicators.addView(metric("RSI (14)",haveOhlc?String.format(Locale.US,"%.1f · %s",rsiValue,rsiValue>=70?"Overbought":rsiValue<=30?"Oversold":"Neutral"):"—",GREEN),weight());
        indicators.addView(metric("MACD",haveOhlc?String.format(Locale.US,"%+.2f",macdValue):"—",macdValue>=0?GREEN:RED),weight());
        indicators.addView(metric("ATR (14)",haveOhlc?String.format(Locale.US,"%.2f",atrValue):"—",GOLD),weight());
        indicators.addView(metric("Τάση EMA 9/21",haveOhlc?(emaFast>emaSlow?"Ανοδική":"Καθοδική"):"—",haveOhlc?(emaFast>emaSlow?GREEN:RED):GOLD),weight());
        market.addView(indicators);
        TextView chartNote = text(brokerChartActive ? "Στρατηγική AUTO: H1 EMA 9 / 21 · H4 EMA 50." : "Αναμονή πραγματικών MT5 OHLC candles · δεν εμφανίζονται κατασκευασμένα δεδομένα.", 9, MUTED, false);
        chartNote.setPadding(0, dp(5), 0, 0);
        market.addView(chartNote);
        root.addView(market);
        addSpace(10);

        LinearLayout aiPanels = new LinearLayout(this);
        aiPanels.setOrientation(LinearLayout.VERTICAL);
        aiPanels.setGravity(Gravity.TOP);
        LinearLayout agent = card();
        agentSection = agent;
        agent.setPadding(dp(16),dp(15),dp(16),dp(15));
        addLabel(agent, "✦  D I O M A S T E R   A I   S I G N A L");
        int signalColor = "BUY".equals(aiSignal.side) ? GREEN : "SELL".equals(aiSignal.side) ? RED : GOLD;
        String signalTitle = "BUY".equals(aiSignal.side) ? "▲ BUY" : "SELL".equals(aiSignal.side) ? "▼ SELL" : "Ⅱ HOLD";
        LinearLayout signalHead = new LinearLayout(this);
        signalHead.setOrientation(LinearLayout.HORIZONTAL);
        signalHead.setGravity(Gravity.CENTER_VERTICAL);
        TextView signal = text(signalTitle, 30, signalColor, true);
        signal.setGravity(Gravity.CENTER);
        signal.setPadding(dp(20), dp(8), dp(20), dp(8));
        signal.setBackground(round("BUY".equals(aiSignal.side) ? 0xFF063B20 : "SELL".equals(aiSignal.side) ? 0xFF410D14 : 0xFF25200F, 18, signalColor));
        signalHead.addView(signal);
        LinearLayout confidenceBox = new LinearLayout(this);
        confidenceBox.setOrientation(LinearLayout.VERTICAL);
        confidenceBox.setGravity(Gravity.RIGHT|Gravity.CENTER_VERTICAL);
        TextView confidenceLabel=text("ΕΜΠΙΣΤΟΣΥΝΗ AI",9,MUTED,true);
        confidenceLabel.setGravity(Gravity.RIGHT);
        confidenceBox.addView(confidenceLabel);
        TextView confidence = text(aiSignal.ready ? aiSignal.confidence + "%" : "—", 22, signalColor, true);
        confidence.setGravity(Gravity.RIGHT);
        confidenceBox.addView(confidence);
        signalHead.addView(confidenceBox,new LinearLayout.LayoutParams(0,-2,1));
        agent.addView(signalHead);
        TextView reason = text(aiSignal.reason, 12, 0xFFE2E4E8, false);
        reason.setPadding(0,dp(10),0,dp(8));
        agent.addView(reason);
        LinearLayout signalLevels = new LinearLayout(this);
        signalLevels.setOrientation(LinearLayout.HORIZONTAL);
        boolean showLevels=aiSignal.ready && ("BUY".equals(aiSignal.side) || "SELL".equals(aiSignal.side))
                && aiSignal.entry>0 && aiSignal.stopLoss>0 && aiSignal.takeProfit>0;
        signalLevels.addView(metric("ENTRY",showLevels?String.format(Locale.US,"%,.2f",aiSignal.entry):"—",0xFF75C9FF),weight());
        signalLevels.addView(metric("STOP LOSS",showLevels?String.format(Locale.US,"%,.2f",aiSignal.stopLoss):"—",RED),weight());
        signalLevels.addView(metric("TAKE PROFIT",showLevels?String.format(Locale.US,"%,.2f",aiSignal.takeProfit):"—",GREEN),weight());
        agent.addView(signalLevels);
        LinearLayout evaluation = new LinearLayout(this);
        evaluation.setOrientation(LinearLayout.HORIZONTAL);
        evaluation.addView(metric("LIVE TICK",quoteFresh()?"OK":"WAIT",quoteFresh()?GREEN:RED),weight());
        evaluation.addView(metric("MT5 OHLC",brokerChartActive?String.valueOf(brokerCandles.length()):"—",brokerChartActive?GREEN:GOLD),weight());
        evaluation.addView(metric("AI ENGINE",aiEngineStarted?"ON":"OFF",aiEngineStarted?GREEN:GOLD),weight());
        agent.addView(evaluation);
        aiPanels.addView(agent,new LinearLayout.LayoutParams(-1,-2));
        root.addView(aiPanels);
        addSpace(8);

        LinearLayout quickActions = new LinearLayout(this);
        quickActions.setOrientation(LinearLayout.HORIZONTAL);
        Button autoTrade = actionButton(aiEngineStarted ? "Ⅱ  STOP AUTO · DEMO" : "▶  START AUTO · DEMO", GREEN, this::startAiEngine);
        autoTrade.setLayoutParams(new LinearLayout.LayoutParams(0,-2,1));
        Button analysis = actionButton("⌁  ΑΝΑΛΥΣΗ", GOLD, () -> scrollToSection(marketSection));
        analysis.setLayoutParams(new LinearLayout.LayoutParams(0,-2,1));
        quickActions.addView(autoTrade); quickActions.addView(analysis);
        root.addView(quickActions);
        addSpace(10);

        // Premium home-screen account strip: live broker figures when connected,
        // otherwise clearly labelled PAPER figures from the local simulator.
        JSONObject homeSnap = engine.snapshot(quoteFresh() ? price : 0);
        boolean useBrokerAccount = mt5Connected;
        double homeBalance = useBrokerAccount ? mt5Balance : homeSnap.optDouble("equity");
        double homeEquity = useBrokerAccount ? mt5Equity : homeSnap.optDouble("equity") + homeSnap.optDouble("floating");
        double homePnl = useBrokerAccount ? (mt5Equity - mt5Balance) : homeSnap.optDouble("floating");
        double homePct = homeBalance > 0 ? (homePnl / homeBalance) * 100.0 : 0.0;
        LinearLayout accountTiles = new LinearLayout(this);
        accountTiles.setOrientation(LinearLayout.HORIZONTAL);
        accountTiles.addView(metric(useBrokerAccount ? "MT5 BALANCE" : "PAPER BALANCE", useBrokerAccount ? money(homeBalance) : PaperTradingEngine.money(homeBalance), GOLD),weight());
        accountTiles.addView(metric("EQUITY", useBrokerAccount ? money(homeEquity) : PaperTradingEngine.money(homeEquity), GOLD),weight());
        accountTiles.addView(metric("P/L", useBrokerAccount ? money(homePnl) : PaperTradingEngine.money(homePnl), homePnl >= 0 ? GREEN : RED),weight());
        accountTiles.addView(metric("P/L %", String.format(Locale.US,"%+.2f%%",homePct), homePct >= 0 ? GREEN : RED),weight());
        root.addView(accountTiles);
        addSpace(10);

        LinearLayout overviewRow = new LinearLayout(this);
        overviewRow.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout homePositions = card();
        homePositions.setPadding(dp(12),dp(13),dp(12),dp(13));
        addLabel(homePositions,"▣  ΑΝΟΙΧΤΕΣ ΘΕΣΕΙΣ");
        JSONArray homeOpen = useBrokerAccount ? mt5OpenPositions : homeSnap.optJSONArray("positions");
        if (homeOpen == null || homeOpen.length() == 0) {
            homePositions.addView(text("Δεν υπάρχουν ανοιχτές θέσεις.",11,MUTED,false));
        } else {
            for (int n=0; n<Math.min(3,homeOpen.length()); n++) {
                JSONObject pos=homeOpen.optJSONObject(n); if(pos==null) continue;
                String side=pos.optString("side",pos.optInt("type")==0?"BUY":"SELL");
                double pnl=pos.optDouble("profit",0);
                String symbol=pos.optString("symbol",mt5Symbol);
                String size=useBrokerAccount?String.format(Locale.US,"%.2f lot",pos.optDouble("volume")):String.format(Locale.US,"%.2f oz",pos.optDouble("oz"));
                addRow(homePositions,symbol+"  "+side+"  "+size,
                        useBrokerAccount?PaperTradingEngine.money(pnl):PaperTradingEngine.money(pnl),pnl>=0?GREEN:RED);
            }
        }
        LinearLayout homeStats = card();
        homeStats.setPadding(dp(12),dp(13),dp(12),dp(13));
        JSONArray homeClosed = useBrokerAccount ? mt5ClosedHistory : homeSnap.optJSONArray("history");
        if(homeClosed==null) homeClosed=new JSONArray();
        addLabel(homeStats,useBrokerAccount ? "▥  ΣΤΑΤΙΣΤΙΚΑ MT5 DEMO" : "▥  ΣΤΑΤΙΣΤΙΚΑ PAPER");
        int homeWins=0,homeLosses=0; double homeNet=0;
        for(int n=0;n<homeClosed.length();n++){
            JSONObject tr=homeClosed.optJSONObject(n); if(tr==null) continue;
            double result=tr.optDouble(useBrokerAccount ? "profit" : "pnl",0.0);
            homeNet+=result;
            if(result>0) homeWins++; else if(result<0) homeLosses++;
        }
        int homeTrades=homeWins+homeLosses;
        String homeWinRate=homeTrades>0?String.format(Locale.US,"%.1f%%",100.0*homeWins/homeTrades):"—";
        addRow(homeStats,"Κλεισμένες",String.valueOf(homeTrades));
        addRow(homeStats,"Κερδισμένες",String.valueOf(homeWins),GREEN);
        addRow(homeStats,"Χαμένες",String.valueOf(homeLosses),RED);
        addRow(homeStats,"Win Rate",homeWinRate,GOLD);
        addRow(homeStats,"Καθαρό P/L",PaperTradingEngine.money(homeNet),homeNet>=0?GREEN:RED);
        if(useBrokerAccount && homeTrades==0) homeStats.addView(text("Δεν έχουν επιστραφεί κλεισμένες συναλλαγές MT5 ακόμη. Οι ανοιχτές θέσεις δεν υπολογίζονται.",9,MUTED,false));
        LinearLayout.LayoutParams overviewHalf=new LinearLayout.LayoutParams(0,-2,1);
        overviewHalf.setMargins(dp(2),0,dp(4),0);
        overviewRow.addView(homePositions,overviewHalf);
        LinearLayout.LayoutParams overviewHalf2=new LinearLayout.LayoutParams(0,-2,1);
        overviewHalf2.setMargins(dp(4),0,dp(2),0);
        overviewRow.addView(homeStats,overviewHalf2);
        root.addView(overviewRow);
        addSpace(10);
        homePageEnd = root.getChildCount();

        positionsPageStart = root.getChildCount();
        JSONObject snap = engine.snapshot(quoteFresh() ? price : 0);
        LinearLayout metrics = new LinearLayout(this);
        metrics.setOrientation(LinearLayout.VERTICAL);
        LinearLayout metricsTop = new LinearLayout(this);
        metricsTop.setOrientation(LinearLayout.HORIZONTAL);
        metricsTop.addView(metric("PAPER ΚΕΦΑΛΑΙΟ", PaperTradingEngine.money(snap.optDouble("equity")), GOLD), weight());
        metricsTop.addView(metric("ΑΝΟΙΧΤΟ P/L", PaperTradingEngine.money(snap.optDouble("floating")), snap.optDouble("floating") >= 0 ? GREEN : RED), weight());
        LinearLayout metricsBottom = new LinearLayout(this);
        metricsBottom.setOrientation(LinearLayout.HORIZONTAL);
        metricsBottom.addView(metric("ΚΛΕΙΣΜΕΝΟ P/L", PaperTradingEngine.money(snap.optDouble("daily")), snap.optDouble("daily") >= 0 ? GREEN : RED), weight());
        metricsBottom.addView(metric("ΑΝΟΙΧΤΕΣ ΘΕΣΕΙΣ", snap.optJSONArray("positions").length() + " / 10", GOLD), weight());
        metrics.addView(metricsTop);
        addSpace(4);
        metrics.addView(metricsBottom);
        root.addView(metrics);
        addSpace(10);

        LinearLayout risk = card();
        addLabel(risk, "♢  ΔΙΑΧΕΙΡΙΣΗ ΚΙΝΔΥΝΟΥ (AUTO)  ·  PAPER");
        LinearLayout riskRow1=new LinearLayout(this); riskRow1.setOrientation(LinearLayout.HORIZONTAL);
        riskRow1.addView(metric("Ρίσκο / θέση","0.5%",GOLD),weight());
        riskRow1.addView(metric("Stop Loss","$8",RED),weight());
        riskRow1.addView(metric("Take Profit","$16",GREEN),weight());
        risk.addView(riskRow1);
        LinearLayout riskRow2=new LinearLayout(this); riskRow2.setOrientation(LinearLayout.HORIZONTAL);
        riskRow2.addView(metric("Μέγ. μέγεθος","5.0 oz",GOLD),weight());
        riskRow2.addView(metric("Ημερ. όριο","$200",GOLD),weight());
        riskRow2.addView(metric("Μέγ. ημερήσια ζημιά","5%",RED),weight());
        risk.addView(riskRow2);

        addRow(risk,"Νέες PAPER συναλλαγές",snap.optBoolean("paused")?"ΣΕ ΠΑΥΣΗ":"ΕΝΕΡΓΕΣ");
        TextView riskNote = text("Κάθε νέα εικονική συναλλαγή περνά από τον ίδιο αυτόματο έλεγχο κινδύνου. Παλιές ή ανύπαρκτες τιμές μπλοκάρουν τις νέες εισόδους.", 10, MUTED, false);
        riskNote.setPadding(0, dp(8), 0, 0);
        risk.addView(riskNote);
        root.addView(risk);
        addSpace(10);

        LinearLayout actions = card();
        tradesSection = actions;
        addLabel(actions, mt5ExecutionEnabled ? "VANTAGE MT5 DEMO · ΧΕΙΡΟΚΙΝΗΤΕΣ ΕΝΤΟΛΕΣ" : "PAPER TRADING · ΕΙΚΟΝΙΚΕΣ ΣΥΝΑΛΛΑΓΕΣ");
        LinearLayout actionRow = new LinearLayout(this);
        actionRow.setOrientation(LinearLayout.HORIZONTAL);
        actionRow.addView(actionButton("BUY", GREEN, () -> openTrade("BUY")), weight());
        actionRow.addView(actionButton("SELL", RED, () -> openTrade("SELL")), weight());
        actions.addView(actionRow);
        Button mt5Open = actionButton("ΠΡΟΒΟΛΗ ΑΝΟΙΧΤΩΝ ΘΕΣΕΩΝ VANTAGE DEMO", 0xFF292C34, this::showMt5Positions);
        actions.addView(mt5Open);
        Button closeAll = actionButton("ΚΛΕΙΣΙΜΟ ΟΛΩΝ ΤΩΝ PAPER ΘΕΣΕΩΝ", 0xFF343943, () -> {
            if (!quoteFresh()) { Toast.makeText(this, "Waiting for fresh quote.", Toast.LENGTH_SHORT).show(); fetchPrice(); return; }
            new AlertDialog.Builder(this).setTitle("Να κλείσουν όλες οι εικονικές θέσεις;")
                    .setMessage("Όλες οι ανοιχτές εικονικές θέσεις θα κλείσουν στην τρέχουσα ενδεικτική τιμή.")
                    .setNegativeButton("Ακύρωση", null)
                    .setPositiveButton("Κλείσιμο όλων", (d, w) -> { engine.closeAll(price); render(); })
                    .show();
        });
        actions.addView(closeAll);
        Button pause = actionButton(snap.optBoolean("paused") ? "ΕΠΑΝΕΝΕΡΓΟΠΟΙΗΣΗ ΝΕΩΝ ΕΙΣΟΔΩΝ" : "ΠΑΥΣΗ ΝΕΩΝ ΕΙΣΟΔΩΝ", 0xFF292C34,
                () -> { engine.setPaused(!engine.snapshot(quoteFresh() ? price : 0).optBoolean("paused")); render(); });
        actions.addView(pause);
        root.addView(actions);
        addSpace(10);

        LinearLayout positions = card();
        positionsSection = positions;
        addLabel(positions, "PAPER ΘΕΣΕΙΣ · ΤΟ MT5 ΕΜΦΑΝΙΖΕΤΑΙ ΣΤΗΝ ΞΕΧΩΡΙΣΤΗ ΛΙΣΤΑ");
        JSONArray open = snap.optJSONArray("positions");
        if (open == null || open.length() == 0) positions.addView(text("Δεν υπάρχουν ανοιχτές εικονικές θέσεις.", 12, MUTED, false));
        else {
            for (int i = 0; i < open.length(); i++) {
                JSONObject p = open.optJSONObject(i);
                if (p == null) continue;
                int id = p.optInt("id");
                String side = p.optString("side");
                double pnl = quoteFresh() ? ("BUY".equals(side) ? price - p.optDouble("entry") : p.optDouble("entry") - price) * p.optDouble("oz") : 0;
                LinearLayout row = new LinearLayout(this);
                row.setGravity(Gravity.CENTER_VERTICAL);
                row.setPadding(0, dp(8), 0, dp(8));
                row.setOrientation(LinearLayout.HORIZONTAL);
                LinearLayout details = new LinearLayout(this);
                details.setOrientation(LinearLayout.VERTICAL);
                details.addView(text("#" + id + "  " + side + "  ·  " + String.format(Locale.US, "%.1f", p.optDouble("oz")) + " oz", 13, "BUY".equals(side) ? GREEN : RED, true));
                details.addView(text("Είσοδος " + money(p.optDouble("entry")) + "   SL " + money(p.optDouble("sl")) + "   TP " + money(p.optDouble("tp")), 10, MUTED, false));
                details.addView(text("Μη πραγματοποιημένο P/L " + PaperTradingEngine.money(pnl), 11, pnl >= 0 ? GREEN : RED, true));
                row.addView(details, new LinearLayout.LayoutParams(0, -2, 1));
                Button closeButton = actionButton("ΚΛΕΙΣΙΜΟ", 0xFF343943, () -> closePosition(id));
                closeButton.setLayoutParams(new LinearLayout.LayoutParams(-2, -2));
                row.addView(closeButton);
                positions.addView(row);
                if (i < open.length() - 1) addDivider(positions);
            }
        }
        if (mt5Status != null && mt5Status.startsWith("DEMO")) {
            addDivider(positions);
            addLabel(positions,"VANTAGE MT5 DEMO · ΑΝΟΙΧΤΕΣ ΘΕΣΕΙΣ");
            if(mt5OpenPositions.length()==0) positions.addView(text("Ο broker δεν αναφέρει ανοιχτές θέσεις.",11,MUTED,false));
            for(int i=0;i<Math.min(10,mt5OpenPositions.length());i++) {
                JSONObject p=mt5OpenPositions.optJSONObject(i); if(p==null) continue;
                String side=p.optString("side",p.optInt("type")==0?"BUY":"SELL");
                double pnl=p.optDouble("profit",0);
                addRow(positions,"#"+p.optString("ticket")+"  "+p.optString("symbol")+"  "+side+"  "+p.optDouble("volume")+" lot",
                        PaperTradingEngine.money(pnl),pnl>=0?GREEN:RED);
            }
            Button closeManual=actionButton("ΚΛΕΙΣΙΜΟ ΟΛΩΝ ΤΩΝ ΧΕΙΡΟΚΙΝΗΤΩΝ MT5",0xFF8A3434,this::closeAllManualMt5Positions);
            positions.addView(closeManual);
            Button reloadPositions=actionButton("↻ ΑΝΑΝΕΩΣΗ MT5 ΘΕΣΕΩΝ",0xFF292C34,this::loadMt5AccountData);
            positions.addView(reloadPositions);
        }
        root.addView(positions);
        addSpace(10);
        positionsPageEnd = root.getChildCount();

        historyPageStart = root.getChildCount();
        LinearLayout history = card();
        historySection = history;
        addLabel(history, "ΙΣΤΟΡΙΚΟ PAPER · ΑΠΟΔΟΣΗ");
        JSONArray closed = snap.optJSONArray("history");
        if (closed == null) closed = new JSONArray();
        int winCount = 0, lossCount = 0;
        double netClosedPnl = 0.0;
        for (int k = 0; k < closed.length(); k++) {
            JSONObject trade = closed.optJSONObject(k);
            if (trade == null) continue;
            double result = trade.optDouble("pnl", 0.0);
            netClosedPnl += result;
            if (result > 0) winCount++;
            else if (result < 0) lossCount++;
        }
        LinearLayout historyStatsTop = new LinearLayout(this);
        historyStatsTop.setOrientation(LinearLayout.HORIZONTAL);
        historyStatsTop.addView(metric("ΚΛΕΙΣΜΕΝΕΣ", String.valueOf(closed.length()), GOLD), weight());
        historyStatsTop.addView(metric("WIN / LOSS", winCount + " / " + lossCount, winCount >= lossCount ? GREEN : RED), weight());
        history.addView(historyStatsTop);
        addSpace(5);
        LinearLayout historyStatsBottom = new LinearLayout(this);
        historyStatsBottom.setOrientation(LinearLayout.HORIZONTAL);
        historyStatsBottom.addView(metric("NET PAPER P/L", PaperTradingEngine.money(netClosedPnl), netClosedPnl >= 0 ? GREEN : RED), weight());
        String winRate = (winCount + lossCount) > 0 ? String.format(Locale.US, "%.1f%%", 100.0 * winCount / (winCount + lossCount)) : "—";
        historyStatsBottom.addView(metric("WIN RATE", winRate, GOLD), weight());
        history.addView(historyStatsBottom);
        addSpace(8);
        addLabel(history, "ΠΡΟΣΦΑΤΕΣ PAPER ΣΥΝΑΛΛΑΓΕΣ");
        if (closed.length() == 0) history.addView(text("Δεν υπάρχουν κλεισμένες συναλλαγές ακόμη. Τα στατιστικά θα ενημερωθούν μετά τις πρώτες πραγματικές PAPER συναλλαγές.", 12, MUTED, false));
        else {
            for (int i = 0; i < Math.min(8, closed.length()); i++) {
                JSONObject p = closed.optJSONObject(i);
                if (p == null) continue;
                double pnl = p.optDouble("pnl");
                String time = new SimpleDateFormat("dd/MM HH:mm", Locale.getDefault()).format(new Date(p.optLong("closedAt")));
                addRow(history, "#" + p.optInt("id") + " " + p.optString("side") + " · " + time, PaperTradingEngine.money(pnl) + " · " + p.optString("reason"), pnl >= 0 ? GREEN : RED);
            }
        }
        if (mt5Status != null && mt5Status.startsWith("DEMO")) {
            addDivider(history);
            addLabel(history,"VANTAGE MT5 DEMO · ΚΛΕΙΣΜΕΝΕΣ ΣΥΝΑΛΛΑΓΕΣ");
            if (mt5ClosedHistory.length()==0) history.addView(text("Δεν επέστρεψε κλεισμένες συναλλαγές ο broker.",11,MUTED,false));
            for(int i=0;i<Math.min(8,mt5ClosedHistory.length());i++) {
                JSONObject trade=mt5ClosedHistory.optJSONObject(i); if(trade==null) continue;
                double pnl=trade.optDouble("profit",Double.NaN);
                String side=trade.optString("side","—");
                String time=trade.optString("closeTime",trade.optString("close_time",""));
                addRow(history,"#"+trade.optString("ticket")+"  "+side+"  "+trade.optString("symbol")+"  "+time,
                        Double.isNaN(pnl)?"P/L μη διαθέσιμο":PaperTradingEngine.money(pnl),
                        Double.isNaN(pnl)?MUTED:(pnl>=0?GREEN:RED));
            }
            Button reloadHistory=actionButton("↻ ΑΝΑΝΕΩΣΗ MT5 ΙΣΤΟΡΙΚΟΥ",0xFF292C34,this::loadMt5AccountData);
            history.addView(reloadHistory);
        }
        root.addView(history);
        addSpace(10);

        LinearLayout mtfCard = card();
        addLabel(mtfCard, "MULTI-TIMEFRAME MONITOR · ΔΙΑΓΝΩΣΤΙΚΟ");
        mtfCard.addView(text(multiTimeframeStatus, 11, GOLD, true));
        mtfCard.addView(text("M1/M5/M15/M30/H1/H4 · Ανεξάρτητη ανάλυση · Δεν επηρεάζει BUY/SELL ή εντολές.", 10, MUTED, false));
        root.addView(mtfCard);
        addSpace(10);

        LinearLayout activity = card();
        addLabel(activity, "✦  AI ACTIVITY LOG  ·  ΖΩΝΤΑΝΕΣ ΕΝΕΡΓΕΙΕΣ");
        synchronized (agentActivityLog) {
            if (agentActivityLog.length() == 0) {
                activity.addView(text("Αναμονή για νέα δεδομένα αγοράς και ενέργειες του AI Agent.",11,MUTED,false));
            } else {
                for (int i=0; i<Math.min(6,agentActivityLog.length()); i++) {
                    JSONObject event=agentActivityLog.optJSONObject(i);
                    if(event==null) continue;
                    String when=new SimpleDateFormat("HH:mm:ss",Locale.getDefault()).format(new Date(event.optLong("at")));
                    addRow(activity,when+"  "+event.optString("agent")+" · "+event.optString("action"),event.optString("reason"),"BLOCKED".equals(event.optString("action"))?RED:GREEN);
                }
            }
        }
        root.addView(activity);
        addSpace(10);

        LinearLayout audit = card();
        addLabel(audit, "ΚΑΤΑΓΡΑΦΗ ΑΠΟΦΑΣΕΩΝ");
        JSONArray events = snap.optJSONArray("events");
        if (events == null || events.length() == 0) audit.addView(text("Δεν υπάρχουν ακόμη καταγεγραμμένες ενέργειες.", 12, MUTED, false));
        else {
            for (int i = 0; i < Math.min(6, events.length()); i++) {
                JSONObject e = events.optJSONObject(i);
                if (e == null) continue;
                String when = new SimpleDateFormat("dd/MM HH:mm:ss", Locale.getDefault()).format(new Date(e.optLong("at")));
                addRow(audit, e.optString("type") + " · " + when, e.optString("detail"), GOLD);
            }
        }
        root.addView(audit);
        addSpace(10);
        historyPageEnd = root.getChildCount();

        settingsPageStart = root.getChildCount();
        LinearLayout connections = card();
        settingsSection = connections;
        addLabel(connections, "ΣΥΝΔΕΣΕΙΣ & ΚΑΤΑΣΤΑΣΗ ΣΥΣΤΗΜΑΤΟΣ");
        addRow(connections, "Δεδομένα αγοράς", quoteFresh() ? "ΤΙΜΗ SPOT ONLINE" : "ΑΝΑΜΟΝΗ / ΠΑΛΙΑ ΤΙΜΗ", quoteFresh() ? GREEN : RED);
        addRow(connections, "Γέφυρα MT5 Demo", mt5Status, mt5Status.startsWith("DEMO") ? GREEN : MUTED);
        addRow(connections, "Μηχανή σημάτων AI", aiEngineStarted ? (aiSignal.ready ? aiSignal.side + " · " + aiSignal.confidence + "%" : "ΕΝΕΡΓΗ · ΣΥΛΛΟΓΗ ΔΕΔΟΜΕΝΩΝ") : "ΑΝΑΜΟΝΗ START AI", aiEngineStarted ? GOLD : MUTED);
        addRow(connections, "Εντολές MT5 DEMO", mt5ExecutionEnabled ? "ΕΝΕΡΓΕΣ · ΜΟΝΟ ΜΕ ΕΠΙΒΕΒΑΙΩΣΗ DEMO" : "ΑΝΑΜΟΝΗ ΣΥΝΔΕΣΗΣ", mt5ExecutionEnabled ? GREEN : GOLD);
        TextView bridgeNote = text("Η σύνδεση γίνεται μέσω TickerAll API προς τον Vantage MT5 DEMO. Ο server ελέγχει ότι ο λογαριασμός είναι DEMO. Η τιμή αναφοράς για εντολές προέρχεται από το τελευταίο M1 candle και όχι από live bid/ask tick. Οι εντολές παραμένουν απενεργοποιημένες μέχρι να ολοκληρωθούν οι έλεγχοι. Η αυτόματη στρατηγική cloud δεν έχει υλοποιηθεί ακόμη.", 10, MUTED, false);
        bridgeNote.setPadding(0, dp(8), 0, dp(8));
        connections.addView(bridgeNote);
        Button bridgeInfo = actionButton("ΣΥΝΔΕΣΗ TICKERALL API · VANTAGE DEMO", 0xFF292C34, this::configureMt5Bridge);
        connections.addView(bridgeInfo);
        Button startAi = actionButton(aiEngineStarted ? "STOP AUTO · ΔΙΑΚΟΠΗ ΝΕΩΝ ΕΝΤΟΛΩΝ" : "START AUTO · MT5 DEMO", 0xFFB58A35, aiEngineStarted ? this::stopAiEngine : this::startAiEngine);
        connections.addView(startAi);
        addRow(connections, "Αυτόματη εκτέλεση", autoExecutionMessage, aiEngineStarted ? GREEN : MUTED);
        Button mt5Positions = actionButton("ΠΡΟΒΟΛΗ / ΚΛΕΙΣΙΜΟ ΘΕΣΕΩΝ MT5 DEMO", 0xFF292C34, this::showMt5Positions);
        connections.addView(mt5Positions);
        Button reset = actionButton("ΕΠΑΝΑΦΟΡΑ DEMO ΛΟΓΑΡΙΑΣΜΟΥ", 0xFF292C34, () ->
                new AlertDialog.Builder(this).setTitle("Επαναφορά demo λογαριασμού;")
                        .setMessage("Θα διαγραφούν οι εικονικές θέσεις και το ιστορικό και θα επανέλθει κεφάλαιο $10.000.")
                        .setNegativeButton("Ακύρωση", null)
                        .setPositiveButton("Επαναφορά", (d, w) -> { engine.reset(); render(); })
                        .show());
        connections.addView(reset);
        root.addView(connections);
        addSpace(10);
        LinearLayout bottomNav=new LinearLayout(this);
        bottomNav.setOrientation(LinearLayout.HORIZONTAL);
        bottomNav.setGravity(Gravity.CENTER);
        bottomNav.setPadding(dp(5),dp(5),dp(5),dp(5));
        bottomNav.setBackground(goldShell(0xFF080707,0xFFFFC83D));
        String[] bottomLabels={"⌂\\nΑρχική","▤\\nΘέσεις","◷\\nΙστορικό","⚙\\nΡυθμίσεις"};
        for(int i=0;i<bottomLabels.length;i++){
            final int index=i;
            boolean active=index==selectedBottomTab;
            TextView item=text(bottomLabels[i],11,active?GOLD:0xFFE5E0D5,true);
            item.setGravity(Gravity.CENTER);
            item.setPadding(dp(2),dp(8),dp(2),dp(8));
            item.setBackground(active?round(0xFF30220A,16,0xFFFFC83D):round(0xFF090909,16,0xFF302A20));
            item.setOnClickListener(v -> {
                selectedBottomTab=index;
                for(int j=0;j<bottomNav.getChildCount();j++){
                    TextView tab=(TextView)bottomNav.getChildAt(j);
                    boolean chosen=j==selectedBottomTab;
                    tab.setTextColor(chosen?GOLD:0xFFE5E0D5);
                    tab.setBackground(chosen?round(0xFF30220A,16,0xFFFFC83D):round(0xFF090909,16,0xFF302A20));
                }
                applySelectedPage();
                currentScroll.scrollTo(0,0);
            });
            bottomNav.addView(item,new LinearLayout.LayoutParams(0,dp(58),1));
        }
        if(bottomNavigation!=null) appShell.removeView(bottomNavigation);
        bottomNavigation=bottomNav;
        appShell.addView(bottomNavigation,new LinearLayout.LayoutParams(-1,dp(68)));
        applySelectedPage();
        TextView footer = text("DioMasteR GOLD AI · v2.0 · XAUUSD · MT5 DEMO", 10, MUTED, false);
        footer.setGravity(Gravity.CENTER);
        root.addView(footer);

        // Build the next layout offscreen, then swap its content in one UI pass.
        // The window and scroll container stay mounted, preventing full-screen redraws.
        if (!firstRender) {
            scroll.removeAllViews();
            scroll.addView(root);
            scroll.scrollTo(0, previousScrollY);
        }
    }


    private void applySelectedPage() {
        if (root == null) return;
        for (int i = 0; i < root.getChildCount(); i++) {
            boolean visible;
            if (selectedBottomTab == 0) visible = i < homePageEnd;
            else if (selectedBottomTab == 1) visible = i >= positionsPageStart && i < positionsPageEnd;
            else if (selectedBottomTab == 2) visible = i >= historyPageStart && i < historyPageEnd;
            else visible = i >= settingsPageStart;
            root.getChildAt(i).setVisibility(visible ? View.VISIBLE : View.GONE);
        }
        if (currentScroll != null) currentScroll.scrollTo(0,0);
    }

    // Local execution loop: strategy stays in GoldAiAgent; broker execution is DEMO-only.
    private void startAiEngine() {
        if (mt5BaseUrl.isEmpty() || mt5Token.isEmpty()) {
            Toast.makeText(this, "Πρώτα σύνδεσε τον υπάρχοντα Vantage MT5 DEMO.", Toast.LENGTH_LONG).show();
            return;
        }
        autoExecutionMessage = "Έλεγχος DEMO και εκκίνησης Cloud AUTO…";
        render();
        new Thread(() -> {
            String failure = null;
            try {
                Mt5DemoClient client = new Mt5DemoClient(mt5BaseUrl, mt5Token);
                JSONObject status = client.status();
                if (!"DEMO".equals(status.optString("account_mode"))
                        || !status.optBoolean("terminal_connected")
                        || !status.optBoolean("execution_enabled"))
                    throw new IllegalStateException("Απαιτείται επαληθευμένος Vantage MT5 DEMO και ενεργό server-side DEMO execution.");
                String server = status.optString("server", "");
                if (!server.toLowerCase(Locale.US).contains("vantage") || !server.toLowerCase(Locale.US).contains("demo"))
                    throw new IllegalStateException("Ο broker δεν επιβεβαιώθηκε ως Vantage DEMO.");
                JSONObject started = client.autoStart();
                if (!started.optBoolean("running")) throw new IllegalStateException("Ο cloud AUTO δεν ξεκίνησε.");
            } catch (Exception e) { failure = e.getMessage() == null ? "Αποτυχία εκκίνησης Cloud AUTO" : e.getMessage(); }
            final String error = failure;
            runOnUiThread(() -> {
                if (error != null) {
                    aiEngineStarted = false;
                    autoExecutionMessage = "ΜΠΛΟΚΑΡΙΣΜΕΝΟ · " + error;
                    Toast.makeText(this, autoExecutionMessage, Toast.LENGTH_LONG).show();
                } else {
                    aiEngineStarted = true;
                    autoExecutionMessage = "CLOUD AUTO ΕΝΕΡΓΟ · Unified 8/10 · DEMO";
                    Toast.makeText(this, "Cloud AUTO ξεκίνησε στον server DEMO.", Toast.LENGTH_LONG).show();
                }
                render();
            });
        }).start();
    }

    private void stopAiEngine() {
        aiEngineStarted = false;
        autoExecutionMessage = "Αποστολή εντολής STOP στο Cloud AUTO…";
        render();
        new Thread(() -> {
            String result;
            try {
                new Mt5DemoClient(mt5BaseUrl, mt5Token).autoStop();
                result = "STOP · Cloud AUTO σταμάτησε. Οι ανοιχτές θέσεις διατηρούν τα SL/TP.";
            } catch (Exception e) { result = "STOP ERROR · " + e.getMessage(); }
            final String message = result;
            runOnUiThread(() -> { autoExecutionMessage = message; Toast.makeText(this,message,Toast.LENGTH_LONG).show(); render(); });
        }).start();
    }

    private void setAutoDiagnostic(String message) {
        if (message == null || message.equals(autoExecutionMessage)) return;
        autoExecutionMessage = message;
        // Keep a local audit trail of each distinct decision/blocker without changing strategy.
        logAgentActivity("AI DECISION", "DIAGNOSTIC",
                selectedTimeframe + " · candles=" + chartPrices.size()
                        + " · quoteAge=" + (quoteAt > 0 ? Math.max(0L, (System.currentTimeMillis() - quoteAt) / 1000L) + "s" : "n/a")
                        + " · " + message
                        + " · " + (aiSignal == null ? "" : aiSignal.reason));
        render();
    }

    // Diagnostics explain every local gate; Original EMA 9/21 H1 strategy diagnostics.
    private void evaluateAutoSignal(JSONArray bars, JSONArray h4Bars, long quoteTimestamp) {
        if (!aiEngineStarted) return;
        // AUTO decisions and orders are exclusively handled by the cloud Unified 8/10 engine.
        setAutoDiagnostic("CLOUD AUTO · αποφάσεις στον server · Unified Score 8/10 · DEMO.");
    }

    private String cleanBridgeToken(String value) {
        if (value == null) return "";
        // Accept either a raw token or a pasted "Bearer <token>" header value.
        String cleaned = value.trim().replaceFirst("(?i)^Bearer\\s+", "");
        return cleaned.replaceAll("[\\\\r\\\\n\\\\t ]+", "");
    }
    private void configureMt5Bridge() {
        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(8);
        EditText endpoint = new EditText(this);
        endpoint.setSingleLine(true);
        endpoint.setTextColor(Color.WHITE);
        endpoint.setHintTextColor(MUTED);
        endpoint.setHint("HTTPS διεύθυνση bridge, π.χ. https://...");
        endpoint.setText(mt5BaseUrl.isEmpty() ? "https://diomaster-gold-ai-metaapi-demo.onrender.com" : mt5BaseUrl);
        endpoint.setInputType( android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        form.addView(endpoint);
        EditText token = new EditText(this);
        token.setSingleLine(true);
        token.setTextColor(Color.WHITE);
        token.setHintTextColor(MUTED);
        token.setHint("DIO_BRIDGE_TOKEN");
        token.setText(mt5Token);
        token.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        form.addView(token);
        TextView note = text("Βάλε το HTTPS URL του cloud bridge και το DIO_BRIDGE_TOKEN από τα Render secrets. Το TickerAll API key παραμένει μόνο στο Render και δεν μπαίνει στην εφαρμογή. Ο server απορρίπτει κάθε λογαριασμό που δεν επιβεβαιώνεται ως DEMO.", 11, MUTED, false);
        note.setPadding(0, pad, 0, 0);
        form.addView(note);
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("Σύνδεση MT5 Demo")
                .setView(form)
                .setNegativeButton("Ακύρωση", null)
                .setPositiveButton("Έλεγχος", null)
                .create();
        dialog.setOnShowListener(v -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
            String base = endpoint.getText().toString().trim().replaceAll("/+$", "");
            String secret = cleanBridgeToken(token.getText().toString());
            if (!base.startsWith("https://") || secret.length() < 16) {
                Toast.makeText(this, "Βάλε έγκυρο HTTPS URL και token τουλάχιστον 16 χαρακτήρων.", Toast.LENGTH_LONG).show();
                return;
            }
            dialog.dismiss();
            mt5Status = "ΕΛΕΓΧΟΣ…";
            render();
            new Thread(() -> {
                HttpURLConnection connection = null;
                String result;
                try {
                    URL url = new URL(base + "/v1/status");
                    connection = (HttpURLConnection) url.openConnection();
                    connection.setRequestMethod("GET");
                    connection.setConnectTimeout(8000);
                    connection.setReadTimeout(8000);
                    connection.setRequestProperty("Authorization", "Bearer " + secret);
                    connection.setRequestProperty("Accept", "application/json");
                    int code = connection.getResponseCode();
                    java.io.InputStream stream = code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream();
                    java.io.BufferedReader reader = new java.io.BufferedReader(new java.io.InputStreamReader(stream, "UTF-8"));
                    StringBuilder body = new StringBuilder();
                    String line;
                    while ((line = reader.readLine()) != null) body.append(line);
                    reader.close();
                    if (code < 200 || code >= 300) throw new IllegalStateException("Bridge HTTP " + code + (body.length() > 0 ? " · " + body.toString() : ""));
                    String rawStatus = body.toString().trim();
                    if (rawStatus.isEmpty()) throw new IllegalStateException("Bridge HTTP " + code + ": κενή απάντηση.");
                    if (rawStatus.startsWith("<") || rawStatus.regionMatches(true, 0, "<!DOCTYPE", 0, 9)
                            || rawStatus.regionMatches(true, 0, "<html", 0, 5)) {
                        throw new IllegalStateException("Το Render επέστρεψε HTML αντί για JSON (HTTP " + code
                                + "). Έλεγξε το Base URL και το route /v1/status.");
                    }
                    JSONObject status;
                    try {
                        status = new JSONObject(rawStatus);
                    } catch (Exception parseError) {
                        throw new IllegalStateException("Μη έγκυρη απάντηση JSON από το Render (HTTP " + code + ").");
                    }
                    if (!"DEMO".equals(status.optString("account_mode")) || !status.optBoolean("terminal_connected")) {
                        throw new IllegalStateException("Δεν επιβεβαιώθηκε ασφαλής σύνδεση DEMO.");
                    }
                    JSONArray allowed = status.optJSONArray("allowed_symbols");
                    String selectedSymbol = allowed != null && allowed.length()>0 ? allowed.optString(0,"XAUUSD") : "XAUUSD";
                    boolean execEnabled = status.optBoolean("execution_enabled");
                    String display = "DEMO · " + status.optString("server", "MT5") + " · #" + status.optString("account_login") + (execEnabled ? " · ORDERS ON" : " · READ ONLY");
                    getSharedPreferences("diomaster_mt5_demo", MODE_PRIVATE).edit().putString("base",base).putString("token",secret).putString("symbol",selectedSymbol).putBoolean("execution_enabled",execEnabled).putString("status",display).apply();
                    mt5BaseUrl=base; mt5Token=secret; mt5Symbol=selectedSymbol; mt5ExecutionEnabled=execEnabled;
                    mt5Login=status.optString("account_login",""); mt5Currency=status.optString("currency","USD"); mt5Balance=status.optDouble("balance",0); mt5Equity=status.optDouble("equity",mt5Balance);
                    getSharedPreferences("diomaster_mt5_demo",MODE_PRIVATE).edit().putString("login",mt5Login).putString("currency",mt5Currency).putLong("balance_bits",Double.doubleToRawLongBits(mt5Balance)).putLong("equity_bits",Double.doubleToRawLongBits(mt5Equity)).apply();
                    result = display;
                } catch (Exception e) {
                    result = "ΑΠΟΤΥΧΙΑ ΣΥΝΔΕΣΗΣ: " + (e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
                } finally {
                    if (connection != null) connection.disconnect();
                }
                final String finalResult = result;
                runOnUiThread(() -> {
                    mt5Status = finalResult;
                    Toast.makeText(this, finalResult, Toast.LENGTH_LONG).show();
                    render();
                });
            }).start();
        }));
        dialog.show();
    }

    private void scrollToSection(View section) {
        if (currentScroll == null || section == null) return;
        currentScroll.post(() -> currentScroll.smoothScrollTo(0, section.getTop() + root.getTop() - dp(8)));
    }

    // Custom vector-style gold lion and AI robot artwork; rendered natively at any screen density.
    private final class MascotView extends View {
        private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        MascotView(android.content.Context context) { super(context); }
        private void stroke(Canvas c, Path path, int color, float width) {
            p.setStyle(Paint.Style.STROKE); p.setStrokeWidth(width); p.setStrokeCap(Paint.Cap.ROUND);
            p.setStrokeJoin(Paint.Join.ROUND); p.setColor(color); c.drawPath(path,p);
        }
        private void fill(Canvas c, Path path, int color) { p.setStyle(Paint.Style.FILL); p.setColor(color); c.drawPath(path,p); }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float sx=getWidth()/320f, sy=getHeight()/104f;
            canvas.save(); canvas.scale(sx,sy);
            int gold=0xFFFFC94D, pale=0xFFFFE6A0, dark=0xFF704512, cyan=0xFF43D9F2;
            // Lion mane silhouette.
            Path mane=new Path();
            mane.moveTo(12,52); mane.lineTo(5,31); mane.lineTo(25,37); mane.lineTo(19,12);
            mane.lineTo(43,27); mane.lineTo(51,4); mane.lineTo(66,26); mane.lineTo(84,8);
            mane.lineTo(88,34); mane.lineTo(108,24); mane.lineTo(100,49); mane.lineTo(111,70);
            mane.lineTo(88,72); mane.lineTo(78,96); mane.lineTo(60,82); mane.lineTo(39,98);
            mane.lineTo(34,76); mane.lineTo(10,82); mane.lineTo(22,61); mane.close();
            fill(canvas,mane,dark); stroke(canvas,mane,gold,2.1f);
            Path face=new Path(); face.moveTo(36,37); face.lineTo(49,27); face.lineTo(72,29);
            face.lineTo(88,43); face.lineTo(83,68); face.lineTo(63,84); face.lineTo(43,68); face.close();
            fill(canvas,face,0xFF17120A); stroke(canvas,face,pale,1.6f);
            Path brow=new Path(); brow.moveTo(42,46); brow.lineTo(55,42); brow.lineTo(61,48);
            brow.moveTo(67,48); brow.lineTo(74,42); brow.lineTo(84,46); stroke(canvas,brow,gold,2.2f);
            p.setStyle(Paint.Style.FILL); p.setColor(gold);
            canvas.drawCircle(54,51,3,p); canvas.drawCircle(75,51,3,p);
            Path muzzle=new Path(); muzzle.moveTo(53,61); muzzle.lineTo(64,57); muzzle.lineTo(76,61);
            muzzle.lineTo(69,72); muzzle.lineTo(60,72); muzzle.close(); fill(canvas,muzzle,pale);
            Path mouth=new Path(); mouth.moveTo(64,72); mouth.lineTo(64,78); mouth.moveTo(64,78); mouth.lineTo(56,81);
            mouth.moveTo(64,78); mouth.lineTo(73,81); stroke(canvas,mouth,gold,1.5f);
            // Central crown and brand flare.
            Path crown=new Path(); crown.moveTo(137,25); crown.lineTo(145,9); crown.lineTo(158,21);
            crown.lineTo(173,5); crown.lineTo(184,21); crown.lineTo(197,9); crown.lineTo(204,25);
            crown.lineTo(198,39); crown.lineTo(143,39); crown.close(); fill(canvas,crown,gold); stroke(canvas,crown,pale,1.5f);
            p.setStyle(Paint.Style.FILL); p.setColor(0xFFFFF0BD);
            canvas.drawCircle(145,8,3,p); canvas.drawCircle(173,4,3,p); canvas.drawCircle(197,8,3,p);
            // AI robot head.
            Path head=new Path(); head.moveTo(232,29); head.lineTo(279,20); head.lineTo(306,38);
            head.lineTo(310,73); head.lineTo(289,91); head.lineTo(248,87); head.lineTo(226,65); head.close();
            fill(canvas,head,0xFF101A22); stroke(canvas,head,gold,2.2f);
            Path visor=new Path(); visor.moveTo(238,42); visor.lineTo(278,31); visor.lineTo(298,43);
            visor.lineTo(295,66); visor.lineTo(251,72); visor.lineTo(237,60); visor.close();
            fill(canvas,visor,0xFF17303A); stroke(canvas,visor,cyan,1.5f);
            p.setStyle(Paint.Style.FILL); p.setColor(cyan);
            canvas.drawCircle(254,52,4,p); canvas.drawCircle(280,48,4,p);
            Path jaw=new Path(); jaw.moveTo(250,76); jaw.lineTo(289,70); jaw.lineTo(281,84); jaw.lineTo(258,87); jaw.close();
            fill(canvas,jaw,0xFF27343A); stroke(canvas,jaw,pale,1.1f);
            Path antenna=new Path(); antenna.moveTo(273,20); antenna.lineTo(277,10); antenna.lineTo(288,8);
            stroke(canvas,antenna,gold,2); p.setStyle(Paint.Style.FILL); p.setColor(cyan); canvas.drawCircle(290,8,3,p);
            // Subtle circuit accents.
            Path circuits=new Path(); circuits.moveTo(226,46); circuits.lineTo(216,40); circuits.lineTo(216,31);
            circuits.moveTo(303,58); circuits.lineTo(316,58); circuits.moveTo(245,88); circuits.lineTo(239,96);
            stroke(canvas,circuits,0xFFB98B32,1.2f);
            canvas.restore();
        }
    }

    private LinearLayout card() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(16), dp(16), dp(16), dp(16));
        GradientDrawable shell = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{0xFF1A202B, 0xFF11151D, 0xFF151923});
        shell.setCornerRadius(dp(22));
        shell.setStroke(dp(1), 0xFF554522);
        box.setBackground(shell);
        box.setElevation(dp(3));
        return box;
    }

    private LinearLayout metric(String label, String value, int color) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(12), dp(13), dp(12), dp(13));
        box.setBackground(goldShell(0xFF111113,0xFF493918));
        box.setElevation(dp(2));
        TextView title = text(label, 9, 0xFFB8AA8E, true);
        title.setLetterSpacing(0.045f);
        box.addView(title);
        TextView v = text(value, 15, color, true);
        v.setSingleLine(true);
        v.setEllipsize(android.text.TextUtils.TruncateAt.END);
        v.setPadding(0, dp(7), 0, 0);
        box.addView(v);
        return box;
    }

    private void addLabel(LinearLayout box, String value) {
        TextView t = text(value, 11, 0xFFFFD36A, true);
        t.setLetterSpacing(0.055f);
        t.setPadding(0, 0, 0, dp(13));
        box.addView(t);
    }

    private void addRow(LinearLayout box, String left, String right) { addRow(box, left, right, 0xFFF1F1F1); }
    private void addRow(LinearLayout box, String left, String right, int color) {
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(6), 0, dp(6));
        TextView l = text(left, 11, MUTED, false);
        TextView r = text(right, 11, color, true);
        r.setGravity(Gravity.RIGHT);
        row.addView(l, new LinearLayout.LayoutParams(0, -2, 1));
        row.addView(r);
        box.addView(row);
        addDivider(box);
    }

    private void addDivider(LinearLayout box) {
        View line = new View(this);
        line.setBackgroundColor(0xFF292621);
        box.addView(line, new LinearLayout.LayoutParams(-1, dp(1)));
    }

    private Button actionButton(String label, int color, Runnable action) {        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(11);
        b.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        b.setLetterSpacing(0.035f);
        b.setTextColor(Color.WHITE);
        b.setAllCaps(false);
        b.setMinHeight(dp(50));
        b.setPadding(dp(10), dp(8), dp(10), dp(8));
        int deep = color == GREEN ? 0xFF06351D : color == GOLD ? 0xFF352407 :
                color == 0xFFB12BEE ? 0xFF260B38 : color == 0xFF168CFF ? 0xFF071D3B : 0xFF171719;
        GradientDrawable face = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{deep, 0xFF08090B, deep});
        face.setCornerRadius(dp(17));
        face.setStroke(dp(2), color);
        b.setBackground(face);
        b.setShadowLayer(dp(9), 0, 0, color);
        b.setElevation(dp(5));
        b.setOnClickListener(v -> action.run());
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(dp(4), dp(6), dp(4), dp(4));
        b.setLayoutParams(lp);
        return b;
    }

    private TextView text(String value, int size, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(value);
        t.setTextSize(size);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return t;
    }

    private GradientDrawable goldShell(int color, int stroke) {
        GradientDrawable d = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{0xFF20232B, color, 0xFF10131A});
        d.setCornerRadius(dp(20));
        d.setStroke(dp(1), stroke);
        return d;
    }

    private GradientDrawable round(int color, int radius, int stroke) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(radius));
        d.setStroke(dp(1), stroke);
        return d;
    }

    private LinearLayout.LayoutParams weight() {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, -2, 1);
        p.setMargins(dp(3), 0, dp(3), 0);
        return p;
    }

    private void addSpace(int height) {
        View v = new View(this);
        root.addView(v, new LinearLayout.LayoutParams(1, dp(height)));
    }

    private int dp(int value) { return (int) (value * getResources().getDisplayMetrics().density + 0.5f); }
    private String money(double value) { return "$" + String.format(Locale.US, "%,.2f", value); }
}