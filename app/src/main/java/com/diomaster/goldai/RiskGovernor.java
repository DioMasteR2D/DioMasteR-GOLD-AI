package com.diomaster.goldai;

/** Deterministic, fail-closed paper-trading risk governor. */
public final class RiskGovernor {
    private RiskGovernor() {}

    public static final double RISK_PERCENT = 0.005;
    public static final double STOP_DISTANCE = 8.0;
    public static final double MAX_OZ = 5.0;
    public static final int MAX_POSITIONS = 3;
    public static final double DAILY_LOSS_LIMIT = 200.0;
    public static final double MAX_DRAWDOWN = 0.05;

    public static String refusal(boolean quoteFresh, boolean paused, int openPositions,
                                 double equity, double peakEquity,
                                 double realisedToday, double floatingPnl) {
        if (!quoteFresh) return "No fresh market quote";
        if (paused) return "Trading is paused";
        if (openPositions >= MAX_POSITIONS) return "Maximum open positions reached";
        if (realisedToday + floatingPnl <= -DAILY_LOSS_LIMIT) return "Daily loss limit reached";
        if (peakEquity > 0 && equity <= peakEquity * (1.0 - MAX_DRAWDOWN)) return "Maximum drawdown reached";
        return "";
    }

    public static double positionSize(double equity) {
        if (equity <= 0) return 0.0;
        double riskCash = equity * RISK_PERCENT;
        double sized = Math.floor((riskCash / STOP_DISTANCE) * 10.0) / 10.0;
        return Math.min(MAX_OZ, Math.max(0.0, sized));
    }
}
