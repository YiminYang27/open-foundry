"""Factory for creating LLM provider instances."""

from forge.llm.llm_provider import LLMProvider


class LLMProviderFactory:
    """Create LLM provider instances by name."""

    @staticmethod
    def create(provider: str = "claude-cli", *,
               model: str = "sonnet",
               dry_run: bool = False,
               **kwargs) -> LLMProvider:
        if provider == "claude-cli":
            from forge.llm.claude_cli import ClaudeCLI
            return ClaudeCLI(model=model, dry_run=dry_run, **kwargs)
        raise ValueError(f"Unknown LLM provider: {provider}")
