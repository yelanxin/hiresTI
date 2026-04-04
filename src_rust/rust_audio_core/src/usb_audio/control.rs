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
/// UAC 2.0 CUR request — both GET and SET use bRequest=0x01; the direction
/// is encoded in bmRequestType.  Some devices also respond to the UAC 1.0
/// style GET_CUR=0x81, but not all.
const UAC2_CUR: u8 = 0x01;
/// UAC 1.0 GET_CUR — direction baked into bRequest.
const GET_CUR: u8 = 0x81;
/// UAC 1.0 legacy request codes.
const GET_MIN: u8 = 0x82;
const GET_MAX: u8 = 0x83;
const GET_RES: u8 = 0x84;
/// UAC 2.0 RANGE request.  Per the spec (Section 5.2.2) the bRequest for
/// RANGE is **0x02**; the direction is encoded in bmRequestType, not bRequest.
/// Some devices also accept the UAC 1.0-style 0x82, but not all.
const UAC2_GET_RANGE: u8 = 0x02;
/// Legacy alias used by some DACs that respond to 0x82 for RANGE.
const UAC2_GET_RANGE_LEGACY: u8 = 0x82;

/// UAC 1.0 — Sampling Frequency Control selector (wValue high byte).
const UAC1_CS_SAM_FREQ: u8 = 0x01;

/// UAC 2.0 — Clock Frequency Control selector (wValue high byte).
const UAC2_CS_SAM_FREQ: u8 = 0x01;

/// Feature Unit — Volume Control selector (wValue high byte), same for UAC 1.0/2.0.
const FU_VOLUME_CONTROL: u8 = 0x02;

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
pub fn get_sample_rate_uac1<T: UsbContext>(handle: &DeviceHandle<T>, ep: u8) -> Option<u32> {
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

    // Try UAC2 spec-correct bRequest=0x02 first, fall back to legacy 0x82.
    let range_req = if handle
        .read_control(rt, UAC2_GET_RANGE, w_value, w_index, &mut hdr, CTRL_TIMEOUT)
        .is_ok()
    {
        UAC2_GET_RANGE
    } else if handle
        .read_control(rt, UAC2_GET_RANGE_LEGACY, w_value, w_index, &mut hdr, CTRL_TIMEOUT)
        .is_ok()
    {
        UAC2_GET_RANGE_LEGACY
    } else {
        return Vec::new();
    };

    let num_ranges = u16::from_le_bytes(hdr) as usize;
    if num_ranges == 0 || num_ranges > 64 {
        return Vec::new();
    }

    // Second read: full response = 2 + num_ranges * 12 bytes
    let total = 2 + num_ranges * 12;
    let mut buf = vec![0u8; total];
    let n = match handle.read_control(rt, range_req, w_value, w_index, &mut buf, CTRL_TIMEOUT) {
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
            for &r in &[
                44100u32, 48000, 88200, 96000, 176400, 192000, 352800, 384000,
            ] {
                if r >= d_min && r <= d_max && !rates.contains(&r) {
                    rates.push(r);
                }
            }
        }
    }

    rates.sort_unstable();
    rates
}

// ---------------------------------------------------------------------------
// Feature Unit — Hardware Volume Control
// ---------------------------------------------------------------------------
//
// Volume values are in 1/256 dB (i16).  E.g. 0x0000 = 0.0 dB,
// 0xFF00 = -1.0 dB (-256 in i16 / 256 = -1.0).

/// UAC 1.0: query volume range (min, max, resolution) from a Feature Unit.
///
/// Issues GET_MIN (0x82) and GET_MAX (0x83).
/// `channel`: 0 = master, 1/2/… = per-channel.
/// Returns `(min_raw, max_raw, res_raw)` in 1/256 dB units.
pub fn get_volume_range_uac1<T: UsbContext>(
    handle: &DeviceHandle<T>,
    ctrl_iface: u8,
    unit_id: u8,
    channel: u8,
) -> Option<(i16, i16, i16)> {
    let rt_in = rusb::request_type(Direction::In, RequestType::Class, Recipient::Interface);
    let w_value = ((FU_VOLUME_CONTROL as u16) << 8) | (channel as u16);
    let w_index = ((unit_id as u16) << 8) | (ctrl_iface as u16);

    let mut buf = [0u8; 2];

    // GET_MIN
    let min_raw = handle
        .read_control(rt_in, GET_MIN, w_value, w_index, &mut buf, CTRL_TIMEOUT)
        .ok()
        .filter(|&n| n >= 2)
        .map(|_| i16::from_le_bytes(buf))?;

    // GET_MAX
    let max_raw = handle
        .read_control(rt_in, GET_MAX, w_value, w_index, &mut buf, CTRL_TIMEOUT)
        .ok()
        .filter(|&n| n >= 2)
        .map(|_| i16::from_le_bytes(buf))?;

    // GET_RES — optional; default to 1 (= 1/256 dB ≈ 0.004 dB)
    let res_raw = handle
        .read_control(rt_in, GET_RES, w_value, w_index, &mut buf, CTRL_TIMEOUT)
        .ok()
        .filter(|&n| n >= 2)
        .map(|_| i16::from_le_bytes(buf))
        .unwrap_or(1);

    Some((min_raw, max_raw, res_raw.max(1)))
}

