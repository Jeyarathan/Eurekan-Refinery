from enum import Enum


class OperatingMode(str, Enum):
    SIMULATE = "simulate"
    OPTIMIZE = "optimize"
    HYBRID = "hybrid"


class UnitType(str, Enum):
    CDU = "cdu"
    FCC = "fcc"
    REFORMER = "reformer"
    HYDROTREATER = "hydrotreater"
    HYDROCRACKER = "hydrocracker"
    COKER = "coker"
    ALKYLATION = "alkylation"
    ISOMERIZATION = "isomerization"
    BLENDER = "blender"


class TankType(str, Enum):
    CRUDE = "crude"
    PRODUCT = "product"
    INTERMEDIATE = "intermediate"


class BlendMethod(str, Enum):
    LINEAR_VOLUME = "linear_volume"
    LINEAR_WEIGHT = "linear_weight"
    POWER_LAW = "power_law"
    INDEX = "index"


class StreamDisposition(str, Enum):
    BLEND = "blend"
    SELL = "sell"
    FUEL_OIL = "fuel_oil"
    INTERNAL = "internal"
    FCC_FEED = "fcc_feed"


class DataSource(str, Enum):
    """Tracks WHERE every data value came from. Shown in UI."""

    DEFAULT = "default"
    TEMPLATE = "template"
    IMPORTED = "imported"
    USER_ENTERED = "user"
    AI_EXTRACTED = "ai"
    CALIBRATED = "calibrated"
    CALCULATED = "calculated"
    MARKET_DATA = "market"
