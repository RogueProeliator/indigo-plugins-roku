#Introduction
This Indigo 6.1+ plugin allows Indigo to act as a remote control for a network-connected Roku streaming player. All commands/buttons found on the standard remote can be sent to the Roku as well as several additional commands found on the mobile applications.

Note that the protocol exposed by the Roku devices, and utilized by this plugin, does not allow for state information about the Roku to be obtained (such as what current application/channel is active or what screen the Roku is currently showing).

_**INDIGO 6 IMPORTANT NOTE:**_ The Indigo 6 version of this plugin is end-of-life with respect to new development, however the latest stable version on Indigo 6 is [still available](https://github.com/RogueProeliator/IndigoPlugins-Roku-Network-Remote/releases/tag/v1.6.19) on the releases page and is working as expected at the moment. Please consider an upgrade to Indigo 7 to support further development of our favorite HA platform!

#Hardware Requirements
This plugin should work with any Roku streaming player; you must be on Firmware version 2.8 in order to utilize the plugin's ability to download the channel icons for use on control pages.

The auto-discovery feature requires that the Roku and Indigo server be on the same subnet, though manual IP entry should allow remote control via a WAN interfaces (such as over a VPN connection).

#Installation and Configuration
###Obtaining the Plugin
The latest released version of the plugin is available for download in the GitHub Releases section... those versions in beta will be marked as a Pre-Release and will not appear in update notifications. Once installed, you may use the Check for Updates option in the plugin's menu to check for and download updates.

###Configuring the Plugin
Upon first installation you will be asked to configure the plugin; please see the instructions on the configuration screen for more information. Most users will be fine with the defaults unless an email is desired when a new version is released.
![](<Documentation/Doc-Images/PluginConfigurationScreen.png>)

#Plugin Devices
When creating (or editing a device), in the Device Settings you will need to select from the list of Roku devices found on the network or else manually enter your Roku's IP address. Note that if you ever lose connection with your Roku device, you may need to return here to find/enter the IP Address again if it has picked up a new address on the network (the plugin will attempt to find the IP address if it or the server is restarted). Please read the other configuration instructions shown on screen as you may be able to adjust to optimize the performance of your Roku hardware.
![](<Documentation/Doc-Images/EditDeviceSettings.png>)

#Available Actions
###Send Button Press
This action will send a network command that is equivalent to pressing the button on the remote (some buttons included are not found on the physical remote, but usually included in the mobile apps).

###Send Keyboard Text
This action will send text to the Roku as if it had been typed in via the onscreen keyboard or the mobile application's keyboard. Only alphanumerics and a handful of punctuation are currently supported.

###Launch Channel/Application
This action will launch a particular channel on your Roku. Note that the list of available channels is loaded from your Roku device itself, so adding a new channel from the channel store will automatically add it to the list of channels from which you may choose in the action configuration dialog.

###Perform Search on Channel
This action will allow you to launch and perform a search on a channel in one step. It is currently only able to implement this as a series of keystrokes sent in a timed fashion to the Roku device and so care/testing is needed to ensure it works for you; you may leave the search text blank in order to navigate to the search screen but not actually perform a search. Roku has allowed some channels to be searched through ECP and the hope is that they will expand the offering; when/if this occurs the plugin will be updated to provide access to an integrated search method without relying on keystrokes.

###Download Channel Icons
This action will download all of the channel icons from the Roku (for channels currently added to the box). These will be saved in the format provided by the Roku devices (generally PNG, though JPG is an allowed format). The default directory is to the static images directory used by the Control Page Editor; however, you may override this in the action's settings dialog.
