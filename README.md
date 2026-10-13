# ViewSonic Projector

A Home Assistant custom integration for controlling supported ViewSonic projectors over a local network connection.

## Installation

### HACS

1. In HACS, open **Integrations** and select the three-dot menu.
2. Choose **Custom repositories**.
3. Add this repository's GitHub URL and select **Integration** as the category.
4. Find **ViewSonic Projector** in HACS and install it.
5. Restart Home Assistant.

### Manual

Copy the `custom_components/viewsonic_projector` directory into the `custom_components` directory of your Home Assistant configuration, then restart Home Assistant.

## Configuration

After installation, go to **Settings → Devices & services → Add integration**, search for **ViewSonic Projector**, and enter:

- **Host**: the projector's IP address or hostname.
- **Port**: the projector's TCP control port (default: `4661`).
- **Model**: the projector model. The integration currently supports PX701-4K Pro and PX748-4K.

The integration creates a projector media player for power, volume, mute, and input selection. Operating temperature and light-source usage time are available as entity attributes. The projector must be reachable from Home Assistant over the local network.

## Removal

Remove the integration from **Settings → Devices & services**, then remove it from HACS (or delete `custom_components/viewsonic_projector` if installed manually) and restart Home Assistant.

## Projector command reference

See [the RS232 command table](docs/RS232-command-table.pdf) for reference material.
