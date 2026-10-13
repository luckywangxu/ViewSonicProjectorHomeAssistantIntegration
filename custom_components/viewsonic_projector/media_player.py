"""Media Player platform for ViewSonic integration."""

import logging
from typing import override

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ProjectorConfigEntry
from .const import DOMAIN, PROJECTOR_MODELS
from .coordinator import ProjectorUpdateCoordinator
from .viewsonic_projector_tcp import InputSource, PowerStatus

_LOGGER = logging.getLogger(__name__)


_POWER_TO_STATE: dict[PowerStatus, MediaPlayerState] = {
    PowerStatus.ON: MediaPlayerState.ON,
    PowerStatus.WARM_UP: MediaPlayerState.ON,
    PowerStatus.COOL_DOWN: MediaPlayerState.ON,
    PowerStatus.OFF: MediaPlayerState.OFF,
}

VOLUME_MAX = 255


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ProjectorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Load ViewSonic Projector media player based on a config entry."""
    projector_entity = ViewsonicProjectorMediaPlayer(config_entry)
    async_add_entities([projector_entity])


class ViewsonicProjectorMediaPlayer(
    CoordinatorEntity[ProjectorUpdateCoordinator],
    MediaPlayerEntity,
):
    """Representation of ViewSonic Projector Device."""

    _attr_has_entity_name = True
    _attr_device_class = MediaPlayerDeviceClass.PROJECTOR

    # _attr_supported_features = (
    #     MediaPlayerEntityFeature.TURN_ON
    #     | MediaPlayerEntityFeature.TURN_OFF
    #     | MediaPlayerEntityFeature.VOLUME_SET
    #     | MediaPlayerEntityFeature.VOLUME_STEP
    #     | MediaPlayerEntityFeature.VOLUME_MUTE
    #     | MediaPlayerEntityFeature.SELECT_SOURCE
    # )

    def __init__(self, config_entry: ProjectorConfigEntry) -> None:
        """Initialize entity to control ViewSonic projector."""
        coordinator = config_entry.runtime_data
        super().__init__(coordinator)

        self._projector = coordinator.projector
        self._entry = config_entry

        model = config_entry.data[CONF_MODEL]
        if model not in PROJECTOR_MODELS:
            raise ValueError(
                f"Model {model!r} is not in PROJECTOR_MODELS; "
                f"known models: {list(PROJECTOR_MODELS)}"
            )
        self._sources_by_enum: dict[InputSource, str] = PROJECTOR_MODELS[model]
        self._enum_to_name: dict[InputSource, str] = self._sources_by_enum
        self._name_to_enum: dict[str, InputSource] = {
            name: enum for enum, name in self._sources_by_enum.items()
        }

        self._attr_source_list = list(self._enum_to_name.values())
        self._attr_unique_id = config_entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=config_entry.title,
            manufacturer="ViewSonic",
            model=model,
        )

    # ------------------------------------------------------------------ #
    # State properties — sourced from coordinator data
    # ------------------------------------------------------------------ #

    @property
    @override
    def state(self) -> MediaPlayerState | None:
        """Return the current media player state."""
        return _POWER_TO_STATE.get(self.coordinator.data.power)

    @property
    @override
    def volume_level(self) -> float | None:
        """Return the current volume level (0.0-1.0)."""
        volume = self.coordinator.data.volume
        if not isinstance(volume, int):
            return None
        return volume / VOLUME_MAX

    @property
    @override
    def is_volume_muted(self) -> bool:
        """Return True if the projector's audio is muted."""
        return bool(self.coordinator.data.muted)

    @property
    @override
    def source(self) -> str | None:
        """Return the currently selected input source name."""
        source = self.coordinator.data.source
        if not isinstance(source, InputSource):
            return None
        return self._enum_to_name.get(source)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose informational readings that have no first-class HA property."""
        return {
            "operating_temperature": self.coordinator.data.temperature,
            "light_source_hours": self.coordinator.data.lamp_hours,
        }

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    @override
    async def async_turn_on(self) -> None:
        """Turn on."""
        if self.state == MediaPlayerState.OFF:
            await self._projector.power_on()
            await self.coordinator.async_request_refresh()

    @override
    async def async_turn_off(self) -> None:
        """Turn off."""
        if self.state == MediaPlayerState.ON:
            await self._projector.power_off()
            await self.coordinator.async_request_refresh()

    @override
    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        selected = self._name_to_enum.get(source)
        if selected is None:
            _LOGGER.error(
                "Unknown source %r for model %s. Valid sources: %s",
                source,
                self._entry.data[CONF_MODEL],
                self._attr_source_list,
            )
            return
        await self._projector.set_input(selected)
        await self.coordinator.async_request_refresh()

    @override
    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume to a value in the range 0.0-1.0."""
        level = max(0, min(VOLUME_MAX, round(volume * VOLUME_MAX)))
        await self._projector.volume_set(level)
        await self.coordinator.async_request_refresh()

    @override
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute (true) or unmute (false) the audio output."""
        if mute:
            await self._projector.mute_on()
        else:
            await self._projector.mute_off()
        await self.coordinator.async_request_refresh()

    @override
    async def async_volume_up(self) -> None:
        """Increase volume by one step."""
        await self._projector.volume_up()
        await self.coordinator.async_request_refresh()

    @override
    async def async_volume_down(self) -> None:
        """Decrease volume by one step."""
        await self._projector.volume_down()
        await self.coordinator.async_request_refresh()

    @property
    @override
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return the features supported at this moment.

        The power-off feature is withheld while the projector is warming
        up or cooling down, which disables the power button in the UI.
        """
        power = self.coordinator.data.power

        if power in (PowerStatus.WARM_UP, PowerStatus.COOL_DOWN):
            return MediaPlayerEntityFeature.TURN_ON

        if power == PowerStatus.OFF:
            return MediaPlayerEntityFeature.TURN_ON

        return (
            MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.SELECT_SOURCE
        )
