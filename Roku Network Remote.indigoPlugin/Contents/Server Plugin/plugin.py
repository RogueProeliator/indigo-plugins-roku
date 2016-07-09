#! /usr/bin/env python
# -*- coding: utf-8 -*-
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# Roku Network Remote Control by RogueProeliator <rp@rogueproeliator.com>
# 	Indigo plugin designed to allow control of Roku devices via control pages using
#	Roku's built-in External Control Protocol (ECP) interface
#	
#	Command structure based on Roku's documentation:
#	http://sdkdocs.roku.com/display/sdkdoc/External+Control+Guide
#
#	Version 1.0:
#		* Initial release of the plugin to Indigo users
#	Version 1.1:
#		* Integrated plugin into the RPFramewrok
#		* Changed network addressing to a single device property; devices should auto
#		  upgrade to the new format
#		* Changed post-command delays to only fire when multiple commands are fired
#		* Updated post-command delays with shorter defaults
#	Version 1.2:
#		* Fixed bug with downloading channel icons
#	Version 1.3:
#		* Updated application list parser to work with newest Roku 3 software
#	Version 1.4:
#		* Lowered case text sent to Roku so it all passes validation
#		* Reduced wait time when the queue is empty after a command has executed
#
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////


#/////////////////////////////////////////////////////////////////////////////////////////
# Python imports
#/////////////////////////////////////////////////////////////////////////////////////////
import random
import re
import select
import socket
import string
import telnetlib
import urllib
import os

import RPFramework
import rokuNetworkRemoteDevice

#/////////////////////////////////////////////////////////////////////////////////////////
# Constants and configuration variables
#/////////////////////////////////////////////////////////////////////////////////////////


#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
# Plugin
#	Primary Indigo plugin class that is universal for all devices (Roku instances) to be
#	controlled
#/////////////////////////////////////////////////////////////////////////////////////////
#/////////////////////////////////////////////////////////////////////////////////////////
class Plugin(RPFramework.RPFrameworkPlugin.RPFrameworkPlugin):

	#/////////////////////////////////////////////////////////////////////////////////////
	# Class construction and destruction methods
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Constructor called once upon plugin class creation; setup the device tracking
	# variables for later use
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		# RP framework base class's init method
		super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs, managedDeviceClassModule=rokuNetworkRemoteDevice)
		
		# create a list that will hold a cached version of the list of roku hardware
		# devices found on the network
		self.enumeratedRokuDevices = []
		
		
	#/////////////////////////////////////////////////////////////////////////////////////
	# Data Validation functions... these functions allow the plugin or devices to validate
	# user input
	#/////////////////////////////////////////////////////////////////////////////////////		
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine is called to parse out a uPNP search results list in order to createDeviceObject
	# an indigo-friendly menu; usually will be overridden in plugin descendants
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-	
	def parseUPNPDeviceList(self, deviceList):
		try:
			rokuOptions = []
		
			for rokuDevice in deviceList:
				serialNumber = string.replace(rokuDevice.usn, 'uuid:roku:ecp:', '')
				ipAddress = re.match(r'http://([\d\.]*)\:{0,1}(\d+)', rokuDevice.location, re.I)
				rokuOptions.append((RPFramework.RPFrameworkUtils.to_unicode(serialNumber), u'Serial #' + RPFramework.RPFrameworkUtils.to_unicode(serialNumber) + u' (Currently ' + RPFramework.RPFrameworkUtils.to_unicode(ipAddress.group(1)) + u')'))
			return rokuOptions
			
		except:
			if self.debugLevel == RPFramework.RPFrameworkPlugin.DEBUGLEVEL_HIGH:
				self.exceptionLog()
			return []	
	
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine is called back to the plugin when the GUI action loads that allows
	# launching a channel
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def retrieveRokuApps(self, filter=u'', valuesDict=None, typeId=u'', targetId=0):
		try:
			# use the roku device to retrieve the list of available applications
			availableApps = self.managedDevices[targetId].retrieveAppList()
			appOptions = []
			
			for rokuApp in availableApps:
				appId = rokuApp[0]
				appVersion = rokuApp[1]
				appName = rokuApp[2]
				
				appOptions.append((appId, appName))
			
			return sorted(appOptions, key=lambda option: option[1])
		except:
			self.exceptionLog()
			return []
			
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# This routine is called back to the plugin when the GUI action loads that allows
	# launching a channel that will be searched
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def retrieveSearchableRokuApps(self, filter=u'', valuesDict=None, typeId=u'', targetId=0):
		appsList = self.retrieveRokuApps(filter, valuesDict, typeId, targetId)
		searchableAppsList = []
		
		for rokuApp in appsList:
			if rokuApp[0] == u'13' or rokuApp[0] == u'12':
				searchableAppsList.append(rokuApp)
				
		return searchableAppsList
	

	#/////////////////////////////////////////////////////////////////////////////////////
	# Actions object callback handlers/routines
	#/////////////////////////////////////////////////////////////////////////////////////
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	# Send a series of commands to attempt to perform a search on a channel
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
	def performSearchOnChannel(self, pluginAction):
		dev = indigo.devices[pluginAction.deviceId]
		selectedChannel = pluginAction.props.get(u'rokuAppId')
		searchText = pluginAction.props.get(u'searchText', u'')
		
		launchChannelPause = u'5'
		stopAtSuggestions = False
		if selectedChannel == u'12':
			launchChannelPause = pluginAction.props.get(u'netflixPauseForLaunch', u'9')
			stopAtSuggestions = pluginAction.props.get("netflixStopAtSuggestions", False)
		elif selectedChannel == u'13':
			launchChannelPause = pluginAction.props.get(u'amazonPauseForLaunch', u'6.5')
			stopAtSuggestions = pluginAction.props.get(u'amazonStopAtSuggestions', False)
		
		self.managedDevices[dev.id].performSearchOnChannel(selectedChannel, launchChannelPause, searchText, stopAtSuggestions)

	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-	
	# This routine will be called from the user executing the menu item action to send
	# an arbitrary command code to the Onkyo receiver
	#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-	
	def sendArbitraryCommand(self, valuesDict, typeId):
		try:
			deviceId = valuesDict.get(u'targetDevice', u'0')
			commandCode = valuesDict.get(u'commandToSend', u'').strip()
		
			if deviceId == u'' or deviceId == u'0':
				# no device was selected
				errorDict = indigo.Dict()
				errorDict[u'targetDevice'] = u'Please select a device'
				return (False, valuesDict, errorDict)
			elif commandCode == u'':
				errorDict = indigo.Dict()
				errorDict[u'commandToSend'] = u'Enter command to send'
				return (False, valuesDict, errorDict)
			else:
				# send the code using the normal action processing...
				actionParams = indigo.Dict()
				actionParams[u'commandCode'] = commandCode
				self.executeAction(pluginAction=None, indigoActionId=u'sendArbitraryCommand', indigoDeviceId=int(deviceId), paramValues=actionParams)
				return (True, valuesDict)
		except:
			self.exceptionLog()
			return (False, valuesDict)	
	