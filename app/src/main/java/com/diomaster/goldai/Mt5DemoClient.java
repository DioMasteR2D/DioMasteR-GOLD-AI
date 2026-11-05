package com.diomaster.goldai;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.UUID;

public final class Mt5DemoClient {
    private final String base;
    private final String token;
    public Mt5DemoClient(String base, String token) {
        this.base=base.replaceAll("/+$","");
        this.token=token==null?"":token.replaceAll("\\\\s+","");\n        if(this.token.indexOf("\\r")>=0 || this.token.indexOf("\\n")>=0) throw new IllegalArgumentException("Το bridge token περιέχει μη έγκυρους χαρακτήρες.");
    }
    private JSONObject request(String method,String path,JSONObject payload) throws Exception {
        HttpURLConnection c=(HttpURLConnection)new URL(base+path).openConnection();
        try {
            c.setRequestMethod(method); c.setConnectTimeout(8000); c.setReadTimeout(12000);
            c.setRequestProperty("Authorization","Bearer "+token);
            c.setRequestProperty("Accept","application/json");
            if(payload!=null) {
                c.setDoOutput(true); c.setRequestProperty("Content-Type","application/json");
                OutputStream out=c.getOutputStream(); out.write(payload.toString().getBytes("UTF-8")); out.close();
            }
            int code=c.getResponseCode();
            InputStream in=code>=200&&code<300?c.getInputStream():c.getErrorStream();
            BufferedReader reader=new BufferedReader(new InputStreamReader(in,"UTF-8"));
            StringBuilder body=new StringBuilder(); String line;
            while((line=reader.readLine())!=null) body.append(line);
            reader.close();
            JSONObject json=new JSONObject(body.toString());
            if(code<200||code>=300) throw new IllegalStateException(json.optString("detail","MT5 bridge HTTP "+code));
            return json;
        } finally { c.disconnect(); }
    }
    public JSONObject status() throws Exception { return request("GET","/v1/status",null); }
    public JSONObject quote(String symbol) throws Exception { return request("GET","/v1/quote/"+symbol,null); }
    public JSONObject positions() throws Exception { return request("GET","/v1/positions",null); }
    public JSONObject candles(String symbol,String timeframe,int hours) throws Exception {
        return request("GET","/v1/candles/"+symbol+"?timeframe="+timeframe+"&hours="+hours,null);
    }
    public JSONObject history(String symbol,int limit) throws Exception {
        return request("GET","/v1/history?symbol="+symbol+"&limit="+limit,null);
    }
    public JSONObject autoStart() throws Exception { return request("POST","/v1/auto/start",new JSONObject()); }
    public JSONObject autoStop() throws Exception { return request("POST","/v1/auto/stop",new JSONObject()); }
    public JSONObject autoStatus() throws Exception { return request("GET","/v1/auto/status",null); }
    public JSONObject order(String symbol,String side,double volume,double sl,double tp) throws Exception {
        JSONObject p=new JSONObject();
        p.put("symbol",symbol); p.put("side",side); p.put("volume",volume);
        p.put("stop_loss",sl); p.put("take_profit",tp);
        p.put("client_order_id","android-"+UUID.randomUUID().toString());
        return request("POST","/v1/order",p);
    }
    public JSONObject close(long ticket) throws Exception { return request("POST","/v1/positions/"+ticket+"/close",new JSONObject()); }
}
