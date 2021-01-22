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
import xml.etree.ElementTree
import requests

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
			devProps[u'httpAddress']   = tempRokuIPAddress
			devProps[u'rokuIPAddress'] = u''
			device.replacePluginPropsOnServer(devProps)
		elif tempRokuSerialNumber != u'':
			devProps[u'httpAddress']       = tempRokuSerialNumber
			devProps[u'rokuEnumeratedUSN'] = u''
			device.replacePluginPropsOnServer(devProps)
		self.rokuNetworkAddress = devProps.get(u'httpAddress', u'')

		self.cachedIPAddress = u''
		self.hostPlugin.logger.debug(u'Roku Address is ' + self.rokuNetworkAddress)
		
		# add in updated/new states and properties
		self.upgradedDeviceStates.append(u'isPoweredOn') 
		self.upgradedDeviceStates.append(u'serialNumber')
		self.upgradedDeviceStates.append(u'deviceModel')
		self.upgradedDeviceStates.append(u'isTV')
		self.upgradedDeviceStates.append(u'activeChannel')
		self.upgradedDeviceStates.append(u'screensaverActive')
		self.upgradedDeviceStates.append(u'activeTunerChannel')
		
		self.upgradedDeviceProperties.append((u'updateInterval', '10'))

	
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
				self.hostPlugin.logger.debug(u'Ignoring send text to Roku, validated string is blank (source: {0})'.format(rpCommand.commandPayload))
			else:
				self.hostPlugin.logger.threaddebug(u'Sending keyboard text: {0}'.format(validatedText))
				pauseBetweenKeys = float(self.indigoDevice.pluginProps.get(u'rokuLiteralCommandPause', u'0.1'))
				for char in validatedText:
					self.queueDeviceCommand(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_PUT, commandPayload=u'http|*|/keypress/Lit_' + urllib.quote_plus(char), postCommandPause=pauseBetweenKeys))
		
		elif rpCommand.commandName == u'DOWNLOAD_CHANNEL_ICONS':
			# the user has requested that we download all of the icons for channels on the Roku device...
			downloadDestination = rpCommand.commandPayload
			if downloadDestination == None or downloadDestination == u'':
				downloadDestination = indigo.server.getInstallFolderPath()
				self.hostPlugin.logger.threaddebug(u'Indigo installation folder: {0}'.format(downloadDestination))
				downloadDestination = os.path.join(downloadDestination, u'IndigoWebServer/images/controls/static')
			 
			# retrieve the list of channels/applications and attempt to download
			# each application's icon
			appList = self.retrieveAppList()
			
			for rokuApp in appList:
				iconFile = None
				try:
					applicationId = rokuApp[0]
					applicationName = rokuApp[2]
					
					self.hostPlugin.logger.debug(u'Attempting download of icon for App #{0} ({1})'.format(applicationId, applicationName))
					conn = httplib.HTTPConnection(deviceHTTPAddress[0], deviceHTTPAddress[1])
					conn.connect()
					conn.putrequest(u'GET', u'/query/icon/' + applicationId)
					conn.endheaders()
					
					iconResponse = conn.getresponse()
					iconImageExtension = iconResponse.getheader(u'content-type').replace(u'image/', u'')
					iconImageSaveFN = os.path.join(downloadDestination, u'RokuChannelIcon_' + applicationId + u'.' + iconImageExtension)
					
					self.hostPlugin.logger.debug(u'Saving icon to {0}'.format(iconImageSaveFN))
					iconFile = open(RPFramework.RPFrameworkUtils.to_str(iconImageSaveFN), "wb")
					iconFile.write(iconResponse.read())
					iconFile.close()
					
					conn.close()
				except:
					if iconFile != None:
						iconFile.close()
					self.hostPlugin.exceptionLog()
		else:
			self.hostPlugin.logger.error(u'Received unknown command for device {0}: {1}'.format(self.indigoDevice.id, rpCommand.commandName))
				
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine should return the HTTP address that will be used to connect to the
	# RESTful device. It may connect via IP address or a host name
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def getRESTfulDeviceAddress(self):
		self.hostPlugin.logger.debug(u'IP address requested for Roku Device: {0}'.format(self.rokuNetworkAddress))
			
		# if the ip address has not been filled in then we must look it up by serialNumber
		# via the SSDP service
		if self.hostPlugin.isIPv4Valid(self.rokuNetworkAddress):
			ipAddress = self.rokuNetworkAddress
		else:
			ipAddress = self.obtainRokuIPAddress(self.rokuNetworkAddress)
			
		# return the IP address to the calling procedure...
		return (ipAddress, 8060)
		
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will process any response from the device following the list of
	# response objects defined for this device type. For telnet this will always be
	# a text string
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def handleDeviceTextResponse(self, responseObj, rpCommand):
		# loop through the list of response definitions defined in the (base) class
		# and determine if any match
		responseText = responseObj.content
		for rpResponse in self.hostPlugin.getDeviceResponseDefinitions(self.indigoDevice.deviceTypeId):
			if rpCommand.parentAction is None:
				actionId = ""
			elif isinstance(rpCommand.parentAction, basestring):
				actionId = rpCommand.parentAction
			else:
				actionId = rpCommand.parentAction.indigoActionId

			self.hostPlugin.logger.threaddebug(u'Checking Action {0}  response against {1}'.format(actionId, rpResponse.respondToActionId))
			if rpResponse.isResponseMatch(responseText, rpCommand, self, self.hostPlugin):
				self.hostPlugin.logger.threaddebug(u'Found response match: {0}'.format(rpResponse.responseId))
				rpResponse.executeEffects(responseText, rpCommand, self, self.hostPlugin)
			
			
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
					self.hostPlugin.logger.debug(u'Found IP address of {0} for serial #{1}'.format(discoveredIPAddress, serialNumber))
					self.cachedIPAddress = discoveredIPAddress
					self.indigoDevice.updateStateOnServer(u'lastDiscoveredIPAddress', value=discoveredIPAddress)
					return discoveredIPAddress
			
			# if execution made it through the loop then the device was not found... first attempt
			# to read the last known IP address, then bail with a failure to find
			if self.indigoDevice.states.get(u'lastDiscoveredIPAddress', u'') != u'':
				lastKnownIP = self.indigoDevice.states.get(u'lastDiscoveredIPAddress')
				self.hostPlugin.logger.debug(u'Using last discovered IP address: {0}'.format(lastKnownIP))
				return lastKnownIP
			else:
				self.hostPlugin.logger.error(u'IP not found for serial #{0}'.format(serialNumber))
				return u''
		else:
			return self.cachedIPAddress
			
	
	#/////////////////////////////////////////////////////////////////////////////////////
	# Custom Response Handlers
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This callback is made whenever the plugin has received the response to a status
	# request for a Roku device
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def updateDeviceStatusInfo(self, responseObj, rpCommand):
		deviceInfoDoc = xml.etree.ElementTree.fromstring(responseObj)
		
		if deviceInfoDoc.tag == "device-info":
			self.hostPlugin.logger.debug("Received device info query response")
			isPoweredOn = deviceInfoDoc.find("power-mode").text == 'PowerOn'
			serialNum   = deviceInfoDoc.find("serial-number").text
			deviceModel = deviceInfoDoc.find("model-name").text
			isTv        = deviceInfoDoc.find("is-tv").text
		
			statesToUpdate = []
			if isPoweredOn:
				statesToUpdate.append({ 'key' : u'isPoweredOn', 'value' : 'On' })
			else:
				statesToUpdate.append({ 'key' : u'isPoweredOn', 'value' : 'Off' })
			statesToUpdate.append({ 'key' : u'serialNumber', 'value' : serialNum })
			statesToUpdate.append({ 'key' : u'deviceModel', 'value' : deviceModel })
			statesToUpdate.append({ 'key' : u'isTV', 'value' : isTv })

			# if this device is a TV then we need to perform additional queries in order
			# to pull in the tv/tuner information
			if isTv == "true": 
				self.hostPlugin.logger.threaddebug(u'Queuing TV query commands')
				self.queueDeviceCommand(RPFramework.RPFrameworkCommand.RPFrameworkCommand(RPFramework.RPFrameworkRESTfulDevice.CMD_RESTFUL_GET, commandPayload=u'http|*|/query/tv-active-channel', parentAction=u'updateRokuStatus'))
			else:
				statesToUpdate.append({ u'key' : u'activeTunerChannel', u'value' : u'n/a' })

			self.indigoDevice.updateStatesOnServer(statesToUpdate)

		elif deviceInfoDoc.tag == "active-app":
			try:
				self.hostPlugin.logger.debug("Received active app query response")
				appName = deviceInfoDoc.find("app").text
				screenSaverOn = deviceInfoDoc.find("screensaver")
				
				statesToUpdate = []
				statesToUpdate.append({ u'key' : u'activeChannel', u'value' : appName })
				statesToUpdate.append({ u'key' : u'screensaverActive', u'value' : screenSaverOn is not None })
				self.indigoDevice.updateStatesOnServer(statesToUpdate)
			except:
				self.hostPlugin.logger.debug("Failed to parse active app query response")
				statesToUpdate = []
				statesToUpdate.append({ u'key' : u'activeChannel', u'value' : '-- error --' })
				statesToUpdate.append({ u'key' : u'screensaverActive', u'value' : False })
				self.indigoDevice.updateStatesOnServer(statesToUpdate)

		elif deviceInfoDoc.tag == "tv-channel":
			self.hostPlugin.logger.debug(u"Received active channel query response")
			try:
				channelNode = deviceInfoDoc.find("channel")
				if channelNode is None:
					channelNumber = ''
				else:
					channelNumber = deviceInfoDoc.find("channel").find("number").text
				
				statesToUpdate = []
				statesToUpdate.append({ u'key' : u'activeTunerChannel', u'value' : channelNumber })
				self.indigoDevice.updateStatesOnServer(statesToUpdate)
			except:
				statesToUpdate = []
				statesToUpdate.append({ u'key' : u'activeTunerChannel', u'value' : '-- error --' })
				self.indigoDevice.updateStatesOnServer(statesToUpdate)
			
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine will handle an error as thrown by the REST call... Some Roku devices
	# return an Error 60 / device timeout when off
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-		
	def handleRESTfulError(self, rpCommand, err, response=None):
		if type(err).__name__ == u'ConnectionError':
			# update the device to Off and/or offline
			self.hostPlugin.logger.debug(u'Failed to contact device {0}; device may be off.'.format(self.indigoDevice.id))
			self.hostPlugin.logger.debug(RPFramework.RPFrameworkUtils.to_unicode(err))
			
			statesToUpdate = []
			statesToUpdate.append({ u'key' : u'activeChannel',     u'value' : u'' })
			statesToUpdate.append({ u'key' : u'screensaverActive', u'value' : False })
			statesToUpdate.append({ u'key' : u'isPoweredOn',       u'value' : 'Off' })
			self.indigoDevice.updateStatesOnServer(statesToUpdate)
		else:	
			super(RokuNetworkRemoteDevice, self).handleRESTfulError(rpCommand, err, response)
		
		
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
			conn.putrequest("GET", "/query/apps")
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
			reAppParser = re.compile(r"\<app id=\"(\d+)\"\s*(?:subtype=\"[\w]+\"){0,1}\s*(?:type=\"[\w]+\"){0,1}\s*version=\"([\d\.]+)\"\>(.*)\</app\>")
			appMatches = reAppParser.findall(bodyText)
			return appMatches
		except:
			self.hostPlugin.exceptionLog()
			return []
