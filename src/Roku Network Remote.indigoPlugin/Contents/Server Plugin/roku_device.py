#! /usr/bin/env python
# -*- coding: utf-8 -*-
"""
Roku Device Communication Class

Manages communication with a single Roku device via the External Control Protocol (ECP).
This class handles all HTTP communication, command queuing, and state updates for a
single Roku device or Roku TV.

Command structure based on Roku's External Control Protocol documentation:
https://developer.roku.com/docs/developer-program/debugging/external-control-api.md
"""

# region Python Imports
import os
import re
import shutil
import time
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from queue import Queue, Empty
from typing import Optional, Tuple, List, Any, TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum

import requests
import indigo

if TYPE_CHECKING:
    from plugin import Plugin
# endregion


class CommandType(Enum):
    """Types of commands that can be queued."""
    STATUS_UPDATE = "status_update"
    KEYPRESS = "keypress"
    KEYBOARD_STRING = "keyboard_string"
    LAUNCH_APP = "launch_app"
    TUNE_CHANNEL = "tune_channel"
    DOWNLOAD_ICONS = "download_icons"
    ARBITRARY = "arbitrary"


@dataclass
class Command:
    """A command to be executed on the Roku device."""
    command_type: CommandType
    payload: Any = None
    repeat_count: int = 1


