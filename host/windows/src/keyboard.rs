//! The keyboard's raw HID interface: finding it and writing reports to it.
//!
//! The keyboard has an ordinary keyboard interface too, but Windows doesn't let apps write to it: it
//! refuses both output report calls, over Bluetooth at least. A vendor-defined interface is fair
//! game, so the left half has one (zmk-raw-hid), and the firmware reads its reports as light reports.

use std::fmt;
use std::mem::{size_of, zeroed};
use std::ptr::{addr_of, null, null_mut};
use std::time::Instant;

use windows_sys::Win32::Devices::DeviceAndDriverInstallation::{
    CM_Get_DevNode_PropertyW, CM_Get_Device_IDW, CM_Get_Parent, CR_SUCCESS, DIGCF_DEVICEINTERFACE,
    DIGCF_PRESENT, HDEVINFO, MAX_DEVICE_ID_LEN, SP_DEVICE_INTERFACE_DATA,
    SP_DEVICE_INTERFACE_DETAIL_DATA_W, SP_DEVINFO_DATA, SetupDiDestroyDeviceInfoList,
    SetupDiEnumDeviceInterfaces, SetupDiGetClassDevsW, SetupDiGetDeviceInterfaceDetailW,
};
use windows_sys::Win32::Devices::HumanInterfaceDevice::{
    HIDP_CAPS, HIDP_STATUS_SUCCESS, HidD_FreePreparsedData, HidD_GetHidGuid, HidD_GetPreparsedData,
    HidD_GetProductString, HidD_SetOutputReport, HidP_GetCaps, PHIDP_PREPARSED_DATA,
};
use windows_sys::Win32::Devices::Properties::{
    DEVPKEY_Device_LastArrivalDate, DEVPKEY_NAME, DEVPROP_TYPE_BOOLEAN, DEVPROP_TYPE_FILETIME,
    DEVPROP_TYPE_STRING, DEVPROPTYPE,
};
use windows_sys::Win32::Foundation::{
    CloseHandle, DEVPROPKEY, GENERIC_READ, GENERIC_WRITE, HANDLE, INVALID_HANDLE_VALUE,
    WAIT_ABANDONED, WAIT_OBJECT_0,
};
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING,
};
use windows_sys::Win32::System::Threading::{
    CreateMutexW, INFINITE, ReleaseMutex, WaitForSingleObject,
};
use windows_sys::core::GUID;

use crate::{PRODUCT, SEND_LOCK, log, warn};

// zmk-raw-hid's defaults (CONFIG_RAW_HID_USAGE_PAGE and CONFIG_RAW_HID_USAGE)
const RAW_USAGE_PAGE: u16 = 0xff60;
const RAW_USAGE: u16 = 0x61;
// ZMK's vendor and product IDs, over USB and Bluetooth. Every ZMK keyboard has them, so the
// product name decides.
const VENDOR_ID: &str = "1D50";
const PRODUCT_ID: &str = "615E";
// The bytes in each HID report (CONFIG_RAW_HID_REPORT_SIZE), for `encode --raw`; sending asks the
// interface.
pub const RAW_REPORT_SIZE: usize = 32;

// Bluetooth device properties windows-sys doesn't name
const DEVPKEY_BLUETOOTH_LAST_CONNECTED_TIME: DEVPROPKEY = DEVPROPKEY {
    fmtid: GUID::from_u128(0x2bd67d8b_8beb_48d5_87e0_6cda3428040a),
    pid: 11,
};
const DEVPKEY_DEVICE_IS_CONNECTED: DEVPROPKEY = DEVPROPKEY {
    fmtid: GUID::from_u128(0x83da6326_97a6_4088_9453_a1923f573b29),
    pid: 15,
};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Transport {
    Usb,
    Bluetooth,
}

impl fmt::Display for Transport {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str(match self {
            Transport::Usb => "USB",
            Transport::Bluetooth => "Bluetooth",
        })
    }
}

pub struct Keyboard {
    path: Vec<u16>, // the interface's device path, NUL-terminated
    pub transport: Transport,
    pub instance_id: String,
    // Changes whenever the keyboard reconnects, which includes waking up, and the keyboard forgets
    // the clock and the cards when it sleeps.
    pub connection: String,
}

