use std::collections::HashMap;
use std::slice;

pub struct VizProcessor {
    num_bars: usize,
    db_min: f32,
    db_range: f32,
    smooth: f32,
    min_interval_ms: f64,
    last_emit_ms: f64,
    current: Vec<f32>,
}

impl VizProcessor {
    fn new(num_bars: usize, max_hz: f32, smooth: f32, db_min: f32, db_range: f32) -> Self {
        let bars = num_bars.max(1);
        let hz = if max_hz <= 0.0 { 20.0 } else { max_hz };
        let interval = 1000.0_f64 / f64::from(hz);
        let s = smooth.clamp(0.0, 1.0);
        let range = if db_range.abs() < f32::EPSILON { 60.0 } else { db_range };
        Self {
            num_bars: bars,
            db_min,
            db_range: range,
            smooth: s,
            min_interval_ms: interval,
            last_emit_ms: -1.0,
            current: vec![0.0; bars],
        }
    }
}

fn map_input_to_heights(input: &[f32], out: &mut [f32], db_min: f32, db_range: f32) {
    let n = out.len();
    let in_n = input.len().min(n);
    for i in 0..in_n {
        let val = input[i];
        let mut h = if val <= db_min { 0.0 } else { (val - db_min) / db_range };
        if h < 0.0 {
            h = 0.0;
        } else if h > 1.0 {
            h = 1.0;
        }
        out[i] = h;
    }
    if in_n < n {
        out[in_n..n].fill(0.0);
    }
}

fn build_log_bins_impl(input: &[f32], out: &mut [f32]) {
    let in_count = input.len();
    let out_count = out.len();
    if in_count == 0 || out_count == 0 {
        return;
    }
    for i in 0..out_count {
        let t0 = (i as f32) / (out_count as f32);
        let t1 = ((i + 1) as f32) / (out_count as f32);
        let mut x0 = (t0.powf(2.15) * ((in_count - 1) as f32)) as usize;
        let mut x1 = (t1.powf(2.15) * ((in_count - 1) as f32)) as usize;
        if x1 <= x0 {
            x1 = (x0 + 1).min(in_count - 1);
        }
        if x0 >= in_count {
            x0 = in_count - 1;
        }
        let mut sum = 0.0_f32;
        let mut cnt = 0_usize;
        for &v in &input[x0..=x1] {
            sum += v;
            cnt += 1;
        }
        let avg = if cnt > 0 { sum / (cnt as f32) } else { 0.0 };
        let tilt = 0.92 + (0.16 * ((i as f32) / ((out_count.saturating_sub(1).max(1)) as f32)));
        out[i] = (avg.max(0.0).min(1.0).powf(0.84) * tilt).max(0.0).min(1.0);
    }
}

#[no_mangle]
pub extern "C" fn viz_processor_new(
    num_bars: usize,
    max_hz: f32,
    smooth: f32,
    db_min: f32,
    db_range: f32,
) -> *mut VizProcessor {
    let p = VizProcessor::new(num_bars, max_hz, smooth, db_min, db_range);
    Box::into_raw(Box::new(p))
}

#[no_mangle]
pub extern "C" fn viz_processor_free(ptr: *mut VizProcessor) {
    if ptr.is_null() {
        return;
    }
    unsafe {
        drop(Box::from_raw(ptr));
    }
}

#[no_mangle]
pub extern "C" fn viz_processor_reset(ptr: *mut VizProcessor) {
    if ptr.is_null() {
        return;
    }
    let p = unsafe { &mut *ptr };
    p.last_emit_ms = -1.0;
    p.current.fill(0.0);
}

