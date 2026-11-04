package com.diomaster.goldai;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.view.View;
import java.util.ArrayList;
import java.util.List;

public final class GoldChartView extends View {
    private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint grid = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final List<Double> values = new ArrayList<>();

    public GoldChartView(Context context) {
        super(context);
        line.setColor(0xFFD7AD54);
        line.setStrokeWidth(4f);
        line.setStyle(Paint.Style.STROKE);
        line.setStrokeJoin(Paint.Join.ROUND);
        line.setStrokeCap(Paint.Cap.ROUND);
        grid.setColor(0xFF292C34);
        grid.setStrokeWidth(1f);
    }

    public void addPrice(double value) {
        values.add(value);
        while (values.size() > 90) values.remove(0);
        invalidate();
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float w = getWidth(), h = getHeight();
        for (int i = 1; i <= 3; i++) canvas.drawLine(0, h * i / 4f, w, h * i / 4f, grid);
        if (values.size() < 2) return;
        double min = Double.MAX_VALUE, max = -Double.MAX_VALUE;
        for (double v : values) { min = Math.min(min, v); max = Math.max(max, v); }
        double range = Math.max(0.01, max - min);
        Path path = new Path();
        for (int i = 0; i < values.size(); i++) {
            float x = w * i / (values.size() - 1f);
            float y = (float) (h - 8f - ((values.get(i) - min) / range) * (h - 16f));
            if (i == 0) path.moveTo(x, y); else path.lineTo(x, y);
        }
        canvas.drawPath(path, line);
    }
}
