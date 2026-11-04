package com.diomaster.goldai;
import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
public class MainActivity extends Activity {
 @Override public void onCreate(Bundle state) {
  super.onCreate(state);
  WebView web = new WebView(this);
  WebSettings s = web.getSettings();
  s.setJavaScriptEnabled(true);
  s.setDomStorageEnabled(true);
  web.setBackgroundColor(0xFF090A0D);
  setContentView(web);
  web.loadUrl("file:///android_asset/index.html");
 }
}
