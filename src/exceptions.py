"""Project-specific exceptions."""


class BotError(Exception):
    """Base class for recoverable bot errors."""


class ConfigurationError(BotError):
    """Raised when local configuration or device state is invalid."""


class MissingAssetError(BotError):
    """Raised when a required template asset is missing."""


class SceneError(BotError):
    """Raised when scene detection cannot confirm a needed screen."""


class NavigationError(BotError):
    """Raised when the bot cannot safely navigate to the target screen."""


class TaskFailedError(BotError):
    """Raised when a task reaches a known failed state."""


class TaskSkippedError(BotError):
    """Raised when a task safely stops and should let later tasks continue."""
