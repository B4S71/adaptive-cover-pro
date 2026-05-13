"""Constants for integration_blueprint."""

import logging

DOMAIN = "adaptive_cover_pro"
LOGGER = logging.getLogger(__package__)
_LOGGER = logging.getLogger(__name__)

ATTR_POSITION = "position"
ATTR_TILT_POSITION = "tilt_position"

CONF_AZIMUTH = "set_azimuth"
CONF_BLUEPRINT = "blueprint"
CONF_HEIGHT_WIN = "window_height"
CONF_DISTANCE = "distance_shaded_area"
CONF_WINDOW_DEPTH = "window_depth"
CONF_SILL_HEIGHT = "sill_height"
CONF_DEFAULT_HEIGHT = "default_percentage"
CONF_FOV_LEFT = "fov_left"
CONF_FOV_RIGHT = "fov_right"
CONF_ENTITIES = "group"
CONF_HEIGHT_AWNING = "height_awning"
CONF_LENGTH_AWNING = "length_awning"
CONF_AWNING_ANGLE = "angle"
CONF_SENSOR_TYPE = "sensor_type"
CONF_INVERSE_STATE = "inverse_state"
CONF_INVERSE_TILT = "inverse_tilt"
CONF_SUNSET_POS = "sunset_position"
CONF_SUNSET_OFFSET = "sunset_offset"
CONF_TILT_DEPTH = "slat_depth"
CONF_TILT_DISTANCE = "slat_distance"
CONF_TILT_MODE = "tilt_mode"
CONF_SUNRISE_OFFSET = "sunrise_offset"
CONF_TEMP_ENTITY = "temp_entity"
CONF_PRESENCE_ENTITY = "presence_entity"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_TEMP_LOW = "temp_low"
CONF_TEMP_HIGH = "temp_high"
CONF_MODE = "mode"
CONF_CLIMATE_MODE = "climate_mode"
CONF_WEATHER_STATE = "weather_state"
CONF_MAX_POSITION = "max_position"
CONF_MIN_POSITION = "min_position"
CONF_ENABLE_MAX_POSITION = "enable_max_position"
CONF_ENABLE_MIN_POSITION = "enable_min_position"
CONF_ENABLE_SUN_TRACKING = "enable_sun_tracking"
CONF_OUTSIDETEMP_ENTITY = "outside_temp"
CONF_FORCE_OVERRIDE_SENSORS = "force_override_sensors"
CONF_FORCE_OVERRIDE_POSITION = "force_override_position"
CONF_FORCE_OVERRIDE_MIN_MODE = "force_override_min_mode"

# --- Custom position slots ---------------------------------------------------
# Each slot exposes the same five config keys (sensor / position / priority /
# min_mode / use_my). The wire-format names ("custom_position_sensor_3" etc.)
# are stored in user config_entry.options, so they MUST stay stable; the helper
# below derives them programmatically and the per-slot CONF_* aliases below are
# kept for callers that prefer the named constant.
CUSTOM_POSITION_SLOT_NUMBERS: tuple[int, ...] = (1, 2, 3, 4)


def _custom_position_slot_keys(n: int) -> dict[str, str]:
    """Return the five wire-format option keys for slot *n*."""
    return {
        "sensor": f"custom_position_sensor_{n}",
        "position": f"custom_position_{n}",
        "priority": f"custom_position_priority_{n}",
        "min_mode": f"custom_position_min_mode_{n}",
        "use_my": f"custom_position_use_my_{n}",
    }


CUSTOM_POSITION_SLOTS: dict[int, dict[str, str]] = {
    n: _custom_position_slot_keys(n) for n in CUSTOM_POSITION_SLOT_NUMBERS
}

