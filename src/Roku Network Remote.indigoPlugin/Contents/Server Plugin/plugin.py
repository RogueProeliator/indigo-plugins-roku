#! /usr/bin/env python
# -*- coding: utf-8 -*-
"""
Roku Network Remote Control Plugin for Indigo
Developed by RogueProeliator <rp@rogueproeliator.com>

This plugin allows Indigo to control Roku devices and Roku TVs via their
External Control Protocol (ECP) over HTTP.

Command structure based on Roku's External Control Protocol documentation:
https://developer.roku.com/docs/developer-program/debugging/external-control-api.md

Rewritten for Indigo 2025.1 without RPFramework dependency.
"""

# region Python Imports
import logging
import time
from typing import Dict, Optional, Tuple, List

import indigo

from roku_device import RokuDevice
from roku_discovery import RokuDiscovery
# endregion

# region Constants
LOG_FORMAT = '%(asctime)s.%(msecs)03d\t%(levelname)-10s\t%(name)s.%(funcName)-28s %(message)s'

# Debug level mapping from plugin prefs to Python logging levels
DEBUG_LEVEL_MAP = {
    "0": logging.WARNING,  # Off = minimal logging
    "1": logging.INFO,     # Low = info level
    "2": logging.DEBUG     # High = debug level
}
# endregion


