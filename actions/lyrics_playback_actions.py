from threading import Thread
import logging

from gi.repository import Gtk, GLib
from app_errors import classify_exception, user_message
from actions import audio_settings_actions

logger = logging.getLogger(__name__)
MAX_PREFETCH_CACHE = 6
NO_LYRICS_BOTTOM_HINT = "No usable lyrics for this track."


def _split_bilingual_line(text):
    if not text:
        return "", ""

    line = str(text).strip()
    if not line:
        return "", ""

    # Conservative separators to avoid over-splitting normal lyrics.
    for sep in (" / ", " | ", " ｜ ", " // "):
        if sep in line:
            left, right = line.split(sep, 1)
            left = left.strip()
            right = right.strip()
            if left and right:
                return left, right
    return line, ""


def _karaoke_markup(words, active_idx, active_color="#FFFFFF", inactive_color="#AEB8C8"):
    chunks = []
    for i, (_, token) in enumerate(words):
        txt = GLib.markup_escape_text(token)
        if i <= active_idx:
            chunks.append(f'<span foreground="{active_color}" weight="700">{txt}</span>')
        else:
            chunks.append(f'<span foreground="{inactive_color}">{txt}</span>')
    return "".join(chunks)


def _karaoke_active_idx(words, current_time):
    idx = -1
    for i, (t, _token) in enumerate(words):
        if t <= current_time:
            idx = i
        else:
            break
    return idx


def _prefetch_next_track(app, current_index):
    try:
        next_idx = app.get_next_index(direction=1)
        if next_idx < 0 or next_idx == current_index:
            return
        queue = app._get_active_queue() if hasattr(app, "_get_active_queue") else list(getattr(app, "current_track_list", []) or [])
        if next_idx >= len(queue):
            return

        next_track = queue[next_idx]
        track_id = getattr(next_track, "id", None)
        if track_id is None:
            return

        quality_key = str(getattr(app.backend, "quality", "unknown"))
        cache = getattr(app, "stream_prefetch_cache", {})
        cached = cache.get(track_id)
        if cached and cached.get("quality") == quality_key and cached.get("url"):
            return

        prefetch_url = app.backend.get_stream_url(next_track)
        if not prefetch_url:
            return

        meta = {
            "name": getattr(next_track, "name", ""),
            "artist": getattr(getattr(next_track, "artist", None), "name", ""),
            "album": getattr(getattr(next_track, "album", None), "name", ""),
            "artwork_url": app.backend.get_artwork_url(next_track, 320),
        }

        cache[track_id] = {"url": prefetch_url, "quality": quality_key, "meta": meta}
        if len(cache) > MAX_PREFETCH_CACHE:
            oldest_key = next(iter(cache))
            cache.pop(oldest_key, None)
        app.stream_prefetch_cache = cache
        logger.debug("Prefetched next track url: %s", track_id)
    except Exception as e:
        logger.debug("Next-track prefetch failed: %s", e)


def _cache_current_track_audio(app, track_id, quality_key, stream_url):
    try:
        max_tracks = int(getattr(app, "audio_cache_tracks", 0) or 0)
        if max_tracks <= 0:
            return
        cache_dir = getattr(app, "audio_cache_dir", "")
        if not cache_dir:
            return
        local_path = utils.cache_audio_from_url(cache_dir, track_id, quality_key, stream_url)
        if local_path:
            utils.prune_audio_cache(cache_dir, max_tracks=max_tracks)
    except Exception as e:
        logger.debug("Audio cache store failed: %s", e)


