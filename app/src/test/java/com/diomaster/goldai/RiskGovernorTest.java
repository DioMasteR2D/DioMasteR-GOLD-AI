package com.diomaster.goldai;

import org.junit.Test;
import static org.junit.Assert.*;

public class RiskGovernorTest {
    @Test public void sizesFromEquityAndCapsExposure() {
        assertEquals(5.0, RiskGovernor.positionSize(10000), 0.0001);
        assertEquals(3.1, RiskGovernor.positionSize(5000), 0.0001);
        assertEquals(0.0, RiskGovernor.positionSize(0), 0.0001);
    }

    @Test public void failsClosedForStaleQuoteAndPause() {
        assertEquals("No fresh market quote", RiskGovernor.refusal(false, false, 0, 10000, 10000, 0, 0));
        assertEquals("Trading is paused", RiskGovernor.refusal(true, true, 0, 10000, 10000, 0, 0));
    }

    @Test public void enforcesPositionAndLossLimits() {
        assertEquals("Maximum open positions reached", RiskGovernor.refusal(true, false, 3, 10000, 10000, 0, 0));
        assertEquals("Daily loss limit reached", RiskGovernor.refusal(true, false, 0, 9800, 10000, -190, -10));
        assertEquals("Maximum drawdown reached", RiskGovernor.refusal(true, false, 0, 9499, 10000, 0, 0));
        assertEquals("", RiskGovernor.refusal(true, false, 1, 10000, 10000, 0, 0));
    }
}
