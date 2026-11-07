"""Refresh explicitly translated Tk text while preserving widgets and user input."""

from types import SimpleNamespace
import weakref

from . import i18n


def render(value):
    return value.render() if isinstance(value, Text) else value


class Text(str):
    """A displayed string that retains its message and formatting arguments."""

    def __new__(cls, message=None, *values, parts=None):
        translated = ("".join(str(render(part)) for part in parts) if parts is not None
                      else i18n.tr(message, *(render(value) for value in values)))
        text = super().__new__(cls, translated)
        text.message, text.values, text.parts = message, values, parts
        return text

    def render(self):
        return str(self.current())

    def current(self):
        return Text(self.message, *self.values, parts=self.parts)

    def __add__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return Text(parts=(self, other))

    def __radd__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return Text(parts=(other, self))


class LiveTranslations:
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk

        self.widgets = weakref.WeakKeyDictionary()
        self.variables = weakref.WeakValueDictionary()
        self.custom = weakref.WeakSet()
        self.tk = SimpleNamespace(**vars(tk))
        self.ttk = SimpleNamespace(**vars(ttk))
        bindings = self

        class TranslatedWidget:
            def __init__(self, *args, **kwargs):
                self._messages = {}
                options = self._translated_options(kwargs)
                super().__init__(*args, **options)
                bindings.widgets[self] = self._messages

            def _translated_options(self, options):
                options = dict(options)
                for name in ("text", "values"):
                    if name not in options:
                        continue
                    value = options[name]
                    if name == "values":
                        if isinstance(value, (tuple, list)) and any(isinstance(item, Text) for item in value):
                            self._messages[name] = value
                            options[name] = tuple(render(item) for item in value)
                        else:
                            self._messages.pop(name, None)
                    elif isinstance(value, Text):
                        self._messages[name] = value
                        options[name] = render(value)
                    else:
                        self._messages.pop(name, None)
                return options

            def configure(self, cnf=None, **kwargs):
                if cnf is None or isinstance(cnf, dict):
                    options = dict(cnf or {})
                    options.update(kwargs)
                    return super().configure(**self._translated_options(options))
                return super().configure(cnf, **kwargs)

            config = configure

        class StringVar(tk.StringVar):
            def __init__(self, master=None, value=None, name=None):
                self._message = value if isinstance(value, Text) else None
                self._setting = False
                super().__init__(master, value, name)
                bindings.variables[id(self)] = self
                reference = weakref.ref(self)
                def edited(*_):
                    # A combobox can write Tcl directly. Keep this callback weak
                    # so reopening settings does not retain its old variables.
                    variable = reference()
                    if variable is not None and not variable._setting:
                        variable._message = None
                self.trace_add("write", edited)

            def set(self, value):
                self._message = value if isinstance(value, Text) else None
                self._setting = True
                try:
                    super().set(render(value))
                finally:
                    self._setting = False

            initialize = set

        self.tk.StringVar = StringVar
        for module, names in ((self.tk, ("Label", "Button", "Checkbutton")),
                              (self.ttk, ("Label", "Button", "Checkbutton", "Combobox"))):
            for name in names:
                original = getattr(module, name)
                setattr(module, name, type(name, (TranslatedWidget, original), {}))

    text = staticmethod(Text)
    render = staticmethod(render)

    def set_language(self, code):
        i18n.set_language(code)
        for variable in tuple(self.variables.values()):
            if variable._message is not None:
                variable.set(variable._message)
        for widget, messages in tuple(self.widgets.items()):
            if widget.winfo_exists():
                widget.configure(**dict(messages))
        for widget in tuple(self.custom):
            if widget.winfo_exists():
                widget.refresh_language()
