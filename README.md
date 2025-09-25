# Mouse forwarder

The point of this project is quite easy :

- You plug your arduino programming port inside a scripting computer
- You flash your arduino
- You plug your mouse to the script computer
- You plug the second arduino port to your main computer (do not unplug the programming port from the script computer)
- You press forward
- Mouse movement should be disabled on the script computer and moving on the main computer (even tho the mouse is plugged inside the script computer)

## Troubleshooting

- Board/port: Use a board with native USB (e.g. Arduino Due). Connect the Programming Port to the script PC (serial) and the Native USB Port to the gaming PC (HID).
- Firmware build: Ensure you compile/flash the "Arduino Due (Native USB Port)" variant so the HID Mouse interface is present. In this repo the default board is already set to the native USB variant.
- Device Manager: On the gaming PC, verify that a new "HID-compliant mouse" appears when you plug the Arduino’s native USB port. If not, the HID interface isn’t enumerating (wrong board variant or bad cable/port).
- Quick self-test: Temporarily flash an Arduino Mouse example that moves the cursor on its own to confirm the HID side works, then return to this firmware.
- Serial rate: If you suspect serial stability issues, try lowering the baud rate to 115200 in both the sketch and `serial_sender.py` to test.
