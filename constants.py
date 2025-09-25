DEFAULT_BLOCKED = {"left", "right"}
BOSSAC_URL = "https://downloads.arduino.cc/tools/bossac-1.9.1-arduino2-windows.tar.gz"
ARDUINO_CLI_URL = "https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Windows_64bit.zip"
BOARDS = {
    "Arduino Due": {
        "fqbn": "arduino:sam:arduino_due_x",
        "flash": "bossac",
        "ext": ".bin",
    },
    "Arduino Leonardo": {
        "fqbn": "arduino:avr:leonardo",
        "flash": "arduino-cli",
        "ext": ".hex",
    },
}
APP_NAME = "MouseControler - Fizo"
TOOLS_SUBDIR = "tools"
