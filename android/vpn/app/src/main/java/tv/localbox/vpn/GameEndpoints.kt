package tv.localbox.vpn

/** Only known Jackbox game services, never arbitrary download/store hosts. */
object GameEndpoints {
    private val hosts = listOf(
        "ecast.jackboxgames.com", "ecast-prod-use2.jackboxgames.com", "ecast.jackbox.tv",
        "blobcast.jackboxgames.com", "blobcast.jackbox.tv", "api.jackbox.tv", "bc.jackbox.tv",
        "jb-ecast.klucva.ru", "server.rujackbox.loamfy.com", "jack.nevpn2.fenst4r.live", "jack.fenst4r.live"
    )
    val authorityPattern = "(?:" + (hosts + listOf("127.0.0.1", "localhost")).joinToString("|") { Regex.escape(it) } +
        "|(?:[a-z0-9-]+\\.)+(?:ecast|blobcast)\\.jackboxgames\\.com)(?::[0-9]{1,5})?"
    private val authority = Regex("^$authorityPattern$", RegexOption.IGNORE_CASE)
    fun isAuthority(value: String) = authority.matches(value)
    // Preserve encoded path/query exactly. An authority-only string is also a valid API base.
    val literal = Regex("^(https?|wss?)://($authorityPattern)(/[^\\s]*)?$", RegexOption.IGNORE_CASE)
    fun rewriteLiteral(value: String, port: Int): String? {
        val match = literal.matchEntire(value) ?: return null
        val tail = match.groups[3]?.value.orEmpty()
        if (tail.isNotEmpty() && tail!="/" && !Regex("^/(?:api/v2(?:/|[?#]|$)|room(?:/|[?#]|$)|socket\\.io(?:/|[?#]|$)|tts/generate(?:[?#]|$))").containsMatchIn(tail)) return null
        val scheme = if (match.groupValues[1].lowercase().startsWith("ws")) "ws" else "http"
        return "$scheme://127.0.0.1:$port$tail"
    }
}