#[no_mangle]
pub extern "C" fn viz_processor_process(
    ptr: *mut VizProcessor,
    input_ptr: *const f32,
    input_len: usize,
    now_ms: f64,
    output_ptr: *mut f32,
    output_len: usize,
) -> usize {
    if ptr.is_null() || input_ptr.is_null() || output_ptr.is_null() || output_len == 0 {
        return 0;
    }
    let p = unsafe { &mut *ptr };
    let n = p.num_bars.min(output_len);
    if n == 0 {
        return 0;
    }
    if p.last_emit_ms >= 0.0 && (now_ms - p.last_emit_ms) < p.min_interval_ms {
        return 0;
    }

    let input = unsafe { slice::from_raw_parts(input_ptr, input_len) };
    let mut mapped = vec![0.0_f32; n];
    map_input_to_heights(input, &mut mapped, p.db_min, p.db_range);

    for i in 0..n {
        let cur = p.current[i];
        let tgt = mapped[i];
        p.current[i] = cur + ((tgt - cur) * p.smooth);
    }

    let out = unsafe { slice::from_raw_parts_mut(output_ptr, n) };
    out.copy_from_slice(&p.current[..n]);
    p.last_emit_ms = now_ms;
    n
}

#[no_mangle]
pub extern "C" fn process_spectrum(
    input_ptr: *const f32,
    input_len: usize,
    num_bars: usize,
    db_min: f32,
    db_range: f32,
    output_ptr: *mut f32,
    output_len: usize,
) -> usize {
    if input_ptr.is_null() || output_ptr.is_null() || num_bars == 0 || output_len == 0 {
        return 0;
    }
    let n = num_bars.min(output_len);
    let input = unsafe { slice::from_raw_parts(input_ptr, input_len) };
    let out = unsafe { slice::from_raw_parts_mut(output_ptr, n) };
    let safe_range = if db_range.abs() < f32::EPSILON { 60.0 } else { db_range };
    map_input_to_heights(input, out, db_min, safe_range);
    n
}

#[no_mangle]
pub extern "C" fn build_log_bins(
    input_ptr: *const f32,
    input_len: usize,
    output_ptr: *mut f32,
    output_len: usize,
) -> usize {
    if input_ptr.is_null() || output_ptr.is_null() || output_len == 0 {
        return 0;
    }
    let input = unsafe { slice::from_raw_parts(input_ptr, input_len) };
    let out = unsafe { slice::from_raw_parts_mut(output_ptr, output_len) };
    build_log_bins_impl(input, out);
    output_len
}

#[no_mangle]
pub extern "C" fn build_spiral_points(
    bins_ptr: *const f32,
    bins_len: usize,
    width: f32,
    height: f32,
    phase: f32,
    gain: f32,
    output_ptr: *mut f32,
    output_len: usize,
) -> usize {
    if bins_ptr.is_null() || output_ptr.is_null() || bins_len == 0 || output_len < 4 {
        return 0;
    }
    let bins = unsafe { slice::from_raw_parts(bins_ptr, bins_len) };
    let out = unsafe { slice::from_raw_parts_mut(output_ptr, output_len) };

    let cx = width * 0.5;
    let cy = height * 0.54;
    let full_span = width.hypot(height);
    let base = width.min(height) * 0.015;
    let span = full_span * 0.52;
    let sample_n: usize = 240;
    let mut max_bin = 0.001_f32;
    for &v in bins {
        if v > max_bin {
            max_bin = v;
        }
    }
    if max_bin < 0.001 {
        max_bin = 0.001;
    }

    let mut w = 0usize;
    let cap_points = output_len / 4;
    for si in 0..sample_n {
        if (w / 4) >= cap_points {
            break;
        }
        let t = (si as f32) / ((sample_n - 1) as f32);
        let src = ((t * (bins_len as f32)) as usize).min(bins_len - 1);
        let raw = (bins[src] * gain).clamp(0.0, 1.0);
        let lvl = (raw / max_bin).clamp(0.0, 1.0);
        if lvl < 0.004 {
            continue;
        }
        let angle = (phase * 1.2) + (t * 14.0 * std::f32::consts::PI);
        let radius = base + (t * span * (0.42 + (lvl * 0.72)));
        let x = cx + angle.cos() * radius;
        let y = cy + angle.sin() * radius;

        out[w] = x;
        out[w + 1] = y;
        out[w + 2] = lvl;
        out[w + 3] = t;
        w += 4;
    }
    w
}