CONF_CUSTOM_POSITION_SENSOR_1 = CUSTOM_POSITION_SLOTS[1]["sensor"]
CONF_CUSTOM_POSITION_1 = CUSTOM_POSITION_SLOTS[1]["position"]
CONF_CUSTOM_POSITION_PRIORITY_1 = CUSTOM_POSITION_SLOTS[1]["priority"]
CONF_CUSTOM_POSITION_MIN_MODE_1 = CUSTOM_POSITION_SLOTS[1]["min_mode"]
CONF_CUSTOM_POSITION_USE_MY_1 = CUSTOM_POSITION_SLOTS[1]["use_my"]
CONF_CUSTOM_POSITION_SENSOR_2 = CUSTOM_POSITION_SLOTS[2]["sensor"]
CONF_CUSTOM_POSITION_2 = CUSTOM_POSITION_SLOTS[2]["position"]
CONF_CUSTOM_POSITION_PRIORITY_2 = CUSTOM_POSITION_SLOTS[2]["priority"]
CONF_CUSTOM_POSITION_MIN_MODE_2 = CUSTOM_POSITION_SLOTS[2]["min_mode"]
CONF_CUSTOM_POSITION_USE_MY_2 = CUSTOM_POSITION_SLOTS[2]["use_my"]
CONF_CUSTOM_POSITION_SENSOR_3 = CUSTOM_POSITION_SLOTS[3]["sensor"]
CONF_CUSTOM_POSITION_3 = CUSTOM_POSITION_SLOTS[3]["position"]
CONF_CUSTOM_POSITION_PRIORITY_3 = CUSTOM_POSITION_SLOTS[3]["priority"]
CONF_CUSTOM_POSITION_MIN_MODE_3 = CUSTOM_POSITION_SLOTS[3]["min_mode"]
CONF_CUSTOM_POSITION_USE_MY_3 = CUSTOM_POSITION_SLOTS[3]["use_my"]
CONF_CUSTOM_POSITION_SENSOR_4 = CUSTOM_POSITION_SLOTS[4]["sensor"]
CONF_CUSTOM_POSITION_4 = CUSTOM_POSITION_SLOTS[4]["position"]
CONF_CUSTOM_POSITION_PRIORITY_4 = CUSTOM_POSITION_SLOTS[4]["priority"]
CONF_CUSTOM_POSITION_MIN_MODE_4 = CUSTOM_POSITION_SLOTS[4]["min_mode"]
CONF_CUSTOM_POSITION_USE_MY_4 = CUSTOM_POSITION_SLOTS[4]["use_my"]
CONF_MY_POSITION_VALUE = "my_position_value"
CONF_SUNSET_USE_MY = "sunset_use_my"
DEFAULT_CUSTOM_POSITION_PRIORITY = 77
CONF_MOTION_SENSORS = "motion_sensors"
CONF_MOTION_TIMEOUT = "motion_timeout"
CONF_ENABLE_BLIND_SPOT = "blind_spot"
CONF_BLIND_SPOT_RIGHT = "blind_spot_right"
CONF_BLIND_SPOT_LEFT = "blind_spot_left"
CONF_BLIND_SPOT_ELEVATION = "blind_spot_elevation"
CONF_MIN_ELEVATION = "min_elevation"
CONF_MAX_ELEVATION = "max_elevation"
CONF_TRANSPARENT_BLIND = "transparent_blind"
CONF_WINTER_CLOSE_INSULATION = "winter_close_insulation"
CONF_CLOUD_SUPPRESSION = "cloud_suppression"
CONF_CLOUDY_POSITION = "cloudy_position"
CONF_INTERP_START = "interp_start"
CONF_INTERP_END = "interp_end"
CONF_INTERP_LIST = "interp_list"
CONF_INTERP_LIST_NEW = "interp_list_new"
CONF_INTERP = "interp"
CONF_LUX_ENTITY = "lux_entity"
CONF_LUX_THRESHOLD = "lux_threshold"
CONF_IRRADIANCE_ENTITY = "irradiance_entity"
CONF_IRRADIANCE_THRESHOLD = "irradiance_threshold"
CONF_CLOUD_COVERAGE_ENTITY = "cloud_coverage_entity"
CONF_CLOUD_COVERAGE_THRESHOLD = "cloud_coverage_threshold"
CONF_IS_SUNNY_SENSOR = "is_sunny_sensor"
CONF_OUTSIDE_THRESHOLD = "outside_threshold"
CONF_DEVICE_ID = "linked_device_id"
CONF_ENABLE_GLARE_ZONES = "enable_glare_zones"
CONF_WINDOW_WIDTH = "window_width"

