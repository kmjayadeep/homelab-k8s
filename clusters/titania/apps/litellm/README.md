# LiteLLM model names

Use `qwen-intel` in LiteLLM clients that should follow the currently selected Intel Qwen variant without changing client configuration for each experiment. The existing `qwen3.6-35b-a3b-intel` name is retained for compatibility. Both names currently route to the same `intel-llama` backend and served model; they do not run two copies of the model.

When changing variants, update the `qwen-intel` entry in `helm-release.yaml` to match the backend URL and its exact served-model name, and adjust token limits to the deployed context window. A new variant needs an independently configured and running backend before the alias can select it. Do not assume the versioned name remains an accurate pin if the shared backend is repointed; keep or remove that name only after checking its clients and obtaining approval for any removal. Changes here are GitOps desired state, not proof of a live rollout.
