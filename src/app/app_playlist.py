"""
Playlist management for TidalApp.
Contains playlist creation, editing and management methods.
"""
import logging
from gi.repository import Gtk, GLib
from core.executor import submit_daemon

logger = logging.getLogger(__name__)


def on_playlist_sort_clicked(self, field):
    if self.playlist_sort_field == field:
        self.playlist_sort_asc = not self.playlist_sort_asc
    else:
        self.playlist_sort_field = field
        self.playlist_sort_asc = True
    if self.current_playlist_id:
        self.render_playlist_detail(self.current_playlist_id)


def on_playlist_folder_card_clicked(self, folder_obj):
    if folder_obj is None:
        return
    fid = str(getattr(folder_obj, "id", "") or "")
    if not fid:
        return
    self.current_playlist_folder = folder_obj
    stack = list(getattr(self, "current_playlist_folder_stack", []) or [])
    if stack and str(stack[-1].get("id", "")) == fid:
        pass
    else:
        stack.append({"id": fid, "name": str(getattr(folder_obj, "name", "") or "Folder"), "obj": folder_obj})
    self.current_playlist_folder_stack = stack
    if getattr(self, "back_btn", None) is not None:
        self.back_btn.set_sensitive(True)
    self.render_playlists_home()


def on_playlist_folder_up_clicked(self, _btn=None):
    stack = list(getattr(self, "current_playlist_folder_stack", []) or [])
    if not stack:
        self.current_playlist_folder = None
        self.render_playlists_home()
        return
    stack.pop()
    self.current_playlist_folder_stack = stack
    if stack:
        self.current_playlist_folder = stack[-1].get("obj")
    else:
        self.current_playlist_folder = None
    self.render_playlists_home()


def on_create_playlist_folder_clicked(self, _btn=None):
    if not getattr(self.backend, "user", None):
        self._show_simple_dialog("Login Required", "Please login first.")
        return

    def _submit(name):
        folder_name = str(name or "").strip() or "New Folder"
        parent_id = "root"
        if getattr(self, "current_playlist_folder", None) is not None:
            parent_id = str(getattr(self.current_playlist_folder, "id", "root") or "root")
        self.show_output_notice("Creating folder...", "ok", 1500)

        def task():
            f = self.backend.create_cloud_folder(folder_name, parent_folder_id=parent_id)

            def apply():
                if f is None:
                    self.show_output_notice("Failed to create folder.", "warn", 2600)
                else:
                    self.show_output_notice("Folder created.", "ok", 2200)
                    self.render_playlists_home()
                return False

            GLib.idle_add(apply)

        submit_daemon(task)

    self._prompt_playlist_name(
        "New Folder",
        "New Folder",
        _submit,
        subtitle="Create a folder to organize your cloud playlists.",
        placeholder="Folder name",
        save_label="Create",
        dialog_size=(480, 220),
    )


def on_playlist_folder_rename_clicked(self, folder_obj=None):
    folder_obj = folder_obj or getattr(self, "current_playlist_folder", None)
    if folder_obj is None:
        return
    old_name = str(getattr(folder_obj, "name", "") or "Folder")

    def _submit(name):
        new_name = str(name or "").strip()
        if not new_name or new_name == old_name:
            return
        self.show_output_notice("Renaming folder...", "ok", 1500)

        def task():
            res = self.backend.rename_cloud_folder(folder_obj, new_name)

            def apply():
                if bool(res.get("ok")):
                    self.show_output_notice("Folder renamed.", "ok", 2200)
                    stack = list(getattr(self, "current_playlist_folder_stack", []) or [])
                    for item in stack:
                        if str(item.get("id", "")) == str(getattr(folder_obj, "id", "") or ""):
                            item["name"] = new_name
                    self.current_playlist_folder_stack = stack
                    self.render_playlists_home()
                else:
                    self.show_output_notice("Failed to rename folder.", "warn", 2600)
                return False

            GLib.idle_add(apply)

        submit_daemon(task)

    self._prompt_playlist_name(
        "Rename Folder",
        old_name,
        _submit,
        subtitle="Update folder name for your cloud playlists.",
        placeholder="Folder name",
        save_label="Rename",
        dialog_size=(480, 220),
    )


