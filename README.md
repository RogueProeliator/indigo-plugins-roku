#Introduction
This Indigo 6.1+ plugin allows Indigo to act as a remote control for a network-connected Roku streaming player. All commands/buttons found on the standard remote can be sent to the Roku as well as several additional commands found on the mobile applications.

Note that the protocol exposed by the Roku devices, and utilized by this plugin, does not allow for state information about the Roku to be obtained (such as what current application/channel is active or what screen the Roku is currently showing).

#Hardware Requirements
This plugin should work with any Roku streaming player; you must be on Firmware version 2.8 in order to utilize the plugin's ability to download the channel icons for use on control pages.

The auto-discovery feature requires that the Roku and Indigo server be on the same subnet, though manual IP entry should allow remote control via a WAN interfaces (such as over a VPN connection).

#Installation and Configuration
