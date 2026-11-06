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
            connection.setRequestProperty("User-Agent", "DioMasteR-GOLD-AI/1.0");
            int code = connection.getResponseCode();
            BufferedReader reader = new BufferedReader(new InputStreamReader(
                    code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream(), "UTF-8"));
            StringBuilder body = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) body.append(line);
            reader.close();

            if (code < 200 || code >= 300) throw new IllegalStateException("Gold spot API HTTP " + code);
            String raw = body.toString().trim();
            if (raw.isEmpty()) throw new IllegalStateException("Η πηγή spot επέστρεψε κενή απάντηση.");
            if (raw.startsWith("<") || raw.regionMatches(true, 0, "<!DOCTYPE", 0, 9)
                    || raw.regionMatches(true, 0, "<html", 0, 5)) {
                throw new IllegalStateException("Η πηγή spot επέστρεψε HTML αντί για JSON. Δεν χρησιμοποιείται αυτή η απάντηση.");
            }

            JSONObject json = new JSONObject(raw);
            double price = json.optDouble("price", Double.NaN);
            if (!isValid(price)) price = json.optDouble("ask", Double.NaN);
            if (!isValid(price)) price = json.optDouble("value", Double.NaN);
            if (!isValid(price) || price < 100 || price > 100000) {
                throw new IllegalStateException("Η πηγή spot δεν επέστρεψε έγκυρη τιμή XAU.");
            }
            callback.onPrice(price, System.currentTimeMillis());
        } catch (Exception e) {
            callback.onError(e.getMessage() == null ? "Η πηγή τιμής δεν είναι διαθέσιμη" : e.getMessage());
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private boolean isValid(double value) {
        return !Double.isNaN(value) && !Double.isInfinite(value);
    }
}
