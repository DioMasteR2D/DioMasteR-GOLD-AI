package com.diomaster.goldai;

import java.util.List;
import java.util.Locale;

/**
 * On-device XAUUSD signal assistant.
 * Uses broker candle closes when MT5 is connected. The rules and thresholds are
 * intentionally unchanged; diagnostics expose why a setup is or is not confirmed.
 */
public final class GoldAiAgent {
    private GoldAiAgent() {}

    public static final class Signal {
        public final String side;
        public final String reason;
        public final int confidence;
        public final double entry;
        public final double stopLoss;
        public final double takeProfit;
        public final boolean ready;

        private Signal(String side, String reason, int confidence, double entry,
                       double stopLoss, double takeProfit, boolean ready) {
            this.side = side;
            this.reason = reason;
            this.confidence = confidence;
            this.entry = entry;
            this.stopLoss = stopLoss;
            this.takeProfit = takeProfit;
            this.ready = ready;
        }

        public static Signal waiting(String reason) {
            return new Signal("HOLD", reason, 0, 0, 0, 0, false);
        }
    }

    public static Signal analyze(List<Double> prices, double current) {
        if (prices == null || prices.size() < 24 || current <= 0) {
            int count = prices == null ? 0 : prices.size();
            return Signal.waiting("ΑΝΕΠΑΡΚΗ ΔΕΔΟΜΕΝΑ · Μετρήσεις: " + count
                    + "/24 · απαιτούνται τουλάχιστον 24 έγκυρες τιμές και θετική τρέχουσα τιμή.");
        }

        double fast = ema(prices, 6);
        double slow = ema(prices, 15);
        int n = prices.size();
        int from = Math.max(0, n - 13);
        double high = -Double.MAX_VALUE;
        double low = Double.MAX_VALUE;
        double movement = 0;
        int changes = 0;
        for (int i = from; i < n - 1; i++) {
            double v = prices.get(i);
            high = Math.max(high, v);
            low = Math.min(low, v);
            if (i > from) {
                movement += Math.abs(v - prices.get(i - 1));
                changes++;
            }
        }
        double volatility = changes == 0 ? 0 : movement / changes;
        double floor = Math.max(0.35, volatility * 1.8);
        double breakoutBuffer = Math.max(0.08, volatility * 0.12);
        boolean upTrend = fast > slow && current > prices.get(n - 5);
        boolean downTrend = fast < slow && current < prices.get(n - 5);
        boolean breakoutUp = current > high + breakoutBuffer;
        boolean breakoutDown = current < low - breakoutBuffer;

        String metrics = "ΔΙΑΓΝΩΣΗ · " + n + " candles | EMA6 " + fmt(fast)
                + " / EMA15 " + fmt(slow) + " | εύρος " + fmt(low) + "–" + fmt(high)
                + " | τιμή " + fmt(current) + " | buffer " + fmt(breakoutBuffer);

        if (upTrend && breakoutUp) {
            int score = score(Math.abs(fast - slow), volatility, current - high);
            double sl = current - floor;
            return new Signal("BUY", "ΕΠΙΒΕΒΑΙΩΜΕΝΟ BUY · Ανοδική EMA τάση και διάσπαση πρόσφατου εύρους. "
                    + metrics + " | απόσταση διάσπασης " + fmt(current - high)
                    + " | επιβεβαίωσε spread και νέα τιμή πριν από εκτέλεση.",
                    score, current, sl, current + floor * 1.8, true);
        }
        if (downTrend && breakoutDown) {
            int score = score(Math.abs(fast - slow), volatility, low - current);
            double sl = current + floor;
            return new Signal("SELL", "ΕΠΙΒΕΒΑΙΩΜΕΝΟ SELL · Καθοδική EMA τάση και διάσπαση πρόσφατου εύρους. "
                    + metrics + " | απόσταση διάσπασης " + fmt(low - current)
                    + " | επιβεβαίωσε spread και νέα τιμή πριν από εκτέλεση.",
                    score, current, sl, current - floor * 1.8, true);
        }

        String trend = fast > slow ? "ήπια ανοδική" : fast < slow ? "ήπια καθοδική" : "ουδέτερη";
        String blockers = (upTrend ? "UPTREND ΝΑΙ" : "UPTREND ΟΧΙ") + " · "
                + (downTrend ? "DOWNTREND ΝΑΙ" : "DOWNTREND ΟΧΙ") + " · "
                + (breakoutUp ? "BREAKOUT UP ΝΑΙ" : "BREAKOUT UP ΟΧΙ") + " · "
                + (breakoutDown ? "BREAKOUT DOWN ΝΑΙ" : "BREAKOUT DOWN ΟΧΙ");
        return new Signal("HOLD", "HOLD · Δεν υπάρχει επιβεβαιωμένο breakout. Τάση: " + trend
                + ". " + blockers + ". " + metrics
                + " | απαιτείται τιμή πάνω από " + fmt(high + breakoutBuffer)
                + " για breakout UP ή κάτω από " + fmt(low - breakoutBuffer)
                + " για breakout DOWN.", 0, 0, 0, 0, true);
    }

    private static String fmt(double value) {
        return String.format(Locale.US, "%.2f", value);
    }

    private static double ema(List<Double> values, int period) {
        int start = Math.max(0, values.size() - period * 3);
        double alpha = 2.0 / (period + 1.0);
        double result = values.get(start);
        for (int i = start + 1; i < values.size(); i++) {
            result = values.get(i) * alpha + result * (1.0 - alpha);
        }
        return result;
    }

    private static int score(double trendGap, double volatility, double breakoutDistance) {
        double denominator = Math.max(0.15, volatility);
        int value = 62 + (int) Math.min(17, (trendGap / denominator) * 5.0)
                + (int) Math.min(12, (breakoutDistance / denominator) * 3.0);
        return Math.min(91, Math.max(62, value));
    }
}
