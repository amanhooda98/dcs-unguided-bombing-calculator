import json
import math
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectArtifactTests(unittest.TestCase):
    def test_telemetry_has_expected_legacy_header(self):
        telemetry_path = ROOT / "data" / "raw" / "bomb_flight_telemetry.csv"
        lines = telemetry_path.read_text().splitlines()
        header = next(line for line in lines if "Weapon_Name" in line)
        self.assertEqual(
            header,
            "Weapon_Name,Time_s,PosX,PosY_Alt,PosZ,VelX,VelY_Vert,VelZ",
        )

    def test_weapon_database_contains_valid_luts(self):
        database_path = ROOT / "data" / "processed" / "weapon_drag_database.json"
        database = json.loads(database_path.read_text())
        self.assertTrue(database)

        for weapon in database.values():
            table = weapon["dragTable"]
            self.assertGreater(len(table), 1)
            mach_values = [point["mach"] for point in table]
            self.assertEqual(mach_values, sorted(mach_values))
            self.assertTrue(
                all(
                    math.isfinite(point["mach"])
                    and math.isfinite(point["kd"])
                    and point["kd"] > 0
                    for point in table
                )
            )

    def test_browser_database_matches_json_database(self):
        json_path = ROOT / "data" / "processed" / "weapon_drag_database.json"
        js_path = ROOT / "docs" / "weapon_drag_database.js"
        database = json.loads(json_path.read_text())
        javascript = js_path.read_text()
        match = re.search(r"const WEAPON_DATABASE = (.*);\s*$", javascript, re.S)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1)), database)

    def test_pages_entry_point_loads_database(self):
        index_path = ROOT / "docs" / "index.html"
        html = index_path.read_text()
        self.assertIn('<script src="weapon_drag_database.js"></script>', html)
        self.assertTrue((index_path.parent / "weapon_drag_database.js").exists())


if __name__ == "__main__":
    unittest.main()