def on_playlist_folder_delete_clicked(self, folder_obj=None):
    folder_obj = folder_obj or getattr(self, "current_playlist_folder", None)
    if folder_obj is None:
        return
    fname = str(getattr(folder_obj, "name", "") or "this folder")
    dialog = Gtk.Dialog(title="Delete Folder", transient_for=self.win, modal=True)
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
    )
    root.append(Gtk.Label(label=f"Delete '{fname}' permanently?", xalign=0))
    action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel")
    delete_btn = Gtk.Button(label="Delete")
    cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
    delete_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
    action_row.append(cancel_btn)
    action_row.append(delete_btn)
    root.append(action_row)
    dialog.set_child(root)

    def _on_response(d, resp):
        if resp != Gtk.ResponseType.OK:
            d.destroy()
            return
        d.destroy()
        self.show_output_notice("Deleting folder...", "ok", 1600)

        def task():
            res = self.backend.delete_cloud_folder(folder_obj)

            def apply():
                if bool(res.get("ok")):
                    self.show_output_notice("Folder deleted.", "ok", 2200)
                    fid = str(getattr(folder_obj, "id", "") or "")
                    stack = [x for x in list(getattr(self, "current_playlist_folder_stack", []) or []) if str(x.get("id", "")) != fid]
                    self.current_playlist_folder_stack = stack
                    self.current_playlist_folder = stack[-1].get("obj") if stack else None
                    self.render_playlists_home()
                else:
                    self.show_output_notice("Failed to delete folder.", "warn", 2800)
                return False

            GLib.idle_add(apply)

        submit_daemon(task)

    dialog.connect("response", _on_response)
    dialog.present()


def on_playlist_card_clicked(self, playlist_id):
    self.current_remote_playlist = None
    if self.remote_playlist_edit_btn is not None:
        self.remote_playlist_edit_btn.set_visible(False)
    if self.remote_playlist_visibility_btn is not None:
        self.remote_playlist_visibility_btn.set_visible(False)
    if self.remote_playlist_more_btn is not None:
        self.remote_playlist_more_btn.set_visible(False)
    self.current_playlist_id = playlist_id
    self.playlist_edit_mode = False
    self.playlist_rename_mode = False
    if hasattr(self, "grid_title_label") and self.grid_title_label is not None:
        self.grid_title_label.set_visible(False)
    if hasattr(self, "grid_subtitle_label") and self.grid_subtitle_label is not None:
        self.grid_subtitle_label.set_visible(False)
    if self.back_btn is not None:
        self.back_btn.set_sensitive(True)
    self.render_playlist_detail(playlist_id)


