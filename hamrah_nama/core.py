from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


SCRCPY_VERSION = "4.1"
SCRCPY_RELEASES = {
    "win64": {
        "version": SCRCPY_VERSION,
        "url": f"https://github.com/Genymobile/scrcpy/releases/download/v{SCRCPY_VERSION}/scrcpy-win64-v{SCRCPY_VERSION}.zip",
        "sha256": "5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db",
    },
    "win32": {
        "version": SCRCPY_VERSION,
        "url": f"https://github.com/Genymobile/scrcpy/releases/download/v{SCRCPY_VERSION}/scrcpy-win32-v{SCRCPY_VERSION}.zip",
        "sha256": "fa57b36622a53b6aec74c5e5b5c08236165efa445c4f186d48f176ebf9c24eec",
    },
}
SCRCPY_LATEST_API = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"


@dataclass(slots=True)
class CommandResult:
    code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0


@dataclass(slots=True)
class Device:
    serial: str
    state: str
    model: str = ""
    manufacturer: str = ""
    android_version: str = ""
    sdk: int | None = None
    abi: str = ""
    connection: str = "USB"

    @property
    def display_name(self) -> str:
        title = " ".join(part for part in (self.manufacturer, self.model) if part).strip()
        return title or self.serial

    @property
    def state_fa(self) -> str:
        return {
            "device": "آماده",
            "unauthorized": "در انتظار تأیید روی گوشی",
            "offline": "آفلاین",
            "no permissions": "بدون مجوز",
        }.get(self.state, self.state)


@dataclass(slots=True)
class MirrorOptions:
    max_size: int = 1600
    max_fps: int = 60
    video_bit_rate: str = "8M"
    audio: bool = True
    fullscreen: bool = False
    turn_screen_off: bool = False
    stay_awake: bool = False
    record_path: str = ""
    mouse_mode: str = "sdk"


def windows_architecture() -> str:
    machine = (os.environ.get("PROCESSOR_ARCHITEW6432") or platform.machine()).lower()
    return "win64" if "64" in machine else "win32"


