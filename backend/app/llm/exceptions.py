class LLMNotConfiguredError(Exception):
    pass


class LLMTimeoutError(Exception):
    pass


class LLMUnavailableError(Exception):
    pass


class LLMRateLimitError(Exception):
    pass


class LLMProviderError(Exception):
    pass
