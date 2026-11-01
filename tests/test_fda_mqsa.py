"""FDA MQSA certified mammography facility list: land whole -> derive
facility.site (a Type-2, retire-on-disappearance table, kind='mammography').

Fixture is a real byte-for-byte excerpt of the live download (2026-09-18),
tests/tiny_fda_mqsa.txt: a plain facility with no Address 2/3, a military
facility with an "x"-extension phone number, a ZIP+4 facility, a Puerto
Rico facility whose name itself contains a comma (proving the pipe
delimiter, not comma, is what matters), and the real three-row "Invision
Diagnostics" listing that demonstrates FDA's own file lists one facility
more than once -- two of the three rows share a normalised key and collapse
to one, the third (different street spelling) keeps its own.
"""

import json
from pathlib import Path

import pyarrow as pa
import pytest
from pyiceberg.expressions import EqualTo

from cancerbasemap import fda_mqsa, merge

REL = "2026.09"
MQSA_TXT = str(Path(__file__).parent / "tiny_fda_mqsa.txt")

# The collision winner: "Invision Diagnostics - MOBILE" / "Elm Lane" (rn=1
# under ORDER BY "Facility Name", "Address 1"), not the "- Mobile" variant
# of the same address text.
COLLISION_ID = "FDA_MQSA:327fcf16b6a204be0e428a5e0dc1c6a8"


def rows(cat, identifier, **kw):
    return cat.load_table(identifier).scan(**kw).to_arrow().to_pylist()


def test_raw_is_verbatim_and_whole(cat):
    retrieved_on, n = fda_mqsa.land_raw(cat, REL, MQSA_TXT, retrieved_on="2026-09-18")
    assert retrieved_on == "2026-09-18"
    assert n == 7

    raw = rows(cat, "raw.fda__mqsa_facilities")
    assert len(raw) == 7
    assert {r["retrieved_on"] for r in raw} == {"2026-09-18"}
    assert {r["landed_in"] for r in raw} == {REL}

    keller = next(r for r in raw if r["Facility Name"] == "0086A-ACH Keller - West Point")
    assert keller["Zip Code"] == "10996-1197"          # ZIP+4 landed verbatim
    assert keller["Phone"] == "3157748801x8806"        # x-extension landed verbatim

    comma_name = next(r for r in raw if r["State"] == "PR")
    assert comma_name["Facility Name"] == "AGUADILLA MEDICAL SERVICES,INC"  # comma inside a field, pipe-delimited

    # re-landing the same retrieval date replaces it rather than appending
    fda_mqsa.land_raw(cat, REL, MQSA_TXT, retrieved_on="2026-09-18")
    assert len(rows(cat, "raw.fda__mqsa_facilities")) == 7


