"""Supported sensor capabilities and quantities from the supplied hardware plan."""

AIR_SENSOR_TYPES = frozenset({"am103", "am107"})
SENSOR_MODELS = (
    {"type": "am103", "name": "Milesight AM103", "planned_quantity": 12,
     "metrics": ["battery", "temperature", "humidity", "co2"]},
    {"type": "am107", "name": "Milesight AM107", "planned_quantity": 4,
     "metrics": ["battery", "temperature", "humidity", "activity", "illumination",
                 "infrared_and_visible", "infrared", "co2", "tvoc", "pressure"]},
    {"type": "ct305", "name": "Milesight CT305", "planned_quantity": 3,
     "metrics": ["current_1", "current_2", "current_3", "total_1", "total_2", "total_3", "temperature"]},
)
