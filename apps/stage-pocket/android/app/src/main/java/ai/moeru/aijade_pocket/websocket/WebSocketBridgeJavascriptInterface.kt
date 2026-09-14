package ai.moeru.aijade_pocket.websocket

import android.webkit.JavascriptInterface

class WebSocketBridgeJavascriptInterface(
    private val bridge: HostWebSocketBridge,
) {
    @JavascriptInterface
    fun postMessage(payload: String) {
        bridge.handleCommand(payload)
    }
}
