from homeassistant.helpers.entity import CoordinatorEntity
from homeassistant.components.sensor import SensorEntity

class ClashConnectionsSensor(CoordinatorEntity, SensorEntity):
    """A sensor to track the number of active connections in Clash."""

    def __init__(self, coordinator):
        """
        Initialize the sensor.
        """
        super().__init__(coordinator)
        self._attr_name = "Active Connections"
        self._attr_icon = "mdi:connection"
        self._attr_unit_of_measurement = "connections"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get("connections_count", 0)