def version_key(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", value)
    return tuple(int(number) for number in numbers) or (0,)


def parse_mdns_addresses(output: str) -> list[str]:
    addresses: set[str] = set()
    for line in output.splitlines():
        lowered = line.lower()
        if "_adb-tls-pairing" in lowered:
            continue
        if "_adb-tls-connect" not in lowered and "_adb._tcp" not in lowered:
            continue
        match = re.search(r"((?:\d{1,3}\.){3}\d{1,3}:\d{1,5})", line)
        if match:
            try:
                addresses.add(validate_address(match.group(1)))
            except ValueError:
                pass
    return sorted(addresses)


def _hidden_process_kwargs() -> dict:
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": startup, "creationflags": subprocess.CREATE_NO_WINDOW}


def run_command(args: Iterable[str], timeout: int = 15) -> CommandResult:
    try:
        completed = subprocess.run(
            [str(item) for item in args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **_hidden_process_kwargs(),
        )
        return CommandResult(completed.returncode, completed.stdout.strip(), completed.stderr.strip())
    except subprocess.TimeoutExpired as exc:
        return CommandResult(124, (exc.stdout or "").strip(), "زمان اجرای دستور به پایان رسید.")
    except OSError as exc:
        return CommandResult(127, "", str(exc))


class BinaryManager:
    def __init__(self, app_root: Path | None = None, data_root: Path | None = None):
        if app_root is not None:
            self.app_root = app_root
        elif getattr(sys, "frozen", False):
            self.app_root = Path(sys.executable).resolve().parent
        else:
            self.app_root = Path(__file__).resolve().parents[1]
        local = os.environ.get("LOCALAPPDATA")
        self.data_root = data_root or (Path(local) / "HamrahNama" if local else Path.home() / ".hamrah_nama")
        self.preferred_arch: str | None = None
        try:
            self.migrate_cached_tools()
        except (OSError, RuntimeError):
            pass

    @property
    def architecture(self) -> str:
        return windows_architecture()

    @property
    def active_architecture(self) -> str:
        return self.preferred_arch or self.architecture

    def select_architecture(self, arch: str) -> None:
        if arch not in {"auto", "win32", "win64"}:
            raise ValueError("معماری انتخاب‌شده معتبر نیست.")
        if arch == "win64" and self.architecture == "win32":
            raise ValueError("نسخه ۶۴ بیتی روی ویندوز ۳۲ بیتی اجرا نمی‌شود.")
        self.preferred_arch = None if arch == "auto" else arch

    def _tool_dirs(self, arch: str | None = None) -> list[Path]:
        arch = arch or self.active_architecture
        return [self.app_root / "tools" / arch, self.data_root / "tools" / arch]

    def _install_destination(self, arch: str) -> Path:
        candidates = [self.app_root / "tools" / arch, self.data_root / "tools" / arch]
        for directory in candidates:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(prefix=".write-test-", dir=directory):
                    pass
                return directory
            except OSError:
                continue
        raise PermissionError("امکان نوشتن ابزارها کنار برنامه یا در LocalAppData وجود ندارد.")

    def migrate_cached_tools(self) -> None:
        if self.app_root.resolve() == self.data_root.resolve():
            return
        for arch in ("win32", "win64"):
            app_destination = self._install_destination(arch)
            if self.data_root.resolve() in app_destination.resolve().parents:
                continue
            if list(app_destination.glob("scrcpy-*/scrcpy.exe")):
                continue
            data_directory = self.data_root / "tools" / arch
            matches = list(data_directory.glob("scrcpy-*/scrcpy.exe")) if data_directory.exists() else []
            if not matches:
                continue
            source_directory = max(matches, key=lambda item: version_key(item.parent.name)).parent
            target_directory = app_destination / source_directory.name
            shutil.copytree(source_directory, target_directory, dirs_exist_ok=True)
            if not (target_directory / "scrcpy.exe").is_file():
                raise RuntimeError("انتقال ابزارهای قبلی کنار برنامه کامل نشد.")

    def find_scrcpy(self, arch: str | None = None) -> Path | None:
        explicit_arch = arch is not None
        for directory in self._tool_dirs(arch):
            direct = directory / "scrcpy.exe"
            if direct.is_file():
                return direct
            matches = list(directory.glob("scrcpy-*/scrcpy.exe")) if directory.exists() else []
            if matches:
                return max(matches, key=lambda item: version_key(item.parent.name))
        found = None if explicit_arch else shutil.which("scrcpy")
        return Path(found) if found else None

    def find_adb(self) -> Path | None:
        scrcpy = self.find_scrcpy()
        if scrcpy and (scrcpy.parent / "adb.exe").is_file():
            return scrcpy.parent / "adb.exe"
        for directory in self._tool_dirs():
            for candidate in (directory / "adb.exe",):
                if candidate.is_file():
                    return candidate
            matches = list(directory.glob("scrcpy-*/adb.exe")) if directory.exists() else []
            if matches:
                return matches[0]
        found = shutil.which("adb")
        return Path(found) if found else None

    def installed_version(self, arch: str) -> str | None:
        executable = self.find_scrcpy(arch)
        if not executable:
            return None
        match = re.search(r"-v([0-9][0-9A-Za-z.\-]*)$", executable.parent.name)
        return match.group(1) if match else None

    def latest_release(self) -> tuple[str, dict[str, dict[str, str]]]:
        request = urllib.request.Request(
            SCRCPY_LATEST_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "HamrahNama-Updater"},
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.load(response)
        version = str(payload.get("tag_name", "")).removeprefix("v")
        if not version:
            raise RuntimeError("نسخه انتشار رسمی قابل تشخیص نیست.")
        releases: dict[str, dict[str, str]] = {}
        for arch in ("win32", "win64"):
            expected = f"scrcpy-{arch}-v{version}.zip"
            asset = next((item for item in payload.get("assets", []) if item.get("name") == expected), None)
            if not asset:
                raise RuntimeError(f"بسته رسمی {arch} در انتشار جدید پیدا نشد.")
            digest = str(asset.get("digest") or "")
            if not digest.startswith("sha256:"):
                raise RuntimeError(f"هش رسمی بسته {arch} در دسترس نیست.")
            releases[arch] = {
                "version": version,
                "url": str(asset["browser_download_url"]),
                "sha256": digest.split(":", 1)[1],
            }
        return version, releases

    def install(
        self,
        arch: str | None = None,
        progress: Callable[[int], None] | None = None,
        release: dict[str, str] | None = None,
    ) -> Path:
        arch = arch or self.active_architecture
        if arch not in SCRCPY_RELEASES:
            raise ValueError("معماری انتخاب‌شده معتبر نیست.")
        release = release or SCRCPY_RELEASES[arch]
        destination = self._install_destination(arch)
        with tempfile.TemporaryDirectory(prefix="hamrahnama-") as temporary:
            archive = Path(temporary) / "scrcpy.zip"

            def report(blocks: int, block_size: int, total: int) -> None:
                if progress and total > 0:
                    progress(min(100, int(blocks * block_size * 100 / total)))

            urllib.request.urlretrieve(release["url"], archive, reporthook=report)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if digest.lower() != release["sha256"].lower():
                raise RuntimeError("صحت فایل دانلودشده تأیید نشد؛ نصب متوقف شد.")
            with zipfile.ZipFile(archive) as package:
                root = destination.resolve()
                for member in package.infolist():
                    target = (destination / member.filename).resolve()
                    if root not in target.parents and target != root:
                        raise RuntimeError("ساختار بسته دانلودشده ناامن است.")
                package.extractall(destination)
        version = release["version"]
        matches = list(destination.glob(f"scrcpy-*-v{version}/scrcpy.exe"))
        executable = matches[0] if matches else None
        if not executable:
            raise RuntimeError("scrcpy پس از استخراج پیدا نشد.")
        destination_root = destination.resolve()
        for old_directory in destination.glob("scrcpy-*"):
            resolved = old_directory.resolve()
            if old_directory.is_dir() and resolved != executable.parent.resolve() and destination_root in resolved.parents:
                shutil.rmtree(resolved)
        return executable

    def install_all(self, progress: Callable[[int], None] | None = None) -> dict[str, object]:
        self.migrate_cached_tools()
        try:
            latest_version, releases = self.latest_release()
            checked_online = True
        except Exception:
            latest_version, releases = SCRCPY_VERSION, SCRCPY_RELEASES
            checked_online = False
        installed: dict[str, Path] = {}
        skipped: list[str] = []
        architectures = ("win32", "win64")
        pending = [
            arch for arch in architectures
            if self.find_scrcpy(arch) is None
            or (checked_online and self.installed_version(arch) != latest_version)
        ]
        if not pending:
            if progress:
                progress(100)
            return {"version": latest_version, "installed": installed, "skipped": list(architectures)}
        for index, arch in enumerate(pending):
            def mapped(value: int, offset: int = index, count: int = len(pending)) -> None:
                if progress:
                    progress(min(100, int((offset + value / 100) * 100 / count)))

            installed[arch] = self.install(arch=arch, progress=mapped, release=releases[arch])
        skipped = [arch for arch in architectures if arch not in installed]
        if progress:
            progress(100)
        return {"version": latest_version, "installed": installed, "skipped": skipped}


class ScrcpyService:
    def __init__(self, binaries: BinaryManager | None = None):
        self.binaries = binaries or BinaryManager()
        self.process: subprocess.Popen | None = None

    def _adb(self) -> Path:
        adb = self.binaries.find_adb()
        if not adb:
            raise FileNotFoundError("ADB نصب نیست. ابتدا ابزارهای scrcpy را دریافت کنید.")
        return adb

    def adb(self, *args: str, timeout: int = 15) -> CommandResult:
        return run_command([self._adb(), *args], timeout=timeout)

    def list_devices(self, include_properties: bool = True) -> list[Device]:
        result = self.adb("devices", "-l")
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout or "خواندن فهرست دستگاه‌ها ناموفق بود.")
        devices: list[Device] = []
        for line in result.stdout.splitlines()[1:]:
            line = line.strip()
            if not line or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            fields = dict(token.split(":", 1) for token in parts[2:] if ":" in token)
            device = Device(
                serial=serial,
                state=state,
                model=fields.get("model", "").replace("_", " "),
                connection="Wi‑Fi" if re.match(r"^\[?[0-9a-fA-F:.]+\]?:\d+$", serial) else "USB",
            )
            if include_properties and state == "device":
                self._populate_properties(device)
            devices.append(device)
        return devices

    def _property(self, serial: str, name: str) -> str:
        return self.adb("-s", serial, "shell", "getprop", name, timeout=8).stdout.strip()

    def _populate_properties(self, device: Device) -> None:
        device.manufacturer = self._property(device.serial, "ro.product.manufacturer")
        device.model = self._property(device.serial, "ro.product.model") or device.model
        device.android_version = self._property(device.serial, "ro.build.version.release")
        sdk = self._property(device.serial, "ro.build.version.sdk")
        device.sdk = int(sdk) if sdk.isdigit() else None
        device.abi = self._property(device.serial, "ro.product.cpu.abi")

    def pair(self, address: str, code: str) -> CommandResult:
        address = validate_address(address)
        if not re.fullmatch(r"\d{6}", code.strip()):
            raise ValueError("کد جفت‌سازی باید ۶ رقم باشد.")
        return self.adb("pair", address, code.strip(), timeout=30)

    def connect(self, address: str) -> CommandResult:
        return self.adb("connect", validate_address(address), timeout=30)

    def discover_network_devices(self) -> list[str]:
        addresses: set[str] = set()
        try:
            mdns = self.adb("mdns", "services", timeout=8)
            if mdns.ok:
                addresses.update(parse_mdns_addresses(mdns.stdout))
        except (FileNotFoundError, RuntimeError):
            pass

        local_ip = self._local_ipv4()
        if local_ip:
            network = ipaddress.ip_network(f"{local_ip}/24", strict=False)

            def has_adb_port(host: str) -> str | None:
                try:
                    with socket.create_connection((host, 5555), timeout=0.12):
                        return f"{host}:5555"
                except OSError:
                    return None

            hosts = [str(host) for host in network.hosts() if str(host) != local_ip]
            with ThreadPoolExecutor(max_workers=48) as executor:
                for address in executor.map(has_adb_port, hosts):
                    if address:
                        addresses.add(address)

        try:
            devices = self.list_devices(include_properties=False)
        except (FileNotFoundError, RuntimeError):
            devices = []
        for device in devices:
            if device.connection == "Wi‑Fi" and device.state == "device":
                addresses.add(device.serial)
        return sorted(
            addresses,
            key=lambda value: (
                ipaddress.ip_address(value.rsplit(":", 1)[0]),
                int(value.rsplit(":", 1)[1]),
            ),
        )

    @staticmethod
    def _local_ipv4() -> str:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("1.1.1.1", 80))
            address = probe.getsockname()[0]
            return address if not address.startswith("127.") else ""
        except OSError:
            try:
                addresses = socket.gethostbyname_ex(socket.gethostname())[2]
                return next((item for item in addresses if not item.startswith("127.")), "")
            except OSError:
                return ""
        finally:
            probe.close()

    def enable_tcpip(self, serial: str, port: int = 5555) -> tuple[CommandResult, str]:
        route = self.adb("-s", serial, "shell", "ip", "route", timeout=10)
        match = re.search(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)", route.stdout)
        result = self.adb("-s", serial, "tcpip", str(port), timeout=20)
        return result, (f"{match.group(1)}:{port}" if match else "")

    def build_mirror_command(self, serial: str, options: MirrorOptions) -> list[str]:
        executable = self.binaries.find_scrcpy()
        if not executable:
            raise FileNotFoundError("scrcpy نصب نیست. ابتدا ابزار مناسب را دریافت کنید.")
        args = [
            str(executable),
            "--serial", serial,
            f"--max-size={options.max_size}",
            f"--max-fps={options.max_fps}",
            f"--video-bit-rate={options.video_bit_rate}",
            "--window-title=همراه‌نما",
        ]
        if not options.audio:
            args.append("--no-audio")
        if options.fullscreen:
            args.append("--fullscreen")
        if options.turn_screen_off:
            args.append("--turn-screen-off")
        if options.stay_awake:
            args.append("--stay-awake")
        if options.record_path:
            args.append(f"--record={options.record_path}")
        if options.mouse_mode == "uhid":
            args.append("--mouse=uhid")
            args.append("--mouse-bind=bhsn:++++")
        return args

    def capture_screenshot(self, serial: str, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"screenshot-{datetime.now():%Y-%m-%d_%H-%M-%S}.png"
        completed = subprocess.run(
            [str(self._adb()), "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=20,
            **_hidden_process_kwargs(),
        )
        if completed.returncode != 0 or not completed.stdout.startswith(b"\x89PNG"):
            error = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(error or "گرفتن عکس از صفحه ناموفق بود.")
        target.write_bytes(completed.stdout)
        return target

    def start(self, serial: str, options: MirrorOptions) -> subprocess.Popen:
        if self.process and self.process.poll() is None:
            raise RuntimeError("یک جلسه نمایش در حال اجراست.")
        args = self.build_mirror_command(serial, options)
        popen_options = {}
        if os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        self.process = subprocess.Popen(args, cwd=str(Path(args[0]).parent), **popen_options)
        return self.process

    def stop(self) -> bool:
        if not self.process or self.process.poll() is not None:
            return False
        try:
            if os.name == "nt":
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.process.terminate()
            self.process.wait(timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(timeout=2)
        return True


def validate_address(address: str) -> str:
    address = address.strip()
    pattern = r"^(?:\d{1,3}\.){3}\d{1,3}:\d{1,5}$"
    if not re.fullmatch(pattern, address):
        raise ValueError("آدرس باید مانند 192.168.1.20:5555 باشد.")
    host, port_text = address.rsplit(":", 1)
    if any(int(part) > 255 for part in host.split(".")) or not 1 <= int(port_text) <= 65535:
        raise ValueError("آدرس یا پورت معتبر نیست.")
    return address
