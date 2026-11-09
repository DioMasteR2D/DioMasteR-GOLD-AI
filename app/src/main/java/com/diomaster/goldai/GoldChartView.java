package com.diomaster.goldai;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.view.View;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;

public final class GoldChartView extends View {
    private static final int UP=0xFF00D98B, DOWN=0xFFFF4968, GOLD=0xFFFFC84A, BLUE=0xFF28B8FF;
    private final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint grid=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final List<Bar> bars=new ArrayList<>();
    private final List<Double> fallback=new ArrayList<>();
    private static final class Bar {
        double o,h,l,c,v;
        Bar(double o,double h,double l,double c,double v){this.o=o;this.h=h;this.l=l;this.c=c;this.v=v;}
    }
    public GoldChartView(Context context) {
        super(context);
        grid.setColor(0xFF292D36); grid.setStrokeWidth(1f);
        setLayerType(View.LAYER_TYPE_SOFTWARE,null);
    }
    public void setCandles(JSONArray rows) {
        bars.clear(); fallback.clear();
        if(rows!=null) for(int i=0;i<rows.length();i++) {
            JSONObject x=rows.optJSONObject(i); if(x==null) continue;
            double o=x.optDouble("open",Double.NaN),h=x.optDouble("high",Double.NaN),
                l=x.optDouble("low",Double.NaN),c=x.optDouble("close",Double.NaN),v=x.optDouble("tick_volume",0);
            if(Double.isFinite(o)&&Double.isFinite(h)&&Double.isFinite(l)&&Double.isFinite(c)&&h>=l&&o>0&&c>0)
                bars.add(new Bar(o,h,l,c,v));
        }
        invalidate();
    }
    public void addPrice(double value) {
        if(value<=0||!Double.isFinite(value)) return;
        fallback.add(value); while(fallback.size()>90) fallback.remove(0);
        invalidate();
    }
    private double ema(int end,int period) {
        int start=Math.max(0,end-period*3); double a=2.0/(period+1.0);
        double e=bars.get(start).c;
        for(int i=start+1;i<=end;i++) e=bars.get(i).c*a+e*(1-a);
        return e;
    }
    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float w=getWidth(),h=getHeight();
        for(int i=1;i<=4;i++) canvas.drawLine(0,h*i/5f,w,h*i/5f,grid);
        if(bars.size()>=2) drawBars(canvas,w,h);
        else drawFallback(canvas,w,h);
    }
    private void drawBars(Canvas c,float w,float h) {
        int n=bars.size(); double min=Double.MAX_VALUE,max=-Double.MAX_VALUE,maxVol=1;
        for(Bar b:bars){min=Math.min(min,b.l);max=Math.max(max,b.h);maxVol=Math.max(maxVol,b.v);}
        double pad=(max-min)*0.10; if(pad==0)pad=Math.max(0.1,max*0.0002);
        min-=pad;max+=pad; final double range=max-min;
        float top=8,bottom=h*0.78f,chartH=bottom-top;
        float step=w/n,body=Math.max(2f,Math.min(11f,step*0.58f));
        // Tick-volume bars.
        p.setStyle(Paint.Style.FILL);
        for(int i=0;i<n;i++){
            Bar b=bars.get(i); float x=(i+.5f)*step;
            p.setColor(b.c>=b.o?0x5532C98B:0x55FF4968);
            float vh=(float)(Math.max(0,b.v)/maxVol)*(h*.13f);
            c.drawRect(x-body*.45f,h-3-vh,x+body*.45f,h-3,p);
        }
        // EMA overlays.
        Path e6=new Path(),e15=new Path();
        for(int i=0;i<n;i++){
            float x=(i+.5f)*step;
            float y6=(float)(bottom-(ema(i,6)-min)/range*chartH);
            float y15=(float)(bottom-(ema(i,15)-min)/range*chartH);
            if(i==0){e6.moveTo(x,y6);e15.moveTo(x,y15);}else{e6.lineTo(x,y6);e15.lineTo(x,y15);}
        }
        // Candlestick wicks and bodies.
        for(int i=0;i<n;i++){
            Bar b=bars.get(i); float x=(i+.5f)*step;
            float yo=(float)(bottom-(b.o-min)/range*chartH);
            float yc=(float)(bottom-(b.c-min)/range*chartH);
            float yh=(float)(bottom-(b.h-min)/range*chartH);
            float yl=(float)(bottom-(b.l-min)/range*chartH);
            int color=b.c>=b.o?UP:DOWN;
            p.setColor(color);p.setStrokeWidth(Math.max(1.2f,step*.10f));p.setStyle(Paint.Style.STROKE);
            c.drawLine(x,yh,x,yl,p);
            p.setStyle(Paint.Style.FILL);
            float bh=Math.max(2f,Math.abs(yc-yo));
            c.drawRect(x-body/2,Math.min(yo,yc),x+body/2,Math.min(yo,yc)+bh,p);
        }
        p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(2.2f);p.setColor(BLUE);c.drawPath(e6,p);
        p.setStrokeWidth(2.2f);p.setColor(GOLD);c.drawPath(e15,p);
        Bar last=bars.get(n-1);float ly=(float)(bottom-(last.c-min)/range*chartH);
        p.setStyle(Paint.Style.FILL);p.setColor(GOLD);c.drawCircle(w-3,ly,3.5f,p);
    }
    private void drawFallback(Canvas c,float w,float h) {
        if(fallback.size()<2)return;
        double min=Double.MAX_VALUE,max=-Double.MAX_VALUE;
        for(double v:fallback){min=Math.min(min,v);max=Math.max(max,v);}
        double range=Math.max(.01,max-min);Path path=new Path();
        for(int i=0;i<fallback.size();i++){
            float x=w*i/(fallback.size()-1f);
            float y=(float)(h-8-((fallback.get(i)-min)/range)*(h-16));
            if(i==0)path.moveTo(x,y);else path.lineTo(x,y);
        }
        p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(3);p.setColor(GOLD);p.setShadowLayer(8,0,0,0x88D7AD54);
        c.drawPath(path,p);p.clearShadowLayer();
    }
}
