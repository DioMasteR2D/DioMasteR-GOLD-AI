package com.diomaster.goldai;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
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
    private final int BG = 0xFF090A0D;
    private final int PANEL = 0xFF14161B;
    private final int GOLD = 0xFFD7AD54;
    private final int MUTED = 0xFF9296A0;
    private final int GREEN = 0xFF39C98A;
    private final int RED = 0xFFFF6570;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final GoldPriceClient priceClient = new GoldPriceClient();
    private final ArrayList<Double> chartPrices = new ArrayList<>();
    private PaperTradingEngine engine;
    private LinearLayout root;
    private ScrollView currentScroll;
    private double price = 0.0;
    private long quoteAt = 0L;
    private boolean fetching = false;
    private String feedMessage = "Σύνδεση με την τιμή χρυσού…";
    private String mt5Status = "ΜΗ ΣΥΝΔΕΔΕΜΕΝΗ";
    private String mt5BaseUrl = "";
    private String mt5Token = "";
    private String mt5Symbol = "XAUUSD";
    private boolean mt5ExecutionEnabled = false;
    private GoldAiAgent.Signal aiSignal = GoldAiAgent.Signal.waiting("Συλλογή δεδομένων αγοράς…");

    private final Runnable refreshLoop = new Runnable() {
        @Override public void run() {
            fetchPrice();
            handler.postDelayed(this, 30000L);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        engine = new PaperTradingEngine(this);
        android.content.SharedPreferences mt5Prefs = getSharedPreferences("diomaster_mt5_demo", MODE_PRIVATE);
        mt5BaseUrl = mt5Prefs.getString("base", "");
        mt5Token = mt5Prefs.getString("token", "");
        mt5Symbol = mt5Prefs.getString("symbol", "XAUUSD");
        mt5ExecutionEnabled = mt5Prefs.getBoolean("execution_enabled", false);
        mt5Status = mt5Prefs.getString("status", "ΜΗ ΣΥΝΔΕΔΕΜΕΝΗ");
        render();
        fetchPrice();
        handler.postDelayed(refreshLoop, 30000L);
    }

    @Override protected void onResume() {
        super.onResume();
        fetchPrice();
    }

    @Override protected void onDestroy() {
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

    private void fetchPrice() {
        if (fetching) return;
        fetching = true;
        new Thread(() -> priceClient.fetch(new GoldPriceClient.Callback() {
            @Override public void onPrice(double value, long receivedAt) {
                runOnUiThread(() -> {
                    fetching = false;
                    price = value;
                    quoteAt = receivedAt;
                    feedMessage = "Ζωντανή ενδεικτική τιμή · ενημέρωση " + new SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(new Date(receivedAt));
                    chartPrices.add(value);
                    while (chartPrices.size() > 90) chartPrices.remove(0);
                    aiSignal = GoldAiAgent.analyze(chartPrices, value);
                    engine.onQuote(value);
                    render();
                });
            }
            @Override public void onError(String message) {
                runOnUiThread(() -> {
                    fetching = false;
                    feedMessage = "Αδυναμία λήψης τιμής: " + message;
                    render();
                });
            }
        })).start();
    }

    private boolean quoteFresh() {
        return price > 0 && quoteAt > 0 && System.currentTimeMillis() - quoteAt <= 120000L;
    }

    private void openTrade(String side) {
        if (mt5ExecutionEnabled && !mt5BaseUrl.isEmpty() && !mt5Token.isEmpty()) { openMt5Trade(side); return; }
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

        int previousScrollY = currentScroll == null ? 0 : currentScroll.getScrollY();
        ScrollView scroll = new ScrollView(this);
        currentScroll = scroll;
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BG);
        scroll.addView(root);
        setContentView(scroll);
        scroll.post(() -> scroll.scrollTo(0, previousScrollY));

        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setOrientation(LinearLayout.HORIZONTAL);
        TextView brand = text("◆ DioMasteR GOLD AI", 19, GOLD, true);
        android.view.animation.AlphaAnimation glow = new android.view.animation.AlphaAnimation(0.72f, 1.0f);
        glow.setDuration(1100L); glow.setRepeatMode(android.view.animation.Animation.REVERSE); glow.setRepeatCount(android.view.animation.Animation.INFINITE);
        brand.startAnimation(glow);
        header.addView(brand, new LinearLayout.LayoutParams(0, -2, 1));
        TextView mode = text(mt5ExecutionEnabled ? "MT5 DEMO · ORDERS ON" : "PAPER MODE", 10, GREEN, true);
        mode.setPadding(dp(10), dp(7), dp(10), dp(7));
        mode.setBackground(round(0xFF143325, 24, 0xFF286D50));
        header.addView(mode);
        root.addView(header);
        addSpace(14);

        LinearLayout market = card();
        addLabel(market, "XAUUSD · SPOT PRICE SNAPSHOTS");
        TextView priceText = text(price > 0 ? "$" + String.format(Locale.US, "%,.2f", price) : "—", 34, GOLD, true);
        market.addView(priceText);
        TextView feed = text((quoteFresh() ? "● " : "● ") + feedMessage, 11, quoteFresh() ? GREEN : RED, false);
        market.addView(feed);
        GoldChartView chart = new GoldChartView(this);
        chart.setLayoutParams(new LinearLayout.LayoutParams(-1, dp(92)));
        for (double p : chartPrices) chart.addPrice(p);
        market.addView(chart);
        TextView chartNote = text("Ενδεικτική spot ροή ανά 30s · όχι ακόμη broker tick / OHLC feed.", 9, MUTED, false);
        chartNote.setPadding(0, dp(5), 0, 0);
        market.addView(chartNote);
        root.addView(market);
        addSpace(10);

        LinearLayout agent = card();
        addLabel(agent, "DIOMASTER AI AGENT · LIVE MARKET ANALYSIS");
        int signalColor = "BUY".equals(aiSignal.side) ? GREEN : "SELL".equals(aiSignal.side) ? RED : GOLD;
        String signalTitle = "BUY".equals(aiSignal.side) ? "▲ BUY SIGNAL" : "SELL".equals(aiSignal.side) ? "▼ SELL SIGNAL" : "HOLD · WAIT";
        TextView signal = text(signalTitle, 25, signalColor, true);
        if (aiSignal.ready && !"HOLD".equals(aiSignal.side)) {
            android.view.animation.AlphaAnimation pulse = new android.view.animation.AlphaAnimation(0.55f, 1.0f);
            pulse.setDuration(850L); pulse.setRepeatMode(android.view.animation.Animation.REVERSE);
            pulse.setRepeatCount(android.view.animation.Animation.INFINITE); signal.startAnimation(pulse);
        }
        agent.addView(signal);
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
        Button refreshAgent = actionButton("ΑΝΑΝΕΩΣΗ ΑΝΑΛΥΣΗΣ", 0xFF292C34, this::fetchPrice);
        agent.addView(refreshAgent);
        root.addView(agent);
        addSpace(10);

        JSONObject snap = engine.snapshot(quoteFresh() ? price : 0);
        LinearLayout metrics = new LinearLayout(this);
        metrics.setOrientation(LinearLayout.HORIZONTAL);
        metrics.addView(metric("PAPER ΚΕΦΑΛΑΙΟ", PaperTradingEngine.money(snap.optDouble("equity")), GOLD), weight());
        metrics.addView(metric("PAPER ΑΝΟΙΧΤΟ P/L", PaperTradingEngine.money(snap.optDouble("floating")), snap.optDouble("floating") >= 0 ? GREEN : RED), weight());
        root.addView(metrics);
        addSpace(8);
        LinearLayout metrics2 = new LinearLayout(this);
        metrics2.setOrientation(LinearLayout.HORIZONTAL);
        metrics2.addView(metric("ΚΛΕΙΣΜΕΝΟ P/L ΣΗΜΕΡΑ", PaperTradingEngine.money(snap.optDouble("daily")), snap.optDouble("daily") >= 0 ? GREEN : RED), weight());
        metrics2.addView(metric("ΑΝΟΙΧΤΕΣ ΘΕΣΕΙΣ", snap.optJSONArray("positions").length() + " / " + PaperTradingEngine.MAX_POSITIONS, GOLD), weight());
        root.addView(metrics2);
        addSpace(10);

        LinearLayout risk = card();
        addLabel(risk, "ΔΙΑΧΕΙΡΙΣΗ ΚΙΝΔΥΝΟΥ · ΕΝΕΡΓΗ");
        addRow(risk, "Ρίσκο ανά συναλλαγή", "0.5% of equity");
        addRow(risk, "Stop Loss / Take Profit", "$8 / $16");
        addRow(risk, "Μέγιστο μέγεθος θέσης", "5.0 oz");
        addRow(risk, "Ημερήσιο όριο ζημιάς", "$200");
        addRow(risk, "Μέγιστη πτώση κεφαλαίου", "5%");
        addRow(risk, "Νέες συναλλαγές", snap.optBoolean("paused") ? "ΣΕ ΠΑΥΣΗ" : "ΕΝΕΡΓΕΣ");
        TextView riskNote = text("Κάθε νέα εικονική συναλλαγή περνά από τον ίδιο αυτόματο έλεγχο κινδύνου. Παλιές ή ανύπαρκτες τιμές μπλοκάρουν τις νέες εισόδους.", 10, MUTED, false);
        riskNote.setPadding(0, dp(8), 0, 0);
        risk.addView(riskNote);
        root.addView(risk);
        addSpace(10);

        LinearLayout actions = card();
        addLabel(actions, mt5ExecutionEnabled ? "VANTAGE MT5 DEMO · ΧΕΙΡΟΚΙΝΗΤΕΣ ΕΝΤΟΛΕΣ" : "PAPER TRADING · ΕΙΚΟΝΙΚΕΣ ΣΥΝΑΛΛΑΓΕΣ");
        LinearLayout actionRow = new LinearLayout(this);
        actionRow.setOrientation(LinearLayout.HORIZONTAL);
        actionRow.addView(actionButton("BUY", GREEN, () -> openTrade("BUY")), weight());
        actionRow.addView(actionButton("SELL", RED, () -> openTrade("SELL")), weight());
        actions.addView(actionRow);
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
        root.addView(positions);
        addSpace(10);

        LinearLayout history = card();
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
        root.addView(history);
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
        addLabel(connections, "ΣΥΝΔΕΣΕΙΣ & ΚΑΤΑΣΤΑΣΗ ΣΥΣΤΗΜΑΤΟΣ");
        addRow(connections, "Δεδομένα αγοράς", quoteFresh() ? "ΤΙΜΗ SPOT ONLINE" : "ΑΝΑΜΟΝΗ / ΠΑΛΙΑ ΤΙΜΗ", quoteFresh() ? GREEN : RED);
        addRow(connections, "Γέφυρα MT5 Demo", mt5Status, mt5Status.startsWith("DEMO") ? GREEN : MUTED);
        addRow(connections, "Μηχανή σημάτων AI", aiSignal.ready ? aiSignal.side + " · " + aiSignal.confidence + "%" : "ΣΥΛΛΟΓΗ ΔΕΔΟΜΕΝΩΝ", aiSignal.ready ? GOLD : MUTED);
        addRow(connections, "Εντολές MT5 DEMO", mt5ExecutionEnabled ? "ΕΝΕΡΓΕΣ · ΜΟΝΟ ΜΕ ΕΠΙΒΕΒΑΙΩΣΗ DEMO" : "ΑΝΑΜΟΝΗ ΣΥΝΔΕΣΗΣ", mt5ExecutionEnabled ? GREEN : GOLD);
        TextView bridgeNote = text("Η σύνδεση γίνεται μέσω MetaApi Cloud προς τον Vantage MT5 DEMO, χωρίς δικό σου Windows VPS. Τα BUY/SELL στέλνουν εντολές μόνο όταν ο server επιβεβαιώνει DEMO, με υποχρεωτικά Stop Loss και Take Profit. Η αυτόματη στρατηγική cloud δεν έχει ενεργοποιηθεί ακόμη.", 10, MUTED, false);
        bridgeNote.setPadding(0, dp(8), 0, dp(8));
        connections.addView(bridgeNote);
        Button bridgeInfo = actionButton("ΣΥΝΔΕΣΗ METAAPI CLOUD · VANTAGE DEMO", 0xFF292C34, this::configureMt5Bridge);
        connections.addView(bridgeInfo);
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
        addSpace(16);
        TextView footer = text("DioMasteR GOLD AI · Native Android · Μόνο DEMO", 10, MUTED, false);
        footer.setGravity(Gravity.CENTER);
        root.addView(footer);
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
        endpoint.setText(mt5BaseUrl);
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
        TextView note = text("Βάλε το HTTPS URL του cloud bridge και το DIO_BRIDGE_TOKEN από τα Render secrets. Τα MetaApi credentials δεν μπαίνουν στην εφαρμογή. Ο server απορρίπτει κάθε λογαριασμό που δεν επιβεβαιώνεται ως DEMO.", 11, MUTED, false);
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
            String secret = token.getText().toString().trim();
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
                    if (code < 200 || code >= 300) throw new IllegalStateException("Bridge HTTP " + code);
                    JSONObject status = new JSONObject(body.toString());
                    if (!"DEMO".equals(status.optString("account_mode")) || !status.optBoolean("terminal_connected")) {
                        throw new IllegalStateException("Δεν επιβεβαιώθηκε ασφαλής σύνδεση DEMO.");
                    }
                    JSONArray allowed = status.optJSONArray("allowed_symbols");
                    String selectedSymbol = allowed != null && allowed.length()>0 ? allowed.optString(0,"XAUUSD") : "XAUUSD";
                    boolean execEnabled = status.optBoolean("execution_enabled");
                    String display = "DEMO · " + status.optString("server", "MT5") + " · #" + status.optString("account_login") + (execEnabled ? " · ORDERS ON" : " · READ ONLY");
                    getSharedPreferences("diomaster_mt5_demo", MODE_PRIVATE).edit().putString("base",base).putString("token",secret).putString("symbol",selectedSymbol).putBoolean("execution_enabled",execEnabled).putString("status",display).apply();
                    mt5BaseUrl=base; mt5Token=secret; mt5Symbol=selectedSymbol; mt5ExecutionEnabled=execEnabled;
                    result = display;
                } catch (Exception e) {
                    result = "ΑΠΟΤΥΧΙΑ ΣΥΝΔΕΣΗΣ";
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

    private LinearLayout card() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(14), dp(14), dp(14), dp(14));
        box.setBackground(round(PANEL, 16, 0xFF292C34));
        return box;
    }

    private LinearLayout metric(String label, String value, int color) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(12), dp(12), dp(12), dp(12));
        box.setBackground(round(PANEL, 13, 0xFF292C34));
        box.addView(text(label, 9, MUTED, true));
        TextView v = text(value, 17, color, true);
        v.setPadding(0, dp(5), 0, 0);
        box.addView(v);
        return box;
    }

    private void addLabel(LinearLayout box, String value) {
        TextView t = text(value, 11, GOLD, true);
        t.setPadding(0, 0, 0, dp(10));
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
        line.setBackgroundColor(0xFF292C34);
        box.addView(line, new LinearLayout.LayoutParams(-1, dp(1)));
    }

    private Button actionButton(String label, int color, Runnable action) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(12);
        b.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        b.setTextColor(color == GREEN || color == GOLD ? Color.BLACK : Color.WHITE);
        b.setAllCaps(false);
        b.setMinHeight(dp(46));
        b.setPadding(dp(8), dp(6), dp(8), dp(6));
        b.setBackground(round(color, 11, color));
        b.setOnClickListener(v -> action.run());
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(dp(3), dp(5), dp(3), dp(3));
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
