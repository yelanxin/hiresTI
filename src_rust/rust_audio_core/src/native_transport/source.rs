use quick_xml::events::Event;
use quick_xml::Reader;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TidalTrackContext {
    pub track_id: String,
    pub title: String,
    pub quality_label: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NativeTransportSourceKind {
    DirectFlacUrl,
    DashMpd,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NativeTransportStreamMode {
    DirectHttpStream,
    DashSegmentPrefetch,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NativeDecoderKind {
    SymphoniaFlac,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NativeTransportSource {
    TidalDirectFlac {
        url: String,
        track: TidalTrackContext,
    },
    TidalMpd {
        manifest_uri: String,
        track: TidalTrackContext,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NativeTransportPlan {
    pub source_kind: NativeTransportSourceKind,
    pub stream_mode: NativeTransportStreamMode,
    pub decoder: NativeDecoderKind,
    pub supports_seek: bool,
    pub supports_processor_chain: bool,
}

impl NativeTransportSource {
    pub fn from_tidal_uri(uri: &str) -> Result<Self, String> {
        let trimmed = uri.trim();
        if trimmed.is_empty() {
            return Err("native transport: empty uri".to_string());
        }
        let title = infer_title_from_locator(trimmed);
        let track = TidalTrackContext {
            track_id: infer_track_id_from_locator(trimmed),
            title,
            quality_label: infer_quality_label(trimmed),
        };
        if locator_has_extension(trimmed, "mpd") {
            return Ok(Self::TidalMpd {
                manifest_uri: trimmed.to_string(),
                track,
            });
        }
        if locator_has_extension(trimmed, "flac") {
            return Ok(Self::TidalDirectFlac {
                url: trimmed.to_string(),
                track,
            });
        }
        Err(format!("native transport: unsupported TIDAL uri '{trimmed}'"))
    }

    pub fn kind(&self) -> NativeTransportSourceKind {
        match self {
            Self::TidalDirectFlac { .. } => NativeTransportSourceKind::DirectFlacUrl,
            Self::TidalMpd { .. } => NativeTransportSourceKind::DashMpd,
        }
    }

    pub fn track(&self) -> &TidalTrackContext {
        match self {
            Self::TidalDirectFlac { track, .. } | Self::TidalMpd { track, .. } => track,
        }
    }

    pub fn locator(&self) -> &str {
        match self {
            Self::TidalDirectFlac { url, .. } => url.as_str(),
            Self::TidalMpd { manifest_uri, .. } => manifest_uri.as_str(),
        }
    }

    pub fn plan(&self) -> NativeTransportPlan {
        match self {
            Self::TidalDirectFlac { .. } => NativeTransportPlan {
                source_kind: NativeTransportSourceKind::DirectFlacUrl,
                stream_mode: NativeTransportStreamMode::DirectHttpStream,
                decoder: NativeDecoderKind::SymphoniaFlac,
                supports_seek: true,
                supports_processor_chain: true,
            },
            Self::TidalMpd { .. } => NativeTransportPlan {
                source_kind: NativeTransportSourceKind::DashMpd,
                stream_mode: NativeTransportStreamMode::DashSegmentPrefetch,
                decoder: NativeDecoderKind::SymphoniaFlac,
                supports_seek: true,
                supports_processor_chain: true,
            },
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct MpdManifestInfo {
    pub representation_count: usize,
    pub first_representation_id: Option<String>,
    pub first_initialization: Option<String>,
    pub first_media_template: Option<String>,
    pub first_codecs: Option<String>,
    pub first_audio_sampling_rate: Option<u32>,
    pub first_start_number: Option<u64>,
    pub first_timescale: Option<u64>,
    pub first_segment_count: Option<u64>,
    /// Total duration in milliseconds, sourced from `<MPD mediaPresentationDuration>`
    /// or `<Period duration>` (ISO 8601 durations).
    pub total_duration_ms: Option<u64>,
    /// `<SegmentTemplate duration>` in `timescale` units.
    pub segment_template_duration: Option<u64>,
    /// Summed `<S d="...">` duration in `timescale` units.
    pub segment_timeline_total: Option<u64>,
}

pub fn inspect_mpd_manifest(xml: &str) -> Result<MpdManifestInfo, String> {
    let mut reader = Reader::from_str(xml);
    reader.config_mut().trim_text(true);
    let mut buf = Vec::new();
    let mut info = MpdManifestInfo::default();

    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(event)) | Ok(Event::Empty(event)) => {
                parse_mpd_node(&reader, event.name().as_ref(), event.attributes(), &mut info)?;
            }
            Ok(Event::Eof) => break,
            Err(err) => return Err(format!("native transport: MPD parse failed: {err}")),
            _ => {}
        }
        buf.clear();
    }

    Ok(info)
}

fn parse_mpd_node<'a>(
    reader: &Reader<&[u8]>,
    name: &[u8],
    attributes: quick_xml::events::attributes::Attributes<'a>,
    info: &mut MpdManifestInfo,
) -> Result<(), String> {
    match name {
        b"MPD" => {
            for attr in attributes.flatten() {
                if attr.key.as_ref() == b"mediaPresentationDuration"
                    && info.total_duration_ms.is_none()
                {
                    let raw = decode_attr_value(reader, attr.value.as_ref())?;
                    info.total_duration_ms = parse_iso8601_duration_ms(&raw);
                }
            }
        }
        b"Period" => {
            for attr in attributes.flatten() {
                if attr.key.as_ref() == b"duration" && info.total_duration_ms.is_none() {
                    let raw = decode_attr_value(reader, attr.value.as_ref())?;
                    info.total_duration_ms = parse_iso8601_duration_ms(&raw);
                }
            }
        }
        b"Representation" => {
            info.representation_count += 1;
            for attr in attributes.flatten() {
                match attr.key.as_ref() {
                    b"id" if info.first_representation_id.is_none() => {
                        info.first_representation_id =
                            Some(decode_attr_value(reader, attr.value.as_ref())?);
                    }
                    b"codecs" if info.first_codecs.is_none() => {
                        info.first_codecs = Some(decode_attr_value(reader, attr.value.as_ref())?);
                    }
                    b"audioSamplingRate" if info.first_audio_sampling_rate.is_none() => {
                        info.first_audio_sampling_rate = decode_attr_value(reader, attr.value.as_ref())?
                            .parse::<u32>()
                            .ok();
                    }
                    _ => {}
                }
            }
        }
        b"SegmentTemplate" if info.first_initialization.is_none() => {
            for attr in attributes.flatten() {
                match attr.key.as_ref() {
                    b"initialization" if info.first_initialization.is_none() => {
                        info.first_initialization =
                            Some(decode_attr_value(reader, attr.value.as_ref())?);
                    }
                    b"media" if info.first_media_template.is_none() => {
                        info.first_media_template =
                            Some(decode_attr_value(reader, attr.value.as_ref())?);
                    }
                    b"startNumber" if info.first_start_number.is_none() => {
                        info.first_start_number = decode_attr_value(reader, attr.value.as_ref())?
                            .parse::<u64>()
                            .ok();
                    }
                    b"timescale" if info.first_timescale.is_none() => {
                        info.first_timescale = decode_attr_value(reader, attr.value.as_ref())?
                            .parse::<u64>()
                            .ok();
                    }
                    b"duration" if info.segment_template_duration.is_none() => {
                        info.segment_template_duration = decode_attr_value(reader, attr.value.as_ref())?
                            .parse::<u64>()
                            .ok();
                    }
                    _ => {}
                }
            }
        }
        b"S" => {
            let mut count = 1u64;
            let mut seg_d = 0u64;
            for attr in attributes.flatten() {
                match attr.key.as_ref() {
                    b"r" => {
                        let repeat = decode_attr_value(reader, attr.value.as_ref())?
                            .parse::<i64>()
                            .unwrap_or(0);
                        if repeat >= 0 {
                            count = count.saturating_add(repeat as u64);
                        }
                    }
                    b"d" => {
                        seg_d = decode_attr_value(reader, attr.value.as_ref())?
                            .parse::<u64>()
                            .unwrap_or(0);
                    }
                    _ => {}
                }
            }
            info.first_segment_count =
                Some(info.first_segment_count.unwrap_or(0).saturating_add(count));
            if seg_d > 0 {
                let total = seg_d.saturating_mul(count);
                info.segment_timeline_total = Some(
                    info.segment_timeline_total
                        .unwrap_or(0)
                        .saturating_add(total),
                );
            }
        }
        _ => {}
    }
    Ok(())
}

fn locator_without_query(locator: &str) -> &str {
    locator.split('?').next().unwrap_or(locator)
}

fn locator_has_extension(locator: &str, extension: &str) -> bool {
    locator_without_query(locator)
        .to_ascii_lowercase()
        .ends_with(&format!(".{}", extension.to_ascii_lowercase()))
}

fn infer_title_from_locator(locator: &str) -> String {
    locator_without_query(locator)
        .rsplit('/')
        .next()
        .filter(|part| !part.is_empty())
        .unwrap_or("TIDAL Stream")
        .to_string()
}

fn infer_track_id_from_locator(locator: &str) -> String {
    locator_without_query(locator)
        .rsplit('/')
        .next()
        .filter(|part| !part.is_empty())
        .unwrap_or(locator)
        .to_string()
}

fn infer_quality_label(locator: &str) -> String {
    let lower = locator.to_ascii_lowercase();
    if lower.ends_with(".mpd") || lower.contains(".mpd?") {
        "HI_RES_LOSSLESS".to_string()
    } else {
        "LOSSLESS".to_string()
    }
}

impl MpdManifestInfo {
    pub fn total_duration_s(&self) -> Option<f64> {
        if let Some(ms) = self.total_duration_ms {
            return Some(ms as f64 / 1000.0);
        }
        let ts = self.first_timescale.filter(|t| *t > 0)? as f64;
        if let (Some(count), Some(seg_d)) =
            (self.first_segment_count, self.segment_template_duration)
        {
            if count > 0 && seg_d > 0 {
                return Some((count as f64 * seg_d as f64) / ts);
            }
        }
        if let Some(total) = self.segment_timeline_total {
            if total > 0 {
                return Some(total as f64 / ts);
            }
        }
        None
    }
}

fn parse_iso8601_duration_ms(raw: &str) -> Option<u64> {
    let s = raw.trim();
    let rest = s.strip_prefix('P').or_else(|| s.strip_prefix('p'))?;
    let rest = rest.strip_prefix('T').or_else(|| rest.strip_prefix('t')).unwrap_or(rest);
    if rest.is_empty() {
        return None;
    }

    let mut total_ms: u64 = 0;
    let mut num_start = 0usize;
    let bytes = rest.as_bytes();
    let mut i = 0usize;
    while i < bytes.len() {
        let c = bytes[i] as char;
        if c.is_ascii_digit() || c == '.' {
            i += 1;
            continue;
        }
        let token = &rest[num_start..i];
        if token.is_empty() {
            return None;
        }
        match c {
            'H' | 'h' => {
                let h: u64 = token.parse().ok()?;
                total_ms = total_ms.checked_add(h.checked_mul(3_600_000)?)?;
            }
            'M' | 'm' => {
                let m: u64 = token.parse().ok()?;
                total_ms = total_ms.checked_add(m.checked_mul(60_000)?)?;
            }
            'S' | 's' => {
                let sec: f64 = token.parse().ok()?;
                let ms = (sec * 1000.0).round();
                if !ms.is_finite() || ms < 0.0 {
                    return None;
                }
                total_ms = total_ms.checked_add(ms as u64)?;
            }
            _ => return None,
        }
        i += 1;
        num_start = i;
    }
    if num_start != bytes.len() {
        return None;
    }
    Some(total_ms)
}

fn decode_attr_value(reader: &Reader<&[u8]>, raw: &[u8]) -> Result<String, String> {
    reader
        .decoder()
        .decode(raw)
        .map(|text| text.into_owned().replace("&amp;", "&"))
        .map_err(|e| format!("native transport: invalid MPD attribute: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classify_tidal_uris() {
        assert!(matches!(
            NativeTransportSource::from_tidal_uri("https://example.invalid/a.flac?token=1").unwrap(),
            NativeTransportSource::TidalDirectFlac { .. }
        ));
        assert!(matches!(
            NativeTransportSource::from_tidal_uri("file:///tmp/test.mpd").unwrap(),
            NativeTransportSource::TidalMpd { .. }
        ));
    }

    #[test]
    fn inspect_mpd_extracts_basic_audio_shape() {
        let xml = r#"
            <MPD>
              <Period>
                <AdaptationSet mimeType="audio/mp4">
                  <Representation id="1" codecs="flac" audioSamplingRate="44100">
                    <SegmentTemplate initialization="init-stream$RepresentationID$.m4s"
                                     media="chunk-stream$RepresentationID$-$Number%05d$.m4s"
                                     startNumber="1"
                                     timescale="44100">
                      <SegmentTimeline>
                        <S t="0" d="46728" />
                      </SegmentTimeline>
                    </SegmentTemplate>
                  </Representation>
                </AdaptationSet>
              </Period>
            </MPD>
        "#;
        let info = inspect_mpd_manifest(xml).unwrap();
        assert_eq!(info.representation_count, 1);
        assert_eq!(info.first_codecs.as_deref(), Some("flac"));
        assert_eq!(info.first_audio_sampling_rate, Some(44100));
        assert_eq!(
            info.first_initialization.as_deref(),
            Some("init-stream$RepresentationID$.m4s")
        );
        assert_eq!(
            info.first_media_template.as_deref(),
            Some("chunk-stream$RepresentationID$-$Number%05d$.m4s")
        );
        assert_eq!(
            info.first_segment_count,
            Some(1)
        );
    }

    #[test]
    fn inspect_mpd_extracts_total_duration_from_manifest() {
        let xml = r#"
            <MPD mediaPresentationDuration="PT4M12.5S">
              <Period>
                <AdaptationSet mimeType="audio/mp4">
                  <Representation id="1" codecs="flac" audioSamplingRate="96000">
                    <SegmentTemplate initialization="init.m4s"
                                     media="chunk-$Number$.m4s"
                                     startNumber="1"
                                     timescale="48000">
                      <SegmentTimeline>
                        <S t="0" d="96000" r="125" />
                      </SegmentTimeline>
                    </SegmentTemplate>
                  </Representation>
                </AdaptationSet>
              </Period>
            </MPD>
        "#;
        let info = inspect_mpd_manifest(xml).unwrap();
        assert_eq!(info.total_duration_ms, Some(252_500));
        assert_eq!(info.total_duration_s(), Some(252.5));
    }

    #[test]
    fn inspect_mpd_falls_back_to_segment_timeline_duration() {
        let xml = r#"
            <MPD>
              <Period>
                <AdaptationSet mimeType="audio/mp4">
                  <Representation id="1" codecs="flac" audioSamplingRate="96000">
                    <SegmentTemplate initialization="init.m4s"
                                     media="chunk-$Number$.m4s"
                                     startNumber="1"
                                     timescale="48000">
                      <SegmentTimeline>
                        <S t="0" d="96000" r="2" />
                      </SegmentTimeline>
                    </SegmentTemplate>
                  </Representation>
                </AdaptationSet>
              </Period>
            </MPD>
        "#;
        let info = inspect_mpd_manifest(xml).unwrap();
        assert_eq!(info.first_segment_count, Some(3));
        assert_eq!(info.segment_timeline_total, Some(288000));
        assert_eq!(info.total_duration_s(), Some(6.0));
    }
}
