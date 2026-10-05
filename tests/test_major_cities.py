import pytest

from pws.data.major_cities import _haversine_miles, major_cities_near

STATIONS = {
    "Houston, TX": (29.76, -95.37),
    "Levittown, PA": (40.155, -74.829),
    "Chicago, IL": (41.88, -87.63),
    "London, UK": (51.507, -0.128),
}


@pytest.mark.parametrize("name", list(STATIONS))
def test_picks_are_spread_and_skip_home(name):
    lat, lon = STATIONS[name]
    picks = major_cities_near(lat, lon, max_results=6, home_name=name)
    assert len(picks) == 6
    home = name.split(",")[0].lower()
    for p in picks:
        assert p["name"].lower() != home
        assert p["distance"] > 20
        if p["distance"] <= 40:
            assert p["population"] >= 500_000      # only distinct big cities that close
    for i, a in enumerate(picks):
        for b in picks[i + 1:]:
            assert _haversine_miles(a["lat"], a["lon"], b["lat"], b["lon"]) >= 25


def test_levittown_not_clustered_on_new_york():
    lat, lon = STATIONS["Levittown, PA"]
    names = {p["name"] for p in major_cities_near(lat, lon, home_name="Levittown, PA")}
    assert not names & {"Newark", "Jersey City", "Yonkers", "Corona", "Brooklyn", "Queens"}


def test_remote_location_still_gets_cities():
    assert major_cities_near(35.0, -50.0, max_results=3)   # mid-Atlantic