def on_remote_playlist_card_clicked(self, playlist_obj):
    if playlist_obj is None:
        return
    self.current_remote_playlist = playlist_obj
    self.current_album = None
    self.current_playlist_id = None
    self.playlist_edit_mode = False
    self.playlist_rename_mode = False
    self.right_stack.set_visible_child_name("tracks")
    if hasattr(self, "_remember_last_view"):
        self._remember_last_view("tracks")
    self.back_btn.set_sensitive(True)

    title = getattr(playlist_obj, "name", "TIDAL Playlist")
    creator = getattr(playlist_obj, "creator", None)
    creator_name = str(getattr(creator, "name", None) or "TIDAL")
    user_id = str(getattr(getattr(self.backend, "user", None), "id", "") or "").strip()
    creator_id = str(getattr(creator, "id", "") or "").strip()
    self._remote_playlist_is_own = bool(user_id and creator_id and user_id == creator_id)
    self.header_kicker.set_text("Playlist")
    self.header_title.set_text(title)
    self.header_title.set_tooltip_text(title)
    self.header_artist.set_text(creator_name)
    self.header_artist.set_tooltip_text(creator_name)
    self.header_meta.set_text("")
    if hasattr(self, "similar_albums_box"):
        self.similar_albums_box.set_visible(False)
    if self.fav_btn is not None:
        self.fav_btn.set_visible(False)
    if self.add_playlist_btn is not None:
        self.add_playlist_btn.set_visible(False)
    if self.remote_playlist_edit_btn is not None:
        self.remote_playlist_edit_btn.set_visible(False)
    if self.remote_playlist_visibility_btn is not None:
        self.remote_playlist_visibility_btn.set_visible(False)
    if self.remote_playlist_more_btn is not None:
        self.remote_playlist_more_btn.set_visible(self._remote_playlist_is_own)
    self._refresh_remote_playlist_visibility_button(playlist_obj)
    # Ensure play/shuffle buttons exist and are visible
    from actions.ui_actions import _ensure_play_shuffle_btns
    _ensure_play_shuffle_btns(self)
    import utils.helpers as utils
    utils.load_img(self.header_art, lambda: self.backend.get_artwork_url(playlist_obj, 640), self.cache_dir, utils.COVER_SIZE)

    while c := self.track_list.get_first_child():
        self.track_list.remove(c)

    # Clean up previous lazy-load hook (if any).
    try:
        old_vadj = getattr(self, "_remote_pl_vadj", None)
        old_handler = int(getattr(self, "_remote_pl_vadj_handler_id", 0) or 0)
        if old_vadj is not None and old_handler:
            old_vadj.disconnect(old_handler)
    except Exception:
        pass
    self._remote_pl_vadj = None
    self._remote_pl_vadj_handler_id = 0

    render_token = int(getattr(self, "_remote_pl_render_token", 0) or 0) + 1
    self._remote_pl_render_token = render_token

    state = {
        "tracks": [],
        "offset": 0,
        "loading": False,
        "has_more": True,
    }
    initial_limit = 20
    page_limit = 40

    def _get_total_tracks():
        for k in ("number_of_tracks", "num_tracks", "numberOfTracks", "total_number_of_items"):
            try:
                v = int(getattr(playlist_obj, k, 0) or 0)
            except Exception:
                v = 0
            if v > 0:
                return v
        return 0

    def _apply_loaded_tracks():
        total = _get_total_tracks()
        loaded = len(state["tracks"])
        if total > 0:
            self.header_meta.set_text(f"{loaded}/{total} Tracks")
        else:
            self.header_meta.set_text(f"{loaded} Tracks")
        self.load_album_tracks(list(state["tracks"]))

    def _get_track_scroller():
        try:
            return self.track_list.get_ancestor(Gtk.ScrolledWindow)
        except Exception:
            return None

    def _maybe_load_more(_adj=None):
        if int(getattr(self, "_remote_pl_render_token", 0) or 0) != render_token:
            return
        if state["loading"] or not state["has_more"]:
            return
        scroller = _get_track_scroller()
        if scroller is None:
            return
        vadj = scroller.get_vadjustment()
        if vadj is None:
            return
        # Keep first screen fixed: only start paging after user scrolls.
        if float(vadj.get_value()) <= 1.0:
            return
        remain = float(vadj.get_upper()) - (float(vadj.get_value()) + float(vadj.get_page_size()))
        if remain <= 320:
            _load_next_page()

    def _ensure_scroll_hook():
        if self._remote_pl_vadj_handler_id:
            return
        scroller = _get_track_scroller()
        if scroller is None:
            return
        vadj = scroller.get_vadjustment()
        if vadj is None:
            return
        self._remote_pl_vadj = vadj
        self._remote_pl_vadj_handler_id = vadj.connect("value-changed", _maybe_load_more)

    def _load_next_page():
        if state["loading"] or not state["has_more"]:
            return
        state["loading"] = True
        offset = int(state["offset"])
        limit = initial_limit if offset == 0 else page_limit

        def task():
            page = list(self.backend.get_playlist_tracks_page(playlist_obj, limit=limit, offset=offset) or [])

            def apply():
                if int(getattr(self, "_remote_pl_render_token", 0) or 0) != render_token:
                    return False
                state["loading"] = False
                if not page:
                    state["has_more"] = False
                    return False
                state["tracks"].extend(page)
                state["offset"] += len(page)
                if len(page) < limit:
                    state["has_more"] = False
                _apply_loaded_tracks()
                _ensure_scroll_hook()
                return False

            GLib.idle_add(apply)

        submit_daemon(task)

    _load_next_page()


