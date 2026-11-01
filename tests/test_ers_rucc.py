"""USDA ERS RUCC: land whole -> derive one rurality observation per county,
scoped as a writer to the stacked measure.observation table.

The fixture (tests/tiny_ers_rucc.csv) is a real excerpt of the downloaded
2023 CSV: a plain metro county, a Connecticut planning region, an Alaska
census area, and American Samoa's Rose Island, which has no RUCC_2023 row at
all (missing, not blank) -- the not_available case.
"""

from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import ers_rucc, merge

REL = "2026.08"
CSV = str(Path(__file__).parent / "tiny_ers_rucc.csv")
# Synthetic -- ERS's real file has never published a non-numeric, present
# RUCC_2023 value (verified 2026-09-18) -- built only to exercise the
# malformed-but-present case below.
MALFORMED_CSV = str(Path(__file__).parent / "tiny_ers_rucc_malformed.csv")


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole(cat):
    edition, n = ers_rucc.land_raw(cat, REL, url=CSV)
    assert edition == "2023"
    assert n == 11

    raw = rows(cat, "raw.ers__rucc")
    assert len(raw) == 11
    assert {r["FIPS"] for r in raw} == {"01001", "09110", "02063", "60030"}
    assert {r["rucc_edition"] for r in raw} == {"2023"}
    assert {r["landed_in"] for r in raw} == {REL}
    rucc_row = next(r for r in raw if r["FIPS"] == "01001" and r["Attribute"] == "RUCC_2023")
    assert rucc_row["Value"] == "2"  # unparsed string

    # re-landing the same edition replaces it rather than appending
    ers_rucc.land_raw(cat, REL, url=CSV)
    assert len(rows(cat, "raw.ers__rucc")) == 11


def test_a_changed_header_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("FIPS,State,County_Name,Attribute,Val\n01001,AL,Autauga County,RUCC_2023,2\n")
    with pytest.raises(SystemExit, match="Val"):
        ers_rucc.land_raw(cat, REL, url=str(bad))


def test_derives_definition_stratum_and_observations(cat):
    counts = ers_rucc.ingest(cat, REL, url=CSV)
    assert counts["raw.ers__rucc"] == 11

    defs = rows(cat, "measure.definition")
    assert len(defs) == 1
    d = defs[0]
    assert (d["measure_id"], d["source"], d["rate_basis"], d["method"]) == (
        "RUCC:code", "RUCC", "index", "derived")
    assert "1 = " in d["doc"] and "9 = " in d["doc"]

    strata = rows(cat, "measure.stratum")
    assert len(strata) == 1
    assert (strata[0]["stratum_id"], strata[0]["scheme"]) == ("RUCC:none", "RUCC_NONE")

    obs = {r["geo_id"]: r for r in rows(cat, "measure.observation", row_filter="source = 'RUCC'")}
    assert set(obs) == {"county:01001", "county:09110", "county:02063", "county:60030"}
    assert obs["county:01001"]["value"] == 2.0
    assert obs["county:01001"]["value_status"] == "reported"
    assert obs["county:01001"]["geo_vintage"] == 2020
    assert obs["county:01001"]["period_start"] == obs["county:01001"]["period_end"] == "2023"
    # Connecticut's 2022 planning region and Alaska's current census area land fine
    assert obs["county:09110"]["value"] == 1.0
    assert obs["county:02063"]["value"] == 9.0
    # Rose Island has no RUCC_2023 row at all: not_available, never a number, never dropped
    assert obs["county:60030"]["value"] is None
    assert obs["county:60030"]["value_status"] == "not_available"


def test_a_present_non_numeric_value_lands_not_available_not_reported(cat):
    """A cell that is present but doesn't parse as a number must not read as
    a numberless 'reported' row: value_status was derived from the raw cell's
    presence (`r.Value IS NOT NULL`) while `value` went through a separate
    `TRY_CAST`, so a present-but-non-numeric cell used to land as
    value_status='reported' with value NULL -- the same class of bug #141
    flagged in this module, and what merge.check_observations' reverse
    guard now catches for any source that regresses to it."""
    ers_rucc.ingest(cat, REL, url=MALFORMED_CSV)
    obs = rows(cat, "measure.observation", row_filter="source = 'RUCC'")
    assert len(obs) == 1
    assert obs[0]["value"] is None
    assert obs[0]["value_status"] == "not_available"


def test_rerun_is_idempotent(cat):
    ers_rucc.ingest(cat, REL, url=CSV)
    counts = ers_rucc.ingest(cat, "2026.09", url=CSV)
    assert counts["measure.observation"]["written"] == 0
    assert counts["measure.observation"]["unchanged"] == 4
    assert counts["measure.definition"] == 1
    assert counts["measure.stratum"] == 1


def other_observation():
    return dict(source="OTHER", source_release="V0", measure_id="OTHER:x", geo_id="county:99999",
               geo_vintage=2020, period_start="2020", period_end="2020", stratum_id="OTHER:none",
               value=1.0, lower=None, upper=None, interval_level=None, numerator=None,
               denominator=None, value_status="reported", reliability_flag=None, trend=None)


def test_rucc_does_not_retire_another_writer(cat):
    """measure.observation is a stacked, multi-writer table (SPEC.md § Measures):
    the merge scope must be (source, source_release), not source_release alone,
    or one source's re-ingest would retire another source's rows."""
    other = pa.Table.from_pylist([other_observation()])
    merge.merge(cat, "measure.observation", other, REL, EqualTo("source", "OTHER"))

    ers_rucc.ingest(cat, REL, url=CSV)
    ers_rucc.ingest(cat, "2026.09", url=CSV)

    live_other = rows(cat, "measure.observation",
                      row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_every_column_is_documented(cat):
    ers_rucc.ingest(cat, REL, url=CSV)
    table = cat.load_table("raw.ers__rucc")
    assert table.properties.get("comment")
    for f in table.schema().fields:
        assert f.doc, f"raw.ers__rucc.{f.name} has no doc"
