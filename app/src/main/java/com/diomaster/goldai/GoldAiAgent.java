package com.diomaster.goldai;

import org.json.JSONArray;
import java.util.List;

/**
 * Android-side display adapter only.
 * Display-only adapter. The sole automatic strategy is cloud EMA 20/50/200 + ADX/ATR on M15 DEMO.
 * This class never generates local orders or competing trading signals.
 */
public final class GoldAiAgent {
    private GoldAiAgent() {}
    public static final class Signal {
        public final String side, reason;
        public final int confidence;
        public final double entry, stopLoss, takeProfit;
        public final boolean ready;
        private Signal(String s,String r,int c,double e,double sl,double tp,boolean ok) {
            side=s; reason=r; confidence=c; entry=e; stopLoss=sl; takeProfit=tp; ready=ok;
        }
        public static Signal waiting(String reason) {
            return new Signal("HOLD",reason,0,0,0,0,false);
        }
        public static Signal cloud(String side,String reason,int confidence,double entry,double stopLoss,double takeProfit) {
            boolean valid = ("BUY".equals(side) || "SELL".equals(side))
                    && entry > 0 && stopLoss > 0 && takeProfit > 0;
            return new Signal(valid ? side : "HOLD", reason, confidence,
                    valid ? entry : 0, valid ? stopLoss : 0, valid ? takeProfit : 0, valid);
        }
    }
    public static Signal analyze(List<Double> prices,double current) {
        return Signal.waiting("EMA CROSSOVER 20/50/200 · M15 · ADX14 · ATR14 · DEMO cloud owns all trade decisions.");
    }
    public static Signal analyze(JSONArray h1,JSONArray h4,double executableReference) {
        return Signal.waiting("EMA CROSSOVER 20/50/200 · M15 · ADX14 · ATR14 · DEMO cloud.");
    }
}
