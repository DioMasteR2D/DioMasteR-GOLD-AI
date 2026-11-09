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
    private final int BG = 0xFF050506;
    private final int PANEL = 0xFF111014;
    private final int GOLD = 0xFFFFC83D;
    private final int MUTED = 0xFFB5A58A;
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
    private LinearLayout marketSection, agentSection, tradesSection, historySection, settingsSection;
    private double price = 0.0;
    private long quoteAt = 0L;
    private boolean fetching = false;
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
    private final JSONArray agentActivityLog = new JSONArray();

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
                for (int i = 0; i < agentActivityLog.length() && i < 39; i++) next.put(agentActivityLog.opt(i));
                while (agentActivityLog.length() > 0) agentActivityLog.remove(0);
                for (int i = 0; i < next.length(); i++) agentActivityLog.put(next.opt(i));
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
        android.content.SharedPreferences mt5Prefs = getSharedPreferences("diomaster_mt5_demo", MODE_PRIVATE);
        mt5BaseUrl = mt5Prefs.getString("base", "https://diomaster-gold-ai-metaapi-demo.onrender.com");
        mt5Token = cleanBridgeToken(mt5Prefs.getString("token", ""));
        mt5Symbol = mt5Prefs.getString("symbol", "XAUUSD");
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
        new Thread(() -> {
            String result;
            try {
                Mt5DemoClient client = new Mt5DemoClient(mt5BaseUrl, mt5Token);
                JSONObject status = client.status();
                if (!"DEMO".equals(status.optString("account_mode")) || !status.optBoolean("terminal_connected") || !status.optBoolean("execution_enabled"))
                    throw new IllegalStateException("Το MT5 δεν είναι συνδεδεμένο σε ενεργό DEMO execution.");
                JSONObject started = client.autoStart();
                result = started.optBoolean("running") ? "DioMasteR AI AUTO ξεκίνησε στο Vantage DEMO." : "Η αυτόματη λειτουργία δεν ξεκίνησε.";
            } catch(Exception e) { result = "AI AUTO σε αναμονή: " + e.getMessage(); }
            final String message = result;
            runOnUiThread(() -> Toast.makeText(this, message, Toast.LENGTH_LONG).show());
        }).start();
    }

    private void fetchPrice() { fetchPrice(false); }

    private void fetchPrice(boolean force) {
        if (!activityResumed && !force) return;
        if (fetching && !force) return;
        fetching = true;
        final int requestId = ++fetchSequence;
        final String requestTimeframe = selectedTimeframe;
        if (mt5BaseUrl != null && !mt5BaseUrl.isEmpty() && mt5Token != null && !mt5Token.isEmpty()
                && mt5Status != null && mt5Status.startsWith("DEMO")) {
            new Thread(() -> {
                try {
                    Mt5DemoClient client = new Mt5DemoClient(mt5BaseUrl, mt5Token);
                    JSONObject quote = client.quote(mt5Symbol);
                    JSONObject candleData = client.candles(mt5Symbol, requestTimeframe, 48);
                    JSONArray rows = candleData.optJSONArray("candles");
                    if (rows == null || rows.length() < 2) throw new IllegalStateException("Δεν υπάρχουν αρκετά broker OHLC candles.");
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
                    final String effectiveTimeframe = candleData.optString("effective_timeframe",
                            candleData.optString("timeframe", requestTimeframe));
                    final long receivedAt = stamp;
                    runOnUiThread(() -> {
                        if (requestId != fetchSequence || !activityResumed) return;
                        fetching = false; price = latest; quoteAt = receivedAt;
                        brokerCandles = bars; brokerChartActive = true;
                        chartPrices.clear();
                        for (int i=0;i<bars.length();i++) {
                            JSONObject bar=bars.optJSONObject(i);
                            if(bar!=null && bar.optDouble("close",0)>0) chartPrices.add(bar.optDouble("close"));
                        }
                        feedMessage = "VANTAGE MT5 DEMO · LIVE BID/ASK TICK · " + effectiveTimeframe +
                                ("tickerall_live_ticks".equals(candleData.optString("source")) ? " · LIVE TICK CHART" : "") + " · " +
                                new SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(new Date(receivedAt));
                        aiSignal = GoldAiAgent.analyze(chartPrices, latest);
                        engine.onQuote(latest);
                        if (aiEngineStarted) evaluateAutoSignal(bars, receivedAt);
                        render();
                    });
                } catch (Exception e) {
                    runOnUiThread(() -> {
                        if (requestId != fetchSequence || !activityResumed) return;
                        fetching=false; brokerChartActive=false;
                        price=0.0; quoteAt=0L; brokerCandles=new JSONArray(); chartPrices.clear();
                        aiSignal=GoldAiAgent.Signal.waiting("NO LIVE BROKER TICK · "+(e.getMessage()==null?"unknown":e.getMessage()));
                        feedMessage="MT5 DEMO · NO LIVE TICK: "+(e.getMessage()==null?"unknown":e.getMessage());
                        logAgentActivity("MARKET FEED", "BLOCKED", e.getMessage()==null ? "Άγνωστο σφάλμα broker feed" : e.getMessage());
                        logAgentActivity("MARKET FEED", "BLOCKED",
                                e.getMessage()==null ? "Άγνωστο σφάλμα broker feed" : e.getMessage());
                        render();
                    });
                }
            }).start();
            return;
        }
        new Thread(() -> priceClient.fetch(new GoldPriceClient.Callback() {
            @Override public void onPrice(double value, long receivedAt) {
                runOnUiThread(() -> {
                    if (requestId != fetchSequence || !activityResumed) return;
                    fetching = false; price = value; quoteAt = receivedAt; brokerChartActive=false;
                    brokerCandles = new JSONArray();
                    feedMessage = "Ενδεικτική spot τιμή · όχι broker tick · " +
                            new SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(new Date(receivedAt));
                    chartPrices.add(value); while (chartPrices.size() > 90) chartPrices.remove(0);
                    aiSignal = GoldAiAgent.analyze(chartPrices, value); engine.onQuote(value); render();
                });
            }
            @Override public void onError(String message) {
                runOnUiThread(() -> {
                    if (requestId != fetchSequence || !activityResumed) return;
                    fetching=false; feedMessage="Αδυναμία λήψης τιμής: "+message; render();
                });
            }
        })).start();
    }

    private boolean quoteFresh() {
        return price > 0 && quoteAt > 0 && System.currentTimeMillis() - quoteAt <= 15000L;
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
                if (bid<=0 || ask<=0 || ask<bid) throw new IllegalStateException("Μη έγκυρη τιμή broker.");
                double entry="BUY".equals(side)?ask:bid;
                double sl="BUY".equals(side)?entry-8.0:entry+8.0;
                double tp="BUY".equals(side)?entry+16.0:entry-16.0;
                JSONObject result=client.order(mt5Symbol,side,0.01,sl,tp);
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

    private void confirmMt5Close(JSONObject position) {
        long ticket=position.optLong("ticket");
        new AlertDialog.Builder(this).setTitle("Κλείσιμο θέσης #"+ticket)
            .setMessage("Θα σταλεί εντολή κλεισίματος στον Vantage MT5 DEMO.")
            .setNegativeButton("Άκυρο",null)
            .setPositiveButton("Κλείσιμο",(d,w)->new Thread(()->{
                String msg;
                try { JSONObject r=new Mt5DemoClient(mt5BaseUrl,mt5Token).close(ticket); msg="Εντολή κλεισίματος στάλθηκε · deal #"+r.optLong("deal"); }
                catch(Exception e) { msg="Δεν έκλεισε: "+e.getMessage(); }
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
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(12), dp(16), dp(24));
        root.setBackgroundColor(BG);

        // Keep the existing ScrollView attached to the Activity during data refreshes.
        // Replacing the whole window on every market tick caused visible flashing and lag.
        final boolean firstRender = currentScroll == null;
        final int previousScrollY = firstRender ? 0 : currentScroll.getScrollY();
        final ScrollView scroll;
        if (firstRender) {
            scroll = new ScrollView(this);
            scroll.setFillViewport(true);
            scroll.setBackgroundColor(BG);
            currentScroll = scroll;
            scroll.addView(root);
            setContentView(scroll);
        } else {
            scroll = currentScroll;
        }

        LinearLayout hero = new LinearLayout(this);
        hero.setOrientation(LinearLayout.HORIZONTAL);
        hero.setGravity(Gravity.CENTER_VERTICAL);
        hero.setPadding(dp(10),dp(8),dp(10),dp(8));
        hero.setBackground(goldShell(0xFF080707,0xFF5B3A08));
        MascotView headerArt=new MascotView(this);
        hero.addView(headerArt,new LinearLayout.LayoutParams(dp(112),dp(82)));
        LinearLayout brandText=new LinearLayout(this); brandText.setOrientation(LinearLayout.VERTICAL); brandText.setGravity(Gravity.CENTER);
        TextView brandTitle=text("DioMasteR2D",19,0xFFFFD45A,true); brandTitle.setGravity(Gravity.CENTER); brandTitle.setLetterSpacing(0.025f); brandText.addView(brandTitle);
        TextView goldTitle=text("GOLD AI",25,0xFFFFD45A,true); goldTitle.setGravity(Gravity.CENTER); brandText.addView(goldTitle);
        TextView brandSub=text("AI TRADING · XAUUSD · MT5",8,0xFFFFD98A,true); brandSub.setGravity(Gravity.CENTER); brandText.addView(brandSub);
        LinearLayout.LayoutParams brandLp=new LinearLayout.LayoutParams(0,-2,1); brandLp.leftMargin=dp(4); hero.addView(brandText,brandLp);
        boolean mt5Connected = mt5Status != null && mt5Status.startsWith("DEMO");
        TextView statusPill=text(mt5Connected?"DEMO":"OFFLINE",10,mt5Connected?0xFF071B12:0xFFFFE5A3,true);
        statusPill.setGravity(Gravity.CENTER); statusPill.setPadding(dp(11),dp(8),dp(11),dp(8));
        statusPill.setBackground(round(mt5Connected?GREEN:0xFF302515,18,mt5Connected?GREEN:GOLD));
        statusPill.setOnClickListener(v -> configureMt5Bridge());
        hero.addView(statusPill);
        root.addView(hero,new LinearLayout.LayoutParams(-1,dp(122)));
        addSpace(10);

        // Primary navigation is intentionally kept at the bottom of the dashboard.
        addSpace(8);

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
        root.addView(connection);
        addSpace(10);

        LinearLayout market = card();
        marketSection = market;
        addLabel(market, brokerChartActive ? "XAUUSD  ·  GOLD  ·  VANTAGE MT5 DEMO OHLC" : "XAUUSD  ·  GOLD  ·  ΕΝΔΕΙΚΤΙΚΗ SPOT ΤΙΜΗ");
        TextView priceText = text(price > 0 ? "$" + String.format(Locale.US, "%,.2f", price) : "—", 40, GOLD, true);
        market.addView(priceText);
        TextView feed = text((quoteFresh() ? "● " : "● ") + feedMessage, 11, quoteFresh() ? GREEN : RED, false);
        market.addView(feed);
        LinearLayout periods = new LinearLayout(this);
        periods.setOrientation(LinearLayout.HORIZONTAL);
        periods.setGravity(Gravity.CENTER);
        String[] frames={"M1","M5","M15","M30","H1","H4","D1"};
        for(String frame:frames) {
            final String tf=frame;
            TextView chip=text(frame,10,selectedTimeframe.equals(frame)?Color.BLACK:0xFFE8E8EA,true);
            chip.setGravity(Gravity.CENTER); chip.setPadding(dp(7),dp(8),dp(7),dp(8));
            chip.setBackground(selectedTimeframe.equals(frame)?round(GOLD,9,0xFFFFE18A):round(0xFF171A20,9,0xFF343944));
            chip.setOnClickListener(v->{
                if (!tf.equals(selectedTimeframe)) {
                    selectedTimeframe=tf;
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
        chart.setLayoutParams(new LinearLayout.LayoutParams(-1, dp(270)));
        if (brokerChartActive) chart.setCandles(brokerCandles);
        else for (double p : chartPrices) chart.addPrice(p);
        market.addView(chart);
        LinearLayout indicators = new LinearLayout(this);
        indicators.setOrientation(LinearLayout.HORIZONTAL);
        boolean haveOhlc=brokerChartActive && brokerCandles.length()>=26;
        double rsiValue=calcRsi14(), macdValue=calcMacd(), atrValue=calcAtr14();
        double emaFast=calcEma(9), emaSlow=calcEma(21);
        indicators.addView(metric("RSI (14)",haveOhlc?String.format(Locale.US,"%.1f · %s",rsiValue,rsiValue>=70?"Overbought":rsiValue<=30?"Oversold":"Neutral"):"—",GREEN),weight());
        indicators.addView(metric("MACD",haveOhlc?String.format(Locale.US,"%+.2f",macdValue):"—",macdValue>=0?GREEN:RED),weight());
        indicators.addView(metric("ATR (14)",haveOhlc?String.format(Locale.US,"%.2f",atrValue):"—",GOLD),weight());
        indicators.addView(metric("Τάση EMA",haveOhlc?(emaFast>emaSlow?"Ανοδική":"Καθοδική"):"—",haveOhlc?(emaFast>emaSlow?GREEN:RED):GOLD),weight());
        market.addView(indicators);
        TextView chartNote = text(brokerChartActive ? "Πραγματικά OHLC candles από Vantage MT5 DEMO · EMA 9 / EMA 21." : "Spot snapshots μόνο · σύνδεσε MT5 DEMO για πραγματικά OHLC candlesticks.", 9, MUTED, false);
        chartNote.setPadding(0, dp(5), 0, 0);
        market.addView(chartNote);
        root.addView(market);
        addSpace(10);

        LinearLayout agent = card();
        agentSection = agent;
        addLabel(agent, "✦  DIOMASTER AI SIGNAL  ·  MARKET ANALYSIS");
        int signalColor = "BUY".equals(aiSignal.side) ? GREEN : "SELL".equals(aiSignal.side) ? RED : GOLD;
        String signalTitle = "BUY".equals(aiSignal.side) ? "▲ BUY SIGNAL" : "SELL".equals(aiSignal.side) ? "▼ SELL SIGNAL" : "HOLD · WAIT";
        TextView signal = text(signalTitle, 25, signalColor, true);
        if (aiSignal.ready && !"HOLD".equals(aiSignal.side)) {
            android.view.animation.AlphaAnimation pulse = new android.view.animation.AlphaAnimation(0.55f, 1.0f);
            pulse.setDuration(850L); pulse.setRepeatMode(android.view.animation.Animation.REVERSE);
            pulse.setRepeatCount(android.view.animation.Animation.INFINITE); signal.startAnimation(pulse);
        }
        agent.addView(signal);
        LinearLayout signalRow = new LinearLayout(this);
        signalRow.setOrientation(LinearLayout.HORIZONTAL);
        TextView setup = text(aiSignal.ready && !"HOLD".equals(aiSignal.side) ? aiSignal.side+" SETUP" : "WAITING FOR SETUP",13,0xFFFFFFFF,true);
        setup.setGravity(Gravity.CENTER); setup.setPadding(dp(12),dp(10),dp(12),dp(10));
        setup.setBackground(round(aiSignal.ready && "BUY".equals(aiSignal.side)?0xFF087C43:0xFF22262E,12,0xFF24D978));
        signalRow.addView(setup,new LinearLayout.LayoutParams(0,-2,1));
        TextView probability=text(aiSignal.ready?aiSignal.confidence+"%":"—",23,GREEN,true);
        probability.setGravity(Gravity.CENTER); signalRow.addView(probability,new LinearLayout.LayoutParams(dp(84),-2));
        agent.addView(signalRow);
        TextView confidence = text(!aiSignal.ready ? "Ο Agent περιμένει επαρκή δεδομένα" : "HOLD".equals(aiSignal.side) ? "Δεν υπάρχει επιβεβαιωμένο setup" : "Βαθμός επιβεβαίωσης κανόνων: " + aiSignal.confidence + "%", 11, MUTED, true);
        confidence.setPadding(0, dp(4), 0, dp(8));
        agent.addView(confidence);
        TextView reason = text(aiSignal.reason, 12, 0xFFE2E4E8, false);
        agent.addView(reason);
        if (aiSignal.ready && !"HOLD".equals(aiSignal.side)) {
            addDivider(agent);
            addRow(agent, "Ενδεικτική είσοδος", money(aiSignal.entry), GOLD);
            addRow(agent, "Stop Loss", money(aiSignal.stopLoss), RED);
            addRow(agent, "Take Profit", money(aiSignal.takeProfit), GREEN);
            addRow(agent, "Risk / Reward", "1 : 1.8", GOLD);
        } else {
            TextView waiting = text("Οι ενδείξεις είναι αναλυτικά σήματα, όχι εντολές broker. Το liquidity sweep / FVG απαιτεί επιβεβαιωμένα OHLC candles. Δεν ανοίγει συναλλαγή αυτόματα.", 10, MUTED, false);
            waiting.setPadding(0, dp(8), 0, 0);
            agent.addView(waiting);
        }
        LinearLayout aiButtons = new LinearLayout(this);
        aiButtons.setOrientation(LinearLayout.HORIZONTAL);
        Button aiStart = actionButton("▶ START AI ENGINE", GOLD, this::startAiEngine);
        aiStart.setLayoutParams(new LinearLayout.LayoutParams(0,-2,2));
        Button aiStop = actionButton("Ⅱ STOP AI", 0xFF49302B, () -> {
            aiEngineStarted=false;
            Toast.makeText(this,"AI analysis paused.",Toast.LENGTH_SHORT).show();
            render();
        });
        aiStop.setLayoutParams(new LinearLayout.LayoutParams(0,-2,1));
        aiButtons.addView(aiStart); aiButtons.addView(aiStop);
        agent.addView(aiButtons);
        root.addView(agent);
        addSpace(10);

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
            Button reloadPositions=actionButton("↻ ΑΝΑΝΕΩΣΗ MT5 ΘΕΣΕΩΝ",0xFF292C34,this::loadMt5AccountData);
            positions.addView(reloadPositions);
        }
        root.addView(positions);
        addSpace(10);

        LinearLayout history = card();
        historySection = history;
        addLabel(history, "ΙΣΤΟΡΙΚΟ ΚΛΕΙΣΜΕΝΩΝ ΣΥΝΑΛΛΑΓΩΝ");
        JSONArray closed = snap.optJSONArray("history");
        if (closed == null || closed.length() == 0) history.addView(text("Δεν υπάρχουν κλεισμένες συναλλαγές ακόμη.", 12, MUTED, false));
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
        bottomNav.setPadding(dp(3),dp(7),dp(3),dp(7));
        bottomNav.setBackground(goldShell(0xFF080707,0xFF9B6B17));
        String[] bottomLabels={"⌂\nΑρχική","↗\nΑγορές","▥\nΓράφημα","◷\nΙστορικό","⚙\nΡυθμίσεις"};
        for(int i=0;i<bottomLabels.length;i++){
            final int index=i;
            TextView item=text(bottomLabels[i],10,i==0?GOLD:Color.WHITE,true);
            item.setGravity(Gravity.CENTER);
            item.setPadding(dp(2),dp(7),dp(2),dp(7));
            item.setOnClickListener(v -> {
                if(index==0){currentScroll.smoothScrollTo(0,0);}
                else if(index==1){scrollToSection(marketSection);}
                else if(index==2){scrollToSection(marketSection);}
                else if(index==3){scrollToSection(historySection);}
                else {scrollToSection(settingsSection);}
            });
            bottomNav.addView(item,new LinearLayout.LayoutParams(0,dp(54),1));
        }
        root.addView(bottomNav);
        addSpace(16);
        TextView footer = text("DioMasteR GOLD AI · Native Android · Μόνο DEMO", 10, MUTED, false);
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


    // Local execution loop: strategy stays in GoldAiAgent; broker execution is DEMO-only.
    private void startAiEngine() {
        if (mt5BaseUrl.isEmpty() || mt5Token.isEmpty()) {
            Toast.makeText(this, "Πρώτα σύνδεσε τον υπάρχοντα Vantage MT5 DEMO.", Toast.LENGTH_LONG).show();
            return;
        }
        autoExecutionMessage = "Έλεγχος Vantage MT5 DEMO και δικαιώματος εντολών…";
        render();
        new Thread(() -> {
            String failure = null;
            try {
                JSONObject status = new Mt5DemoClient(mt5BaseUrl, mt5Token).status();
                if (!"DEMO".equals(status.optString("account_mode"))
                        || !status.optBoolean("terminal_connected")
                        || !status.optBoolean("execution_enabled")) {
                    throw new IllegalStateException("Απαιτείται συνδεδεμένος Vantage MT5 DEMO με ενεργό server-side DEMO execution.");
                }
                String server = status.optString("server", "");
                if (!server.toLowerCase(Locale.US).contains("vantage") || !server.toLowerCase(Locale.US).contains("demo")) {
                    throw new IllegalStateException("Ο broker server δεν επιβεβαιώθηκε ως Vantage DEMO.");
                }
            } catch (Exception e) { failure = e.getMessage() == null ? "Αποτυχία ελέγχου MT5" : e.getMessage(); }
            final String error = failure;
            runOnUiThread(() -> {
                if (error != null) {
                    aiEngineStarted = false;
                    autoExecutionMessage = "ΜΠΛΟΚΑΡΙΣΜΕΝΟ · " + error;
                    Toast.makeText(this, autoExecutionMessage, Toast.LENGTH_LONG).show();
                } else {
                    aiEngineStarted = true;
                    autoExecutionMessage = "ΕΝΕΡΓΟ · εντολές μόνο στον Vantage MT5 DEMO";
                    Toast.makeText(this, "AUTO ενεργό στον υπάρχοντα Vantage MT5 DEMO.", Toast.LENGTH_LONG).show();
                    fetchPrice();
                }
                render();
            });
        }).start();
    }

    private void stopAiEngine() {
        aiEngineStarted = false;
        autoExecutionMessage = "STOP · δεν θα σταλούν νέες εντολές· οι ανοιχτές θέσεις μένουν στο MT5 με τα SL/TP τους";
        Toast.makeText(this, "Auto σταμάτησε. Δεν θα ανοίξουν νέες θέσεις.", Toast.LENGTH_LONG).show();
        render();
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

    // Diagnostics explain every local gate; GoldAiAgent strategy and thresholds remain unchanged.
    private void evaluateAutoSignal(JSONArray bars, long quoteTimestamp) {
        if (!aiEngineStarted) return;
        if (autoOrderInFlight) { setAutoDiagnostic("ΕΛΕΓΧΟΣ · προηγούμενη εντολή ακόμη σε εξέλιξη"); return; }
        if (!brokerChartActive) { setAutoDiagnostic("ΜΠΛΟΚΑΡΙΣΜΕΝΟ · δεν έχουν φορτωθεί broker OHLC candles"); return; }
        if (!quoteFresh()) { setAutoDiagnostic("ΜΠΛΟΚΑΡΙΣΜΕΝΟ · η τιμή broker είναι παλιά ή εκτός ορίου 15 δευτ."); return; }
        if (!mt5ExecutionEnabled) { setAutoDiagnostic("ΜΠΛΟΚΑΡΙΣΜΕΝΟ · ο server δεν επιτρέπει DEMO εντολές"); return; }
        if (bars == null || bars.length() < 2) { setAutoDiagnostic("ΑΝΑΜΟΝΗ · ανεπαρκή OHLC candles · timeframe=" + selectedTimeframe); return; }
        if (!aiSignal.ready) { setAutoDiagnostic("ΑΝΑΜΟΝΗ ΣΗΜΑΤΟΣ · timeframe=" + selectedTimeframe + " · candles=" + chartPrices.size() + " · " + aiSignal.reason); return; }
        if (!("BUY".equals(aiSignal.side) || "SELL".equals(aiSignal.side))) {
            setAutoDiagnostic("ΑΝΑΜΟΝΗ ΣΗΜΑΤΟΣ · timeframe=" + selectedTimeframe + " · candles=" + chartPrices.size() + " · " + aiSignal.side + " · " + aiSignal.reason);
            return;
        }
        if (aiSignal.stopLoss <= 0 || aiSignal.takeProfit <= 0) {
            setAutoDiagnostic("ΜΠΛΟΚΑΡΙΣΜΕΝΟ · το σήμα δεν έχει έγκυρα SL/TP");
            return;
        }
        JSONObject latestBar = bars.optJSONObject(bars.length() - 1);
        if (latestBar == null) { setAutoDiagnostic("ΜΠΛΟΚΑΡΙΣΜΕΝΟ · λείπει το τελευταίο OHLC candle"); return; }
        long barTime = (long)(latestBar.optDouble("timestamp", 0) * 1000L);
        if (barTime <= 0) { setAutoDiagnostic("ΜΠΛΟΚΑΡΙΣΜΕΝΟ · μη έγκυρη χρονική σήμανση candle"); return; }
        if (barTime == lastAutoSignalBar) { setAutoDiagnostic("ΑΝΑΜΟΝΗ · το σήμα αυτού του candle έχει ήδη ελεγχθεί"); return; }
        autoOrderInFlight = true;
        autoExecutionMessage = "Έλεγχος θέσεων και σήματος " + aiSignal.side + "…";
        final String side = aiSignal.side;
        final double sl = aiSignal.stopLoss;
        final double tp = aiSignal.takeProfit;
        final long signalBar = barTime;
        render();
        new Thread(() -> {
            String resultMessage;
            boolean submitted = false;
            try {
                Mt5DemoClient client = new Mt5DemoClient(mt5BaseUrl, mt5Token);
                JSONObject status = client.status();
                if (!"DEMO".equals(status.optString("account_mode"))
                        || !status.optBoolean("terminal_connected")
                        || !status.optBoolean("execution_enabled")) {
                    throw new IllegalStateException("DEMO execution/σύνδεση δεν επιβεβαιώθηκε ξανά.");
                }
                JSONObject posResponse = client.positions();
                JSONArray positions = posResponse.optJSONArray("positions");
                int botOpen = 0;
                if (positions != null) {
                    for (int i = 0; i < positions.length(); i++) {
                        JSONObject p = positions.optJSONObject(i);
                        if (p != null && p.optString("comment", "").startsWith("DioMasteR")) botOpen++;
                    }
                }
                if (botOpen > 0) {
                    resultMessage = "Αναμονή · υπάρχει ήδη ανοιχτή θέση DioMasteR στο MT5 DEMO";
                } else {
                    JSONObject q = client.quote(mt5Symbol);
                    double ref = q.optDouble("bid", 0);
                    long qTime = (long)(q.optDouble("time", 0) * 1000L);
                    if (ref <= 0 || qTime <= 0 || System.currentTimeMillis() - qTime > 120000L)
                        throw new IllegalStateException("Η τιμή broker δεν είναι φρέσκια.");
                    if (("BUY".equals(side) && !(sl < ref && ref < tp))
                            || ("SELL".equals(side) && !(tp < ref && ref < sl)))
                        throw new IllegalStateException("Το SL/TP του υπάρχοντος σήματος δεν συμφωνεί με την τελευταία τιμή broker.");
                    JSONObject order = client.order(mt5Symbol, side, 0.01, sl, tp);
                    submitted = true;
                    resultMessage = "ΕΝΤΟΛΗ DEMO " + side + " · " + mt5Symbol + " · 0.01 lot · ticket #" + order.optLong("order");
                }
            } catch (Exception e) {
                resultMessage = "Η εντολή DEMO μπλοκαρίστηκε: " + (e.getMessage() == null ? "άγνωστο σφάλμα" : e.getMessage());
            }
            final String message = resultMessage;
            final boolean sent = submitted;
            runOnUiThread(() -> {
                autoOrderInFlight = false;
                if (sent) lastAutoSignalBar = signalBar;
                autoExecutionMessage = message;
                Toast.makeText(this, message, Toast.LENGTH_LONG).show();
                loadMt5AccountData();
                render();
            });
        }).start();
    }


    private String cleanBridgeToken(String value) {
        if (value == null) return "";
        // Accept either a raw token or a pasted "Bearer <token>" header value.
        String cleaned = value.trim().replaceFirst("(?i)^Bearer\\s+", "");
        return cleaned.replaceAll("[\\r\\n\\t ]+", "");
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
                new int[]{0xFF171719, 0xFF0D0D0F, 0xFF141311});
        shell.setCornerRadius(dp(20));
        shell.setStroke(dp(1), 0xFF6E5425);
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
        TextView v = text(value, 17, color, true);
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

    private Button actionButton(String label, int color, Runnable action) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(11);
        b.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        b.setLetterSpacing(0.035f);
        b.setTextColor(color == GREEN || color == GOLD ? 0xFF100D07 : Color.WHITE);
        b.setAllCaps(false);
        b.setMinHeight(dp(48));
        b.setPadding(dp(10), dp(7), dp(10), dp(7));
        b.setBackground(round(color, 14, color == GREEN || color == GOLD ? color : 0xFF5C4A2B));
        b.setElevation(dp(2));
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
                new int[]{0xFF1B1710, color, 0xFF0D0D0F});
        d.setCornerRadius(dp(18));
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