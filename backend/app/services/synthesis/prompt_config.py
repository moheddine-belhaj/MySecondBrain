"""Per-model token budget configuration.

Each model has a different context window. We pre-allocate the total
token budget across three named sections:

  system   — system prompt and instructions (fixed overhead, small)
  context  — retrieved note excerpts (largest share, variable)
  response — headroom reserved for the model's generated answer

The sum of all three sections must be comfortably below context_window
(leave ~10 % headroom for template overhead and adapter message formatting).

Adding a new model
------------------
Add an entry to MODEL_CONFIGS. Keys are matched as a prefix of the
model name, so "qwen2.5" matches "qwen2.5:7b", "qwen2.5:14b", etc.
The "default" key is the fallback for any model not explicitly listed.

Usage
-----
    from app.services.synthesis.prompt_config import get_prompt_config

    config = get_prompt_config(settings.ollama_chat_model)
    builder = ContextBuilder(max_context_tokens=config.context_budget)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptConfig:
    """Token budget allocation for one model."""

    context_window: int     # total tokens the model accepts
    system_budget: int      # tokens reserved for system instructions
    context_budget: int     # tokens reserved for retrieved note excerpts
    response_budget: int    # tokens reserved for the generated answer


MODEL_CONFIGS: dict[str, PromptConfig] = {
    # 32 k context — generous allocation across all sections
    "qwen2.5": PromptConfig(
        context_window=32_768,
        system_budget=500,
        context_budget=6_000,
        response_budget=2_048,
    ),
    # llama3 family: 8 k context
    "llama3": PromptConfig(
        context_window=8_192,
        system_budget=400,
        context_budget=3_000,
        response_budget=1_024,
    ),
    # mistral: 8 k context
    "mistral": PromptConfig(
        context_window=8_192,
        system_budget=400,
        context_budget=3_000,
        response_budget=1_024,
    ),
    # phi3: 4 k context — conservative
    "phi3": PromptConfig(
        context_window=4_096,
        system_budget=300,
        context_budget=1_500,
        response_budget=512,
    ),
    # gemma: 8 k context
    "gemma": PromptConfig(
        context_window=8_192,
        system_budget=400,
        context_budget=3_000,
        response_budget=1_024,
    ),
    # deepseek: 32 k context
    "deepseek": PromptConfig(
        context_window=32_768,
        system_budget=500,
        context_budget=6_000,
        response_budget=2_048,
    ),
    # Safe fallback for any unlisted model
    "default": PromptConfig(
        context_window=4_096,
        system_budget=300,
        context_budget=1_500,
        response_budget=512,
    ),
}


def get_prompt_config(model_name: str) -> PromptConfig:
    """Return the PromptConfig for *model_name*, falling back to 'default'.

    Matching is prefix-based: 'qwen2.5:7b' → key 'qwen2.5'.
    """
    for key, config in MODEL_CONFIGS.items():
        if key != "default" and model_name.startswith(key):
            return config
    return MODEL_CONFIGS["default"]
