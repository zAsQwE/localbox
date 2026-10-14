"""Initial Tk setup size bounded by the screen and the window manager's work area."""


def fit_window(root):
    width, height = root.winfo_screenwidth(), root.winfo_screenheight()
    max_width, max_height = root.maxsize()
    available_width = max(200, min(width - 24, max_width))
    available_height = max(200, min(height - 64, max_height))
    initial_width, initial_height = min(680, available_width), min(720, available_height)
    root.minsize(min(420, available_width), min(340, available_height))
    root.maxsize(available_width, available_height)
    root.geometry(f"{initial_width}x{initial_height}+{max(0, (width-initial_width)//2)}+{max(0, (height-initial_height-40)//2)}")
