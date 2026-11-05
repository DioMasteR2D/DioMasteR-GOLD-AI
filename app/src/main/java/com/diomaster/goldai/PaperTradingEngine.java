package com.diomaster.goldai;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

public final class PaperTradingEngine {
    public static final double START_BALANCE = 10000.0;
    public static final double RISK_PERCENT = 0.005;
    public static final double STOP_DISTANCE = 8.0;
    public static final double TARGET_DISTANCE = 16.0;
    public static final double MAX_OZ = 5.0;
    public static final int MAX_POSITIONS = 10;
    public static final double DAILY_LOSS_LIMIT = 200.0;
    public static final double MAX_DRAWDOWN = 0.05;
    private final SharedPreferences prefs;
    private JSONObject state;

    public static final class Result {
        public final boolean ok;
        public final String message;
        Result(boolean ok, String message) { this.ok = ok; this.message = message; }
    }

    public PaperTradingEngine(Context context) {
        prefs = context.getSharedPreferences("diomaster_gold_paper", Context.MODE_PRIVATE);
        load();
        rollDay();
    }

    private void load() {
        try {
            String raw = prefs.getString("state", null);
            state = raw == null ? freshState() : new JSONObject(raw);
            if (!state.has("positions")) state.put("positions", new JSONArray());
            if (!state.has("history")) state.put("history", new JSONArray());
            if (!state.has("events")) state.put("events", new JSONArray());
        } catch (Exception e) {
            state = freshState();
        }
        save();
    }

    private JSONObject freshState() {
        JSONObject s = new JSONObject();
        try {
            s.put("balance", START_BALANCE);
            s.put("peak", START_BALANCE);
            s.put("daily", 0.0);
            s.put("day", today());
            s.put("paused", false);
            s.put("nextId", 1);
            s.put("positions", new JSONArray());
            s.put("history", new JSONArray());
            s.put("events", new JSONArray());
        } catch (JSONException ignored) {}
        return s;
    }

