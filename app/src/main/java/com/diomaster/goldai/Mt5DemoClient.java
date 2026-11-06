package com.diomaster.goldai;

import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.UUID;

public final class Mt5DemoClient {
    private final String base;
    private final String token;

    public Mt5DemoClient(String base, String token) {
        this.base = base.replaceAll("/+$", "");
        this.token = token == null ? "" : token.trim();
        if (this.token.indexOf("\r") >= 0 || this.token.indexOf("\n") >= 0)
            throw new IllegalArgumentException("Το bridge token περιέχει μη έγκυρους χαρακτήρες.");
    }

    private JSONObject request(String method, String path, JSONObject payload) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(base + path).openConnection();
        try {
            c.setRequestMethod(method);
            c.setConnectTimeout(8000);
            c.setReadTimeout(12000);
            c.setRequestProperty("Authorization", "Bearer " + token);
            c.setRequestProperty("Accept", "application/json");
            if (payload != null) {
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                OutputStream out = c.getOutputStream();
                out.write(payload.toString().getBytes("UTF-8"));
                out.close();
            }

            int code = c.getResponseCode();
            InputStream stream = code >= 200 && code < 300 ? c.getInputStream() : c.getErrorStream();
            if (stream == null) throw new IllegalStateException("MT5 bridge HTTP " + code + ": κενή απάντηση.");
            BufferedReader reader = new BufferedReader(new InputStreamReader(stream, "UTF-8"));
            StringBuilder body = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) body.append(line);
            reader.close();

            String raw = body.toString().trim();
            if (raw.isEmpty()) throw new IllegalStateException("MT5 bridge HTTP " + code + ": κενή απάντηση.");
            if (raw.startsWith("<") || raw.regionMatches(true, 0, "<!DOCTYPE", 0, 9)
                    || raw.regionMatches(true, 0, "<html", 0, 5)) {
                throw new IllegalStateException("Το MT5 bridge επέστρεψε HTML αντί για JSON (HTTP "
                        + code + "). Έλεγξε το Base URL του Render, όχι το TickerAll API key.");
            }

            JSONObject json;
            try {
                json = new JSONObject(raw);
            } catch (Exception parseError) {
                throw new IllegalStateException("Μη έγκυρη JSON απάντηση από MT5 bridge (HTTP " + code + ").");
            }
            if (code < 200 || code >= 300)
                throw new IllegalStateException(json.optString("detail", "MT5 bridge HTTP " + code));
            return json;
        } finally {
            c.disconnect();
        }
    }

    public JSONObject status() throws Exception { return request("GET", "/v1/status", null); }
    public JSONObject quote(String symbol) throws Exception { return request("GET", "/v1/quote/" + symbol, null); }
    public JSONObject positions() throws Exception { return request("GET", "/v1/positions", null); }
    public JSONObject candles(String symbol, String timeframe, int hours) throws Exception {
        return request("GET", "/v1/candles/" + symbol + "?timeframe=" + timeframe + "&hours=" + hours, null);
    }
    public JSONObject history(String symbol, int limit) throws Exception {
        return request("GET", "/v1/history?symbol=" + symbol + "&limit=" + limit, null);
    }
    public JSONObject autoStart() throws Exception { return request("POST", "/v1/auto/start", new JSONObject()); }
    public JSONObject autoStop() throws Exception { return request("POST", "/v1/auto/stop", new JSONObject()); }
    public JSONObject autoStatus() throws Exception { return request("GET", "/v1/auto/status", null); }
    public JSONObject order(String symbol, String side, double volume, double sl, double tp) throws Exception {
        JSONObject p = new JSONObject();
        p.put("symbol", symbol);
        p.put("side", side);
        p.put("volume", volume);
        p.put("stop_loss", sl);
        p.put("take_profit", tp);
        p.put("client_order_id", "android-" + UUID.randomUUID().toString());
        return request("POST", "/v1/order", p);
    }
    public JSONObject close(long ticket) throws Exception {
        return request("POST", "/v1/positions/" + ticket + "/close", new JSONObject());
    }
}
