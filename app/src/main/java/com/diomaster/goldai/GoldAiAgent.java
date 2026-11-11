package com.diomaster.goldai;

import org.json.JSONArray;
import org.json.JSONObject;
import java.util.Calendar;
import java.util.Locale;
import java.util.TimeZone;

/**
 * XAUUSD Phase 1 strategy ported from a1shmuk/xauusd-algo-trader.
 * AUTO signals use completed H1 candles only and a completed H4 EMA50 filter.
 * Swing-point SL refinement is intentionally omitted: the source implementation
 * reads future candles to confirm pivots, which would introduce look-ahead bias.
 */
public final class GoldAiAgent {
    private GoldAiAgent() {}
    public static final class Signal {
        public final String side, reason;
        public final int confidence;
        public final double entry, stopLoss, takeProfit;
        public final boolean ready;
        private Signal(String s,String r,int c,double e,double sl,double tp,boolean ok){
            side=s;reason=r;confidence=c;entry=e;stopLoss=sl;takeProfit=tp;ready=ok;
        }
        public static Signal waiting(String r){return new Signal("HOLD",r,0,0,0,0,false);}
    }

    /** Kept for read-only chart diagnostics; AUTO uses the H1/H4 overload below. */
    public static Signal analyze(java.util.List<Double> prices,double current){
        return Signal.waiting("AUTO STRATEGY: απαιτούνται κλεισμένα H1/H4 broker candles.");
    }

    public static Signal analyze(JSONArray h1, JSONArray h4, double executableReference) {
        if (h1 == null || h1.length() < 30 || h4 == null || h4.length() < 52)
            return Signal.waiting("EMA 9/21 · Αναμονή επαρκών H1/H4 candles (30 H1 και 52 H4).");
        int n=h1.length(), hn=h4.length();
        // The final row is the currently forming candle. Never use it for indicators/signals.
        int last=n-2, prev=n-3, h4Last=hn-2;
        if(last<28 || prev<0 || h4Last<50 || executableReference<=0)
            return Signal.waiting("EMA 9/21 · Ανεπαρκή candles ή τιμή εκτέλεσης.");
        double[] close=new double[last+1], high=new double[last+1], low=new double[last+1];
        for(int i=0;i<=last;i++){
            JSONObject b=h1.optJSONObject(i); if(b==null)return Signal.waiting("H1 candle μη έγκυρο.");
            close[i]=b.optDouble("close",0); high[i]=b.optDouble("high",0); low[i]=b.optDouble("low",0);
            if(close[i]<=0 || high[i]<=0 || low[i]<=0)return Signal.waiting("H1 OHLC μη έγκυρα.");
        }
        double[] h4c=new double[h4Last+1];
        for(int i=0;i<=h4Last;i++){JSONObject b=h4.optJSONObject(i); if(b==null)return Signal.waiting("H4 candle μη έγκυρο."); h4c[i]=b.optDouble("close",0); if(h4c[i]<=0)return Signal.waiting("H4 close μη έγκυρο.");}
        double ema9Prev=ema(close,prev,9), ema21Prev=ema(close,prev,21);
        double ema9Now=ema(close,last,9), ema21Now=ema(close,last,21);
        boolean buyCross=ema9Prev<=ema21Prev && ema9Now>ema21Now;
        boolean sellCross=ema9Prev>=ema21Prev && ema9Now<ema21Now;
        if(!buyCross&&!sellCross)return Signal.waiting("H1 EMA 9/21 · Δεν υπάρχει νέο crossover σε κλεισμένο κερί.");
        String side=buyCross?"BUY":"SELL";
        double rsi=rsi(close,last,14), atr=atr(high,low,close,last,14);
        double h4ema=ema(h4c,h4Last,50);
        boolean h4Bull=h4c[h4Last]>h4ema;
        if(buyCross && !(rsi>50 && rsi<65))
            return Signal.waiting(String.format(Locale.US,"BUY μπλοκαρίστηκε · RSI %.1f (απαιτείται >50 και <65).",rsi));
        if(sellCross && !(rsi<50 && rsi>35))
            return Signal.waiting(String.format(Locale.US,"SELL μπλοκαρίστηκε · RSI %.1f (απαιτείται <50 και >35).",rsi));
        if(buyCross&&!h4Bull)return Signal.waiting("BUY μπλοκαρίστηκε · H4 close κάτω από EMA50.");
        if(sellCross&&h4Bull)return Signal.waiting("SELL μπλοκαρίστηκε · H4 close πάνω από EMA50.");
        Calendar utc=Calendar.getInstance(TimeZone.getTimeZone("UTC"),Locale.US);
        int day=utc.get(Calendar.DAY_OF_WEEK), hour=utc.get(Calendar.HOUR_OF_DAY);
        if(day==Calendar.SATURDAY||day==Calendar.SUNDAY||hour<13||hour>=17)
            return Signal.waiting("Σήμα "+side+" μπλοκαρίστηκε · επιτρέπεται μόνο Δευτέρα–Παρασκευή 13:00–16:59 UTC.");
        if((Double.isNaN(atr)||Double.isInfinite(atr))||atr<=0)return Signal.waiting("ATR14 μη έγκυρο.");
        double sl=side.equals("BUY")?executableReference-2.0*atr:executableReference+2.0*atr;
        double tp=side.equals("BUY")?executableReference+3.0*atr:executableReference-3.0*atr;
        String why=String.format(Locale.US,"ORIGINAL EMA 9/21 H1 · RSI14 %.1f · ATR14 %.2f · H4 EMA50 %.2f · Session 13–17 UTC · SL 2×ATR / TP 3×ATR · 1:1.5",rsi,atr,h4ema);
        return new Signal(side,why,75,executableReference,sl,tp,true);
    }
    private static double ema(double[] v,int end,int period){
        double a=2.0/(period+1.0), out=v[0];
        for(int i=1;i<=end;i++)out=v[i]*a+out*(1-a);
        return out;
    }
    private static double rsi(double[] c,int end,int period){
        double gain=0,loss=0;
        for(int i=1;i<=period;i++){double d=c[i]-c[i-1];gain+=Math.max(0,d);loss+=Math.max(0,-d);}
        gain/=period;loss/=period;
        for(int i=period+1;i<=end;i++){double d=c[i]-c[i-1];gain=(gain*(period-1)+Math.max(0,d))/period;loss=(loss*(period-1)+Math.max(0,-d))/period;}
        if(loss==0)return 100;return 100.0-(100.0/(1.0+gain/loss));
    }
    private static double atr(double[] h,double[] l,double[] c,int end,int period){
        double value=0;
        for(int i=1;i<=period;i++)value+=Math.max(h[i]-l[i],Math.max(Math.abs(h[i]-c[i-1]),Math.abs(l[i]-c[i-1])));
        value/=period;
        for(int i=period+1;i<=end;i++){double tr=Math.max(h[i]-l[i],Math.max(Math.abs(h[i]-c[i-1]),Math.abs(l[i]-c[i-1])));value=(value*(period-1)+tr)/period;}
        return value;
    }
}
