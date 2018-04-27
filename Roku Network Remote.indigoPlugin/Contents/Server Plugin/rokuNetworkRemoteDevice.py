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
		
		tempRokuIPAddress = devProps.get(u'rokuIPAddress', u'')
		tempRokuSerialNumber = devProps.get(u'rokuEnumeratedUSN', u'')
		if tempRokuIPAddress != u'':
			devProps[u'httpAddress'] = tempRokuIPAddress
			devProps[u'rokuIPAddress'] = u''
			device.replacePluginPropsOnServer(devProps)
		elif tempRokuSerialNumber != u'':
			devProps[u'httpAddress'] = tempRokuSerialNumber
			devProps[u'rokuEnumeratedUSN'] = u''
			device.replacePluginPropsOnServer(devProps)
		self.rokuNetworkAddress = devProps.get(u'httpAddress', u'')

		self.cachedIPAddress = u''
		self.hostPlugin.logger.debug(u'Roku Address is ' + self.rokuNetworkAddress)

	
	#/////////////////////////////////////////////////////////////////////////////////////
	# Processing and command functions
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will process the commands that are not processed automatically by the
	# base class; it will be called on a concurrent thread
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def handleUnmanagedCommandInQueue(self, deviceHTTPAddress, rpCommand):
		if rpCommand.commandName == u'SEND_KEYBOARD_STRING':
			# needs to send a string of text to the roku device as a series of keypress
			# commands (RESTFUL_PUT commands)
			validatedText = re.sub(r'[^a-z\d ]', '', rpCommand.commandPayload.lower())
			if validatedText == u'':
				self.hostPlugin.logger.debug(u'Ignoring send text to Roku, validated string is blank (source: ' + rpCommand.commandPayload + u')')
			else:
				self.hostPlugin.logger.threaddebug(u'Sending keyboard text: ' + validatedText)
				pauseBetweenKeys = float(self.indigoDevice.pluginProps.get(u'rokuLiteralCommandPause', u'0.1'))
				for char in validatedText:
					self.queueDeviceCommand(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/keypress/Lit_' + urllib.quote_plus(char), postCommandPause=pauseBetweenKeys))
		
		elif rpCommand.commandName == u'DOWNLOAD_CHANNEL_ICONS':
			# the user has requested that we download all of the icons for channels on the Roku device...
			downloadDestination = rpCommand.commandPayload
			if downloadDestination == None or downloadDestination == u'':
				downloadDestination = indigo.server.getInstallFolderPath()
				self.hostPlugin.logger.threaddebug(u'Indigo installation folder: ' + downloadDestination)
				downloadDestination = os.path.join(downloadDestination, u'IndigoWebServer/images/controls/static')
			 
			# retrieve the list of channels/applications and attempt to download
			# each application's icon
			appList = self.retrieveAppList()
			
			for rokuApp in appList:
				iconFile = None
				try:
					applicationId = rokuApp[0]
					applicationName = rokuApp[2]
					
					self.hostPlugin.logger.debug(u'Attempting download of icon for App #' + applicationId + u' (' + applicationName + u')')
					conn = httplib.HTTPConnection(deviceHTTPAddress[0], deviceHTTPAddress[1])
					conn.connect()
					request = conn.putrequest(u'GET', u'/query/icon/' + applicationId)
					conn.endheaders()
					
					iconResponse = conn.getresponse()
					iconImageExtension = iconResponse.getheader(u'content-type').replace(u'image/', u'')
					iconImageSaveFN = os.path.join(downloadDestination, u'RokuChannelIcon_' + applicationId + u'.' + iconImageExtension)
					
					self.hostPlugin.logger.debug(u'Saving icon to ' + iconImageSaveFN)
					iconFile = open(RPFramework.RPFrameworkUtils.to_str(iconImageSaveFN), "wb")
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
		self.hostPlugin.logger.debug(u'IP address requested for Roku Device: ' + self.rokuNetworkAddress)
			
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
		if self.cachedIPAddress == u'':
			self.hostPlugin.updateUPNPEnumerationList(self.indigoDevice.deviceTypeId)
			rokuList = self.hostPlugin.enumeratedDevices
			for rokuDevice in rokuList:
				enumeratedSerial = string.replace(rokuDevice.usn, 'uuid:roku:ecp:', '')
				if enumeratedSerial == serialNumber:
					discoveredIPAddress = re.match(r'http://([\d\.]*)\:{0,1}(\d+)', rokuDevice.location, re.I).group(1)
					self.hostPlugin.logger.debug(u'Found IP address of ' + discoveredIPAddress + u' for serial #' + serialNumber)
					self.cachedIPAddress = discoveredIPAddress
					self.indigoDevice.updateStateOnServer(u'lastDiscoveredIPAddress', value=discoveredIPAddress)
					return discoveredIPAddress
			
			# if execution made it through the loop then the device was not found... first attempt
			# to read the last known IP address, then bail with a failure to find
			if self.indigoDevice.states.get(u'lastDiscoveredIPAddress', u'') != u'':
				lastKnownIP = self.indigoDevice.states.get(u'lastDiscoveredIPAddress')
				self.hostPlugin.logger.debug(u'Using last discovered IP address: ' + lastKnownIP)
				return lastKnownIP
			else:
				self.hostPlugin.logger.error(u'IP not found for serial #' + serialNumber)
				return u''
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
			self.hostPlugin.logger.debug(u'Sending /query/apps request to ' + deviceIPAddress[0])
			conn = httplib.HTTPConnection(deviceIPAddress[0], int(deviceIPAddress[1]))
			conn.connect()
			request = conn.putrequest("GET", "/query/apps")
			conn.endheaders()
			
			# read the response to the query
			responseToREST = conn.getresponse()
			responseStatus = responseToREST.status
			bodyText = responseToREST.read()
			self.hostPlugin.logger.threaddebug(u'App list response: ' + RPFramework.RPFrameworkUtils.to_unicode(responseStatus) + u'; body: ' + RPFramework.RPFrameworkUtils.to_unicode(bodyText))
			
			# parse out the XML returned which should be in the format of:
			#	<apps>
			#	<app id="[id]">[appname]</app>
			# note that this may not be standard XML... so use a regular expression to parse
			reAppParser = re.compile("\<app id=\"(\d+)\"\s*(?:subtype=\"[\w]+\"){0,1}\s*(?:type=\"[\w]+\"){0,1}\s*version=\"([\d\.]+)\"\>(.*)\</app\>")
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
		
		literalPauseTime = float(self.indigoDevice.pluginProps.get(u'rokuLiteralCommandPause', u'0.1'))
		irPauseTime = float(self.indigoDevice.pluginProps.get(u'rokuIRCommandPause', u'0.1'))
		
		# -=-=- LAUNCH SEARCH SCREEN COMMANDS -=-=-
		if selectedChannel == u'13':
			# -=-=- AMAZON PRIME -=-=-
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/launch/13'))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkCommand.CMD_PAUSE_PROCESSING, commandPayload=channelLaunchPause))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/keypress/Select'))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkCommand.CMD_PAUSE_PROCESSING, commandPayload=u'2'))
				
		elif selectedChannel == u'12':
			# -=-=- NETFLIX -=-=-
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/launch/12'))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkCommand.CMD_PAUSE_PROCESSING, commandPayload=channelLaunchPause))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/keypress/Search'))
			commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkCommand.CMD_PAUSE_PROCESSING, commandPayload=u'2'))
		# -=-=- END LAUNCH SEARCH SCREEN COMMANDS -=-=-
				
		# -=-=- ENTER SEARCH STRING COMMANDS -=-=-
		if searchText != u'':
			for char in searchText:
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'/keypress/Lit_' + urllib.quote_plus(char), postCommandPause=literalPauseTime))
				
		# -=-=- POST SEARCH TERM COMMANDS -=-=-
		if searchText != "":
			if stopAtSuggestions == True:
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/keypress/Right', postCommandPause=irPauseTime))
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/keypress/Right', postCommandPause=irPauseTime))
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/keypress/Right', postCommandPause=irPauseTime))
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/keypress/Right', postCommandPause=irPauseTime))
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/keypress/Right', postCommandPause=irPauseTime))
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/keypress/Right'))
			else:
				commands.append(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/keypress/Enter'))
		# -=-=- END POST SEARCH TERM COMMANDS -=-=-
				
		# send the commands to the roku now...
		for cmd in commands:
			self.queueDeviceCommand(cmd)