/// UAC 2.0: query volume range from a Feature Unit via GET_RANGE.
///
/// `channel`: 0 = master, 1/2/… = per-channel.
/// Returns `(min_raw, max_raw, res_raw)` aggregated across all sub-ranges.
pub fn get_volume_range_uac2<T: UsbContext>(
    handle: &DeviceHandle<T>,
    ctrl_iface: u8,
    unit_id: u8,
    channel: u8,
) -> Option<(i16, i16, i16)> {
    let rt_in = rusb::request_type(Direction::In, RequestType::Class, Recipient::Interface);
    let w_value = ((FU_VOLUME_CONTROL as u16) << 8) | (channel as u16);
    let w_index = ((unit_id as u16) << 8) | (ctrl_iface as u16);

    let mut hdr = [0u8; 2];
    // Try UAC2 spec-correct bRequest=0x02 first, fall back to legacy 0x82.
    let range_req = match handle.read_control(rt_in, UAC2_GET_RANGE, w_value, w_index, &mut hdr, CTRL_TIMEOUT) {
        Ok(_) => {
            eprintln!("usb-audio: UAC2 GET_RANGE(0x02) header ok (unit={} ch={})", unit_id, channel);
            UAC2_GET_RANGE
        }
        Err(_) => {
            match handle.read_control(rt_in, UAC2_GET_RANGE_LEGACY, w_value, w_index, &mut hdr, CTRL_TIMEOUT) {
                Ok(_) => {
                    eprintln!("usb-audio: UAC2 GET_RANGE(0x82) header ok (unit={} ch={})", unit_id, channel);
                    UAC2_GET_RANGE_LEGACY
                }
                Err(e) => {
                    eprintln!("usb-audio: UAC2 GET_RANGE header failed both 0x02 and 0x82 (unit={} ch={}): {}", unit_id, channel, e);
                    return get_volume_range_uac2_legacy(handle, ctrl_iface, unit_id, channel);
                }
            }
        }
    };

    let num_ranges = u16::from_le_bytes(hdr) as usize;
    if num_ranges == 0 || num_ranges > 64 {
        eprintln!("usb-audio: UAC2 GET_RANGE bad num_ranges={} (unit={} ch={})", num_ranges, unit_id, channel);
        return get_volume_range_uac2_legacy(handle, ctrl_iface, unit_id, channel);
    }

    let total = 2 + num_ranges * 6;
    let mut buf = vec![0u8; total];
    let n = match handle.read_control(rt_in, range_req, w_value, w_index, &mut buf, CTRL_TIMEOUT) {
        Ok(n) => n,
        Err(e) => {
            eprintln!("usb-audio: UAC2 GET_RANGE payload failed (unit={} ch={}): {}", unit_id, channel, e);
            return get_volume_range_uac2_legacy(handle, ctrl_iface, unit_id, channel);
        }
    };
    if n < total {
        eprintln!("usb-audio: UAC2 GET_RANGE short payload {}/{} (unit={} ch={})", n, total, unit_id, channel);
        return get_volume_range_uac2_legacy(handle, ctrl_iface, unit_id, channel);
    }

    let mut min_raw = i16::MAX;
    let mut max_raw = i16::MIN;
    let mut res_raw = i16::MAX;
    for index in 0..num_ranges {
        let off = 2 + index * 6;
        let d_min = i16::from_le_bytes(buf[off..off + 2].try_into().unwrap());
        let d_max = i16::from_le_bytes(buf[off + 2..off + 4].try_into().unwrap());
        let d_res = i16::from_le_bytes(buf[off + 4..off + 6].try_into().unwrap()).abs();
        min_raw = min_raw.min(d_min);
        max_raw = max_raw.max(d_max);
        if d_res > 0 {
            res_raw = res_raw.min(d_res);
        }
    }

    if min_raw == i16::MAX || max_raw == i16::MIN {
        return None;
    }

    Some((
        min_raw,
        max_raw,
        if res_raw == i16::MAX { 1 } else { res_raw },
    ))
}

