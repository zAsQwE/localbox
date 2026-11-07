package tv.localbox.vpn

import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.webkit.*
import android.widget.*
import androidx.appcompat.widget.AppCompatButton as Button
import androidx.appcompat.app.AppCompatActivity

/** Local HTTP controller. WebView doesn't apply an external browser's HTTPS-only mode. */
class PlayerActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private var playerUrl=""
    private var loadError=false
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if(!ServerService.running) { finish();return }
        val port=getSharedPreferences("localbox",0).getInt("webPort",8080)
        val code=intent.getStringExtra("code").orEmpty().takeIf { it.matches(Regex("[A-Z]{4}")) }.orEmpty()
        playerUrl="http://127.0.0.1:$port/"+(if(code.isNotEmpty()) "?code=$code" else "")
        val layout=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setBackgroundColor(Color.rgb(9,11,15)) }
        val toolbar=LinearLayout(this)
        toolbar.addView(Button(this).apply { text="Закрыть";setOnClickListener { finish() } })
        toolbar.addView(Button(this).apply { text="Обновить";setOnClickListener { web.reload() } })
        toolbar.addView(Button(this).apply { text="В браузере";setOnClickListener {
            try { startActivity(Intent(Intent.ACTION_VIEW,Uri.parse(playerUrl))) } catch(_: Exception) { Toast.makeText(this@PlayerActivity,"Браузер не найден",Toast.LENGTH_LONG).show() }
        } })
        layout.addView(toolbar)
        val status=TextView(this).apply { setTextColor(Color.WHITE);text="Открываю локальный сайт…";setPadding(16,8,16,8) };layout.addView(status)
        web=WebView(this).apply { id=R.id.playerWeb }
        web.settings.apply {
            javaScriptEnabled=true;domStorageEnabled=true
            allowFileAccess=false;allowContentAccess=false
            mixedContentMode=WebSettings.MIXED_CONTENT_NEVER_ALLOW
        }
        web.webChromeClient=WebChromeClient()
        web.webViewClient=object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView,request: WebResourceRequest): Boolean {
                val uri=request.url
                if(uri.host=="127.0.0.1" && uri.port==port && uri.scheme=="https") { view.loadUrl(uri.buildUpon().scheme("http").build().toString());return true }
                // No file/content/intent URLs from downloaded client assets.
                return uri.scheme !in setOf("http","https")
            }
            override fun onPageStarted(view: WebView,url: String,favicon: android.graphics.Bitmap?) { loadError=false }
            override fun onPageFinished(view: WebView,url: String) { if(!loadError) status.visibility=View.GONE }
            override fun onReceivedError(view: WebView,request: WebResourceRequest,error: WebResourceError) {
                if(request.isForMainFrame) { loadError=true;status.visibility=View.VISIBLE;status.text="Не удалось открыть сайт: ${error.description}. Проверьте сервер и скачанный клиент" }
            }
            override fun onReceivedHttpError(view: WebView,request: WebResourceRequest,errorResponse: WebResourceResponse) {
                if(request.isForMainFrame) { loadError=true;status.visibility=View.VISIBLE;status.text="Сайт вернул HTTP ${errorResponse.statusCode}. Проверьте выбранный клиент" }
            }
        }
        layout.addView(web,LinearLayout.LayoutParams(-1,0,1f));setContentView(layout)
        if(savedInstanceState==null || web.restoreState(savedInstanceState)==null) web.loadUrl(playerUrl)
    }
    override fun onSaveInstanceState(outState: Bundle) { web.saveState(outState);super.onSaveInstanceState(outState) }
    @Deprecated("Back navigation") override fun onBackPressed() { if(web.canGoBack()) web.goBack() else super.onBackPressed() }
    override fun onDestroy() { if(::web.isInitialized) { web.stopLoading();web.destroy() };super.onDestroy() }
}