def render_lyrics_list(app, lyrics_obj=None, status_msg=None):
    logger.debug("Rendering lyrics. status=%s", status_msg)

    if not hasattr(app, "lyrics_vbox"):
        return

    while child := app.lyrics_vbox.get_first_child():
        app.lyrics_vbox.remove(child)
    app.lyric_widgets = []
    app.current_lyric_index = -1

    if status_msg:
        if status_msg == NO_LYRICS_BOTTOM_HINT:
            spacer = Gtk.Box(vexpand=True)
            app.lyrics_vbox.append(spacer)
            bottom = Gtk.Label(label=status_msg, css_classes=["dim-label"], halign=Gtk.Align.CENTER)
            bottom.set_margin_bottom(20)
            app.lyrics_vbox.append(bottom)
            return

        lbl = Gtk.Label(label=status_msg, css_classes=["title-2"], valign=Gtk.Align.CENTER)
        lbl.set_opacity(0.5)
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, vexpand=True)
        center.append(lbl)
        app.lyrics_vbox.append(center)
        return

    # Keep a clean blank state with a small bottom breathing margin.
    if not lyrics_obj:
        spacer = Gtk.Box(vexpand=True)
        spacer.set_margin_bottom(20)
        app.lyrics_vbox.append(spacer)
        return

    if lyrics_obj:
        source = lyrics_obj.time_points if lyrics_obj.has_synced else [0]
        logger.debug("Drawing %s lyric lines", len(source))

        for t in source:
            text = lyrics_obj.lyrics_map.get(t, "") if lyrics_obj.has_synced else lyrics_obj.raw_text
            if not text:
                text = " "

            karaoke_words = []
            if lyrics_obj.has_synced and hasattr(lyrics_obj, "karaoke_map"):
                karaoke_words = list(lyrics_obj.karaoke_map.get(t, []))

            # Karaoke line: keep as a single main line and update words progressively.
            if karaoke_words:
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["lyric-row"])
                row.set_halign(Gtk.Align.CENTER)
                main_lbl = Gtk.Label(css_classes=["lyric-line"], wrap=True, max_width_chars=40)
                main_lbl.set_justify(Gtk.Justification.CENTER)
                main_lbl.set_use_markup(True)
                main_lbl.set_markup(_karaoke_markup(karaoke_words, -1))
                row.append(main_lbl)
                app.lyrics_vbox.append(row)

                if lyrics_obj.has_synced:
                    app.lyric_widgets.append(
                        {
                            "time": t,
                            "widget": row,
                            "main": main_lbl,
                            "sub": None,
                            "karaoke_words": karaoke_words,
                            "karaoke_last_idx": -2,
                        }
                    )
                continue

            primary, secondary = _split_bilingual_line(text)
            if not primary:
                primary = " "

            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["lyric-row"])
            row.set_halign(Gtk.Align.CENTER)

            main_lbl = Gtk.Label(label=primary, css_classes=["lyric-line"], wrap=True, max_width_chars=40)
            main_lbl.set_justify(Gtk.Justification.CENTER)
            row.append(main_lbl)

            sub_lbl = None
            if secondary:
                sub_lbl = Gtk.Label(
                    label=secondary,
                    css_classes=["lyric-sub-line"],
                    wrap=True,
                    max_width_chars=42,
                )
                sub_lbl.set_justify(Gtk.Justification.CENTER)
                row.append(sub_lbl)

            app.lyrics_vbox.append(row)

            if lyrics_obj.has_synced:
                app.lyric_widgets.append(
                    {
                        "time": t,
                        "widget": row,
                        "main": main_lbl,
                        "sub": sub_lbl,
                        "karaoke_words": [],
                        "karaoke_last_idx": -2,
                    }
                )


