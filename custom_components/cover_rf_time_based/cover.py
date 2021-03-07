"""Cover Time based, RF version."""
import logging

import voluptuous as vol

from datetime import timedelta

from homeassistant.core import callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.event import async_track_utc_time_change, async_track_time_interval
from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    PLATFORM_SCHEMA,
    CoverEntity,
)
from homeassistant.const import (
    CONF_NAME,
    ATTR_ENTITY_ID,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_STOP_COVER,
)

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.restore_state import RestoreEntity

_LOGGER = logging.getLogger(__name__)

CONF_DEVICES = 'devices'
CONF_NAME = 'name'
CONF_ALIASES = 'aliases'
CONF_TRAVELLING_TIME_DOWN = 'travelling_time_down'
CONF_TRAVELLING_TIME_UP = 'travelling_time_up'
CONF_SEND_STOP_AT_ENDS = 'send_stop_at_ends'
DEFAULT_TRAVEL_TIME = 25
DEFAULT_SEND_STOP_AT_ENDS = False

CONF_OPEN_SCRIPT_ENTITY_ID = 'open_script_entity_id'
CONF_CLOSE_SCRIPT_ENTITY_ID = 'close_script_entity_id'
CONF_STOP_SCRIPT_ENTITY_ID = 'stop_script_entity_id'
ATTR_CONFIDENT = 'confident'
ATTR_POSITION = 'position'
ATTR_ACTION = 'action'
ATTR_POSITION_TYPE = 'position_type'
ATTR_POSITION_TYPE_CURRENT = 'current'
ATTR_POSITION_TYPE_TARGET = 'target'
ATTR_UNCONFIRMED_STATE = 'unconfirmed_state'
SERVICE_SET_KNOWN_POSITION = 'set_known_position'
SERVICE_SET_KNOWN_ACTION = 'set_known_action'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_DEVICES, default={}): vol.Schema(
            {
                cv.string: {
                    vol.Required(CONF_NAME): cv.string,
                    vol.Required(CONF_OPEN_SCRIPT_ENTITY_ID): cv.entity_id,
                    vol.Required(CONF_CLOSE_SCRIPT_ENTITY_ID): cv.entity_id,
                    vol.Required(CONF_STOP_SCRIPT_ENTITY_ID): cv.entity_id,
                    vol.Optional(CONF_ALIASES, default=[]): vol.All(cv.ensure_list, [cv.string]),
                    vol.Optional(CONF_TRAVELLING_TIME_DOWN, default=DEFAULT_TRAVEL_TIME): cv.positive_int,
                    vol.Optional(CONF_TRAVELLING_TIME_UP, default=DEFAULT_TRAVEL_TIME): cv.positive_int,
                    vol.Optional(CONF_SEND_STOP_AT_ENDS, default=DEFAULT_SEND_STOP_AT_ENDS): cv.boolean,
                }
            }
        ),
    }
)

POSITION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_POSITION): cv.positive_int,
        vol.Optional(ATTR_CONFIDENT, default=False): cv.boolean,
        vol.Optional(ATTR_POSITION_TYPE, default=ATTR_POSITION_TYPE_TARGET): cv.string
    }
)


ACTION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_ACTION): cv.string
    }
)


DOMAIN = "cover_rf_time_based"

def devices_from_config(domain_config):
    """Parse configuration and add cover devices."""
    devices = []
    for device_id, config in domain_config[CONF_DEVICES].items():
        name = config.pop(CONF_NAME)
        travel_time_down = config.pop(CONF_TRAVELLING_TIME_DOWN)
        travel_time_up = config.pop(CONF_TRAVELLING_TIME_UP)
        open_script_entity_id = config.pop(CONF_OPEN_SCRIPT_ENTITY_ID)
        close_script_entity_id = config.pop(CONF_CLOSE_SCRIPT_ENTITY_ID)
        stop_script_entity_id = config.pop(CONF_STOP_SCRIPT_ENTITY_ID)
        send_stop_at_ends = config.pop(CONF_SEND_STOP_AT_ENDS)
        device = CoverTimeBased(device_id, name, travel_time_down, travel_time_up, open_script_entity_id, close_script_entity_id, stop_script_entity_id, send_stop_at_ends)
        devices.append(device)
    return devices



