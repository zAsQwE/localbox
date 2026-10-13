"""Импорт музыки Додо Ре Ми из установленной игры без изменения исходных файлов."""

from pathlib import Path
import shutil


def songs_directory(game):
    game = Path(game).expanduser().resolve()
    candidates = (game / "games" / "NopusOpus" / "songs", game / "NopusOpus" / "songs",
                  game / "songs", game)
    for path in candidates:
        if path.is_dir() and any(path.glob("*/backing*.ogg")):
            return path
    raise ValueError("В выбранной папке не найдены games/NopusOpus/songs/<песня>/backing*.ogg. "
                     "Выберите папку Jackbox Party Pack 10 или непосредственно songs.")


def import_dodo(game, target, log=print):
    songs = songs_directory(game)
    output = Path(target) / "server" / "render" / "nopus-opus"
    count = 0
    for path in sorted(songs.glob("*/backing*.ogg")):
        if path.is_file() and not path.is_symlink():
            relative = path.relative_to(songs)
            destination = output / "songs" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if path.resolve() != destination.resolve():
                shutil.copy2(path, destination)
            count += 1
    instruments = songs.parent / "instruments"
    if instruments.is_dir():
        for path in sorted(instruments.glob("*/*.ogg")):
            if path.is_file() and not path.is_symlink():
                destination = output / "instruments" / path.relative_to(instruments)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.resolve() != path.resolve():
                    shutil.copy2(path, destination)
    log(f"Додо Ре Ми: скопировано файлов музыки — {count}. Файлы игры сохранены.")
    return count