#[no_mangle]
pub extern "C" fn build_neon_spokes(
    bins_ptr: *const f32,
    bins_len: usize,
    width: f32,
    height: f32,
    phase: f32,
    gain: f32,
    output_ptr: *mut f32,
    output_len: usize,
) -> usize {
    if bins_ptr.is_null() || output_ptr.is_null() || bins_len == 0 || output_len < 6 {
        return 0;
    }
    let bins = unsafe { slice::from_raw_parts(bins_ptr, bins_len) };
    let out = unsafe { slice::from_raw_parts_mut(output_ptr, output_len) };
    let cx = width * 0.5;
    let cy = height * 0.54;
    let size = width.min(height);
    let full_span = width.hypot(height);
    let max_len = full_span * 0.62;

    let mut w = 0usize;
    let cap = output_len / 6;
    for i in 0..bins_len {
        if (w / 6) >= cap {
            break;
        }
        let lvl = (bins[i] * gain).clamp(0.0, 1.0);
        if lvl < 0.02 {
            continue;
        }
        let angle = ((2.0 * std::f32::consts::PI) * ((i as f32) / (bins_len as f32))) + (phase * 0.30);
        let ln = (size * 0.06) + (lvl * max_len);
        let x2 = cx + angle.cos() * ln;
        let y2 = cy + angle.sin() * ln;
        out[w] = cx;
        out[w + 1] = cy;
        out[w + 2] = x2;
        out[w + 3] = y2;
        out[w + 4] = lvl;
        out[w + 5] = (i as f32) / ((bins_len.saturating_sub(1).max(1)) as f32);
        w += 6;
    }
    w
}

#[no_mangle]
pub extern "C" fn build_neon_ring_points(
    ring_count: usize,
    width: f32,
    height: f32,
    phase: f32,
    bass: f32,
    output_ptr: *mut f32,
    output_len: usize,
) -> usize {
    if output_ptr.is_null() || output_len < 6 {
        return 0;
    }
    let out = unsafe { slice::from_raw_parts_mut(output_ptr, output_len) };
    let rings = ring_count.max(1);
    let seg_n: usize = 180;
    let cx = width * 0.5;
    let cy = height * 0.54;
    let size = width.min(height);
    let full_span = width.hypot(height);
    let base = size * 0.04;
    let depth_span = full_span * 0.62;
    let drift = phase * 0.85;
    let b = bass.clamp(0.0, 1.0);
    let mut w = 0usize;
    let cap = output_len / 6;
    for ri in 0..rings {
        let z = (((ri as f32) / (rings as f32)) + (drift * 0.10)).fract();
        let radius = base + ((1.0 - z).powf(1.65) * depth_span);
        let t = 1.0 - z;
        let alpha = 0.10 + (0.42 * t.powf(1.8)) + (0.10 * b * t);
        let lw = 0.8 + (2.6 * t.powf(1.4));
        let color_t = 0.05 + (0.90 * t);
        let warp_amp = (10.0 + (42.0 * t)) * (1.0 + (1.10 * b));
        let f1 = 2.6 + (2.8 * t);
        let f2 = 6.4 + (4.4 * (1.0 - t));
        let ph = (phase * (1.2 + (0.25 * t))) + ((ri as f32) * 0.19);
        let start_a =
            (((ri as f32) * 2.399_963_1) + (phase * 0.17) + (t * 1.1)).rem_euclid(2.0 * std::f32::consts::PI);
        for si in 0..seg_n {
            if (w / 6) >= cap {
                return w;
            }
            let a = start_a + ((2.0 * std::f32::consts::PI) * ((si as f32) / (seg_n as f32)));
            let wobble_raw = (a * f1 + ph).sin() * warp_amp
                + (a * f2 - (ph * 1.35)).sin() * (warp_amp * 0.72);
            let wobble = wobble_raw.clamp(-radius * 0.34, radius * 0.34);
            let rr = (radius + wobble).max(2.0);
            let px = cx + (a.cos() * rr);
            let py = cy + (a.sin() * rr);
            out[w] = px;
            out[w + 1] = py;
            out[w + 2] = alpha;
            out[w + 3] = lw;
            out[w + 4] = color_t;
            out[w + 5] = if si == 0 { 1.0 } else { 0.0 };
            w += 6;
        }
    }
    w
}

