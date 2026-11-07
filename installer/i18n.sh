# Messages needed before Python is available. Arguments are fixed message formats.
if [ "${LOCALBOX_LANGUAGE:-}" != ru ] && [ "${LOCALBOX_LANGUAGE:-}" != en ]; then
    case "${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}" in
        ru*|RU*) LOCALBOX_LANGUAGE=ru ;;
        *) LOCALBOX_LANGUAGE=en ;;
    esac
fi
export LOCALBOX_LANGUAGE
localbox_text() {
    local message="$1"
    if [ "$LOCALBOX_LANGUAGE" = en ]; then message="$2"; fi
    shift 2
    printf "$message" "$@"
}
