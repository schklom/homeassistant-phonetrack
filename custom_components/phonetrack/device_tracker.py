"""Support for PhoneTrack device tracking."""
import logging
import urllib.parse
from datetime import timedelta
from typing import Any

import homeassistant.helpers.config_validation as cv  # type: ignore[import]
import requests  # type: ignore[import]
import voluptuous as vol  # type: ignore[import]
from homeassistant.components.device_tracker import (  # type: ignore[import]
    PLATFORM_SCHEMA,
    SeeCallback,
)
from homeassistant.const import CONF_DEVICES  # type: ignore[import]
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant  # type: ignore[import]
from homeassistant.helpers.event import async_track_time_interval # type: ignore[import]
from homeassistant.helpers.typing import ConfigType  # type: ignore[import]
from homeassistant.helpers.typing import DiscoveryInfoType
from homeassistant.util import slugify  # type: ignore[import]

_LOGGER = logging.getLogger(__name__)

CONF_MAX_GPS_ACCURACY = "max_gps_accuracy"
CONF_UPDATE_TIME_MINUTES = "update_time_minutes"
CONF_UPDATE_TIME_SECONDS = "update_time_seconds"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_DEVICES, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Required(CONF_TOKEN, default=""): cv.string,
        vol.Required(CONF_URL, default=""): cv.string,
        vol.Optional(CONF_MAX_GPS_ACCURACY, default=100000): vol.Coerce(float),
        vol.Optional(CONF_UPDATE_TIME_SECONDS, default=0): vol.Coerce(float),
        vol.Optional(CONF_UPDATE_TIME_MINUTES, default=5): vol.Coerce(float),
    }
)

def setup_scanner(
    hass: HomeAssistant,
    config: ConfigType,
    see: SeeCallback,
    _: DiscoveryInfoType | None = None,
) -> bool:
    """Set up the PhoneTrack scanner."""
    config_check = {
        CONF_URL: "URL",
        CONF_TOKEN: "Token",
        CONF_DEVICES: "Device list",
    }

    for key, item in config_check.items():
        if not config[key]:
            _LOGGER.error("%s missing from configuration", item)
            return False

    PhoneTrackDeviceTracker(hass, config, see)
    return True


class PhoneTrackDeviceTracker:  # pylint: disable=too-few-public-methods
    """
    A device tracker fetching last position from the PhoneTrack Nextcloud
    app.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config: ConfigType,
        see: SeeCallback,
    ) -> None:
        """Initialize the PhoneTrack tracking."""
        _LOGGER.debug("Initialize the PhoneTrack tracking")
        self.hass = hass
        self.url = config[CONF_URL]
        self.token = config[CONF_TOKEN]
        self.devices = config[CONF_DEVICES]
        self.max_gps_accuracy = config[CONF_MAX_GPS_ACCURACY]
        self.update_time_minutes = config[CONF_UPDATE_TIME_MINUTES]
        self.update_time_seconds = config[CONF_UPDATE_TIME_SECONDS]
        self.see = see
        self._update_info()

        self.update_interval = timedelta(minutes=self.update_time_minutes, seconds=self.update_time_seconds)

        _LOGGER.debug("Setting up PhoneTrack with update interval: %s", self.update_interval)

        # Initial call to update information
        self._update_info()

        # Schedule the periodic update
        self.hass.add_job(
            async_track_time_interval,
            self.hass,
            self._async_update_wrapper,
            self.update_interval
        )

    async def _async_update_wrapper(self, now=None):
        """Wrapper to run blocking update in executor."""
        await self.hass.async_add_executor_job(self._update_info)

    def _update_info(self, *_: Any, **__: Any) -> bool:
        """Update the device info."""
        _LOGGER.debug("Updating devices")
        try:
            data = requests.get(
                urllib.parse.urljoin(self.url, self.token),
                timeout=30,
            ).json()
            _LOGGER.debug("data gotten")
            data = data[self.token]
            _LOGGER.debug("data keys=%s", data.keys())
        except requests.exceptions.RequestException as ex:
            _LOGGER.error("Connection error while updating PhoneTrack: %s", ex)
            return False
        except ValueError as ex:
            _LOGGER.error("Error parsing PhoneTrack JSON: %s", ex)
            return False
        except requests.exceptions.ReadTimeout as ex:
            _LOGGER.error("Connection to server timed out after 30 seconds: %s", ex)
            return False

        for device in self.devices:
            _LOGGER.debug("Looping over devices: device=%s", device)
            if device not in data.keys():
                _LOGGER.info("Device %s is not available.", device)
                continue
            _LOGGER.debug("Getting lat and lon")
            lat, lon = data[device]["lat"], data[device]["lon"]
            _LOGGER.debug("lat=%s and lon=%s", lat, lon)
            accuracy = data[device]["accuracy"]
            battery = data[device]["batterylevel"]
            if (
                self.max_gps_accuracy is not None
                and data[device]["accuracy"] > self.max_gps_accuracy
            ):
                _LOGGER.info(
                    "Ignoring %s update because expected GPS accuracy is not met",
                    device,
                )
                continue

            self.see(
                dev_id=slugify(device),
                gps=(lat, lon),
                source_type="gps",
                gps_accuracy=accuracy,
                battery=battery,
            )
        return True
