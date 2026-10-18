"""Domain and safety errors for the Tech4ce backend (Developer 1)."""


class Tech4ceError(Exception):
    """Base class for all backend errors."""


class ConfigError(Tech4ceError):
    """A required setting is missing or invalid."""


class SafetyError(Tech4ceError):
    """A database-protection rule would be violated. Always fatal."""


class OriginalDatabaseTampered(SafetyError):
    """The original APS-01.db fingerprint does not match the recorded value."""


class NotAWorkingCopy(SafetyError):
    """The target database is not a marked working copy."""


class RefusedOriginalTarget(SafetyError):
    """An operation tried to target the original database file."""


class MigrationError(Tech4ceError):
    """A schema migration could not be applied."""


class MoneyError(Tech4ceError, ValueError):
    """A monetary value is malformed or out of range."""
