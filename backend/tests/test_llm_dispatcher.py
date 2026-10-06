from app.services.llm import ProviderConfig, dispatcher


class _FakeProvider:
    def __init__(self, config):
        self.config = config
        self.name = config.name

    def complete(self, prompt, *, temperature=0.3, json_mode=False, timeout=120, model=None):
        if self.config.name == "bad":
            raise RuntimeError("provider down")
        return f"ok:{model}"


def test_dispatcher_tries_providers_in_priority_order(monkeypatch):
    configs = [
        ProviderConfig(name="bad", provider_type="openai", model="m1", priority=1),
        ProviderConfig(name="good", provider_type="openai", model="m2", priority=2),
    ]
    monkeypatch.setattr(dispatcher, "_load_db_configs", lambda: configs)
    monkeypatch.setattr(dispatcher, "build_provider", _FakeProvider)

    assert dispatcher.generate_content("hello", task="slides") == "ok:m2"


def test_dispatcher_raises_when_every_provider_fails(monkeypatch):
    class _AlwaysDown(_FakeProvider):
        def complete(self, prompt, **kwargs):
            raise RuntimeError("down")

    monkeypatch.setattr(dispatcher, "_load_db_configs", lambda: [])
    monkeypatch.setattr(dispatcher, "build_provider", _AlwaysDown)

    try:
        dispatcher.generate_content("hello", task="slides")
    except Exception as exc:
        assert "All LLM providers failed" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected every provider to fail")


def test_per_task_model_override(monkeypatch):
    config = ProviderConfig(
        name="router",
        provider_type="openai",
        model="default-model",
        priority=1,
        extra={"task_models": {"slides": "slides-model"}},
    )
    monkeypatch.setattr(dispatcher, "_load_db_configs", lambda: [config])
    monkeypatch.setattr(dispatcher, "build_provider", _FakeProvider)
    assert dispatcher.generate_content("hi", task="slides") == "ok:slides-model"
    assert dispatcher.generate_content("hi", task="visual_plan") == "ok:default-model"


def test_task_filter_skips_providers_that_do_not_serve(monkeypatch):
    configs = [
        ProviderConfig(
            name="visual-only",
            provider_type="openai",
            model="m",
            priority=1,
            extra={"tasks": ["visual_plan"]},
        ),
    ]
    monkeypatch.setattr(dispatcher, "_load_db_configs", lambda: configs)
    monkeypatch.setattr(dispatcher, "build_provider", _FakeProvider)

    # No DB provider serves "slides", so only the built-in Gemini remains. Stub
    # the built-in so the assertion stays hermetic.
    class _Builtin(_FakeProvider):
        def complete(self, prompt, **kwargs):
            return "builtin"

    monkeypatch.setattr(dispatcher, "build_provider", lambda c: _Builtin(c) if c.is_builtin else _FakeProvider(c))
    assert dispatcher.generate_content("hi", task="slides") == "builtin"
    assert dispatcher.generate_content("hi", task="visual_plan") == "ok:m"
