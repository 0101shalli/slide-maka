from app.core.config import settings
from app.services import visual_planner


def test_parse_plan_keeps_a_flow_with_its_steps():
    raw = (
        '{"slides":[{"index":1,"kind":"flow","query":"api request lifecycle",'
        '"caption":"Request path","title":"Request Flow",'
        '"steps":["Client","Server","Database"]}]}'
    )
    plan = visual_planner._parse_visual_plan(raw, 3)
    assert plan[1]["kind"] == "flow"
    assert plan[1]["steps"] == ["Client", "Server", "Database"]
    assert plan[1]["flow_title"] == "Request Flow"
    assert plan[1]["query"] == "api request lifecycle"


def test_parse_plan_drops_unknown_kinds_and_too_short_flows():
    raw = (
        '{"slides":['
        '{"index":0,"kind":"none"},'
        '{"index":1,"kind":"flow","steps":["only one"]},'
        '{"index":2,"kind":"hologram","query":"x"},'
        '{"index":9,"kind":"photo","query":"out of range"}'
        "]}"
    )
    assert visual_planner._parse_visual_plan(raw, 3) == {}


def test_parse_plan_keeps_concept_diagram_points():
    raw = '{"slides":[{"index":0,"kind":"diagram","query":"c4 model","points":["Context","Container"]}]}'
    plan = visual_planner._parse_visual_plan(raw, 1)
    assert plan[0]["kind"] == "diagram"
    assert plan[0]["points"] == ["Context", "Container"]


def test_plan_visuals_is_disabled_by_default_in_tests(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_visual_planner", False)
    assert visual_planner.plan_visuals([{"title": "x", "bullets": ["a"]}]) == {}


def test_plan_visuals_caches_and_degrades_on_error(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_visual_planner", True)
    visual_planner.invalidate_cache()
    calls = []

    def fake_generate(*args, **kwargs):
        calls.append(1)
        return '{"slides":[{"index":0,"kind":"photo","query":"solar panels"}]}'

    monkeypatch.setattr(visual_planner, "generate_content", fake_generate)
    slides = [{"title": "Solar", "bullets": ["Rooftop panels"]}]
    first = visual_planner.plan_visuals(slides)
    second = visual_planner.plan_visuals(slides)
    assert first == second == {0: {"kind": "photo", "query": "solar panels", "caption": ""}}
    assert len(calls) == 1

    def boom(*args, **kwargs):
        raise RuntimeError("no provider")

    monkeypatch.setattr(visual_planner, "generate_content", boom)
    visual_planner.invalidate_cache()
    assert visual_planner.plan_visuals(slides) == {}
