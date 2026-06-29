"""Unit tests for prompt_config — PromptConfig and get_prompt_config()."""

import pytest

from app.services.synthesis.prompt_config import MODEL_CONFIGS, PromptConfig, get_prompt_config


class TestGetPromptConfig:
    def test_exact_model_name_match(self):
        config = get_prompt_config("qwen2.5")
        assert config == MODEL_CONFIGS["qwen2.5"]

    def test_prefix_match_with_variant_suffix(self):
        config = get_prompt_config("qwen2.5:7b")
        assert config == MODEL_CONFIGS["qwen2.5"]

    def test_prefix_match_longer_suffix(self):
        config = get_prompt_config("qwen2.5:14b-instruct-q4_K_M")
        assert config == MODEL_CONFIGS["qwen2.5"]

    def test_unknown_model_returns_default(self):
        config = get_prompt_config("unknown-model-xyz")
        assert config == MODEL_CONFIGS["default"]

    def test_empty_model_name_returns_default(self):
        config = get_prompt_config("")
        assert config == MODEL_CONFIGS["default"]

    def test_mistral_match(self):
        config = get_prompt_config("mistral:7b")
        assert config == MODEL_CONFIGS["mistral"]

    def test_returns_prompt_config_type(self):
        config = get_prompt_config("qwen2.5")
        assert isinstance(config, PromptConfig)


class TestModelConfigs:
    def test_all_configs_have_positive_context_window(self):
        for name, config in MODEL_CONFIGS.items():
            assert config.context_window > 0, f"{name}: context_window must be positive"

    def test_all_configs_have_positive_system_budget(self):
        for name, config in MODEL_CONFIGS.items():
            assert config.system_budget > 0, f"{name}: system_budget must be positive"

    def test_all_configs_have_positive_context_budget(self):
        for name, config in MODEL_CONFIGS.items():
            assert config.context_budget > 0, f"{name}: context_budget must be positive"

    def test_all_configs_have_positive_response_budget(self):
        for name, config in MODEL_CONFIGS.items():
            assert config.response_budget > 0, f"{name}: response_budget must be positive"

    def test_all_budgets_fit_within_context_window(self):
        for name, config in MODEL_CONFIGS.items():
            total = config.system_budget + config.context_budget + config.response_budget
            assert total < config.context_window, (
                f"{name}: budgets sum ({total}) must be < context_window ({config.context_window})"
            )

    def test_default_key_exists(self):
        assert "default" in MODEL_CONFIGS

    def test_qwen25_has_large_context(self):
        assert MODEL_CONFIGS["qwen2.5"].context_window >= 32_768

    def test_context_budget_is_largest_section(self):
        for name, config in MODEL_CONFIGS.items():
            assert config.context_budget > config.system_budget, (
                f"{name}: context_budget should exceed system_budget"
            )
            assert config.context_budget > config.response_budget, (
                f"{name}: context_budget should exceed response_budget"
            )
