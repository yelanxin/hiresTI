//! UAC 1.0 / 2.0 USB Audio control transfers.
//!
//! Implements the control-transfer layer for sample-rate negotiation:
//!
//! - **UAC 1.0**: `SET_CUR` to the ISO OUT endpoint
//!   (SAMPLING_FREQ_CONTROL, 3-byte LE frequency)
//! - **UAC 2.0**: `SET_CUR` / `GET_CUR` / `GET_RANGE` to the Clock Source
//!   entity via the Audio Control interface
//!   (CS_SAM_FREQ_CONTROL, 4-byte LE frequency)

use std::time::Duration;

use rusb::{DeviceHandle, Direction, Recipient, RequestType, UsbContext};

// ---------------------------------------------------------------------------
// UAC control-request constants
// ---------------------------------------------------------------------------

/// Class request codes (bRequest).
const SET_CUR: u8 = 0x01;
const GET_CUR: u8 = 0x81;
const GET_RANGE: u8 = 0x82;

/// UAC 1.0 — Sampling Frequency Control selector (wValue high byte).
const UAC1_CS_SAM_FREQ: u8 = 0x01;

/// UAC 2.0 — Clock Frequency Control selector (wValue high byte).
const UAC2_CS_SAM_FREQ: u8 = 0x01;

const CTRL_TIMEOUT: Duration = Duration::from_millis(500);

// ---------------------------------------------------------------------------
// UAC 1.0
// ---------------------------------------------------------------------------

/// Set the sample rate on a UAC 1.0 device.
///
/// Sends `SET_CUR` for `SAMPLING_FREQ_CONTROL` to the ISO OUT endpoint.
/// The frequency is encoded as a 3-byte little-endian integer per UAC 1.0 spec.
pub fn set_sample_rate_uac1<T: UsbContext>(
    handle: &DeviceHandle<T>,
    ep: u8,
    rate: u32,
) -> Result<(), String> {
    let buf = [
        (rate & 0xFF) as u8,
        ((rate >> 8) & 0xFF) as u8,
        ((rate >> 16) & 0xFF) as u8,
    ];
    // bmRequestType: Host→Device, Class, Endpoint = 0x22
    let rt = rusb::request_type(Direction::Out, RequestType::Class, Recipient::Endpoint);
    let w_value = (UAC1_CS_SAM_FREQ as u16) << 8;
    let w_index = ep as u16;

    handle
        .write_control(rt, SET_CUR, w_value, w_index, &buf, CTRL_TIMEOUT)
        .map(|_| ())
        .map_err(|e| format!("UAC1 SET_CUR SAMPLING_FREQ: {}", e))
}

/// Read the current sample rate from a UAC 1.0 device (best-effort).
///
/// Returns `None` if the device does not support `GET_CUR` for this control.
pub fn get_sample_rate_uac1<T: UsbContext>(
    handle: &DeviceHandle<T>,
    ep: u8,
) -> Option<u32> {
    let mut buf = [0u8; 3];
    let rt = rusb::request_type(Direction::In, RequestType::Class, Recipient::Endpoint);
    let w_value = (UAC1_CS_SAM_FREQ as u16) << 8;
    let w_index = ep as u16;

    handle
        .read_control(rt, GET_CUR, w_value, w_index, &mut buf, CTRL_TIMEOUT)
        .ok()
        .filter(|&n| n >= 3)
        .map(|_| u32::from_le_bytes([buf[0], buf[1], buf[2], 0]))
}

// ---------------------------------------------------------------------------
// UAC 2.0
// ---------------------------------------------------------------------------