#[no_mangle]
pub extern "C" fn build_line_points(
    bins_ptr: *const f32,
    bins_len: usize,
    width: f32,
    height: f32,
    gain: f32,
    output_ptr: *mut f32,
    output_len: usize,
) -> usize {
    if bins_ptr.is_null() || output_ptr.is_null() || bins_len < 2 || output_len < 2 {
        return 0;
    }
    let bins = unsafe { slice::from_raw_parts(bins_ptr, bins_len) };
    let out = unsafe { slice::from_raw_parts_mut(output_ptr, output_len) };
    let n = bins_len;
    let step_x = width / ((n.saturating_sub(1).max(1)) as f32);
    let mut w = 0usize;
    let cap = output_len / 2;
    for i in 0..n {
        if (w / 2) >= cap {
            break;
        }
        let lvl = (bins[i] * gain).clamp(0.0, 1.0);
        let x = (i as f32) * step_x;
        let y = height - (lvl * height);
        out[w] = x;
        out[w + 1] = y;
        w += 2;
    }
    w
}

#[no_mangle]
pub extern "C" fn build_fall_cells(
    levels_ptr: *const f32,
    levels_len: usize,
    gain: f32,
    height: f32,
    step_y: f32,
    layers: usize,
    output_ptr: *mut f32,
    output_len: usize,
) -> usize {
    if levels_ptr.is_null() || output_ptr.is_null() || levels_len == 0 || output_len < 3 {
        return 0;
    }
    let levels = unsafe { slice::from_raw_parts(levels_ptr, levels_len) };
    let out = unsafe { slice::from_raw_parts_mut(output_ptr, output_len) };
    let mut w = 0usize;
    let cap = output_len / 3;
    let lcnt = layers.max(1);
    for l in 0..lcnt {
        let fade = 1.0 - ((l as f32) / ((lcnt.saturating_sub(1).max(1)) as f32));
        let y_off = (l as f32) * step_y;
        for i in 0..levels_len {
            if (w / 3) >= cap {
                return w;
            }
            let lvl = (levels[i] * gain).clamp(0.0, 1.0);
            if lvl < 0.01 {
                continue;
            }
            if y_off > (lvl * height) {
                continue;
            }
            let y = height - y_off - 2.0;
            if y < 0.0 {
                continue;
            }
            out[w] = i as f32;
            out[w + 1] = y;
            out[w + 2] = fade;
            w += 3;
        }
    }
    w
}

#[no_mangle]
pub extern "C" fn build_pro_fall_column(
    bins_ptr: *const f32,
    bins_len: usize,
    gain: f32,
    output_ptr: *mut f32,
    output_len: usize,
) -> usize {
    if bins_ptr.is_null() || output_ptr.is_null() || bins_len == 0 || output_len < 2 {
        return 0;
    }
    let bins = unsafe { slice::from_raw_parts(bins_ptr, bins_len) };
    let out = unsafe { slice::from_raw_parts_mut(output_ptr, output_len) };
    let mut w = 0usize;
    let cap = output_len / 2;
    for r in 0..bins_len {
        if (w / 2) >= cap {
            return w;
        }
        let lvl = (bins[r] * gain).clamp(0.0, 1.0);
        if lvl < 0.008 {
            continue;
        }
        out[w] = r as f32;
        out[w + 1] = lvl;
        w += 2;
    }
    w
}

