class GrantBotError(Exception):
    """Base exception for GrantBot Pro."""


class ConfigurationError(GrantBotError):
    """Configuration is invalid."""


class DatabaseError(GrantBotError):
    """Database operation failed."""


class ValidationError(GrantBotError):
    """Input or stored data failed validation."""


class MigrationError(GrantBotError):
    """Database migration failed."""


class ExternalServiceError(GrantBotError):
    """External API/service failed."""


class FundingSourceError(GrantBotError):
    """Funding-source operation failed."""


class EligibilityError(GrantBotError):
    """Eligibility analysis failed."""


class MatchingError(GrantBotError):
    """Funding match analysis failed."""


class UnsafeClaimError(GrantBotError):
    """An unsupported application claim was detected."""


class NofoParsingError(GrantBotError):
    """NOFO/document parsing failed."""
