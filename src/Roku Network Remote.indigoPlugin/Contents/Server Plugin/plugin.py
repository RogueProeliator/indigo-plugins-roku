#! /usr/bin/env python
# -*- coding: utf-8 -*-
#######################################################################################
# Roku Network Remote Control by RogueProeliator <rp@rogueproeliator.com>
# Indigo plugin designed to allow control of Roku devices via control pages using
# Roku's built-in External Control Protocol (ECP) interface
#
# Command structure based on Roku's documentation:
# http://sdkdocs.roku.com/display/sdkdoc/External+Control+Guide
#######################################################################################

# region Python imports
import re
import indigo # Added import
import logging # Added import for logging levels


import rokuNetworkRemoteDevice

# endregion


class Plugin(indigo.PluginBase): # Changed base class

	#######################################################################################
	# region Class construction and destruction methods
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Constructor called once upon plugin class creation; setup the device tracking
	# variables for later use
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def __init__(self, plugin_id, plugin_display_name, plugin_version, plugin_prefs):
		indigo.PluginBase.__init__(self, plugin_id, plugin_display_name, plugin_version, plugin_prefs)
		self.device_class = rokuNetworkRemoteDevice.RokuNetworkRemoteDevice # Store device class
		
		# create a list that will hold a cached version of the list of roku hardware
		# devices found on the network
		self.enumerated_roku_devices = []

	# endregion

	def startup(self):
		self.logger.debug("startup called")

	def shutdown(self):
		self.logger.debug("shutdown called")

	def deviceStartComm(self, device):
		self.logger.debug(f"deviceStartComm called for {device.name}")
		if hasattr(device, 'start_communication') and callable(getattr(device, 'start_communication')):
			device.start_communication()
		else:
			self.logger.warning(f"Device {device.name} has no start_communication method.")


	def deviceStopComm(self, device):
		self.logger.debug(f"deviceStopComm called for {device.name}")
		if hasattr(device, 'stop_communication') and callable(getattr(device, 'stop_communication')):
			device.stop_communication()
		else:
			self.logger.warning(f"Device {device.name} has no stop_communication method.")

	def runConcurrentThread(self):
		self.logger.debug("runConcurrentThread called - placeholder")
		try:
			while True:
				self.sleep(300) # Example: Discover every 5 minutes
		except self.StopThread:
			self.logger.debug("runConcurrentThread stopping.")
			pass # Optionally perform cleanup

	def validatePrefsConfigUi(self, values_dict):
		self.logger.debug("validatePrefsConfigUi called")
		return True, values_dict

	def closedPrefsConfigUi(self, values_dict, user_cancelled):
		self.logger.debug(f"closedPrefsConfigUi called, user_cancelled={user_cancelled}")
		if not user_cancelled:
			pass

	def validateDeviceConfigUi(self, values_dict, type_id, dev_id):
		self.logger.debug(f"validateDeviceConfigUi called for type_id={type_id}, dev_id={dev_id}")
		return True, values_dict

	def validateActionConfigUi(self, values_dict, type_id, action_id):
		self.logger.debug(f"validateActionConfigUi called for type_id={type_id}, action_id={action_id}")
		return True, values_dict

	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def actionControlGeneral(self, action, dev):
		if action.deviceAction == indigo.kDeviceGeneralAction.RequestStatus:
			self.logger.info(f"Status request for {dev.name}")
			if hasattr(dev, 'queue_command') and callable(getattr(dev, 'queue_command')):
				dev.queue_command({'type': 'status_update'})
			else:
				self.logger.error(f"Device {dev.name} cannot handle status requests.")
		else:
			self.logger.warning(f"Unhandled general action {action.deviceAction} for device {dev.name}")

	def actionControlDevice(self, action, dev):
		action_id = action.pluginTypeId
		self.logger.debug(f"actionControlDevice called for {dev.name}, action: {action_id}")

		#	 else:
		# else:
		pass # Remove pass once actions are implemented

	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def discover_roku_devices(self):
		self.logger.info("Starting Roku discovery via SSDP")
		try:
			from ssdpy import SSDPClient
			client = SSDPClient()
			devices = client.m_search("roku:ecp", timeout=5) # Adjust timeout as needed

			self.logger.info(f"SSDP discovery found {len(devices)} potential Roku devices.")
			self.enumerated_roku_devices = self.parse_ssdp_device_list(devices) # Use the refactored parser


		except ImportError:
			self.logger.error("Failed to import ssdpy library. Ensure it is vendored correctly.")
		except Exception as e:
			self.logger.exception(f"Error during SSDP discovery: {e}")

	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def log_discovered_devices_menu_item(self):
		self.logger.info("Manual Roku Discovery Triggered")
		self.discover_roku_devices()
		if self.enumerated_roku_devices:
			self.logger.info("Discovered Roku Devices (Serial | Location):")
			for serial, description in self.enumerated_roku_devices:
				self.logger.info(f"  - {description}")
		else:
			self.logger.info("No Roku devices found in the last discovery scan.")


	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def is_ip_v4_valid(self, ip_string):
		import socket
		try:
			socket.inet_aton(ip_string)
			return True
		except socket.error:
			return False


	#######################################################################################
		
	#######################################################################################
	# region Data Validation methods
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def parse_ssdp_device_list(self, device_list):
		self.logger.debug("parse_ssdp_device_list called - needs implementation")
		roku_options = []
		try:
			for device in device_list:
				usn = device.get('usn', '')
				location = device.get('location', '')
				if "roku:ecp" in usn: # Check if USN contains Roku identifier
					serial_number = usn.replace("uuid:roku:ecp:", "")
					match = re.match(r"http://([\d\.]+):(\d+)/?", location)
					if match and serial_number:
						ip_address = match.group(1)
						roku_options.append((f"{serial_number}", f"Serial #{serial_number} (Currently {ip_address})"))
					else:
						self.logger.warning(f"Could not parse location or serial for SSDP device: {device}")
				else:
					self.logger.debug(f"Ignoring non-Roku SSDP device: {usn}")
		except Exception as e:
			self.logger.exception(f"Failed to parse SSDP devices: {e}")
		return roku_options
	
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def retrieve_roku_apps(self, filter="", values_dict=None, type_id="", target_id=0):
		try:
			if target_id == 0:
				self.logger.error("retrieve_roku_apps: No target device specified.")
				return []
				
			roku_device = indigo.devices.get(target_id, None)
			if not roku_device:
				self.logger.error(f"retrieve_roku_apps: Target device {target_id} not found.")
				return []

			if hasattr(roku_device, 'get_cached_app_list') and callable(getattr(roku_device, 'get_cached_app_list')):
				available_apps = roku_device.get_cached_app_list() # Or trigger an update if cache is stale
				app_options = []
				if available_apps:
					for app_info in available_apps:
						if len(app_info) >= 3:
							app_id, _, app_name = app_info[:3]
							app_options.append((str(app_id), app_name)) # Ensure ID is string for list control
						else:
							self.logger.warning(f"Malformed app info in cache for device {target_id}: {app_info}")
				else:
					self.logger.debug(f"No cached app list available for device {target_id}.")
				return sorted(app_options, key=lambda option: option[1])
			else:
				self.logger.error(f"retrieve_roku_apps: Device {target_id} ({roku_device.name}) does not have get_cached_app_list method.")
				return [] # Return empty list if method missing
		except Exception as e:
			self.logger.exception(f"Failed to retrieve Roku Apps for device {target_id}: {e}")
			return []


	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def get_channel_list_for_menu(self, filter="", values_dict=None, type_id="", target_id=0):
		"""Renamed from retrieve_roku_apps for clarity in XML."""
		return self.retrieve_roku_apps(filter, values_dict, type_id, target_id)

	def get_discovered_device_list_for_menu(self, filter="", values_dict=None, type_id="", target_id=0):
		"""Returns the cached list of discovered Roku devices for config dialogs."""
		if not self.enumerated_roku_devices:
			self.logger.debug("Discovered device list is empty, triggering discovery for menu.")
			self.discover_roku_devices() # Perform discovery if list is empty
			
		manual_entry = [("manual", "-- Manually Enter IP Address --")]
		return manual_entry + self.enumerated_roku_devices

	def select_discovered_device_for_config(self, values_dict, type_id, dev_id):
		"""Callback for the 'Use Selected Device' button in device config."""
		selected_serial = values_dict.get("upnpEnumeratedDevices", "")
		if selected_serial and selected_serial != "manual":
			self.logger.debug(f"User selected discovered device with serial: {selected_serial}")
			found_desc = ""
			for serial, description in self.enumerated_roku_devices:
				if serial == selected_serial:
					found_desc = description
					break
			
			if found_desc:
				values_dict["httpAddress"] = selected_serial 
				self.logger.info(f"Set httpAddress field to serial: {selected_serial}")
			else:
				self.logger.warning(f"Selected serial {selected_serial} not found in cached list.")
		elif selected_serial == "manual":
			values_dict["httpAddress"] = ""
			self.logger.debug("User selected manual IP entry.")
		else:
			self.logger.warning("No device selected or invalid selection.")
			
		return values_dict # Return modified values_dict to update the dialog


	# endregion
	#######################################################################################

	#######################################################################################
	# region Actions object callback handlers/routines
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will be called from the user executing the menu item action to send
	# an arbitrary command code to the Onkyo receiver
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def send_arbitrary_command(self, values_dict, type_id):
		try:
			device_id    = values_dict.get("targetDevice", "0")
			command_code = values_dict.get("commandToSend", "").strip()
		
			if device_id == "" or device_id == "0":
				# no device was selected
				error_dict = indigo.Dict()
				error_dict["targetDevice"] = "Please select a device"
				return False, values_dict, error_dict
			elif command_code == "":
				error_dict = indigo.Dict()
				error_dict["commandToSend"] = "Enter command to send"
				return False, values_dict, error_dict
			else:
				roku_device = indigo.devices.get(int(device_id), None)
				if not roku_device:
					self.logger.error(f"send_arbitrary_command: Target device {device_id} not found.")
					return False, values_dict 

				if hasattr(roku_device, 'queue_command') and callable(getattr(roku_device, 'queue_command')):
					roku_device.queue_command({'type': 'arbitrary', 'command': command_code})
					self.logger.info(f"Queued arbitrary command '{command_code}' for device {device_id}")
					return True, values_dict
				else:
					self.logger.error(f"send_arbitrary_command: Device {device_id} ({roku_device.name}) cannot process arbitrary commands (missing queue_command method).")
					error_dict = indigo.Dict()
					error_dict["commandToSend"] = "Device cannot process command."
					return False, values_dict, error_dict
					
		except Exception as e:
			self.logger.exception(f"Error in send_arbitrary_command: {e}")
			return False, values_dict


	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def toggle_debug_enabled(self, values_dict=None, type_id=""):
		"""Toggles the debug level preference."""
		current_level = int(self.pluginPrefs.get("debugLevel", 0))
		new_level = (current_level + 1) % 3 # Cycle through 0, 1, 2
		self.pluginPrefs["debugLevel"] = str(new_level)
		self.logger.info(f"Debug level set to: {['Off', 'Low', 'High'][new_level]}")
		if new_level == 0:
			self.logger.setLevel(logging.INFO)
		elif new_level == 1:
			self.logger.setLevel(logging.DEBUG)
		else: # High
			self.logger.setLevel(logging.DEBUG) 

	def dump_device_details_to_log(self, values_dict, type_id):
		"""Logs details for selected devices."""
		device_ids_to_dump = values_dict.get("devicesToDump", [])
		self.logger.info("--- Dumping Device Details ---")
		for dev_id in device_ids_to_dump:
			try:
				dev = indigo.devices[int(dev_id)]
				self.logger.info(f"Device: {dev.name} (ID: {dev.id}, Type: {dev.deviceTypeId})")
				self.logger.info("  States:")
				for key, value in dev.states.items():
					self.logger.info(f"    {key}: {value}")
				self.logger.info("  Props:")
				for key, value in dev.pluginProps.items():
					self.logger.info(f"    {key}: {value}")
				self.logger.info("-" * 20)
			except Exception as e:
				self.logger.error(f"Failed to dump details for device ID {dev_id}: {e}")
		self.logger.info("--- End Device Dump ---")
		return True # Indicate success



	# endregion
	#######################################################################################