#[no_mangle]
pub extern "C" fn build_pro_fall_rgba(
    frames_ptr: *const f32,
    cols: usize,
    rows: usize,
    gain: f32,
    palette_ptr: *const f32,
    palette_n: usize,
    out_ptr: *mut u8,
    out_len: usize,
) -> usize {
    if frames_ptr.is_null()
        || palette_ptr.is_null()
        || out_ptr.is_null()
        || cols == 0
        || rows == 0
        || palette_n == 0
    {
        return 0;
    }
    let px_count = cols.saturating_mul(rows);
    let need = px_count.saturating_mul(4);
    if out_len < need {
        return 0;
    }
    let frames = unsafe { slice::from_raw_parts(frames_ptr, cols.saturating_mul(rows)) };
    let palette = unsafe { slice::from_raw_parts(palette_ptr, palette_n.saturating_mul(4)) };
    let out = unsafe { slice::from_raw_parts_mut(out_ptr, need) };
    out.fill(0);

    for c in 0..cols {
        let age = if cols <= 1 {
            1.0
        } else {
            ((c as f32) / ((cols - 1) as f32)).clamp(0.0, 1.0).powf(1.25)
        };
        for r in 0..rows {
            let raw = frames[c * rows + r];
            let lvl = (raw * gain).clamp(0.0, 1.0);
            if lvl < 0.008 {
                continue;
            }
            let idx = ((lvl.powf(0.86) * ((palette_n - 1) as f32)) as usize).min(palette_n - 1);
            let p = idx * 4;
            let rr = palette[p].clamp(0.0, 1.0);
            let gg = palette[p + 1].clamp(0.0, 1.0);
            let bb = palette[p + 2].clamp(0.0, 1.0);
            let aa = palette[p + 3].clamp(0.0, 1.0);
            let a = (aa * age).max(0.03).min(1.0);
            let pr = rr * a;
            let pg = gg * a;
            let pb = bb * a;

            // r=0 is low band at bottom in original code; convert to image top-origin.
            let y = rows - 1 - r;
            let off = (y * cols + c) * 4;
            // Cairo FORMAT_ARGB32 on little-endian memory is BGRA premultiplied.
            out[off] = (pb * 255.0) as u8;
            out[off + 1] = (pg * 255.0) as u8;
            out[off + 2] = (pr * 255.0) as u8;
            out[off + 3] = (a * 255.0) as u8;
        }
    }
    need
}

