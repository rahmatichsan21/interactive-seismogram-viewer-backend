from app.processing.operations.trim import apply_trim
from app.processing.operations.filter import apply_filter
from app.processing.operations.instrument_correction import (
    apply_instrument_correction,
)

OPERATION_REGISTRY = {
    "trim": apply_trim,
    "filter": apply_filter,
    "instrument_correction": apply_instrument_correction,
}