# services/synthesis

Turns retrieved chunks into a grounded answer.

- `synthesizer.py`: `ResponseSynthesizer.synthesize()` runs ContextBuilder, then LlamaIndex (`SYNTHESIS_MODE`: compact, refine or tree_summarize), and returns a `SynthesisResult`.
- `context_builder.py`: formats chunks in rank order as a numbered context, capped to a token budget.
- `prompt_config.py`: per-model token budgets (context window, system, context, response). Keys match as a model-name prefix (`qwen2.5` matches `qwen2.5:7b`) with a `default` fallback. Add new models to `MODEL_CONFIGS`.
- `prompts.py`: prompt templates; `build_rag_user_message()` is used by the streaming path.
- `token_counter.py`: character-based token estimate and truncation.
- `models.py`: `SynthesisResult`.