#[no_mangle]
pub extern "C" fn build_fall_rgba(
    levels_ptr: *const f32,
    levels_len: usize,
    gain: f32,
    height_px: usize,
    step_y_px: usize,
    thickness_px: usize,
    bar_colors_ptr: *const f32,
    bar_colors_len: usize,
    out_ptr: *mut u8,
    out_len: usize,
) -> usize {
    if levels_ptr.is_null()
        || bar_colors_ptr.is_null()
        || out_ptr.is_null()
        || levels_len == 0
        || height_px == 0
        || step_y_px == 0
        || thickness_px == 0
        || bar_colors_len < levels_len.saturating_mul(4)
    {
        return 0;
    }
    let width_px = levels_len;
    let need = width_px.saturating_mul(height_px).saturating_mul(4);
    if out_len < need {
        return 0;
    }
    let levels = unsafe { slice::from_raw_parts(levels_ptr, levels_len) };
    let bar_colors = unsafe { slice::from_raw_parts(bar_colors_ptr, bar_colors_len) };
    let out = unsafe { slice::from_raw_parts_mut(out_ptr, need) };
    out.fill(0);

    let layers = (height_px / step_y_px).clamp(8, 36);
    for l in 0..layers {
        let fade = 1.0 - ((l as f32) / ((layers.saturating_sub(1).max(1)) as f32));
        let y_off = l * step_y_px;
        for i in 0..levels_len {
            let lvl = (levels[i] * gain).clamp(0.0, 1.0);
            if lvl < 0.01 {
                continue;
            }
            let active = lvl * (height_px as f32);
            if (y_off as f32) > active {
                continue;
            }
            let y_bottom = (height_px as isize) - (y_off as isize) - 2;
            if y_bottom < 0 {
                continue;
            }
            let p = i * 4;
            let r = bar_colors[p].clamp(0.0, 1.0);
            let g = bar_colors[p + 1].clamp(0.0, 1.0);
            let b = bar_colors[p + 2].clamp(0.0, 1.0);
            let a0 = bar_colors[p + 3].clamp(0.0, 1.0);
            let a = (a0 * 0.55 * fade).max(0.05).min(1.0);
            let pr = r * a;
            let pg = g * a;
            let pb = b * a;
            for t in 0..thickness_px {
                let yy = y_bottom - (t as isize);
                if yy < 0 || (yy as usize) >= height_px {
                    continue;
                }
                let off = ((yy as usize) * width_px + i) * 4;
                out[off] = (pb * 255.0) as u8;
                out[off + 1] = (pg * 255.0) as u8;
                out[off + 2] = (pr * 255.0) as u8;
                out[off + 3] = (a * 255.0) as u8;
            }
        }
    }
    need
}

#[no_mangle]
pub extern "C" fn build_dots_rgba(
    levels_ptr: *const f32,
    levels_len: usize,
    gain: f32,
    canvas_width_px: usize,
    height_px: usize,
    bar_w_px: usize,
    spacing_px: usize,
    dot_h_px: usize,
    gap_y_px: usize,
    bar_colors_ptr: *const f32,
    bar_colors_len: usize,
    out_ptr: *mut u8,
    out_len: usize,
) -> usize {
    if levels_ptr.is_null()
        || bar_colors_ptr.is_null()
        || out_ptr.is_null()
        || levels_len == 0
        || canvas_width_px == 0
        || height_px == 0
        || bar_w_px == 0
        || dot_h_px == 0
        || bar_colors_len < levels_len.saturating_mul(4)
    {
        return 0;
    }
    let width_px = canvas_width_px;
    let need = width_px.saturating_mul(height_px).saturating_mul(4);
    if out_len < need {
        return 0;
    }
    let levels = unsafe { slice::from_raw_parts(levels_ptr, levels_len) };
    let bar_colors = unsafe { slice::from_raw_parts(bar_colors_ptr, bar_colors_len) };
    let out = unsafe { slice::from_raw_parts_mut(out_ptr, need) };
    out.fill(0);
    let gap = gap_y_px;
    let step = dot_h_px.saturating_add(gap).max(1);

    for i in 0..levels_len {
        let lvl = (levels[i] * gain).clamp(0.0, 1.0);
        if lvl < 0.001 {
            continue;
        }
        let x0 = i.saturating_mul(bar_w_px.saturating_add(spacing_px));
        if x0 >= width_px {
            continue;
        }
        let x1 = (x0 + bar_w_px).min(width_px);
        if x1 <= x0 {
            continue;
        }
        let h = (lvl * (height_px as f32)).max(1.0) as usize;
        let p = i * 4;
        let r = bar_colors[p].clamp(0.0, 1.0);
        let g = bar_colors[p + 1].clamp(0.0, 1.0);
        let b = bar_colors[p + 2].clamp(0.0, 1.0);
        let a0 = bar_colors[p + 3].clamp(0.0, 1.0);
        let y0 = height_px.saturating_sub(dot_h_px);
        let mut drawn = 0usize;
        while drawn < h {
            let y_top = y0.saturating_sub(drawn);
            let a = a0;
            let pr = r * a;
            let pg = g * a;
            let pb = b * a;
            for t in 0..dot_h_px {
                let yy = y_top.saturating_sub(t);
                if yy >= height_px {
                    continue;
                }
                for xx in x0..x1 {
                    let off = (yy * width_px + xx) * 4;
                    out[off] = (pb * 255.0) as u8;
                    out[off + 1] = (pg * 255.0) as u8;
                    out[off + 2] = (pr * 255.0) as u8;
                    out[off + 3] = (a * 255.0) as u8;
                }
            }
            drawn = drawn.saturating_add(step);
        }
    }
    need
}

