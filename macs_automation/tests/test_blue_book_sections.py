"""Tests for Blue Book UB section database — data integrity, merge logic, UI."""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from macs_automation.blue_book_sections import UB_SECTIONS, get_blue_book_sections


# ─── Data integrity tests ────────────────────────────────────────────────────

class TestUBSectionsData:
    def test_has_sections(self):
        assert len(UB_SECTIONS) >= 90

    def test_all_sections_have_required_keys(self):
        for serial, props in UB_SECTIONS.items():
            assert "h" in props, f"{serial} missing h"
            assert "b" in props, f"{serial} missing b"
            assert "tw" in props, f"{serial} missing tw"
            assert "tf" in props, f"{serial} missing tf"
            assert "mass_per_m" in props, f"{serial} missing mass_per_m"

    def test_all_values_positive(self):
        for serial, props in UB_SECTIONS.items():
            assert props["h"] > 0, f"{serial} h must be positive"
            assert props["b"] > 0, f"{serial} b must be positive"
            assert props["tw"] > 0, f"{serial} tw must be positive"
            assert props["tf"] > 0, f"{serial} tf must be positive"
            assert props["mass_per_m"] > 0, f"{serial} mass_per_m must be positive"

    def test_h_greater_than_b(self):
        """Beam depth should always exceed flange width."""
        for serial, props in UB_SECTIONS.items():
            assert props["h"] > props["b"], f"{serial}: h ({props['h']}) should be > b ({props['b']})"

    def test_tf_greater_than_tw(self):
        """Flange thickness typically exceeds web thickness for UB sections."""
        for serial, props in UB_SECTIONS.items():
            assert props["tf"] >= props["tw"], (
                f"{serial}: tf ({props['tf']}) should be >= tw ({props['tw']})"
            )

    def test_key_format(self):
        """Keys should be in 'AxBxC' serial format."""
        for serial in UB_SECTIONS:
            parts = serial.split("x")
            assert len(parts) == 3, f"Key '{serial}' should have 3 parts separated by 'x'"
            for part in parts:
                assert part.isdigit() or part.replace(".", "").isdigit(), (
                    f"Key part '{part}' in '{serial}' should be numeric"
                )

    def test_specific_section_values(self):
        """Spot-check a few well-known sections against Blue Book values."""
        # UB 457x191x89 — very common beam
        sec = UB_SECTIONS["457x191x89"]
        assert sec["h"] == pytest.approx(463.4, abs=0.5)
        assert sec["b"] == pytest.approx(191.9, abs=0.5)
        assert sec["tw"] == pytest.approx(10.5, abs=0.2)
        assert sec["tf"] == pytest.approx(17.7, abs=0.2)

        # UB 610x229x113 — common secondary beam
        sec = UB_SECTIONS["610x229x113"]
        assert sec["h"] == pytest.approx(607.6, abs=0.5)
        assert sec["b"] == pytest.approx(228.2, abs=0.5)

    def test_533x165x74_serial_size(self):
        """533x165 UB 74 — the Blue Book serial is x74 even though the actual
        mass is 74.7 kg/m, so it can't be derived by rounding the mass."""
        assert "533x165x75" not in UB_SECTIONS, "x75 is not a Blue Book serial size"
        sec = UB_SECTIONS["533x165x74"]
        assert sec["h"] == pytest.approx(529.1, abs=0.05)
        assert sec["b"] == pytest.approx(165.9, abs=0.05)
        assert sec["tw"] == pytest.approx(9.7, abs=0.05)
        assert sec["tf"] == pytest.approx(13.6, abs=0.05)
        assert sec["mass_per_m"] == pytest.approx(74.7, abs=0.05)

    @pytest.mark.parametrize("serial,wrong,h,b,tw,tf,mass", [
        # Verified against the British Steel "Advance UK Beams" datasheet.
        # Each was stored under a serial derived by rounding mass_per_m; the
        # official designation is conventional and can't be computed from mass.
        ("914x305x239", "914x305x238", 915.0, 305.0, 16.5, 25.9, 238.3),
        ("533x312x272", "533x312x273", 577.1, 320.2, 21.1, 37.6, 273.2),
        ("533x312x150", "533x312x151", 542.5, 312.0, 12.7, 20.3, 150.6),
        ("1016x305x437", "1016x305x438", 1026.1, 305.4, 26.9, 49.0, 437.0),
    ])
    def test_official_serial_sizes(self, serial, wrong, h, b, tw, tf, mass):
        assert wrong not in UB_SECTIONS, f"{wrong} is not a Blue Book serial size"
        sec = UB_SECTIONS[serial]
        assert sec["h"] == pytest.approx(h, abs=0.05)
        assert sec["b"] == pytest.approx(b, abs=0.05)
        assert sec["tw"] == pytest.approx(tw, abs=0.05)
        assert sec["tf"] == pytest.approx(tf, abs=0.05)
        assert sec["mass_per_m"] == pytest.approx(mass, abs=0.05)

    @pytest.mark.parametrize("serial,h,b", [
        ("914x305x576", 993.0, 322.0),
        ("914x305x521", 981.0, 319.0),
        ("914x305x474", 971.0, 316.0),
        ("914x305x425", 961.0, 313.0),
    ])
    def test_extended_914x305_range_retained(self, serial, h, b):
        """The heavy 914x305 sections aren't in British Steel's rolled range or
        the classic BS 4-1 tables, but they are real EN 10365 / ArcelorMittal
        sections. Pinned so a future catalogue audit doesn't delete them."""
        sec = UB_SECTIONS[serial]
        assert sec["h"] == pytest.approx(h, abs=0.05)
        assert sec["b"] == pytest.approx(b, abs=0.05)

    def test_serial_sizes_cover_all_families(self):
        """Check that major serial size groups are present."""
        serials = set(UB_SECTIONS.keys())
        expected_prefixes = [
            "1016x305", "914x305", "914x419", "838x292", "762x267",
            "686x254", "610x305", "610x229", "610x178",
            "533x312", "533x210", "533x165",
            "457x191", "457x152",
            "406x178", "406x140",
            "356x171", "356x127",
            "305x165", "305x127", "305x102",
            "254x146", "254x102",
            "203x133", "203x102", "178x102",
        ]
        for prefix in expected_prefixes:
            matching = [s for s in serials if s.startswith(prefix)]
            assert len(matching) >= 1, f"No sections found for family {prefix}"