def _refresh_remote_playlist_visibility_button(self, playlist_obj=None):
    pl = playlist_obj or getattr(self, "current_remote_playlist", None)
    if pl is None:
        return
    is_public = bool(getattr(pl, "public", False))
    # Update menu item icon and label
    icon = getattr(self, "_vis_menu_icon", None)
    label = getattr(self, "_vis_menu_label", None)
    if icon is not None:
        icon.set_from_icon_name("changes-allow-symbolic" if is_public else "changes-prevent-symbolic")
    if label is not None:
        label.set_text("Make Private" if is_public else "Make Public")


def on_remote_playlist_toggle_public_clicked(self, _btn=None, playlist_obj=None):
    pl = playlist_obj or getattr(self, "current_remote_playlist", None)
    if pl is None:
        return
    target_public = not bool(getattr(pl, "public", False))
    self.show_output_notice("Updating playlist visibility...", "ok", 1800)

    def task():
        res = self.backend.update_cloud_playlist(pl, is_public=target_public)

        def apply():
            if bool(res.get("ok")):
                try:
                    pl.public = target_public
                except Exception:
                    pass
                self._refresh_remote_playlist_visibility_button(pl)
                self.show_output_notice(
                    "Playlist is now public." if target_public else "Playlist is now private.",
                    "ok",
                    2200,
                )
            else:
                self.show_output_notice("Failed to update playlist visibility.", "warn", 3200)
            return False

        GLib.idle_add(apply)

    submit_daemon(task)