#[no_mangle]
pub extern "C" fn count_artist_keys(
    keys_ptr: *const u64,
    keys_len: usize,
    out_keys_ptr: *mut u64,
    out_counts_ptr: *mut u32,
    out_len: usize,
) -> usize {
    if keys_ptr.is_null() || out_keys_ptr.is_null() || out_counts_ptr.is_null() || out_len == 0 {
        return 0;
    }
    let keys = unsafe { slice::from_raw_parts(keys_ptr, keys_len) };
    let out_keys = unsafe { slice::from_raw_parts_mut(out_keys_ptr, out_len) };
    let out_counts = unsafe { slice::from_raw_parts_mut(out_counts_ptr, out_len) };

    let mut counts: HashMap<u64, u32> = HashMap::new();
    for &k in keys {
        let entry = counts.entry(k).or_insert(0);
        *entry = entry.saturating_add(1);
    }

    let mut pairs: Vec<(u64, u32)> = counts.into_iter().collect();
    pairs.sort_unstable_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));

    let n = pairs.len().min(out_len);
    for i in 0..n {
        out_keys[i] = pairs[i].0;
        out_counts[i] = pairs[i].1;
    }
    n
}

#[no_mangle]
pub extern "C" fn filter_sort_indices_no_query(
    artist_keys_ptr: *const u64,
    title_rank_ptr: *const u32,
    artist_rank_ptr: *const u32,
    album_rank_ptr: *const u32,
    durations_ptr: *const u32,
    len: usize,
    sort_mode: u32,
    artist_filter_key: u64,
    use_artist_filter: u8,
    out_indices_ptr: *mut u32,
    out_len: usize,
) -> usize {
    if artist_keys_ptr.is_null()
        || title_rank_ptr.is_null()
        || artist_rank_ptr.is_null()
        || album_rank_ptr.is_null()
        || durations_ptr.is_null()
        || out_indices_ptr.is_null()
        || out_len == 0
    {
        return 0;
    }

    let artist_keys = unsafe { slice::from_raw_parts(artist_keys_ptr, len) };
    let title_rank = unsafe { slice::from_raw_parts(title_rank_ptr, len) };
    let artist_rank = unsafe { slice::from_raw_parts(artist_rank_ptr, len) };
    let album_rank = unsafe { slice::from_raw_parts(album_rank_ptr, len) };
    let durations = unsafe { slice::from_raw_parts(durations_ptr, len) };
    let out = unsafe { slice::from_raw_parts_mut(out_indices_ptr, out_len) };

    let mut idxs: Vec<usize> = Vec::with_capacity(len);
    if use_artist_filter != 0 {
        for i in 0..len {
            if artist_keys[i] == artist_filter_key {
                idxs.push(i);
            }
        }
    } else {
        idxs.extend(0..len);
    }

    match sort_mode {
        1 => idxs.sort_unstable_by(|&a, &b| title_rank[a].cmp(&title_rank[b]).then_with(|| a.cmp(&b))),
        2 => idxs.sort_unstable_by(|&a, &b| artist_rank[a].cmp(&artist_rank[b]).then_with(|| a.cmp(&b))),
        3 => idxs.sort_unstable_by(|&a, &b| album_rank[a].cmp(&album_rank[b]).then_with(|| a.cmp(&b))),
        4 => idxs.sort_unstable_by(|&a, &b| durations[a].cmp(&durations[b]).then_with(|| a.cmp(&b))),
        _ => {}
    }

    let n = idxs.len().min(out_len);
    for i in 0..n {
        out[i] = idxs[i] as u32;
    }
    n
}

