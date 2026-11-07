package tv.localbox.vpn

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import org.json.JSONObject

object RoomQr {
    fun room(): JSONObject? = if(ServerService.running) try { JSONObject(NativeServer.status()).optJSONObject("room") } catch(_: Exception) { null } else null
    fun visible(context: Context,room: JSONObject?): Boolean {
        if(room==null || !room.optBoolean("qrVisible") || !ClientCatalog.ready(context)) return false
        val prefs=context.getSharedPreferences("localbox",0)
        return prefs.getBoolean("showQr",true) && prefs.getString("dismissedQr","")!=room.optString("id",room.optString("code"))
    }
    fun dismiss(context: Context,room: JSONObject) { context.getSharedPreferences("localbox",0).edit().putString("dismissedQr",room.optString("id",room.optString("code"))).apply() }
    fun bitmap(url: String): Bitmap {
        val matrix=QRCodeWriter().encode(url,BarcodeFormat.QR_CODE,480,480)
        val pixels=IntArray(480*480) { index -> if(matrix[index%480,index/480]) Color.BLACK else Color.WHITE }
        return Bitmap.createBitmap(pixels,480,480,Bitmap.Config.ARGB_8888)
    }
}