fn get_volume_range_uac2_legacy<T: UsbContext>(
    handle: &DeviceHandle<T>,
    ctrl_iface: u8,
    unit_id: u8,
    channel: u8,
) -> Option<(i16, i16, i16)> {
    eprintln!(
        "usb-audio: UAC2 volume range probe falling back to legacy GET_MIN/GET_MAX/GET_RES (unit={} channel={})",
        unit_id, channel
    );
    let rt_in = rusb::request_type(Direction::In, RequestType::Class, Recipient::Interface);
    let w_value = ((FU_VOLUME_CONTROL as u16) << 8) | (channel as u16);
    let w_index = ((unit_id as u16) << 8) | (ctrl_iface as u16);
    let mut buf = [0u8; 2];

    let min_raw = match handle
        .read_control(rt_in, GET_MIN, w_value, w_index, &mut buf, CTRL_TIMEOUT)
    {
        Ok(n) if n >= 2 => i16::from_le_bytes(buf),
        Ok(n) => {
            eprintln!("usb-audio: GET_MIN short read {} bytes (unit={} ch={})", n, unit_id, channel);
            return None;
        }
        Err(e) => {
            eprintln!("usb-audio: GET_MIN failed (unit={} ch={}): {}", unit_id, channel, e);
            return None;
        }
    };
    let max_raw = match handle
        .read_control(rt_in, GET_MAX, w_value, w_index, &mut buf, CTRL_TIMEOUT)
    {
        Ok(n) if n >= 2 => i16::from_le_bytes(buf),
        Ok(n) => {
            eprintln!("usb-audio: GET_MAX short read {} bytes (unit={} ch={})", n, unit_id, channel);
            return None;
        }
        Err(e) => {
            eprintln!("usb-audio: GET_MAX failed (unit={} ch={}): {}", unit_id, channel, e);
            return None;
        }
    };
    let res_raw = handle
        .read_control(rt_in, GET_RES, w_value, w_index, &mut buf, CTRL_TIMEOUT)
        .ok()
        .filter(|&n| n >= 2)
        .map(|_| i16::from_le_bytes(buf))
        .unwrap_or(1)
        .abs()
        .max(1);

    Some((min_raw, max_raw, res_raw))
}

/// Get the current volume from a Feature Unit (UAC 1.0 or 2.0).
///
/// `channel`: 0 = master, 1/2/… = per-channel.
pub fn get_volume_cur<T: UsbContext>(
    handle: &DeviceHandle<T>,
    ctrl_iface: u8,
    unit_id: u8,
    channel: u8,
) -> Option<i16> {
    let rt_in = rusb::request_type(Direction::In, RequestType::Class, Recipient::Interface);
    let w_value = ((FU_VOLUME_CONTROL as u16) << 8) | (channel as u16);
    let w_index = ((unit_id as u16) << 8) | (ctrl_iface as u16);
    let mut buf = [0u8; 2];

    // Try UAC2 bRequest=0x01 first, then UAC1 bRequest=0x81.
    if let Ok(n) = handle.read_control(rt_in, UAC2_CUR, w_value, w_index, &mut buf, CTRL_TIMEOUT) {
        if n >= 2 {
            return Some(i16::from_le_bytes(buf));
        }
    }
    handle
        .read_control(rt_in, GET_CUR, w_value, w_index, &mut buf, CTRL_TIMEOUT)
        .ok()
        .filter(|&n| n >= 2)
        .map(|_| i16::from_le_bytes(buf))
}

/// Set the volume on a Feature Unit (UAC 1.0 or 2.0).
///
/// `channel`: 0 = master, 1/2/… = per-channel.
/// `value_raw` is in 1/256 dB units (e.g. -7680 = -30.0 dB).
pub fn set_volume_cur<T: UsbContext>(
    handle: &DeviceHandle<T>,
    ctrl_iface: u8,
    unit_id: u8,
    channel: u8,
    value_raw: i16,
) -> Result<(), String> {
    let rt_out = rusb::request_type(Direction::Out, RequestType::Class, Recipient::Interface);
    let w_value = ((FU_VOLUME_CONTROL as u16) << 8) | (channel as u16);
    let w_index = ((unit_id as u16) << 8) | (ctrl_iface as u16);
    let buf = value_raw.to_le_bytes();

    handle
        .write_control(rt_out, SET_CUR, w_value, w_index, &buf, CTRL_TIMEOUT)
        .map(|_| ())
        .map_err(|e| {
            format!(
                "SET_CUR Volume (unit_id={}, ch={}, val={}): {}",
                unit_id, channel, value_raw, e
            )
        })
}
