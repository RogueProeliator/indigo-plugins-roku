#! /usr/bin/env python
# -*- coding: utf-8 -*-
#######################################################################################
# Roku Network Remote Control by RogueProeliator <rp@rogueproeliator.com>
#######################################################################################

# region Python Imports
import httplib
import os
import re
import urllib
import xml.etree.ElementTree

import indigo
from RPFramework.RPFrameworkCommand import RPFrameworkCommand
from RPFramework.RPFrameworkRESTfulDevice import RPFrameworkRESTfulDevice

# endregion


class RokuNetworkRemoteDevice(RPFrameworkRESTfulDevice):

	#######################################################################################
	# region Class construction and destruction methods
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Constructor called once upon plugin class receiving a command to start device
	# communication. The plugin will call other commands when needed, simply zero out the
	# member variables
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def __init__(self, plugin, device):
		super().__init__(plugin, device)
		
		# get the device properties; we may need to upgrade users from the old version of
		# addresses to the new version
		dev_props = self.indigoDevice.pluginProps
		
		temp_roku_ip_address    = dev_props.get("rokuIPAddress", "")
		temp_roku_serial_number = dev_props.get("rokuEnumeratedUSN", "")
		if temp_roku_ip_address != "":
			dev_props["httpAddress"]   = temp_roku_ip_address
			dev_props["rokuIPAddress"] = ""
			device.replacePluginPropsOnServer(dev_props)
		elif temp_roku_serial_number != "":
			dev_props["httpAddress"]       = temp_roku_serial_number
			dev_props["rokuEnumeratedUSN"] = ""
			device.replacePluginPropsOnServer(dev_props)
		self.roku_network_address = dev_props.get("httpAddress", "")

		self.cached_ip_address = ""
		self.host_plugin.logger.debug(f"Roku Address is {self.roku_network_address}")
		
		# add in updated/new states and properties
		self.upgraded_device_states.append("isPoweredOn")
		self.upgraded_device_states.append("serialNumber")
		self.upgraded_device_states.append("deviceModel")
		self.upgraded_device_states.append("isTV")
		self.upgraded_device_states.append("activeChannel")
		self.upgraded_device_states.append("screensaverActive")
		self.upgraded_device_states.append("activeTunerChannel")
		
		self.upgraded_device_properties.append(("updateInterval", "10"))

	# endregion
	#######################################################################################
	
	#######################################################################################
	# region Processing and command functions
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will process the commands that are not processed automatically by the
	# base class; it will be called on a concurrent thread
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def handle_unmanaged_command_in_queue(self, device_http_address, rp_command):
		if rp_command.commandName == "SEND_KEYBOARD_STRING":
			# needs to send a string of text to the roku device as a series of keypress
			# commands (RESTFUL_PUT commands)
			validated_text = re.sub(r'[^a-z\d ]', "", rp_command.commandPayload.lower())
			if validated_text == "":
				self.host_plugin.logger.debug(f"Ignoring send text to Roku, validated string is blank (source: {rp_command.commandPayload})")
			else:
				self.host_plugin.logger.threaddebug(f"Sending keyboard text: {validated_text}")
				pause_between_keys = float(self.indigoDevice.pluginProps.get("rokuLiteralCommandPause", "0.1"))
				for char in validated_text:
					self.queue_device_command(RPFrameworkCommand(RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, command_payload=f"http|*|/keypress/Lit_{urllib.quote_plus(char)}", post_command_pause=pause_between_keys))
		
		elif rp_command.commandName == u'DOWNLOAD_CHANNEL_ICONS':
			# the user has requested that we download the icons for channels on the Roku device...
			download_destination = rp_command.commandPayload
			if download_destination is None or download_destination == "":
				download_destination = indigo.server.getInstallFolderPath()
				self.host_plugin.logger.threaddebug(f"Indigo installation folder: {download_destination}")
				download_destination = os.path.join(download_destination, "IndigoWebServer/images/controls/static")

			# retrieve the list of channels/applications and attempt to download
			# each application's icon
			app_list = self.retrieve_app_list()
			
			for rokuApp in app_list:
				icon_file = None
				try:
					application_id   = rokuApp[0]
					application_name = rokuApp[2]
					
					self.host_plugin.logger.debug(f"Attempting download of icon for App #{application_id} ({application_name})")
					conn = httplib.HTTPConnection(device_http_address[0], device_http_address[1])
					conn.connect()
					conn.putrequest("GET", f"/query/icon/{application_id}")
					conn.endheaders()
					
					icon_response        = conn.getresponse()
					icon_image_extension = icon_response.getheader("content-type").replace("image/", "")
					icon_image_save_fn   = os.path.join(download_destination, f"RokuChannelIcon_{application_id}.{icon_image_extension}")
					
					self.host_plugin.logger.debug(f"Saving icon to {icon_image_save_fn}")
					icon_file = open(icon_image_save_fn, "wb")
					icon_file.write(icon_response.read())
					icon_file.close()
					
					conn.close()
				except:
					if icon_file is not None:
						icon_file.close()
					self.host_plugin.exceptionLog()
		else:
			self.host_plugin.logger.error(f"Received unknown command for device {self.indigoDevice.id}: {rp_command.command_name}")
				
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine should return the HTTP address that will be used to connect to the
	# device. It may connect via IP address or a host name
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def get_restful_device_address(self):
		self.host_plugin.logger.debug(f"IP address requested for Roku Device: {self.roku_network_address}")
			
		# if the ip address has not been filled in then we must look it up by serialNumber
		# via the SSDP service
		if self.host_plugin.isIPv4Valid(self.roku_network_address):
			ip_address = self.roku_network_address
		else:
			ip_address = self.obtain_roku_ip_address(self.roku_network_address)
			
		# return the IP address to the calling procedure...
		return ip_address, 8060
		
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will process any response from the device following the list of
	# response objects defined for this device type. For telnet this will always be
	# a text string
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def handle_device_text_response(self, response_obj, rp_command):
		# loop through the list of response definitions defined in the (base) class
		# and determine if any match
		response_text = response_obj.content
		for rpResponse in self.host_plugin.getDeviceResponseDefinitions(self.indigoDevice.deviceTypeId):
			if rp_command.parentAction is None:
				action_id = ""
			elif isinstance(rp_command.parentAction, str):
				action_id = rp_command.parentAction
			else:
				action_id = rp_command.parentAction.indigoActionId

			self.host_plugin.logger.threaddebug(f"Checking Action {action_id}  response against {rpResponse.respondToActionId}")
			if rpResponse.isResponseMatch(response_text, rp_command, self, self.host_plugin):
				self.host_plugin.logger.threaddebug(f"Found response match: {rpResponse.responseId}")
				rpResponse.executeEffects(response_text, rp_command, self, self.host_plugin)

	# endregion
	#######################################################################################

	#######################################################################################
	# region Private Utility Routines
	#######################################################################################
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will obtain the IP address for a Roku given the serial number; it does
	# this synchronously with the expectation that it is called from a concurrent thread
	# when asynchronous operations are required
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def obtain_roku_ip_address(self, serial_number):
		if self.cached_ip_address == u'':
			self.host_plugin.updateUPNPEnumerationList(self.indigoDevice.deviceTypeId)
			roku_list = self.host_plugin.enumeratedDevices
			for rokuDevice in roku_list:
				enumerated_serial = rokuDevice.usn.replace("uuid:roku:ecp:", "")
				if enumerated_serial == serial_number:
					discovered_ip_address = re.match(r'http://([\d\.]*)\:{0,1}(\d+)', rokuDevice.location, re.I).group(1)
					self.host_plugin.logger.debug(f"Found IP address of {discovered_ip_address} for serial #{serial_number}")
					self.cached_ip_address = discovered_ip_address
					self.indigoDevice.updateStateOnServer("lastDiscoveredIPAddress", value=discovered_ip_address)
					return discovered_ip_address
			
			# if execution made it through the loop then the device was not found... first attempt
			# to read the last known IP address, then bail with a failure to find
			if self.indigoDevice.states.get("lastDiscoveredIPAddress", "") != "":
				last_known_ip = self.indigoDevice.states.get("lastDiscoveredIPAddress")
				self.host_plugin.logger.debug(f"Using last discovered IP address: {last_known_ip}")
				return last_known_ip
			else:
				self.host_plugin.logger.error(f"IP not found for serial #{serial_number}")
				return ""
		else:
			return self.cached_ip_address

	# endregion
	#######################################################################################
	
	#######################################################################################
	# region Custom Response Handlers
	#######################################################################################
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This callback is made whenever the plugin has received the response to a status
	# request for a Roku device
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def update_device_status_info(self, response_obj, rp_command):
		device_info_doc = xml.etree.ElementTree.fromstring(response_obj)
		
		if device_info_doc.tag == "device-info":
			self.host_plugin.logger.debug("Received device info query response")
			is_powered_on = device_info_doc.find("power-mode").text == 'PowerOn'
			serial_num    = device_info_doc.find("serial-number").text
			device_model  = device_info_doc.find("model-name").text
			is_tv         = device_info_doc.find("is-tv").text
		
			states_to_update = []
			if is_powered_on:
				states_to_update.append({"key": "isPoweredOn", "value": "On"})
			else:
				states_to_update.append({"key": "isPoweredOn", "value": "Off"})
			states_to_update.append({"key" : "serialNumber", "value": serial_num})
			states_to_update.append({"key": "deviceModel", "value": device_model})
			states_to_update.append({"key": "isTV", "value": is_tv})

			# if this device is a TV then we need to perform additional queries in order
			# to pull in the tv/tuner information
			if is_tv == "true":
				self.host_plugin.logger.threaddebug("Queuing TV query commands")
				self.queue_device_command(RPFrameworkCommand(RPFrameworkRESTfulDevice.CMD_RESTFUL_GET, command_payload="http|*|/query/tv-active-channel", parent_action="updateRokuStatus"))
			else:
				states_to_update.append({"key": "activeTunerChannel", "value": "n/a" })

			self.indigoDevice.updateStatesOnServer(states_to_update)

		elif device_info_doc.tag == "active-app":
			try:
				self.host_plugin.logger.debug("Received active app query response")
				app_name = device_info_doc.find("app").text
				screen_saver_on = device_info_doc.find("screensaver")
				
				states_to_update = [{"key": "activeChannel", "value": app_name},
									{"key": "screensaverActive", "value": screen_saver_on is not None}]
				self.indigoDevice.updateStatesOnServer(states_to_update)
			except:
				self.host_plugin.logger.debug("Failed to parse active app query response")
				states_to_update = [{"key": "activeChannel", "value": "-- error --"},
									{"key": "screensaverActive", "value": False}]
				self.indigoDevice.updateStatesOnServer(states_to_update)

		elif device_info_doc.tag == "tv-channel":
			self.host_plugin.logger.debug("Received active channel query response")
			try:
				channel_node = device_info_doc.find("channel")
				if channel_node is None:
					channel_number = ''
				else:
					channel_number = device_info_doc.find("channel").find("number").text
				
				states_to_update = [{"key": "activeTunerChannel", "value": channel_number}]
				self.indigoDevice.updateStatesOnServer(states_to_update)
			except:
				states_to_update = [{"key": "activeTunerChannel", "value": "-- error --"}]
				self.indigoDevice.updateStatesOnServer(states_to_update)
			
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will handle an error as thrown by the REST call... Some Roku devices
	# return an Error 60 / device timeout when off
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def handle_restful_error(self, rp_command, err, response=None):
		if type(err).__name__ == "ConnectionError":
			# update the device to Off and/or offline
			self.host_plugin.logger.debug(f"Failed to contact device {self.indigoDevice.id}; device may be off.")
			self.host_plugin.logger.debug(f"{err}")
			
			states_to_update = [{"key": "activeChannel", "value": ""},
							  	{"key": "screensaverActive", "value": False},
							  	{"key": "isPoweredOn", "value": "Off"}]
			self.indigoDevice.updateStatesOnServer(states_to_update)
		else:	
			super(RokuNetworkRemoteDevice, self).handle_restful_error(rp_command, err, response)

	# endregion
	#######################################################################################
		
	#######################################################################################
	# region Public command-interface functions
	#######################################################################################
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will retrieve a list of the available applications on the connected
	# roku device (it does this synchronously with the expectation that it is called on
	# a concurrent thread when necessary
	# -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def retrieve_app_list(self):
		try:
			# determine the IP address used to connect to the roku device
			device_ip_address = self.get_restful_device_address()
				
			# send a GET to the roku which should result in a list of applications
			# available (in XML format)
			self.host_plugin.logger.debug(f"Sending /query/apps request to {device_ip_address[0]}")
			conn = httplib.HTTPConnection(device_ip_address[0], int(device_ip_address[1]))
			conn.connect()
			conn.putrequest("GET", "/query/apps")
			conn.endheaders()
			
			# read the response to the query
			response_to_rest = conn.getresponse()
			response_status = response_to_rest.status
			body_text       = response_to_rest.read()
			self.host_plugin.logger.threaddebug(f"App list response: {response_status}; body: {body_text}")
			
			# parse out the XML returned which should be in the format of:
			#	<apps>
			#	<app id="[id]">[appname]</app>
			# note that this may not be standard XML... so use a regular expression to parse
			re_app_parser = re.compile(r"\<app id=\"(\d+)\"\s*(?:subtype=\"[\w]+\"){0,1}\s*(?:type=\"[\w]+\"){0,1}\s*version=\"([\d\.]+)\"\>(.*)\</app\>")
			app_matches   = re_app_parser.findall(body_text)
			return app_matches
		except:
			self.host_plugin.exceptionLog()
			return []

	# endregion
	#######################################################################################
