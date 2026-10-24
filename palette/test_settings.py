"""Settings transfer and the Settings window: export -> import round trip, bad files refused, and every setting the
window shows survives load -> collect. Runs headless against a temporary config directory."""
import json, os, sys, tempfile, unittest

TMP = tempfile.mkdtemp(prefix="vimvibe-test-")
os.environ["XDG_CONFIG_HOME"] = TMP      # must be set before vimvibe_style computes its paths
os.environ["XDG_STATE_HOME"] = TMP
os.environ.pop("VIMVIBE_PROFILE", None)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
import vimvibe_keys as keys
import vimvibe_style as S

app = QApplication.instance() or QApplication([])


class Transfer(unittest.TestCase):
    def setUp(self):
        """Start every test from no config file."""
        if os.path.exists(S.CONFIG):
            os.remove(S.CONFIG)

    def test_round_trip(self):
        # changed colours, keys and a nested option come back after export, reset and import
        cfg = S.read_config()
        cfg["ui"]["accent"] = "#ff0000"; cfg["mouse"]["cols"] = 7; cfg["ocr"]["lang"] = "eng+deu"
        cfg["keys"] = {"mouse_grid": ["Ctrl+Alt+G"]}
        S.write_config(cfg)
        path = os.path.join(TMP, "export.json")
        S.export_settings(path, "test")
        data = json.load(open(path))
        self.assertEqual(data["format"], S.EXPORT_FORMAT)
        self.assertEqual(set(data["keys"]), set(keys.DEFAULTS))        # every binding is written, not only changes
        self.assertIn("double_tap_ms", data["config"]["behavior"])      # defaults are filled in
        os.remove(S.CONFIG)
        S.import_settings(path)
        back = S.read_config()
        self.assertEqual(back["ui"]["accent"], "#ff0000"); self.assertEqual(back["mouse"]["cols"], 7)
        self.assertEqual(back["ocr"]["lang"], "eng+deu")
        self.assertEqual(back["keys"], {"mouse_grid": ["Ctrl+Alt+G"]})  # unchanged bindings are not pinned

    def test_bad_files_are_refused(self):
        # a JSON file that is not an export, and wrongly typed values, change nothing
        path = os.path.join(TMP, "other.json")
        json.dump({"hello": 1}, open(path, "w"))
        with self.assertRaises(ValueError):
            S.import_settings(path)
        json.dump({"format": S.EXPORT_FORMAT, "config": {"mouse": {"cols": "many"}}}, open(path, "w"))
        S.import_settings(path)
        self.assertEqual(S.read_config()["mouse"]["cols"], S.DEFAULTS["mouse"]["cols"])

    def test_window_keeps_every_setting(self):
        # load -> collect in the Settings window returns every default option (no control drops one)
        from vimvibe_settings import SettingsWindow
        w = SettingsWindow(S.read_config, S.write_config, S.DEFAULTS)
        out = w.collect()
        for section, values in S.DEFAULTS.items():
            if isinstance(values, dict) and section != "keys":
                for k in values:
                    self.assertIn(k, out[section], f"{section}.{k}")
        self.assertTrue(w.enable_on_start.isChecked()); self.assertTrue(w.insert_after.isChecked())


if __name__ == "__main__":
    unittest.main()