def play_track(app, index):
    logger.info("play_track called. index=%s", index)

    queue = app._get_active_queue() if hasattr(app, "_get_active_queue") else list(getattr(app, "current_track_list", []) or [])
    if not queue:
        return
    if index < 0 or index >= len(queue):
        return

    app.current_track_index = index
    app._play_request_id = getattr(app, "_play_request_id", 0) + 1
    request_id = app._play_request_id
    track = queue[index]
    app.playing_track = track
    app.playing_track_id = track.id
    if hasattr(app, "refresh_current_track_favorite_state"):
        GLib.idle_add(app.refresh_current_track_favorite_state)

    logger.info("Playing: %s", track.name)

    try:
        title = getattr(track, "name", "Unknown Track")
        artist = getattr(track.artist, "name", "Unknown Artist")
        album = getattr(track.album, "name", "Unknown Album")
        app.lbl_title.set_label(title)
        app.lbl_artist.set_label(artist)
        app.lbl_album.set_label(album)
        app.lbl_title.set_tooltip_text(title)
        app.lbl_artist.set_tooltip_text(artist)
        app.lbl_album.set_tooltip_text(album)
    except Exception:
        fallback = getattr(track, "title", "Loading...")
        app.lbl_title.set_label(fallback)
        app.lbl_title.set_tooltip_text(fallback)

    GLib.idle_add(lambda: app._update_list_ui(index))
    GLib.idle_add(lambda: app._update_track_list_icon())
    if hasattr(app, "render_queue_drawer"):
        GLib.idle_add(app.render_queue_drawer)

    cover_id = getattr(track, "cover", None) or getattr(track.album, "cover", None)
    cover_url = app._get_tidal_image_url(cover_id) if cover_id else None
    if hasattr(app, "bg_viz"):
        if cover_url:
            app.bg_viz.set_colors_from_cover(cover_url, app.cache_dir)
        else:
            app.bg_viz.randomize_colors()

    if cover_id:
        Thread(target=lambda: app._load_cover_art(cover_id), daemon=True).start()
        if hasattr(app, "history_mgr"):
            app.history_mgr.add(track, cover_id)

    Thread(target=lambda: _prefetch_next_track(app, index), daemon=True).start()

    def task():
        logger.debug("Playback background task started")

        try:
            quality_key = str(getattr(app.backend, "quality", "unknown"))
            cache = getattr(app, "stream_prefetch_cache", {})
            cached = cache.get(track.id)
            url = None
            max_tracks = int(getattr(app, "audio_cache_tracks", 0) or 0)
            if cached and cached.get("quality") == quality_key and cached.get("url"):
                url = cached.get("url")
                cache.pop(track.id, None)
                logger.debug("Using prefetched stream url for track: %s", track.id)
            else:
                url = app.backend.get_stream_url(track)

            if url and max_tracks > 0 and str(url).startswith("http"):
                Thread(
                    target=_cache_current_track_audio,
                    args=(app, track.id, quality_key, url),
                    daemon=True,
                ).start()
            if url:
                logger.debug("Stream URL resolved. Loading player")
                if hasattr(app, "set_diag_health"):
                    app.set_diag_health("network", "ok")
                    app.set_diag_health("decoder", "ok")

                def apply_playback():
                    if request_id != getattr(app, "_play_request_id", 0):
                        return False
                    prev_state = str(getattr(app.player, "output_state", "idle") or "idle")
                    app.player.load(url)
                    app.player.play()
                    audio_settings_actions.update_output_status_ui(app)
                    cur_state = str(getattr(app.player, "output_state", "idle") or "idle")
                    cur_err = str(getattr(app.player, "output_error", "") or "").strip()
                    blocked = bool(getattr(app.player, "_pipewire_rate_blocked", False))
                    if blocked or cur_state == "error":
                        if app.play_btn is not None:
                            app.play_btn.set_icon_name("media-playback-start-symbolic")
                        msg = cur_err or "Audio output error."
                        if hasattr(app, "show_output_notice"):
                            app.show_output_notice(f"Output error: {msg}", "error", 4200)
                        if blocked and hasattr(app, "_show_simple_dialog"):
                            app._show_simple_dialog("Playback blocked", msg)
                        logger.warning(
                            "Playback blocked after load/play: prev_state=%s state=%s err=%s",
                            prev_state,
                            cur_state,
                            msg,
                        )
                        return False
                    app.play_btn.set_icon_name("media-playback-pause-symbolic")
                    return False

                GLib.idle_add(apply_playback)
            else:
                logger.warning("Stream URL is None")

                def apply_stream_missing():
                    if request_id != getattr(app, "_play_request_id", 0):
                        return False
                    app.render_lyrics_list(None, user_message("not_found", "playback"))
                    return False

                GLib.idle_add(apply_stream_missing)
        except Exception as e:
            kind = classify_exception(e)
            logger.warning("Playback error [%s]: %s", kind, e)
            if hasattr(app, "record_diag_event"):
                app.record_diag_event(f"Playback error [{kind}]: {e}")
            if hasattr(app, "set_diag_health"):
                if kind in ("network", "server", "auth"):
                    app.set_diag_health("network", "error", kind)
                elif kind in ("parse", "not_found", "unknown"):
                    app.set_diag_health("decoder", "warn", kind)
                else:
                    app.set_diag_health("decoder", "warn", kind)

            def apply_playback_error():
                if request_id != getattr(app, "_play_request_id", 0):
                    return False
                app.render_lyrics_list(None, user_message(kind, "playback"))
                return False

            GLib.idle_add(apply_playback_error)

        try:
            logger.debug("Starting lyrics sequence")

            def apply_loading_lyrics():
                if request_id != getattr(app, "_play_request_id", 0):
                    return False
                app.render_lyrics_list(None, "Loading Lyrics...")
                return False

            GLib.idle_add(apply_loading_lyrics)

            raw_lyrics = app.backend.get_lyrics(track.id)

            if raw_lyrics:
                logger.debug("Got lyrics data. length=%s", len(raw_lyrics))
                app.lyrics_mgr.load_lyrics(raw_lyrics)

                def apply_lyrics():
                    if request_id != getattr(app, "_play_request_id", 0):
                        return False
                    app.render_lyrics_list(app.lyrics_mgr, None)
                    return False

                GLib.idle_add(apply_lyrics)
            else:
                logger.debug("No lyrics returned")

                def apply_no_lyrics():
                    if request_id != getattr(app, "_play_request_id", 0):
                        return False
                    app.render_lyrics_list(None, NO_LYRICS_BOTTOM_HINT)
                    return False

                GLib.idle_add(apply_no_lyrics)

        except Exception as e:
            kind = classify_exception(e)
            logger.exception("Lyrics error [%s]: %s", kind, e)
            if hasattr(app, "record_diag_event"):
                app.record_diag_event(f"Lyrics error [{kind}]: {e}")
            if hasattr(app, "set_diag_health"):
                if kind in ("network", "server", "auth"):
                    app.set_diag_health("network", "warn", f"lyrics-{kind}")
                elif kind in ("parse", "not_found"):
                    app.set_diag_health("decoder", "warn", f"lyrics-{kind}")

            def apply_lyrics_error():
                if request_id != getattr(app, "_play_request_id", 0):
                    return False
                # No-lyrics states should show a subtle bottom hint.
                if kind == "not_found":
                    app.render_lyrics_list(None, NO_LYRICS_BOTTOM_HINT)
                else:
                    app.render_lyrics_list(None, user_message(kind, "lyrics"))
                return False

            GLib.idle_add(apply_lyrics_error)

    Thread(target=task, daemon=True).start()


