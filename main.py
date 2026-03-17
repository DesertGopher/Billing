import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
import os
import sys

import database as db

MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

_font_cache = {}


def get_font(size, weight="normal"):
    key = (size, weight)
    f = _font_cache.get(key)
    if f is None:
        f = ctk.CTkFont(size=size, weight=weight)
        _font_cache[key] = f
    return f


def _bundle_dir():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def load_pin():
    env_path = os.path.join(_bundle_dir(), ".env")
    if not os.path.isfile(env_path):
        return None
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("CODE="):
                return line.split("=", 1)[1].strip()
    return None


def month_add(month_str, delta):
    y, m = map(int, month_str.split("-"))
    m += delta
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}"


def format_month(month_str):
    y, m = map(int, month_str.split("-"))
    return f"{MONTHS_RU[m - 1]} {y}"


def format_amount(value):
    if value == int(value):
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ")


def sort_items(items, current_month):
    def sort_key(item):
        is_rec = 0 if item["is_recurring"] else 1
        raw_date = item.get("date")
        if raw_date:
            try:
                day = datetime.strptime(raw_date, "%Y-%m-%d").day
            except ValueError:
                day = 99
        else:
            day = 99
        return (is_rec, day, item["name"])
    return sorted(items, key=sort_key)


class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tw = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule_show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule_show(self, event=None):
        self._hide()
        self._after_id = self.widget.after(400, self._show)

    def _show(self, event=None):
        if not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tw = tw = ctk.CTkToplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        label = ctk.CTkLabel(tw, text=self.text, corner_radius=6,
                             fg_color="#333", text_color="#fff",
                             font=ctk.CTkFont(size=12))
        label.pack(padx=1, pady=1)

    def _hide(self, event=None):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self.tw:
            self.tw.destroy()
            self.tw = None


class AddItemDialog(ctk.CTkToplevel):
    def __init__(self, parent, current_month, on_save, preset_category="expense"):
        super().__init__(parent)
        self.title("Новая запись")
        self.resizable(False, False)
        self.grab_set()

        self.on_save = on_save
        self.current_month = current_month
        self.category = preset_category

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=16)

        ctk.CTkLabel(content, text="Название", font=ctk.CTkFont(size=13)).pack(anchor="w")
        self.name_entry = ctk.CTkEntry(content)
        self.name_entry.pack(fill="x", pady=(2, 10))

        ctk.CTkLabel(content, text="Сумма", font=ctk.CTkFont(size=13)).pack(anchor="w")
        self.amount_entry = ctk.CTkEntry(content)
        self.amount_entry.pack(fill="x", pady=(2, 10))

        ctk.CTkLabel(content, text="Дата", font=ctk.CTkFont(size=13)).pack(anchor="w")
        self.date_entry = ctk.CTkEntry(content, placeholder_text="ДД.ММ.ГГГГ")
        self.date_entry.pack(fill="x", pady=(2, 10))
        today = datetime.now().strftime("%d.%m.%Y")
        self.date_entry.insert(0, today)

        self.recurring_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(content, text="Ежемесячная", variable=self.recurring_var,
                        font=ctk.CTkFont(size=13)).pack(anchor="w", pady=(2, 10))

        ctk.CTkButton(content, text="Сохранить", height=36, command=self._save).pack(fill="x", pady=(6, 0))

        self.after(50, self._fit_window)

    def _fit_window(self):
        self.update_idletasks()
        w = 360
        h = self.winfo_reqheight() + 10
        self.geometry(f"{w}x{h}")

    def _save(self):
        name = self.name_entry.get().strip()
        raw = self.amount_entry.get().strip().replace(" ", "").replace(",", ".")
        if not name or not raw:
            return
        try:
            amount = float(raw)
        except ValueError:
            return
        if amount <= 0:
            return

        date = None
        date_raw = self.date_entry.get().strip()
        if date_raw:
            try:
                dt = datetime.strptime(date_raw, "%d.%m.%Y")
                date = dt.strftime("%Y-%m-%d")
            except ValueError:
                return

        is_recurring = self.recurring_var.get()
        db.add_item(
            name=name,
            amount=amount,
            category=self.category,
            is_recurring=is_recurring,
            start_month=self.current_month,
            date=date,
        )
        self.on_save()
        self.destroy()