class Plugin(indigo.PluginBase):
    """
    Main plugin class for Roku Network Remote Control.
    
    This plugin allows Indigo to control Roku devices and Roku TVs
    via their External Control Protocol (ECP) over HTTP.
    """

    # ========================================================================
    # region Class Construction and Destruction
    # ========================================================================
    def __init__(self, plugin_id: str, plugin_display_name: str, 
                 plugin_version: str, plugin_prefs: indigo.Dict):
        """
        Initialize the plugin.
        
        Args:
            plugin_id: The unique identifier for this plugin
            plugin_display_name: Human-readable plugin name
            plugin_version: Plugin version string
            plugin_prefs: Saved plugin preferences
        """
        super().__init__(plugin_id, plugin_display_name, plugin_version, plugin_prefs)
        
        # Initialization flags
        self.plugin_is_initializing = True
        self.plugin_is_shutting_down = False
        
        # Configure logging
        debug_level_str = str(plugin_prefs.get('debugLevel', '0'))
        self.debug_level = DEBUG_LEVEL_MAP.get(debug_level_str, logging.WARNING)

        self.plugin_file_handler.setFormatter(
            logging.Formatter(fmt=LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S')
        )
        self.indigo_log_handler.setLevel(self.debug_level)
        
        # Device tracking - maps device ID to RokuDevice instance
        self.managed_devices: Dict[int, RokuDevice] = {}
        
        # UPnP discovery
        self.discovery = RokuDiscovery(self.logger)
        self.enumerated_roku_devices: List = []
        
        self.logger.debug("Plugin __init__ complete")
        self.plugin_is_initializing = False

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Plugin Lifecycle Methods
    # ========================================================================
    def startup(self) -> None:
        """
        Called after plugin initialization.
        
        Perform any startup tasks here, such as:
        - Verifying Indigo version compatibility
        - Initializing device states
        - Starting background services
        """
        import sys
        
        # Log startup banner
        self.logger.info(f"{'=' * 28} Initializing Plugin {'=' * 28}")
        self.logger.info(f"{'Plugin Name:':<30} {self.pluginDisplayName}")
        self.logger.info(f"{'Plugin Version:':<30} {self.pluginVersion}")
        self.logger.info(f"{'Plugin ID:':<30} {self.pluginId}")
        self.logger.info(f"{'Logging Level:':<30} {logging.getLevelName(self.debug_level)}")
        self.logger.info(f"{'Indigo Version:':<30} {indigo.server.version}")
        self.logger.info(f"{'Python Version:':<30} {sys.version.split()[0]}")
        self.logger.info("=" * 72)
        
        # Initialize all existing devices to a known state
        for dev in indigo.devices.iter("self"):
            self.logger.debug(f"Initializing device: {dev.name}")
            dev.updateStateOnServer('isPoweredOn', value=False, uiValue='Starting')
        
        self.logger.info("Plugin started successfully")

    def shutdown(self) -> None:
        """
        Called when plugin is shutting down.
        
        Clean up any resources, stop threads, etc.
        """
        self.logger.info("Plugin shutting down...")
        self.plugin_is_shutting_down = True
        
        # Stop all device threads
        for dev_id, roku_device in self.managed_devices.items():
            try:
                roku_device.stop()
            except Exception as e:
                self.logger.warning(f"Error stopping device {dev_id}: {e}")
        
        self.logger.info("Plugin shutdown complete")

    def runConcurrentThread(self) -> None:
        """
        Main plugin loop for status polling.
        
        This method runs in a separate thread and is responsible for
        periodic status updates of all managed devices.
        """
        self.logger.debug("Concurrent thread starting")
        self.sleep(1)  # Initial pause
        
        try:
            while True:
                # Check each managed device for status update
                for dev_id, roku_device in list(self.managed_devices.items()):
                    try:
                        dev = indigo.devices.get(dev_id)
                        if dev and self._time_to_update(dev, roku_device):
                            roku_device.queue_status_update()
                    except Exception as e:
                        self.logger.error(f"Error checking device {dev_id}: {e}")
                
                self.sleep(2)  # Main loop interval
                
        except self.StopThread:
            self.logger.info("Concurrent thread stopping")

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Device Communication Methods
    # ========================================================================
    def deviceStartComm(self, dev: indigo.Device) -> None:
        """
        Called when device communication should start.
        
        Args:
            dev: The Indigo device to start communication with
        """
        self.logger.info(f"Starting communication with {dev.name}")
        
        try:
            # Check for and handle property upgrades from old versions
            self._upgrade_device_properties(dev)
            
            # Update state to indicate we're starting
            dev.updateStateOnServer('isPoweredOn', value=False, uiValue='Starting')
            
            # Create device manager instance
            roku_device = RokuDevice(self, dev)
            self.managed_devices[dev.id] = roku_device
            roku_device.start()
            
            # Trigger state list refresh if needed
            dev.stateListOrDisplayStateIdChanged()
            
            self.logger.debug(f"Device {dev.name} communication started")
            
        except Exception as e:
            self.logger.error(f"Failed to start communication with {dev.name}: {e}")
            dev.updateStateOnServer('isPoweredOn', value=False, uiValue='Error')

    def deviceStopComm(self, dev: indigo.Device) -> None:
        """
        Called when device communication should stop.
        
        Args:
            dev: The Indigo device to stop communication with
        """
        self.logger.info(f"Stopping communication with {dev.name}")
        
        try:
            # Stop and remove device manager
            if dev.id in self.managed_devices:
                roku_device = self.managed_devices[dev.id]
                roku_device.stop()
                del self.managed_devices[dev.id]
            
            # Update device state
            dev.setErrorStateOnServer("")
            dev.updateStateOnServer('isPoweredOn', value=False, uiValue='Disabled')
            
            self.logger.debug(f"Device {dev.name} communication stopped")
            
        except Exception as e:
            self.logger.warning(f"Error stopping communication with {dev.name}: {e}")

    def didDeviceCommPropertyChange(self, orig_dev: indigo.Device, 
                                    new_dev: indigo.Device) -> bool:
        """
        Check if device properties changed in a way that requires restart.
        
        Args:
            orig_dev: Original device state
            new_dev: New device state
            
        Returns:
            True if communication should be restarted
        """
        # Properties that require restart if changed
        restart_props = ['httpAddress', 'updateInterval', 'rokuIRCommandPause', 'rokuLiteralCommandPause']
        
        for prop in restart_props:
            if orig_dev.pluginProps.get(prop) != new_dev.pluginProps.get(prop):
                self.logger.debug(f"Property {prop} changed, requiring restart")
                return True
        
        return False

    def _upgrade_device_properties(self, dev: indigo.Device) -> None:
        """
        Upgrade device properties from older plugin versions.
        
        Handles migration of property names from pre-3.0 versions.
        
        Args:
            dev: The device to upgrade
        """
        dev_props = dev.pluginProps
        updated = False
        
        # Migrate old rokuIPAddress to httpAddress
        temp_roku_ip_address = dev_props.get("rokuIPAddress", "")
        if temp_roku_ip_address:
            dev_props["httpAddress"] = temp_roku_ip_address
            dev_props["rokuIPAddress"] = ""
            updated = True
        
        # Migrate old rokuEnumeratedUSN to httpAddress
        temp_roku_serial_number = dev_props.get("rokuEnumeratedUSN", "")
        if temp_roku_serial_number:
            dev_props["httpAddress"] = temp_roku_serial_number
            dev_props["rokuEnumeratedUSN"] = ""
            updated = True
        
        if updated:
            dev.replacePluginPropsOnServer(dev_props)
            self.logger.info(f"Upgraded device properties for {dev.name}")

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Action Callbacks
    # ========================================================================
    def execute_action(self, action: indigo.ActionGroup, dev: indigo.Device, 
                       caller_waiting_for_result: bool = False) -> None:
        """
        Handle action execution for device-specific actions.
        
        This is the main callback method referenced in Actions.xml.
        
        Args:
            action: The action to execute
            dev: The target device
            caller_waiting_for_result: Whether caller is waiting for result
        """
        action_id = action.pluginTypeId
        props = action.props
        
        self.logger.debug(f"Executing action {action_id} on {dev.name}")
        
        if dev.id not in self.managed_devices:
            self.logger.error(f"Device {dev.name} is not available")
            return
        
        roku_device = self.managed_devices[dev.id]
        
        try:
            if action_id == "remoteButtonToRoku":
                button = props.get("buttonSelect", "")
                repeat_count = int(props.get("repeatCount", "") or "1")
                roku_device.send_keypress(button, repeat_count)
                
            elif action_id == "sendKeyboardString":
                text = props.get("rokuKeyboardText", "")
                roku_device.send_keyboard_string(text)
                
            elif action_id == "launchChannel":
                app_id = props.get("rokuAppId", "")
                roku_device.launch_app(app_id)
                
            elif action_id == "tuneToStation":
                channel = props.get("rokuTVChannel", "")
                roku_device.tune_channel(channel)
                
            elif action_id == "downloadChannelIcons":
                destination = props.get("destinationOverride", "")
                roku_device.download_channel_icons(destination)
                
            elif action_id == "sendArbitraryCommand":
                command = props.get("commandToSend", "")
                roku_device.send_arbitrary_command(command)
                
            else:
                self.logger.warning(f"Unknown action: {action_id}")
                
        except Exception as e:
            self.logger.error(f"Error executing action {action_id}: {e}")

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Configuration UI Callbacks
    # ========================================================================
    def validateDeviceConfigUi(self, values_dict: indigo.Dict, 
                               type_id: str, dev_id: int) -> Tuple[bool, indigo.Dict]:
        """
        Validate device configuration.
        
        Args:
            values_dict: Dialog values
            type_id: Device type ID
            dev_id: Device ID (0 for new device)
            
        Returns:
            Tuple of (valid, values_dict) or (False, values_dict, errors_dict)
        """
        errors_dict = indigo.Dict()
        
        # Validate HTTP address
        http_address = values_dict.get("httpAddress", "").strip()
        if not http_address:
            errors_dict["httpAddress"] = "Please enter an IP address or select a device"
        
        # Validate update interval
        try:
            update_interval = int(values_dict.get("updateInterval", "10"))
            if update_interval < 0:
                errors_dict["updateInterval"] = "Update interval must be 0 or greater"
        except ValueError:
            errors_dict["updateInterval"] = "Please enter a valid number"
        
        # Validate IR command pause
        try:
            ir_pause = float(values_dict.get("rokuIRCommandPause", "0.3"))
            if ir_pause < 0 or ir_pause > 5:
                errors_dict["rokuIRCommandPause"] = "Pause must be between 0 and 5"
        except ValueError:
            errors_dict["rokuIRCommandPause"] = "Please enter a valid number"
        
        # Validate literal command pause
        try:
            literal_pause = float(values_dict.get("rokuLiteralCommandPause", "0.05"))
            if literal_pause < 0 or literal_pause > 5:
                errors_dict["rokuLiteralCommandPause"] = "Pause must be between 0 and 5"
        except ValueError:
            errors_dict["rokuLiteralCommandPause"] = "Please enter a valid number"
        
        if len(errors_dict) > 0:
            errors_dict["showAlertText"] = "Please correct the highlighted errors."
            return False, values_dict, errors_dict
        
        # Set the address field for display
        values_dict["address"] = http_address
        
        return True, values_dict

    def validatePrefsConfigUi(self, values_dict: indigo.Dict) -> Tuple[bool, indigo.Dict]:
        """
        Validate plugin preferences configuration.
        
        Args:
            values_dict: Dialog values
            
        Returns:
            Tuple of (valid, values_dict)
        """
        return True, values_dict

    def closedPrefsConfigUi(self, values_dict: indigo.Dict, 
                            user_cancelled: bool) -> None:
        """
        Called when plugin prefs dialog closes.
        
        Args:
            values_dict: Final dialog values
            user_cancelled: True if user cancelled
        """
        if not user_cancelled:
            # Update debug level
            debug_level_str = values_dict.get('debugLevel', '0')
            self.debug_level = DEBUG_LEVEL_MAP.get(debug_level_str, logging.WARNING)
            self.indigo_log_handler.setLevel(self.debug_level)
            
            self.logger.info("Plugin preferences saved")
        else:
            self.logger.debug("Plugin preferences cancelled")

    def getConfigDialogUPNPDeviceMenu(self, filter: str = "", 
                                      values_dict: indigo.Dict = None,
                                      type_id: str = "", 
                                      target_id: int = 0) -> List[Tuple[str, str]]:
        """
        Get UPnP device list for configuration dialog menu.
        
        Called by Devices.xml to populate the device discovery dropdown.
        
        Args:
            filter: Filter string (unused)
            values_dict: Current dialog values
            type_id: Device type ID
            target_id: Target device ID
            
        Returns:
            List of (value, label) tuples for menu
        """
        menu_items = []
        
        try:
            # Perform UPnP discovery
            self.enumerated_roku_devices = self.discovery.discover_devices(timeout=5)
            
            # Add manual entry option (use placeholder ID - Indigo requires non-empty IDs)
            menu_items.append(("MANUAL_ENTRY", "-- Manual Entry Below --"))
            
            # Add discovered devices
            for roku_device in self.enumerated_roku_devices:
                serial = roku_device.serial_number
                ip = roku_device.ip_address
                menu_items.append((serial, f"Serial #{serial} (Currently {ip})"))
                
        except Exception as e:
            self.logger.error(f"Error enumerating devices: {e}")
            menu_items.append(("DISCOVERY_ERROR", "-- Discovery Error --"))
        
        return menu_items

    def selectUPNPEnumeratedDeviceForUse(self, values_dict: indigo.Dict, 
                                         type_id: str, 
                                         dev_id: int) -> indigo.Dict:
        """
        Handle selection of UPnP device from menu.
        
        Called when user clicks "Use Selected Device" button.
        
        Args:
            values_dict: Current dialog values
            type_id: Device type ID
            dev_id: Device ID
            
        Returns:
            Updated values_dict
        """
        selected = values_dict.get("upnpEnumeratedDevices", "")
        
        # Ignore placeholder menu items
        if selected and selected not in ("MANUAL_ENTRY", "DISCOVERY_ERROR"):
            # Use serial number as address for dynamic IP resolution
            values_dict["httpAddress"] = selected
            self.logger.info(f"Selected Roku device: {selected}")
        
        return values_dict

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Dynamic List Generators
    # ========================================================================
    def retrieve_roku_apps(self, filter: str = "", values_dict: indigo.Dict = None,
                           type_id: str = "", target_id: int = 0) -> List[Tuple[str, str]]:
        """
        Retrieve list of apps from Roku device for action config.
        
        Called by Actions.xml to populate the app launch dropdown.
        
        Args:
            filter: Filter string (unused)
            values_dict: Current dialog values
            type_id: Action type ID
            target_id: Target device ID
            
        Returns:
            List of (app_id, app_name) tuples sorted by name
        """
        app_list = []
        
        try:
            if target_id in self.managed_devices:
                roku_device = self.managed_devices[target_id]
                apps = roku_device.get_app_list()
                
                for app_id, version, name in apps:
                    app_list.append((app_id, name))
                
                # Sort by name
                app_list.sort(key=lambda x: x[1])
                
        except Exception as e:
            self.logger.error(f"Error retrieving Roku apps: {e}")
        
        return app_list

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Menu Item Callbacks
    # ========================================================================
    def send_arbitrary_command(self, values_dict: indigo.Dict, 
                               type_id: str) -> Tuple[bool, indigo.Dict]:
        """
        Send an arbitrary command via menu item.
        
        Args:
            values_dict: Dialog values
            type_id: Type identifier
            
        Returns:
            Tuple of (success, values_dict) or (False, values_dict, errors_dict)
        """
        try:
            device_id_str = values_dict.get("targetDevice", "0")
            command = values_dict.get("commandToSend", "").strip()
            
            if device_id_str == "" or device_id_str == "0":
                error_dict = indigo.Dict()
                error_dict["targetDevice"] = "Please select a device"
                return False, values_dict, error_dict
                
            if command == "":
                error_dict = indigo.Dict()
                error_dict["commandToSend"] = "Enter command to send"
                return False, values_dict, error_dict
            
            device_id = int(device_id_str)
            if device_id in self.managed_devices:
                roku_device = self.managed_devices[device_id]
                roku_device.send_arbitrary_command(command)
                self.logger.info(f"Sent arbitrary command: {command}")
                return True, values_dict
            else:
                error_dict = indigo.Dict()
                error_dict["targetDevice"] = "Device not found or not running"
                return False, values_dict, error_dict
                
        except Exception as e:
            self.logger.error(f"Error sending arbitrary command: {e}")
            return False, values_dict

    def toggle_debug_enabled(self) -> None:
        """Toggle debug logging on/off."""
        if self.debug_level == logging.DEBUG:
            self.debug_level = logging.WARNING
            self.indigo_log_handler.setLevel(self.debug_level)
            self.pluginPrefs["debugLevel"] = "0"
            indigo.server.log("Debug logging disabled")
        else:
            self.debug_level = logging.DEBUG
            self.indigo_log_handler.setLevel(self.debug_level)
            self.pluginPrefs["debugLevel"] = "2"
            indigo.server.log("Debug logging enabled")

    def dump_device_details_to_log(self, values_dict: indigo.Dict, 
                                   type_id: str) -> Tuple[bool, indigo.Dict]:
        """
        Dump device details to the event log.
        
        Args:
            values_dict: Dialog values
            type_id: Type identifier
            
        Returns:
            Tuple of (success, values_dict)
        """
        device_ids = values_dict.get("devicesToDump", [])
        
        for dev_id_str in device_ids:
            try:
                dev_id = int(dev_id_str)
                dev = indigo.devices[dev_id]
                
                indigo.server.log("")
                indigo.server.log(f"===== Device Details: {dev.name} =====")
                indigo.server.log(f"Device ID: {dev.id}")
                indigo.server.log(f"Device Type: {dev.deviceTypeId}")
                indigo.server.log(f"Enabled: {dev.enabled}")
                indigo.server.log(f"Address: {dev.address}")
                
                indigo.server.log("----- Plugin Properties -----")
                for key, value in dev.pluginProps.items():
                    indigo.server.log(f"  {key}: {value}")
                
                indigo.server.log("----- States -----")
                for key, value in dev.states.items():
                    indigo.server.log(f"  {key}: {value}")
                
                indigo.server.log("================================")
                
            except Exception as e:
                self.logger.error(f"Error dumping device {dev_id_str}: {e}")
        
        return True, values_dict

    def log_upnp_devices_found(self, values_dict: indigo.Dict, 
                               type_id: str) -> Tuple[bool, indigo.Dict]:
        """
        Log UPnP devices found on the network.
        
        Args:
            values_dict: Dialog values
            type_id: Type identifier
            
        Returns:
            Tuple of (success, values_dict)
        """
        indigo.server.log("")
        indigo.server.log("===== UPnP Device Search =====")
        
        try:
            # Perform discovery with extended timeout
            devices = self.discovery.discover_devices(timeout=10)
            
            if not devices:
                indigo.server.log("No Roku devices found on network")
            else:
                indigo.server.log(f"Found {len(devices)} Roku device(s):")
                for device in devices:
                    indigo.server.log(f"  Serial: {device.serial_number}")
                    indigo.server.log(f"  IP: {device.ip_address}:{device.port}")
                    indigo.server.log(f"  Location: {device.location}")
                    indigo.server.log("")
                    
        except Exception as e:
            indigo.server.log(f"Error during UPnP search: {e}")
        
        indigo.server.log("==============================")
        
        return True, values_dict

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Helper Methods
    # ========================================================================
    def _time_to_update(self, dev: indigo.Device, roku_device: RokuDevice) -> bool:
        """
        Check if device is due for status update.
        
        Args:
            dev: The Indigo device to check
            roku_device: The RokuDevice manager instance
            
        Returns:
            True if device should be updated
        """
        if not dev.enabled:
            return False
        
        update_interval = int(dev.pluginProps.get("updateInterval", "10"))
        if update_interval <= 0:
            return False  # Polling disabled
        
        # Check time since last update
        elapsed = time.time() - roku_device.last_update_time
        return elapsed >= update_interval

    @staticmethod
    def is_ip_v4_valid(address: str) -> bool:
        """
        Check if address is a valid IPv4 address.
        
        Args:
            address: Address string to check
            
        Returns:
            True if valid IPv4 address
        """
        import re
        pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if re.match(pattern, address):
            parts = address.split('.')
            return all(0 <= int(part) <= 255 for part in parts)
        return False

    # endregion
    # ========================================================================
