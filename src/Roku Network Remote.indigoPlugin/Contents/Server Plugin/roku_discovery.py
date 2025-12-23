#! /usr/bin/env python
# -*- coding: utf-8 -*-
"""
Roku UPnP Discovery Module

Implements SSDP (Simple Service Discovery Protocol) to find Roku devices on the local network.
Roku devices respond to SSDP M-SEARCH requests with their location URL and USN containing
their serial number.
"""

# region Python Imports
import re
import socket
import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
import logging
# endregion


@dataclass
class RokuInfo:
    """Information about a discovered Roku device."""
    serial_number: str
    ip_address: str
    port: int
    location: str
    usn: str  # Full USN string


class RokuDiscovery:
    """
    UPnP SSDP discovery for Roku devices.
    
    Roku devices respond to SSDP M-SEARCH requests with their location URL
    and a USN (Unique Service Name) that contains their serial number.
    
    Example USN: uuid:roku:ecp:YN00H12345678
    Example Location: http://192.168.1.100:8060/
    """
    
    # SSDP multicast address and port
    SSDP_ADDR = '239.255.255.250'
    SSDP_PORT = 1900
    
    # Roku-specific URN
    ROKU_URN = 'roku:ecp'
    
    # Default timeouts
    DEFAULT_TIMEOUT = 5.0
    CACHE_TIMEOUT = 300  # 5 minutes

    def __init__(self, logger: logging.Logger):
        """
        Initialize the discovery module.
        
        Args:
            logger: Logger instance from the plugin
        """
        self.logger = logger
        
        # Cache for discovered devices
        self._cache: Dict[str, RokuInfo] = {}
        self._cache_time: float = 0

    def discover_devices(self, timeout: float = DEFAULT_TIMEOUT) -> List[RokuInfo]:
        """
        Discover Roku devices on the local network using SSDP.
        
        Args:
            timeout: How long to wait for responses (seconds)
            
        Returns:
            List of RokuInfo objects for discovered devices
        """
        devices: List[RokuInfo] = []
        
        # Build M-SEARCH request
        search_request = self._build_search_request()
        
        sock = None
        try:
            # Create UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout)
            
            # Send multicast search request
            self.logger.debug(f"Sending SSDP search for {self.ROKU_URN}")
            sock.sendto(
                search_request.encode('utf-8'),
                (self.SSDP_ADDR, self.SSDP_PORT)
            )
            
            # Collect responses
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    response, addr = sock.recvfrom(4096)
                    response_text = response.decode('utf-8', errors='ignore')
                    
                    self.logger.debug(f"SSDP response from {addr[0]}")
                    
                    # Parse the response
                    roku_info = self._parse_response(response_text)
                    if roku_info:
                        # Check for duplicate
                        if not any(d.serial_number == roku_info.serial_number for d in devices):
                            devices.append(roku_info)
                            self.logger.info(
                                f"Found Roku: {roku_info.serial_number} at {roku_info.ip_address}"
                            )
                            
                except socket.timeout:
                    break
                except Exception as e:
                    self.logger.debug(f"Error receiving SSDP response: {e}")
                    continue
            
        except Exception as e:
            self.logger.error(f"SSDP discovery error: {e}")
        finally:
            if sock:
                try:
                    sock.close()
                except:
                    pass
        
        # Update cache
        self._update_cache(devices)
        
        return devices

    def resolve_serial_to_ip(self, serial_number: str) -> Optional[str]:
        """
        Resolve a Roku serial number to an IP address.
        
        First checks cache, then performs discovery if needed.
        
        Args:
            serial_number: The Roku device serial number
            
        Returns:
            IP address string, or None if not found
        """
        # Check cache first
        if self._is_cache_valid():
            if serial_number in self._cache:
                cached = self._cache[serial_number]
                self.logger.debug(f"Using cached IP for {serial_number}: {cached.ip_address}")
                return cached.ip_address
        
        # Perform discovery
        self.logger.debug(f"Cache miss for {serial_number}, performing discovery")
        devices = self.discover_devices()
        
        # Search results
        for device in devices:
            if device.serial_number == serial_number:
                return device.ip_address
        
        self.logger.warning(f"Serial number {serial_number} not found on network")
        return None

    def _build_search_request(self) -> str:
        """
        Build an SSDP M-SEARCH request.
        
        Returns:
            The M-SEARCH request string
        """
        return (
            f"M-SEARCH * HTTP/1.1\r\n"
            f"HOST: {self.SSDP_ADDR}:{self.SSDP_PORT}\r\n"
            f"MAN: \"ssdp:discover\"\r\n"
            f"MX: 3\r\n"
            f"ST: {self.ROKU_URN}\r\n"
            f"\r\n"
        )

    def _parse_response(self, response_text: str) -> Optional[RokuInfo]:
        """
        Parse an SSDP response into RokuInfo.
        
        Args:
            response_text: The raw SSDP response
            
        Returns:
            RokuInfo object or None if parsing fails
        """
        try:
            # Check if this is a Roku device response
            if self.ROKU_URN not in response_text.lower():
                return None
            
            # Extract headers
            headers = self._parse_headers(response_text)
            
            location = headers.get('location', headers.get('LOCATION', ''))
            usn = headers.get('usn', headers.get('USN', ''))
            
            if not location or not usn:
                return None
            
            # Parse location URL for IP and port
            ip_address, port = self._parse_location(location)
            if not ip_address:
                return None
            
            # Parse USN for serial number
            serial_number = self._parse_usn(usn)
            if not serial_number:
                return None
            
            return RokuInfo(
                serial_number=serial_number,
                ip_address=ip_address,
                port=port,
                location=location,
                usn=usn
            )
            
        except Exception as e:
            self.logger.debug(f"Error parsing SSDP response: {e}")
            return None

    def _parse_headers(self, response_text: str) -> Dict[str, str]:
        """
        Parse HTTP headers from response text.
        
        Args:
            response_text: Raw HTTP response
            
        Returns:
            Dictionary of header names to values
        """
        headers = {}
        lines = response_text.split('\r\n')
        
        for line in lines[1:]:  # Skip status line
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip().lower()] = value.strip()
        
        return headers

    def _parse_location(self, location: str) -> Tuple[Optional[str], int]:
        """
        Parse IP address and port from SSDP location URL.
        
        Args:
            location: Location URL (e.g., 'http://192.168.1.100:8060/')
            
        Returns:
            Tuple of (ip_address, port) or (None, 0) on failure
        """
        # Pattern to match http://IP:PORT/
        pattern = r'http://(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):?(\d+)?/?'
        match = re.match(pattern, location, re.IGNORECASE)
        
        if match:
            ip = match.group(1)
            port = int(match.group(2)) if match.group(2) else 8060
            return (ip, port)
        
        return (None, 0)

    def _parse_usn(self, usn: str) -> Optional[str]:
        """
        Parse serial number from USN string.
        
        Args:
            usn: USN string (e.g., 'uuid:roku:ecp:YN00H12345678')
            
        Returns:
            Serial number string or None
        """
        # USN format: uuid:roku:ecp:SERIALNUMBER
        usn_lower = usn.lower()
        
        if 'uuid:roku:ecp:' in usn_lower:
            # Extract everything after the prefix
            parts = usn.split(':')
            if len(parts) >= 4:
                return parts[3]
        
        return None

    def _update_cache(self, devices: List[RokuInfo]) -> None:
        """
        Update the device cache.
        
        Args:
            devices: List of discovered devices
        """
        self._cache.clear()
        for device in devices:
            self._cache[device.serial_number] = device
        self._cache_time = time.time()

    def _is_cache_valid(self) -> bool:
        """
        Check if the cache is still valid.
        
        Returns:
            True if cache is valid
        """
        if not self._cache:
            return False
        return (time.time() - self._cache_time) < self.CACHE_TIMEOUT

    def clear_cache(self) -> None:
        """Clear the device cache."""
        self._cache.clear()
        self._cache_time = 0


# ============================================================================
# Stand-alone testing
# ============================================================================
if __name__ == '__main__':
    """Test discovery when run directly."""
    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    
    # Create discovery instance
    discovery = RokuDiscovery(logger)
    
    # Run discovery
    print("Searching for Roku devices...")
    devices = discovery.discover_devices(timeout=10)
    
    if devices:
        print(f"\nFound {len(devices)} device(s):")
        for device in devices:
            print(f"  Serial: {device.serial_number}")
            print(f"  IP: {device.ip_address}:{device.port}")
            print(f"  Location: {device.location}")
            print()
    else:
        print("No Roku devices found.")