def _open_cloud_playlist_editor(
    self,
    dialog_title,
    save_label,
    initial_title,
    initial_desc="",
    initial_public=False,
    playlist_obj=None,
    folder_options=None,
    initial_folder_id="root",
    on_submit=None,
):
    dialog = Gtk.Dialog(title=dialog_title, transient_for=self.win, modal=True)
    dialog.set_default_size(586, 413)
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=14,
        margin_bottom=14,
        margin_start=14,
        margin_end=14,
    )
    content = Gtk.Box(spacing=16)

    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    import utils.helpers as utils
    cover = Gtk.Image(css_classes=["album-cover-img", "playlist-cover-img"])
    cover.set_size_request(utils.COVER_SIZE, utils.COVER_SIZE)
    if playlist_obj is not None:
        utils.load_img(cover, lambda: self.backend.get_artwork_url(playlist_obj, 640), self.cache_dir, utils.COVER_SIZE)
    else:
        cover.set_from_icon_name("audio-x-generic-symbolic")
    left.append(cover)
    change_btn = Gtk.Button(label="Change image")
    change_btn.set_sensitive(False)
    change_btn.set_tooltip_text("Not available in this version")
    left.append(change_btn)
    content.append(left)

    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True)
    right.append(Gtk.Label(label="Title", xalign=0))
    title_entry = Gtk.Entry(text=str(initial_title or ""))
    right.append(title_entry)

    folder_dd = None
    folder_ids = []
    if folder_options:
        right.append(Gtk.Label(label="Folder", xalign=0))
        folder_labels = [str(item[1] or "Root") for item in folder_options]
        folder_ids = [str(item[0] or "root") for item in folder_options]
        folder_dd = Gtk.DropDown(model=Gtk.StringList.new(folder_labels))
        selected_idx = 0
        target_id = str(initial_folder_id or "root")
        for i, fid in enumerate(folder_ids):
            if fid == target_id:
                selected_idx = i
                break
        folder_dd.set_selected(selected_idx)
        right.append(folder_dd)

    right.append(Gtk.Label(label="Description", xalign=0))
    desc_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, vexpand=True)
    desc_buf = desc_view.get_buffer()
    desc_buf.set_text(str(initial_desc or ""))
    desc_scroll = Gtk.ScrolledWindow(vexpand=True, min_content_height=120)
    desc_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    desc_scroll.set_child(desc_view)
    right.append(desc_scroll)
    count_lbl = Gtk.Label(xalign=0, css_classes=["dim-label"])
    right.append(count_lbl)

    public_row = Gtk.Box(spacing=8, margin_top=6)
    public_lbl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    public_lbl_box.append(Gtk.Label(label="Make it public", xalign=0))
    public_lbl_box.append(Gtk.Label(label="Your playlist will be visible on your profile and accessible by anyone.", xalign=0, css_classes=["dim-label"]))
    public_switch = Gtk.Switch(active=bool(initial_public), halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
    public_row.append(public_lbl_box)
    public_row.append(public_switch)
    right.append(public_row)

    content.append(right)
    root.append(content)

    action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel")
    save_btn = Gtk.Button(label=save_label)
    save_btn.add_css_class("suggested-action")
    cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
    save_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
    action_row.append(cancel_btn)
    action_row.append(save_btn)
    root.append(action_row)
    dialog.set_child(root)

    def _update_count(_buf=None):
        txt = desc_buf.get_text(desc_buf.get_start_iter(), desc_buf.get_end_iter(), True) or ""
        count_lbl.set_text(f"{len(txt)}/500 characters")
        if len(txt) > 500:
            count_lbl.add_css_class("status-error")
        else:
            count_lbl.remove_css_class("status-error")
        return False

    desc_buf.connect("changed", _update_count)
    _update_count()

    def _on_response(d, resp):
        if resp != Gtk.ResponseType.OK:
            d.destroy()
            return
        title = str(title_entry.get_text() or "").strip()
        desc = desc_buf.get_text(desc_buf.get_start_iter(), desc_buf.get_end_iter(), True) or ""
        is_public = bool(public_switch.get_active())
        selected_folder_id = str(initial_folder_id or "root")
        if folder_dd is not None and folder_ids:
            idx = int(folder_dd.get_selected())
            if 0 <= idx < len(folder_ids):
                selected_folder_id = folder_ids[idx]
        d.destroy()
        if not title:
            self.show_output_notice("Playlist title cannot be empty.", "warn", 2600)
            return
        if len(desc) > 500:
            self.show_output_notice("Description is too long (max 500).", "warn", 2600)
            return
        if callable(on_submit):
            on_submit(title, desc, is_public, selected_folder_id)

    dialog.connect("response", _on_response)
    dialog.present()


def on_remote_playlist_rename_clicked(self, playlist_obj=None):
    pl = playlist_obj or getattr(self, "current_remote_playlist", None)
    if pl is None:
        return
    title_init = str(getattr(pl, "name", None) or "Untitled Playlist")
    desc_init = str(getattr(pl, "description", None) or "")
    public_init = bool(getattr(pl, "public", False))

    def _submit(title, desc, is_public, _folder_id):
        self.show_output_notice("Saving playlist...", "ok", 1800)

        def task():
            res = self.backend.update_cloud_playlist(pl, name=title, description=desc, is_public=is_public)

            def apply():
                if bool(res.get("ok")):
                    try:
                        pl.name = title
                        pl.description = desc
                        pl.public = is_public
                    except Exception:
                        pass
                    self.show_output_notice("Playlist updated.", "ok", 2400)
                    if getattr(self, "current_remote_playlist", None) is not None and getattr(self.current_remote_playlist, "id", None) == getattr(pl, "id", None):
                        self.on_remote_playlist_card_clicked(pl)
                else:
                    self.show_output_notice("Failed to update playlist.", "warn", 3200)
                return False

            GLib.idle_add(apply)

        submit_daemon(task)

    self._open_cloud_playlist_editor(
        dialog_title="Edit playlist",
        save_label="Save",
        initial_title=title_init,
        initial_desc=desc_init,
        initial_public=public_init,
        playlist_obj=pl,
        on_submit=_submit,
    )


def on_remote_playlist_delete_clicked(self, playlist_obj=None):
    pl = playlist_obj or getattr(self, "current_remote_playlist", None)
    if pl is None:
        return
    pname = str(getattr(pl, "name", None) or "this playlist")
    dialog = Gtk.Dialog(title="Delete Playlist", transient_for=self.win, modal=True)
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
    )
    root.append(Gtk.Label(label=f"Delete '{pname}' permanently?", xalign=0))
    action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel")
    delete_btn = Gtk.Button(label="Delete")
    cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
    delete_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
    action_row.append(cancel_btn)
    action_row.append(delete_btn)
    root.append(action_row)
    dialog.set_child(root)

    def _on_response(d, resp):
        if resp != Gtk.ResponseType.OK:
            d.destroy()
            return
        d.destroy()
        self.show_output_notice("Deleting playlist...", "ok", 1600)

        def task():
            res = self.backend.delete_cloud_playlist(pl)

            def apply():
                if bool(res.get("ok")):
                    self.show_output_notice("Playlist deleted.", "ok", 2200)
                    if getattr(self, "current_remote_playlist", None) is not None and getattr(self.current_remote_playlist, "id", None) == getattr(pl, "id", None):
                        self.current_remote_playlist = None
                    self.render_playlists_home()
                else:
                    self.show_output_notice("Failed to delete playlist.", "warn", 3000)
                return False

            GLib.idle_add(apply)

        submit_daemon(task)

    dialog.connect("response", _on_response)
    dialog.present()


