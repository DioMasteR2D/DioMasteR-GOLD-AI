package com.diomaster.goldai;

import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

public final class GoldPriceClient {
    public interface Callback {
        void onPrice(double price, long receivedAt);
        void onError(String message);
    }

    public void fetch(Callback callback) {
        HttpURLConnection connection = null;
        try {
            URL url = new URL("https://api.gold-api.com/price/XAU");
            connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(8000);
            connection.setRequestProperty("Accept", "application/json");
            int code = connection.getResponseCode();
            if (code < 200 || code >= 300) throw new IllegalStateException("HTTP " + code);
            BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream(), "UTF-8"));
            StringBuilder body = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) body.append(line);
            reader.close();
            JSONObject json = new JSONObject(body.toString());
            double price = json.optDouble("price", Double.NaN);
            if (!Double.isFinite(price)) price = json.optDouble("ask", Double.NaN);
            if (!Double.isFinite(price)) price = json.optDouble("value", Double.NaN);
            if (!Double.isFinite(price) || price < 100 || price > 100000) {
                throw new IllegalStateException("Invalid XAU price response");
            }
            callback.onPrice(price, System.currentTimeMillis());
        } catch (Exception e) {
            callback.onError(e.getMessage() == null ? "Price feed unavailable" : e.getMessage());
        } finally {
            if (connection != null) connection.disconnect();
        }
    }
}