class EditRecurringDialog(ctk.CTkToplevel):
    def __init__(self, parent, item, current_month, on_save):
        super().__init__(parent)
        self.title("Редактировать")
        self.resizable(False, False)
        self.grab_set()

        self.item = item
        self.current_month = current_month
        self.on_save = on_save

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=16)

        ctk.CTkLabel(content, text="Название", font=ctk.CTkFont(size=13)).pack(anchor="w")
        self.name_entry = ctk.CTkEntry(content)
        self.name_entry.pack(fill="x", pady=(2, 10))
        self.name_entry.insert(0, item['name'])

        ctk.CTkLabel(content, text="Сумма", font=ctk.CTkFont(size=13)).pack(anchor="w")
        self.amount_entry = ctk.CTkEntry(content)
        self.amount_entry.pack(fill="x", pady=(2, 10))

        current = item["effective_amount"]
        display = str(int(current)) if current == int(current) else str(current)
        self.amount_entry.insert(0, display)
        self.amount_entry.select_range(0, "end")

        ctk.CTkLabel(content, text="Дата", font=ctk.CTkFont(size=13)).pack(anchor="w")
        self.date_entry = ctk.CTkEntry(content, placeholder_text="ДД.ММ.ГГГГ")
        self.date_entry.pack(fill="x", pady=(2, 10))
        raw_date = item.get("date")
        if raw_date:
            try:
                dt = datetime.strptime(raw_date, "%Y-%m-%d")
                self.date_entry.insert(0, dt.strftime("%d.%m.%Y"))
            except ValueError:
                pass

        self.scope_var = ctk.StringVar(value="from_now")
        ctk.CTkRadioButton(content, text=f"С {format_month(current_month)} и далее",
                           variable=self.scope_var, value="from_now").pack(anchor="w")
        ctk.CTkRadioButton(content, text=f"Только {format_month(current_month)}",
                           variable=self.scope_var, value="only_this").pack(anchor="w", pady=(4, 10))

        ctk.CTkButton(content, text="Сохранить", height=36, command=self._save).pack(fill="x", pady=(4, 0))

        self.after(50, self._fit_window)

    def _fit_window(self):
        self.update_idletasks()
        w = 360
        h = self.winfo_reqheight() + 10
        self.geometry(f"{w}x{h}")

    def _save(self):
        raw = self.amount_entry.get().strip().replace(" ", "").replace(",", ".")
        if not raw:
            return
        try:
            amount = float(raw)
        except ValueError:
            return
        if amount <= 0:
            return

        new_name = self.name_entry.get().strip()
        if not new_name:
            return
        if new_name != self.item["name"]:
            db.update_item_name(self.item["id"], new_name)

        only_this = self.scope_var.get() == "only_this"
        db.update_recurring_amount(self.item["id"], amount, self.current_month, only_this_month=only_this)

        date_raw = self.date_entry.get().strip()
        if date_raw:
            try:
                dt = datetime.strptime(date_raw, "%d.%m.%Y")
                db.update_item_date(self.item["id"], dt.strftime("%Y-%m-%d"))
            except ValueError:
                pass

        self.on_save()
        self.destroy()