# Weather override
CONF_WEATHER_WIND_SPEED_SENSOR = "weather_wind_speed_sensor"
CONF_WEATHER_WIND_DIRECTION_SENSOR = "weather_wind_direction_sensor"
CONF_WEATHER_WIND_SPEED_THRESHOLD = "weather_wind_speed_threshold"
CONF_WEATHER_WIND_DIRECTION_TOLERANCE = "weather_wind_direction_tolerance"
CONF_WEATHER_RAIN_SENSOR = "weather_rain_sensor"
CONF_WEATHER_RAIN_THRESHOLD = "weather_rain_threshold"
CONF_WEATHER_IS_RAINING_SENSOR = "weather_is_raining_sensor"
CONF_WEATHER_IS_WINDY_SENSOR = "weather_is_windy_sensor"
CONF_WEATHER_SEVERE_SENSORS = "weather_severe_sensors"
CONF_WEATHER_OVERRIDE_POSITION = "weather_override_position"
CONF_WEATHER_OVERRIDE_MIN_MODE = "weather_override_min_mode"
CONF_WEATHER_TIMEOUT = "weather_timeout"
CONF_WEATHER_BYPASS_AUTO_CONTROL = "weather_bypass_auto_control"


CONF_DELTA_POSITION = "delta_position"
CONF_DELTA_TIME = "delta_time"
CONF_START_TIME = "start_time"
CONF_START_ENTITY = "start_entity"
CONF_END_TIME = "end_time"
CONF_END_ENTITY = "end_entity"
CONF_RETURN_SUNSET = "return_sunset"
CONF_MANUAL_OVERRIDE_DURATION = "manual_override_duration"
CONF_MANUAL_OVERRIDE_RESET = "manual_override_reset"
CONF_MANUAL_THRESHOLD = "manual_threshold"
CONF_MANUAL_IGNORE_INTERMEDIATE = "manual_ignore_intermediate"
CONF_OPEN_CLOSE_THRESHOLD = "open_close_threshold"

# Debug & Diagnostics
CONF_DEBUG_MODE = "debug_mode"
CONF_DEBUG_CATEGORIES = "debug_categories"
CONF_DEBUG_EVENT_BUFFER_SIZE = "debug_event_buffer_size"
CONF_DRY_RUN = "dry_run"

DEBUG_CATEGORY_MANUAL_OVERRIDE = "manual_override"
DEBUG_CATEGORY_RECONCILIATION = "reconciliation"
DEBUG_CATEGORY_PIPELINE = "pipeline"
DEBUG_CATEGORY_MOTION = "motion"
DEBUG_CATEGORIES_ALL = [
    DEBUG_CATEGORY_MANUAL_OVERRIDE,
    DEBUG_CATEGORY_RECONCILIATION,
    DEBUG_CATEGORY_PIPELINE,
    DEBUG_CATEGORY_MOTION,
]

DEFAULT_DEBUG_EVENT_BUFFER_SIZE = 250
MAX_DEBUG_EVENT_BUFFER_SIZE = 1000

# Position verification constants (fixed values, not configurable)
POSITION_CHECK_INTERVAL_MINUTES = 1  # Fixed interval for position verification
POSITION_TOLERANCE_PERCENT = 3  # Fixed tolerance for position matching
MAX_POSITION_RETRIES = 3  # Maximum retry attempts before giving up