def scroll_to_lyric(app, widget):
    if not hasattr(app, "lyrics_scroller") or not widget:
        return

    try:
        success, rect = widget.compute_bounds(app.lyrics_vbox)
        if not success:
            return

        label_center_y = rect.origin.y + (rect.size.height / 2)
        viewport_h = app.lyrics_scroller.get_height()
        # Keep active lyric near upper-middle area for smoother reading rhythm.
        anchor_ratio = 0.38
        target = label_center_y - (viewport_h * anchor_ratio)

        adj = app.lyrics_scroller.get_vadjustment()
        max_scroll = adj.get_upper() - adj.get_page_size()
        app.target_scroll_y = max(0, min(target, max_scroll))
    except Exception:
        pass


def update_ui_loop(app):
    now = GLib.get_monotonic_time() / 1_000_000.0
    try:
        playing_now = bool(app.player.is_playing())
        last_playing = getattr(app, "_last_playing_ui_state", None)
        if playing_now != last_playing:
            app._last_playing_ui_state = playing_now
            if getattr(app, "play_btn", None) is not None:
                app.play_btn.set_icon_name(
                    "media-playback-pause-symbolic" if playing_now else "media-playback-start-symbolic"
                )
    except Exception:
        playing_now = False

    p = 0.0
    d = 0.0
    cached_pd = getattr(app, "_ui_cached_pd", None)
    if (not playing_now) and cached_pd is not None:
        last_poll = float(getattr(app, "_ui_last_pos_poll_ts", 0.0) or 0.0)
        if (now - last_poll) < 0.25:
            p, d = cached_pd
        else:
            p, d = app.player.get_position()
            app._ui_cached_pd = (p, d)
            app._ui_last_pos_poll_ts = now
    else:
        p, d = app.player.get_position()
        app._ui_cached_pd = (p, d)
        app._ui_last_pos_poll_ts = now

    if d > 0:
        user_interacting_seek = bool(getattr(app, "_seek_user_interacting", False))
        if not user_interacting_seek:
            app.is_programmatic_update = True
            app.scale.set_range(0, d)
            app.scale.set_value(p)
            app.is_programmatic_update = False
            if hasattr(app, "_update_progress_thumb_position"):
                app._update_progress_thumb_position()

        current_int_sec = int(p)
        if (not user_interacting_seek) and (not hasattr(app, "_last_sec") or app._last_sec != current_int_sec):
            app.lbl_current_time.set_text(f"{int(p//60)}:{int(p%60):02d}")
            app.lbl_total_time.set_text(f"{int(d//60)}:{int(d%60):02d}")
            app._last_sec = current_int_sec
        elif user_interacting_seek:
            app.lbl_total_time.set_text(f"{int(d//60)}:{int(d%60):02d}")

    if hasattr(app, "lyrics_mgr") and app.lyrics_mgr.has_synced and hasattr(app, "lyric_widgets") and app.lyric_widgets:
        offset_ms = int(getattr(app, "lyrics_user_offset_ms", 0) or 0)
        current_time = p + 0.3 + (offset_ms / 1000.0)
        active_idx = -1

        for i, item in enumerate(app.lyric_widgets):
            if item["time"] <= current_time:
                active_idx = i
            else:
                break

        current_idx = getattr(app, "current_lyric_index", -1)
        if active_idx != current_idx:
            if current_idx != -1 and current_idx < len(app.lyric_widgets):
                prev = app.lyric_widgets[current_idx]
                prev["widget"].remove_css_class("active")
                prev["main"].remove_css_class("active")
                if prev.get("sub") is not None:
                    prev["sub"].remove_css_class("active")
                if prev.get("karaoke_words"):
                    prev["main"].set_markup(_karaoke_markup(prev["karaoke_words"], -1))
                    prev["karaoke_last_idx"] = -1

            if active_idx != -1:
                cur = app.lyric_widgets[active_idx]
                w = cur["widget"]
                w.add_css_class("active")
                cur["main"].add_css_class("active")
                if cur.get("sub") is not None:
                    cur["sub"].add_css_class("active")
                if cur.get("karaoke_words"):
                    k_idx = _karaoke_active_idx(cur["karaoke_words"], current_time)
                    cur["main"].set_markup(_karaoke_markup(cur["karaoke_words"], k_idx))
                    cur["karaoke_last_idx"] = k_idx
                app._scroll_to_lyric(w)

            app.current_lyric_index = active_idx

        # Update karaoke progression while staying on the same active line.
        if active_idx != -1 and active_idx < len(app.lyric_widgets):
            cur = app.lyric_widgets[active_idx]
            if cur.get("karaoke_words"):
                k_idx = _karaoke_active_idx(cur["karaoke_words"], current_time)
                if k_idx != cur.get("karaoke_last_idx", -2):
                    cur["main"].set_markup(_karaoke_markup(cur["karaoke_words"], k_idx))
                    cur["karaoke_last_idx"] = k_idx

    if hasattr(app, "target_scroll_y") and hasattr(app, "lyrics_scroller"):
        adj = app.lyrics_scroller.get_vadjustment()
        current_y = adj.get_value()
        target_y = app.target_scroll_y
        if abs(target_y - current_y) > 0.5:
            new_y = current_y + (target_y - current_y) * 0.08
            adj.set_value(new_y)

    return True