/// Every connected raw HID interface with the keyboard's product name: Bluetooth and, if plugged
/// in, USB. USB comes first: the keyboard shows what arrives over USB while it's plugged in, and
/// USB is fast.
pub fn keyboards() -> Vec<Keyboard> {
    let mut found: Vec<Keyboard> =
        hid_interfaces().into_iter().filter_map(|(path, devinst)| keyboard(path, devinst)).collect();
    found.sort_by_key(|k| k.transport != Transport::Usb);
    found
}

/// What's connected, in a form that changes when anything reconnects.
pub fn connection_ids() -> String {
    let mut ids: Vec<String> = keyboards().into_iter().map(|k| k.connection).collect();
    ids.sort();
    ids.join(",")
}

fn keyboard(path: Vec<u16>, devinst: u32) -> Option<Keyboard> {
    let instance_id = device_id(devinst)?;
    let upper = instance_id.to_uppercase();
    if !upper.contains(VENDOR_ID) || !upper.contains(PRODUCT_ID) {
        return None;
    }
    let device = Device::open(&path, 0)?;
    let caps = device.caps()?;
    if caps.UsagePage != RAW_USAGE_PAGE || caps.Usage != RAW_USAGE {
        return None;
    }
    let bluetooth = ancestors(devinst).find(|&parent| {
        device_id(parent).is_some_and(|id| id.to_uppercase().starts_with("BTHLE\\DEV_"))
    });
    // Over Bluetooth, Windows has no product string, but the Bluetooth device has the name.
    let name = device
        .product()
        .filter(|name| !name.is_empty())
        .or_else(|| bluetooth.and_then(|parent| property_string(parent, &DEVPKEY_NAME)))?;
    if name != *PRODUCT {
        return None;
    }
    let arrived = property_filetime(devinst, &DEVPKEY_Device_LastArrivalDate).unwrap_or(0);
    let (transport, connection) = match bluetooth {
        Some(parent) => {
            // A Bluetooth keyboard's interfaces can stay while it's away: asleep, or on another slot.
            if property_bool(parent, &DEVPKEY_DEVICE_IS_CONNECTED) == Some(false) {
                return None;
            }
            let connected = property_filetime(parent, &DEVPKEY_BLUETOOTH_LAST_CONNECTED_TIME).unwrap_or(0);
            (Transport::Bluetooth, format!("{instance_id}@{arrived}/{connected}"))
        }
        None => (Transport::Usb, format!("{instance_id}@{arrived}")),
    };
    Some(Keyboard { path, transport, instance_id, connection })
}

// Sending

/// Part of a report sequence, built right before it goes out, so a clock frame and the flags
/// after each frame are current even when the frames before them took a while.
pub type Step<'a> = Box<dyn Fn() -> Vec<u8> + 'a>;

/// Send reports to each keyboard interface, in order, a HID report's worth at a time. Returns how
/// many interfaces took them all, or None if another process is sending and wait is false.
pub fn send(steps: &[Step], wait: bool) -> Option<usize> {
    let _lock = NamedLock::acquire(SEND_LOCK, wait)?;
    // While it's plugged in, the keyboard uses USB and ignores what arrives over Bluetooth,
    // so don't spend its radio on it. Unplugging starts a push over Bluetooth.
    let devices = keyboards();
    let usb = devices.iter().any(|k| k.transport == Transport::Usb);
    let mut sent = 0;
    for device in devices.iter().filter(|k| !usb || k.transport == Transport::Usb) {
        match device.send(steps) {
            Ok(()) => sent += 1,
            Err(message) => warn(&message),
        }
    }
    Some(sent)
}

/// One HID report's bytes. A short one is padded with copies of its last byte, which the
/// keyboard takes as repeats and ignores.
pub fn pad(reports: &[u8], size: usize) -> Vec<u8> {
    let mut bytes = reports.to_vec();
    if let Some(&last) = reports.last() {
        bytes.resize(size, last);
    }
    bytes
}

