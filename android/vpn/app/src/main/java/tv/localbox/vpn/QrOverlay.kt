package tv.localbox.vpn

import android.content.Context
import android.graphics.Color
import android.graphics.Point
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.*
import android.widget.*
import androidx.appcompat.widget.AppCompatButton as Button
import kotlin.math.abs
import kotlin.math.roundToInt

/** Optional small overlay, maintained by the running server foreground service. */
class QrOverlay(private val context: Context) {
    private val handler=Handler(Looper.getMainLooper())
    private val manager=context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var view: View?=null
    private var identity=""
    private val prefs=context.getSharedPreferences("localbox",0)
    private var layout: WindowManager.LayoutParams?=null
    private var qr: ImageView?=null
    private var frame=Point()
    private var dragging=false

    /** Coordinates are relative to the usable window area, outside system bars. */
    @Suppress("DEPRECATION")
    private fun available(): Point {
        if(Build.VERSION.SDK_INT>=30) {
            val metrics=manager.currentWindowMetrics
            val insets=metrics.windowInsets.getInsetsIgnoringVisibility(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            return Point((metrics.bounds.width()-insets.left-insets.right).coerceAtLeast(1),(metrics.bounds.height()-insets.top-insets.bottom).coerceAtLeast(1))
        }
        view?.let { card ->
            val visible=Rect();card.getWindowVisibleDisplayFrame(visible)
            if(visible.width()>0 && visible.height()>0) return Point(visible.width(),visible.height())
        }
        return Point().also { manager.defaultDisplay.getSize(it) }
    }
    private fun position(restore: Boolean=false) {
        val card=view ?: return
        val params=layout ?: return
        val size=available()
        val changed=size!=frame
        frame=size
        val width=minOf(dp(204),(size.x-dp(16)).coerceAtLeast(dp(64)))
        val edge=minOf(dp(180),(width-dp(24)).coerceAtLeast(1),(size.y-dp(152)).coerceAtLeast(dp(64)))
        if(params.width!=width || qr?.layoutParams?.height!=edge) {
            params.width=width
            qr?.layoutParams=LinearLayout.LayoutParams(edge,edge).apply { gravity=Gravity.CENTER_HORIZONTAL }
            card.post { position(restore=true) }
        }
        val maxX=(size.x-params.width).coerceAtLeast(0)
        val maxY=(size.y-card.height).coerceAtLeast(0)
        if(restore || changed) {
            params.x=(prefs.getFloat("qrPositionX",1f)*maxX).roundToInt()
            params.y=(prefs.getFloat("qrPositionY",0.03f)*maxY).roundToInt()
        }
        params.x=params.x.coerceIn(0,maxX);params.y=params.y.coerceIn(0,maxY)
        try { manager.updateViewLayout(card,params) } catch(_: Exception) { hide() }
    }
    private fun savePosition() {
        val card=view ?: return
        val params=layout ?: return
        val maxX=(frame.x-params.width).coerceAtLeast(0)
        val maxY=(frame.y-card.height).coerceAtLeast(0)
        prefs.edit().putFloat("qrPositionX",if(maxX>0) params.x.toFloat()/maxX else 0f)
            .putFloat("qrPositionY",if(maxY>0) params.y.toFloat()/maxY else 0f).apply()
    }
    private fun dragHandle(target: View) {
        val slop=ViewConfiguration.get(context).scaledTouchSlop
        var downX=0f;var downY=0f;var startX=0;var startY=0
        target.setOnTouchListener { touched,event ->
            val params=layout
            if(params==null) false else {
                when(event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        downX=event.rawX;downY=event.rawY;startX=params.x;startY=params.y;dragging=false
                    }
                    MotionEvent.ACTION_MOVE -> {
                        val dx=event.rawX-downX;val dy=event.rawY-downY
                        if(abs(dx)>slop || abs(dy)>slop) dragging=true
                        if(dragging) { params.x=startX+dx.roundToInt();params.y=startY+dy.roundToInt();position() }
                    }
                    MotionEvent.ACTION_UP,MotionEvent.ACTION_CANCEL -> {
                        if(dragging) savePosition() else if(event.actionMasked==MotionEvent.ACTION_UP) touched.performClick()
                        dragging=false
                    }
                }
                true
            }
        }
    }
    private val poll=object : Runnable {
        override fun run() {
            val room=RoomQr.room()
            val enabled=!MainActivity.inForeground && context.getSharedPreferences("localbox",0).getBoolean("overlayQr",false) && Settings.canDrawOverlays(context)
            if(!enabled || !RoomQr.visible(context,room)) hide()
            else {
                val id=room!!.optString("id")+room.optString("joinUrl")
                if(view==null || identity!=id) {
                    hide();identity=id
                    val themed=ContextThemeWrapper(context,R.style.Theme_LocalBox)
                    val card=LinearLayout(themed).apply {
                        orientation=LinearLayout.VERTICAL;setPadding(dp(12),dp(8),dp(12),dp(12))
                        background=GradientDrawable().apply { setColor(Color.rgb(16,20,27));cornerRadius=dp(16).toFloat() }
                    }
                    val header=LinearLayout(themed)
                    header.addView(TextView(themed).apply { text=room.optString("code");textSize=22f;setTextColor(Color.rgb(222,180,92));dragHandle(this) },LinearLayout.LayoutParams(0,-2,1f))
                    header.addView(Button(themed).apply { text="×";contentDescription="Закрыть QR-код";textSize=22f;setOnClickListener { RoomQr.dismiss(context,room);hide() } },LinearLayout.LayoutParams(dp(48),dp(48)))
                    card.addView(header)
                    qr=ImageView(themed).apply { contentDescription="QR-код входа";setImageBitmap(RoomQr.bitmap(room.optString("joinUrl")));dragHandle(this) }
                    card.addView(qr,LinearLayout.LayoutParams(dp(180),dp(180)).apply { gravity=Gravity.CENTER_HORIZONTAL })
                    card.addView(TextView(themed).apply {
                        text=room.optString("joinUrl");textSize=14f;setTextColor(Color.rgb(240,242,246))
                        gravity=Gravity.CENTER;textDirection=View.TEXT_DIRECTION_LTR;setPadding(0,dp(8),0,0)
                        contentDescription="Адрес сайта: $text";dragHandle(this)
                    },LinearLayout.LayoutParams(-1,-2))
                    dragHandle(card);dragHandle(header)
                    val params=WindowManager.LayoutParams(dp(204),-2,
                        if(Build.VERSION.SDK_INT>=26) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY else @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE,
                        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,android.graphics.PixelFormat.TRANSLUCENT)
                    params.gravity=Gravity.TOP or Gravity.LEFT
                    layout=params;frame=Point()
                    try { manager.addView(card,params);view=card;card.post { position(restore=true) } } catch(_: Exception) { hide() }
                }
                else if(!dragging && available()!=frame) position(restore=true)
            }
            handler.postDelayed(this,1000)
        }
    }
    fun start() { handler.removeCallbacks(poll);handler.post(poll) }
    fun stop() { handler.removeCallbacks(poll);hide() }
    private fun hide() { view?.let { try { manager.removeView(it) } catch(_: Exception) { } };view=null;layout=null;qr=null;dragging=false }
    private fun dp(value: Int)=(context.resources.displayMetrics.density*value).toInt()
}
