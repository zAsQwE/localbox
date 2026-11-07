package tv.localbox.vpn

object NativeServer {
    private var loaded = false
    @Synchronized fun load() {
        if (!loaded) {
            System.loadLibrary("localbox_server")
            loaded = true
        }
    }
    external fun start(directory: String, host: String, gamePort: Int, webPort: Int): String?
    external fun stop()
    external fun status(): String
    external fun speechState(ready: Boolean,message: String)
    external fun speechNext(): String
    external fun speechDone(id: String,error: String)
}