impl Keyboard {
    fn send(&self, steps: &[Step]) -> Result<(), String> {
        let transport = self.transport;
        let device = Device::open(&self.path, GENERIC_READ | GENERIC_WRITE)
            .ok_or_else(|| format!("can't open {transport}: {}", std::io::Error::last_os_error()))?;
        // the report ID (0: the interface has no IDs), then the bytes
        let length = device.caps().map_or(0, |caps| caps.OutputReportByteLength as usize);
        let size = length.saturating_sub(1);
        if size == 0 {
            return Err(format!("{transport} interface has no output report"));
        }
        let write = |bytes: &[u8]| -> Result<(), String> {
            let mut report = vec![0u8; length];
            report[1..].copy_from_slice(&pad(bytes, size));
            // SAFETY: report is length bytes long
            if unsafe { HidD_SetOutputReport(device.0, report.as_ptr().cast(), length as u32) } {
                Ok(())
            } else {
                Err(format!("{transport} report failed: {}", std::io::Error::last_os_error()))
            }
        };
        let start = Instant::now();
        let (mut pending, mut count, mut writes) = (Vec::new(), 0, 0);
        for step in steps {
            let reports = step();
            count += reports.len();
            pending.extend(reports);
            while pending.len() >= size {
                write(&pending[..size])?;
                pending.drain(..size);
                writes += 1;
            }
        }
        if !pending.is_empty() {
            write(&pending)?;
            writes += 1;
        }
        if count > 1 {
            let ms = start.elapsed().as_millis();
            log(&format!("sent {count} reports via {transport} in {writes} HID reports, {ms} ms"));
        }
        Ok(())
    }
}

/// A lock shared by every sofle-status process, so reports from two of them can't interleave.
pub struct NamedLock(HANDLE);

impl NamedLock {
    /// With wait false, returns None instead of waiting when another process holds it.
    pub fn acquire(name: &str, wait: bool) -> Option<NamedLock> {
        let name = wide(name);
        // SAFETY: name is NUL-terminated
        let handle = unsafe { CreateMutexW(null(), 0, name.as_ptr()) };
        if handle.is_null() {
            return Some(NamedLock(handle)); // go ahead unlocked
        }
        // A lock its holder didn't release before exiting comes back abandoned, and is ours.
        match unsafe { WaitForSingleObject(handle, if wait { INFINITE } else { 0 }) } {
            WAIT_OBJECT_0 | WAIT_ABANDONED => Some(NamedLock(handle)),
            _ => {
                unsafe { CloseHandle(handle) };
                None
            }
        }
    }
}

impl Drop for NamedLock {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe {
                ReleaseMutex(self.0);
                CloseHandle(self.0);
            }
        }
    }
}

// Windows devices

pub fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain([0]).collect()
}

fn from_wide(chars: &[u16]) -> String {
    let len = chars.iter().position(|&c| c == 0).unwrap_or(chars.len());
    String::from_utf16_lossy(&chars[..len])
}

struct Device(HANDLE);

impl Device {
    /// Access 0 is enough to read what the interface is.
    fn open(path: &[u16], access: u32) -> Option<Device> {
        // SAFETY: path is NUL-terminated
        let handle = unsafe {
            CreateFileW(path.as_ptr(), access, FILE_SHARE_READ | FILE_SHARE_WRITE, null(), OPEN_EXISTING, 0, null_mut())
        };
        (handle != INVALID_HANDLE_VALUE).then_some(Device(handle))
    }

    fn caps(&self) -> Option<HIDP_CAPS> {
        unsafe {
            let mut data: PHIDP_PREPARSED_DATA = 0;
            if !HidD_GetPreparsedData(self.0, &mut data) {
                return None;
            }
            let mut caps: HIDP_CAPS = zeroed();
            let status = HidP_GetCaps(data, &mut caps);
            HidD_FreePreparsedData(data);
            (status == HIDP_STATUS_SUCCESS).then_some(caps)
        }
    }

    fn product(&self) -> Option<String> {
        let mut chars = [0u16; 127];
        // SAFETY: the length is the buffer's, in bytes
        unsafe { HidD_GetProductString(self.0, chars.as_mut_ptr().cast(), size_of_val(&chars) as u32) }
            .then(|| from_wide(&chars))
    }
}

impl Drop for Device {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0) };
    }
}

