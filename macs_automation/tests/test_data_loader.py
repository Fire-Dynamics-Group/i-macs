"""Tests for data_loader module — parses Data.xml for sections, decks, meshes."""

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

from macs_automation.data_loader import (
    _load_all_sections,
    _load_decks,
    _load_meshes,
    load_data,
    lookup_section,
)

# Minimal XML for testing
SAMPLE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<Root>
   <Signature>FRACOFParameters</Signature>
   <FormatVersion>1.0</FormatVersion>

   <DeckRoot Id="DeckRoot" Name="Available decks">
      <TreeNode Id="T" Name="Trapezoidal">
         <TreeNode Id="T14" deck_type="T" deck_depth="58" deck_trug="207"
                   deck_top="106" deck_bot="62" deck_stiff_height="0"
                   icon="Bullet.gif" deck_cover="1035" deck_scale="58,24">COFRAPLUS 60</TreeNode>
      </TreeNode>
      <TreeNode Id="R" Name="Re-entrant">
         <TreeNode Id="R6" deck_type="R" deck_depth="40" deck_trug="150"
                   deck_top="46.5" deck_bot="124" deck_stiff_height="0"
                   icon="Bullet.gif" deck_cover="750" deck_scale="40,19">COFRASTRA 40</TreeNode>
      </TreeNode>
   </DeckRoot>

   <MeshRoot>
      <Mesh Id="A393" mainArea="393" transArea="393" min_mesh_dia="10" max_mesh_dia="10">A393</Mesh>
      <Mesh Id="B503" mainArea="503" transArea="252" min_mesh_dia="8" max_mesh_dia="8">B503</Mesh>
      <Mesh Id="UDF" mainArea="" transArea="" min_mesh_dia="" max_mesh_dia="">User defined</Mesh>
   </MeshRoot>

   <IPE>
      <Section Id="IPE_300" grade="235,275,355,35H,460" h="300" b="150" tw="7.1" tf="10.7">IPE 300</Section>
      <Section Id="IPE_500" grade="235,275,355,35H,460" h="500" b="200" tw="10.2" tf="16">IPE 500</Section>
   </IPE>

   <HE>
      <Section Id="HE_200B" grade="235,275,355,35H,460" h="200" b="200" tw="9" tf="15">HE 200 B</Section>
   </HE>

   <HL></HL>
   <HD></HD>
   <UB></UB>
   <UC></UC>
   <UBP></UBP>
   <HPUK></HPUK>
   <W></W>
   <HPUS></HPUS>
   <H></H>
</Root>
"""


@pytest.fixture
def sample_root():
    return ET.fromstring(SAMPLE_XML)


@pytest.fixture
def sample_xml_file(tmp_path):
    xml_file = tmp_path / "Data.xml"
    xml_file.write_text(SAMPLE_XML, encoding="utf-8")
    return xml_file


class TestLoadSections:
    def test_loads_ipe_sections(self, sample_root):
        sections = _load_all_sections(sample_root)
        assert "IPE_300" in sections
        assert "IPE_500" in sections

    def test_section_properties(self, sample_root):
        sections = _load_all_sections(sample_root)
        ipe500 = sections["IPE_500"]
        assert ipe500["family"] == "IPE"
        assert ipe500["h"] == 500.0
        assert ipe500["b"] == 200.0
        assert ipe500["tw"] == 10.2
        assert ipe500["tf"] == 16.0
        assert ipe500["name"] == "IPE 500"

    def test_loads_he_sections(self, sample_root):
        sections = _load_all_sections(sample_root)
        assert "HE_200B" in sections
        he200 = sections["HE_200B"]
        assert he200["family"] == "HE"
        assert he200["h"] == 200.0

    def test_total_section_count(self, sample_root):
        sections = _load_all_sections(sample_root)
        assert len(sections) == 3  # IPE_300, IPE_500, HE_200B


class TestLoadDecks:
    def test_loads_trapezoidal_deck(self, sample_root):
        decks = _load_decks(sample_root)
        assert "T14" in decks
        t14 = decks["T14"]
        assert t14["deck_type"] == "T"
        assert t14["deck_depth"] == 58.0
        assert t14["deck_trug"] == 207.0
        assert t14["name"] == "COFRAPLUS 60"

    def test_loads_reentrant_deck(self, sample_root):
        decks = _load_decks(sample_root)
        assert "R6" in decks
        r6 = decks["R6"]
        assert r6["deck_type"] == "R"
        assert r6["deck_depth"] == 40.0

    def test_deck_count(self, sample_root):
        decks = _load_decks(sample_root)
        assert len(decks) == 2


class TestLoadMeshes:
    def test_loads_mesh_types(self, sample_root):
        meshes = _load_meshes(sample_root)
        assert "A393" in meshes
        a393 = meshes["A393"]
        assert a393["mainArea"] == 393.0
        assert a393["transArea"] == 393.0
        assert a393["min_mesh_dia"] == 10.0
        assert a393["max_mesh_dia"] == 10.0

    def test_skips_udf_mesh(self, sample_root):
        meshes = _load_meshes(sample_root)
        assert "UDF" not in meshes

    def test_mesh_count(self, sample_root):
        meshes = _load_meshes(sample_root)
        assert len(meshes) == 2


class TestLookupSection:
    def test_found(self, sample_root):
        sections = _load_all_sections(sample_root)
        sec = lookup_section(sections, "IPE_500")
        assert sec["h"] == 500.0

    def test_not_found(self, sample_root):
        sections = _load_all_sections(sample_root)
        with pytest.raises(KeyError, match="NOTEXIST"):
            lookup_section(sections, "NOTEXIST")


class TestLoadData:
    def test_loads_from_file(self, sample_xml_file):
        data = load_data(sample_xml_file)
        assert "sections" in data
        assert "decks" in data
        assert "meshes" in data
        assert "IPE_500" in data["sections"]
        assert "T14" in data["decks"]
        assert "A393" in data["meshes"]


class TestRealDataXml:
    """Tests against the actual installed Data.xml file."""

    @pytest.fixture
    def real_data_path(self):
        path = Path(r"C:\Program Files (x86)\MACS+\EN\Data\Data.xml")
        if not path.exists():
            pytest.skip("MACS+ Data.xml not found — skipping real data tests")
        return path

    def test_loads_all_section_families(self, real_data_path):
        data = load_data(real_data_path)
        sections = data["sections"]
        # Should have sections from multiple families
        families = {s["family"] for s in sections.values()}
        assert "IPE" in families
        assert "HE" in families
        assert "UB" in families

    def test_has_many_sections(self, real_data_path):
        data = load_data(real_data_path)
        assert len(data["sections"]) > 100

    def test_has_decks(self, real_data_path):
        data = load_data(real_data_path)
        assert len(data["decks"]) > 10
        assert "T14" in data["decks"]

    def test_has_meshes(self, real_data_path):
        data = load_data(real_data_path)
        assert len(data["meshes"]) > 10
        assert "A393" in data["meshes"]

    def test_ipe_500_properties(self, real_data_path):
        data = load_data(real_data_path)
        ipe500 = data["sections"]["IPE_500"]
        assert ipe500["h"] == 500.0
        assert ipe500["b"] == 200.0
        assert ipe500["tw"] == 10.2
        assert ipe500["tf"] == 16.0