async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the cover platform."""
    async_add_entities(devices_from_config(config))

    platform = entity_platform.current_platform.get()

    platform.async_register_entity_service(
        SERVICE_SET_KNOWN_POSITION, POSITION_SCHEMA, "set_known_position"
    )

    platform.async_register_entity_service(
        SERVICE_SET_KNOWN_ACTION, ACTION_SCHEMA, "set_known_action"
    )


class CoverTimeBased(CoverEntity, RestoreEntity):
    def __init__(self, device_id, name, travel_time_down, travel_time_up, open_script_entity_id, close_script_entity_id, stop_script_entity_id, send_stop_at_ends):
        """Initialize the cover."""
        from xknx.devices import TravelCalculator
        self._travel_time_down = travel_time_down
        self._travel_time_up = travel_time_up
        self._open_script_entity_id = open_script_entity_id
        self._close_script_entity_id = close_script_entity_id 
        self._stop_script_entity_id = stop_script_entity_id
        self._send_stop_at_ends = send_stop_at_ends
        self._assume_uncertain_position = True 
        self._target_position = 0
        self._processing_known_position = False

        if name:
            self._name = name
        else:
            self._name = device_id

        self._unsubscribe_auto_updater = None

        self.tc = TravelCalculator(self._travel_time_down, self._travel_time_up)

    async def async_added_to_hass(self):
        """ Only cover position and confidence in that matters."""
        """ The rest is calculated from this attribute.        """
        old_state = await self.async_get_last_state()
        _LOGGER.debug(self._name + ': ' + 'async_added_to_hass :: oldState %s', old_state)
        if (old_state is not None and self.tc is not None and old_state.attributes.get(ATTR_CURRENT_POSITION) is not None):
            self.tc.set_position(int(old_state.attributes.get(ATTR_CURRENT_POSITION)))
        if (old_state is not None and old_state.attributes.get(ATTR_UNCONFIRMED_STATE) is not None):
         if type(old_state.attributes.get(ATTR_UNCONFIRMED_STATE)) == bool:
           self._assume_uncertain_position = old_state.attributes.get(ATTR_UNCONFIRMED_STATE)
         else:
           self._assume_uncertain_position = str(old_state.attributes.get(ATTR_UNCONFIRMED_STATE)) == str(True)


    def _handle_my_button(self):
        """Handle the MY button press"""
        if self.tc.is_traveling():
            _LOGGER.debug(self._name + ': ' + '_handle_my_button :: button stops cover')
            self.tc.stop()
            self.stop_auto_updater()

    @property
    def unconfirmed_state(self):
        """Return the assume state as a string to persist through restarts ."""
        return str(self._assume_uncertain_position)

    @property
    def name(self):
        """Return the name of the cover."""
        return self._name

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        attr = {}
        if self._travel_time_down is not None:
            attr[CONF_TRAVELLING_TIME_DOWN] = self._travel_time_down
        if self._travel_time_up is not None:
            attr[CONF_TRAVELLING_TIME_UP] = self._travel_time_up 
        attr[ATTR_UNCONFIRMED_STATE] = str(self._assume_uncertain_position)
        return attr

    @property
    def current_cover_position(self):
        """Return the current position of the cover."""
        return self.tc.current_position()

    @property
    def is_opening(self):
        """Return if the cover is opening or not."""
        from xknx.devices import TravelStatus
        return self.tc.is_traveling() and \
               self.tc.travel_direction == TravelStatus.DIRECTION_UP

    @property
    def is_closing(self):
        """Return if the cover is closing or not."""
        from xknx.devices import TravelStatus
        return self.tc.is_traveling() and \
               self.tc.travel_direction == TravelStatus.DIRECTION_DOWN

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        return self.tc.is_closed()

    @property
    def assumed_state(self):
        """Return True unless we have set position with confidence through send_know_position service."""
        return self._assume_uncertain_position
 
    async def async_set_cover_position(self, **kwargs):
       """Move the cover to a specific position."""
       if ATTR_POSITION in kwargs:
           self._target_position = kwargs[ATTR_POSITION]
           _LOGGER.debug(self._name + ': ' + 'async_set_cover_position: %d', self._target_position)
           await self.set_position(self._target_position)

    async def async_close_cover(self, **kwargs):
        """Turn the device close."""
        _LOGGER.debug(self._name + ': ' + 'async_close_cover')
        self.tc.start_travel_down()
        self._target_position = 100

        self.start_auto_updater()
        await self._async_handle_command(SERVICE_CLOSE_COVER)

    async def async_open_cover(self, **kwargs):
        """Turn the device open."""
        _LOGGER.debug(self._name + ': ' + 'async_open_cover')
        self.tc.start_travel_up()
        self._target_position = 0

        self.start_auto_updater()
        await self._async_handle_command(SERVICE_OPEN_COVER)

    async def async_stop_cover(self, **kwargs):
        """Turn the device stop."""
        _LOGGER.debug(self._name + ': ' + 'async_stop_cover')
        self._handle_my_button()
        await self._async_handle_command(SERVICE_STOP_COVER)

    async def set_position(self, position):
        _LOGGER.debug(self._name + ': ' + 'set_position')
        """Move cover to a designated position."""
        current_position = self.tc.current_position()
        _LOGGER.debug(self._name + ': ' + 'set_position :: current_position: %d, new_position: %d',
                      current_position, position)
        command = None
        if position > current_position:
            command = SERVICE_CLOSE_COVER
        elif position < current_position:
            command = SERVICE_OPEN_COVER
        if command is not None:
            self.start_auto_updater()
            self.tc.start_travel(position)
            _LOGGER.debug(self._name + ': ' + 'set_position :: command %s', command)
            await self._async_handle_command(command)

        return

    def start_auto_updater(self):
        """Start the autoupdater to update HASS while cover is moving."""
        _LOGGER.debug(self._name + ': ' + 'start_auto_updater')
        if self._unsubscribe_auto_updater is None:
            _LOGGER.debug(self._name + ': ' + 'init _unsubscribe_auto_updater')
            interval = timedelta(seconds=0.1)
            self._unsubscribe_auto_updater = async_track_time_interval(
                self.hass, self.auto_updater_hook, interval)

    @callback
    def auto_updater_hook(self, now):
        """Call for the autoupdater."""
        _LOGGER.debug(self._name + ': ' + 'auto_updater_hook')
        self.async_schedule_update_ha_state()
        if self.position_reached():
            _LOGGER.debug(self._name + ': ' + 'auto_updater_hook :: position_reached')
            self.stop_auto_updater()
        self.hass.async_create_task(self.auto_stop_if_necessary())

    def stop_auto_updater(self):
        """Stop the autoupdater."""
        _LOGGER.debug(self._name + ': ' + 'stop_auto_updater')
        if self._unsubscribe_auto_updater is not None:
            self._unsubscribe_auto_updater()
            self._unsubscribe_auto_updater = None

    def position_reached(self):
        """Return if cover has reached its final position."""
        return self.tc.position_reached()

    async def set_known_action(self, **kwargs):
        """We want to do a few things when we get a position"""
        action = kwargs[ATTR_ACTION]
        if action not in ["open","close","stop"]:
          raise ValueError("action must be one of open, close or stop.")
        if action == "stop":
          self._handle_my_button()
          return
        if action == "open":
          self.tc.start_travel_up()
          self._target_position = 0
        if action == "close":
          self.tc.start_travel_down()
          self._target_position = 100
        self.start_auto_updater()

    async def set_known_position(self, **kwargs):
        """We want to do a few things when we get a position"""
        position = kwargs[ATTR_POSITION]
        confident = kwargs[ATTR_CONFIDENT] if ATTR_CONFIDENT in kwargs else False
        position_type = kwargs[ATTR_POSITION_TYPE] if ATTR_POSITION_TYPE in kwargs else ATTR_POSITION_TYPE_TARGET
        if position_type not in [ATTR_POSITION_TYPE_TARGET, ATTR_POSITION_TYPE_CURRENT]:
          raise ValueError(ATTR_POSITION_TYPE + " must be one of %s, %s", ATTR_POSITION_TYPE_TARGET,ATTR_POSITION_TYPE_CURRENT)
        _LOGGER.debug(self._name + ': ' + 'set_known_position :: position  %d, confident %s, position_type %s, self.tc.is_traveling%s', position, str(confident), position_type, str(self.tc.is_traveling()))
        self._assume_uncertain_position = not confident 
        self._processing_known_position = True
        if position_type == ATTR_POSITION_TYPE_TARGET:
          self._target_position = position
          position = self.current_cover_position


        if self.tc.is_traveling():
          self.tc.set_position(position)
          self.tc.start_travel(self._target_position)
          self.start_auto_updater()
        else:
          if position_type == ATTR_POSITION_TYPE_TARGET:
            self.tc.start_travel(self._target_position)
            self.start_auto_updater()
          else:
            _LOGGER.debug(self._name + ': ' + 'set_known_position :: non_traveling position  %d, confident %s, position_type %s', position, str(confident), position_type)
            self.tc.set_position(position)

    async def auto_stop_if_necessary(self):
        """Do auto stop if necessary."""
        current_position = self.tc.current_position()
        if self.position_reached() and not self._processing_known_position:
            self.tc.stop()
            if (current_position > 0) and (current_position < 100):
                _LOGGER.debug(self._name + ': ' + 'auto_stop_if_necessary :: current_position between 1 and 99 :: calling stop command')
                await self._async_handle_command(SERVICE_STOP_COVER)
            else:
                if self._send_stop_at_ends:
                    _LOGGER.debug(self._name + ': ' + 'auto_stop_if_necessary :: send_stop_at_ends :: calling stop command')
                    await self._async_handle_command(SERVICE_STOP_COVER)

    async def _async_handle_command(self, command, *args):
        """We have cover.* triggered command. Reset assumed state and known_position processsing and execute"""
        self._assume_uncertain_position = True
        self._processing_known_position = False
        if command == "close_cover":
            cmd = "DOWN"
            self._state = False
            await self.hass.services.async_call("homeassistant", "turn_on", {"entity_id": self._close_script_entity_id}, False)

        elif command == "open_cover":
            cmd = "UP"
            self._state = True
            await self.hass.services.async_call("homeassistant", "turn_on", {"entity_id": self._open_script_entity_id}, False)

        elif command == "stop_cover":
            cmd = "STOP"
            self._state = True
            await self.hass.services.async_call("homeassistant", "turn_on", {"entity_id": self._stop_script_entity_id}, False)

        _LOGGER.debug(self._name + ': ' + '_async_handle_command :: %s', cmd)
        
        # Update state of entity
        self.async_write_ha_state()
