"""Tests for config validation honesty (mock default off, prod guards)."""

import pytest
from app.config import Settings, _DEFAULT_JWT_SECRET


def _settings(**kw):
    """Settings with env/.env ignored and safe explicit defaults, overridable per-test."""
    base = dict(
        _env_file=None, mock_mode=False, environment="development",
        jwt_secret_key=_DEFAULT_JWT_SECRET,
        anthropic_api_key="", gemini_api_key="", groq_api_key="", gemini_api_keys="",
    )
    base.update(kw)
    return Settings(**base)


def test_dev_autogenerates_default_jwt_secret():
    s = _settings()
    s.validate_on_startup()
    assert s.jwt_secret_key != _DEFAULT_JWT_SECRET  # auto-generated for the session


def test_dev_without_api_key_does_not_raise():
    # No key in dev → falls back to (badged) mock, not a hard error
    _settings().validate_on_startup()  # must not raise


def test_production_rejects_default_jwt_secret():
    s = _settings(environment="production")
    with pytest.raises(ValueError):
        s.validate_on_startup()


def test_production_requires_an_api_key():
    s = _settings(environment="production",
                  jwt_secret_key="a-strong-non-default-secret-0123456789")
    with pytest.raises(ValueError):  # valid secret but no AI key
        s.validate_on_startup()


def test_production_passes_with_secret_and_key():
    s = _settings(environment="production",
                  jwt_secret_key="a-strong-non-default-secret-0123456789",
                  groq_api_key="gsk_real")
    s.validate_on_startup()  # must not raise
