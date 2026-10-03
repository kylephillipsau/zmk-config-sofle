# Firmware sources for this config that aren't part of a shield.

# Bluetooth name: replace a stale name stored in settings with the configured one (central only;
# the right half's name is never shown to a host).
if(CONFIG_ZMK_BLE AND CONFIG_BT_DEVICE_NAME_DYNAMIC AND (NOT CONFIG_ZMK_SPLIT OR CONFIG_ZMK_SPLIT_ROLE_CENTRAL))
    target_sources(app PRIVATE src/ble_name.c)
endif()