# Dual-axis venetian sequencing (Issue #33). After a position command lands,
# the service polls current_position every poll-interval seconds, declares
# the cover "settled" when the position matches the target within the standard
# tolerance OR has not changed for three consecutive samples, and proceeds to
# the tilt command.  Hard cap at the timeout so a stuck cover does not block
# the rest of the update cycle indefinitely.
VENETIAN_POSITION_SETTLE_POLL_SECONDS = 0.5
VENETIAN_POSITION_SETTLE_TIMEOUT_SECONDS = 60.0
VENETIAN_POSITION_SETTLE_NO_CHANGE_SAMPLES = 3
# Suppress tilt-axis manual override detection for this many seconds after a
# venetian position command. Real motors back-rotate the slats while moving
# vertically, and that drift would otherwise read as a user touch.
VENETIAN_TILT_SUPPRESSION_SECONDS = 90.0
# After set_cover_tilt_position returns, real motors keep back-driving the
# vertical axis briefly. Wait this many seconds before reading current_position
# for the post-tilt rebase so the rebase captures the actual settled position
# rather than the pre-back-drive snapshot.
VENETIAN_POST_TILT_REBASE_DELAY_SECONDS = 1.5
# Drift tolerance for tilt verification: if actual tilt differs from the sent
# target by more than this many percent after the post-tilt delay, the recorded
# target is cleared so the next update_tilt_only cycle retries the command.
VENETIAN_TILT_VERIFY_TOLERANCE = 5  # percent
# Skip the tilt command when the commanded position exceeds this threshold —
# at high positions the slats are retracted into the housing and tilting is
# physically meaningless. The value is configurable per-instance.
CONF_VENETIAN_TILT_SKIP_ABOVE = "venetian_tilt_skip_above"
DEFAULT_VENETIAN_TILT_SKIP_ABOVE = 95  # percent
MIN_VENETIAN_TILT_SKIP_ABOVE = 50
MAX_VENETIAN_TILT_SKIP_ABOVE = 100

# Venetian cover operating mode.  position_and_tilt tracks both axes with solar
# geometry; tilt_only closes the cover to 0% and tracks only the slat angle.
CONF_VENETIAN_MODE = "venetian_mode"
VENETIAN_MODE_POSITION_AND_TILT = "position_and_tilt"
VENETIAN_MODE_TILT_ONLY = "tilt_only"
DEFAULT_VENETIAN_MODE = VENETIAN_MODE_POSITION_AND_TILT
VENETIAN_MODES = (VENETIAN_MODE_POSITION_AND_TILT, VENETIAN_MODE_TILT_ONLY)

# Maximum slat tilt percentage (0–100). Caps the sun-derived slat angle so
# slats never reach angles that can reflect direct sun into the room.
CONF_MAX_TILT = "max_tilt"
DEFAULT_MAX_TILT = 100
_RANGE_MAX_TILT = (0, 100)

# Minimum slat tilt percentage (0–100). Floors the sun-derived slat angle so
# slats never close fully — useful for blinds that block all light at 0%.
CONF_MIN_TILT = "min_tilt"
DEFAULT_MIN_TILT = 0
_RANGE_MIN_TILT = (0, 100)

# Manual override detection grace period (fixed values, not configurable)
COMMAND_GRACE_PERIOD_SECONDS = 5.0  # Time to ignore position changes after command
STARTUP_GRACE_PERIOD_SECONDS = (
    30.0  # Time to disable manual override detection on startup
)

# Maximum time (seconds) to suppress manual override detection after sending a
# position command.  Once this threshold is crossed, wait_for_target is cleared
# even if the cover still reports a transitional state ("opening"/"closing").
#
# Purpose: covers that do not report a final state ("stopped"/"open"/"closed")
# when the user stops them mid-transit — only emitting position updates — would
# otherwise keep wait_for_target=True indefinitely, preventing manual override
# detection until the reconciliation timer fired.  This constant caps that
# window at a value that accommodates most motorized blinds and awnings, which
# typically complete a full traverse in 20–40 seconds.  The timeout resets
# whenever the cover makes forward progress toward target, so slow-but-moving
# covers get an extended window proportional to when they last moved.
DEFAULT_TRANSIT_TIMEOUT_SECONDS = 45
TRANSIT_TIMEOUT_SECONDS = DEFAULT_TRANSIT_TIMEOUT_SECONDS  # backward-compat alias

# User-configurable transit timeout (exposed in the manual override config step)
CONF_TRANSIT_TIMEOUT = "transit_timeout"
MIN_TRANSIT_TIMEOUT = 15
MAX_TRANSIT_TIMEOUT = 600