class RokuDevice:
    """
    Manages communication with a single Roku device.
    
    Features:
    - Threaded command processing via queue
    - Status polling
    - Keypress/keyboard input
    - App launching
    - TV tuner control (Roku TV)
    - Channel icon downloads
    
    All commands are queued and processed in a separate thread to avoid
    blocking the main Indigo thread.
    """
    
    ROKU_PORT = 8060
    DEFAULT_TIMEOUT = 5
    MAX_BAD_CALLS = 5

    def __init__(self, plugin: 'Plugin', device: indigo.Device):
        """
        Initialize the Roku device manager.
        
        Args:
            plugin: Reference to the main plugin instance
            device: The Indigo device this manager controls
        """
        self.host_plugin = plugin
        self.device = device
        self.logger = plugin.logger
        
        # Address configuration - can be IP or serial number
        self._address = device.pluginProps.get('httpAddress', '')
        self._cached_ip: str = ''
        
        # Command timing configuration
        self.ir_command_pause = float(device.pluginProps.get('rokuIRCommandPause', '0.3'))
        self.literal_command_pause = float(device.pluginProps.get('rokuLiteralCommandPause', '0.05'))
        
        # Threading infrastructure
        self.queue: Queue = Queue()
        self.thread: Optional[threading.Thread] = None
        self._stop_thread = False
        
        # Status tracking
        self.bad_calls = 0
        self.last_update_time: float = 0
        
        self.logger.debug(f"RokuDevice initialized for {device.name}")

    # ========================================================================
    # region Lifecycle Methods
    # ========================================================================
    def start(self) -> None:
        """Start the device communication thread."""
        self._stop_thread = False
        self.thread = threading.Thread(
            target=self._process_queue,
            name=f"Roku-{self.device.id}",
            daemon=True
        )
        self.thread.start()
        self.logger.debug(f"Device thread started for {self.device.name}")
        
        # Queue an initial status update
        self.queue_status_update()

    def stop(self) -> None:
        """Stop the device communication thread."""
        self._stop_thread = True
        
        # Add a None command to wake up the thread
        self.queue.put(None)
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
            
        self.logger.debug(f"Device thread stopped for {self.device.name}")

    def _process_queue(self) -> None:
        """Main thread loop - processes commands from queue."""
        while not self._stop_thread:
            try:
                command = self.queue.get(timeout=0.5)
                
                if command is None:
                    continue
                
                self._execute_command(command)
                
            except Empty:
                continue
            except Exception as e:
                self.logger.error(f"Error processing queue for {self.device.name}: {e}")

    def _execute_command(self, command: Command) -> None:
        """
        Execute a command from the queue.
        
        Args:
            command: The command to execute
        """
        try:
            if command.command_type == CommandType.STATUS_UPDATE:
                self._do_status_update()
                
            elif command.command_type == CommandType.KEYPRESS:
                key, repeat = command.payload
                self._do_keypress(key, repeat)
                
            elif command.command_type == CommandType.KEYBOARD_STRING:
                self._do_keyboard_string(command.payload)
                
            elif command.command_type == CommandType.LAUNCH_APP:
                self._do_launch_app(command.payload)
                
            elif command.command_type == CommandType.TUNE_CHANNEL:
                self._do_tune_channel(command.payload)
                
            elif command.command_type == CommandType.DOWNLOAD_ICONS:
                self._do_download_icons(command.payload)
                
            elif command.command_type == CommandType.ARBITRARY:
                self._do_arbitrary_command(command.payload)
                
        except Exception as e:
            self.logger.error(f"Error executing {command.command_type}: {e}")
            self._handle_error(e)

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Public Command Methods
    # ========================================================================
    def queue_status_update(self) -> None:
        """Queue a status update command."""
        self.queue.put(Command(CommandType.STATUS_UPDATE))

    def send_keypress(self, key: str, repeat_count: int = 1) -> None:
        """
        Queue a keypress command.
        
        Args:
            key: The key to press (e.g., 'Home', 'Select', 'Up')
            repeat_count: Number of times to repeat the keypress
        """
        self.queue.put(Command(
            CommandType.KEYPRESS,
            payload=(key, repeat_count)
        ))
        self.logger.debug(f"Queued keypress: {key} (x{repeat_count})")

    def send_keyboard_string(self, text: str) -> None:
        """
        Queue a keyboard string command.
        
        Args:
            text: The text to send as keypresses
        """
        self.queue.put(Command(
            CommandType.KEYBOARD_STRING,
            payload=text
        ))
        self.logger.debug(f"Queued keyboard string: {text[:20]}...")

    def launch_app(self, app_id: str) -> None:
        """
        Queue an app launch command.
        
        Args:
            app_id: The Roku app ID to launch
        """
        self.queue.put(Command(
            CommandType.LAUNCH_APP,
            payload=app_id
        ))
        self.logger.debug(f"Queued app launch: {app_id}")

    def tune_channel(self, channel: str) -> None:
        """
        Queue a TV tuner channel command.
        
        Args:
            channel: The channel number to tune to
        """
        self.queue.put(Command(
            CommandType.TUNE_CHANNEL,
            payload=channel
        ))
        self.logger.debug(f"Queued tune channel: {channel}")

    def download_channel_icons(self, destination: str) -> None:
        """
        Queue a channel icons download command.
        
        Args:
            destination: Directory path to save icons
        """
        self.queue.put(Command(
            CommandType.DOWNLOAD_ICONS,
            payload=destination
        ))
        self.logger.debug(f"Queued icon download to: {destination}")

    def send_arbitrary_command(self, command: str) -> None:
        """
        Queue an arbitrary ECP command.
        
        Args:
            command: The raw command path (e.g., '/keypress/Home')
        """
        self.queue.put(Command(
            CommandType.ARBITRARY,
            payload=command
        ))
        self.logger.debug(f"Queued arbitrary command: {command}")

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Command Implementations
    # ========================================================================
    def _do_status_update(self) -> None:
        """Execute status update queries."""
        address = self._get_address()
        if not address:
            return
        
        ip, port = address
        
        # Query device info
        response = self._get(f"http://{ip}:{port}/query/device-info")
        if response:
            self._parse_device_info(response.text)
        
        # Query active app
        response = self._get(f"http://{ip}:{port}/query/active-app")
        if response:
            self._parse_active_app(response.text)
        
        # Query TV channel if this is a Roku TV
        if self.device.states.get("isTV", False):
            response = self._get(f"http://{ip}:{port}/query/tv-active-channel")
            if response:
                self._parse_tv_channel(response.text)
        
        # Query media player state
        response = self._get(f"http://{ip}:{port}/query/media-player")
        if response:
            self._parse_media_player(response.text)
        
        self.last_update_time = time.time()
        self.bad_calls = 0  # Reset on success

    def _do_keypress(self, key: str, repeat_count: int) -> None:
        """Execute keypress command."""
        address = self._get_address()
        if not address:
            return
        
        ip, port = address
        
        for i in range(repeat_count):
            response = self._post(f"http://{ip}:{port}/keypress/{key}")
            if response and response.status_code == 200:
                self.logger.debug(f"Keypress {key} sent successfully")
            else:
                self.logger.warning(f"Keypress {key} may have failed")
            
            if i < repeat_count - 1:
                time.sleep(self.ir_command_pause)

    def _do_keyboard_string(self, text: str) -> None:
        """Execute keyboard string command."""
        address = self._get_address()
        if not address:
            return
        
        ip, port = address
        
        # Filter to valid characters - Roku accepts alphanumeric and some punctuation
        # The original plugin filtered to lowercase alphanumeric and space
        validated_text = re.sub(r'[^a-zA-Z\d ]', '', text)
        
        if not validated_text:
            self.logger.warning(f"No valid characters in text: {text}")
            return
        
        self.logger.debug(f"Sending keyboard text: {validated_text}")
        
        for char in validated_text:
            encoded_char = urllib.parse.quote(char)
            response = self._post(f"http://{ip}:{port}/keypress/Lit_{encoded_char}")
            
            if not response or response.status_code != 200:
                self.logger.warning(f"Failed to send character: {char}")
            
            time.sleep(self.literal_command_pause)

    def _do_launch_app(self, app_id: str) -> None:
        """Execute app launch command."""
        address = self._get_address()
        if not address:
            return
        
        ip, port = address
        
        response = self._post(f"http://{ip}:{port}/launch/{app_id}")
        if response and response.status_code == 200:
            self.logger.info(f"Launched app {app_id}")
        else:
            self.logger.warning(f"Failed to launch app {app_id}")

    def _do_tune_channel(self, channel: str) -> None:
        """Execute TV tuner command."""
        address = self._get_address()
        if not address:
            return
        
        ip, port = address
        
        response = self._post(f"http://{ip}:{port}/launch/tvinput.dtv?ch={channel}")
        if response and response.status_code == 200:
            self.logger.info(f"Tuned to channel {channel}")
        else:
            self.logger.warning(f"Failed to tune to channel {channel}")

    def _do_download_icons(self, destination: str) -> None:
        """Execute channel icon download command."""
        address = self._get_address()
        if not address:
            return
        
        ip, port = address
        
        # Use default destination if not specified
        if not destination:
            destination = os.path.join(
                indigo.server.getInstallFolderPath(),
                "IndigoWebServer/images/controls/static"
            )
        
        # Get app list
        apps = self.get_app_list()
        
        for app_id, version, name in apps:
            icon_file = None
            try:
                self.logger.debug(f"Downloading icon for {name} ({app_id})")
                
                response = requests.get(
                    f"http://{ip}:{port}/query/icon/{app_id}",
                    stream=True,
                    timeout=10
                )
                
                if response.status_code == 200:
                    content_type = response.headers.get("content-type", "image/png")
                    extension = content_type.replace("image/", "")
                    filename = f"RokuChannelIcon_{app_id}.{extension}"
                    filepath = os.path.join(destination, filename)
                    
                    with open(filepath, "wb") as icon_file:
                        response.raw.decode_content = True
                        shutil.copyfileobj(response.raw, icon_file)
                    
                    self.logger.debug(f"Saved icon to {filepath}")
                else:
                    self.logger.warning(f"Failed to download icon for {name}: HTTP {response.status_code}")
                    
            except Exception as e:
                self.logger.error(f"Error downloading icon for {name}: {e}")
            finally:
                if icon_file is not None:
                    try:
                        icon_file.close()
                    except:
                        pass

    def _do_arbitrary_command(self, command: str) -> None:
        """Execute arbitrary command."""
        address = self._get_address()
        if not address:
            return
        
        ip, port = address
        
        # Ensure command starts with /
        if not command.startswith('/'):
            command = '/' + command
        
        # Determine if this is a GET (query) or POST (command) based on path
        if '/query/' in command:
            response = self._get(f"http://{ip}:{port}{command}")
        else:
            response = self._post(f"http://{ip}:{port}{command}")
        
        if response:
            self.logger.info(f"Arbitrary command result: {response.status_code}")
        else:
            self.logger.warning(f"Arbitrary command failed: {command}")

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Query Methods (Synchronous)
    # ========================================================================
    def get_app_list(self) -> List[Tuple[str, str, str]]:
        """
        Get list of installed apps.
        
        This method is synchronous and should be called from a concurrent thread
        when used for action callbacks.
        
        Returns:
            List of (app_id, version, name) tuples
        """
        apps = []
        
        try:
            address = self._get_address()
            if not address:
                return apps
            
            ip, port = address
            
            response = self._get(f"http://{ip}:{port}/query/apps")
            if not response:
                return apps
            
            # Parse XML response
            # Format: <apps><app id="123" version="1.0">App Name</app></apps>
            # Note: May include subtype and type attributes
            re_app_parser = re.compile(
                r'<app id="(\d+)"\s*(?:subtype="[\w]+")?\s*(?:type="[\w]+")?\s*version="([\d\.]+)">(.*?)</app>'
            )
            matches = re_app_parser.findall(response.text)
            
            for app_id, version, name in matches:
                apps.append((app_id, version, name))
                
        except Exception as e:
            self.logger.error(f"Error retrieving app list: {e}")
        
        return apps

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Response Parsers
    # ========================================================================
    def _parse_device_info(self, xml_text: str) -> None:
        """
        Parse device info response and update states.
        
        Args:
            xml_text: XML response from /query/device-info
        """
        try:
            root = ET.fromstring(xml_text)
            
            if root.tag != "device-info":
                return
            
            states_to_update = []
            
            # Power state
            power_mode_elem = root.find("power-mode")
            if power_mode_elem is not None:
                is_powered_on = power_mode_elem.text == 'PowerOn'
                states_to_update.append({
                    "key": "isPoweredOn",
                    "value": is_powered_on,
                    "uiValue": "On" if is_powered_on else "Off"
                })
            
            # Serial number
            serial_elem = root.find("serial-number")
            if serial_elem is not None and serial_elem.text:
                states_to_update.append({
                    "key": "serialNumber",
                    "value": serial_elem.text
                })
            
            # Model
            model_elem = root.find("model-name")
            if model_elem is not None and model_elem.text:
                states_to_update.append({
                    "key": "deviceModel",
                    "value": model_elem.text
                })
            
            # Is TV
            is_tv_elem = root.find("is-tv")
            if is_tv_elem is not None:
                is_tv = is_tv_elem.text == 'true'
                states_to_update.append({
                    "key": "isTV",
                    "value": is_tv
                })
                
                # Set default TV channel state if not a TV
                if not is_tv:
                    states_to_update.append({
                        "key": "activeTunerChannel",
                        "value": "n/a"
                    })
            
            # Batch update states
            if states_to_update:
                self.device.updateStatesOnServer(states_to_update)
            
        except ET.ParseError as e:
            self.logger.error(f"Error parsing device-info XML: {e}")
        except Exception as e:
            self.logger.error(f"Error processing device info: {e}")

    def _parse_active_app(self, xml_text: str) -> None:
        """
        Parse active app response and update states.
        
        Args:
            xml_text: XML response from /query/active-app
        """
        try:
            root = ET.fromstring(xml_text)
            
            if root.tag != "active-app":
                return
            
            states_to_update = []
            
            # Active app name
            app_elem = root.find("app")
            if app_elem is not None:
                app_name = app_elem.text or ""
                states_to_update.append({
                    "key": "activeChannel",
                    "value": app_name
                })
            
            # Screensaver state
            screensaver_elem = root.find("screensaver")
            screensaver_active = screensaver_elem is not None
            states_to_update.append({
                "key": "screensaverActive",
                "value": screensaver_active
            })
            
            # Batch update states
            if states_to_update:
                self.device.updateStatesOnServer(states_to_update)
            
        except ET.ParseError:
            self.logger.debug("Failed to parse active-app response")
            self.device.updateStatesOnServer([
                {"key": "activeChannel", "value": "-- error --"},
                {"key": "screensaverActive", "value": False}
            ])
        except Exception as e:
            self.logger.error(f"Error processing active app: {e}")

    def _parse_tv_channel(self, xml_text: str) -> None:
        """
        Parse TV channel response and update states.
        
        Args:
            xml_text: XML response from /query/tv-active-channel
        """
        try:
            root = ET.fromstring(xml_text)
            
            if root.tag != "tv-channel":
                return
            
            channel_number = ""
            
            channel_node = root.find("channel")
            if channel_node is not None:
                number_elem = channel_node.find("number")
                if number_elem is not None and number_elem.text:
                    channel_number = number_elem.text
            
            self.device.updateStateOnServer("activeTunerChannel", value=channel_number)
            
        except ET.ParseError:
            self.device.updateStateOnServer("activeTunerChannel", value="-- error --")
        except Exception as e:
            self.logger.error(f"Error processing TV channel: {e}")

    def _parse_media_player(self, xml_text: str) -> None:
        """
        Parse media player response and update states.
        
        Args:
            xml_text: XML response from /query/media-player
            
        Example response:
        <player error="false" state="play">
            <plugin bandwidth="44692475 bps" id="dev" name="AppName"/>
            <format audio="aac" captions="none" container="mp4" drm="none" video="mpeg4_15" video_res="1280x546"/>
            <buffering current="1000" max="1000" target="0"/>
            <position>6916 ms</position>
            <duration>887999 ms</duration>
            <is_live>false</is_live>
            <runtime>887999 ms</runtime>
        </player>
        """
        try:
            root = ET.fromstring(xml_text)
            
            if root.tag != "player":
                return
            
            states_to_update = []
            
            # Player state (play, pause, stop, close, etc.)
            player_state = root.get("state", "close")
            player_error = root.get("error", "false") == "true"
            
            if player_error:
                player_state = "error"
            
            states_to_update.append({
                "key": "mediaPlayerState",
                "value": player_state
            })
            
            # Plugin/app info
            plugin_elem = root.find("plugin")
            if plugin_elem is not None:
                app_name = plugin_elem.get("name", "")
                states_to_update.append({
                    "key": "mediaPlayerApp",
                    "value": app_name
                })
            else:
                states_to_update.append({
                    "key": "mediaPlayerApp",
                    "value": ""
                })
            
            # Position (convert from ms to seconds)
            position_elem = root.find("position")
            if position_elem is not None and position_elem.text:
                # Format is "6916 ms" - extract the number
                position_text = position_elem.text.replace(" ms", "").strip()
                try:
                    position_ms = int(position_text)
                    position_sec = position_ms // 1000
                    states_to_update.append({
                        "key": "mediaPositionSeconds",
                        "value": position_sec
                    })
                except ValueError:
                    states_to_update.append({
                        "key": "mediaPositionSeconds",
                        "value": 0
                    })
            else:
                states_to_update.append({
                    "key": "mediaPositionSeconds",
                    "value": 0
                })
            
            # Duration (convert from ms to seconds)
            duration_elem = root.find("duration")
            if duration_elem is not None and duration_elem.text:
                duration_text = duration_elem.text.replace(" ms", "").strip()
                try:
                    duration_ms = int(duration_text)
                    duration_sec = duration_ms // 1000
                    states_to_update.append({
                        "key": "mediaDurationSeconds",
                        "value": duration_sec
                    })
                except ValueError:
                    states_to_update.append({
                        "key": "mediaDurationSeconds",
                        "value": 0
                    })
            else:
                states_to_update.append({
                    "key": "mediaDurationSeconds",
                    "value": 0
                })
            
            # Is live content
            is_live_elem = root.find("is_live")
            if is_live_elem is not None and is_live_elem.text:
                is_live = is_live_elem.text.lower() == "true"
                states_to_update.append({
                    "key": "mediaIsLive",
                    "value": is_live
                })
            else:
                states_to_update.append({
                    "key": "mediaIsLive",
                    "value": False
                })
            
            # Format info
            format_elem = root.find("format")
            if format_elem is not None:
                audio_format = format_elem.get("audio", "")
                video_format = format_elem.get("video", "")
                video_res = format_elem.get("video_res", "")
                
                states_to_update.append({
                    "key": "mediaAudioFormat",
                    "value": audio_format
                })
                states_to_update.append({
                    "key": "mediaVideoFormat",
                    "value": video_format
                })
                states_to_update.append({
                    "key": "mediaVideoResolution",
                    "value": video_res
                })
            else:
                states_to_update.append({"key": "mediaAudioFormat", "value": ""})
                states_to_update.append({"key": "mediaVideoFormat", "value": ""})
                states_to_update.append({"key": "mediaVideoResolution", "value": ""})
            
            # Batch update states
            if states_to_update:
                self.device.updateStatesOnServer(states_to_update)
            
        except ET.ParseError:
            self.logger.debug("Failed to parse media-player response")
            # Set default/empty values on parse error
            self.device.updateStatesOnServer([
                {"key": "mediaPlayerState", "value": "close"},
                {"key": "mediaPlayerApp", "value": ""},
                {"key": "mediaPositionSeconds", "value": 0},
                {"key": "mediaDurationSeconds", "value": 0},
                {"key": "mediaIsLive", "value": False},
                {"key": "mediaAudioFormat", "value": ""},
                {"key": "mediaVideoFormat", "value": ""},
                {"key": "mediaVideoResolution", "value": ""}
            ])
        except Exception as e:
            self.logger.error(f"Error processing media player: {e}")

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region HTTP Methods
    # ========================================================================
    def _get(self, url: str) -> Optional[requests.Response]:
        """
        Perform HTTP GET request.
        
        Args:
            url: Full URL to request
            
        Returns:
            Response object or None on error
        """
        try:
            self.logger.debug(f"HTTP GET: {url}")
            response = requests.get(url, timeout=self.DEFAULT_TIMEOUT)
            return response
        except requests.exceptions.ConnectionError as e:
            self._handle_connection_error(e)
            return None
        except requests.exceptions.Timeout:
            self.logger.warning(f"Timeout connecting to {url}")
            self._handle_error(None)
            return None
        except Exception as e:
            self.logger.error(f"HTTP GET error: {e}")
            self._handle_error(e)
            return None

    def _post(self, url: str, data: str = "") -> Optional[requests.Response]:
        """
        Perform HTTP POST request.
        
        Args:
            url: Full URL to request
            data: Optional POST body
            
        Returns:
            Response object or None on error
        """
        try:
            self.logger.debug(f"HTTP POST: {url} | Data: {data}")
            response = requests.post(url, data=data, timeout=self.DEFAULT_TIMEOUT)
            return response
        except requests.exceptions.ConnectionError as e:
            self._handle_connection_error(e)
            return None
        except requests.exceptions.Timeout:
            self.logger.warning(f"Timeout connecting to {url}")
            self._handle_error(None)
            return None
        except Exception as e:
            self.logger.error(f"HTTP POST error: {e}")
            self._handle_error(e)
            return None

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Address Resolution
    # ========================================================================
    def _get_address(self) -> Optional[Tuple[str, int]]:
        """
        Get the IP address and port for the Roku device.
        
        If the configured address is a serial number, resolves it to an IP
        using UPnP discovery.
        
        Returns:
            Tuple of (ip_address, port) or None if not found
        """
        self.logger.debug(f"IP address requested for Roku Device: {self._address}")
        
        # Check if address is an IP
        if self._is_valid_ip(self._address):
            return (self._address, self.ROKU_PORT)
        
        # Otherwise, treat as serial number and resolve via UPnP
        ip_address = self._obtain_ip_from_serial(self._address)
        if ip_address:
            return (ip_address, self.ROKU_PORT)
        
        return None

    def _obtain_ip_from_serial(self, serial_number: str) -> Optional[str]:
        """
        Resolve a Roku serial number to an IP address via UPnP discovery.
        
        Args:
            serial_number: The Roku device serial number
            
        Returns:
            IP address string or None
        """
        # Check cache first
        if self._cached_ip:
            return self._cached_ip
        
        # Use the plugin's discovery module
        ip_address = self.host_plugin.discovery.resolve_serial_to_ip(serial_number)
        
        if ip_address:
            self.logger.debug(f"Found IP address {ip_address} for serial #{serial_number}")
            self._cached_ip = ip_address
            self.device.updateStateOnServer("lastDiscoveredIPAddress", value=ip_address)
            return ip_address
        
        # Try last known IP address as fallback
        last_known = self.device.states.get("lastDiscoveredIPAddress", "")
        if last_known:
            self.logger.debug(f"Using last known IP address: {last_known}")
            return last_known
        
        self.logger.error(f"IP not found for serial #{serial_number}")
        return None

    @staticmethod
    def _is_valid_ip(address: str) -> bool:
        """
        Check if address is a valid IPv4 address.
        
        Args:
            address: Address string to check
            
        Returns:
            True if valid IPv4 address
        """
        pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if re.match(pattern, address):
            parts = address.split('.')
            return all(0 <= int(part) <= 255 for part in parts)
        return False

    # endregion
    # ========================================================================
    
    # ========================================================================
    # region Error Handling
    # ========================================================================
    def _handle_connection_error(self, error: Exception) -> None:
        """
        Handle connection errors (device may be off).
        
        Args:
            error: The connection error
        """
        self.logger.debug(f"Failed to contact device {self.device.id}; device may be off.")
        self.logger.debug(f"{error}")
        
        # Update device state to indicate offline/off
        self.device.updateStatesOnServer([
            {"key": "activeChannel", "value": ""},
            {"key": "screensaverActive", "value": False},
            {"key": "isPoweredOn", "value": False, "uiValue": "Off"}
        ])
        
        self.bad_calls += 1

    def _handle_error(self, error: Optional[Exception]) -> None:
        """
        Handle general errors.
        
        Args:
            error: The error that occurred
        """
        self.bad_calls += 1
        
        if self.bad_calls >= self.MAX_BAD_CALLS:
            self.logger.warning(
                f"Device {self.device.name} has failed {self.bad_calls} consecutive calls"
            )

    def clear_cached_ip(self) -> None:
        """Clear the cached IP address, forcing re-discovery."""
        self._cached_ip = ''
        self.host_plugin.discovery.clear_cache()

    # endregion
    # ========================================================================
