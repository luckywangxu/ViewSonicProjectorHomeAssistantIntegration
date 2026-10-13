"""Config flow for the viewsonic_projector integration."""

import logging
from typing import Any

import probatio

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_MODEL, CONF_PORT
from homeassistant.helpers import config_validation as cv, selector

from .const import DOMAIN, PROJECTOR_MODELS_LIST
from .viewsonic_projector_tcp import VIEWSONIC_LAN_PORT

_LOGGER = logging.getLogger(__name__)

TCP_TIMEOUT = 5.0


STEP_USER_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): cv.string,
        probatio.Required(CONF_PORT, default=VIEWSONIC_LAN_PORT): probatio.All(
            selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=65535, mode=selector.NumberSelectorMode.BOX
                ),
            ),
            probatio.Coerce(int),
        ),
        probatio.Required(CONF_MODEL): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=PROJECTOR_MODELS_LIST,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for viewsonic_projector."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip().lower()
            port = int(user_input[CONF_PORT])
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"{user_input[CONF_MODEL]} at {user_input[CONF_HOST]}:{user_input[CONF_PORT]}",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
