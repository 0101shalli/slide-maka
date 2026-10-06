import io

from PIL import Image

from app.services import image_fetcher
from app.services.image_fetcher import ImageSpec, _Candidate


def test_query_tokens_drop_stopwords():
    tokens = image_fetcher._query_tokens("The Overview of Solar Panels")
    assert tokens == {"solar", "panels"}


def test_relevance_counts_query_words_in_the_title():
    assert image_fetcher._relevance(["Solar panel array"], {"solar", "panel"}) == 1.0
    assert image_fetcher._relevance(["Mountain lake"], {"solar", "panel"}) == 0.0
    assert image_fetcher._relevance(["solar farm"], {"solar", "panel"}) == 0.5


def test_relevance_outweighs_aspect_ratio():
    target = 16 / 9
    relevant = image_fetcher._candidate_score(1.0, 1000, 1000, target)
    irrelevant = image_fetcher._candidate_score(0.0, 1600, 900, target)
    assert relevant < irrelevant


def test_photo_fetch_picks_the_most_relevant_candidate(monkeypatch):
    monkeypatch.setattr(image_fetcher, "_NETWORK_BLOCKED", False)
    providers = (
        lambda k, r, q: [_Candidate(0.9, "http://weak", None, "irrelevant")],
        lambda k, r, q: [_Candidate(0.1, "http://best", None, "solar panel")],
    )
    monkeypatch.setattr(image_fetcher, "_IMAGE_PROVIDERS", providers)
    downloaded = []
    monkeypatch.setattr(image_fetcher, "_download_candidate", lambda c: downloaded.append(c.url) or b"img")
    assert image_fetcher._try_photo_fetch("solar panel", 1600, 900) == b"img"
    assert downloaded == ["http://best"]


def test_photo_fetch_pools_the_best_of_every_provider(monkeypatch):
    monkeypatch.setattr(image_fetcher, "_NETWORK_BLOCKED", False)
    calls = []

    def provider_a(k, r, q):
        calls.append("a")
        return [_Candidate(0.5, "http://a1", None, "solar"), _Candidate(0.9, "http://a2", None, "x")]

    def provider_b(k, r, q):
        calls.append("b")
        return [_Candidate(0.2, "http://b1", None, "solar panel")]

    monkeypatch.setattr(image_fetcher, "_IMAGE_PROVIDERS", (provider_a, provider_b))
    picked = []
    monkeypatch.setattr(image_fetcher, "_download_candidate", lambda c: picked.append(c.url) or b"img")

    assert image_fetcher._try_photo_fetch("solar panel", 1600, 900) == b"img"
    # Every provider is consulted, but only its best candidate enters the pool.
    assert sorted(calls) == ["a", "b"]
    assert picked == ["http://b1"]


def test_fetch_image_is_memoized(monkeypatch):
    calls = []

    def fake_uncached(*args, **kwargs):
        calls.append(args[0])
        return b"jpeg-bytes"

    monkeypatch.setattr(image_fetcher, "_fetch_image_uncached", fake_uncached)
    image_fetcher._IMAGE_CACHE.clear()

    for _ in range(3):
        assert image_fetcher.fetch_image("quantum computing", points=["a", "b"]) == b"jpeg-bytes"
    assert len(calls) == 1

    # A different point list is a different diagram and must be fetched again.
    image_fetcher.fetch_image("quantum computing", points=["c"])
    assert len(calls) == 2
    image_fetcher._IMAGE_CACHE.clear()


def test_flow_diagram_renders_as_a_valid_image():
    data = image_fetcher.generate_infographic(
        "Request lifecycle",
        diagram={"title": "Request lifecycle", "steps": ["Client", "Server", "Database", "Response"]},
    )
    assert data[:3] == b"\xff\xd8\xff"  # JPEG
    assert Image.open(io.BytesIO(data)).size == (
        image_fetcher.DEFAULT_WIDTH,
        image_fetcher.DEFAULT_HEIGHT,
    )


def test_diagram_spec_never_searches_for_a_photo(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("a diagram must not trigger a photo search")

    monkeypatch.setattr(image_fetcher, "_try_photo_fetch", fail)
    image_fetcher._IMAGE_CACHE.clear()
    data = image_fetcher.fetch_image(
        "Approval flow",
        diagram={"title": "Approval flow", "steps": ["Draft", "Review", "Approve"]},
    )
    image_fetcher._IMAGE_CACHE.clear()
    assert data[:3] == b"\xff\xd8\xff"
    # The diagram is registered as generated under its own key, so the deck
    # knows to give it a full slide.
    diagram = {"title": "Approval flow", "steps": ["Draft", "Review", "Approve"]}
    key = image_fetcher._spec_key(
        "Approval flow", "#0B3C5D", "#1D5C7C", "#3A7CA5", "#F0F8FF", None, diagram
    )
    assert key in image_fetcher._GENERATED_KEYS


def test_prefetch_images_warms_the_cache_in_parallel(monkeypatch):
    calls = []

    def fake_uncached(*args, **kwargs):
        calls.append(args[0])
        return b"jpeg-bytes"

    monkeypatch.setattr(image_fetcher, "_fetch_image_uncached", fake_uncached)
    image_fetcher._IMAGE_CACHE.clear()

    specs = [
        ImageSpec(f"topic {i}", "#0B3C5D", "#1D5C7C", "#3A7CA5", "#F0F8FF", [f"line {i}"])
        for i in range(4)
    ]
    image_fetcher.prefetch_images(specs)
    assert sorted(calls) == [f"topic {i}" for i in range(4)]

    # Rendering then reads from the cache instead of hitting the network again.
    calls.clear()
    for spec in specs:
        assert image_fetcher.fetch_image(
            spec.keyword, spec.primary, spec.secondary, spec.accent, spec.background, points=spec.points
        ) == b"jpeg-bytes"
    assert calls == []
    image_fetcher._IMAGE_CACHE.clear()
