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

import rokuNetworkRemoteDevice

from RPFramework.RPFrameworkPlugin import RPFrameworkPlugin
from RPFramework.RPFrameworkPlugin import DEBUGLEVEL_HIGH
# endregion


class Plugin(RPFrameworkPlugin):

	#######################################################################################
	# region Class construction and destruction methods
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Constructor called once upon plugin class creation; setup the device tracking
	# variables for later use
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def __init__(self, plugin_id, plugin_display_name, plugin_version, plugin_prefs):
		# RP framework base class's init method
		super().__init__(plugin_id, plugin_display_name, plugin_version, plugin_prefs, managed_device_class_module=rokuNetworkRemoteDevice, supports_upnp=True)
		
		# create a list that will hold a cached version of the list of roku hardware
		# devices found on the network
		self.enumerated_roku_devices = []

	# endregion
	#######################################################################################
		
	#######################################################################################
	# region Data Validation methods
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine is called to parse out a uPNP search results list
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def parse_upnp_device_list(self, device_list):
		try:
			roku_options = []
		
			for roku_device in device_list:
				serial_number = roku_device.usn.replace("uuid:roku:ecp:", "")
				ip_address    = re.match(r"http://([\d\.]*)\:{0,1}(\d+)", roku_device.location, re.I)
				roku_options.append((f"{serial_number}", f"Serial #{serial_number} (Currently {ip_address.group(1)})"))
			return roku_options
			
		except:
			if self.debugLevel == DEBUGLEVEL_HIGH:
				self.logger.exception("Failed to enumerate devices")
			return []	
	
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine is called back to the plugin when the GUI action loads that allows
	# launching a channel
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def retrieve_roku_apps(self, filter="", values_dict=None, type_id="", target_id=0):
		try:
			# use the roku device to retrieve the list of available applications
			available_apps = self.managed_devices[target_id].retrieve_app_list()
			app_options    = []
			
			for rokuApp in available_apps:
				app_id      = rokuApp[0]
				app_version = rokuApp[1]
				app_name    = rokuApp[2]
				
				app_options.append((app_id, app_name))
			
			return sorted(app_options, key=lambda option: option[1])
		except:
			self.logger.exception("Failed to retrieve Roku Apps")
			return []

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
				# send the code using the normal action processing...
				action_params = indigo.Dict()
				action_params["commandToSend"] = command_code
				self.execute_action(pluginAction=None, indigoActionId="sendArbitraryCommand", indigoDeviceId=int(device_id), paramValues=action_params)
				return True, values_dict
		except:
			self.logger.exception()
			return False, values_dict

	# endregion
	#######################################################################################