def test_a_changed_layout_fails_before_landing(cat, tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("Only One Field\r\n")
    with pytest.raises(SystemExit, match="pipe-delimited fields"):
        fda_mqsa.land_raw(cat, REL, url=str(bad))


def test_derives_facility_site(cat):
    counts = fda_mqsa.ingest(cat, REL, MQSA_TXT, retrieved_on="2026-09-18")
    assert counts["facility.site"]["written"] == 6
    assert counts["facility.site key collisions"] == 1

    sites = rows(cat, "facility.site")
    assert len(sites) == 6

    edgemont = next(r for r in sites if r["name"] == "1505 EDGEMONT MEDICAL OFFICES")
    assert edgemont["source"] == "FDA_MQSA"
    assert edgemont["source_release"] is None      # not part of the business key -- see module docstring
    assert edgemont["kind"] == "mammography"
    assert edgemont["address"] == "1505 N. Edgemont, Los Angeles, CA, 90027"
    assert edgemont["lat"] is None and edgemont["lon"] is None
    assert edgemont["geo_id"] is None and edgemont["geo_vintage"] is None
    assert json.loads(edgemont["attributes_json"]) == {"zip": "90027", "city": "Los Angeles", "state": "CA"}

    military = next(r for r in sites if "Aviano" in r["name"])
    assert military["address"] == "31 Medical Group, Unit 6180, Air Post Office, AE, 09604"

    aguadilla = next(r for r in sites if r["name"] == "AGUADILLA MEDICAL SERVICES,INC")
    assert aguadilla["address"] == "CARR 2 KM 129.5, BO. VICTORIA, Aguadilla, PR, 00603"


def test_collision_collapses_to_one_deterministic_survivor(cat):
    """The real "Invision Diagnostics" triple listing (module docstring):
    two rows share a normalised key and must collapse to exactly one row,
    picked deterministically -- not two facility.site rows silently
    violating the (facility_id, source) business key."""
    fda_mqsa.ingest(cat, REL, MQSA_TXT, retrieved_on="2026-09-18")
    invision = [r for r in rows(cat, "facility.site") if "Invision" in r["name"]]
    assert len(invision) == 2   # the colliding pair -> 1, the differently-spelled address -> 1

    collided = next(r for r in invision if r["facility_id"] == COLLISION_ID)
    assert collided["name"] == "Invision Diagnostics - MOBILE"   # deterministic tie-break, see module

    distinct = next(r for r in invision if r["facility_id"] != COLLISION_ID)
    assert "Elm Ln." in distinct["address"]


def test_facility_site_retires_dropped_and_renamed_looks_like_retire_plus_new(cat, tmp_path):
    """SPEC.md's facility history case, issue #36, with the issue #19
    interim fix (source_release NULL for FDA_MQSA): two snapshots on
    different retrieval dates where one facility is dropped and one is
    renamed. A rename changes facility_id itself (module docstring's
    ponytail note: name+address IS the key, so 'changed' structurally never
    happens for this source) -- it must present as one retirement plus one
    new facility, not a changed/superseded pair. Every genuinely untouched
    facility must stay on its original row."""
    fda_mqsa.ingest(cat, REL, MQSA_TXT, retrieved_on="2026-09-18")
    live_day1 = {r["name"] for r in rows(cat, "facility.site", row_filter="valid_to IS NULL")}
    assert len(live_day1) == 6

    # Day 2: "0086A-ACH Keller - West Point" has closed; "1505 EDGEMONT
    # MEDICAL OFFICES" was renamed -- everything else byte-identical.
    lines = Path(MQSA_TXT).read_text(encoding="utf-8").splitlines(keepends=True)
    lines = [l for l in lines if "0086A-ACH Keller" not in l]
    lines = [l.replace("1505 EDGEMONT MEDICAL OFFICES",
                       "1505 EDGEMONT MEDICAL OFFICES (RENAMED)") for l in lines]
    day2 = tmp_path / "day2.txt"
    day2.write_text("".join(lines), encoding="utf-8")

    counts = fda_mqsa.ingest(cat, "2026.10", str(day2), retrieved_on="2026-09-25")

    assert counts["facility.site"]["written"] == 3   # 2 retired (Keller + old Edgemont) + 1 new
    assert counts["facility.site"]["unchanged"] == 4  # the 4 genuinely untouched facilities
    assert counts["facility.site"]["retired"] == 2
    assert counts["facility.site"]["new"] == 1
    assert "changed" not in counts["facility.site"]  # not a key attribute -- see module docstring

    live_day2 = {r["name"] for r in rows(cat, "facility.site", row_filter="valid_to IS NULL")}
    assert "0086A-ACH Keller - West Point" not in live_day2
    assert "1505 EDGEMONT MEDICAL OFFICES" not in live_day2
    assert "1505 EDGEMONT MEDICAL OFFICES (RENAMED)" in live_day2
    assert len(live_day2) == 5   # 6 day-1 facilities - Keller (dropped) - old Edgemont (renamed) + new Edgemont

    old = rows(cat, "facility.site", row_filter="name = '1505 EDGEMONT MEDICAL OFFICES'")
    assert len(old) == 1
    assert old[0]["valid_from"] == REL and old[0]["valid_to"] == "2026.10"

    new = rows(cat, "facility.site", row_filter="name = '1505 EDGEMONT MEDICAL OFFICES (RENAMED)'")
    assert len(new) == 1
    assert new[0]["valid_from"] == "2026.10" and new[0]["valid_to"] is None

    # A genuinely untouched facility: still exactly one row, still open from day 1.
    untouched = rows(cat, "facility.site",
                     row_filter="name = 'AGUADILLA MEDICAL SERVICES,INC'")
    assert len(untouched) == 1
    assert untouched[0]["valid_from"] == REL and untouched[0]["valid_to"] is None


def other_site():
    return dict(facility_id="OTHER:1", source="OTHER", source_release="V0", kind="hospital",
               name="Other Hospital", address=None, lat=None, lon=None, geo_id="county:99999",
               geo_vintage=2020, attributes_json=None)


def test_fda_mqsa_does_not_retire_another_writer(cat):
    """facility.site is a stacked, multi-writer table (SPEC.md § Facilities):
    the merge scope must be `source`, not unscoped."""
    other = pa.Table.from_pylist([other_site()])
    merge.merge(cat, "facility.site", other, REL, EqualTo("source", "OTHER"))

    fda_mqsa.ingest(cat, REL, MQSA_TXT, retrieved_on="2026-09-18")

    live_other = rows(cat, "facility.site", row_filter="source = 'OTHER' AND valid_to IS NULL")
    assert len(live_other) == 1
    assert live_other[0]["valid_from"] == REL


def test_rerun_is_idempotent(cat):
    fda_mqsa.ingest(cat, REL, MQSA_TXT, retrieved_on="2026-09-18")
    counts = fda_mqsa.ingest(cat, REL, MQSA_TXT, retrieved_on="2026-09-18")
    assert counts["facility.site"]["written"] == 0
    assert counts["facility.site"]["unchanged"] == 6


def test_every_column_is_documented(cat):
    fda_mqsa.ingest(cat, REL, MQSA_TXT, retrieved_on="2026-09-18")
    for identifier in ("raw.fda__mqsa_facilities", "facility.site"):
        table = cat.load_table(identifier)
        assert table.properties.get("comment")
        for f in table.schema().fields:
            assert f.doc, f"{identifier}.{f.name} has no doc"
