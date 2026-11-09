from hermes_legal.providers import PROVIDERS, allowed

def by(name):
    return next(p for p in PROVIDERS if p.name.startswith(name))

def test_local_always_allowed():
    assert allowed(by("Local (llama"), "LOCAL_ONLY")

def test_consumer_chat_blocked_even_at_standard():
    assert not allowed(by("Consumer chat"), "STANDARD")

def test_standard_provider_refused_for_local_only_matter():
    assert not allowed(by("OpenAI API (paid)"), "LOCAL_ONLY")

def test_zdr_allowed_at_zdr_ceiling():
    assert allowed(by("AWS Bedrock"), "ZERO_RETENTION")

def test_no_provider_trains_except_blocked():
    assert all((not p.trains_on_data) or p.tier == "BLOCKED" for p in PROVIDERS)