/// Each present HID interface's device path and device node.
fn hid_interfaces() -> Vec<(Vec<u16>, u32)> {
    let mut found = Vec::new();
    unsafe {
        let mut guid: GUID = zeroed();
        HidD_GetHidGuid(&mut guid);
        let set = SetupDiGetClassDevsW(&guid, null(), null_mut(), DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
        if set == INVALID_HANDLE_VALUE as HDEVINFO {
            return found;
        }
        for index in 0.. {
            let mut interface: SP_DEVICE_INTERFACE_DATA = zeroed();
            interface.cbSize = size_of::<SP_DEVICE_INTERFACE_DATA>() as u32;
            if SetupDiEnumDeviceInterfaces(set, null(), &guid, index, &mut interface) == 0 {
                break;
            }
            let mut size = 0u32;
            SetupDiGetDeviceInterfaceDetailW(set, &interface, null_mut(), 0, &mut size, null_mut());
            let offset = size_of::<u32>(); // DevicePath follows cbSize
            if (size as usize) <= offset {
                continue;
            }
            let mut buffer = vec![0u32; (size as usize).div_ceil(4)];
            let detail = buffer.as_mut_ptr().cast::<SP_DEVICE_INTERFACE_DETAIL_DATA_W>();
            (*detail).cbSize = size_of::<SP_DEVICE_INTERFACE_DETAIL_DATA_W>() as u32;
            let mut info: SP_DEVINFO_DATA = zeroed();
            info.cbSize = size_of::<SP_DEVINFO_DATA>() as u32;
            if SetupDiGetDeviceInterfaceDetailW(set, &interface, detail, size, null_mut(), &mut info) == 0 {
                continue;
            }
            let chars = std::slice::from_raw_parts(addr_of!((*detail).DevicePath).cast::<u16>(), (size as usize - offset) / 2);
            let mut path: Vec<u16> = chars.iter().copied().take_while(|&c| c != 0).collect();
            path.push(0);
            found.push((path, info.DevInst));
        }
        SetupDiDestroyDeviceInfoList(set);
    }
    found
}

fn device_id(devinst: u32) -> Option<String> {
    let mut chars = [0u16; MAX_DEVICE_ID_LEN as usize + 1];
    // SAFETY: the length is the buffer's, in characters
    (unsafe { CM_Get_Device_IDW(devinst, chars.as_mut_ptr(), chars.len() as u32, 0) } == CR_SUCCESS)
        .then(|| from_wide(&chars))
}

fn ancestors(mut devinst: u32) -> impl Iterator<Item = u32> {
    std::iter::from_fn(move || {
        let mut parent = 0;
        (unsafe { CM_Get_Parent(&mut parent, devinst, 0) } == CR_SUCCESS).then(|| {
            devinst = parent;
            parent
        })
    })
    .take(8)
}

fn property(devinst: u32, key: &DEVPROPKEY) -> Option<(DEVPROPTYPE, Vec<u8>)> {
    let (mut kind, mut size) = (0, 0u32);
    unsafe { CM_Get_DevNode_PropertyW(devinst, key, &mut kind, null_mut(), &mut size, 0) };
    if size == 0 {
        return None;
    }
    let mut buffer = vec![0u8; size as usize];
    // SAFETY: size is the buffer's length
    (unsafe { CM_Get_DevNode_PropertyW(devinst, key, &mut kind, buffer.as_mut_ptr(), &mut size, 0) } == CR_SUCCESS)
        .then_some((kind, buffer))
}

fn property_string(devinst: u32, key: &DEVPROPKEY) -> Option<String> {
    let (kind, bytes) = property(devinst, key)?;
    let chars: Vec<u16> = bytes.as_chunks::<2>().0.iter().map(|&pair| u16::from_le_bytes(pair)).collect();
    (kind == DEVPROP_TYPE_STRING).then(|| from_wide(&chars))
}

fn property_bool(devinst: u32, key: &DEVPROPKEY) -> Option<bool> {
    let (kind, bytes) = property(devinst, key)?;
    (kind == DEVPROP_TYPE_BOOLEAN && !bytes.is_empty()).then(|| bytes[0] != 0)
}

fn property_filetime(devinst: u32, key: &DEVPROPKEY) -> Option<u64> {
    let (kind, bytes) = property(devinst, key)?;
    if kind != DEVPROP_TYPE_FILETIME {
        return None;
    }
    Some(u64::from_le_bytes(bytes.get(..8)?.try_into().ok()?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn short_reports_are_padded_with_their_last_byte() {
        assert_eq!(pad(&[1, 5, 0], 6), vec![1, 5, 0, 0, 0, 0]);
        assert_eq!(pad(&[1, 9], 2), vec![1, 9]);
        assert_eq!(pad(&[], 4), Vec::<u8>::new());
    }
}
