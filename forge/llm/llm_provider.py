"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Base class for all LLM providers.

    Subclasses must implement complete() and stream().
    If a provider does not support streaming, stream() returns None.
    """

    @property
    @abstractmethod
    def model(self) -> str:
        """Return the configured model name."""
        raise NotImplementedError

    @property
    @abstractmethod
    def dry_run(self) -> bool:
        """Return whether this provider is in dry-run mode."""
        raise NotImplementedError

    @abstractmethod
    def complete(self, prompt: str, *,
                 label: str = "",
                 timeout: int = 600,
                 max_retries: int = 3) -> str:
        """Send prompt, return response text. Empty string on failure."""
        raise NotImplementedError

    @abstractmethod
    def stream(self, prompt: str, *,
               label: str = "",
               timeout: int = 1800,
               max_retries: int = 3) -> int | None:
        """Send prompt with streaming output to stdout.
        Return exit code (0 = success), or None if streaming is unsupported.
        """
        raise NotImplementedError