# ─── get_blue_book_sections() tests ──────────────────────────────────────────

class TestGetBlueBookSections:
    def test_returns_dict(self):
        sections = get_blue_book_sections()
        assert isinstance(sections, dict)

    def test_keys_have_ub_prefix(self):
        sections = get_blue_book_sections()
        for sec_id in sections:
            assert sec_id.startswith("UB_"), f"Key '{sec_id}' should start with 'UB_'"

    def test_values_have_family_field(self):
        sections = get_blue_book_sections()
        for sec_id, sec in sections.items():
            assert sec["family"] == "UB"

    def test_values_have_name_field(self):
        sections = get_blue_book_sections()
        for sec_id, sec in sections.items():
            assert sec["name"].startswith("UB ")

    def test_values_have_mass_per_m(self):
        sections = get_blue_book_sections()
        for sec_id, sec in sections.items():
            assert "mass_per_m" in sec
            assert sec["mass_per_m"] > 0

    def test_count_matches_raw_data(self):
        assert len(get_blue_book_sections()) == len(UB_SECTIONS)


# ─── Merge with Data.xml tests ──────────────────────────────────────────────

class TestMergeWithDataXml:
    def test_blue_book_fills_gaps(self):
        """Blue Book sections are added when not present in Data.xml."""
        from macs_automation.data_loader import _load_all_sections
        import xml.etree.ElementTree as ET

        # Minimal XML with no UB sections
        xml_str = "<root><IPE><Section Id='IPE_500' h='500' b='200' tw='10.2' tf='16'>IPE 500</Section></IPE></root>"
        root = ET.fromstring(xml_str)
        sections = _load_all_sections(root)

        # Should have IPE_500 from XML + all Blue Book UB sections
        assert "IPE_500" in sections
        bb_count = len(get_blue_book_sections())
        ub_in_result = [k for k in sections if k.startswith("UB_")]
        assert len(ub_in_result) == bb_count

    def test_data_xml_sections_not_overwritten(self):
        """If Data.xml already has a UB section, Blue Book doesn't overwrite it."""
        from macs_automation.data_loader import _load_all_sections
        import xml.etree.ElementTree as ET

        # XML has UB_457x191x89 with a custom grade
        xml_str = (
            "<root><UB>"
            "<Section Id='UB_457x191x89' h='463' b='192' tw='10.5' tf='17.7' grade='S355'>UB 457x191x89</Section>"
            "</UB></root>"
        )
        root = ET.fromstring(xml_str)
        sections = _load_all_sections(root)

        # The Data.xml version should be kept (it has grade info)
        sec = sections["UB_457x191x89"]
        assert sec["grade"] == "S355"

    def test_remaining_blue_book_sections_added(self):
        """Blue Book sections not in Data.xml are still added."""
        from macs_automation.data_loader import _load_all_sections
        import xml.etree.ElementTree as ET

        # XML has just one UB section
        xml_str = (
            "<root><UB>"
            "<Section Id='UB_457x191x89' h='463' b='192' tw='10.5' tf='17.7'>UB 457x191x89</Section>"
            "</UB></root>"
        )
        root = ET.fromstring(xml_str)
        sections = _load_all_sections(root)

        # The 1016x305x584 should come from Blue Book
        assert "UB_1016x305x584" in sections
        assert sections["UB_1016x305x584"]["h"] == 1056.0


