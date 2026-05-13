"""Tests for custom beam sections — DB CRUD, API endpoints, merge logic, UI."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from macs_automation.db import ResultsDB


# ─── DB-level tests ───────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_results.db"
    with ResultsDB(db_path) as database:
        yield database


class TestCustomSectionsTable:
    def test_table_created(self, db):
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='custom_sections'"
        )
        assert cursor.fetchone() is not None

    def test_table_columns(self, db):
        cursor = db.conn.execute("PRAGMA table_info(custom_sections)")
        cols = {row[1] for row in cursor.fetchall()}
        assert {"id", "name", "h", "b", "tw", "tf", "created_at"} <= cols


class TestAddCustomSection:
    def test_returns_id(self, db):
        sec_id = db.add_custom_section("My Beam", h=500, b=200, tw=10.0, tf=16.0)
        assert sec_id.startswith("CUSTOM_")

    def test_auto_increment_ids(self, db):
        id1 = db.add_custom_section("Beam A", h=500, b=200, tw=10.0, tf=16.0)
        id2 = db.add_custom_section("Beam B", h=600, b=220, tw=11.0, tf=17.0)
        assert id1 == "CUSTOM_1"
        assert id2 == "CUSTOM_2"

    def test_stored_values(self, db):
        db.add_custom_section("Test Beam", h=450, b=190, tw=9.5, tf=15.0)
        sections = db.get_custom_sections()
        assert len(sections) == 1
        sec = sections[0]
        assert sec["name"] == "Test Beam"
        assert sec["h"] == 450
        assert sec["b"] == 190
        assert sec["tw"] == 9.5
        assert sec["tf"] == 15.0

    def test_created_at_set(self, db):
        db.add_custom_section("Beam", h=500, b=200, tw=10.0, tf=16.0)
        sections = db.get_custom_sections()
        assert sections[0]["created_at"] is not None


class TestGetCustomSections:
    def test_empty(self, db):
        assert db.get_custom_sections() == []

    def test_returns_all(self, db):
        db.add_custom_section("A", h=500, b=200, tw=10.0, tf=16.0)
        db.add_custom_section("B", h=600, b=220, tw=11.0, tf=17.0)
        sections = db.get_custom_sections()
        assert len(sections) == 2

    def test_ordered_by_name(self, db):
        db.add_custom_section("Zeta", h=500, b=200, tw=10.0, tf=16.0)
        db.add_custom_section("Alpha", h=600, b=220, tw=11.0, tf=17.0)
        sections = db.get_custom_sections()
        assert sections[0]["name"] == "Alpha"
        assert sections[1]["name"] == "Zeta"


class TestDeleteCustomSection:
    def test_delete_existing(self, db):
        sec_id = db.add_custom_section("Beam", h=500, b=200, tw=10.0, tf=16.0)
        db.delete_custom_section(sec_id)
        assert db.get_custom_sections() == []

    def test_delete_nonexistent_no_error(self, db):
        db.delete_custom_section("CUSTOM_999")  # should not raise


# ─── App-level tests ──────────────────────────────────────────────────────────

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


class TestCustomSectionAPI:
    def test_post_creates_section(self, client):
        resp = client.post("/api/custom-sections", json={
            "name": "My Custom", "h": 500, "b": 200, "tw": 10.0, "tf": 16.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"].startswith("CUSTOM_")
        assert data["name"] == "My Custom"
        assert data["h"] == 500

    def test_post_missing_field_returns_422(self, client):
        resp = client.post("/api/custom-sections", json={
            "name": "Incomplete", "h": 500,
        })
        assert resp.status_code == 422

    def test_get_lists_sections(self, client):
        client.post("/api/custom-sections", json={
            "name": "A", "h": 500, "b": 200, "tw": 10.0, "tf": 16.0,
        })
        client.post("/api/custom-sections", json={
            "name": "B", "h": 600, "b": 220, "tw": 11.0, "tf": 17.0,
        })
        resp = client.get("/api/custom-sections")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_delete_removes_section(self, client):
        resp = client.post("/api/custom-sections", json={
            "name": "Temp", "h": 500, "b": 200, "tw": 10.0, "tf": 16.0,
        })
        sec_id = resp.json()["id"]
        del_resp = client.delete(f"/api/custom-sections/{sec_id}")
        assert del_resp.status_code == 200
        # Verify gone
        get_resp = client.get("/api/custom-sections")
        assert len(get_resp.json()) == 0

    def test_delete_nonexistent_returns_200(self, client):
        resp = client.delete("/api/custom-sections/CUSTOM_999")
        assert resp.status_code == 200


class TestMergedSections:
    def test_api_sections_includes_custom(self, client):
        """GET /api/sections includes Custom family."""
        client.post("/api/custom-sections", json={
            "name": "My Custom", "h": 500, "b": 200, "tw": 10.0, "tf": 16.0,
        })
        resp = client.get("/api/sections")
        data = resp.json()
        assert "Custom" in data
        assert any(s["name"] == "My Custom (Custom)" for s in data["Custom"])

    def test_submit_run_with_custom_section(self, client):
        """POST /api/runs can use a custom section."""
        # Add a custom section first
        resp = client.post("/api/custom-sections", json={
            "name": "My Beam", "h": 500, "b": 200, "tw": 10.0, "tf": 16.0,
        })
        sec_id = resp.json()["id"]

        with patch("macs_automation.app._run_single_com") as mock_run:
            mock_run.return_value = {"uf_max": 0.5, "duration_ms": 100, "comp_failure": 0, "time_series": []}
            resp = client.post("/api/runs", json={"u_sec_size": sec_id, "method": "iso"})
        assert resp.status_code == 200
        # Verify the merged sections_db was passed to the engine
        call_args = mock_run.call_args
        sections_db = call_args[0][1]
        assert sec_id in sections_db
        assert sections_db[sec_id]["h"] == 500

    def test_sweep_uses_merged_sections(self, client):
        """POST /api/sweeps passes merged sections_db to background runner."""
        client.post("/api/custom-sections", json={
            "name": "My Beam", "h": 500, "b": 200, "tw": 10.0, "tf": 16.0,
        })
        payload = {
            "analysis_method": "iso",
            "sweep": {"qf": [300, 500]},
            "fixed": {"span1": 9, "span2": 9, "u_sec_size": "CUSTOM_1"},
        }

        with patch("macs_automation.app._run_sweep_background") as mock_bg:
            with patch("threading.Thread") as mock_thread:
                def start_side_effect():
                    args = mock_thread.call_args
                    target = args[1]["target"]
                    target_args = args[1].get("args", ())
                    target(*target_args)
                mock_instance = MagicMock()
                mock_instance.start = start_side_effect
                mock_thread.return_value = mock_instance
                resp = client.post("/api/sweeps", json=payload)
                assert resp.status_code == 200
                # Check the sections_db passed to _run_sweep_background
                sections_db = mock_bg.call_args[0][1]
                assert "CUSTOM_1" in sections_db


# ═══════════════════════════════════════════════════════════════════════════════
# Custom Decks — DB CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestCustomDecksTable:
    def test_table_created(self, db):
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='custom_decks'"
        )
        assert cursor.fetchone() is not None

    def test_table_columns(self, db):
        cursor = db.conn.execute("PRAGMA table_info(custom_decks)")
        cols = {row[1] for row in cursor.fetchall()}
        assert {"id", "name", "deck_type", "deck_depth", "deck_trug",
                "deck_top", "deck_bot", "deck_stiff_height", "created_at"} <= cols


class TestAddCustomDeck:
    def test_returns_id(self, db):
        deck_id = db.add_custom_deck("My Deck", deck_type="T", deck_depth=58,
                                      deck_trug=207, deck_top=106, deck_bot=62,
                                      deck_stiff_height=0)
        assert deck_id.startswith("CDECK_")

    def test_auto_increment_ids(self, db):
        id1 = db.add_custom_deck("Deck A", deck_type="T", deck_depth=58,
                                  deck_trug=207, deck_top=106, deck_bot=62,
                                  deck_stiff_height=0)
        id2 = db.add_custom_deck("Deck B", deck_type="R", deck_depth=51,
                                  deck_trug=150, deck_top=80, deck_bot=50,
                                  deck_stiff_height=10)
        assert id1 == "CDECK_1"
        assert id2 == "CDECK_2"

    def test_stored_values(self, db):
        db.add_custom_deck("Test Deck", deck_type="T", deck_depth=58,
                           deck_trug=207, deck_top=106, deck_bot=62,
                           deck_stiff_height=0)
        decks = db.get_custom_decks()
        assert len(decks) == 1
        d = decks[0]
        assert d["name"] == "Test Deck"
        assert d["deck_type"] == "T"
        assert d["deck_depth"] == 58
        assert d["deck_trug"] == 207
        assert d["deck_top"] == 106
        assert d["deck_bot"] == 62
        assert d["deck_stiff_height"] == 0

    def test_created_at_set(self, db):
        db.add_custom_deck("Deck", deck_type="T", deck_depth=58,
                           deck_trug=207, deck_top=106, deck_bot=62,
                           deck_stiff_height=0)
        decks = db.get_custom_decks()
        assert decks[0]["created_at"] is not None


class TestGetCustomDecks:
    def test_empty(self, db):
        assert db.get_custom_decks() == []

    def test_returns_all(self, db):
        db.add_custom_deck("A", deck_type="T", deck_depth=58,
                           deck_trug=207, deck_top=106, deck_bot=62,
                           deck_stiff_height=0)
        db.add_custom_deck("B", deck_type="R", deck_depth=51,
                           deck_trug=150, deck_top=80, deck_bot=50,
                           deck_stiff_height=10)
        assert len(db.get_custom_decks()) == 2

    def test_ordered_by_name(self, db):
        db.add_custom_deck("Zeta", deck_type="T", deck_depth=58,
                           deck_trug=207, deck_top=106, deck_bot=62,
                           deck_stiff_height=0)
        db.add_custom_deck("Alpha", deck_type="R", deck_depth=51,
                           deck_trug=150, deck_top=80, deck_bot=50,
                           deck_stiff_height=10)
        decks = db.get_custom_decks()
        assert decks[0]["name"] == "Alpha"
        assert decks[1]["name"] == "Zeta"


class TestDeleteCustomDeck:
    def test_delete_existing(self, db):
        deck_id = db.add_custom_deck("Deck", deck_type="T", deck_depth=58,
                                      deck_trug=207, deck_top=106, deck_bot=62,
                                      deck_stiff_height=0)
        db.delete_custom_deck(deck_id)
        assert db.get_custom_decks() == []

    def test_delete_nonexistent_no_error(self, db):
        db.delete_custom_deck("CDECK_999")  # should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# Custom Meshes — DB CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestCustomMeshesTable:
    def test_table_created(self, db):
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='custom_meshes'"
        )
        assert cursor.fetchone() is not None

    def test_table_columns(self, db):
        cursor = db.conn.execute("PRAGMA table_info(custom_meshes)")
        cols = {row[1] for row in cursor.fetchall()}
        assert {"id", "name", "main_area", "trans_area", "created_at"} <= cols


class TestAddCustomMesh:
    def test_returns_id(self, db):
        mesh_id = db.add_custom_mesh("My Mesh", main_area=142, trans_area=142)
        assert mesh_id.startswith("CMESH_")

    def test_auto_increment_ids(self, db):
        id1 = db.add_custom_mesh("Mesh A", main_area=142, trans_area=142)
        id2 = db.add_custom_mesh("Mesh B", main_area=193, trans_area=193)
        assert id1 == "CMESH_1"
        assert id2 == "CMESH_2"

    def test_stored_values(self, db):
        db.add_custom_mesh("Test Mesh", main_area=142, trans_area=98)
        meshes = db.get_custom_meshes()
        assert len(meshes) == 1
        m = meshes[0]
        assert m["name"] == "Test Mesh"
        assert m["main_area"] == 142
        assert m["trans_area"] == 98

    def test_created_at_set(self, db):
        db.add_custom_mesh("Mesh", main_area=142, trans_area=142)
        meshes = db.get_custom_meshes()
        assert meshes[0]["created_at"] is not None


class TestGetCustomMeshes:
    def test_empty(self, db):
        assert db.get_custom_meshes() == []

    def test_returns_all(self, db):
        db.add_custom_mesh("A", main_area=142, trans_area=142)
        db.add_custom_mesh("B", main_area=193, trans_area=193)
        assert len(db.get_custom_meshes()) == 2

    def test_ordered_by_name(self, db):
        db.add_custom_mesh("Zeta", main_area=142, trans_area=142)
        db.add_custom_mesh("Alpha", main_area=193, trans_area=193)
        meshes = db.get_custom_meshes()
        assert meshes[0]["name"] == "Alpha"
        assert meshes[1]["name"] == "Zeta"


class TestDeleteCustomMesh:
    def test_delete_existing(self, db):
        mesh_id = db.add_custom_mesh("Mesh", main_area=142, trans_area=142)
        db.delete_custom_mesh(mesh_id)
        assert db.get_custom_meshes() == []

    def test_delete_nonexistent_no_error(self, db):
        db.delete_custom_mesh("CMESH_999")  # should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# Custom Decks — API endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestCustomDeckAPI:
    def test_post_creates_deck(self, client):
        resp = client.post("/api/custom-decks", json={
            "name": "My Deck", "deck_type": "T", "deck_depth": 58,
            "deck_trug": 207, "deck_top": 106, "deck_bot": 62,
            "deck_stiff_height": 0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"].startswith("CDECK_")
        assert data["name"] == "My Deck"
        assert data["deck_depth"] == 58

    def test_post_missing_field_returns_422(self, client):
        resp = client.post("/api/custom-decks", json={
            "name": "Incomplete", "deck_type": "T",
        })
        assert resp.status_code == 422

    def test_get_lists_decks(self, client):
        client.post("/api/custom-decks", json={
            "name": "A", "deck_type": "T", "deck_depth": 58,
            "deck_trug": 207, "deck_top": 106, "deck_bot": 62,
            "deck_stiff_height": 0,
        })
        client.post("/api/custom-decks", json={
            "name": "B", "deck_type": "R", "deck_depth": 51,
            "deck_trug": 150, "deck_top": 80, "deck_bot": 50,
            "deck_stiff_height": 10,
        })
        resp = client.get("/api/custom-decks")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_delete_removes_deck(self, client):
        resp = client.post("/api/custom-decks", json={
            "name": "Temp", "deck_type": "T", "deck_depth": 58,
            "deck_trug": 207, "deck_top": 106, "deck_bot": 62,
            "deck_stiff_height": 0,
        })
        deck_id = resp.json()["id"]
        del_resp = client.delete(f"/api/custom-decks/{deck_id}")
        assert del_resp.status_code == 200
        assert len(client.get("/api/custom-decks").json()) == 0

    def test_delete_nonexistent_returns_200(self, client):
        resp = client.delete("/api/custom-decks/CDECK_999")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Custom Meshes — API endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestCustomMeshAPI:
    def test_post_creates_mesh(self, client):
        resp = client.post("/api/custom-meshes", json={
            "name": "My Mesh", "main_area": 142, "trans_area": 142,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"].startswith("CMESH_")
        assert data["name"] == "My Mesh"
        assert data["main_area"] == 142

    def test_post_missing_field_returns_422(self, client):
        resp = client.post("/api/custom-meshes", json={
            "name": "Incomplete",
        })
        assert resp.status_code == 422

    def test_get_lists_meshes(self, client):
        client.post("/api/custom-meshes", json={
            "name": "A", "main_area": 142, "trans_area": 142,
        })
        client.post("/api/custom-meshes", json={
            "name": "B", "main_area": 193, "trans_area": 193,
        })
        resp = client.get("/api/custom-meshes")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_delete_removes_mesh(self, client):
        resp = client.post("/api/custom-meshes", json={
            "name": "Temp", "main_area": 142, "trans_area": 142,
        })
        mesh_id = resp.json()["id"]
        del_resp = client.delete(f"/api/custom-meshes/{mesh_id}")
        assert del_resp.status_code == 200
        assert len(client.get("/api/custom-meshes").json()) == 0

    def test_delete_nonexistent_returns_200(self, client):
        resp = client.delete("/api/custom-meshes/CMESH_999")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Merged decks/meshes — config page, API, submit
# ═══════════════════════════════════════════════════════════════════════════════

class TestMergedDecks:
    def test_api_decks_includes_custom(self, client):
        client.post("/api/custom-decks", json={
            "name": "My Deck", "deck_type": "T", "deck_depth": 58,
            "deck_trug": 207, "deck_top": 106, "deck_bot": 62,
            "deck_stiff_height": 0,
        })
        resp = client.get("/api/decks")
        data = resp.json()
        custom_ids = [k for k in data if k.startswith("CDECK_")]
        assert len(custom_ids) == 1
        assert data[custom_ids[0]]["name"] == "My Deck (Custom)"

    def test_custom_decks_listed_before_standard(self, client):
        """Custom decks appear before standard decks in /api/decks (insertion order)."""
        client.post("/api/custom-decks", json={
            "name": "My Deck", "deck_type": "T", "deck_depth": 58,
            "deck_trug": 207, "deck_top": 106, "deck_bot": 62,
            "deck_stiff_height": 0,
        })
        resp = client.get("/api/decks")
        ids = list(resp.json().keys())
        custom_idx = next(i for i, k in enumerate(ids) if k.startswith("CDECK_"))
        t14_idx = ids.index("T14")
        assert custom_idx < t14_idx


class TestMergedMeshes:
    def test_api_meshes_includes_custom(self, client):
        client.post("/api/custom-meshes", json={
            "name": "My Mesh", "main_area": 142, "trans_area": 142,
        })
        resp = client.get("/api/meshes")
        data = resp.json()
        custom_ids = [k for k in data if k.startswith("CMESH_")]
        assert len(custom_ids) == 1
        assert data[custom_ids[0]]["name"] == "My Mesh (Custom)"

    def test_custom_meshes_listed_before_standard(self, client):
        """Custom meshes appear before standard meshes in /api/meshes (insertion order)."""
        client.post("/api/custom-meshes", json={
            "name": "My Mesh", "main_area": 142, "trans_area": 142,
        })
        resp = client.get("/api/meshes")
        ids = list(resp.json().keys())
        custom_idx = next(i for i, k in enumerate(ids) if k.startswith("CMESH_"))
        st15c_idx = ids.index("ST15C")
        assert custom_idx < st15c_idx


class TestSubmitWithCustomDeckMesh:
    def test_submit_run_with_custom_deck(self, client):
        """Custom deck values (not defaults) flow through to engine params."""
        # Use distinctive values that differ from any standard deck
        resp = client.post("/api/custom-decks", json={
            "name": "Unique Deck", "deck_type": "R", "deck_depth": 99.9,
            "deck_trug": 333, "deck_top": 111, "deck_bot": 77,
            "deck_stiff_height": 15.5,
        })
        deck_id = resp.json()["id"]

        with patch("macs_automation.app._run_single_com") as mock_run:
            mock_run.return_value = {"uf_max": 0.5, "duration_ms": 100, "comp_failure": 0, "time_series": []}
            resp = client.post("/api/runs", json={"deck_id": deck_id, "method": "iso"})
        assert resp.status_code == 200
        # Verify ALL custom deck fields were resolved into params
        call_args = mock_run.call_args[0][0]
        assert call_args["deck_type"] == "R"
        assert call_args["deck_depth"] == 99.9
        assert call_args["deck_trug"] == 333
        assert call_args["deck_top"] == 111
        assert call_args["deck_bot"] == 77
        assert call_args["deck_stiff_height"] == 15.5

    def test_submit_run_with_custom_mesh(self, client):
        """Custom mesh values (not defaults) flow through to engine params."""
        # Use distinctive values that differ from standard meshes
        resp = client.post("/api/custom-meshes", json={
            "name": "Unique Mesh", "main_area": 999, "trans_area": 777,
        })
        mesh_id = resp.json()["id"]

        with patch("macs_automation.app._run_single_com") as mock_run:
            mock_run.return_value = {"uf_max": 0.5, "duration_ms": 100, "comp_failure": 0, "time_series": []}
            resp = client.post("/api/runs", json={"mesh_type": mesh_id, "method": "iso"})
        assert resp.status_code == 200
        # Verify both mesh areas resolved from custom values
        call_args = mock_run.call_args[0][0]
        assert call_args["mesh_area_max"] == 999
        assert call_args["mesh_area_min"] == 777

    def test_sweep_uses_custom_deck_values(self, client):
        """Sweep resolves custom deck values correctly."""
        client.post("/api/custom-decks", json={
            "name": "Sweep Deck", "deck_type": "T", "deck_depth": 75,
            "deck_trug": 250, "deck_top": 120, "deck_bot": 70,
            "deck_stiff_height": 5,
        })
        payload = {
            "analysis_method": "iso",
            "sweep": {"qf": [300, 500]},
            "fixed": {"span1": 9, "span2": 9, "deck_id": "CDECK_1"},
        }

        with patch("macs_automation.app._run_sweep_background") as mock_bg:
            with patch("threading.Thread") as mock_thread:
                def start_side_effect():
                    args = mock_thread.call_args
                    target = args[1]["target"]
                    target_args = args[1].get("args", ())
                    target(*target_args)
                mock_instance = MagicMock()
                mock_instance.start = start_side_effect
                mock_thread.return_value = mock_instance
                resp = client.post("/api/sweeps", json=payload)
                assert resp.status_code == 200
                # Check first combination has resolved deck values
                combinations = mock_bg.call_args[0][0]
                assert combinations[0]["deck_depth"] == 75
                assert combinations[0]["deck_trug"] == 250

    def test_sweep_uses_custom_mesh_values(self, client):
        """Sweep resolves custom mesh values correctly."""
        client.post("/api/custom-meshes", json={
            "name": "Sweep Mesh", "main_area": 500, "trans_area": 300,
        })
        payload = {
            "analysis_method": "iso",
            "sweep": {"qf": [300, 500]},
            "fixed": {"span1": 9, "span2": 9, "mesh_type": "CMESH_1"},
        }

        with patch("macs_automation.app._run_sweep_background") as mock_bg:
            with patch("threading.Thread") as mock_thread:
                def start_side_effect():
                    args = mock_thread.call_args
                    target = args[1]["target"]
                    target_args = args[1].get("args", ())
                    target(*target_args)
                mock_instance = MagicMock()
                mock_instance.start = start_side_effect
                mock_thread.return_value = mock_instance
                resp = client.post("/api/sweeps", json=payload)
                assert resp.status_code == 200
                combinations = mock_bg.call_args[0][0]
                assert combinations[0]["mesh_area_max"] == 500
                assert combinations[0]["mesh_area_min"] == 300