def on_remote_playlist_move_to_folder_clicked(self, playlist_obj=None):
    pl = playlist_obj or getattr(self, "current_remote_playlist", None)
    if pl is None:
        return
    folders = [{"id": "root", "path": "Root"}] + list(self.backend.get_all_playlist_folders(limit=1000) or [])
    options = [(str(f.get("id", "root")), str(f.get("path", "Root"))) for f in folders]
    if not options:
        self.show_output_notice("No folders available.", "warn", 2400)
        return
    dialog = Gtk.Dialog(title="Move to Folder", transient_for=self.win, modal=True)
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
    )
    root.append(Gtk.Label(label="Select destination folder:", xalign=0))
    dd = Gtk.DropDown(model=Gtk.StringList.new([label for _fid, label in options]))
    dd.set_selected(0)
    root.append(dd)
    action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel")
    move_btn = Gtk.Button(label="Move")
    move_btn.add_css_class("suggested-action")
    cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
    move_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
    action_row.append(cancel_btn)
    action_row.append(move_btn)
    root.append(action_row)
    dialog.set_child(root)

    def _on_response(d, resp):
        if resp != Gtk.ResponseType.OK:
            d.destroy()
            return
        idx = int(dd.get_selected())
        target_id = options[idx][0] if 0 <= idx < len(options) else "root"
        d.destroy()
        self.show_output_notice("Moving playlist...", "ok", 1800)

        def task():
            res = self.backend.move_cloud_playlist_to_folder(pl, target_folder_id=target_id)

            def apply():
                if bool(res.get("ok")):
                    self.show_output_notice("Playlist moved.", "ok", 2200)
                    self.current_remote_playlist = None
                    self.current_playlist_folder = None
                    self.current_playlist_folder_stack = []
                    self.render_playlists_home()
                else:
                    self.show_output_notice("Failed to move playlist.", "warn", 2800)
                return False

            GLib.idle_add(apply)

        submit_daemon(task)

    dialog.connect("response", _on_response)
    dialog.present()


def on_remove_single_track_from_remote_playlist(self, track):
    pl = getattr(self, "current_remote_playlist", None)
    if pl is None or track is None:
        return

    def task():
        res = self.backend.remove_tracks_from_cloud_playlist(pl, [track])

        def apply():
            if bool(res.get("ok")):
                removed = int(res.get("removed", 0) or 0)
                self.show_output_notice(f"Removed {removed} track", "ok", 2200)
                # Refresh current remote playlist view
                self.on_remote_playlist_card_clicked(pl)
            else:
                self.show_output_notice("Failed to remove track from playlist.", "warn", 2800)
            return False

        GLib.idle_add(apply)

    submit_daemon(task)


def on_playlist_track_selected(self, box, row):
    if not row:
        return
    idx = getattr(row, "playlist_track_index", -1)
    tracks = getattr(box, "playlist_tracks", [])
    if not tracks or idx < 0 or idx >= len(tracks):
        return
    self.current_track_list = tracks
    self._set_play_queue(tracks)
    self.play_track(idx)


def _next_playlist_name(self):
    return "New Playlist"