# ─── App-level tests (dropdown rendering) ───────────────────────────────────

@pytest.fixture(autouse=True)
def mock_ref_data():
    """Provide fake reference data so tests don't need Data.xml."""
    import macs_automation.app as app_module
    app_module._ref_data = {
        "sections": {
            "IPE_500": {"family": "IPE", "name": "IPE 500", "h": 500, "b": 200, "tw": 10.2, "tf": 16},
            "IPE_300": {"family": "IPE", "name": "IPE 300", "h": 300, "b": 150, "tw": 7.1, "tf": 10.7},
        },
        "decks": {
            "T14": {"deck_type": "T", "deck_depth": 58, "deck_trug": 207, "deck_top": 106, "deck_bot": 62, "deck_stiff_height": 0, "name": "COFRAPLUS 60"},
        },
        "meshes": {
            "ST15C": {"mainArea": 142, "transArea": 142, "min_mesh_dia": 6, "max_mesh_dia": 6, "name": "ST15C"},
        },
    }
    yield
    app_module._ref_data = None


@pytest.fixture
def use_tmp_db(tmp_path, monkeypatch):
    import macs_automation.app as app_module
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "test.db")
    return tmp_path / "test.db"


@pytest.fixture
def client(use_tmp_db):
    from macs_automation.app import app
    return TestClient(app)


class TestBlueBookSectionsApi:
    """The React config form pulls sections from /api/sections — verify Blue
    Book UBs are exposed there and ordered ahead of IPEs."""

    def test_api_sections_includes_ub_family(self, client):
        resp = client.get("/api/sections")
        assert resp.status_code == 200
        data = resp.json()
        assert "UB" in data
        # Should have all Blue Book sections
        assert len(data["UB"]) >= 90
        names = [s["name"] for s in data["UB"]]
        assert any("UB 457 x 191 x 89" in n for n in names)

    def test_blue_book_sections_loaded(self, client):
        """Blue Book UB metadata is loaded — h/b are populated for known sections."""
        from macs_automation.blue_book_sections import get_blue_book_sections
        bb = get_blue_book_sections()
        assert "UB_457x191x89" in bb
        assert bb["UB_457x191x89"]["h"] > 0

    def test_ub_family_listed_before_ipe(self, client):
        """The /api/ref-data response should serialise UB sections before IPE,
        matching the dropdown ordering the React form uses."""
        resp = client.get("/api/ref-data")
        data = resp.json()
        families = list(data["sections"].keys())
        assert "UB" in families and "IPE" in families
        assert families.index("UB") < families.index("IPE")

    def test_api_sections_includes_largest_ub(self, client):
        resp = client.get("/api/sections")
        data = resp.json()
        names = [s["name"] for s in data["UB"]]
        assert any("UB 1016 x 305 x 584" in n for n in names)

    def test_submit_run_with_blue_book_section(self, client):
        """Can submit a run using a Blue Book section ID."""
        with patch("macs_automation.app._run_single_com") as mock_run:
            mock_run.return_value = {
                "uf_max": 0.5, "duration_ms": 100,
                "comp_failure": 0, "time_series": [],
            }
            resp = client.post("/api/runs", json={
                "u_sec_size": "UB_457x191x89", "method": "iso",
            })
        assert resp.status_code == 200
        # Verify section was found in sections_db
        sections_db = mock_run.call_args[0][1]
        assert "UB_457x191x89" in sections_db
        assert sections_db["UB_457x191x89"]["h"] == pytest.approx(463.4, abs=0.5)
