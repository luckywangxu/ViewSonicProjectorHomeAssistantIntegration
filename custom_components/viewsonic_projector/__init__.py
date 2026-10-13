"""The projector_rs232 integration."""

import logging

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import ProjectorConfigEntry, ProjectorUpdateCoordinator
from .viewsonic_projector_tcp import ViewSonicProjectorTCP

_PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ProjectorConfigEntry) -> bool:
    """Set up projector_rs232 from a config entry."""

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    success = False
    projector = ViewSonicProjectorTCP(host=host, port=port)
    try:
        await projector.async_init()
        success = True
    except TimeoutError as err:
        _LOGGER.warning("Timeout connecting to %s:%s", host, port)
        raise ConfigEntryNotReady from err
    except OSError as err:
        _LOGGER.warning("Connection error to %s:%s: %s", host, port, err)
        raise ConfigEntryNotReady from err
    finally:
        if not success:
            projector.close()
    coordinator = ProjectorUpdateCoordinator(hass, projector)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ProjectorConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    if unload_ok:
        projector: ViewSonicProjectorTCP = entry.runtime_data.projector
        projector.close()
    return unload_ok
