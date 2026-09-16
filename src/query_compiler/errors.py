"""Public, named failures; invalid requests never silently lose features."""


class QueryCompilerError(ValueError):
    """Base class for expected compilation failures."""


class InvalidContractError(QueryCompilerError):
    pass


class InvalidSemanticModelError(QueryCompilerError):
    pass


class UnknownMetricError(QueryCompilerError):
    pass


class UnknownDimensionError(QueryCompilerError):
    pass


class InvalidFilterError(QueryCompilerError):
    pass


class NoJoinPathError(QueryCompilerError):
    pass


class AmbiguousJoinPathError(QueryCompilerError):
    pass


class UnsupportedRelationshipError(QueryCompilerError):
    pass


class UnsupportedFeatureError(QueryCompilerError):
    pass


class UnsupportedDialectError(QueryCompilerError):
    pass
