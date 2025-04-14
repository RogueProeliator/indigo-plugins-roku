#! /usr/bin/env python
# -*- coding: utf-8 -*-
#######################################################################################
# Roku Network Remote Control by RogueProeliator <rp@rogueproeliator.com>
#######################################################################################

# region Python Imports
import os
import re
import requests
import shutil
import urllib.parse
import xml.etree.ElementTree

import indigo
import logging
import queue
import threading
import time
import xml.etree.ElementTree as ET

# endregion


class RokuNetworkRemoteDevice(indigo.Device):

    #######################################################################################
    # region Class construction and destruction methods
    # -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    # Constructor called once upon plugin class receiving a command to start device
    # communication. The plugin will call other commands when needed, simply zero out the
    # member variables
    # -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    def __init__(self, device):
        indigo.Device.__init__(self, device)

        self.logger = logging.getLogger(f"Plugin.Roku.{self.id}")

        self.command_queue = queue.Queue()
        self.command_thread = None
        self.stop_thread = threading.Event()

        self.cached_ip_address = ""
        self.app_list_cache = []
        self.last_app_list_update = 0
        self.plugin = indigo.server.getPlugin(self.pluginId) # Get plugin instance for shared methods/data

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
    # -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    # -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    def deviceStartComm(self):
        self.logger.debug("deviceStartComm called")
        self.stop_thread.clear()
        if not self.command_thread or not self.command_thread.is_alive():
            self.command_thread = threading.Thread(target=self._command_processing_loop)
            self.command_thread.start()
        self.queue_command({'type': 'status_update'}) # Initial status fetch

    def deviceStopComm(self):
        self.logger.debug("deviceStopComm called")
        self.stop_thread.set()
        self.command_queue.put(None) 
        if self.command_thread and self.command_thread.is_alive():
            self.logger.debug("Waiting for command thread to stop...")
            self.command_thread.join(timeout=5.0) # Wait max 5 seconds
            if self.command_thread.is_alive():
                self.logger.warning("Command thread did not stop gracefully.")
            else:
                self.logger.debug("Command thread stopped.")
        self.command_thread = None

    # -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    # -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    def actionControlDevice(self, action):
        self.logger.debug(f"actionControlDevice called: {action.pluginTypeId}")
        
        action_id = action.pluginTypeId
        props = action.props

        if action_id == "remoteButtonToRoku":
            button = props.get("remoteButton", "")
            if button:
                self.queue_command({'type': 'keypress', 'path': f"keypress/{button}"})
            else:
                self.logger.error("Missing 'remoteButton' property for remoteButtonToRoku action.")

        elif action_id == "sendKeyboardString":
            text = props.get("keyboardStringToSend", "")
            if text:
                self.queue_command({'type': 'send_string', 'payload': text})
            else:
                self.logger.error("Missing 'keyboardStringToSend' property for sendKeyboardString action.")

        elif action_id == "launchChannel":
            channel_id = props.get("channelToLaunch", "")
            if channel_id:
                self.queue_command({'type': 'launch', 'path': f"launch/{channel_id}"})
            else:
                self.logger.error("Missing 'channelToLaunch' property for launchChannel action.")
        
        elif action_id == "tuneToStation":
            station_id = props.get("stationToTune", "")
            if station_id:
                 self.queue_command({'type': 'launch', 'path': f"launch/tvinput.dtv?ch={station_id}"})
            else:
                 self.logger.error("Missing 'stationToTune' property for tuneToStation action.")

        elif action_id == "downloadChannelIcons":
            self.queue_command({'type': 'download_icons', 'payload': props.get("iconDownloadPath", "")})

        else:
            self.logger.warning(f"Unhandled actionControlDevice: {action_id}")

    def actionControlGeneral(self, action):
        self.logger.debug(f"actionControlGeneral called: {action.deviceAction}")
        if action.deviceAction == indigo.kDeviceGeneralAction.RequestStatus:
            self.queue_command({'type': 'status_update'})
        else:
            self.logger.warning(f"Unhandled actionControlGeneral: {action.deviceAction}")

    # -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    # -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    def queue_command(self, command_dict):
        """Adds a command dictionary to the processing queue."""
        self.command_queue.put(command_dict)
        self.logger.debug(f"Queued command: {command_dict}")

    def _command_processing_loop(self):
        """Runs in a separate thread, processing commands from the queue."""
        self.logger.debug("Command processing thread started.")
        while not self.stop_thread.is_set():
            try:
                command = self.command_queue.get(timeout=10) # Wait up to 10s for a command
                if command is None: # Sentinel value to stop the thread
                    self.logger.debug("Received stop sentinel.")
                    break 

                self.logger.debug(f"Processing command: {command}")
                command_type = command.get('type')
                
                device_ip, device_port = self._get_device_address()
                if not device_ip:
                    self.logger.error(f"Unable to resolve IP address for device {self.id}. Skipping command: {command}")
                    self.updateStateOnServer("isPoweredOn", "Offline") # Indicate potential issue
                    continue # Skip this command

                base_url = f"http://{device_ip}:{device_port}"

                if command_type == 'status_update':
                    self._send_request(base_url, 'query/device-info', method='GET', command_info=command)
                    self._send_request(base_url, 'query/active-app', method='GET', command_info=command)
                
                elif command_type == 'keypress':
                    path = command.get('path')
                    if path:
                        self._send_request(base_url, path, method='POST', command_info=command)
                    else:
                         self.logger.error(f"Missing 'path' for keypress command: {command}")

                elif command_type == 'launch':
                    path = command.get('path')
                    if path:
                        self._send_request(base_url, path, method='POST', command_info=command)
                    else:
                         self.logger.error(f"Missing 'path' for launch command: {command}")

                elif command_type == 'send_string':
                    text_to_send = command.get('payload', '')
                    validated_text = re.sub(r'[^a-zA-Z0-9 ]', '', text_to_send) # Allow upper/lower case now
                    if validated_text:
                        self.logger.debug(f"Sending keyboard text: '{validated_text}'")
                        pause_between_keys = float(self.pluginProps.get("rokuLiteralCommandPause", "0.1"))
                        for char in validated_text:
                            quoted_char = urllib.parse.quote(char)
                            self._send_request(base_url, f"keypress/Lit_{quoted_char}", method='POST', command_info=command)
                            time.sleep(pause_between_keys) # Pause between keys
                    else:
                        self.logger.warning(f"Ignoring send text to Roku, validated string is blank (source: {text_to_send})")
                
                elif command_type == 'download_icons':
                    self._download_channel_icons(base_url, command.get('payload', ''))

                elif command_type == 'arbitrary': # From plugin.py send_arbitrary_command
                     path = command.get('path')
                     method = command.get('method', 'POST') # Default to POST if not specified
                     if path:
                         self._send_request(base_url, path, method=method, command_info=command)
                     else:
                         self.logger.error(f"Missing 'path' for arbitrary command: {command}")

                elif command_type == 'fetch_app_list': # Internal command if needed
                    self._fetch_and_cache_app_list(base_url)

                else:
                    self.logger.warning(f"Unknown command type received: {command_type}")


            except queue.Empty:
                pass 
            except Exception as e:
                self.logger.exception(f"Error in command processing loop: {e}")
                time.sleep(5) 

        self.logger.debug("Command processing thread finished.")

    def _send_request(self, base_url, path, method='POST', payload=None, command_info=None):
        """Sends an HTTP request to the Roku device."""
        url = f"{base_url}/{path}"
        self.logger.debug(f"Sending {method} request to {url}")
        try:
            if method == 'GET':
                response = requests.get(url, timeout=5) # 5 second timeout
            elif method == 'POST':
                response = requests.post(url, data=payload, timeout=5)
            else:
                self.logger.error(f"Unsupported HTTP method: {method}")
                return

            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            self.logger.debug(f"Response status: {response.status_code}, Content: {response.text[:200]}...") # Log truncated response

            if method == 'GET':
                self._handle_response(response, command_info)

        except requests.exceptions.ConnectionError as e:
            self.logger.warning(f"Connection error contacting {url}: {e}. Device might be offline.")
            self.updateStateOnServer("isPoweredOn", "Offline")
            self.cached_ip_address = "" # Clear cached IP on connection error
        except requests.exceptions.Timeout:
            self.logger.warning(f"Timeout contacting {url}. Device might be offline or slow.")
            self.updateStateOnServer("isPoweredOn", "Offline")
            self.cached_ip_address = "" # Clear cached IP on timeout
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error during {method} request to {url}: {e}")
        except Exception as e:
             self.logger.exception(f"Unexpected error sending request to {url}: {e}")

    def _handle_response(self, response, command_info):
        """Parses XML responses from GET requests."""
        try:
            content_type = response.headers.get('Content-Type', '')
            if 'xml' in content_type:
                response_text = response.text
                self.logger.debug(f"Parsing XML response: {response_text[:200]}...")
                root = ET.fromstring(response_text)
                
                if root.tag == "device-info":
                    self._parse_device_info(root)
                elif root.tag == "active-app":
                    self._parse_active_app(root)
                elif root.tag == "tv-channel":
                     self._parse_tv_channel(root)
                elif root.tag == "apps": # Response from /query/apps
                     self._parse_app_list(root)
                else:
                    self.logger.warning(f"Unhandled XML root tag: {root.tag}")
            else:
                self.logger.debug(f"Received non-XML response (Content-Type: {content_type})")

        except ET.ParseError as e:
            self.logger.error(f"Failed to parse XML response: {e}\nResponse Text: {response.text[:500]}")
        except Exception as e:
            self.logger.exception(f"Error handling response: {e}")

    # -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    # -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    def _get_device_address(self):
        """Resolves the device IP address, using cache or discovery."""
        if self.plugin.is_ip_v4_valid(self.roku_network_address):
            return self.roku_network_address, 8060

        if self.cached_ip_address and self.plugin.is_ip_v4_valid(self.cached_ip_address):
             self.logger.debug(f"Using cached IP: {self.cached_ip_address}")
             return self.cached_ip_address, 8060

        self.logger.info(f"IP address not cached or invalid, attempting discovery for serial: {self.roku_network_address}")
        serial_to_find = self.roku_network_address
        
        
        found_ip = None
        for serial, description in self.plugin.enumerated_roku_devices:
             if serial == serial_to_find:
                 match = re.search(r'\(Currently ([\d\.]+)\)', description)
                 if match:
                     found_ip = match.group(1)
                     self.logger.info(f"Discovered IP {found_ip} for serial {serial_to_find}")
                     break
        
        if found_ip:
            self.cached_ip_address = found_ip
            self.updateStateOnServer("lastDiscoveredIPAddress", value=found_ip)
            return found_ip, 8060
        else:
            last_known_ip = self.states.get("lastDiscoveredIPAddress", "")
            if last_known_ip and self.plugin.is_ip_v4_valid(last_known_ip):
                self.logger.warning(f"Discovery failed for {serial_to_find}, falling back to last known IP: {last_known_ip}")
                self.cached_ip_address = last_known_ip # Cache it again
                return last_known_ip, 8060
            else:
                 self.logger.error(f"Unable to find IP address for Roku device {self.id} (Serial/Address: {self.roku_network_address}).")
                 return None, None

    def _parse_device_info(self, root_element):
        """Parses the /query/device-info XML response."""
        self.logger.debug("Parsing device info")
        states_to_update = []
        try:
            is_powered_on = root_element.findtext("power-mode") == 'PowerOn'
            serial_num    = root_element.findtext("serial-number")
            device_model  = root_element.findtext("model-name")
            is_tv_str     = root_element.findtext("is-tv", "false") # Default to false if missing
            is_tv         = is_tv_str.lower() == 'true'

            states_to_update.append({"key": "isPoweredOn", "value": "On" if is_powered_on else "Off"})
            states_to_update.append({"key": "serialNumber", "value": serial_num})
            states_to_update.append({"key": "deviceModel", "value": device_model})
            states_to_update.append({"key": "isTV", "value": is_tv})

            if is_tv and is_powered_on:
                self.logger.debug("Device is TV, queuing active channel query.")
                device_ip, device_port = self._get_device_address()
                if device_ip:
                     base_url = f"http://{device_ip}:{device_port}"
                     self._send_request(base_url, 'query/tv-active-channel', method='GET')
                else:
                     self.logger.error("Cannot query TV channel, IP address unknown.")
            elif not is_tv:
                states_to_update.append({"key": "activeTunerChannel", "value": "n/a"})

            self.updateStatesOnServer(states_to_update)
            self.updateStateImageOnServer(indigo.kStateImageSel.PowerOn if is_powered_on else indigo.kStateImageSel.PowerOff)

        except Exception as e:
            self.logger.exception(f"Error parsing device-info XML: {e}")

    def _parse_active_app(self, root_element):
        """Parses the /query/active-app XML response."""
        self.logger.debug("Parsing active app info")
        try:
            app_name = root_element.findtext("app", "Unknown") # Default if tag missing
            screensaver_node = root_element.find("screensaver")
            screensaver_active = screensaver_node is not None

            states_to_update = [{"key": "activeChannel", "value": app_name},
                                {"key": "screensaverActive", "value": screensaver_active}]
            self.updateStatesOnServer(states_to_update)
        except Exception as e:
            self.logger.exception(f"Error parsing active-app XML: {e}")
            self.updateStateOnServer("activeChannel", "-- error --")

    def _parse_tv_channel(self, root_element):
         """Parses the /query/tv-active-channel XML response."""
         self.logger.debug("Parsing TV channel info")
         try:
             channel_node = root_element.find("channel")
             channel_number = ""
             if channel_node is not None:
                 channel_number_node = channel_node.find("number")
                 if channel_number_node is not None:
                     channel_number = channel_number_node.text
             
             self.updateStateOnServer("activeTunerChannel", channel_number if channel_number else "None")
         except Exception as e:
             self.logger.exception(f"Error parsing tv-channel XML: {e}")
             self.updateStateOnServer("activeTunerChannel", "-- error --")
             
    def _fetch_and_cache_app_list(self, base_url):
        """Sends request for /query/apps and updates cache."""
        self.logger.debug("Fetching app list...")
        self._send_request(base_url, 'query/apps', method='GET', command_info={'type': 'internal_fetch_apps'})

    def _parse_app_list(self, root_element):
        """Parses the /query/apps XML response and updates cache."""
        self.logger.debug("Parsing app list response")
        new_app_list = []
        try:
            for app_node in root_element.findall("app"):
                app_id = app_node.get("id")
                app_version = app_node.get("version")
                app_name = app_node.text
                if app_id and app_name:
                    new_app_list.append((app_id, app_version, app_name))
                else:
                    self.logger.warning(f"Skipping app with missing id or name: {ET.tostring(app_node, encoding='unicode')}")
            
            self.app_list_cache = sorted(new_app_list, key=lambda x: x[2]) # Sort by name
            self.last_app_list_update = time.time()
            self.logger.info(f"Updated app list cache with {len(self.app_list_cache)} apps.")
        except Exception as e:
            self.logger.exception(f"Error parsing apps XML: {e}")

    def get_cached_app_list(self):
         """Returns the cached app list, fetching if stale."""
         if not self.app_list_cache or (time.time() - self.last_app_list_update > 3600):
             self.logger.info("App list cache is stale or empty, queuing fetch request.")
             self.queue_command({'type': 'fetch_app_list'})
         return self.app_list_cache

    def _download_channel_icons(self, base_url, download_destination_override=""):
        """Downloads icons for all apps in the cache."""
        self.logger.info("Starting channel icon download...")
        
        if not self.app_list_cache:
             self.logger.warning("App list cache is empty. Cannot download icons. Triggering app list fetch.")
             self._fetch_and_cache_app_list(base_url)
             return

        if download_destination_override:
            download_destination = download_destination_override
        else:
            download_destination = os.path.join(indigo.server.getInstallFolderPath(), "IndigoWebServer/images/controls/static")

        if not os.path.exists(download_destination):
             try:
                 os.makedirs(download_destination)
                 self.logger.info(f"Created icon download directory: {download_destination}")
             except OSError as e:
                 self.logger.error(f"Failed to create icon download directory '{download_destination}': {e}")
                 return # Cannot proceed

        self.logger.info(f"Downloading icons to: {download_destination}")
        
        apps_to_download = self.app_list_cache[:] # Copy list
        for app_id, _, app_name in apps_to_download:
            icon_url = f"{base_url}/query/icon/{app_id}"
            self.logger.debug(f"Attempting download of icon for App #{app_id} ({app_name}) from {icon_url}")
            try:
                icon_response = requests.get(icon_url, stream=True, timeout=10)
                icon_response.raise_for_status()

                content_type = icon_response.headers.get('content-type', 'image/png') # Default to png
                extension = content_type.split('/')[-1] if '/' in content_type else 'png'
                save_filename = f"RokuChannelIcon_{app_id}.{extension}"
                save_path = os.path.join(download_destination, save_filename)

                with open(save_path, "wb") as icon_file:
                    for chunk in icon_response.iter_content(chunk_size=8192):
                         icon_file.write(chunk)
                self.logger.debug(f"Saved icon to {save_path}")

            except requests.exceptions.RequestException as e:
                 self.logger.warning(f"Failed to download icon for app {app_id} ({app_name}): {e}")
            except IOError as e:
                 self.logger.error(f"Failed to save icon file for app {app_id} ({app_name}) to {save_path}: {e}")
            except Exception as e:
                 self.logger.exception(f"Unexpected error downloading icon for app {app_id} ({app_name}): {e}")
            
            time.sleep(0.1) 
            
        self.logger.info("Finished channel icon download attempt.")






    # endregion
    #######################################################################################

    #######################################################################################
    # region Processing and command functions
    # endregion
    #######################################################################################

    #######################################################################################
    # region Private Utility Routines
    #######################################################################################
    # endregion
    #######################################################################################

    #######################################################################################
    # region Custom Response Handlers
    #######################################################################################
    # endregion
    #######################################################################################

    #######################################################################################
    # region Public command-interface functions
    #######################################################################################
    # endregion
    #######################################################################################