    private String today() {
        return new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date());
    }

    private void rollDay() {
        if (!today().equals(state.optString("day"))) {
            try { state.put("day", today()); state.put("daily", 0.0); event("DAILY_RESET", "New local trading day"); }
            catch (JSONException ignored) {}
            save();
        }
    }

    private void save() {
        prefs.edit().putString("state", state.toString()).apply();
    }

    private JSONArray array(String key) {
        JSONArray a = state.optJSONArray(key);
        return a == null ? new JSONArray() : a;
    }

    private double floating(double price) {
        double total = 0.0;
        JSONArray positions = array("positions");
        for (int i = 0; i < positions.length(); i++) {
            JSONObject p = positions.optJSONObject(i);
            if (p == null) continue;
            double entry = p.optDouble("entry");
            double oz = p.optDouble("oz");
            total += ("BUY".equals(p.optString("side")) ? price - entry : entry - price) * oz;
        }
        return total;
    }

    public synchronized Result open(String side, double price, long quoteReceivedAt) {
        rollDay();
        if (!"BUY".equals(side) && !"SELL".equals(side)) return new Result(false, "Μη έγκυρη κατεύθυνση");
        JSONArray positions = array("positions");
        double equity = state.optDouble("balance", START_BALANCE) + floating(price);
        String refusal = RiskGovernor.refusal(
                price > 0 && System.currentTimeMillis() - quoteReceivedAt <= 120000L,
                state.optBoolean("paused"), positions.length(), equity,
                state.optDouble("peak", START_BALANCE), state.optDouble("daily"), floating(price));
        if (!refusal.isEmpty()) return new Result(false, refusal + ". New entries blocked.");
        double oz = RiskGovernor.positionSize(equity);
        if (oz < 0.1) return new Result(false, "Το μέγεθος θέσης είναι κάτω από το ελάχιστο.");
        JSONObject p = new JSONObject();
        try {
            int id = state.optInt("nextId", 1);
            state.put("nextId", id + 1);
            p.put("id", id);
            p.put("side", side);
            p.put("entry", price);
            p.put("oz", oz);
            p.put("sl", "BUY".equals(side) ? price - STOP_DISTANCE : price + STOP_DISTANCE);
            p.put("tp", "BUY".equals(side) ? price + TARGET_DISTANCE : price - TARGET_DISTANCE);
            p.put("openedAt", System.currentTimeMillis());
            positions.put(p);
            state.put("positions", positions);
            event("PAPER_OPEN_" + side, "Position #" + id + " · " + oz + " oz · ref " + price);
            save();
            return new Result(true, "Demo " + side + " opened · " + oz + " oz · risk cap " + money(oz * STOP_DISTANCE));
        } catch (JSONException e) {
            return new Result(false, "Δεν ήταν δυνατή η αποθήκευση της θέσης.");
        }
    }

    public synchronized void onQuote(double price) {
        if (price <= 0) return;
        rollDay();
        JSONArray positions = array("positions");
        for (int i = positions.length() - 1; i >= 0; i--) {
            JSONObject p = positions.optJSONObject(i);
            if (p == null) continue;
            boolean buy = "BUY".equals(p.optString("side"));
            double sl = p.optDouble("sl");
            double tp = p.optDouble("tp");
            String reason = buy ? (price <= sl ? "STOP LOSS" : price >= tp ? "TAKE PROFIT" : null)
                    : (price >= sl ? "STOP LOSS" : price <= tp ? "TAKE PROFIT" : null);
            if (reason != null) closeAtIndex(i, price, reason);
        }
        double markedEquity = state.optDouble("balance", START_BALANCE) + floating(price);
        if (markedEquity > state.optDouble("peak", START_BALANCE)) {
            try { state.put("peak", markedEquity); } catch (JSONException ignored) {}
        }
        save();
    }

    public synchronized Result close(int id, double price) {
        JSONArray positions = array("positions");
        for (int i = 0; i < positions.length(); i++) {
            JSONObject p = positions.optJSONObject(i);
            if (p != null && p.optInt("id") == id) {
                closeAtIndex(i, price, "MANUAL CLOSE");
                save();
                return new Result(true, "Position #" + id + " closed at reference price.");
            }
        }
        return new Result(false, "Position not found.");
    }

    public synchronized void closeAll(double price) {
        if (price <= 0) return;
        JSONArray positions = array("positions");
        for (int i = positions.length() - 1; i >= 0; i--) closeAtIndex(i, price, "CLOSE ALL");
        save();
    }

    private void closeAtIndex(int index, double price, String reason) {
        JSONArray positions = array("positions");
        JSONObject p = positions.optJSONObject(index);
        if (p == null) return;
        double entry = p.optDouble("entry");
        double oz = p.optDouble("oz");
        double pnl = ("BUY".equals(p.optString("side")) ? price - entry : entry - price) * oz;
        try {
            p.put("exit", price);
            p.put("pnl", pnl);
            p.put("reason", reason);
            p.put("closedAt", System.currentTimeMillis());
            state.put("balance", state.optDouble("balance", START_BALANCE) + pnl);
            state.put("daily", state.optDouble("daily") + pnl);
            state.put("peak", Math.max(state.optDouble("peak", START_BALANCE), state.optDouble("balance")));
            JSONArray oldHistory = array("history");
            JSONArray history = new JSONArray();
            history.put(p);
            for (int h = 0; h < oldHistory.length() && h < 99; h++) history.put(oldHistory.opt(h));
            state.put("history", history);
            positions.remove(index);
            state.put("positions", positions);
            event("PAPER_CLOSE", "Position #" + p.optInt("id") + " · " + reason + " · P/L " + money(pnl));
        } catch (JSONException ignored) {}
    }

    public synchronized void setPaused(boolean paused) {
        try { state.put("paused", paused); event(paused ? "PAUSED" : "RESUMED", paused ? "New paper entries disabled" : "Paper entries resumed"); }
        catch (JSONException ignored) {}
        save();
    }

    public synchronized void reset() {
        state = freshState();
        save();
    }

    private void event(String type, String detail) {
        JSONArray oldEvents = array("events");
        JSONArray events = new JSONArray();
        JSONObject e = new JSONObject();
        try {
            e.put("type", type); e.put("detail", detail); e.put("at", System.currentTimeMillis());
            events.put(e);
            for (int i = 0; i < oldEvents.length() && i < 99; i++) events.put(oldEvents.opt(i));
            state.put("events", events);
        } catch (JSONException ignored) {}
    }

    public synchronized JSONObject snapshot(double price) {
        rollDay();
        JSONObject out = new JSONObject();
        try {
            double fl = price > 0 ? floating(price) : 0.0;
            out.put("balance", state.optDouble("balance", START_BALANCE));
            out.put("equity", state.optDouble("balance", START_BALANCE) + fl);
            out.put("floating", fl);
            out.put("daily", state.optDouble("daily"));
            out.put("peak", state.optDouble("peak", START_BALANCE));
            out.put("paused", state.optBoolean("paused"));
            out.put("positions", new JSONArray(array("positions").toString()));
            out.put("history", new JSONArray(array("history").toString()));
            out.put("events", new JSONArray(array("events").toString()));
        } catch (JSONException ignored) {}
        return out;
    }

    public static String money(double value) {
        return (value < 0 ? "-$" : "$") + String.format(Locale.US, "%.2f", Math.abs(value));
    }
}