# Motion control constants
DEFAULT_MOTION_TIMEOUT = 300  # 5 minutes default timeout for no-motion detection
CONF_MOTION_TIMEOUT_MODE = "motion_timeout_mode"
MOTION_TIMEOUT_MODE_RETURN = "return_to_default"
MOTION_TIMEOUT_MODE_HOLD = "hold_position"
DEFAULT_MOTION_TIMEOUT_MODE = MOTION_TIMEOUT_MODE_RETURN

# Weather override constants
DEFAULT_WEATHER_WIND_SPEED_THRESHOLD = (
    50.0  # threshold unit must match sensor (no conversion applied)
)
DEFAULT_WEATHER_WIND_DIRECTION_TOLERANCE = 45  # degrees each side of window azimuth
DEFAULT_WEATHER_RAIN_THRESHOLD = (
    1.0  # threshold unit must match sensor (no conversion applied)
)
DEFAULT_WEATHER_TIMEOUT = 300  # seconds before resuming after conditions clear

# Cloud coverage constants
DEFAULT_CLOUD_COVERAGE_THRESHOLD = 75  # 75% cloud coverage = overcast

# Window/awning geometry defaults (UI defaults and validation caps)
DEFAULT_WINDOW_HEIGHT = 2.1  # metres
DEFAULT_AWNING_LENGTH = 2.1  # metres — awning extension length
DEFAULT_WINDOW_AZIMUTH = 180  # degrees, south-facing
MAX_WINDOW_DEPTH = 5.0  # metres — UI cap for window depth
MAX_AWNING_ANGLE = 45  # degrees — UI cap for awning tilt
DEGREES_IN_CIRCLE = 360  # used for azimuth/wind-direction wrap-around math

STRATEGY_MODE_BASIC = "basic"
STRATEGY_MODE_CLIMATE = "climate"
STRATEGY_MODES = [
    STRATEGY_MODE_BASIC,
    STRATEGY_MODE_CLIMATE,
]


class SensorType:
    """Possible modes for a number selector."""

    BLIND = "cover_blind"
    AWNING = "cover_awning"
    TILT = "cover_tilt"
    VENETIAN = "cover_venetian"


class ControlStatus:
    """Control status options for diagnostic sensor."""

    ACTIVE = "active"
    OUTSIDE_TIME_WINDOW = "outside_time_window"
    POSITION_DELTA_TOO_SMALL = "position_delta_too_small"
    TIME_DELTA_TOO_SMALL = "time_delta_too_small"
    MANUAL_OVERRIDE = "manual_override"
    AUTOMATIC_CONTROL_OFF = "automatic_control_off"
    SUN_NOT_VISIBLE = "sun_not_visible"
    FORCE_OVERRIDE_ACTIVE = "force_override_active"
    WEATHER_OVERRIDE_ACTIVE = "weather_override_active"
    MOTION_TIMEOUT = "motion_timeout"


# Geometric accuracy constants (used in calculation.py for safety margins and edge cases)
# Edge case thresholds for extreme sun positions
EDGE_CASE_LOW_ELEVATION = 2.0  # degrees - minimum elevation for normal calculation
EDGE_CASE_HIGH_ELEVATION = (
    88.0  # degrees - maximum elevation before using simplified calculation
)
EDGE_CASE_EXTREME_GAMMA = 85  # degrees - maximum horizontal angle deviation

# Safety margin thresholds and multipliers
SAFETY_MARGIN_GAMMA_THRESHOLD = 45  # degrees - angle where gamma-based margins start
SAFETY_MARGIN_GAMMA_MAX = 0.2  # 20% increase at extreme horizontal angles (>45°)
SAFETY_MARGIN_LOW_ELEV_THRESHOLD = (
    10  # degrees - elevation where low-angle margins apply
)
SAFETY_MARGIN_LOW_ELEV_MAX = 0.15  # 15% increase at low sun elevation (<10°)
SAFETY_MARGIN_HIGH_ELEV_THRESHOLD = (
    75  # degrees - elevation where high-angle margins apply
)
SAFETY_MARGIN_HIGH_ELEV_MAX = 0.1  # 10% increase at high sun elevation (>75°)

