"""Usage patterns (§4.2 step 3) on synthetic shapes and on optev.sample. The sample covers two
weekdays, so its profiles have 24 `wd` bins and filled `we` bins. The live test runs only when
DATABASE_URL is in the environment and is rolled back."""

import os
from datetime import datetime, timedelta

import pytest

from optev import sample
from optev.analysis import indicators as I
from optev.analysis import patterns as P

START = datetime(2026, 10, 1, tzinfo=I.SGT)
S = sample.load()
READINGS = sample.connector_readings()


def _occupancy(start: datetime, hours: int) -> dict[str, dict[str, float]]:
    return I.compute_occupancy_by_bin(S.sites, S.near, S.connectors, READINGS,
                                      start, start + timedelta(hours=hours))


OCCUPANCY = _occupancy(START, 48)


def _shape(peak: int, weekend: float = 1.0, level: float = 0.6) -> dict[str, float]:
    """A profile peaking at `peak` o'clock; `weekend` scales the we half."""
    out = {}
    for b in P.BINS:
        h = int(b[3:])
        v = level * max(0.0, 1 - min(abs(h - peak), 24 - abs(h - peak)) / 6)
        out[b] = v * (weekend if b.startswith("we") else 1.0)
    return out


SYNTH = {
    **{f"eve-{i}": _shape(19 + i, level=0.5 + i / 10) for i in range(4)},
    **{f"day-{i}": _shape(12 + i, level=0.3 + i / 10) for i in range(4)},
    **{f"wkd-{i}": _shape(7 + i, weekend=0.2, level=0.4 + i / 10) for i in range(4)},
}


def test_profile_fills_gaps_and_normalises():
    bins = {"wd-00": 0.2, "wd-01": 0.6, **{f"wd-{h:02d}": 0.4 for h in range(2, 24)}}
    p = P._profile(bins)
    assert p is not None and p.min() == 0 and p.max() == 1
    assert p[24:].tolist() == pytest.approx([p[:24].mean()] * 24)  # we half from wd mean


def test_profile_needs_min_coverage_of_bins_and_flat_is_zero():
    assert P._profile({f"wd-{h:02d}": 0.5 for h in range(23)}) is None
    assert not P._profile({b: 0.3 for b in P.BINS}).any()


def test_synthetic_shapes_are_recovered_and_labelled():
    got = P.find_patterns(SYNTH)
    assert set(got) == set(SYNTH)
    for group in ("eve", "day", "wkd"):
        assert len({got[s] for s in SYNTH if s.startswith(group)}) == 1
    assert len(set(got.values())) == 3
    labels = P.label_patterns(SYNTH, got)
    assert labels[got["eve-0"]] == "evening peak"
    assert labels[got["day-0"]] == "daytime peak"
    assert labels[got["wkd-0"]] == "morning peak, busier on weekdays"
    assert P.pattern_silhouette(SYNTH, got) > 0.5


def test_clusters_are_numbered_by_first_site_and_deterministic():
    got = P.find_patterns(SYNTH)
    assert got == P.find_patterns(SYNTH)
    assert got[sorted(SYNTH)[0]] == 0
    assert set(got.values()) == set(range(len(set(got.values()))))


def test_too_few_sites_raises_and_empty_is_empty():
    assert P.find_patterns({}) == {}
    with pytest.raises(ValueError):
        P.find_patterns({f"s{i}": _shape(i) for i in range(3)})


def test_flat_cluster_is_labelled_flat_and_duplicates_are_told_apart():
    occ = {f"z{i}": {b: 0.1 * i for b in P.BINS} for i in range(3)}
    assert P._label(P._profile(occ["z1"])) == "flat"  # type: ignore[arg-type]
    eve = {s: (0 if s < "eve-2" else 1) for s in SYNTH if s.startswith("eve")}
    assert P.label_patterns(SYNTH, eve) == {0: "evening peak (cluster 0)",
                                            1: "evening peak (cluster 1)"}


def test_sample_every_served_site_gets_a_cluster_within_k_range():
    got = P.find_patterns(OCCUPANCY)
    assert set(got) == set(OCCUPANCY)
    assert 3 <= len(set(got.values())) <= 6
    labels = P.label_patterns(OCCUPANCY, got)
    assert set(labels) == set(got.values()) and all(labels.values())


def test_sample_splits_by_saturation_not_by_kind():
    """Spec 014 finding 5: with no weekend bins, k = 3 sets apart the two saturated sites
    (S-03, S-04, flat near 1) and the idle one (S-14), and leaves the daytime public sites
    (S-13, S-23) with the evening HDB ones."""
    got = P.find_patterns(OCCUPANCY)
    labels = P.label_patterns(OCCUPANCY, got)
    assert got["SYN-S-03"] == got["SYN-S-04"]
    assert labels[got["SYN-S-04"]] == "overnight peak"
    assert len({got[s] for s in OCCUPANCY} - {got["SYN-S-04"], got["SYN-S-14"]}) == 1


def test_sample_silhouette_is_recorded_not_targeted():
    """§6 asks ≥ 0.5; 11 sites with two generated shapes give about 0.15 (spec 014)."""
    got = P.find_patterns(OCCUPANCY)
    assert 0.0 < P.pattern_silhouette(OCCUPANCY, got) < 0.5


def test_holdout_agreement_on_held_back_day():
    """Fit on day 1, assign day 2 (spec 014 measured 100% at k = 3)."""
    share = P.holdout_agreement(_occupancy(START, 24), _occupancy(START + timedelta(days=1), 24))
    assert share >= 0.8


def test_holdout_agreement_is_one_on_the_same_data_and_needs_common_sites():
    assert P.holdout_agreement(SYNTH, SYNTH) == 1.0
    with pytest.raises(ValueError):
        P.holdout_agreement(SYNTH, {"other": _shape(3)})


live = pytest.mark.skipif(not os.environ.get("DATABASE_URL"),
                          reason="DATABASE_URL not in environment")


@live
def test_write_patterns_upserts():
    import psycopg

    got = P.find_patterns(OCCUPANCY)
    labels = P.label_patterns(OCCUPANCY, got)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO candidate_site (site_id, kind, geom) VALUES"
                    " (%s, %s, ST_SetSRID(ST_MakePoint(103.9, 1.35), 4326))",
                    [(s.site_id, s.kind.value) for s in S.sites])
            for _ in range(2):
                assert P.write_patterns(conn, got, labels) == len(got)
            n = conn.execute("SELECT count(*) FROM site_pattern"
                             " WHERE site_id LIKE 'SYN-%%' AND label IS NOT NULL").fetchone()
            assert n == (len(got),)
        finally:
            conn.rollback()