/// Set the sample rate on a UAC 2.0 device via the Clock Source entity.
///
/// Sends `SET_CUR` for `CS_SAM_FREQ_CONTROL` to the Clock Source entity
/// (`clock_id`) on the Audio Control interface (`ctrl_iface`).
/// The frequency is 4-byte LE per UAC 2.0 spec.
pub fn set_sample_rate_uac2<T: UsbContext>(
    handle: &DeviceHandle<T>,
    ctrl_iface: u8,
    clock_id: u8,
    rate: u32,
) -> Result<(), String> {
    let buf = rate.to_le_bytes();
    // bmRequestType: Host→Device, Class, Interface = 0x21
    let rt = rusb::request_type(Direction::Out, RequestType::Class, Recipient::Interface);
    let w_value = (UAC2_CS_SAM_FREQ as u16) << 8;
    // wIndex: high byte = entity (clock) ID, low byte = interface number
    let w_index = ((clock_id as u16) << 8) | (ctrl_iface as u16);

    handle
        .write_control(rt, SET_CUR, w_value, w_index, &buf, CTRL_TIMEOUT)
        .map(|_| ())
        .map_err(|e| format!("UAC2 SET_CUR CS_SAM_FREQ (clock_id={}): {}", clock_id, e))
}

/// Read the current sample rate from a UAC 2.0 Clock Source entity via GET_CUR.
///
/// Returns `None` if the transfer fails or the response is too short.
pub fn get_cur_sample_rate_uac2<T: UsbContext>(
    handle: &DeviceHandle<T>,
    ctrl_iface: u8,
    clock_id: u8,
) -> Option<u32> {
    let mut buf = [0u8; 4];
    let rt = rusb::request_type(Direction::In, RequestType::Class, Recipient::Interface);
    let w_value = (UAC2_CS_SAM_FREQ as u16) << 8;
    let w_index = ((clock_id as u16) << 8) | (ctrl_iface as u16);

    handle
        .read_control(rt, GET_CUR, w_value, w_index, &mut buf, CTRL_TIMEOUT)
        .ok()
        .filter(|&n| n >= 4)
        .map(|_| u32::from_le_bytes(buf))
}

/// Query supported sample rates from a UAC 2.0 Clock Source entity via GET_RANGE.
///
/// Returns a list of discrete frequencies reported by the device.
/// For continuous ranges (`dRES > 0`), both the minimum and maximum are included.
/// Returns an empty `Vec` if the transfer fails or the response is malformed.
pub fn query_sample_rates_uac2<T: UsbContext>(
    handle: &DeviceHandle<T>,
    ctrl_iface: u8,
    clock_id: u8,
) -> Vec<u32> {
    // First read: 2 bytes to get wNumSubRanges
    let mut hdr = [0u8; 2];
    let rt = rusb::request_type(Direction::In, RequestType::Class, Recipient::Interface);
    let w_value = (UAC2_CS_SAM_FREQ as u16) << 8;
    let w_index = ((clock_id as u16) << 8) | (ctrl_iface as u16);

    if handle
        .read_control(rt, GET_RANGE, w_value, w_index, &mut hdr, CTRL_TIMEOUT)
        .is_err()
    {
        return Vec::new();
    }

    let num_ranges = u16::from_le_bytes(hdr) as usize;
    if num_ranges == 0 || num_ranges > 64 {
        return Vec::new();
    }

    // Second read: full response = 2 + num_ranges * 12 bytes
    let total = 2 + num_ranges * 12;
    let mut buf = vec![0u8; total];
    let n = match handle.read_control(rt, GET_RANGE, w_value, w_index, &mut buf, CTRL_TIMEOUT) {
        Ok(n) => n,
        Err(_) => return Vec::new(),
    };

    if n < total {
        return Vec::new();
    }

    // Parse sub-ranges: each is dMIN(4B) dMAX(4B) dRES(4B)
    let mut rates = Vec::with_capacity(num_ranges);
    for i in 0..num_ranges {
        let off = 2 + i * 12;
        let d_min = u32::from_le_bytes(buf[off..off + 4].try_into().unwrap());
        let d_max = u32::from_le_bytes(buf[off + 4..off + 8].try_into().unwrap());
        let d_res = u32::from_le_bytes(buf[off + 8..off + 12].try_into().unwrap());

        if d_res == 0 {
            // Discrete: d_min == d_max
            if d_min > 0 && !rates.contains(&d_min) {
                rates.push(d_min);
            }
        } else {
            // Continuous range: enumerate common audio rates within [d_min, d_max]
            for &r in &[44100u32, 48000, 88200, 96000, 176400, 192000, 352800, 384000] {
                if r >= d_min && r <= d_max && !rates.contains(&r) {
                    rates.push(r);
                }
            }
        }
    }

    rates.sort_unstable();
    rates
}
