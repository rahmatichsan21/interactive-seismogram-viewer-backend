from app.processing.operations.trim import apply_trim
from app.processing.operations.filter import apply_filter

OPERATION_REGISTRY = {
    "trim": apply_trim,
    "filter": apply_filter,
}