fn bytes_contains(haystack: &[u8], needle: &[u8]) -> bool {
    if needle.is_empty() {
        return true;
    }
    if needle.len() > haystack.len() {
        return false;
    }
    haystack.windows(needle.len()).any(|w| w == needle)
}

#[no_mangle]
pub extern "C" fn filter_sort_indices_with_query(
    search_blob_ptr: *const u8,
    search_blob_len: usize,
    search_offsets_ptr: *const u32,
    search_lens_ptr: *const u32,
    artist_keys_ptr: *const u64,
    title_rank_ptr: *const u32,
    artist_rank_ptr: *const u32,
    album_rank_ptr: *const u32,
    durations_ptr: *const u32,
    len: usize,
    sort_mode: u32,
    artist_filter_key: u64,
    use_artist_filter: u8,
    query_ptr: *const u8,
    query_len: usize,
    out_indices_ptr: *mut u32,
    out_len: usize,
) -> usize {
    if search_blob_ptr.is_null()
        || search_offsets_ptr.is_null()
        || search_lens_ptr.is_null()
        || artist_keys_ptr.is_null()
        || title_rank_ptr.is_null()
        || artist_rank_ptr.is_null()
        || album_rank_ptr.is_null()
        || durations_ptr.is_null()
        || query_ptr.is_null()
        || out_indices_ptr.is_null()
        || out_len == 0
    {
        return 0;
    }

    let search_blob = unsafe { slice::from_raw_parts(search_blob_ptr, search_blob_len) };
    let search_offsets = unsafe { slice::from_raw_parts(search_offsets_ptr, len) };
    let search_lens = unsafe { slice::from_raw_parts(search_lens_ptr, len) };
    let artist_keys = unsafe { slice::from_raw_parts(artist_keys_ptr, len) };
    let title_rank = unsafe { slice::from_raw_parts(title_rank_ptr, len) };
    let artist_rank = unsafe { slice::from_raw_parts(artist_rank_ptr, len) };
    let album_rank = unsafe { slice::from_raw_parts(album_rank_ptr, len) };
    let durations = unsafe { slice::from_raw_parts(durations_ptr, len) };
    let query = unsafe { slice::from_raw_parts(query_ptr, query_len) };
    let out = unsafe { slice::from_raw_parts_mut(out_indices_ptr, out_len) };

    let mut idxs: Vec<usize> = Vec::with_capacity(len);
    for i in 0..len {
        if use_artist_filter != 0 && artist_keys[i] != artist_filter_key {
            continue;
        }
        let off = search_offsets[i] as usize;
        let ln = search_lens[i] as usize;
        if off >= search_blob_len {
            continue;
        }
        let end = off.saturating_add(ln).min(search_blob_len);
        if end <= off {
            continue;
        }
        let text = &search_blob[off..end];
        if bytes_contains(text, query) {
            idxs.push(i);
        }
    }

    match sort_mode {
        1 => idxs.sort_unstable_by(|&a, &b| title_rank[a].cmp(&title_rank[b]).then_with(|| a.cmp(&b))),
        2 => idxs.sort_unstable_by(|&a, &b| artist_rank[a].cmp(&artist_rank[b]).then_with(|| a.cmp(&b))),
        3 => idxs.sort_unstable_by(|&a, &b| album_rank[a].cmp(&album_rank[b]).then_with(|| a.cmp(&b))),
        4 => idxs.sort_unstable_by(|&a, &b| durations[a].cmp(&durations[b]).then_with(|| a.cmp(&b))),
        _ => {}
    }

    let n = idxs.len().min(out_len);
    for i in 0..n {
        out[i] = idxs[i] as u32;
    }
    n
}
