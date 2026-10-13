"""DataUpdateCoordinator for the viewsonic_projector integration."""

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .viewsonic_projector_tcp import (
    InputSource,
    PowerStatus,
    ProjectorError,
    ViewSonicProjectorTCP,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=2)

type ProjectorConfigEntry = ConfigEntry[ProjectorUpdateCoordinator]


@dataclass
class ProjectorData:
    """One polling snapshot of the projector's state."""

    power: PowerStatus
    volume: int
    source: InputSource
    muted: bool
    temperature: float
    lamp_hours: int


class ProjectorUpdateCoordinator(DataUpdateCoordinator[ProjectorData]):
    """Class to manage fetching status from a single ViewSonic projector."""

    projector: ViewSonicProjectorTCP

    def __init__(
        self,
        hass: HomeAssistant,
        projector: ViewSonicProjectorTCP,
    ) -> None:
        """Initialise projector status updater."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.projector = projector

    async def _async_update_data(self) -> ProjectorData:
        """Fetch status from the projector."""
        try:
            return ProjectorData(
                power=await self.projector.power_status(),
                volume=await self.projector.volume_status(),
                source=await self.projector.input_status(),
                muted=await self.projector.mute_status(),
                temperature=await self.projector.get_operating_temperature(),
                lamp_hours=await self.projector.get_light_source_usage_time(),
            )
        except ProjectorError as err:
            raise UpdateFailed(str(err)) from err
        except TimeoutError as err:
            raise UpdateFailed(f"Timeout talking to projector: {err}") from err