# Window depth calculation threshold
WINDOW_DEPTH_GAMMA_THRESHOLD = (
    10  # degrees - minimum gamma for window depth contribution
)

# Climate mode constants
CLIMATE_SUMMER_TILT_ANGLE = 45  # degrees - tilt angle for summer cooling strategy
CLIMATE_DEFAULT_TILT_ANGLE = 80  # degrees - default tilt angle when not present

# Cover position constants
POSITION_CLOSED = 0  # Fully closed position
POSITION_OPEN = 100  # Fully open position


# ---------------------------------------------------------------------------
# Numeric option ranges — single source of truth shared by config_flow.py
# (UI selectors) and services/options_service.py (programmatic validators).
# Each tuple is ``(min, max)`` for the named ``CONF_*`` option.
# ---------------------------------------------------------------------------

# Geometry — vertical blind
_RANGE_HEIGHT_WIN = (0.1, 50.0)
_RANGE_WINDOW_WIDTH = (0.1, 50.0)
_RANGE_WINDOW_DEPTH = (0.0, 5.0)
_RANGE_SILL_HEIGHT = (0.0, 50.0)
# Geometry — awning
_RANGE_LENGTH_AWNING = (0.3, 6.0)
_RANGE_AWNING_ANGLE = (0, 45)
# Geometry — tilt/venetian
_RANGE_TILT_DEPTH = (0.1, 15.0)
_RANGE_TILT_DISTANCE = (0.1, 15.0)
# Sun tracking
_RANGE_AZIMUTH = (0, 359)
_RANGE_FOV = (0, 180)
_RANGE_ELEVATION = (0, 90)
_RANGE_DISTANCE = (0.1, 50.0)
# Blind spot
_RANGE_BLIND_SPOT_LEFT = (0, 359)
_RANGE_BLIND_SPOT_RIGHT = (0, 360)
_RANGE_BLIND_SPOT_ELEVATION = (0, 90)
# Position limits & sunset
_RANGE_DEFAULT_HEIGHT = (0, 100)
_RANGE_MAX_POSITION = (1, 100)
_RANGE_MIN_POSITION = (0, 99)
_RANGE_SUNSET_POS = (0, 100)
_RANGE_MY_POSITION = (1, 99)
_RANGE_OFFSET_MINUTES = (-120, 120)
_RANGE_OPEN_CLOSE_THRESHOLD = (1, 99)
# Interpolation
_RANGE_INTERP_VALUE = (0, 100)
# Automation timing
_RANGE_DELTA_POSITION = (1, 90)
_RANGE_DELTA_TIME = (2, 60)
# Manual override
_RANGE_MANUAL_THRESHOLD = (0, 99)
# Force override / custom positions
_RANGE_FORCE_POSITION = (0, 100)
_RANGE_CUSTOM_POSITION = (0, 100)
_RANGE_CUSTOM_PRIORITY = (1, 99)
# Motion
_RANGE_MOTION_TIMEOUT = (30, 3600)
# Climate
_RANGE_TEMPERATURE = (0, 90)
_RANGE_OUTSIDE_THRESHOLD = (0, 100)
# Weather safety
_RANGE_WEATHER_WIND_SPEED = (0, 200)
_RANGE_WEATHER_WIND_DIRECTION_TOLERANCE = (5, 180)
_RANGE_WEATHER_RAIN = (0, 100)
_RANGE_WEATHER_OVERRIDE_POSITION = (0, 100)
_RANGE_WEATHER_TIMEOUT = (0, 3600)