def on_create_playlist_clicked(self, _btn=None):
    if not getattr(self.backend, "user", None):
        self._show_simple_dialog("Login Required", "Please login first.")
        return
    default_name = self._next_playlist_name()
    folder_rows = [{"id": "root", "path": "Root"}] + list(self.backend.get_all_playlist_folders(limit=1000) or [])
    folder_options = [(str(row.get("id", "root")), str(row.get("path", "Root"))) for row in folder_rows]
    initial_folder_id = "root"
    if getattr(self, "current_playlist_folder", None) is not None:
        initial_folder_id = str(getattr(self.current_playlist_folder, "id", "root") or "root")

    def _submit(name, desc, is_public, folder_id):
        self.show_output_notice("Creating cloud playlist...", "ok", 1600)

        def task():
            pl = self.backend.create_cloud_playlist_in_folder(name, desc, parent_folder_id=folder_id)
            if pl is not None and bool(is_public):
                try:
                    self.backend.update_cloud_playlist(pl, is_public=True)
                except Exception:
                    pass

            def apply():
                if pl is None:
                    self.show_output_notice("Failed to create cloud playlist.", "warn", 2600)
                    return False
                self.show_output_notice(f"Created playlist: {getattr(pl, 'name', name)}", "ok", 2200)
                self.render_playlists_home()
                return False

            GLib.idle_add(apply)

        submit_daemon(task)

    self._open_cloud_playlist_editor(
        dialog_title="Create playlist",
        save_label="Create",
        initial_title=default_name,
        initial_desc="Created from HiresTI",
        initial_public=False,
        playlist_obj=None,
        folder_options=folder_options,
        initial_folder_id=initial_folder_id,
        on_submit=_submit,
    )


def _prompt_playlist_pick(self, on_pick):
    if not getattr(self.backend, "user", None):
        self._show_simple_dialog("Login Required", "Please login first.")
        return
    playlists = list(self.backend.get_user_playlists(limit=1000) or [])
    if not playlists:
        created = self.backend.create_cloud_playlist(self._next_playlist_name(), "Created from HiresTI")
        if created is not None:
            on_pick(created, True)
        else:
            self.show_output_notice("Failed to create cloud playlist.", "warn", 2600)
        return

    dialog = Gtk.Dialog(title="Add to Playlist", transient_for=self.win, modal=True)
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
    )
    box_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
    box_wrap.append(Gtk.Label(label="Select a playlist:", xalign=0))

    names = [getattr(p, "name", None) or "Untitled Playlist" for p in playlists]
    dd = Gtk.DropDown(model=Gtk.StringList.new(names))
    dd.set_selected(0)
    box_wrap.append(dd)
    dedupe_ck = Gtk.CheckButton(label="Auto de-duplicate", active=True)
    box_wrap.append(dedupe_ck)
    root.append(box_wrap)
    action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel")
    new_btn = Gtk.Button(label="New Playlist")
    add_btn = Gtk.Button(label="Add")
    cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
    new_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.APPLY))
    add_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
    action_row.append(cancel_btn)
    action_row.append(new_btn)
    action_row.append(add_btn)
    root.append(action_row)
    dialog.set_child(root)

    def _on_response(d, resp):
        if resp == Gtk.ResponseType.OK:
            idx = dd.get_selected()
            if 0 <= idx < len(playlists):
                on_pick(playlists[idx], dedupe_ck.get_active())
        elif resp == Gtk.ResponseType.APPLY:
            created = self.backend.create_cloud_playlist(self._next_playlist_name(), "Created from HiresTI")
            if created is not None:
                on_pick(created, dedupe_ck.get_active())
            else:
                self.show_output_notice("Failed to create cloud playlist.", "warn", 2600)
        d.destroy()

    dialog.connect("response", _on_response)
    dialog.present()


def on_add_tracks_to_playlist(self, tracks):
    items = [t for t in (tracks or []) if t is not None]
    if not items:
        return

    def _do_add(playlist_obj, dedupe):
        self.show_output_notice("Adding tracks to cloud playlist...", "ok", 1800)

        def task():
            res = self.backend.add_tracks_to_cloud_playlist(playlist_obj, items, dedupe=bool(dedupe), batch_size=100)

            def apply():
                if bool(res.get("ok")):
                    added = int(res.get("added", 0) or 0)
                    requested = int(res.get("requested", 0) or 0)
                    skipped = max(0, requested - added)
                    msg = f"Added {added} tracks"
                    if skipped:
                        msg += f" (skipped {skipped})"
                    self.show_output_notice(msg, "ok", 2600)
                else:
                    self.show_output_notice("Failed to add tracks to cloud playlist.", "warn", 3000)
                return False

            GLib.idle_add(apply)

        submit_daemon(task)

    self._prompt_playlist_pick(_do_add)


def on_add_single_track_to_playlist(self, track):
    if track is None:
        return
    self.on_add_tracks_to_playlist([track])


