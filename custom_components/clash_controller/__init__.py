async def async_setup_entry(hass, entry):
    """Set up Clash Controller from a config entry."""
    hass.data.setdefault("clash_controller", {})
    hass.data["clash_controller"][entry.entry_id] = entry.data

    # Register device
    device_registry = await hass.helpers.device_registry.async_get_registry()
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.data["unique_id"] + "_device")},
        manufacturer="Clash",
        model=entry.data["clash_core_version"],
        name="Clash Controller"
    )

    # Forward entry setup to platforms
    # await hass.config_entries.async_forward_entry_setup(entry, "sensor")

    return True
