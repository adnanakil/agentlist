"""Tests for curated agent implementations.

These run the agents locally using the SDK test harness, without Docker.
"""

from agentgate_sdk.handler import run_local


def test_echo_agent():
    from agents.echo.agent import EchoAgent

    result = run_local(EchoAgent(), {"message": "hello"})
    assert result["success"]
    assert result["data"]["echoed_message"] == "hello"


def test_text_summarizer():
    from agents.text_summarizer.agent import TextSummarizerAgent

    text = (
        "The quick brown fox jumps over the lazy dog. "
        "This is a test sentence for summarization. "
        "Machine learning models can process text effectively. "
        "Natural language processing has many applications. "
        "Text summarization is one of them."
    )
    result = run_local(TextSummarizerAgent(), {"text": text, "num_sentences": 2})
    assert result["success"]
    assert "summary" in result["data"]
    assert result["data"]["summary_sentence_count"] == 2


def test_json_transformer_pick():
    from agents.json_transformer.agent import JsonTransformerAgent

    result = run_local(
        JsonTransformerAgent(),
        {
            "data": {"name": "Alice", "age": 30, "email": "alice@test.com"},
            "operations": [{"type": "pick", "args": {"keys": ["name", "age"]}}],
        },
    )
    assert result["success"]
    assert result["data"]["result"] == {"name": "Alice", "age": 30}


def test_hash_generator():
    from agents.hash_generator.agent import HashGeneratorAgent

    result = run_local(
        HashGeneratorAgent(),
        {"text": "hello", "algorithm": "sha256"},
    )
    assert result["success"]
    assert result["data"]["algorithm"] == "sha256"
    assert len(result["data"]["hash"]) == 64


def test_base64_encoder_encode():
    from agents.base64_encoder.agent import Base64EncoderAgent

    result = run_local(
        Base64EncoderAgent(),
        {"text": "hello world", "operation": "encode"},
    )
    assert result["success"]
    assert result["data"]["result"] == "aGVsbG8gd29ybGQ="


def test_base64_encoder_decode():
    from agents.base64_encoder.agent import Base64EncoderAgent

    result = run_local(
        Base64EncoderAgent(),
        {"text": "aGVsbG8gd29ybGQ=", "operation": "decode"},
    )
    assert result["success"]
    assert result["data"]["result"] == "hello world"


def test_word_counter():
    from agents.word_counter.agent import WordCounterAgent

    result = run_local(
        WordCounterAgent(),
        {"text": "Hello world. This is a test."},
    )
    assert result["success"]
    assert result["data"]["words"] == 6
    assert result["data"]["sentences"] == 2


def test_regex_tester():
    from agents.regex_tester.agent import RegexTesterAgent

    result = run_local(
        RegexTesterAgent(),
        {"pattern": r"\d+", "text": "abc 123 def 456"},
    )
    assert result["success"]
    assert result["data"]["match_count"] == 2


def test_email_validator_valid():
    from agents.email_validator.agent import EmailValidatorAgent

    result = run_local(
        EmailValidatorAgent(),
        {"email": "test@example.com"},
    )
    assert result["success"]
    assert result["data"]["valid"] is True


def test_email_validator_invalid():
    from agents.email_validator.agent import EmailValidatorAgent

    result = run_local(
        EmailValidatorAgent(),
        {"email": "not-an-email"},
    )
    assert result["success"]
    assert result["data"]["valid"] is False


def test_ip_lookup_ipv4():
    from agents.ip_lookup.agent import IpLookupAgent

    result = run_local(IpLookupAgent(), {"ip": "192.168.1.1"})
    assert result["success"]
    assert result["data"]["version"] == 4
    assert result["data"]["is_private"] is True


def test_ip_lookup_cidr():
    from agents.ip_lookup.agent import IpLookupAgent

    result = run_local(IpLookupAgent(), {"ip": "10.0.0.0/24"})
    assert result["success"]
    assert result["data"]["num_addresses"] == 256
