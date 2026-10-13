"""Constants for the viewsonic projector_rs232 integration."""

from .viewsonic_projector_tcp import InputSource

DOMAIN = "viewsonic_projector"

PROJECTOR_MODELS: dict[str, dict[InputSource, str]] = {
    "PX701-4K Pro": {
        InputSource.HDMI_1: "HDMI 1",
        InputSource.HDMI_2: "HDMI 2",
    },
    "PX748-4K": {
        InputSource.HDMI_1: "HDMI 1",
        InputSource.HDMI_2: "HDMI 2",
        InputSource.USB_C: "USB-C",
    },
}

PROJECTOR_MODELS_LIST = list(PROJECTOR_MODELS)