class PinDialog(ctk.CTkToplevel):
    def __init__(self, parent, expected_code, on_success):
        super().__init__(parent)
        self.expected_code = expected_code
        self.on_success = on_success
        self.parent_app = parent

        self.title("Billing")
        self.geometry("380x320")
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        card = ctk.CTkFrame(self, corner_radius=20, fg_color="#FFFFFF",
                            border_width=1, border_color="#E0E0E0")
        card.place(relx=0.5, rely=0.5, anchor="center")

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(padx=40, pady=(36, 32))

        ctk.CTkLabel(inner, text="\U0001F510", font=ctk.CTkFont(size=36)).pack(pady=(0, 8))

        ctk.CTkLabel(inner, text="Введите код доступа",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#333333").pack(pady=(0, 20))

        digits_frame = ctk.CTkFrame(inner, fg_color="transparent")
        digits_frame.pack()

        self.digit_entries = []
        for i in range(4):
            e = ctk.CTkEntry(
                digits_frame, width=56, height=56,
                font=ctk.CTkFont(size=24, weight="bold"),
                justify="center",
                corner_radius=12,
                border_width=2,
                border_color="#D0D5DD",
                fg_color="#F9FAFB",
                text_color="#1A1A2E",
            )
            e.pack(side="left", padx=6)
            e.bind("<KeyRelease>", lambda ev, idx=i: self._on_key(ev, idx))
            e.bind("<BackSpace>", lambda ev, idx=i: self._on_backspace(ev, idx))
            self.digit_entries.append(e)

        self.error_label = ctk.CTkLabel(inner, text="", text_color="#E53935",
                                        font=ctk.CTkFont(size=13))
        self.error_label.pack(pady=(16, 0))

        self.after(200, lambda: self.digit_entries[0].focus_set())

    def _on_key(self, event, idx):
        entry = self.digit_entries[idx]
        text = entry.get()

        if len(text) > 1:
            entry.delete(0, "end")
            entry.insert(0, text[-1])

        if text and idx < 3:
            self.digit_entries[idx + 1].focus_set()

        code = "".join(e.get() for e in self.digit_entries)
        if len(code) == 4:
            self.after(100, self._check)

    def _on_backspace(self, event, idx):
        entry = self.digit_entries[idx]
        if not entry.get() and idx > 0:
            self.digit_entries[idx - 1].focus_set()
            self.digit_entries[idx - 1].delete(0, "end")

    def _check(self):
        code = "".join(e.get() for e in self.digit_entries)
        if code == self.expected_code:
            self.grab_release()
            self.destroy()
            self.on_success()
        else:
            self.error_label.configure(text="Неверный код")
            for e in self.digit_entries:
                e.delete(0, "end")
                e.configure(border_color="#E53935")
            self.digit_entries[0].focus_set()
            self.after(800, self._reset_borders)

    def _reset_borders(self):
        for e in self.digit_entries:
            e.configure(border_color="#D0D5DD")

    def _on_close(self):
        self.parent_app.destroy()


class ItemRow(ctk.CTkFrame):
    _NORMAL = ("#FFFFFF", "#2B2B2B")
    _HOVER = ("#F0F4FF", "#363645")

    def __init__(self, parent, item, current_month, on_change, app):
        super().__init__(parent, fg_color=self._NORMAL, height=24, corner_radius=0)
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.item = item
        self.on_change = on_change
        self.current_month = current_month
        self.app = app

        self.grid_columnconfigure(3, weight=1)

        self.check_var = ctk.BooleanVar(value=bool(item.get("is_checked", 0)))
        cb = ctk.CTkCheckBox(self, text="", variable=self.check_var,
                             width=20, height=20, checkbox_width=16, checkbox_height=16,
                             corner_radius=4, border_width=2,
                             command=self._toggle_checked,
                             fg_color="#4CAF50" if item["category"] == "income" else "#EF5350")
        cb.grid(row=0, column=0, padx=(6, 0), sticky="w")

        icon = "🔁" if item["is_recurring"] else "·"
        ctk.CTkLabel(self, text=icon, width=20, anchor="center",
                     font=get_font(10), text_color="#999"
                     ).grid(row=0, column=1, padx=(2, 0), sticky="w")

        raw_date = item.get("date")
        if raw_date:
            try:
                day = datetime.strptime(raw_date, "%Y-%m-%d").day
                if item["is_recurring"]:
                    _, m = map(int, current_month.split("-"))
                    date_text = f"{day:02d}.{m:02d}"
                else:
                    dt = datetime.strptime(raw_date, "%Y-%m-%d")
                    date_text = dt.strftime("%d.%m")
            except ValueError:
                date_text = "—"
        else:
            date_text = "—"
        ctk.CTkLabel(self, text=date_text, width=40, anchor="w",
                     font=get_font(11), text_color="gray"
                     ).grid(row=0, column=2, padx=(2, 4), sticky="w")

        ctk.CTkLabel(self, text=item["name"], anchor="w",
                     font=get_font(12)
                     ).grid(row=0, column=3, sticky="w")

        display_amount = item["effective_amount"]
        amount_text = f"{format_amount(display_amount)} ₽"
        color = ("#2E7D32", "#66BB6A") if item["category"] == "income" else ("#C62828", "#EF5350")
        ctk.CTkLabel(self, text=amount_text, text_color=color, anchor="e",
                     width=110, font=get_font(12)
                     ).grid(row=0, column=4, padx=(4, 10), sticky="e")

        self._bind_events(self)

    def _bind_events(self, widget):
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<Button-3>", self._show_menu, add="+")
        for child in widget.winfo_children():
            self._bind_events(child)

    def _on_enter(self, event=None):
        self.configure(fg_color=self._HOVER)

    def _on_leave(self, event=None):
        self.configure(fg_color=self._NORMAL)

    def _show_menu(self, event):
        menu = tk.Menu(self, tearoff=0)
        if self.item["is_recurring"]:
            if self.item["is_active"]:
                menu.add_command(label="✎  Редактировать", command=self._edit_recurring)
                menu.add_separator()
                menu.add_command(label="✕  Отключить", command=self._deactivate)
            else:
                menu.add_command(label="↩  Включить обратно", command=self._activate)
        else:
            menu.add_command(label="✕  Удалить", command=self._delete)
        menu.tk_popup(event.x_root, event.y_root)

    def _deactivate(self):
        if messagebox.askyesno("\u041e\u0442\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435", f"\u041e\u0442\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u00ab{self.item['name']}\u00bb?"):
            db.deactivate_item(self.item["id"], self.current_month)
            self.on_change()

    def _activate(self):
        db.activate_item(self.item["id"])
        self.on_change()

    def _delete(self):
        if messagebox.askyesno("\u0423\u0434\u0430\u043b\u0435\u043d\u0438\u0435", f"\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u00ab{self.item['name']}\u00bb?"):
            db.delete_item(self.item["id"])
            self.on_change()

    def _toggle_checked(self):
        checked = self.check_var.get()
        db.set_checked(self.item["id"], self.current_month, checked)
        self.item["is_checked"] = int(checked)
        self.app._update_totals()

    def _edit_recurring(self):
        EditRecurringDialog(self.app, self.item, self.current_month, on_save=self.on_change)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        saved_theme = db.get_setting("theme", "light")
        ctk.set_appearance_mode(saved_theme)
        ctk.set_default_color_theme("blue")

        self.title("Billing — Учёт финансов")
        self.geometry("540x800")
        self.resizable(False, False)

        now = datetime.now()
        self.current_month = f"{now.year:04d}-{now.month:02d}"

        pin = load_pin()
        if pin:
            self.withdraw()
            self.after(100, lambda: PinDialog(self, pin, self._on_pin_success))
        else:
            self._build_ui()
            self.refresh()

    def _on_pin_success(self):
        self.deiconify()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=20, pady=(12, 6))

        ctk.CTkButton(nav, text="◀", width=36, height=30, command=self._prev_month).pack(side="left")
        self.month_label = ctk.CTkLabel(nav, text="", font=get_font(18, "bold"))
        self.month_label.pack(side="left", expand=True)
        ctk.CTkButton(nav, text="▶", width=36, height=30, command=self._next_month).pack(side="right")
        self.theme_btn = ctk.CTkButton(nav, text="☀" if ctk.get_appearance_mode() == "Dark" else "🌙",
                       width=36, height=30,
                       fg_color="transparent", hover_color=("#E0E0E0", "#444"),
                       text_color=("#333", "#DDD"),
                       command=self._toggle_theme)
        self.theme_btn.pack(side="right", padx=(0, 4))

        inc_header = ctk.CTkFrame(self, height=30, fg_color=("#E8EDF5", "#2D3748"), corner_radius=0)
        inc_header.pack(fill="x", padx=20, pady=(8, 0))
        inc_header.pack_propagate(False)
        self.inc_header_label = ctk.CTkLabel(inc_header, text="  Доходы",
                     font=get_font(12, "bold"),
                     text_color=("#333", "#DDD"))
        self.inc_header_label.pack(side="left")
        btn_add_inc = ctk.CTkButton(inc_header, text="+", width=24, height=24,
                                    font=get_font(14, "bold"),
                                    fg_color="#7986CB", hover_color="#5C6BC0",
                                    corner_radius=6, command=self._add_income)
        btn_add_inc.pack(side="right", padx=6)
        Tooltip(btn_add_inc, "Добавить доход")

        self.income_frame = ctk.CTkScrollableFrame(self, height=275, fg_color=("#FFFFFF", "#2B2B2B"),
                                                    corner_radius=0, border_width=1,
                                                    border_color=("#D0D0D0", "#444"))
        self.income_frame.pack(fill="x", padx=20)

        exp_header = ctk.CTkFrame(self, height=30, fg_color=("#FDECEA", "#3D2B2B"), corner_radius=0)
        exp_header.pack(fill="x", padx=20, pady=(8, 0))
        exp_header.pack_propagate(False)
        self.exp_header_label = ctk.CTkLabel(exp_header, text="  Расходы",
                     font=get_font(12, "bold"),
                     text_color=("#333", "#DDD"))
        self.exp_header_label.pack(side="left")
        btn_add_exp = ctk.CTkButton(exp_header, text="+", width=24, height=24,
                                    font=get_font(14, "bold"),
                                    fg_color="#EF9A9A", hover_color="#EF5350",
                                    corner_radius=6, command=self._add_expense)
        btn_add_exp.pack(side="right", padx=6)
        Tooltip(btn_add_exp, "Добавить расход")

        self.expense_frame = ctk.CTkScrollableFrame(self, height=275, fg_color=("#FFFFFF", "#2B2B2B"),
                                                     corner_radius=0, border_width=1,
                                                     border_color=("#D0D0D0", "#444"))
        self.expense_frame.pack(fill="x", padx=20)

        totals = ctk.CTkFrame(self, corner_radius=12)
        totals.pack(fill="x", padx=20, pady=(8, 10))

        self.income_total_label = ctk.CTkLabel(totals, text="", font=get_font(12))
        self.income_total_label.pack(anchor="w", padx=16, pady=(8, 0))

        self.expense_total_label = ctk.CTkLabel(totals, text="", font=get_font(12))
        self.expense_total_label.pack(anchor="w", padx=16)

        self.balance_label = ctk.CTkLabel(totals, text="", font=get_font(14, "bold"))
        self.balance_label.pack(anchor="w", padx=16, pady=(2, 8))

    def _prev_month(self):
        self.current_month = month_add(self.current_month, -1)
        self.refresh()

    def _next_month(self):
        self.current_month = month_add(self.current_month, 1)
        self.refresh()

    def _add_income(self):
        AddItemDialog(self, self.current_month, on_save=self.refresh, preset_category="income")

    def _add_expense(self):
        AddItemDialog(self, self.current_month, on_save=self.refresh, preset_category="expense")

    def _clear_frame(self, frame):
        for widget in frame.winfo_children():
            widget.destroy()

    def refresh(self):
        self.month_label.configure(text=format_month(self.current_month))

        items = db.get_items_for_month(self.current_month)

        incomes = sort_items([dict(r) for r in items if r["category"] == "income"], self.current_month)
        expenses = sort_items([dict(r) for r in items if r["category"] == "expense"], self.current_month)

        self._clear_frame(self.income_frame)
        is_dark = ctk.get_appearance_mode() == "Dark"
        sep_bg = "#444" if is_dark else "#E0E0E0"
        for i, item in enumerate(incomes):
            if i > 0:
                tk.Frame(self.income_frame, height=1, bg=sep_bg).pack(fill="x")
            row = ItemRow(self.income_frame, item, self.current_month, self.refresh, self)
            row.pack(fill="x")

        if not incomes:
            ctk.CTkLabel(self.income_frame, text="Нет записей", text_color="gray").pack(pady=8)

        self._clear_frame(self.expense_frame)
        for i, item in enumerate(expenses):
            if i > 0:
                tk.Frame(self.expense_frame, height=1, bg=sep_bg).pack(fill="x")
            row = ItemRow(self.expense_frame, item, self.current_month, self.refresh, self)
            row.pack(fill="x")

        if not expenses:
            ctk.CTkLabel(self.expense_frame, text="Нет записей", text_color="gray").pack(pady=8)

        self._incomes = incomes
        self._expenses = expenses
        self._update_totals()

    def _update_totals(self):
        total_in = sum(r["effective_amount"] for r in self._incomes)
        total_out = sum(r["effective_amount"] for r in self._expenses)
        checked_in = sum(r["effective_amount"] for r in self._incomes if r.get("is_checked"))
        checked_out = sum(r["effective_amount"] for r in self._expenses if r.get("is_checked"))
        balance = total_in - total_out

        if checked_in > 0:
            self.inc_header_label.configure(text=f"  Доходы ({format_amount(checked_in)} ₽)")
        else:
            self.inc_header_label.configure(text="  Доходы")

        if checked_out > 0:
            self.exp_header_label.configure(text=f"  Расходы ({format_amount(checked_out)} ₽)")
        else:
            self.exp_header_label.configure(text="  Расходы")

        self.income_total_label.configure(text=f"Доходы:  {format_amount(total_in)} ₽")
        self.expense_total_label.configure(text=f"Расходы: {format_amount(total_out)} ₽")

        b_color = "#4CAF50" if balance >= 0 else "#EF5350"
        sign = "+" if balance > 0 else ""
        self.balance_label.configure(text=f"Баланс:  {sign}{format_amount(balance)} ₽", text_color=b_color)

    def _toggle_theme(self):
        new_mode = "dark" if ctk.get_appearance_mode() == "Light" else "light"
        ctk.set_appearance_mode(new_mode)
        db.set_setting("theme", new_mode)
        self.theme_btn.configure(text="☀" if new_mode == "dark" else "🌙")
        self.refresh()


if __name__ == "__main__":
    db.init_db()
    app = App()
    app.mainloop()
