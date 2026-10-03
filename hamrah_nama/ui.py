from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from .core import BinaryManager, Device, MirrorOptions, ScrcpyService
from .guides import GUIDES, guide_for, normalize_brand


BG = "#0f172a"
PANEL = "#172033"
CARD = "#1e293b"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
ACCENT = "#22c55e"
BLUE = "#38bdf8"
DANGER = "#fb7185"
PAIR_BUTTON_TEXT = "جفت‌سازی اختیاری (اندروید ۱۱ به بالا)"
PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def rtl_count(value: int, text: str) -> str:
    number = str(value).translate(PERSIAN_DIGITS)
    return f"\u202B{number} {text}\u202C"


class HamrahNamaApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("همراه‌نما | اتصال ساده به گوشی")
        self.geometry("1000x720")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.option_add("*Font", ("Segoe UI", 10))
        self.binaries = BinaryManager()
        self.service = ScrcpyService(self.binaries)
        self.devices: dict[str, Device] = {}
        self.recording_active = False
        self.current_record_path: Path | None = None
        self.events: queue.Queue[tuple[Callable, tuple]] = queue.Queue()
        self._configure_style()
        self._build_ui()
        self.bind_all("<F8>", lambda _event: self.take_screenshot())
        self.bind_all("<F9>", lambda _event: self.toggle_recording())
        self.after(100, self._drain_events)
        self.after(350, self.refresh_devices)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground=TEXT)
        style.configure("Heading.TLabel", font=("Segoe UI", 12, "bold"), background=CARD, foreground=TEXT)
        style.configure("Accent.TButton", background=ACCENT, foreground="#052e16", font=("Segoe UI", 10, "bold"), padding=(16, 9))
        style.map("Accent.TButton", background=[("active", "#4ade80")])
        style.configure("Secondary.TButton", background="#334155", foreground=TEXT, padding=(12, 8))
        style.map("Secondary.TButton", background=[("active", "#475569")])
        style.configure("Danger.TButton", background="#881337", foreground=TEXT, padding=(12, 8))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(20, 10))
        style.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", TEXT)])
        style.configure("Treeview", background=CARD, foreground=TEXT, fieldbackground=CARD, rowheight=32, borderwidth=0)
        style.configure("Treeview.Heading", background="#334155", foreground=TEXT, relief="flat")
        style.map("Treeview", background=[("selected", "#0369a1")])
        style.configure("TCheckbutton", background=CARD, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", CARD)])
        style.configure("TCombobox", fieldbackground="#f8fafc", foreground="#0f172a")

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(28, 20, 28, 12))
        header.pack(fill="x")
        ttk.Label(header, text="همراه‌نما", style="Title.TLabel").pack(side="right")
        self.tool_status = ttk.Label(header, style="Muted.TLabel")
        self.tool_status.pack(side="left", pady=(8, 0))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        self.connect_tab = ttk.Frame(self.notebook, padding=16)
        self.guide_tab = ttk.Frame(self.notebook, padding=16)
        self.settings_tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(self.connect_tab, text="اتصال و نمایش")
        self.notebook.add(self.guide_tab, text="راهنمای گوشی")
        self.notebook.add(self.settings_tab, text="تنظیمات تصویر")
        self._build_connect_tab()
        self._build_guide_tab()
        self._build_settings_tab()
        self._update_tool_status()

    def _card(self, parent, **grid) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame", padding=18)
        frame.grid(**grid)
        return frame

    def _build_connect_tab(self) -> None:
        self.connect_tab.columnconfigure(0, weight=1)
        self.connect_tab.rowconfigure(0, weight=1)
        devices_card = self._card(self.connect_tab, row=0, column=0, sticky="nsew", padx=(0, 8))
        devices_card.columnconfigure(0, weight=1)
        devices_card.rowconfigure(1, weight=1)
        title_row = ttk.Frame(devices_card, style="Card.TFrame")
        title_row.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(title_row, text="دستگاه‌های متصل", style="Heading.TLabel").pack(side="right")
        ttk.Button(title_row, text="تازه‌سازی", style="Secondary.TButton", command=self.refresh_devices).pack(side="left")

        columns = ("state", "android", "connection", "model")
        self.device_tree = ttk.Treeview(devices_card, columns=columns, show="headings", selectmode="browse")
        for key, text, width in (
            ("state", "وضعیت", 165), ("android", "اندروید", 90),
            ("connection", "نوع اتصال", 100), ("model", "گوشی", 220),
        ):
            self.device_tree.heading(key, text=text, anchor="e")
            self.device_tree.column(key, width=width, anchor="e")
        self.device_tree.grid(row=1, column=0, sticky="nsew")
        self.device_tree.bind("<<TreeviewSelect>>", self._device_selected)

        controls = ttk.Frame(devices_card, style="Card.TFrame")
        controls.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        ttk.Button(controls, text="نمایش گوشی", style="Accent.TButton", command=self.start_mirroring).pack(side="right")
        ttk.Button(controls, text="توقف", style="Danger.TButton", command=self.stop_mirroring).pack(side="right", padx=8)
        self.selected_info = ttk.Label(controls, text="یک گوشی را انتخاب کنید", style="CardMuted.TLabel")
        self.selected_info.pack(side="left")

        side = ttk.Frame(self.connect_tab)
        side.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        side.columnconfigure(0, weight=1)
        tools = self._card(side, row=0, column=0, sticky="ew")
        self.tools_card = tools
        ttk.Label(tools, text="ابزار اتصال", style="Heading.TLabel").pack(anchor="e")
        ttk.Label(tools, text="نسخه فعال", style="CardMuted.TLabel").pack(anchor="e", pady=(12, 4))
        self.arch_var = tk.StringVar(value="خودکار")
        arch_combo = ttk.Combobox(
            tools,
            textvariable=self.arch_var,
            values=["خودکار", "۶۴ بیتی", "۳۲ بیتی"],
            state="readonly",
            justify="right",
        )
        arch_combo.pack(fill="x")
        self._right_align_combo_popup(arch_combo)
        arch_combo.bind("<<ComboboxSelected>>", self._architecture_changed)
        self.install_label = ttk.Label(tools, style="CardMuted.TLabel", justify="right", anchor="e")
        self.install_label.pack(fill="x", pady=10)
        ttk.Button(tools, text="دریافت / بررسی به‌روزرسانی", style="Secondary.TButton", command=self.install_tools).pack(fill="x")

        wireless = self._card(side, row=1, column=0, sticky="ew", pady=(16, 0))
        self.wireless_card = wireless
        ttk.Label(wireless, text="اتصال بی‌سیم", style="Heading.TLabel").pack(anchor="e")
        ttk.Label(wireless, text="آدرس گوشی و پورت", style="CardMuted.TLabel").pack(anchor="e", pady=(12, 4))
        self.address_var = tk.StringVar(value="192.168.1.20:5555")
        self.address_combo = ttk.Combobox(wireless, textvariable=self.address_var, justify="right")
        self.address_combo.pack(fill="x")
        self._right_align_combo_popup(self.address_combo)
        ttk.Button(
            wireless,
            text="جستجوی گوشی‌ها در شبکه",
            style="Secondary.TButton",
            command=self.discover_network,
        ).pack(fill="x", pady=(8, 0))
        row = ttk.Frame(wireless, style="Card.TFrame")
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="اتصال", style="Accent.TButton", command=self.wifi_connect).pack(side="right", expand=True, fill="x")
        ttk.Button(row, text="فعال‌سازی از USB", style="Secondary.TButton", command=self.enable_wifi).pack(side="right", padx=(0, 6))
        self.pair_toggle = ttk.Button(
            wireless,
            text=PAIR_BUTTON_TEXT,
            style="Secondary.TButton",
            command=self.toggle_pairing,
        )
        self.pair_toggle.pack(fill="x", pady=(8, 0))
        self.pair_frame = ttk.Frame(wireless, style="Card.TFrame")
        ttk.Label(
            self.pair_frame,
            text="کد را از مسیر زیر در گوشی دریافت کنید:",
            style="CardMuted.TLabel",
            justify="right",
            anchor="e",
        ).pack(fill="x", pady=(10, 4))
        ttk.Label(
            self.pair_frame,
            text="Developer options  →  Wireless debugging\nPair device with pairing code",
            style="CardMuted.TLabel",
            justify="center",
            anchor="center",
        ).pack(fill="x", pady=(0, 6))
        self.pair_code_var = tk.StringVar()
        ttk.Entry(self.pair_frame, textvariable=self.pair_code_var, justify="right").pack(fill="x")
        ttk.Button(self.pair_frame, text="جفت‌سازی", style="Secondary.TButton", command=self.wifi_pair).pack(fill="x", pady=(8, 0))

        self.status_var = tk.StringVar(value="آماده")
        ttk.Label(
            self.connect_tab,
            textvariable=self.status_var,
            style="Muted.TLabel",
            anchor="e",
            justify="right",
            wraplength=940,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _right_align_combo_popup(self, combo: ttk.Combobox) -> None:
        def align_popup() -> None:
            try:
                popdown = self.tk.call("ttk::combobox::PopdownWindow", str(combo))
                self.tk.call(f"{popdown}.f.l", "configure", "-justify", "right")
            except tk.TclError:
                pass

        combo.configure(postcommand=align_popup)

    def _build_guide_tab(self) -> None:
        self.guide_tab.columnconfigure(0, weight=1)
        self.guide_tab.rowconfigure(1, weight=1)
        top = ttk.Frame(self.guide_tab)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(top, text="برند گوشی:").pack(side="right")
        self.brand_var = tk.StringVar(value="راهنمای عمومی")
        names = ["راهنمای عمومی", "سامسونگ", "شیائومی / ردمی / پوکو", "هواوی", "آنر", "وان‌پلاس", "اوپو", "ریلمی", "گوگل پیکسل", "موتورولا"]
        combo = ttk.Combobox(top, textvariable=self.brand_var, values=names, state="readonly", justify="right", width=28)
        combo.pack(side="right", padx=10)
        combo.bind("<<ComboboxSelected>>", lambda _event: self.show_guide(self.brand_var.get()))
        card = self._card(self.guide_tab, row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        self.guide_content = ttk.Frame(card, style="Card.TFrame")
        self.guide_content.grid(row=0, column=0, sticky="new", padx=12, pady=6)
        self.guide_content.columnconfigure(0, weight=1)
        self.show_guide("generic")

    def _build_settings_tab(self) -> None:
        self.settings_tab.columnconfigure(0, weight=1)
        card = self._card(self.settings_tab, row=0, column=0, sticky="new")
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="کیفیت و رفتار نمایش", style="Heading.TLabel").grid(row=0, column=0, columnspan=2, sticky="e", pady=(0, 14))
        self.size_var = tk.StringVar(value="1600")
        self.fps_var = tk.StringVar(value="60")
        self.bitrate_var = tk.StringVar(value="8M")
        self.mouse_mode_var = tk.StringVar(value="خودکار (پیشنهادی)")
        self._setting_row(card, 1, "حداکثر اندازه تصویر", self.size_var, ["1024", "1280", "1600", "1920"])
        self._setting_row(card, 2, "نرخ فریم", self.fps_var, ["30", "60", "90", "120"])
        self._setting_row(card, 3, "نرخ بیت ویدیو", self.bitrate_var, ["4M", "8M", "12M", "16M"])
        self._setting_row(
            card, 4, "حالت کنترل ماوس", self.mouse_mode_var,
            ["خودکار (پیشنهادی)", "سخت‌افزاری UHID", "معمولی SDK"],
        )
        self.audio_var = tk.BooleanVar(value=True)
        self.fullscreen_var = tk.BooleanVar(value=False)
        self.screen_off_var = tk.BooleanVar(value=False)
        self.awake_var = tk.BooleanVar(value=False)
        for row, text, variable in (
            (5, "انتقال صدا (اندروید ۱۱ به بالا)", self.audio_var),
            (6, "شروع در حالت تمام‌صفحه", self.fullscreen_var),
            (7, "خاموش‌کردن صفحه گوشی هنگام نمایش", self.screen_off_var),
            (8, "روشن نگه‌داشتن گوشی هنگام اتصال", self.awake_var),
        ):
            ttk.Checkbutton(card, text=text, variable=variable).grid(row=row, column=0, columnspan=2, sticky="e", pady=5)
        record = ttk.Frame(card, style="Card.TFrame")
        record.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        default_folder = Path.home() / "Pictures" / "HamrahNama"
        self.output_dir_var = tk.StringVar(value=str(default_folder))
        ttk.Button(record, text="انتخاب پوشه ذخیره", style="Secondary.TButton", command=self.choose_output_directory).pack(side="right")
        ttk.Label(record, textvariable=self.output_dir_var, style="CardMuted.TLabel", anchor="e").pack(side="right", padx=10, fill="x", expand=True)
        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(
            actions,
            text="عکس از صفحه  F8",
            style="Secondary.TButton",
            width=18,
            command=self.take_screenshot,
        ).pack(side="right")
        self.record_button = ttk.Button(
            actions,
            text="شروع ضبط  F9",
            style="Accent.TButton",
            width=18,
            command=self.toggle_recording,
        )
        self.record_button.pack(side="right", padx=(0, 8))
        ttk.Label(
            card,
            text="میانبرهای F8 و F9 هنگامی عمل می‌کنند که پنجره همراه‌نما فعال باشد.",
            style="CardMuted.TLabel",
            anchor="e",
        ).grid(row=11, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def _setting_row(self, parent, row: int, label: str, variable: tk.StringVar, values: list[str]) -> None:
        ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=1, sticky="e", padx=(14, 0), pady=7)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=20, justify="right")
        combo.grid(row=row, column=0, sticky="e", pady=7)
        self._right_align_combo_popup(combo)

    def _background(self, work: Callable, success: Callable | None = None) -> None:
        def runner():
            try:
                value = work()
                if success:
                    self.events.put((success, (value,)))
            except Exception as exc:
                self.events.put((self._show_error, (str(exc),)))
        threading.Thread(target=runner, daemon=True).start()

    def _drain_events(self) -> None:
        try:
            while True:
                callback, args = self.events.get_nowait()
                callback(*args)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _show_error(self, message: str) -> None:
        self.status_var.set(message)
        messagebox.showerror("خطا", message, parent=self)

    def _update_tool_status(self) -> None:
        system_arch = self.binaries.architecture
        active_arch = self.binaries.active_architecture
        installed32 = self.binaries.find_scrcpy("win32") is not None
        installed64 = self.binaries.find_scrcpy("win64") is not None
        version32 = self.binaries.installed_version("win32")
        version64 = self.binaries.installed_version("win64")
        active_installed = installed64 if active_arch == "win64" else installed32
        self.tool_status.configure(
            text=f"ویندوز {'۶۴' if system_arch == 'win64' else '۳۲'} بیتی • "
                 f"نسخه فعال {'۶۴' if active_arch == 'win64' else '۳۲'} بیتی"
        )
        self.install_label.configure(
            text=f"نسخه ۶۴ بیتی: {f'v{version64}' if version64 else 'نصب نشده'}\n"
                 f"نسخه ۳۲ بیتی: {f'v{version32}' if version32 else 'نصب نشده'}\n"
                 f"{'آماده استفاده' if active_installed else 'نسخه فعال هنوز دریافت نشده است'}"
        )

    def _architecture_changed(self, _event=None) -> None:
        selected = {"خودکار": "auto", "۶۴ بیتی": "win64", "۳۲ بیتی": "win32"}[self.arch_var.get()]
        try:
            self.binaries.select_architecture(selected)
        except ValueError as exc:
            self.arch_var.set("خودکار")
            self.binaries.select_architecture("auto")
            self._show_error(str(exc))
            return
        self._update_tool_status()
        self.status_var.set(
            f"نسخه {'۶۴' if self.binaries.active_architecture == 'win64' else '۳۲'} بیتی برای اجرای بعدی انتخاب شد."
        )
        self.refresh_devices()

    def install_tools(self) -> None:
        self.status_var.set("در حال بررسی آخرین نسخه رسمی…")
        def progress(value: int):
            self.events.put((self.status_var.set, (f"در حال دریافت هر دو نسخه… {value}٪",)))
        self._background(lambda: self.binaries.install_all(progress=progress), self._install_done)

    def _install_done(self, result: dict[str, object]) -> None:
        installed = result["installed"]
        version = result["version"]
        if installed:
            labels = {"win32": "۳۲ بیتی", "win64": "۶۴ بیتی"}
            changed = " و ".join(labels[arch] for arch in installed)
            self.status_var.set(f"نسخه {version} برای {changed} نصب یا به‌روزرسانی شد.")
        else:
            self.status_var.set(f"هر دو معماری از قبل روی آخرین نسخه ({version}) هستند؛ دانلودی انجام نشد.")
        self._update_tool_status()
        self.refresh_devices()

    def refresh_devices(self) -> None:
        if not self.binaries.find_adb():
            self.status_var.set("برای شناسایی گوشی، ابتدا ابزار رسمی را دریافت کنید.")
            return
        self.status_var.set("در حال شناسایی گوشی‌ها…")
        self._background(self.service.list_devices, self._render_devices)

    def _render_devices(self, devices: list[Device]) -> None:
        selected = self.device_tree.selection()
        selected_serial = selected[0] if selected else ""
        self.device_tree.delete(*self.device_tree.get_children())
        self.devices = {device.serial: device for device in devices}
        for device in devices:
            android = f"{device.android_version or '—'}" + (f" (API {device.sdk})" if device.sdk else "")
            self.device_tree.insert("", "end", iid=device.serial, values=(device.state_fa, android, device.connection, device.display_name))
        if selected_serial in self.devices:
            self.device_tree.selection_set(selected_serial)
        self.status_var.set(
            rtl_count(len(devices), "دستگاه پیدا شد.")
            if devices else "گوشی پیدا نشد؛ کابل و مجوز USB را بررسی کنید."
        )

    def _selected_device(self, ready: bool = True) -> Device:
        selected = self.device_tree.selection()
        if not selected:
            raise ValueError("ابتدا یک گوشی را از فهرست انتخاب کنید.")
        device = self.devices[selected[0]]
        if ready and device.state != "device":
            raise ValueError("گوشی هنوز آماده نیست؛ پیام مجوز را روی گوشی تأیید کنید.")
        return device

    def _device_selected(self, _event=None) -> None:
        try:
            device = self._selected_device(ready=False)
        except ValueError:
            return
        details = [device.display_name, device.abi]
        self.selected_info.configure(text=" • ".join(item for item in details if item))
        brand = normalize_brand(device.manufacturer)
        display = {"samsung": "سامسونگ", "xiaomi": "شیائومی / ردمی / پوکو", "huawei": "هواوی", "honor": "آنر", "oneplus": "وان‌پلاس", "oppo": "اوپو", "realme": "ریلمی", "google": "گوگل پیکسل", "motorola": "موتورولا"}.get(brand, "راهنمای عمومی")
        self.brand_var.set(display)
        self.show_guide(brand)

    def _mirror_options(self, device: Device, record_path: str = "") -> MirrorOptions:
        selected_mouse_mode = self.mouse_mode_var.get()
        if selected_mouse_mode == "سخت‌افزاری UHID":
            mouse_mode = "uhid"
        elif selected_mouse_mode == "معمولی SDK":
            mouse_mode = "sdk"
        else:
            mouse_mode = "uhid" if normalize_brand(device.manufacturer) == "xiaomi" else "sdk"
        return MirrorOptions(
            max_size=int(self.size_var.get()), max_fps=int(self.fps_var.get()),
            video_bit_rate=self.bitrate_var.get(), audio=self.audio_var.get(),
            fullscreen=self.fullscreen_var.get(), turn_screen_off=self.screen_off_var.get(),
            stay_awake=self.awake_var.get(), record_path=record_path, mouse_mode=mouse_mode,
        )

    def start_mirroring(self) -> None:
        try:
            device = self._selected_device()
            if device.sdk is not None and device.sdk < 21:
                raise ValueError("scrcpy از اندروید پایین‌تر از ۵ پشتیبانی نمی‌کند.")
            self._launch_mirroring(device)
        except Exception as exc:
            self._show_error(str(exc))

    def _launch_mirroring(self, device: Device, record_path: str = "") -> None:
        options = self._mirror_options(device, record_path)
        self.service.start(device.serial, options)
        if record_path:
            self.status_var.set(f"ضبط ویدیو آغاز شد: {record_path}")
        elif options.mouse_mode == "uhid":
            self.status_var.set(f"نمایش {device.display_name} با ماوس UHID آغاز شد؛ Left Alt ماوس را آزاد می‌کند.")
        else:
            self.status_var.set(f"نمایش {device.display_name} آغاز شد.")

    def stop_mirroring(self) -> None:
        stopped = self.service.stop()
        was_recording = self.recording_active
        saved_path = self.current_record_path
        self.recording_active = False
        self.current_record_path = None
        self.record_button.configure(text="شروع ضبط  F9")
        if stopped and was_recording and saved_path:
            self.status_var.set(f"ضبط متوقف و ذخیره شد: {saved_path}")
        else:
            self.status_var.set("جلسه متوقف شد." if stopped else "جلسه فعالی وجود ندارد.")

    def _output_directory(self) -> Path:
        directory = Path(self.output_dir_var.get()).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def take_screenshot(self) -> None:
        try:
            device = self._selected_device()
            directory = self._output_directory()
        except Exception as exc:
            self._show_error(str(exc))
            return
        self.status_var.set("در حال ذخیره عکس صفحه…")
        self._background(
            lambda: self.service.capture_screenshot(device.serial, directory),
            self._screenshot_saved,
        )

    def _screenshot_saved(self, path: Path) -> None:
        self.status_var.set(f"عکس صفحه ذخیره شد: {path}")

    def toggle_recording(self) -> None:
        try:
            device = self._selected_device()
            if self.recording_active:
                saved_path = self.current_record_path
                self.service.stop()
                self.recording_active = False
                self.current_record_path = None
                self.record_button.configure(text="شروع ضبط  F9")
                self.status_var.set(f"ضبط متوقف و ذخیره شد: {saved_path}")
                self.after(350, lambda: self._restart_without_recording(device))
                return
            output = self._output_directory()
            record_path = output / f"recording-{datetime.now():%Y-%m-%d_%H-%M-%S}.mp4"
            self.service.stop()
            self.recording_active = True
            self.current_record_path = record_path
            self.record_button.configure(text="توقف ضبط  F9")
            self.after(350, lambda: self._restart_with_recording(device, record_path))
        except Exception as exc:
            self.recording_active = False
            self.current_record_path = None
            self.record_button.configure(text="شروع ضبط  F9")
            self._show_error(str(exc))

    def _restart_with_recording(self, device: Device, path: Path) -> None:
        try:
            self._launch_mirroring(device, str(path))
        except Exception as exc:
            self.recording_active = False
            self.current_record_path = None
            self.record_button.configure(text="شروع ضبط  F9")
            self._show_error(str(exc))

    def _restart_without_recording(self, device: Device) -> None:
        try:
            self._launch_mirroring(device)
        except Exception as exc:
            self._show_error(str(exc))

    def enable_wifi(self) -> None:
        try:
            device = self._selected_device()
        except Exception as exc:
            self._show_error(str(exc)); return
        self.status_var.set("در حال فعال‌سازی اتصال بی‌سیم…")
        self._background(lambda: self.service.enable_tcpip(device.serial), self._wifi_enabled)

    def _wifi_enabled(self, payload) -> None:
        result, address = payload
        if not result.ok:
            self._show_error(result.stderr or result.stdout); return
        if address:
            self.address_var.set(address)
            self.status_var.set("حالت بی‌سیم فعال شد؛ اتصال خودکار تا لحظاتی دیگر انجام می‌شود…")
            self.after(1200, self.wifi_connect)
        else:
            self.status_var.set("حالت بی‌سیم فعال شد، اما IP گوشی خوانده نشد؛ آدرس را دستی وارد کنید.")

    def wifi_connect(self) -> None:
        self.status_var.set("در حال اتصال بی‌سیم…")
        self._background(lambda: self.service.connect(self.address_var.get()), self._wireless_result)

    def discover_network(self) -> None:
        self.status_var.set("در حال جستجوی گوشی‌های قابل اتصال در شبکه محلی…")
        self._background(self.service.discover_network_devices, self._network_discovered)

    def _network_discovered(self, addresses: list[str]) -> None:
        self.address_combo.configure(values=addresses)
        if addresses:
            self.address_var.set(addresses[0])
            self.status_var.set(
                rtl_count(
                    len(addresses),
                    "آدرس قابل بررسی پیدا شد؛ آدرس را انتخاب و «اتصال» را بزنید.",
                )
            )
        else:
            self.status_var.set(
                "دستگاهی پیدا نشد؛ Wireless debugging را روی گوشی فعال و در صورت نیاز ابتدا جفت‌سازی کنید."
            )

    def wifi_pair(self) -> None:
        self.status_var.set("در حال جفت‌سازی…")
        self._background(lambda: self.service.pair(self.address_var.get(), self.pair_code_var.get()), self._wireless_result)

    def toggle_pairing(self) -> None:
        if self.pair_frame.winfo_manager():
            self.pair_frame.pack_forget()
            self.pair_toggle.configure(text=PAIR_BUTTON_TEXT)
            self.wireless_card.grid_configure(row=1, pady=(16, 0))
            self.tools_card.grid()
        else:
            self.tools_card.grid_remove()
            self.wireless_card.grid_configure(row=0, pady=0)
            self.pair_frame.pack(fill="x")
            self.pair_toggle.configure(text="بستن بخش جفت‌سازی")

    def _wireless_result(self, result) -> None:
        message = result.stdout or result.stderr
        if not result.ok or "failed" in message.lower():
            self._show_error(message or "اتصال ناموفق بود."); return
        self.status_var.set(message or "عملیات موفق بود.")
        self.after(500, self.refresh_devices)

    def show_guide(self, brand: str) -> None:
        guide = guide_for(brand)
        for child in self.guide_content.winfo_children():
            child.destroy()
        rtl = lambda value: f"\u202B{value}\u202C"
        ttk.Label(
            self.guide_content,
            text=rtl(guide["title"]),
            style="Heading.TLabel",
            font=("Segoe UI", 16, "bold"),
            foreground=BLUE,
            anchor="e",
            justify="right",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 14))
        ttk.Label(
            self.guide_content,
            text="مراحل فعال‌سازی",
            style="Heading.TLabel",
            anchor="e",
            justify="right",
        ).grid(row=1, column=0, sticky="ew", pady=(0, 6))
        for index, step in enumerate(guide["steps"], 1):
            ttk.Label(
                self.guide_content,
                text=rtl(f"{index}. {step}"),
                style="Card.TLabel",
                anchor="e",
                justify="right",
                wraplength=900,
            ).grid(row=index + 1, column=0, sticky="ew", pady=3)
        tips_row = len(guide["steps"]) + 2
        ttk.Label(
            self.guide_content,
            text="نکته‌ها",
            style="Heading.TLabel",
            anchor="e",
            justify="right",
        ).grid(row=tips_row, column=0, sticky="ew", pady=(14, 5))
        for offset, tip in enumerate(guide["tips"], 1):
            ttk.Label(
                self.guide_content,
                text=rtl(f"• {tip}"),
                style="CardMuted.TLabel",
                anchor="e",
                justify="right",
                wraplength=900,
            ).grid(row=tips_row + offset, column=0, sticky="ew", pady=3)

    def choose_output_directory(self) -> None:
        path = filedialog.askdirectory(parent=self, title="انتخاب پوشه ذخیره عکس‌ها و ویدیوها")
        if path:
            self.output_dir_var.set(path)


def run_app() -> None:
    app = HamrahNamaApp()
    app.mainloop()
