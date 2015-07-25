#! /usr/bin/env python
# -*- coding: utf-8 -*-
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# Roku Network Remote Control by RogueProeliator <rp@rogueproeliator.com>
# 	See plugin.py for more plugin details and information
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////

#/////////////////////////////////////////////////////////////////////////////////////////
# Python imports
#/////////////////////////////////////////////////////////////////////////////////////////
import functools
import httplib
import os
import Queue
import re
import string
import sys
import threading
import telnetlib
import time
import urllib

import indigo
import RPFramework

#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# RokuNetworkRemoteDevice
#	Handles the configuration of a single Roku device that is connected to this plugin;
#	this class does all the 'grunt work' of communications with the Roku
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
class RokuNetworkRemoteDevice(RPFramework.RPFrameworkRESTfulDevice.RPFrameworkRESTfulDevice):

	#/////////////////////////////////////////////////////////////////////////////////////
	# Class construction and destruction methods
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Constructor called once upon plugin class receiving a command to start device
	# communication. The plugin will call other commands when needed, simply zero out the
	# member variables
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def __init__(self, plugin, device):
		super(RokuNetworkRemoteDevice, self).__init__(plugin, device)
		
		# get the device properties; we may need to upgrade users from the old version of
		# addresses to the new version
		devProps = self.indigoDevice.pluginProps
		
		tempRokuIPAddress = devProps.get("rokuIPAddress", "")
		tempRokuSerialNumber = devProps.get("rokuEnumeratedUSN", "")
		if tempRokuIPAddress != "":
			devProps["httpAddress"] = tempRokuIPAddress
			devProps["rokuIPAddress"] = ""
			device.replacePluginPropsOnServer(devProps)
		elif tempRokuSerialNumber != "":
			devProps["httpAddress"] = tempRokuSerialNumber
			devProps["rokuEnumeratedUSN"] = ""
			device.replacePluginPropsOnServer(devProps)
		self.rokuNetworkAddress = devProps.get("httpAddress", "")

		self.cachedIPAddress = ""
		self.hostPlugin.logDebugMessage("Roku Address is " + self.rokuNetworkAddress, RPFramework.RPFrameworkPlugin.DEBUGLEVEL_LOW)

	
	#/////////////////////////////////////////////////////////////////////////////////////
	# Processing and command functions
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will process the commands that are not processed automatically by the
	# base class; it will be called on a concurrent thread
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def handleUnmanagedCommandInQueue(self, deviceHTTPAddress, rpCommand):
		if rpCommand.commandName == "SEND_KEYBOARD_STRING":
			# needs to send a string of text to the roku device as a series of keypress
			# commands (RESTFUL_PUT commands)
			validatedText = re.sub(r'[^a-z\d ]', '', rpCommand.commandPayload.lower())
			if validatedText == "":
				self.hostPlugin.logDebugMessage("Ignoring send text to Roku, validated string is blank (source: " + rpCommand.commandPayload + ")", RPFramework.RPFrameworkPlugin.DEBUGLEVEL_MED)
			else:
				self.hostPlugin.logDebugMessage("Sending keyboard text: " + validatedText, RPFramework.RPFrameworkPlugin.DEBUGLEVEL_HIGH)
				pauseBetweenKeys = float(self.indigoDevice.pluginProps.get("rokuLiteralCommandPause", "0.1"))
				for char in validatedText:
					self.queueDeviceCommand(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/keypress/Lit_" + urllib.quote_plus(char), postCommandPause=pauseBetweenKeys))
		
		elif rpCommand.commandName == "DOWNLOAD_CHANNEL_ICONS":
			# the user has requested that we download all of the icons for channels on the Roku device...
			downloadDestination = rpCommand.commandPayload
			if downloadDestination == None or downloadDestination == "":
				downloadDestination = indigo.server.getInstallFolderPath()
				self.hostPlugin.logDebugMessage("Indigo installation folder: " + downloadDestination, RPFramework.RPFrameworkPlugin.DEBUGLEVEL_MED)
				downloadDestination = os.path.join(downloadDestination, "IndigoWebServer/images/controls/static")
			 
			# retrieve the list of channels/applications and attempt to download
			# each application's icon
			appList = self.retrieveAppList()
			
			for rokuApp in appList:
				iconFile = None
				try:
					applicationId = rokuApp[0]
					applicationName = rokuApp[2]
					
					self.hostPlugin.logDebugMessage("Attempting download of icon for App #" + applicationId + " (" + applicationName + ")", RPFramework.RPFrameworkPlugin.DEBUGLEVEL_MED)
					conn = httplib.HTTPConnection(deviceHTTPAddress[0], deviceHTTPAddress[1])
					conn.connect()
					request = conn.putrequest('GET', '/query/icon/' + applicationId)
					conn.endheaders()
					
					iconResponse = conn.getresponse()
					iconImageExtension = iconResponse.getheader("content-type").replace("image/", "")
					iconImageSaveFN = os.path.join(downloadDestination, "RokuChannelIcon_" + applicationId + "." + iconImageExtension)
					
					self.hostPlugin.logDebugMessage("Saving icon to " + iconImageSaveFN, RPFramework.RPFrameworkPlugin.DEBUGLEVEL_MED)
					iconFile = open(iconImageSaveFN, 'wb')
					iconFile.write(iconResponse.read())
					iconFile.close()
					
					conn.close()
				except:
					if iconFile != None:
						iconFile.close()
					self.hostPlugin.exceptionLog()
				
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine should return the HTTP address that will be used to connect to the
	# RESTful device. It may connect via IP address or a host name
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def getRESTfulDeviceAddress(self):
		self.hostPlugin.logDebugMessage("IP address requested for Roku Device: " + self.rokuNetworkAddress, RPFramework.RPFrameworkPlugin.DEBUGLEVEL_LOW)
			
		# if the ip address has not been filled in then we must look it up by serialNumber
		# via the SSDP service
		if self.hostPlugin.isIPv4Valid(self.rokuNetworkAddress):
			ipAddress = self.rokuNetworkAddress
		else:
			ipAddress = self.obtainRokuIPAddress(self.rokuNetworkAddress)
			
		# return the IP address to the calling procedure...
		return (ipAddress, 8060)
			
			
	#/////////////////////////////////////////////////////////////////////////////////////
	# Private Utility Routines
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will obtain the IP address for a Roku given the serial number; it does
	# this synchronously with the expectation that it is called from a concurrent thread
	# when asynchronous operations are required
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def obtainRokuIPAddress(self, serialNumber):
		if self.cachedIPAddress == "":
			self.hostPlugin.updateUPNPEnumerationList(self.indigoDevice.deviceTypeId)
			rokuList = self.hostPlugin.enumeratedDevices
			for rokuDevice in rokuList:
				enumeratedSerial = string.replace(rokuDevice.usn, 'uuid:roku:ecp:', '')
				if enumeratedSerial == serialNumber:
					discoveredIPAddress = re.match(r'http://([\d\.]*)\:{0,1}(\d+)', rokuDevice.location, re.I).group(1)
					self.hostPlugin.logDebugMessage("Found IP address of " + discoveredIPAddress + " for serial #" + serialNumber, RPFramework.RPFrameworkPlugin.DEBUGLEVEL_MED)
					self.cachedIPAddress = discoveredIPAddress
					self.indigoDevice.updateStateOnServer("lastDiscoveredIPAddress", value=discoveredIPAddress)
					return discoveredIPAddress
			
			# if execution made it through the loop then the device was not found... first attempt
			# to read the last known IP address, then bail with a failure to find
			if self.indigoDevice.states.get("lastDiscoveredIPAddress", "") != "":
				lastKnownIP = self.indigoDevice.states.get("lastDiscoveredIPAddress")
				self.hostPlugin.logDebugMessage("Using last discovered IP address: " + lastKnownIP, RPFramework.RPFrameworkPlugin.DEBUGLEVEL_MED)
				return lastKnownIP
			else:
				self.hostPlugin.logDebugMessage("IP not found for serial #" + serialNumber, RPFramework.RPFrameworkPlugin.DEBUGLEVEL_LOW)
				return ""
		else:
			return self.cachedIPAddress
				
		
	#/////////////////////////////////////////////////////////////////////////////////////
	# Public command-interface functions
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will retrieve a list of the available applications on the connected
	# roku device (it does this synchronously with the expectation that it is called on
	# a concurrent thread when necessary
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def retrieveAppList(self):
		try:
			# determine the IP address used to connect to the roku device
			deviceIPAddress = self.getRESTfulDeviceAddress()
				
			# send a GET to the roku which should result in a list of applications
			# available (in XML format)
			self.hostPlugin.logDebugMessage("Sending /query/apps request to " + deviceIPAddress[0], RPFramework.RPFrameworkPlugin.DEBUGLEVEL_MED)
			conn = httplib.HTTPConnection(deviceIPAddress[0], int(deviceIPAddress[1]))
			conn.connect()
			request = conn.putrequest('GET', "/query/apps")
			conn.endheaders()
			
			# read the response to the query
			responseToREST = conn.getresponse()
			responseStatus = responseToREST.status
			bodyText = responseToREST.read()
			self.hostPlugin.logDebugMessage("App list response: " + str(responseStatus) + "; body: " + bodyText, RPFramework.RPFrameworkPlugin.DEBUGLEVEL_HIGH)
			
			# parse out the XML returned which should be in the format of:
			#	<apps>
			#	<app id="[id]">[appname]</app>
			# note that this may not be standard XML... so use a regular expression to parse
			reAppParser = re.compile("\<app id=\"(\d+)\"\s*(?:type=\"[\w]+\"){0,1}\s*version=\"([\d\.]+)\"\>(.*)\</app\>")
			appMatches = reAppParser.findall(bodyText)
			return appMatches
		except:
			self.hostPlugin.exceptionLog()
			return []
			

	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Send a series of commands to attempt to perform a search on a channel
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def performSearchOnChannel(self, selectedChannel, channelLaunchPause, searchText, stopAtSuggestions):		
		# the search commands depend on the channel being searched... each channel may
		# require special processing; an empty searchText string will result in the user
		# just being brought to the search box
		commands = []
		
		literalPauseTime = float(self.indigoDevice.pluginProps.get("rokuLiteralCommandPause", "0.1"))
		irPauseTime = float(self.indigoDevice.pluginProps.get("rokuIRCommandPause", "0.1"))
		
		# -=-=- LAUNCH SEARCH SCREEN COMMANDS -=-=-
		if selectedChannel == "13":
			# -=-=- AMAZON PRIME -=-=-
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/launch/13"))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkCommand.CMD_PAUSE_PROCESSING, commandPayload=channelLaunchPause))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/keypress/Select"))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkCommand.CMD_PAUSE_PROCESSING, commandPayload="2"))
				
		elif selectedChannel == "12":
			# -=-=- NETFLIX -=-=-
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/launch/12"))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkCommand.CMD_PAUSE_PROCESSING, commandPayload=channelLaunchPause))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/keypress/Search"))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkCommand.CMD_PAUSE_PROCESSING, commandPayload="2"))
		# -=-=- END LAUNCH SEARCH SCREEN COMMANDS -=-=-
				
		# -=-=- ENTER SEARCH STRING COMMANDS -=-=-
		if searchText != "":
			for char in searchText:
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/keypress/Lit_" + urllib.quote_plus(char), postCommandPause=literalPauseTime))
				
		# -=-=- POST SEARCH TERM COMMANDS -=-=-
		if searchText != "":
			if stopAtSuggestions == True:
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/keypress/Right", postCommandPause=irPauseTime))
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/keypress/Right", postCommandPause=irPauseTime))
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/keypress/Right", postCommandPause=irPauseTime))
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/keypress/Right", postCommandPause=irPauseTime))
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/keypress/Right", postCommandPause=irPauseTime))
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/keypress/Right"))
			else:
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload="/keypress/Enter"))
		# -=-=- END POST SEARCH TERM COMMANDS -=-=-
				
		# send the commands to the roku now...
		for cmd in commands:
			self.queueDeviceCommand(cmd)
