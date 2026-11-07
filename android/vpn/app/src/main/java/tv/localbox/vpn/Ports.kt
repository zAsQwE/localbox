package tv.localbox.vpn

object Ports {
    // Browser port blocking includes IRC ports 6665–6669; 8080 is the default.
    private val blocked = setOf(1719, 1720, 1723, 2049, 3659, 4045, 5060, 5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6697, 10080)
    fun error(game: Int?, web: Int?): String? = when {
        game == null || web == null || game !in 1024..65535 || web !in 1024..65535 -> "Порты должны быть от 1024 до 65535"
        game == web -> "Для игры и сайта нужны разные порты"
        web in blocked -> "Браузеры блокируют порт $web. Используйте 8080 или 8081"
        else -> null
    }
}