def on_add_current_album_to_playlist(self, _btn=None):
    tracks = list(getattr(self, "current_track_list", []) or [])
    if not tracks:
        return
    self.on_add_tracks_to_playlist(tracks)


def _prompt_playlist_name(
    self,
    title,
    initial_name,
    on_submit,
    subtitle=None,
    placeholder=None,
    save_label="Save",
    dialog_size=None,
):
    dialog = Gtk.Dialog(title=title, transient_for=self.win, modal=True)
    if dialog_size:
        try:
            dialog.set_default_size(int(dialog_size[0]), int(dialog_size[1]))
        except Exception:
            pass
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=14,
        margin_top=14,
        margin_bottom=14,
        margin_start=14,
        margin_end=14,
    )
    title_lbl = Gtk.Label(label=str(title or ""), xalign=0, css_classes=["home-section-title"])
    root.append(title_lbl)
    if subtitle:
        root.append(Gtk.Label(label=str(subtitle), xalign=0, css_classes=["dim-label"]))
    entry = Gtk.Entry(text=initial_name or "")
    if placeholder:
        entry.set_placeholder_text(str(placeholder))
    entry.connect("activate", lambda _e: dialog.response(Gtk.ResponseType.OK))
    root.append(entry)
    action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel")
    save_btn = Gtk.Button(label=str(save_label or "Save"), css_classes=["suggested-action"])
    cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
    save_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
    action_row.append(cancel_btn)
    action_row.append(save_btn)
    root.append(action_row)
    dialog.set_child(root)

    def _on_response(d, resp):
        if resp == Gtk.ResponseType.OK:
            on_submit(entry.get_text().strip())
        d.destroy()

    dialog.connect("response", _on_response)
    dialog.present()
    entry.grab_focus()


def on_playlist_start_inline_rename(self, playlist_id):
    self.playlist_rename_mode = True
    self.render_playlist_detail(playlist_id)


def on_playlist_commit_inline_rename(self, playlist_id, name):
    new_name = (name or "").strip()
    if new_name:
        self.playlist_mgr.rename_playlist(playlist_id, new_name)
    self.playlist_rename_mode = False
    self.render_playlist_detail(playlist_id)


def on_playlist_cancel_inline_rename(self, playlist_id):
    self.playlist_rename_mode = False
    self.render_playlist_detail(playlist_id)


def on_playlist_delete_clicked(self, playlist_id):
    dialog = Gtk.Dialog(title="Delete Playlist", transient_for=self.win, modal=True)
    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=12,
        margin_top=12,
        margin_bottom=12,
        margin_start=12,
        margin_end=12,
    )
    root.append(Gtk.Label(label="Delete this playlist permanently?", xalign=0))
    action_row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel")
    delete_btn = Gtk.Button(label="Delete")
    cancel_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.CANCEL))
    delete_btn.connect("clicked", lambda _b: dialog.response(Gtk.ResponseType.OK))
    action_row.append(cancel_btn)
    action_row.append(delete_btn)
    root.append(action_row)
    dialog.set_child(root)

    def _on_response(d, resp):
        if resp == Gtk.ResponseType.OK:
            self.playlist_mgr.delete_playlist(playlist_id)
            self.current_playlist_id = None
            self.render_playlists_home()
        d.destroy()

    dialog.connect("response", _on_response)
    dialog.present()


def on_playlist_remove_track_clicked(self, playlist_id, track_index):
    self.playlist_mgr.remove_track(playlist_id, track_index)
    self.render_playlist_detail(playlist_id)


def on_playlist_move_track_clicked(self, playlist_id, track_index, direction):
    self.playlist_mgr.move_track(playlist_id, track_index, direction)
    self.render_playlist_detail(playlist_id)


def on_playlist_toggle_edit(self, _btn=None):
    self.playlist_edit_mode = not bool(getattr(self, "playlist_edit_mode", False))
    if self.current_playlist_id:
        self.render_playlist_detail(self.current_playlist_id)


def on_playlist_reorder_track(self, playlist_id, from_index, to_index):
    if self.playlist_mgr.move_track_to(playlist_id, from_index, to_index):
        self.render_playlist_detail(playlist_id)