def _build_option_ranges() -> dict[str, tuple[float, float]]:
    """Map every numeric option to its ``(min, max)`` range.

    Built lazily in a function so the module-level dict ordering stays sane
    (constants above are grouped by domain). Consumers should treat the
    returned dict as immutable.
    """
    ranges: dict[str, tuple[float, float]] = {
        CONF_HEIGHT_WIN: _RANGE_HEIGHT_WIN,
        CONF_WINDOW_WIDTH: _RANGE_WINDOW_WIDTH,
        CONF_WINDOW_DEPTH: _RANGE_WINDOW_DEPTH,
        CONF_SILL_HEIGHT: _RANGE_SILL_HEIGHT,
        CONF_LENGTH_AWNING: _RANGE_LENGTH_AWNING,
        CONF_AWNING_ANGLE: _RANGE_AWNING_ANGLE,
        CONF_TILT_DEPTH: _RANGE_TILT_DEPTH,
        CONF_TILT_DISTANCE: _RANGE_TILT_DISTANCE,
        CONF_AZIMUTH: _RANGE_AZIMUTH,
        CONF_FOV_LEFT: _RANGE_FOV,
        CONF_FOV_RIGHT: _RANGE_FOV,
        CONF_MIN_ELEVATION: _RANGE_ELEVATION,
        CONF_MAX_ELEVATION: _RANGE_ELEVATION,
        CONF_DISTANCE: _RANGE_DISTANCE,
        CONF_BLIND_SPOT_LEFT: _RANGE_BLIND_SPOT_LEFT,
        CONF_BLIND_SPOT_RIGHT: _RANGE_BLIND_SPOT_RIGHT,
        CONF_BLIND_SPOT_ELEVATION: _RANGE_BLIND_SPOT_ELEVATION,
        CONF_DEFAULT_HEIGHT: _RANGE_DEFAULT_HEIGHT,
        CONF_MAX_POSITION: _RANGE_MAX_POSITION,
        CONF_MIN_POSITION: _RANGE_MIN_POSITION,
        CONF_SUNSET_POS: _RANGE_SUNSET_POS,
        CONF_MY_POSITION_VALUE: _RANGE_MY_POSITION,
        CONF_SUNSET_OFFSET: _RANGE_OFFSET_MINUTES,
        CONF_SUNRISE_OFFSET: _RANGE_OFFSET_MINUTES,
        CONF_OPEN_CLOSE_THRESHOLD: _RANGE_OPEN_CLOSE_THRESHOLD,
        CONF_INTERP_START: _RANGE_INTERP_VALUE,
        CONF_INTERP_END: _RANGE_INTERP_VALUE,
        CONF_DELTA_POSITION: _RANGE_DELTA_POSITION,
        CONF_DELTA_TIME: _RANGE_DELTA_TIME,
        CONF_MANUAL_THRESHOLD: _RANGE_MANUAL_THRESHOLD,
        CONF_FORCE_OVERRIDE_POSITION: _RANGE_FORCE_POSITION,
        CONF_MOTION_TIMEOUT: _RANGE_MOTION_TIMEOUT,
        CONF_TEMP_LOW: _RANGE_TEMPERATURE,
        CONF_TEMP_HIGH: _RANGE_TEMPERATURE,
        CONF_OUTSIDE_THRESHOLD: _RANGE_OUTSIDE_THRESHOLD,
        CONF_WEATHER_WIND_SPEED_THRESHOLD: _RANGE_WEATHER_WIND_SPEED,
        CONF_WEATHER_WIND_DIRECTION_TOLERANCE: _RANGE_WEATHER_WIND_DIRECTION_TOLERANCE,
        CONF_WEATHER_RAIN_THRESHOLD: _RANGE_WEATHER_RAIN,
        CONF_WEATHER_OVERRIDE_POSITION: _RANGE_WEATHER_OVERRIDE_POSITION,
        CONF_WEATHER_TIMEOUT: _RANGE_WEATHER_TIMEOUT,
        CONF_MAX_TILT: _RANGE_MAX_TILT,
        CONF_MIN_TILT: _RANGE_MIN_TILT,
    }
    # Custom-position slots: per-slot position (0–100) and priority (1–99).
    for slot_keys in CUSTOM_POSITION_SLOTS.values():
        ranges[slot_keys["position"]] = _RANGE_CUSTOM_POSITION
        ranges[slot_keys["priority"]] = _RANGE_CUSTOM_PRIORITY
    return ranges


OPTION_RANGES: dict[str, tuple[float, float]] = _build_option_ranges()
