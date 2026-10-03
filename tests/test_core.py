import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hamrah_nama.core import BinaryManager, Device, MirrorOptions, ScrcpyService, parse_mdns_addresses, validate_address, windows_architecture
from hamrah_nama.guides import guide_for, normalize_brand


class ArchitectureTests(unittest.TestCase):
    @patch.dict(os.environ, {"PROCESSOR_ARCHITEW6432": "AMD64"}, clear=False)
    def test_detects_64_bit_windows_from_wow64(self):
        self.assertEqual(windows_architecture(), "win64")

    def test_user_can_switch_architecture_on_64_bit_windows(self):
        manager = BinaryManager(Path("."), Path("."))
        with patch("hamrah_nama.core.windows_architecture", return_value="win64"):
            manager.select_architecture("win32")
            self.assertEqual(manager.active_architecture, "win32")
            manager.select_architecture("win64")
            self.assertEqual(manager.active_architecture, "win64")
            manager.select_architecture("auto")
            self.assertEqual(manager.active_architecture, "win64")

    def test_64_bit_is_rejected_on_32_bit_windows(self):
        manager = BinaryManager(Path("."), Path("."))
        with patch("hamrah_nama.core.windows_architecture", return_value="win32"):
            with self.assertRaises(ValueError):
                manager.select_architecture("win64")

    def test_install_all_requests_both_packages(self):
        manager = BinaryManager(Path("."), Path("."))
        release = {"win32": {"version": "9.0"}, "win64": {"version": "9.0"}}
        with patch.object(manager, "latest_release", return_value=("9.0", release)), \
             patch.object(manager, "find_scrcpy", return_value=None), \
             patch.object(manager, "install", side_effect=[Path("32.exe"), Path("64.exe")]) as install:
            result = manager.install_all()
        self.assertEqual(set(result["installed"]), {"win32", "win64"})
        self.assertEqual([call.kwargs["arch"] for call in install.call_args_list], ["win32", "win64"])

    def test_install_all_skips_current_packages(self):
        manager = BinaryManager(Path("."), Path("."))
        release = {"win32": {"version": "9.0"}, "win64": {"version": "9.0"}}
        with patch.object(manager, "latest_release", return_value=("9.0", release)), \
             patch.object(manager, "find_scrcpy", return_value=Path("scrcpy.exe")), \
             patch.object(manager, "installed_version", return_value="9.0"), \
             patch.object(manager, "install") as install:
            result = manager.install_all()
        install.assert_not_called()
        self.assertEqual(result["skipped"], ["win32", "win64"])

    def test_app_local_tools_have_priority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_root = root / "app"
            data_root = root / "data"
            app_exe = app_root / "tools" / "win64" / "scrcpy-win64-v9.0" / "scrcpy.exe"
            data_exe = data_root / "tools" / "win64" / "scrcpy-win64-v8.0" / "scrcpy.exe"
            app_exe.parent.mkdir(parents=True)
            data_exe.parent.mkdir(parents=True)
            app_exe.touch()
            data_exe.touch()
            manager = BinaryManager(app_root, data_root)
            self.assertEqual(manager.find_scrcpy("win64"), app_exe)

    def test_cached_tools_are_copied_beside_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_root = root / "app"
            data_root = root / "data"
            cached = data_root / "tools" / "win32" / "scrcpy-win32-v9.0"
            cached.mkdir(parents=True)
            (cached / "scrcpy.exe").write_bytes(b"exe")
            (cached / "adb.exe").write_bytes(b"adb")
            manager = BinaryManager(app_root, data_root)
            manager.migrate_cached_tools()
            copied = app_root / "tools" / "win32" / "scrcpy-win32-v9.0"
            self.assertTrue((copied / "scrcpy.exe").is_file())
            self.assertTrue((copied / "adb.exe").is_file())


class AddressTests(unittest.TestCase):
    def test_valid_address(self):
        self.assertEqual(validate_address("192.168.1.5:5555"), "192.168.1.5:5555")

    def test_invalid_address(self):
        for value in ("192.168.1.5", "999.1.1.1:4", "1.2.3.4:99999"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_address(value)

    def test_parses_connectable_mdns_services_only(self):
        output = """
        adb-device _adb-tls-connect._tcp. 192.168.1.12:37111
        adb-device _adb-tls-pairing._tcp. 192.168.1.12:38888
        old-device _adb._tcp. 192.168.1.20:5555
        """
        self.assertEqual(
            parse_mdns_addresses(output),
            ["192.168.1.12:37111", "192.168.1.20:5555"],
        )


class GuideTests(unittest.TestCase):
    def test_xiaomi_aliases(self):
        self.assertEqual(normalize_brand("Xiaomi"), "xiaomi")
        self.assertEqual(normalize_brand("POCO"), "xiaomi")
        self.assertIn("تنظیمات امنیتی", " ".join(guide_for("Redmi")["steps"]))


class CommandTests(unittest.TestCase):
    def test_mirror_command_contains_selected_options(self):
        manager = BinaryManager(Path("."), Path("."))
        service = ScrcpyService(manager)
        with patch.object(manager, "find_scrcpy", return_value=Path("C:/tools/scrcpy.exe")):
            command = service.build_mirror_command("ABC123", MirrorOptions(max_size=1280, max_fps=30, audio=False, fullscreen=True))
        self.assertIn("--serial", command)
        self.assertIn("ABC123", command)
        self.assertIn("--max-size=1280", command)
        self.assertIn("--max-fps=30", command)
        self.assertIn("--no-audio", command)
        self.assertIn("--fullscreen", command)

    def test_uhid_mouse_option(self):
        manager = BinaryManager(Path("."), Path("."))
        service = ScrcpyService(manager)
        with patch.object(manager, "find_scrcpy", return_value=Path("C:/tools/scrcpy.exe")):
            command = service.build_mirror_command("ABC123", MirrorOptions(mouse_mode="uhid"))
        self.assertIn("--mouse=uhid", command)
        self.assertIn("--mouse-bind=bhsn:++++", command)

    def test_device_friendly_state(self):
        device = Device("abc", "unauthorized")
        self.assertIn("تأیید", device.state_fa)

    def test_wifi_ip_is_read_before_tcpip_restart(self):
        manager = BinaryManager(Path("."), Path("."))
        service = ScrcpyService(manager)
        calls = []

        def fake_adb(*args, **_kwargs):
            calls.append(args)
            if "route" in args:
                from hamrah_nama.core import CommandResult
                return CommandResult(0, "default via 192.168.1.1 dev wlan0 src 192.168.1.9")
            from hamrah_nama.core import CommandResult
            return CommandResult(0, "restarting in TCP mode port: 5555")

        with patch.object(service, "adb", side_effect=fake_adb):
            result, address = service.enable_tcpip("USB123")
        self.assertTrue(result.ok)
        self.assertEqual(address, "192.168.1.9:5555")
        self.assertIn("route", calls[0])
        self.assertIn("tcpip", calls[1])

    def test_screenshot_is_saved_as_png(self):
        manager = BinaryManager(Path("."), Path("."))
        service = ScrcpyService(manager)
        png = b"\x89PNG\r\n\x1a\n" + b"test-image"
        completed = SimpleNamespace(returncode=0, stdout=png, stderr=b"")
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(service, "_adb", return_value=Path("adb.exe")), \
             patch("hamrah_nama.core.subprocess.run", return_value=completed):
            output = service.capture_screenshot("ABC123", Path(directory))
            self.assertEqual(output.read_bytes(), png)
            self.assertEqual(output.suffix, ".png")


if __name__ == "__main__":
    unittest.main()
