# Roku Network Remote Plugin for Indigo

Control your Roku streaming devices and Roku TVs from Indigo Home Automation.

## Version 2025.1.0

This is a complete rewrite of the Roku Network Remote plugin for Indigo 2025.1, removing the dependency on RPFramework and bringing the codebase inline with modern Indigo plugin standards.

## Features

- **Automatic Device Discovery** - Find Roku devices on your network via UPnP/SSDP
- **Remote Control** - Send any button press from the Roku remote
- **Keyboard Input** - Send text strings for search and input fields
- **App Launching** - Launch any installed channel/app
- **TV Tuner Control** - Set channels on Roku TV devices
- **Status Monitoring** - Track power state, current app, current media, and TV channel
- **Channel Icons** - Download app icons for use in Control Pages

## Requirements

- Indigo 2025.1 or later
- Python 3.10+ (included with Indigo)
- Network access to Roku device(s)

## Installation

1. Download the latest release
2. Double-click the `.indigoPlugin` file to install
3. Enable the plugin in Indigo

## API Reference

This plugin uses Roku's External Control Protocol (ECP):
https://developer.roku.com/docs/developer-program/debugging/external-control-api.md

## Support

For issues and feature requests, please visit:
https://github.com/RogueProeliator/indigo-plugins-roku

## License

MIT License - See LICENSE.txt for details.

## Credits

Developed by RogueProeliator <rp@rogueproeliator.com>

Rewritten for Indigo 2025.1 without RPFramework dependency.
