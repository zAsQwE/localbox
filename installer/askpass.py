"""Password dialog fallback for sudo -A; stdout is consumed only by sudo."""

import sys


def main():
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        try:
            password = simpledialog.askstring('LocalBox',
                'Пароль администратора для установки системных пакетов:', show='*', parent=root)
        finally:
            root.destroy()
        if password is None:
            return 1
        sys.stdout.write(password + '\n')
        return 0
    except Exception:
        print('Не удалось открыть запрос пароля. Запустите setup из терминала.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
