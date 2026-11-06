package com.diomaster.goldai;

/** Deterministic, fail-closed paper-trading risk governor. */
public final class RiskGovernor {
    private RiskGovernor() {}

    public static final double RISK_PER_POSITION_USD = 2.0;
    public static final double STOP_DISTANCE = 8.0;
    public static final double MAX_OZ = 5.0;
    public static final int MAX_POSITIONS = 10;
    public static final double DAILY_LOSS_LIMIT = 200.0;
    public static final double MAX_DRAWDOWN = 0.05;

    public static String refusal(boolean quoteFresh, boolean paused, int openPositions,
                                 double equity, double peakEquity,
                                 double realisedToday, double floatingPnl) {
        if (!quoteFresh) return "Δεν υπάρχει φρέσκια τιμή αγοράς";
        if (paused) return "Οι νέες συναλλαγές είναι σε παύση";
        if (openPositions >= MAX_POSITIONS) return "Έφτασες το μέγιστο αριθμό ανοιχτών θέσεων";
        if (realisedToday + floatingPnl <= -DAILY_LOSS_LIMIT) return "Ενεργοποιήθηκε το ημερήσιο όριο ζημιάς";
        if (peakEquity > 0 && equity <= peakEquity * (1.0 - MAX_DRAWDOWN)) return "Ενεργοποιήθηκε το όριο μέγιστης πτώσης κεφαλαίου";
        return "";
    }

    public static double positionSize(double equity) {
        if (equity <= 0) return 0.0;
        double riskCash = Math.min(RISK_PER_POSITION_USD, equity * 0.0025);
        double sized = Math.floor((riskCash / STOP_DISTANCE) * 10.0) / 10.0;
        return Math.min(MAX_OZ, Math.max(0.0, sized));
    }
}
