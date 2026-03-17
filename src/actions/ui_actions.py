from threading import Thread
import logging
import os
import random
import time
from datetime import datetime
import subprocess
from hashlib import blake2b
from types import SimpleNamespace

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango, Gdk, GObject

import utils.helpers as utils
from _rust.viz import RustVizCore
from ui import config as ui_config
from ui.track_table import LAYOUT, build_tracks_header, append_header_action_spacers
from core.errors import classify_exception, user_message

logger = logging.getLogger(__name__)
MAX_SEARCH_HISTORY = 10
DASHBOARD_TRACK_COVER_SIZE = 70
_RUST_COLLECTION_CORE = None


def _get_rust_collection_core():
    global _RUST_COLLECTION_CORE
    if _RUST_COLLECTION_CORE is None:
        try:
            _RUST_COLLECTION_CORE = RustVizCore()
        except Exception:
            _RUST_COLLECTION_CORE = False
    return _RUST_COLLECTION_CORE if _RUST_COLLECTION_CORE is not False else None


def _stable_u64_from_text(text):
    raw = str(text or "").encode("utf-8", "ignore")
    digest = blake2b(raw, digest_size=8).digest()
    return int.from_bytes(digest, byteorder="little", signed=False)


def _build_rank(values):
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    rank = [0] * len(values)
    for r, i in enumerate(order):
        rank[i] = r
    return rank


def _is_home_context_kicker(text):
    low = str(text or "").strip().lower()
    return low in {
        "because you liked",
        "because you listened to",
    }


def _home_section_header_lines(section):
    title = str((section or {}).get("title", "") or "").strip()
    subtitle = str((section or {}).get("subtitle", "") or (section or {}).get("sub_title", "") or "").strip()
    section_type = str((section or {}).get("section_type", "") or "").strip().upper()
    context_header = (section or {}).get("context_header") or {}
    context_title = str((context_header or {}).get("name", "") or "").strip()
    if section_type == "HORIZONTAL_LIST_WITH_CONTEXT" and title and context_title:
        return {"title": context_title, "kicker": title, "secondary": ""}
    if section_type == "HORIZONTAL_LIST_WITH_CONTEXT" and title and subtitle:
        return {"title": subtitle, "kicker": title, "secondary": ""}
    if title and subtitle and _is_home_context_kicker(title):
        return {"title": subtitle, "kicker": title, "secondary": ""}
    if title and subtitle and _is_home_context_kicker(subtitle):
        return {"title": title, "kicker": subtitle, "secondary": ""}
    return {"title": title, "kicker": "", "secondary": subtitle}


def _home_card_subtitle_text(text):
    subtitle = str(text or "").strip()
    if subtitle:
        return subtitle
    # Keep a blank subtitle row so home-card heights stay stable across sections.
    return " "


def _feed_card_classes(*extra_classes):
    classes = ["card", "home-card", "home-feed-card"]
    for cls in extra_classes:
        if cls and cls not in classes:
            classes.append(cls)
    return classes


def _artist_card_classes(*extra_classes):
    return _feed_card_classes("artist-feed-card", *extra_classes)


def _feed_tint_classes(*shape_classes):
    classes = ["home-feed-tint"]
    for cls in shape_classes:
        if cls and cls not in classes:
            classes.append(cls)
    return classes


def _dashboard_track_row_button_classes(is_playing=False):
    classes = ["flat", "history-card-btn", "dashboard-track-row-btn"]
    if is_playing:
        classes.append("track-row-playing")
    return classes


def _norm_trackish_text(value):
    s = str(value or "").strip().lower()
    keep = []
    for ch in s:
        if ch.isalnum() or ch.isspace():
            keep.append(ch)
    return " ".join("".join(keep).split())


def _normalized_section_key(value):
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _filter_hires_sections(sections):
    visible_sections = list(sections or [])
    if len(visible_sections) <= 1:
        return visible_sections

    filtered_sections = [
        sec for sec in visible_sections if _normalized_section_key((sec or {}).get("title")) != "hires"
    ]
    return filtered_sections or visible_sections


def _liked_tracks_signature(tracks):
    items = list(tracks or [])
    digest = blake2b(digest_size=8)
    digest.update(str(len(items)).encode("utf-8", "ignore"))
    digest.update(b":")
    for track in items:
        digest.update(str(getattr(track, "id", "") or "").encode("utf-8", "ignore"))
        digest.update(b"\n")
    return (len(items), digest.hexdigest())


def _build_feed_media_tint(media_size, *shape_classes):
    tint = Gtk.Box(css_classes=_feed_tint_classes(*shape_classes))
    tint.set_size_request(int(media_size), int(media_size))
    tint.set_halign(Gtk.Align.FILL)
    tint.set_valign(Gtk.Align.FILL)
    try:
        tint.set_can_target(False)
    except Exception:
        pass
    return tint


def _build_feed_media_overlay(media_widget, media_size, *shape_classes):
    if not hasattr(Gtk, "Overlay"):
        return media_widget
    overlay = Gtk.Overlay(css_classes=["home-feed-media"])
    overlay.set_halign(Gtk.Align.CENTER)
    overlay.set_valign(Gtk.Align.START)
    overlay.set_size_request(int(media_size), int(media_size))
    overlay.set_child(media_widget)
    overlay.add_overlay(_build_feed_media_tint(media_size, *shape_classes))
    return overlay


def _home_card_layout(item_data, cover_size):
    item_type = str((item_data or {}).get("type") or "")
    item_name = str((item_data or {}).get("name") or "")
    img_size = int(cover_size)
    img_cls = "album-cover-img"
    card_classes = _feed_card_classes()
    if item_type == "Track":
        img_size = 88
        card_classes.append("home-track-card")
    elif item_type == "Artist" or "Radio" in item_name:
        img_size = 150
        img_cls = "circular-avatar"
    # Keep Home feed cards as tight as possible to the media slot so hover
    # chrome does not introduce a visibly wider gutter around artwork.
    card_width = max(88, int(img_size))
    # Clamp title/subtitle width so GTK does not widen FlowBox cells based on
    # long natural label widths in certain Top/New tabs.
    text_width_chars = max(10, int((card_width - 24) / 9))
    return {
        "card_width": card_width,
        "img_size": int(img_size),
        "img_cls": img_cls,
        "card_classes": card_classes,
        "text_width_chars": text_width_chars,
    }


def _build_feed_item_button(app, item_data, on_click):
    layout = _home_card_layout(item_data, utils.COVER_SIZE)
    card_width = layout["card_width"]
    img_size = layout["img_size"]
    img_cls = layout["img_cls"]
    text_width_chars = layout["text_width_chars"]
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=layout["card_classes"])
    v.set_size_request(card_width, -1)
    img = Gtk.Picture(css_classes=[img_cls])
    img.set_size_request(img_size, img_size)
    img.set_can_shrink(True)
    try:
        img.set_content_fit(Gtk.ContentFit.COVER)
    except Exception:
        pass
    media_widget = img
    if item_data["image_url"]:
        utils.load_img(img, item_data["image_url"], app.cache_dir, img_size)
    else:
        fallback = Gtk.Image(icon_name="audio-x-generic-symbolic", pixel_size=img_size, css_classes=[img_cls])
        fallback.set_size_request(img_size, img_size)
        media_widget = fallback
    media = _build_feed_media_overlay(media_widget, img_size, img_cls)
    v.append(media)
    title_text = str(item_data.get("name") or "Unknown")
    title_label = Gtk.Label(
        label=title_text,
        ellipsize=3,
        halign=Gtk.Align.CENTER,
        wrap=False,
        width_chars=text_width_chars,
        max_width_chars=text_width_chars,
        css_classes=["heading", "home-card-title"],
    )
    title_label.set_tooltip_text(title_text)
    v.append(title_label)

    subtitle_raw = str(item_data.get("sub_title") or "").strip()
    subtitle_label = Gtk.Label(
        label=_home_card_subtitle_text(subtitle_raw),
        ellipsize=3,
        halign=Gtk.Align.CENTER,
        wrap=False,
        width_chars=text_width_chars,
        max_width_chars=text_width_chars,
        css_classes=["dim-label", "home-card-subtitle"],
    )
    if subtitle_raw:
        subtitle_label.set_tooltip_text(subtitle_raw)
    v.append(subtitle_label)
    btn = Gtk.Button(css_classes=["flat", "history-card-btn", "home-feed-btn"])
    btn.set_size_request(card_width, -1)
    btn.set_child(v)
    btn.connect("clicked", lambda _b, d=item_data: on_click(d))
    return btn


def _album_title_text(album):
    return str(getattr(album, "title", getattr(album, "name", "Unknown Album")) or "Unknown Album")


def _album_release_year_text(album):
    release_date = getattr(album, "release_date", None)
    if not release_date:
        return ""
    year = getattr(release_date, "year", None)
    if year:
        return str(year)
    text = str(release_date).strip()
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return ""


def _album_artist_name_text(album):
    artist = getattr(album, "artist", None)
    if isinstance(artist, str):
        name = artist.strip()
    else:
        name = str(getattr(artist, "name", "") or "").strip()
    return name or "Unknown"


def _album_artist_year_subtitle_text(album):
    artist_name = _album_artist_name_text(album)
    year = _album_release_year_text(album)
    if year:
        return f"{artist_name}  •  {year}"
    return artist_name


def _album_year_subtitle_text(album):
    year = _album_release_year_text(album)
    if year:
        return year
    return _album_artist_name_text(album)


def _build_my_albums_style_button(app, album, on_click):
    card = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=6,
        css_classes=_feed_card_classes("history-card"),
    )
    img = Gtk.Image(pixel_size=utils.COVER_SIZE, css_classes=["album-cover-img"])
    img.set_from_icon_name("audio-x-generic-symbolic")
    utils.load_img(
        img,
        lambda a=album: app.backend.get_artwork_url(a, 320),
        app.cache_dir,
        utils.COVER_SIZE,
    )
    card.append(_build_feed_media_overlay(img, utils.COVER_SIZE, "album-cover-img"))
    card.append(
        Gtk.Label(
            label=_album_title_text(album),
            halign=Gtk.Align.CENTER,
            ellipsize=3,
            max_width_chars=14,
            css_classes=["home-card-title"],
        )
    )
    subtitle = _album_artist_year_subtitle_text(album)
    subtitle_label = Gtk.Label(
        label=subtitle,
        halign=Gtk.Align.CENTER,
        ellipsize=3,
        max_width_chars=18,
        css_classes=["dim-label", "home-card-subtitle"],
    )
    subtitle_label.set_tooltip_text(subtitle)
    card.append(subtitle_label)
    btn = Gtk.Button(css_classes=["flat", "history-card-btn", "home-feed-btn"])
    btn.set_child(card)
    btn.connect("clicked", lambda _btn, a=album: on_click(a))
    return btn


def sort_objects_by_name_fast(items, context="items"):
    objs = list(items or [])
    n = len(objs)
    if n <= 1:
        return objs

    names_lc = [str(getattr(o, "name", "") or "").lower() for o in objs]
    title_rank = _build_rank(names_lc)
    zeros = [0] * n
    indices = None

    rust_core = _get_rust_collection_core()
    if rust_core is not None and getattr(rust_core, "available", False):
        try:
            indices = rust_core.filter_sort_indices_no_query(
                artist_keys=zeros,
                title_rank=title_rank,
                artist_rank=zeros,
                album_rank=zeros,
                durations=zeros,
                sort_mode=1,  # title
                artist_filter_key=0,
                use_artist_filter=False,
            )
            logger.info("Collection name sort path: Rust (%s, total=%s)", context, n)
        except Exception:
            indices = None
            logger.exception("Rust name sort failed; fallback to Python (%s)", context)

    if indices is None:
        logger.info("Collection name sort path: Python-fallback (%s, total=%s)", context, n)
        indices = sorted(range(n), key=lambda i: (names_lc[i], i))

    return [objs[i] for i in indices if 0 <= int(i) < n]

try:
    from opencc import OpenCC
except Exception:
    OpenCC = None

_OPENCC_S2T = None
_OPENCC_T2S = None
if OpenCC is not None:
    try:
        _OPENCC_S2T = OpenCC("s2t")
        _OPENCC_T2S = OpenCC("t2s")
    except Exception:
        _OPENCC_S2T = None
        _OPENCC_T2S = None

# Built-in fallback map for common Simplified/Traditional conversion.
# This keeps zh search usable even when OpenCC is unavailable.
_S2T_CHAR_MAP = {
    "后": "後", "来": "來", "爱": "愛", "国": "國", "风": "風", "台": "臺", "万": "萬", "与": "與",
    "云": "雲", "乐": "樂", "为": "為", "广": "廣", "东": "東", "业": "業", "丛": "叢", "丝": "絲",
    "两": "兩", "严": "嚴", "个": "個", "丰": "豐", "临": "臨", "丽": "麗", "举": "舉", "义": "義",
    "乌": "烏", "乔": "喬", "习": "習", "乡": "鄉", "书": "書", "买": "買", "乱": "亂", "争": "爭",
    "于": "於", "亏": "虧", "亚": "亞", "产": "產", "亲": "親", "亿": "億", "仅": "僅", "从": "從",
    "仓": "倉", "仪": "儀", "们": "們", "价": "價", "众": "眾", "优": "優", "会": "會", "伟": "偉",
    "传": "傳", "伤": "傷", "伦": "倫", "伪": "偽", "体": "體", "余": "餘", "佛": "彿", "侠": "俠",
    "侣": "侶", "侥": "僥", "侧": "側", "侨": "僑", "侦": "偵", "侨": "僑", "俩": "倆", "俭": "儉",
    "债": "債", "倾": "傾", "储": "儲", "儿": "兒", "党": "黨", "兰": "蘭", "关": "關", "兴": "興",
    "兹": "茲", "养": "養", "兽": "獸", "冈": "岡", "册": "冊", "写": "寫", "军": "軍", "农": "農",
    "冯": "馮", "冰": "氷", "冲": "沖", "决": "決", "况": "況", "冻": "凍", "净": "淨", "减": "減",
    "凑": "湊", "凛": "凜", "几": "幾", "凤": "鳳", "凯": "凱", "击": "擊", "凿": "鑿", "刍": "芻",
    "刘": "劉", "则": "則", "刚": "剛", "创": "創", "删": "刪", "别": "別", "刬": "剷", "刭": "剄",
    "刹": "剎", "剂": "劑", "剑": "劍", "剥": "剝", "剧": "劇", "劝": "勸", "办": "辦", "务": "務",
    "动": "動", "励": "勵", "劳": "勞", "势": "勢", "勋": "勳", "匀": "勻", "华": "華", "协": "協",
    "单": "單", "卖": "賣", "卢": "盧", "卧": "臥", "卫": "衛", "却": "卻", "厂": "廠", "厅": "廳",
    "历": "歷", "厉": "厲", "压": "壓", "厌": "厭", "厕": "廁", "厘": "釐", "县": "縣", "参": "參",
    "双": "雙", "发": "發", "变": "變", "叙": "敘", "叶": "葉", "号": "號", "叹": "嘆", "叽": "嘰",
    "吁": "籲", "吃": "喫", "合": "閤", "吊": "弔", "吗": "嗎", "后": "後", "向": "嚮", "吓": "嚇",
    "吕": "呂", "吗": "嗎", "听": "聽", "启": "啟", "吴": "吳", "呆": "獃", "员": "員", "呜": "嗚",
    "咏": "詠", "咙": "嚨", "咸": "鹹", "响": "響", "哗": "嘩", "唇": "脣", "唤": "喚", "啰": "囉",
    "啸": "嘯", "喷": "噴", "嘱": "囑", "团": "團", "园": "園", "围": "圍", "图": "圖", "圆": "圓",
    "圣": "聖", "场": "場", "坏": "壞", "坚": "堅", "坛": "壇", "坝": "壩", "坞": "塢", "垄": "壟",
    "垦": "墾", "垫": "墊", "埘": "塒", "堑": "塹", "墙": "牆", "壮": "壯", "声": "聲", "壳": "殼",
    "壶": "壺", "处": "處", "备": "備", "复": "復", "够": "夠", "头": "頭", "夹": "夾", "夺": "奪",
    "奋": "奮", "奖": "獎", "妆": "妝", "妇": "婦", "妈": "媽", "妩": "嫵", "娱": "娛", "娄": "婁",
    "娅": "婭", "娇": "嬌", "孙": "孫", "学": "學", "宁": "寧", "宝": "寶", "实": "實", "宠": "寵",
    "审": "審", "宪": "憲", "宫": "宮", "宽": "寬", "宾": "賓", "对": "對", "导": "導", "寿": "壽",
    "将": "將", "尘": "塵", "尝": "嘗", "层": "層", "属": "屬", "屿": "嶼", "岁": "歲", "岂": "豈",
    "岗": "崗", "岛": "島", "岭": "嶺", "岳": "嶽", "峡": "峽", "币": "幣", "帅": "帥", "师": "師",
    "帐": "帳", "帘": "簾", "带": "帶", "帮": "幫", "库": "庫", "应": "應", "庙": "廟", "庞": "龐",
    "废": "廢", "开": "開", "异": "異", "弃": "棄", "张": "張", "弥": "彌", "弯": "彎", "弹": "彈",
    "强": "強", "归": "歸", "当": "當", "录": "錄", "彦": "彥", "彻": "徹", "征": "徵", "径": "徑",
    "御": "禦", "忆": "憶", "志": "誌", "忧": "憂", "怀": "懷", "态": "態", "总": "總", "恋": "戀",
    "恒": "恆", "恶": "惡", "恼": "惱", "悦": "悅", "悬": "懸", "惊": "驚", "惧": "懼", "惨": "慘",
    "惯": "慣", "戏": "戲", "战": "戰", "户": "戶", "扎": "紮", "扑": "撲", "执": "執", "扩": "擴",
    "扫": "掃", "扬": "揚", "扰": "擾", "抚": "撫", "抛": "拋", "抟": "摶", "抢": "搶", "护": "護",
    "报": "報", "担": "擔", "拟": "擬", "拢": "攏", "拣": "揀", "拥": "擁", "拦": "攔", "拧": "擰",
    "拨": "撥", "择": "擇", "挂": "掛", "挚": "摯", "挠": "撓", "挡": "擋", "挣": "掙", "挥": "揮",
    "挤": "擠", "捞": "撈", "损": "損", "换": "換", "据": "據", "掳": "擄", "掷": "擲", "掸": "撣",
    "掺": "摻", "掼": "摜", "揽": "攬", "搀": "攙", "摄": "攝", "摊": "攤", "撑": "撐", "撵": "攆",
    "敌": "敵", "数": "數", "斋": "齋", "断": "斷", "旧": "舊", "时": "時", "旷": "曠", "旺": "旺",
    "昆": "崑", "昙": "曇", "显": "顯", "晋": "晉", "晒": "曬", "晓": "曉", "晚": "晚", "暂": "暫",
    "术": "術", "机": "機", "杀": "殺", "杂": "雜", "权": "權", "条": "條", "来": "來", "杨": "楊",
    "杰": "傑", "松": "鬆", "极": "極", "构": "構", "枪": "槍", "枣": "棗", "柜": "櫃", "柠": "檸",
    "查": "查", "栅": "柵", "标": "標", "栈": "棧", "栋": "棟", "栏": "欄", "树": "樹", "样": "樣",
    "档": "檔", "桥": "橋", "梦": "夢", "检": "檢", "楼": "樓", "横": "橫", "欢": "歡", "欧": "歐",
    "欲": "慾", "歼": "殲", "殁": "歿", "残": "殘", "殴": "毆", "毁": "毀", "毕": "畢", "毡": "氈",
    "气": "氣", "汉": "漢", "汤": "湯", "沟": "溝", "没": "沒", "沣": "灃", "沦": "淪", "沧": "滄",
    "沪": "滬", "泪": "淚", "泽": "澤", "洁": "潔", "洒": "灑", "浇": "澆", "浊": "濁", "测": "測",
    "济": "濟", "浏": "瀏", "浓": "濃", "涂": "塗", "涛": "濤", "涝": "澇", "润": "潤", "涩": "澀",
    "涡": "渦", "涨": "漲", "渔": "漁", "湾": "灣", "湿": "濕", "温": "溫", "溃": "潰", "滚": "滾",
    "满": "滿", "滤": "濾", "滥": "濫", "灭": "滅", "灯": "燈", "灵": "靈", "灾": "災", "炉": "爐",
    "炜": "煒", "点": "點", "炼": "煉", "烁": "爍", "烂": "爛", "热": "熱", "焕": "煥", "爱": "愛",
    "爷": "爺", "牍": "牘", "状": "狀", "犹": "猶", "猎": "獵", "猫": "貓", "献": "獻", "玛": "瑪",
    "环": "環", "现": "現", "珑": "瓏", "琐": "瑣", "琼": "瓊", "画": "畫", "畅": "暢", "疗": "療",
    "疟": "瘧", "疮": "瘡", "疯": "瘋", "痉": "痙", "痒": "癢", "瘫": "癱", "瘾": "癮", "盐": "鹽",
    "监": "監", "盖": "蓋", "盘": "盤", "着": "著", "矫": "矯", "矿": "礦", "码": "碼", "确": "確",
    "礼": "禮", "祷": "禱", "祸": "禍", "禅": "禪", "离": "離", "秃": "禿", "种": "種", "称": "稱",
    "稳": "穩", "稻": "稻", "穷": "窮", "窃": "竊", "竞": "競", "笔": "筆", "笋": "筍", "筑": "築",
    "签": "簽", "简": "簡", "粮": "糧", "紧": "緊", "纠": "糾", "红": "紅", "约": "約", "级": "級",
    "纪": "紀", "纣": "紂", "纤": "纖", "纲": "綱", "纳": "納", "纵": "縱", "纷": "紛", "纸": "紙",
    "纹": "紋", "纺": "紡", "纽": "紐", "线": "線", "练": "練", "组": "組", "绅": "紳", "细": "細",
    "织": "織", "终": "終", "绊": "絆", "绍": "紹", "经": "經", "绑": "綁", "绒": "絨", "结": "結",
    "绕": "繞", "绘": "繪", "给": "給", "络": "絡", "绝": "絕", "统": "統", "绢": "絹", "绣": "繡",
    "绥": "綏", "继": "繼", "续": "續", "缆": "纜", "缔": "締", "编": "編", "缘": "緣", "缠": "纏",
    "罢": "罷", "罗": "羅", "罚": "罰", "羡": "羨", "习": "習", "翘": "翹", "耕": "耕", "耻": "恥",
    "聋": "聾", "职": "職", "联": "聯", "肃": "肅", "肠": "腸", "肤": "膚", "肾": "腎", "肿": "腫",
    "胆": "膽", "胜": "勝", "胶": "膠", "脑": "腦", "脚": "腳", "脱": "脫", "脸": "臉", "脏": "臟",
    "腊": "臘", "腾": "騰", "舱": "艙", "舰": "艦", "艺": "藝", "节": "節", "芦": "蘆", "苏": "蘇",
    "苹": "蘋", "范": "範", "茧": "繭", "荐": "薦", "荡": "蕩", "荣": "榮", "药": "藥", "莲": "蓮",
    "获": "獲", "莹": "瑩", "营": "營", "萧": "蕭", "萨": "薩", "蓝": "藍", "蔼": "藹", "虏": "虜",
    "虑": "慮", "虫": "蟲", "虾": "蝦", "虽": "雖", "蚀": "蝕", "蚁": "蟻", "蛮": "蠻", "补": "補",
    "装": "裝", "裤": "褲", "见": "見", "观": "觀", "规": "規", "觅": "覓", "视": "視", "觉": "覺",
    "览": "覽", "触": "觸", "誉": "譽", "计": "計", "订": "訂", "认": "認", "讥": "譏", "讨": "討",
    "让": "讓", "训": "訓", "议": "議", "讯": "訊", "记": "記", "讲": "講", "讳": "諱", "讶": "訝",
    "讷": "訥", "许": "許", "论": "論", "讽": "諷", "设": "設", "访": "訪", "证": "證", "评": "評",
    "识": "識", "诈": "詐", "诉": "訴", "诊": "診", "词": "詞", "译": "譯", "试": "試", "诗": "詩",
    "诚": "誠", "话": "話", "诞": "誕", "询": "詢", "该": "該", "详": "詳", "诧": "詫", "诫": "誡",
    "诬": "誣", "语": "語", "误": "誤", "诱": "誘", "说": "說", "请": "請", "诸": "諸", "诺": "諾",
    "读": "讀", "课": "課", "谁": "誰", "调": "調", "谅": "諒", "谈": "談", "谋": "謀", "谊": "誼",
    "谜": "謎", "谢": "謝", "谣": "謠", "谨": "謹", "谱": "譜", "谭": "譚", "贝": "貝", "贞": "貞",
    "负": "負", "贡": "貢", "财": "財", "责": "責", "贤": "賢", "败": "敗", "账": "賬", "货": "貨",
    "质": "質", "贩": "販", "贪": "貪", "贫": "貧", "购": "購", "贯": "貫", "贴": "貼", "贵": "貴",
    "贷": "貸", "贸": "貿", "费": "費", "贺": "賀", "贼": "賊", "赁": "賃", "赂": "賂", "资": "資",
    "赐": "賜", "赏": "賞", "赔": "賠", "赖": "賴", "赚": "賺", "赛": "賽", "赞": "贊", "赠": "贈",
    "赵": "趙", "赶": "趕", "趋": "趨", "跃": "躍", "车": "車", "轨": "軌", "轩": "軒", "转": "轉",
    "轮": "輪", "软": "軟", "轰": "轟", "轻": "輕", "载": "載", "轿": "轎", "较": "較", "辅": "輔",
    "辉": "輝", "辈": "輩", "输": "輸", "辞": "辭", "边": "邊", "达": "達", "迁": "遷", "过": "過",
    "还": "還", "这": "這", "进": "進", "远": "遠", "违": "違", "连": "連", "迟": "遲", "适": "適",
    "选": "選", "逊": "遜", "递": "遞", "逻": "邏", "遗": "遺", "邓": "鄧", "郑": "鄭", "邻": "鄰",
    "郁": "鬱", "邮": "郵", "郏": "郟", "郸": "鄲", "酝": "醞", "酱": "醬", "酿": "釀", "释": "釋",
    "里": "裡", "鉴": "鑑", "铜": "銅", "银": "銀", "锅": "鍋", "锣": "鑼", "锤": "錘", "错": "錯",
    "锻": "鍛", "键": "鍵", "镇": "鎮", "镜": "鏡", "长": "長", "门": "門", "闩": "閂", "闪": "閃",
    "闭": "閉", "问": "問", "闯": "闖", "闲": "閒", "闷": "悶", "闸": "閘", "闹": "鬧", "闻": "聞",
    "闽": "閩", "阁": "閣", "阅": "閱", "阔": "闊", "队": "隊", "阳": "陽", "阴": "陰", "阵": "陣",
    "阶": "階", "际": "際", "陆": "陸", "陈": "陳", "随": "隨", "隐": "隱", "隶": "隸", "难": "難",
    "雏": "雛", "雾": "霧", "静": "靜", "页": "頁", "顶": "頂", "项": "項", "顺": "順", "须": "須",
    "顾": "顧", "顿": "頓", "颁": "頒", "预": "預", "领": "領", "频": "頻", "题": "題", "颜": "顏",
    "额": "額", "风": "風", "飞": "飛", "饭": "飯", "饮": "飲", "饲": "飼", "饱": "飽", "饼": "餅",
    "馆": "館", "马": "馬", "驭": "馭", "驴": "驢", "驰": "馳", "驱": "驅", "验": "驗", "骂": "罵",
    "骑": "騎", "骗": "騙", "骄": "驕", "骨": "骨", "鱼": "魚", "鲁": "魯", "鲜": "鮮", "鸟": "鳥",
    "鸣": "鳴", "鸥": "鷗", "鸡": "雞", "鹅": "鵝", "鹤": "鶴", "麦": "麥", "黄": "黃", "黉": "黌",
    "齐": "齊", "龙": "龍", "卷": "捲",
}

_S2T_PHRASE_MAP = {
    "后来": "後來",
    "后台": "後臺",
    "台风": "颱風",
    "台湾": "臺灣",
    "发展": "發展",
    "发行": "發行",
    "发现": "發現",
    "发明": "發明",
    "头发": "頭髮",
    "理发": "理髮",
    "音乐": "音樂",
    "乐队": "樂隊",
    "乐坛": "樂壇",
    "乐迷": "樂迷",
}
_T2S_CHAR_MAP = {v: k for k, v in _S2T_CHAR_MAP.items()}
_T2S_PHRASE_MAP = {v: k for k, v in _S2T_PHRASE_MAP.items()}

def set_search_status(app, message=None):
    if not hasattr(app, "search_status_label"):
        return
    if message:
        app.search_status_label.set_text(message)
        app.search_status_label.set_visible(True)
    else:
        app.search_status_label.set_text("")
        app.search_status_label.set_visible(False)

def _clear_container(container):
    while child := container.get_first_child():
        container.remove(child)


def _normalize_search_text(value):
    return str(value or "").strip().lower()


def _contains_cjk(text):
    for ch in str(text or ""):
        code = ord(ch)
        if (
            0x3400 <= code <= 0x4DBF
            or 0x4E00 <= code <= 0x9FFF
            or 0xF900 <= code <= 0xFAFF
        ):
            return True
    return False


def _opencc_cli_convert(text, config):
    try:
        proc = subprocess.run(
            ["opencc", "-c", config],
            input=str(text),
            text=True,
            capture_output=True,
            check=False,
            timeout=0.35,
        )
        if proc.returncode == 0:
            out = str(proc.stdout or "").strip()
            return out or str(text)
    except Exception:
        pass
    return str(text)


def _convert_by_builtin_map(text, phrase_map, char_map):
    src = str(text or "")
    if not src:
        return src
    out = src
    for frm in sorted(phrase_map.keys(), key=len, reverse=True):
        out = out.replace(frm, phrase_map[frm])
    return "".join(char_map.get(ch, ch) for ch in out)


def _generate_search_variants(query):
    base = str(query or "").strip()
    if not base:
        return []
    variants = [base]
    if not _contains_cjk(base):
        return variants

    conv_candidates = []
    if _OPENCC_S2T is not None:
        try:
            conv_candidates.append(_OPENCC_S2T.convert(base))
        except Exception:
            pass
    if _OPENCC_T2S is not None:
        try:
            conv_candidates.append(_OPENCC_T2S.convert(base))
        except Exception:
            pass
    if not conv_candidates:
        conv_candidates.extend(
            [
                _opencc_cli_convert(base, "s2t.json"),
                _opencc_cli_convert(base, "t2s.json"),
            ]
        )
    conv_candidates.extend(
        [
            _convert_by_builtin_map(base, _S2T_PHRASE_MAP, _S2T_CHAR_MAP),
            _convert_by_builtin_map(base, _T2S_PHRASE_MAP, _T2S_CHAR_MAP),
        ]
    )

    seen = {base}
    for item in conv_candidates:
        txt = str(item or "").strip()
        if txt and txt not in seen:
            seen.add(txt)
            variants.append(txt)
    return variants


def _build_local_search_results(app, queries, playlist_limit=12, history_limit=24):
    terms = [_normalize_search_text(q) for q in (queries or []) if _normalize_search_text(q)]
    if not terms:
        return {"playlists": [], "history_tracks": []}

    playlists = []
    if hasattr(app, "playlist_mgr") and app.playlist_mgr is not None:
        matched = []
        for p in app.playlist_mgr.list_playlists():
            if not isinstance(p, dict):
                continue
            name = str(p.get("name") or "")
            name_l = name.lower()
            score = 0
            best_term_len = 0
            for q in terms:
                if q in name_l:
                    term_len = len(q)
                    local_score = 200 if name_l.startswith(q) else 140
                    if local_score > score or (local_score == score and term_len > best_term_len):
                        score = local_score
                        best_term_len = term_len
            if score == 0:
                for tr in p.get("tracks", []):
                    tname = str(tr.get("track_name") or "").lower()
                    aname = str(tr.get("artist") or "").lower()
                    alb = str(tr.get("album_name") or "").lower()
                    for q in terms:
                        if q in tname:
                            score = max(score, 110)
                            break
                        if q in aname:
                            score = max(score, 90)
                            break
                        if q in alb:
                            score = max(score, 80)
                            break
                    if score > 0:
                        break
            if score > 0:
                matched.append((score, int(p.get("updated_at") or 0), p))

        matched.sort(key=lambda x: (-x[0], -x[1]))
        playlists = [x[2] for x in matched[:playlist_limit]]

    history_tracks = []
    if hasattr(app, "history_mgr") and app.history_mgr is not None:
        seen = set()
        for e in app.history_mgr.get_recent_track_entries(limit=500):
            tname = str(e.get("track_name") or "").lower()
            aname = str(e.get("artist") or "").lower()
            alb = str(e.get("album_name") or "").lower()
            if not any(q in tname or q in aname or q in alb for q in terms):
                continue
            tid = str(e.get("track_id") or "")
            if tid and tid in seen:
                continue
            tr = app.history_mgr.to_local_track(e)
            if tr is None:
                continue
            if tid:
                seen.add(tid)
            history_tracks.append(tr)
            if len(history_tracks) >= history_limit:
                break

    return {"playlists": playlists, "history_tracks": history_tracks}


def _obj_identity(obj):
    if obj is None:
        return None
    oid = getattr(obj, "id", None)
    if oid:
        return f"id:{oid}"
    name = getattr(obj, "name", None) or getattr(obj, "title", None)
    artist = getattr(getattr(obj, "artist", None), "name", "")
    if name:
        return f"name:{str(name).strip().lower()}|artist:{str(artist).strip().lower()}"
    return repr(obj)


def _merge_remote_results(results_list):
    merged = {"artists": [], "albums": [], "tracks": []}
    seen = {"artists": set(), "albums": set(), "tracks": set()}
    for res in results_list:
        if not isinstance(res, dict):
            continue
        for key in ("artists", "albums", "tracks"):
            for item in res.get(key, []) or []:
                ident = _obj_identity(item)
                if ident in seen[key]:
                    continue
                seen[key].add(ident)
                merged[key].append(item)
    return merged


def _bind_horizontal_scroll_buttons(scroller, left_btn, right_btn):
    adj = scroller.get_hadjustment()
    if adj is None:
        left_btn.set_visible(False)
        right_btn.set_visible(False)
        return

    def _refresh(*_args):
        lower = float(adj.get_lower())
        upper = float(adj.get_upper())
        page = float(adj.get_page_size())
        value = float(adj.get_value())
        max_value = upper - page
        overflow = (upper - lower) > (page + 1.0)

        left_btn.set_visible(overflow)
        right_btn.set_visible(overflow)
        if not overflow:
            return

        left_btn.set_sensitive(value > lower + 1.0)
        right_btn.set_sensitive(value < max_value - 1.0)

    adj.connect("changed", _refresh)
    adj.connect("value-changed", _refresh)
    GLib.idle_add(_refresh)


_QUEUE_WINDOW_BEFORE = 50   # rows before the current track to render
_QUEUE_WINDOW_AFTER  = 150  # rows after the current track to render
_QUEUE_EXPAND_STEP   = 50   # rows revealed per "show more" click


def _build_queue_track_row(app, track, i, current_idx, compact):
    """Build a single queue ListBoxRow. Extracted so expand handlers can reuse it."""
    row = Gtk.ListBoxRow(css_classes=["track-row"])
    row.queue_track_index = i
    row.track_id = getattr(track, "id", None)

    row_margin_y = 1 if compact else LAYOUT["row_margin_y"]
    col_gap      = 5 if compact else LAYOUT["col_gap"]
    row_margin_x = 0 if compact else LAYOUT["row_margin_x"]
    idx_width    = 14 if compact else LAYOUT["index_width"]

    box = Gtk.Box(
        spacing=col_gap,
        margin_top=row_margin_y,
        margin_bottom=row_margin_y,
        margin_start=row_margin_x,
        margin_end=row_margin_x,
    )
    stack = Gtk.Stack()
    stack.set_size_request(idx_width, -1)
    stack.add_css_class("track-index-stack")
    num_lbl = Gtk.Label(label=str(i + 1), css_classes=["dim-label"])
    stack.add_named(num_lbl, "num")
    play_icon = Gtk.Image(icon_name="media-playback-start-symbolic")
    play_icon.add_css_class("accent")
    stack.add_named(play_icon, "icon")
    stack.set_visible_child_name("icon" if i == current_idx else "num")
    box.append(stack)

    title = getattr(track, "name", "Unknown Track")
    if compact:
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, hexpand=True, valign=Gtk.Align.CENTER)
        title_lbl = Gtk.Label(label=title, xalign=0, ellipsize=3, css_classes=["track-title", "queue-track-title"])
        title_lbl.set_tooltip_text(title)
        info.append(title_lbl)
        box.append(info)
    else:
        title_lbl = Gtk.Label(label=title, xalign=0, ellipsize=3, hexpand=True, css_classes=["track-title"])
        title_lbl.set_tooltip_text(title)
        box.append(title_lbl)

        artist_name = getattr(getattr(track, "artist", None), "name", "Unknown")
        artist = Gtk.Label(label=artist_name, xalign=0, ellipsize=3, css_classes=["dim-label", "track-artist"])
        artist.set_tooltip_text(artist_name)
        artist.set_size_request(LAYOUT["artist_width"], -1)
        artist.set_max_width_chars(16)
        artist.set_margin_end(LAYOUT["cell_margin_end"])
        box.append(artist)

        album_name = getattr(getattr(track, "album", None), "name", "Unknown Album")
        alb = Gtk.Label(label=album_name, xalign=0, ellipsize=3, css_classes=["dim-label", "track-album"])
        alb.set_tooltip_text(album_name)
        alb.set_size_request(LAYOUT["album_width"], -1)
        alb.set_max_width_chars(16)
        alb.set_margin_end(LAYOUT["cell_margin_end"])
        box.append(alb)

        dur = int(getattr(track, "duration", 0) or 0)
        if dur > 0:
            m, s = divmod(dur, 60)
            d = Gtk.Label(label=f"{m}:{s:02d}", xalign=1, css_classes=["dim-label", "track-duration"])
            d.set_attributes(Pango.AttrList.from_string("font-features 'tnum=1'"))
            d.set_size_request(LAYOUT["time_width"], -1)
            box.append(d)
        else:
            box.append(Gtk.Box(width_request=LAYOUT["time_width"]))

    fav_btn = app.create_track_fav_button(track)
    if compact:
        fav_btn.set_margin_start(2)
        fav_btn.set_margin_end(0)
    box.append(fav_btn)

    rm_btn = Gtk.Button(icon_name="list-remove-symbolic", css_classes=["flat", "playlist-tool-btn", "queue-remove-btn"])
    rm_btn.set_tooltip_text("Remove from Queue")
    if compact:
        rm_btn.set_margin_start(0)
        rm_btn.set_margin_end(0)
    rm_btn.connect("clicked", lambda _b, idx=i: app.on_queue_remove_track_clicked(idx))
    box.append(rm_btn)

    row.set_child(box)
    return row


def _make_queue_expand_btn_row(label_text, on_click):
    """A clickable 'show more' placeholder row."""
    row = Gtk.ListBoxRow()
    row.set_selectable(False)
    row.set_activatable(False)
    btn = Gtk.Button(
        label=label_text,
        css_classes=["flat", "dim-label"],
        halign=Gtk.Align.START,
        margin_start=4,
        margin_top=2,
        margin_bottom=2,
    )
    btn.connect("clicked", lambda _b: on_click())
    row.set_child(btn)
    return row


def _queue_expand_above(list_box):
    """Incrementally reveal _QUEUE_EXPAND_STEP rows above the current window."""
    state = getattr(list_box, "_q_state", None)
    if state is None:
        return
    tracks      = state["tracks"]
    current_idx = state["current_idx"]
    compact     = state["compact"]
    app         = state["app"]
    win_start   = state["win_start"]
    win_end     = state["win_end"]
    total       = len(tracks)

    new_start = max(0, win_start - _QUEUE_EXPAND_STEP)
    if new_start >= win_start:
        return  # nothing to reveal

    # Remove existing "above" placeholder (always the first row).
    first = list_box.get_row_at_index(0)
    if first is not None:
        list_box.remove(first)

    # Insert new track rows at positions 0..N-1 (forward order).
    for offset, i in enumerate(range(new_start, win_start)):
        track_row = _build_queue_track_row(app, tracks[i], i, current_idx, compact)
        list_box.insert(track_row, offset)

    # Insert a new "above" placeholder at position 0 if rows still hidden.
    if new_start > 0:
        newer_start = max(0, new_start - _QUEUE_EXPAND_STEP)
        ph = _make_queue_expand_btn_row(
            f"… {new_start} track{'s' if new_start != 1 else ''} above — show more",
            lambda: _queue_expand_above(list_box),
        )
        list_box.insert(ph, 0)

    state["win_start"] = new_start


def _queue_expand_below(list_box):
    """Incrementally reveal _QUEUE_EXPAND_STEP rows below the current window."""
    state = getattr(list_box, "_q_state", None)
    if state is None:
        return
    tracks      = state["tracks"]
    current_idx = state["current_idx"]
    compact     = state["compact"]
    app         = state["app"]
    win_end     = state["win_end"]
    total       = len(tracks)

    new_end = min(total, win_end + _QUEUE_EXPAND_STEP)
    if new_end <= win_end:
        return  # nothing to reveal

    # Remove the existing "more" placeholder (always the last row).
    # Walk from the end: get_row_at_index stops at None.
    last = None
    idx = 0
    while True:
        r = list_box.get_row_at_index(idx)
        if r is None:
            break
        last = r
        idx += 1
    if last is not None:
        list_box.remove(last)

    # Append new track rows.
    for i in range(win_end, new_end):
        list_box.append(_build_queue_track_row(app, tracks[i], i, current_idx, compact))

    # Append a new "more" placeholder if rows still hidden.
    tail = total - new_end
    if tail > 0:
        list_box.append(_make_queue_expand_btn_row(
            f"… {tail} more track{'s' if tail != 1 else ''} — show more",
            lambda: _queue_expand_below(list_box),
        ))

    state["win_end"] = new_end


def _populate_queue_rows(app, list_box, tracks, current_idx, compact=False):
    _clear_container(list_box)

    total  = len(tracks)
    anchor = max(0, min(current_idx, total - 1)) if total > 0 else 0
    win_start = max(0, anchor - _QUEUE_WINDOW_BEFORE)
    win_end   = min(total, anchor + _QUEUE_WINDOW_AFTER + 1)

    # Store mutable state on the list_box for the incremental expand handlers.
    list_box._q_state = {
        "tracks":      tracks,
        "current_idx": current_idx,
        "compact":     compact,
        "app":         app,
        "win_start":   win_start,
        "win_end":     win_end,
    }

    if win_start > 0:
        list_box.append(_make_queue_expand_btn_row(
            f"… {win_start} track{'s' if win_start != 1 else ''} above — show more",
            lambda: _queue_expand_above(list_box),
        ))

    for i in range(win_start, win_end):
        list_box.append(_build_queue_track_row(app, tracks[i], i, current_idx, compact))

    tail = total - win_end
    if tail > 0:
        list_box.append(_make_queue_expand_btn_row(
            f"… {tail} more track{'s' if tail != 1 else ''} — show more",
            lambda: _queue_expand_below(list_box),
        ))


def render_search_history(app):
    if not hasattr(app, "search_history_section") or not hasattr(app, "search_history_flow"):
        return

    _clear_container(app.search_history_flow)
    history = list(getattr(app, "search_history", []))
    if not history:
        app.search_history_section.set_visible(False)
        return

    for query in history:
        btn = Gtk.Button(label=query, css_classes=["search-suggest-chip"])
        btn.set_hexpand(False)
        btn.set_halign(Gtk.Align.START)
        btn.connect("clicked", lambda _b, q=query: _run_search(app, q))
        child = Gtk.FlowBoxChild()
        child.set_hexpand(False)
        child.set_halign(Gtk.Align.START)
        child.set_child(btn)
        app.search_history_flow.append(child)

    app.search_history_section.set_visible(True)


def _remember_query(app, query):
    if not query:
        return
    history = list(getattr(app, "search_history", []))
    history = [q for q in history if q != query]
    history.insert(0, query)
    app.search_history = history[:MAX_SEARCH_HISTORY]
    render_search_history(app)
    if hasattr(app, "_save_search_history"):
        app._save_search_history()


def clear_search_history(app, _btn=None):
    app.search_history = []
    render_search_history(app)
    if hasattr(app, "_save_search_history"):
        app._save_search_history()


def on_search_changed(app, entry):
    q = entry.get_text().strip()

    pending = getattr(app, "_search_debounce_source", 0)
    if pending:
        GLib.source_remove(pending)
        app._search_debounce_source = 0

    if not q:
        app._search_request_id = getattr(app, "_search_request_id", 0) + 1
        set_search_status(app, None)
        app.res_art_box.set_visible(False)
        app.res_alb_box.set_visible(False)
        app.res_pl_box.set_visible(False)
        app.res_trk_box.set_visible(False)
        render_search_history(app)
        return

    # Enter-only search mode:
    # typing updates UI state only; no remote/local search is started here.


def on_search(app, entry):
    q = entry.get_text().strip()
    pending = getattr(app, "_search_debounce_source", 0)
    if pending:
        GLib.source_remove(pending)
        app._search_debounce_source = 0
    _run_search(app, q)


def _run_search(app, q):
    logger.info("Search triggered with query: '%s'", q)
    if not q:
        render_search_history(app)
        return

    pop = getattr(app, "search_suggest_popover", None)
    if pop is not None:
        try:
            pop.popdown()
        except Exception:
            logger.debug("Failed to close search suggestions popover", exc_info=True)

    query_variants = _generate_search_variants(q)
    if not query_variants:
        query_variants = [q]

    _remember_query(app, q)
    app.search_active_query = q
    app.nav_history.clear()
    app.right_stack.set_visible_child_name("search_view")
    if hasattr(app, "_remember_last_view"):
        app._remember_last_view("search_view")
    app.nav_list.select_row(None)
    app.back_btn.set_sensitive(True)
    set_search_status(app, "Searching...")
    app._search_request_id = getattr(app, "_search_request_id", 0) + 1
    request_id = app._search_request_id
    local_results = _build_local_search_results(app, query_variants)

    _clear_container(app.res_art_flow)
    _clear_container(app.res_alb_flow)
    _clear_container(app.res_pl_flow)
    _clear_container(app.res_trk_list)

    app.res_art_box.set_visible(False)
    app.res_alb_box.set_visible(False)
    app.res_pl_box.set_visible(False)
    app.res_trk_box.set_visible(False)

    def do_search():
        logger.debug("Background search thread started: variants=%s", query_variants)
        try:
            remote_hits = []
            for query in query_variants:
                remote_hits.append(app.backend.search_items(query))
            results = _merge_remote_results(remote_hits)
            merged = {
                "artists": results.get("artists", []),
                "albums": results.get("albums", []),
                "tracks": results.get("tracks", []),
                "playlists": local_results.get("playlists", []),
                "history_tracks": local_results.get("history_tracks", []),
            }
            if hasattr(app, "set_diag_health"):
                app.set_diag_health("network", "ok")

            def apply_results():
                if request_id != getattr(app, "_search_request_id", 0):
                    return False
                app.render_search_results(merged)
                return False

            GLib.idle_add(apply_results)
        except Exception as e:
            kind = classify_exception(e)
            logger.warning("Search error [%s]: %s", kind, e)
            if hasattr(app, "record_diag_event"):
                app.record_diag_event(f"Search error [{kind}]: {e}")
            if hasattr(app, "set_diag_health"):
                if kind in ("network", "server", "auth"):
                    app.set_diag_health("network", "error", kind)
                elif kind == "parse":
                    app.set_diag_health("decoder", "warn", "search-parse")
                else:
                    app.set_diag_health("network", "warn", kind)

            def apply_error():
                if request_id != getattr(app, "_search_request_id", 0):
                    return False
                app.render_search_results(
                    {
                        "artists": [],
                        "albums": [],
                        "tracks": [],
                        "playlists": local_results.get("playlists", []),
                        "history_tracks": local_results.get("history_tracks", []),
                    }
                )
                local_any = bool(local_results.get("playlists")) or bool(local_results.get("history_tracks"))
                if local_any:
                    set_search_status(app, f"{user_message(kind, 'search')} Showing local results.")
                else:
                    set_search_status(app, user_message(kind, "search"))
                return False

            GLib.idle_add(apply_error)

    Thread(target=do_search, daemon=True).start()


def render_search_results(app, res):
    logger.debug("render_search_results: starting UI update")
    app.search_selected_indices = set()
    if hasattr(app, "_update_search_batch_add_state"):
        app._update_search_batch_add_state()

    artists = res.get("artists", [])
    albums = res.get("albums", [])
    tracks = res.get("tracks", [])
    playlists = res.get("playlists", [])
    if artists or albums or tracks or playlists:
        set_search_status(app, None)
    else:
        set_search_status(app, "No results found.")

    logger.info(
        "Rendering search results: %s artists, %s albums, %s playlists, %s tracks",
        len(artists),
        len(albums),
        len(playlists),
        len(tracks),
    )

    app.res_art_box.set_visible(bool(artists))
    for art in artists:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=_artist_card_classes())
        img = Gtk.Image(pixel_size=utils.COVER_SIZE, css_classes=["circular-avatar"])
        url = app.backend.get_artist_artwork_url(art, 320)
        logger.debug("Artist '%s' image URL: %s", getattr(art, "name", "Unknown"), url)
        utils.load_img(img, url, app.cache_dir, utils.COVER_SIZE)
        card.append(_build_feed_media_overlay(img, utils.COVER_SIZE, "circular-avatar"))
        card.append(
            Gtk.Label(
                label=getattr(art, "name", "Unknown"),
                ellipsize=2,
                wrap=True,
                max_width_chars=12,
                css_classes=["heading", "home-card-title"],
            )
        )
        child = Gtk.FlowBoxChild()
        child.set_child(card)
        child.data_item = {"obj": art, "type": "Artist"}
        app.res_art_flow.append(child)

    app.res_alb_box.set_visible(bool(albums))
    for alb in albums:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=_feed_card_classes())
        img = Gtk.Image(pixel_size=utils.COVER_SIZE, css_classes=["album-cover-img"])
        url = app.backend.get_artwork_url(alb, 320)
        alb_title = getattr(alb, "title", getattr(alb, "name", "Unknown Album"))
        logger.debug("Album '%s' image URL: %s", alb_title, url)
        utils.load_img(img, url, app.cache_dir, utils.COVER_SIZE)
        card.append(_build_feed_media_overlay(img, utils.COVER_SIZE, "album-cover-img"))
        card.append(Gtk.Label(label=alb_title, ellipsize=2, wrap=True, max_width_chars=14, css_classes=["home-card-title"]))
        child = Gtk.FlowBoxChild()
        child.set_child(card)
        child.data_item = {"obj": alb, "type": "Album"}
        app.res_alb_flow.append(child)

    app.res_pl_box.set_visible(bool(playlists))
    for p in playlists:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=_feed_card_classes())
        img = Gtk.Image(css_classes=["album-cover-img", "playlist-cover-img"])
        img.set_size_request(utils.COVER_SIZE, utils.COVER_SIZE)
        refs = app.playlist_mgr.get_cover_refs(p, limit=4) if hasattr(app, "playlist_mgr") else []
        collage_dir = os.path.join(app.cache_dir, "playlist_covers")
        collage = utils.generate_auto_collage_cover(
            refs,
            image_cache_dir=app.cache_dir,
            collage_cache_dir=collage_dir,
            key_prefix=f"playlist_search_{p.get('id', 'x')}_{p.get('updated_at', 0)}",
            size=256,
            overlay_alpha=0.34,
            overlay_style="mix",
        )
        if collage:
            utils.load_img(img, collage, app.cache_dir, utils.COVER_SIZE)
        else:
            img.set_pixel_size(utils.COVER_SIZE)
            img.set_from_icon_name("audio-x-generic-symbolic")
        card.append(_build_feed_media_overlay(img, utils.COVER_SIZE, "album-cover-img"))
        card.append(
            Gtk.Label(
                label=p.get("name", "Untitled Playlist"),
                ellipsize=3,
                halign=Gtk.Align.CENTER,
                wrap=True,
                max_width_chars=14,
                css_classes=["home-card-title"],
            )
        )
        card.append(
            Gtk.Label(
                label=f"{len(p.get('tracks', []))} tracks",
                halign=Gtk.Align.CENTER,
                css_classes=["dim-label", "home-card-subtitle"],
            )
        )
        btn = Gtk.Button(css_classes=["flat", "history-card-btn", "home-feed-btn"])
        btn.set_child(card)
        btn.connect("clicked", lambda _b, pid=p.get("id"): app.on_playlist_card_clicked(pid))
        child = Gtk.FlowBoxChild()
        child.set_child(btn)
        app.res_pl_flow.append(child)

    app.res_trk_box.set_visible(bool(tracks))
    app.search_track_data = tracks
    app.search_track_order_indices = None

    # Rust fast path: reorder/filter merged track results by active query for paging/rendering.
    search_query = str(getattr(app, "search_active_query", "") or "").strip().lower()
    if tracks and search_query:
        rust_core = _get_rust_collection_core()
        if rust_core is not None and getattr(rust_core, "available", False):
            try:
                blob = bytearray()
                offsets = []
                lens = []
                keys = []
                title_rank = list(range(len(tracks)))
                artist_rank = list(range(len(tracks)))
                album_rank = list(range(len(tracks)))
                durations = [int(getattr(t, "duration", 0) or 0) for t in tracks]
                for i, t in enumerate(tracks):
                    title = str(getattr(t, "name", "") or "").lower()
                    artist = str(getattr(getattr(t, "artist", None), "name", "") or "").lower()
                    album = str(getattr(getattr(t, "album", None), "name", "") or "").lower()
                    s = f"{title}\n{artist}\n{album}".encode("utf-8", "ignore")
                    offsets.append(len(blob))
                    lens.append(len(s))
                    blob.extend(s)
                    # no artist filter for global search results
                    keys.append(0)
                idxs = rust_core.filter_sort_indices_with_query(
                    search_blob=bytes(blob),
                    search_offsets=offsets,
                    search_lens=lens,
                    artist_keys=keys,
                    title_rank=title_rank,
                    artist_rank=artist_rank,
                    album_rank=album_rank,
                    durations=durations,
                    sort_mode=0,
                    query=search_query,
                    artist_filter_key=0,
                    use_artist_filter=False,
                )
                if idxs is not None:
                    app.search_track_order_indices = [i for i in idxs if 0 <= int(i) < len(tracks)]
                    logger.info(
                        "Search tracks paging/order path: Rust (query_len=%s, total=%s, ordered=%s)",
                        len(search_query),
                        len(tracks),
                        len(app.search_track_order_indices),
                    )
            except Exception:
                app.search_track_order_indices = None
                logger.exception("Rust search track ordering failed; fallback to Python order")

    app.search_tracks_page = 0
    render_search_tracks_page(app)

    logger.debug("Search rendering complete")


def render_search_tracks_page(app):
    tracks = list(getattr(app, "search_track_data", []) or [])
    order = list(getattr(app, "search_track_order_indices", []) or [])
    if order:
        logger.info(
            "Search tracks page render: Rust-order active (page=%s, page_size=%s, ordered_total=%s)",
            int(getattr(app, "search_tracks_page", 0) or 0) + 1,
            int(getattr(app, "search_tracks_page_size", 50) or 50),
            len(order),
        )
        ordered_pairs = [(int(i), tracks[int(i)]) for i in order if 0 <= int(i) < len(tracks)]
    else:
        logger.info(
            "Search tracks page render: Python-order active (page=%s, page_size=%s, total=%s)",
            int(getattr(app, "search_tracks_page", 0) or 0) + 1,
            int(getattr(app, "search_tracks_page_size", 50) or 50),
            len(tracks),
        )
        ordered_pairs = list(enumerate(tracks))
    page_size = max(1, int(getattr(app, "search_tracks_page_size", 50) or 50))
    total = len(ordered_pairs)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = int(getattr(app, "search_tracks_page", 0) or 0)
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1
    app.search_tracks_page = page

    start = page * page_size
    end = min(total, start + page_size)
    page_items = ordered_pairs[start:end] if total > 0 else []

    prev_btn = getattr(app, "search_prev_page_btn", None)
    next_btn = getattr(app, "search_next_page_btn", None)
    page_lbl = getattr(app, "search_tracks_page_label", None)
    if prev_btn is not None:
        prev_btn.set_sensitive(page > 0)
    if next_btn is not None:
        next_btn.set_sensitive(page < (total_pages - 1))
    if page_lbl is not None:
        if total > 0:
            page_lbl.set_text(f"Page {page + 1}/{total_pages}")
        else:
            page_lbl.set_text("Page 1/1")

    _clear_container(app.res_trk_list)
    for i, pair in enumerate(page_items):
        abs_idx = int(pair[0])
        t = pair[1]
        row_box = Gtk.Box(
            spacing=LAYOUT["col_gap"],
            margin_top=LAYOUT["row_margin_y"],
            margin_bottom=LAYOUT["row_margin_y"],
            margin_start=LAYOUT["row_margin_x"],
            margin_end=LAYOUT["row_margin_x"],
        )
        sel_cb = Gtk.CheckButton()
        sel_cb.set_valign(Gtk.Align.CENTER)
        sel_cb.set_active(abs_idx in (getattr(app, "search_selected_indices", set()) or set()))
        sel_cb.connect("toggled", lambda cb, idx=abs_idx: app.on_search_track_checkbox_toggled(cb, idx, cb.get_active()))
        row_box.append(sel_cb)

        stack = Gtk.Stack()
        stack.set_size_request(LAYOUT["index_width"], -1)
        stack.add_css_class("track-index-stack")
        lbl_idx = Gtk.Label(label=str(i + 1), css_classes=["dim-label"])
        stack.add_named(lbl_idx, "num")
        icon = Gtk.Image(icon_name="media-playback-start-symbolic")
        icon.add_css_class("accent")
        stack.add_named(icon, "icon")
        if getattr(app, "playing_track_id", None) and getattr(t, "id", None) == app.playing_track_id:
            stack.set_visible_child_name("icon")
        else:
            stack.set_visible_child_name("num")
        row_box.append(stack)

        img = Gtk.Image(pixel_size=DASHBOARD_TRACK_COVER_SIZE, css_classes=["album-cover-img"])
        cover = app.backend.get_artwork_url(t, 320)
        if cover is None:
            cover = getattr(getattr(t, "album", None), "cover", None)
        if cover:
            utils.load_img(img, cover, app.cache_dir, DASHBOARD_TRACK_COVER_SIZE)
        else:
            img.set_from_icon_name("audio-x-generic-symbolic")
        row_box.append(_build_feed_media_overlay(img, DASHBOARD_TRACK_COVER_SIZE, "album-cover-img"))

        lbl_title = Gtk.Label(label=getattr(t, "name", "Unknown"), xalign=0, hexpand=True, ellipsize=3, css_classes=["track-title"])
        lbl_title.set_tooltip_text(getattr(t, "name", ""))
        row_box.append(lbl_title)

        artist_name = getattr(getattr(t, "artist", None), "name", "Unknown")
        lbl_art = Gtk.Label(label=artist_name, xalign=0, ellipsize=3, css_classes=["dim-label", "track-artist"])
        lbl_art.set_tooltip_text(artist_name)
        lbl_art.set_size_request(LAYOUT["artist_width"], -1)
        lbl_art.set_max_width_chars(16)
        lbl_art.set_margin_end(LAYOUT["cell_margin_end"])
        row_box.append(lbl_art)

        alb_name = getattr(getattr(t, "album", None), "name", "-") or "-"
        lbl_alb = Gtk.Label(label=alb_name, xalign=0, ellipsize=3, css_classes=["dim-label", "track-album"])
        lbl_alb.set_tooltip_text(alb_name)
        lbl_alb.set_size_request(LAYOUT["album_width"], -1)
        lbl_alb.set_max_width_chars(16)
        lbl_alb.set_margin_end(LAYOUT["cell_margin_end"])
        row_box.append(lbl_alb)

        dur_sec = getattr(t, "duration", 0)
        if dur_sec:
            m, s = divmod(dur_sec, 60)
            lbl_dur = Gtk.Label(label=f"{m}:{s:02d}", xalign=1, css_classes=["dim-label", "track-duration"])
            lbl_dur.set_attributes(Pango.AttrList.from_string("font-features 'tnum=1'"))
            lbl_dur.set_size_request(LAYOUT["time_width"], -1)
            row_box.append(lbl_dur)

        fav_btn = app.create_track_fav_button(t)
        row_box.append(fav_btn)
        add_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
        add_btn.set_tooltip_text("Add to Playlist")
        add_btn.connect("clicked", lambda _b, tr=t: app.on_add_single_track_to_playlist(tr))
        row_box.append(add_btn)

        lb_row = Gtk.ListBoxRow()
        lb_row.add_css_class("track-row")
        lb_row.search_track_index = abs_idx
        lb_row.set_child(row_box)
        app.res_trk_list.append(lb_row)


def _on_play_album_tracks(app):
    """Play album tracks from the beginning."""
    tracks = list(getattr(app, "current_track_list", []) or [])
    if not tracks:
        return
    app.current_track_list = tracks
    app._set_play_queue(tracks)
    app.play_track(0)


def _on_shuffle_album_tracks(app):
    """Shuffle and play album tracks."""
    tracks = list(getattr(app, "current_track_list", []) or [])
    if not tracks:
        return
    # Shuffle only for playback, don't modify display list
    import random
    shuffled = tracks.copy()
    random.shuffle(shuffled)
    app._set_play_queue(shuffled)
    app.play_track(0)


def _ensure_play_shuffle_btns(app):
    """Create play/shuffle buttons if needed and add them to album_action_btns_box."""
    if not hasattr(app, "_album_play_btn") or app._album_play_btn is None:
        app._album_play_btn = Gtk.Button(icon_name="media-playback-start-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
        app._album_play_btn.set_tooltip_text("Play all tracks")
        app._album_play_btn.connect("clicked", lambda _b: _on_play_album_tracks(app))

        app._album_shuffle_btn = Gtk.Button(icon_name="media-playlist-shuffle-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
        app._album_shuffle_btn.set_tooltip_text("Shuffle and play")
        app._album_shuffle_btn.connect("clicked", lambda _b: _on_shuffle_album_tracks(app))

    action_box = getattr(app, "album_action_btns_box", None)
    if action_box:
        child = action_box.get_first_child()
        found = False
        while child:
            if child == app._album_play_btn or child == app._album_shuffle_btn:
                found = True
                break
            child = child.get_next_sibling()
        if not found:
            action_box.append(app._album_play_btn)
            action_box.append(app._album_shuffle_btn)

    if app._album_play_btn:
        app._album_play_btn.set_visible(True)
    if app._album_shuffle_btn:
        app._album_shuffle_btn.set_visible(True)


def _artist_context_values(candidate):
    if candidate is None:
        return None, ""
    if isinstance(candidate, dict):
        artist_id = candidate.get("id")
        artist_name = str(candidate.get("name", "") or "").strip()
        return artist_id, artist_name
    if isinstance(candidate, str):
        return None, candidate.strip()
    artist_id = getattr(candidate, "id", None)
    artist_name = str(getattr(candidate, "name", "") or "").strip()
    return artist_id, artist_name


def _resolve_album_artist_context(app, alb):
    candidates = []

    if alb is not None:
        candidates.append(getattr(alb, "artist", None))
        artists = getattr(alb, "artists", None)
        if artists:
            try:
                candidates.extend(list(artists)[:1])
            except Exception:
                pass

    track = getattr(app, "playing_track", None)
    track_album = getattr(track, "album", None) if track is not None else None
    album_id = str(getattr(alb, "id", "") or "")
    track_album_id = str(getattr(track_album, "id", "") or "")
    if track is not None and (not album_id or (track_album_id and album_id == track_album_id)):
        candidates.append(getattr(track, "artist", None))

    for candidate in candidates:
        artist_id, artist_name = _artist_context_values(candidate)
        if artist_id or artist_name:
            return artist_id, artist_name

    return None, "Various Artists"


def _load_similar_albums(app, alb):
    """Fetch other albums by the same artist and populate app.similar_albums_box. Called from a background thread."""
    try:
        artist_obj = getattr(alb, "artist", None) or (getattr(alb, "artists", None) or [None])[0]
        artist_id = getattr(artist_obj, "id", None)
        current_id = getattr(alb, "id", None)
        if not artist_id:
            GLib.idle_add(lambda: getattr(app, "similar_albums_box", None) and app.similar_albums_box.set_visible(False))
            return
        artist = app.backend.session.artist(artist_id)
        artist_name = str(getattr(artist, "name", getattr(artist_obj, "name", "")) or "")
        all_albums = artist.get_albums()
        similar = [a for a in (all_albums or []) if getattr(a, "id", None) != current_id]
        logger.debug("more from artist: %d albums for artist_id=%s", len(similar), artist_id)
    except Exception as e:
        logger.debug("more from artist: exception %s: %s", type(e).__name__, e)
        GLib.idle_add(lambda: getattr(app, "similar_albums_box", None) and app.similar_albums_box.set_visible(False))
        return
    if not similar:
        GLib.idle_add(lambda: getattr(app, "similar_albums_box", None) and app.similar_albums_box.set_visible(False))
        return

    def _similar_initial_count():
        available_width = 0
        try:
            scroll = getattr(app, "trk_scroll", None)
            if scroll is not None:
                available_width = int(scroll.get_width() or 0)
        except Exception:
            pass
        if available_width <= 0:
            try:
                win = getattr(app, "win", None)
                if win is not None:
                    available_width = int(win.get_width() or 0)
            except Exception:
                pass
        if available_width <= 0:
            base_width = int(getattr(ui_config, "WINDOW_WIDTH", 1250) or 1250)
            sidebar_width = max(int(base_width * float(getattr(ui_config, "SIDEBAR_RATIO", 0.15))), 120)
            available_width = max(320, base_width - sidebar_width - 64)
        item_width = max(150, int(getattr(utils, "COVER_SIZE", 170) or 170) + 20)
        gap = 16
        columns = max(1, min(10, int((available_width + gap) // (item_width + gap)) or 1))
        return max(1, columns * 2)

    initial_count = _similar_initial_count()

    def _build_album_card(s_alb):
        return _build_my_albums_style_button(app, s_alb, app.show_album_details)

    def populate():
        flow = getattr(app, "similar_albums_flow", None)
        box = getattr(app, "similar_albums_box", None)
        more_row = getattr(app, "similar_albums_more_row", None)
        if flow is None or box is None:
            return
        lbl = getattr(app, "similar_albums_label", None)
        if lbl is not None and artist_name:
            lbl.set_text(f"More by {artist_name}")
        while c := flow.get_first_child():
            flow.remove(c)
        if more_row is not None:
            while c := more_row.get_first_child():
                more_row.remove(c)
            more_row.set_visible(False)

        for s_alb in similar[:initial_count]:
            flow.append(_build_album_card(s_alb))

        remaining = similar[initial_count:]
        if remaining and more_row is not None:
            while c := more_row.get_first_child():
                more_row.remove(c)
            more_row.append(Gtk.Box(hexpand=True))
            more_btn = Gtk.Button(
                label=f"Show more ({len(remaining)})",
                css_classes=["flat", "liked-action-btn"],
            )
            def _on_show_more(_btn, rem=remaining, f=flow, r=more_row):
                for a in rem:
                    f.append(_build_album_card(a))
                r.set_visible(False)
            more_btn.connect("clicked", _on_show_more)
            more_row.append(more_btn)
            more_row.set_visible(True)

        box.set_visible(True)

    GLib.idle_add(populate)


def show_album_details(app, alb):
    # Invalidate any in-flight playlist page-load callbacks so they don't
    # overwrite the track list we're about to populate with album tracks.
    app._remote_pl_render_token = int(getattr(app, "_remote_pl_render_token", 0) or 0) + 1

    current_view = app.right_stack.get_visible_child_name()
    if current_view and current_view != "tracks":
        app.nav_history.append(current_view)

    app.current_album = alb
    app.right_stack.set_visible_child_name("tracks")
    if hasattr(app, "_remember_last_view"):
        app._remember_last_view("tracks")
    app.back_btn.set_sensitive(True)

    title = getattr(alb, "title", getattr(alb, "name", "Unknown"))
    app.header_title.set_text(title)
    app.header_title.set_tooltip_text(title)

    artist_id, artist_name = _resolve_album_artist_context(app, alb)
    app.current_album_artist_id = artist_id
    app.current_album_artist_name = artist_name
    app.header_artist.set_text(artist_name)
    app.header_artist.set_tooltip_text(artist_name)

    utils.load_img(app.header_art, lambda: app.backend.get_artwork_url(alb, 640), app.cache_dir, utils.COVER_SIZE)
    is_fav = app.backend.is_favorite(getattr(alb, "id", ""))
    app._update_fav_icon(app.fav_btn, is_fav)
    if app.remote_playlist_edit_btn is not None:
        app.remote_playlist_edit_btn.set_visible(False)
    if getattr(app, "remote_playlist_visibility_btn", None) is not None:
        app.remote_playlist_visibility_btn.set_visible(False)
    if app.remote_playlist_more_btn is not None:
        app.remote_playlist_more_btn.set_visible(False)
    if app.fav_btn is not None:
        app.fav_btn.set_visible(True)
    if app.add_playlist_btn is not None:
        app.add_playlist_btn.set_visible(True)

    _ensure_play_shuffle_btns(app)

    while c := app.track_list.get_first_child():
        app.track_list.remove(c)
    app.album_sort_field = None
    app.album_sort_asc = True
    if hasattr(app, "_update_album_sort_headers"):
        app._update_album_sort_headers()
    if hasattr(app, "similar_albums_box"):
        app.similar_albums_box.set_visible(False)

    def detail_task():
        ts = app.backend.get_tracks(alb)
        desc = ""
        year = _album_release_year_text(alb)
        if year:
            desc += year
        elif hasattr(alb, "last_updated"):
            desc += "Updated Recently"
        count = len(ts) if ts else 0
        if count > 0:
            desc += f"  •  {count} Tracks"
        GLib.idle_add(lambda: app.header_meta.set_text(desc.strip(" • ")))
        GLib.idle_add(app.load_album_tracks, ts)
        _load_similar_albums(app, alb)

    Thread(target=detail_task, daemon=True).start()


def populate_tracks(app, tracks):
    app.current_track_list = tracks
    if app.playing_track_id:
        found_idx = -1
        for i, t in enumerate(tracks):
            if t.id == app.playing_track_id:
                found_idx = i
                break
        if found_idx != -1:
            app.current_index = found_idx

    while c := app.track_list.get_first_child():
        app.track_list.remove(c)

    for i, t in enumerate(tracks):
        row = Gtk.ListBoxRow()
        row.track_id = t.id
        row.add_css_class("track-row")
        box = Gtk.Box(
            spacing=LAYOUT["col_gap"],
            margin_top=LAYOUT["row_margin_y"],
            margin_bottom=LAYOUT["row_margin_y"],
            margin_start=LAYOUT["row_margin_x"],
            margin_end=LAYOUT["row_margin_x"],
        )

        stack = Gtk.Stack()
        stack.set_size_request(LAYOUT["index_width"], -1)
        stack.add_css_class("track-index-stack")
        lbl = Gtk.Label(label=str(i + 1), css_classes=["dim-label"])
        stack.add_named(lbl, "num")
        icon = Gtk.Image(icon_name="media-playback-start-symbolic")
        icon.add_css_class("accent")
        stack.add_named(icon, "icon")
        if app.playing_track_id and t.id == app.playing_track_id:
            stack.set_visible_child_name("icon")
        else:
            stack.set_visible_child_name("num")
        box.append(stack)

        lbl_title = Gtk.Label(label=t.name, xalign=0, hexpand=True, ellipsize=3, css_classes=["track-title"])
        lbl_title.set_tooltip_text(t.name)
        box.append(lbl_title)

        art_name = getattr(t.artist, "name", "-") if hasattr(t, "artist") else "-"
        lbl_art = Gtk.Label(label=art_name, xalign=0, ellipsize=3, css_classes=["dim-label", "track-artist"])
        lbl_art.set_tooltip_text(art_name)
        lbl_art.set_size_request(LAYOUT["artist_width"], -1)
        lbl_art.set_max_width_chars(16)
        lbl_art.set_margin_end(LAYOUT["cell_margin_end"])
        box.append(lbl_art)

        alb_name = t.album.name if hasattr(t, "album") and t.album else "-"
        lbl_alb = Gtk.Label(label=alb_name, xalign=0, ellipsize=3, css_classes=["dim-label", "track-album"])
        lbl_alb.set_tooltip_text(alb_name)
        lbl_alb.set_size_request(LAYOUT["album_width"], -1)
        lbl_alb.set_max_width_chars(16)
        lbl_alb.set_margin_end(LAYOUT["cell_margin_end"])
        box.append(lbl_alb)

        dur_sec = getattr(t, "duration", 0)
        if dur_sec:
            m, s = divmod(dur_sec, 60)
            dur_str = f"{m}:{s:02d}"
            lbl_dur = Gtk.Label(label=dur_str, xalign=1, css_classes=["dim-label", "track-duration"])
            lbl_dur.set_attributes(Pango.AttrList.from_string("font-features 'tnum=1'"))
            lbl_dur.set_size_request(LAYOUT["time_width"], -1)
            box.append(lbl_dur)

        fav_btn = app.create_track_fav_button(t)
        box.append(fav_btn)
        current_remote = getattr(app, "current_remote_playlist", None)
        is_own_remote = getattr(app, "_remote_playlist_is_own", False)
        if current_remote is not None and is_own_remote:
            rm_btn = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat", "playlist-tool-btn"])
            rm_btn.set_tooltip_text("Remove from Playlist")
            rm_btn.connect("clicked", lambda _b, tr=t: app.on_remove_single_track_from_remote_playlist(tr))
            box.append(rm_btn)
        else:
            add_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
            add_btn.set_tooltip_text("Add to Playlist")
            add_btn.connect("clicked", lambda _b, tr=t: app.on_add_single_track_to_playlist(tr))
            box.append(add_btn)

        row.set_child(box)
        app.track_list.append(row)

    if hasattr(app, "_update_track_list_icon"):
        app._update_track_list_icon()


def batch_load_albums(app, albs, batch=6, _flow=None, _token=None, _token_attr=None):
    if _token_attr and _token is not None and _token != getattr(app, _token_attr, None):
        return False
    if not albs:
        return False
    flow = _flow if _flow is not None else getattr(app, "main_flow", None)
    if flow is None:
        return False
    curr, rem = albs[:batch], albs[batch:]
    for alb in curr:
        flow.append(_build_my_albums_style_button(app, alb, app.show_album_details))
    if rem:
        GLib.timeout_add(50, app.batch_load_albums, rem, batch, flow, _token, _token_attr)
    return False


def batch_load_artists(app, artists, batch=10, _token=None, _flow=None):
    # Bail out if a newer artists-page render has started since this batch was scheduled.
    if _token is not None and _token != getattr(app, "_artists_render_token", None):
        return False
    if not artists:
        return False
    flow = _flow if _flow is not None else getattr(app, "main_flow", None)
    if flow is None:
        return False
    curr, rem = artists[:batch], artists[batch:]
    for art in curr:
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=_artist_card_classes())
        img = Gtk.Image(pixel_size=150, css_classes=["circular-avatar"])
        # Fast path: try to get artwork URL synchronously from in-memory cache or local
        # object attributes (no network calls). This prevents all _IMG_EXECUTOR workers
        # from being blocked on URL resolution API calls when rendering large collections.
        _cached_url = app.backend._artist_artwork_cache.get(
            f"id:{getattr(art, 'id', None)}:320"
        ) if getattr(art, "id", None) is not None else None
        if not _cached_url:
            _quick_url = app.backend.get_artwork_url(art, 320)
            if _quick_url and not app.backend._is_placeholder_artist_artwork_url(_quick_url):
                _cached_url = _quick_url
        url_arg = _cached_url if _cached_url else (lambda a=art: app.backend.get_artist_artwork_url(a, 320))
        utils.load_img(img, url_arg, app.cache_dir, 150)
        v.append(_build_feed_media_overlay(img, 150, "circular-avatar"))
        v.append(
            Gtk.Label(
                label=art.name,
                ellipsize=2,
                halign=Gtk.Align.CENTER,
                wrap=True,
                max_width_chars=14,
                css_classes=["heading", "home-card-title"],
            )
        )
        c = Gtk.FlowBoxChild()
        c.set_child(v)
        c.data_item = {"obj": art, "type": "Artist"}
        flow.append(c)
    if rem:
        GLib.timeout_add(50, app.batch_load_artists, rem, batch, _token, flow)
    return False


def _artist_added_sort_value(raw):
    if raw is None:
        return float("-inf")
    if isinstance(raw, datetime):
        try:
            return float(raw.timestamp())
        except Exception:
            return float("-inf")
    timestamp = getattr(raw, "timestamp", None)
    if callable(timestamp):
        try:
            return float(timestamp())
        except Exception:
            return float("-inf")
    text = str(raw or "").strip()
    if not text:
        return float("-inf")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return float(datetime.fromisoformat(text).timestamp())
    except Exception:
        return float("-inf")


def _artist_index_entry_from_obj(artist):
    artist_id = str(getattr(artist, "id", "") or "").strip()
    name = str(getattr(artist, "name", "") or "").strip()
    if not artist_id or not name:
        return None
    return {
        "id": artist_id,
        "name": name,
        "name_lc": name.lower(),
        "added": getattr(artist, "user_date_added", None),
    }


def _artist_obj_from_index_entry(entry):
    if hasattr(entry, "id") and hasattr(entry, "name"):
        return entry
    return SimpleNamespace(
        id=str((entry or {}).get("id", "") or ""),
        name=str((entry or {}).get("name", "") or ""),
    )


def _filter_artist_index_entries(entries, query):
    q = str(query or "").strip().lower()
    if not q:
        return list(entries or [])
    return [
        dict(entry)
        for entry in list(entries or [])
        if q in str(entry.get("name_lc", "") or "")
    ]


def _sort_artist_index_entries(entries, sort_key):
    key = str(sort_key or "name_asc").strip().lower()
    seq = [dict(entry) for entry in list(entries or [])]
    if key == "name_desc":
        seq.sort(key=lambda entry: (str(entry.get("name_lc", "") or ""), str(entry.get("id", "") or "")), reverse=True)
    elif key == "date_asc":
        seq.sort(
            key=lambda entry: (
                _artist_added_sort_value(entry.get("added")),
                str(entry.get("name_lc", "") or ""),
                str(entry.get("id", "") or ""),
            )
        )
    elif key == "date_desc":
        seq.sort(
            key=lambda entry: (
                _artist_added_sort_value(entry.get("added")),
                str(entry.get("name_lc", "") or ""),
                str(entry.get("id", "") or ""),
            ),
            reverse=True,
        )
    else:
        seq.sort(key=lambda entry: (str(entry.get("name_lc", "") or ""), str(entry.get("id", "") or "")))
    return seq


def render_artists_dashboard(app):
    logger.info(
        "Artists dashboard opened: query=%r sort=%s page=%s",
        getattr(app, "artists_query", ""),
        getattr(app, "artists_sort", "name_asc"),
        getattr(app, "artists_page", 0),
    )
    _clear_container(app.collection_content_box)
    app.playlist_track_list = None
    app.queue_track_list = None
    app.artists_query = str(getattr(app, "artists_query", "") or "")
    app.artists_sort = str(getattr(app, "artists_sort", "name_asc") or "name_asc")
    app.artists_page = max(0, int(getattr(app, "artists_page", 0) or 0))
    app.artists_page_size = max(1, int(getattr(app, "artists_page_size", 50) or 50))

    current_user_id = str(getattr(getattr(app.backend, "user", None), "id", "") or "")
    if current_user_id != str(getattr(app, "_artists_index_user_id", "") or ""):
        app._artists_total_count = 0
        app._artists_total_count_known = False
        app._artists_index_entries = []
        app._artists_index_ready = False
        app._artists_index_building = False
        app._artists_index_user_id = current_user_id

    if bool(getattr(app.backend, "_favorite_artists_index_dirty", False)):
        app._artists_total_count = 0
        app._artists_total_count_known = False
        app._artists_index_entries = []
        app._artists_index_ready = False
        app._artists_index_building = False

    dashboard_token = int(getattr(app, "_artists_dashboard_token", 0) or 0) + 1
    app._artists_dashboard_token = dashboard_token

    toolbar = Gtk.Box(
        spacing=8,
        margin_start=0,
        margin_end=0,
        margin_top=6,
        margin_bottom=8,
        css_classes=["search-bar"],
    )
    search_entry = Gtk.Entry(hexpand=True, css_classes=["search-entry"])
    search_entry.set_placeholder_text("Search favorite artists")
    search_entry.set_text(app.artists_query)
    toolbar.append(search_entry)
    sort_options = [
        ("name_asc", "Name (A-Z)"),
        ("name_desc", "Name (Z-A)"),
        ("date_desc", "Recently Added"),
        ("date_asc", "Oldest Added"),
    ]
    sort_dd = Gtk.DropDown(
        model=Gtk.StringList.new([label for _key, label in sort_options]),
        css_classes=["sort-dropdown"],
    )
    sort_dd.set_tooltip_text("Sort artists")
    sort_dd.set_size_request(150, -1)
    sort_lookup = {key: idx for idx, (key, _label) in enumerate(sort_options)}
    sort_dd.set_selected(sort_lookup.get(app.artists_sort, 0))
    toolbar.append(sort_dd)
    prev_btn = Gtk.Button(label="Prev", css_classes=["flat", "liked-action-btn"])
    next_btn = Gtk.Button(label="Next", css_classes=["flat", "liked-action-btn"])
    prev_btn.set_tooltip_text("Previous page")
    next_btn.set_tooltip_text("Next page")
    toolbar.append(prev_btn)
    toolbar.append(next_btn)
    app.collection_content_box.append(toolbar)

    pager_bar = Gtk.Box(spacing=8, margin_start=0, margin_end=0, margin_bottom=8)
    status_lbl = Gtk.Label(label="", css_classes=["dim-label"], xalign=1)
    status_lbl.set_hexpand(True)
    pager_bar.append(status_lbl)
    if hasattr(pager_bar, "set_visible"):
        pager_bar.set_visible(False)
    app.collection_content_box.append(pager_bar)

    app.create_album_flow()
    flow = app.main_flow

    def _render_items(items):
        _clear_container(flow)
        render_token = int(getattr(app, "_artists_render_token", 0) or 0) + 1
        app._artists_render_token = render_token
        if items:
            # Render all artists in one shot so every image download is submitted
            # to the executor at t=0.  With the old batch=10/50ms approach the
            # last batch's downloads were queued 200 ms late, causing the last
            # few covers to appear blank until workers caught up.
            app.batch_load_artists(items, len(items), render_token, flow)

    def _set_status(message):
        text = str(message or "")
        status_lbl.set_text(text)
        if hasattr(pager_bar, "set_visible"):
            pager_bar.set_visible(bool(text))

    def _set_subtitle(total_count=None):
        subtitle_label = getattr(app, "grid_subtitle_label", None)
        if subtitle_label is None:
            return
        if total_count is None:
            subtitle_label.set_text("Artists you follow and love")
            return
        total = max(0, int(total_count or 0))
        noun = "Artist" if total == 1 else "Artists"
        subtitle_label.set_text(f"{total} {noun} you follow and love")

    def _update_pager(total_count, page_count, status_message="", subtitle_total_count=None):
        pages = max(0, int(page_count or 0))
        prev_btn.set_sensitive(app.artists_page > 0)
        next_btn.set_sensitive(pages > 0 and app.artists_page < pages - 1)
        if subtitle_total_count is not None:
            app._artists_total_count = max(0, int(subtitle_total_count or 0))
            app._artists_total_count_known = True
            _set_subtitle(app._artists_total_count)
        elif bool(getattr(app, "_artists_total_count_known", False)):
            _set_subtitle(getattr(app, "_artists_total_count", 0))
        else:
            _set_subtitle(None)
        _set_status(status_message)

    def _update_from_local_index():
        query = str(app.artists_query or "").strip()
        if not query and not getattr(app, "_artists_index_ready", False):
            return False
        if query and not getattr(app, "_artists_index_ready", False):
            _render_items([])
            _update_pager(0, 0, "Building artist search index...")
            prev_btn.set_sensitive(False)
            next_btn.set_sensitive(False)
            return True

        index_entries = getattr(app, "_artists_index_entries", [])
        filtered = _filter_artist_index_entries(index_entries, query)
        filtered = _sort_artist_index_entries(filtered, app.artists_sort)
        total = len(filtered)
        library_total = len(index_entries)
        page_size = app.artists_page_size
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        if total_pages > 0 and app.artists_page >= total_pages:
            app.artists_page = total_pages - 1
        elif total_pages == 0:
            app.artists_page = 0
        start = app.artists_page * page_size
        end = start + page_size
        page_items = [_artist_obj_from_index_entry(entry) for entry in filtered[start:end]]
        _render_items(page_items)
        if total == 0:
            _update_pager(0, 0, "No artists match this search.", subtitle_total_count=library_total)
        else:
            _update_pager(total, total_pages, "", subtitle_total_count=library_total)
        return True

    def _load_remote_page():
        request_token = int(getattr(app, "_artists_browser_request_token", 0) or 0) + 1
        app._artists_browser_request_token = request_token
        requested_page = int(app.artists_page)
        sort_key = str(app.artists_sort or "name_asc")
        known_total = max(0, int(getattr(app, "_artists_total_count", 0) or 0))
        known_total_for_subtitle = known_total if bool(getattr(app, "_artists_total_count_known", False)) else None
        _render_items([])
        _update_pager(known_total, 0, "Loading artists...", subtitle_total_count=known_total_for_subtitle)
        prev_btn.set_sensitive(False)
        next_btn.set_sensitive(False)

        def task(token=request_token, dashboard=dashboard_token, page=requested_page, sort=sort_key, total_hint=known_total):
            # Skip the count API call if the index is already building — it will update
            # _artists_total_count when done, so a separate count fetch is redundant.
            if total_hint > 0 or getattr(app, "_artists_index_building", False):
                total = total_hint
            else:
                total = app.backend.get_favorite_artists_count()
            items = list(
                app.backend.get_favorite_artists_page(
                    limit=app.artists_page_size,
                    offset=page * app.artists_page_size,
                    sort=sort,
                ) or []
            )

            def apply():
                if int(getattr(app, "_artists_dashboard_token", 0) or 0) != dashboard:
                    return False
                if int(getattr(app, "_artists_browser_request_token", 0) or 0) != token:
                    return False
                total_count = max(0, int(total or 0))
                if total_count <= 0 and items:
                    total_count = (page * app.artists_page_size) + len(items)
                app._artists_total_count = total_count
                app._artists_total_count_known = True
                total_pages = (total_count + app.artists_page_size - 1) // app.artists_page_size if total_count > 0 else 0
                if total_pages > 0 and app.artists_page >= total_pages:
                    app.artists_page = total_pages - 1
                    _load_remote_page()
                    return False
                _render_items(items)
                if total_count == 0:
                    _update_pager(0, 0, "No favorite artists yet.", subtitle_total_count=total_count)
                else:
                    status = "Building artist search index..." if getattr(app, "_artists_index_building", False) else ""
                    _update_pager(total_count, total_pages, status, subtitle_total_count=total_count)
                if total_count > 0 and total_pages == 0:
                    prev_btn.set_sensitive(app.artists_page > 0)
                    next_btn.set_sensitive(bool(items) and len(items) >= app.artists_page_size)
                return False

            GLib.idle_add(apply)

        Thread(target=task, daemon=True).start()

    def _refresh_view():
        if _update_from_local_index():
            return
        _load_remote_page()

    def _ensure_index():
        if not current_user_id:
            return
        if getattr(app, "_artists_index_ready", False) and not getattr(app.backend, "_favorite_artists_index_dirty", False):
            return
        if getattr(app, "_artists_index_building", False):
            return
        app._artists_index_building = True
        build_token = int(getattr(app, "_artists_index_build_token", 0) or 0) + 1
        app._artists_index_build_token = build_token
        if not app.artists_query.strip():
            _set_status("Building artist search index...")

        def task(token=build_token, dashboard=dashboard_token, user_id=current_user_id):
            artists = list(app.backend.get_favorites(limit=20000) or [])
            entries = []
            seen = set()
            for artist in artists:
                entry = _artist_index_entry_from_obj(artist)
                if not entry:
                    continue
                artist_id = str(entry.get("id") or "")
                if artist_id in seen:
                    continue
                seen.add(artist_id)
                entries.append(entry)

            def apply():
                if int(getattr(app, "_artists_index_build_token", 0) or 0) != token:
                    return False
                if str(getattr(getattr(app.backend, "user", None), "id", "") or "") != user_id:
                    return False
                app._artists_index_entries = entries
                app._artists_index_ready = True
                app._artists_index_building = False
                app._artists_index_user_id = user_id
                app._artists_total_count = max(int(getattr(app, "_artists_total_count", 0) or 0), len(entries))
                app._artists_total_count_known = True
                app.backend._favorite_artists_index_dirty = False
                if int(getattr(app, "_artists_dashboard_token", 0) or 0) != dashboard:
                    return False
                if app.artists_query.strip():
                    _refresh_view()
                else:
                    _set_subtitle(app._artists_total_count)
                    if status_lbl.get_text() == "Building artist search index...":
                        _set_status("")
                return False

            GLib.idle_add(apply)

        Thread(target=task, daemon=True).start()

    def _on_prev_clicked(_btn):
        if app.artists_page <= 0:
            return
        app.artists_page -= 1
        _refresh_view()

    def _on_next_clicked(_btn):
        app.artists_page += 1
        _refresh_view()

    def _on_search_changed(entry):
        app.artists_query = str(entry.get_text() or "")
        app.artists_page = 0
        _refresh_view()

    def _on_sort_changed(dropdown, _pspec):
        idx = int(dropdown.get_selected())
        app.artists_sort = sort_options[idx][0] if 0 <= idx < len(sort_options) else "name_asc"
        app.artists_page = 0
        _refresh_view()

    prev_btn.connect("clicked", _on_prev_clicked)
    next_btn.connect("clicked", _on_next_clicked)
    search_entry.connect("changed", _on_search_changed)
    sort_dd.connect("notify::selected", _on_sort_changed)

    _refresh_view()
    _ensure_index()


def _album_release_sort_value(album):
    raw = getattr(album, "release_date", None)
    if isinstance(raw, datetime):
        try:
            return float(raw.timestamp())
        except Exception:
            return float("-inf")
    text = str(raw or "").strip()
    if not text:
        return float("-inf")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return float(datetime.fromisoformat(text).timestamp())
    except Exception:
        year = _album_release_year_text(album)
        try:
            return float(int(year))
        except Exception:
            return float("-inf")


def _sort_artist_release_groups(items):
    seq = list(items or [])
    seq.sort(
        key=lambda item: (
            _album_release_sort_value(item),
            str(getattr(item, "name", "") or "").lower(),
            str(getattr(item, "id", "") or ""),
        ),
        reverse=True,
    )
    return seq


def _format_track_duration_label(track):
    try:
        dur = int(getattr(track, "duration", 0) or 0)
    except Exception:
        dur = 0
    if dur <= 0:
        return ""
    mins, secs = divmod(dur, 60)
    return f"{mins}:{secs:02d}"


def _compact_count_text(value, suffix):
    try:
        num = int(value or 0)
    except Exception:
        num = 0
    if num <= 0:
        return ""
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M {suffix}"
    if num >= 1_000:
        return f"{num / 1_000:.1f}K {suffix}"
    return f"{num} {suffix}"


def _artist_fans_text(artist):
    for attr in ("num_fans", "number_of_fans", "fans"):
        val = getattr(artist, attr, None)
        text = _compact_count_text(val, "fans")
        if text:
            return text
    return "Top tracks, albums and EP & singles"


def _load_picture_cover_async(picture, url_provider, cache_dir):
    try:
        picture.set_paintable(None)
    except Exception:
        pass

    def task():
        try:
            url = url_provider() if callable(url_provider) else url_provider
            if not url:
                return
            if isinstance(url, str) and os.path.exists(url):
                f_path = url
            else:
                f_path = utils.download_to_cache(str(url), cache_dir)
            if not f_path:
                return

            def apply():
                try:
                    if hasattr(picture, "set_filename"):
                        picture.set_filename(f_path)
                    else:
                        texture = Gdk.Texture.new_from_filename(f_path)
                        picture.set_paintable(texture)
                except Exception:
                    pass
                return False

            GLib.idle_add(apply)
        except Exception:
            logger.debug("Artist hero image load failed", exc_info=True)

    Thread(target=task, daemon=True).start()


def _artist_release_initial_visible_count(app):
    available_width = 0
    try:
        if getattr(app, "alb_scroll", None) is not None:
            available_width = int(app.alb_scroll.get_width() or 0)
    except Exception:
        available_width = 0

    if available_width <= 0:
        try:
            win = getattr(app, "win", None)
            if win is not None:
                available_width = int(win.get_width() or 0)
        except Exception:
            available_width = 0

    if available_width <= 0:
        try:
            base_width = int(getattr(app, "saved_width", 0) or 0)
        except Exception:
            base_width = 0
        if base_width <= 0:
            base_width = int(getattr(ui_config, "WINDOW_WIDTH", 1250) or 1250)
        sidebar_width = max(int(base_width * float(getattr(ui_config, "SIDEBAR_RATIO", 0.15))), 120)
        available_width = max(320, base_width - sidebar_width - 64)

    # Card width is dominated by cover size plus padding/gap.
    item_width = max(150, int(getattr(utils, "COVER_SIZE", 170) or 170) + 20)
    gap = 16
    columns = max(1, min(10, int((available_width + gap) // (item_width + gap)) or 1))
    return max(1, columns * 2)


def _artist_detail_available_width(app):
    available_width = 0
    try:
        if getattr(app, "alb_scroll", None) is not None:
            available_width = int(app.alb_scroll.get_width() or 0)
    except Exception:
        available_width = 0

    if available_width <= 0:
        try:
            content_box = getattr(app, "collection_content_box", None)
            if content_box is not None:
                available_width = int(content_box.get_width() or 0)
        except Exception:
            available_width = 0

    if available_width <= 0:
        try:
            overlay = getattr(app, "content_overlay", None)
            if overlay is not None:
                available_width = int(overlay.get_width() or 0)
        except Exception:
            available_width = 0

    if available_width <= 0:
        try:
            overlay = getattr(app, "body_overlay", None)
            if overlay is not None:
                available_width = int(overlay.get_width() or 0)
        except Exception:
            available_width = 0

    if available_width <= 0:
        try:
            win = getattr(app, "win", None)
            if win is not None:
                available_width = int(win.get_width() or 0)
        except Exception:
            available_width = 0

    if available_width <= 0:
        try:
            base_width = int(getattr(app, "saved_width", 0) or 0)
        except Exception:
            base_width = 0
        if base_width <= 0:
            base_width = int(getattr(ui_config, "WINDOW_WIDTH", 1250) or 1250)
        sidebar_width = max(int(base_width * float(getattr(ui_config, "SIDEBAR_RATIO", 0.15))), 120)
        available_width = max(320, base_width - sidebar_width)

    return max(320, int(available_width))


def _artist_detail_available_height(app):
    available_height = 0
    try:
        overlay = getattr(app, "body_overlay", None)
        if overlay is not None:
            available_height = int(overlay.get_height() or 0)
    except Exception:
        available_height = 0

    if available_height <= 0:
        try:
            overlay = getattr(app, "content_overlay", None)
            if overlay is not None:
                available_height = int(overlay.get_height() or 0)
        except Exception:
            available_height = 0

    if available_height <= 0:
        try:
            win = getattr(app, "win", None)
            if win is not None:
                available_height = int(win.get_height() or 0)
        except Exception:
            available_height = 0

    if available_height <= 0:
        available_height = int(getattr(ui_config, "WINDOW_HEIGHT", 800) or 800)

    return max(240, int(available_height))


def _artist_detail_column_width(app):
    return max(1, int(_artist_detail_available_width(app) // 3))


def _artist_detail_hero_height(app):
    return _artist_detail_column_width(app)


def _artist_detail_center_width(app):
    return _artist_detail_column_width(app)


def render_artist_detail(app, artist, render_token=None):
    token = int(render_token if render_token is not None else getattr(app, "_artist_albums_render_token", 0) or 0)
    detail_t0 = time.monotonic()
    _clear_container(app.collection_content_box)
    app.playlist_track_list = None
    app.queue_track_list = None
    try:
        app.collection_content_box.set_margin_start(0)
        app.collection_content_box.set_margin_end(0)
        app.collection_content_box.set_margin_bottom(int(getattr(app, "collection_base_margin_bottom", 32) or 32))
    except Exception:
        pass

    hero = Gtk.Overlay(css_classes=["artist-detail-hero"], hexpand=True)
    hero.set_size_request(-1, _artist_detail_hero_height(app))
    hero_strip = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        homogeneous=True,
        hexpand=True,
        vexpand=True,
        css_classes=["artist-detail-hero-strip"],
    )

    def _build_side_panel(extra_class):
        panel = Gtk.Overlay(css_classes=["artist-detail-hero-panel", extra_class], hexpand=True, vexpand=True)
        pic = Gtk.Picture(css_classes=["artist-detail-hero-image", "artist-detail-hero-side-image"])
        pic.set_can_shrink(True)
        pic.set_size_request(-1, _artist_detail_hero_height(app))
        panel.set_child(pic)
        dim = Gtk.Box(css_classes=["artist-detail-hero-side-dim"])
        dim.set_hexpand(True)
        dim.set_vexpand(True)
        panel.add_overlay(dim)
        return panel, pic

    left_panel, left_pic = _build_side_panel("artist-detail-hero-left")
    center_panel = Gtk.Overlay(css_classes=["artist-detail-hero-panel", "artist-detail-hero-center"], hexpand=False, vexpand=True)
    center_pic = Gtk.Picture(css_classes=["artist-detail-hero-image", "artist-detail-hero-center-image"])
    try:
        center_pic.set_content_fit(Gtk.ContentFit.CONTAIN)
    except Exception:
        pass
    center_pic.set_can_shrink(True)
    center_pic.set_size_request(_artist_detail_center_width(app), _artist_detail_hero_height(app))
    _load_picture_cover_async(center_pic, lambda a=artist: app.backend.get_artist_artwork_url(a, 750), app.cache_dir)
    center_panel.set_child(center_pic)
    center_fade = Gtk.Box(css_classes=["artist-detail-hero-center-fade"])
    center_fade.set_hexpand(True)
    center_fade.set_vexpand(True)
    center_panel.add_overlay(center_fade)
    right_panel, right_pic = _build_side_panel("artist-detail-hero-right")

    hero_strip.append(left_panel)
    hero_strip.append(center_panel)
    hero_strip.append(right_panel)
    hero.set_child(hero_strip)

    scrim = Gtk.Box(css_classes=["artist-detail-hero-scrim"])
    scrim.set_hexpand(True)
    scrim.set_vexpand(True)
    hero.add_overlay(scrim)

    hero_fav_btn = Gtk.Button(
        icon_name="hiresti-favorite-outline-symbolic",
        css_classes=["flat", "circular", "artist-detail-fav-btn"],
        valign=Gtk.Align.CENTER,
    )
    hero_fav_btn.set_tooltip_text("Favorite Artist")
    hero_fav_btn.connect("clicked", app.on_artist_fav_clicked)

    hero_content = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=8,
        css_classes=["artist-detail-hero-content"],
        valign=Gtk.Align.END,
        halign=Gtk.Align.START,
    )
    hero_content.set_hexpand(True)
    hero_content.append(Gtk.Label(label="Artist", xalign=0, css_classes=["artist-detail-kicker"]))
    hero_title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, hexpand=True)
    hero_title = Gtk.Label(
        label=str(getattr(artist, "name", "") or "Unknown Artist"),
        xalign=0,
        wrap=True,
        css_classes=["artist-detail-title"],
    )
    hero_title.set_max_width_chars(28)
    hero_title.set_hexpand(True)
    hero_title.set_halign(Gtk.Align.START)
    hero_title_row.append(hero_title)
    hero_title_row.append(hero_fav_btn)
    hero_content.append(hero_title_row)
    hero_content.append(Gtk.Label(label=_artist_fans_text(artist), xalign=0, css_classes=["artist-detail-meta"]))
    hero.add_overlay(hero_content)
    app._update_fav_icon(hero_fav_btn, app.backend.is_artist_favorite(getattr(artist, "id", None)))
    app.collection_content_box.append(hero)

    def _apply_hero_size(source="unknown"):
        live_width = 0
        try:
            live_width = int(hero.get_width() or 0)
        except Exception:
            live_width = 0
        try:
            content_w = int(getattr(app, "collection_content_box", None).get_width() or 0) if getattr(app, "collection_content_box", None) is not None else 0
        except Exception:
            content_w = 0
        try:
            scroll_w = int(getattr(app, "alb_scroll", None).get_width() or 0) if getattr(app, "alb_scroll", None) is not None else 0
        except Exception:
            scroll_w = 0
        try:
            content_overlay_w = int(getattr(app, "content_overlay", None).get_width() or 0) if getattr(app, "content_overlay", None) is not None else 0
        except Exception:
            content_overlay_w = 0
        try:
            body_overlay_w = int(getattr(app, "body_overlay", None).get_width() or 0) if getattr(app, "body_overlay", None) is not None else 0
        except Exception:
            body_overlay_w = 0
        try:
            win_w = int(getattr(app, "win", None).get_width() or 0) if getattr(app, "win", None) is not None else 0
        except Exception:
            win_w = 0
        width_source = _artist_detail_available_width(app)
        center_w = max(1, int(width_source // 3))
        side = center_w
        side_target = center_w
        sig = (str(source), live_width, content_w, scroll_w, content_overlay_w, body_overlay_w, win_w, width_source, side, center_w)
        if sig != getattr(app, "_artist_detail_last_layout_log", None):
            app._artist_detail_last_layout_log = sig
            logger.info(
                "ARTIST HERO LAYOUT source=%s hero_w=%s content_w=%s scroll_w=%s content_overlay_w=%s body_overlay_w=%s win_w=%s width_source=%s side=%s center_w=%s",
                str(source),
                int(live_width),
                int(content_w),
                int(scroll_w),
                int(content_overlay_w),
                int(body_overlay_w),
                int(win_w),
                int(width_source),
                int(side),
                int(center_w),
            )
        try:
            hero.set_size_request(-1, side)
            left_panel.set_size_request(side_target, side)
            center_panel.set_size_request(center_w, side)
            center_pic.set_size_request(center_w, side)
            right_panel.set_size_request(side_target, side)
        except Exception:
            pass
        utils.load_picture_cover_crop(
            left_pic,
            lambda a=artist: app.backend.get_artist_artwork_url(a, 750),
            app.cache_dir,
            target_width=side_target,
            target_height=side,
            anchor_x=1.0,
            anchor_y=0.5,
        )
        utils.load_picture_cover_crop(
            right_pic,
            lambda a=artist: app.backend.get_artist_artwork_url(a, 750),
            app.cache_dir,
            target_width=side_target,
            target_height=side,
            anchor_x=0.0,
            anchor_y=0.5,
        )
        return False

    def _schedule_hero_size():
        """Debounce hero layout recalculations: coalesce rapid resize signals into one call."""
        pending = int(getattr(app, "_artist_hero_layout_pending_src", 0) or 0)
        if pending:
            try:
                GLib.source_remove(pending)
            except Exception:
                pass
        def _do():
            app._artist_hero_layout_pending_src = 0
            _apply_hero_size("resize")
            return False
        app._artist_hero_layout_pending_src = GLib.timeout_add(30, _do)

    app._artist_detail_layout_refresh = lambda: _apply_hero_size("layout-proportions")
    _layout_handler_ids = []
    hero.connect("notify::width", lambda *_args: _schedule_hero_size())
    if getattr(app, "collection_content_box", None) is not None:
        try:
            _layout_handler_ids.append((app.collection_content_box, app.collection_content_box.connect("notify::width", lambda *_args: _schedule_hero_size())))
        except Exception:
            pass
    if getattr(app, "alb_scroll", None) is not None:
        try:
            _layout_handler_ids.append((app.alb_scroll, app.alb_scroll.connect("notify::width", lambda *_args: _schedule_hero_size())))
            _layout_handler_ids.append((app.alb_scroll, app.alb_scroll.connect("notify::height", lambda *_args: _schedule_hero_size())))
        except Exception:
            pass
    if getattr(app, "content_overlay", None) is not None:
        try:
            _layout_handler_ids.append((app.content_overlay, app.content_overlay.connect("notify::width", lambda *_args: _schedule_hero_size())))
        except Exception:
            pass
    if getattr(app, "win", None) is not None:
        try:
            _layout_handler_ids.append((app.win, app.win.connect("notify::width", lambda *_args: _schedule_hero_size())))
            _layout_handler_ids.append((app.win, app.win.connect("notify::height", lambda *_args: _schedule_hero_size())))
        except Exception:
            pass
    if getattr(app, "body_overlay", None) is not None:
        try:
            _layout_handler_ids.append((app.body_overlay, app.body_overlay.connect("notify::width", lambda *_args: _schedule_hero_size())))
            _layout_handler_ids.append((app.body_overlay, app.body_overlay.connect("notify::height", lambda *_args: _schedule_hero_size())))
        except Exception:
            pass
    app._artist_detail_layout_handler_ids = _layout_handler_ids
    GLib.idle_add(_apply_hero_size, "initial")

    body_box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=20,
        margin_start=int(getattr(app, "collection_base_margin_start", 20) or 20),
        margin_end=int(getattr(app, "collection_base_margin_end", 20) or 20),
    )
    app.collection_content_box.append(body_box)

    def _append_section_header(title, count=0):
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section", "artist-detail-section"])
        head = Gtk.Box(spacing=8, css_classes=["home-section-head"], margin_start=6, margin_end=6, margin_bottom=8)
        head.append(Gtk.Label(label=title, xalign=0, hexpand=True, css_classes=["home-section-title"]))
        section.append(head)
        body_box.append(section)
        return section

    top_section = _append_section_header("Top Tracks", 0)
    top_grid = Gtk.Grid(column_spacing=16, row_spacing=8, hexpand=True)
    top_section.append(top_grid)
    top_loading = Gtk.Label(
        label="Loading top tracks...",
        xalign=0,
        css_classes=["dim-label"],
        margin_start=8,
        margin_top=8,
    )
    top_section.append(top_loading)

    albums_section = _append_section_header("Albums", 0)
    albums_flow = Gtk.FlowBox(
        homogeneous=True,
        valign=Gtk.Align.START,
        min_children_per_line=4,
        max_children_per_line=10,
        selection_mode=Gtk.SelectionMode.NONE,
        column_spacing=16,
        row_spacing=16,
        css_classes=["home-flow"],
    )
    albums_flow.connect("child-activated", app.on_grid_item_activated)
    albums_section.append(albums_flow)
    albums_action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    albums_action_row.append(Gtk.Box(hexpand=True))
    albums_more_btn = Gtk.Button(label="Show more", css_classes=["flat", "liked-action-btn"])
    albums_action_row.append(albums_more_btn)
    albums_section.append(albums_action_row)
    albums_loading = Gtk.Label(
        label="Loading albums...",
        xalign=0,
        css_classes=["dim-label"],
        margin_start=8,
        margin_top=8,
    )
    albums_section.append(albums_loading)

    eps_section = _append_section_header("EP & Singles", 0)
    eps_flow = Gtk.FlowBox(
        homogeneous=True,
        valign=Gtk.Align.START,
        min_children_per_line=4,
        max_children_per_line=10,
        selection_mode=Gtk.SelectionMode.NONE,
        column_spacing=16,
        row_spacing=16,
        css_classes=["home-flow"],
    )
    eps_flow.connect("child-activated", app.on_grid_item_activated)
    eps_section.append(eps_flow)
    eps_action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    eps_action_row.append(Gtk.Box(hexpand=True))
    eps_more_btn = Gtk.Button(label="Show more", css_classes=["flat", "liked-action-btn"])
    eps_action_row.append(eps_more_btn)
    eps_section.append(eps_action_row)
    eps_loading = Gtk.Label(
        label="Loading EPs & singles...",
        xalign=0,
        css_classes=["dim-label"],
        margin_start=8,
        margin_top=8,
    )
    eps_section.append(eps_loading)

    fans_section = _append_section_header("Fans Also Like", 0)
    fans_flow = Gtk.FlowBox(
        valign=Gtk.Align.START,
        max_children_per_line=30,
        selection_mode=Gtk.SelectionMode.NONE,
        column_spacing=24,
        row_spacing=28,
        css_classes=["home-flow"],
    )
    fans_section.append(fans_flow)
    fans_section.set_visible(False)

    def _render_track_rows(tracks):
        _clear_container(top_grid)
        if top_loading.get_parent() is not None:
            top_section.remove(top_loading)
        if not tracks:
            hint = Gtk.Label(
                label="No top tracks available for this artist.",
                xalign=0,
                css_classes=["dim-label"],
                margin_start=8,
                margin_top=8,
            )
            top_section.append(hint)
            return

        playing_id = str(getattr(app, "playing_track_id", "") or "").strip()

        def _build_top_track_btn(track, rank_idx, all_tracks):
            is_playing = bool(playing_id and str(getattr(track, "id", "") or "").strip() == playing_id)
            row_box = Gtk.Box(spacing=10, margin_start=6, margin_end=6, margin_top=4, margin_bottom=4)
            rank_classes = ["history-rank-chip"]
            if rank_idx == 0:
                rank_classes.append("history-rank-top1")
            elif rank_idx == 1:
                rank_classes.append("history-rank-top2")
            elif rank_idx == 2:
                rank_classes.append("history-rank-top3")
            rank_label = Gtk.Label(label=f"{rank_idx + 1:02d}", xalign=0.5, css_classes=rank_classes)
            rank_label.set_size_request(24, 24)
            rank_label.set_valign(Gtk.Align.CENTER)
            row_box.append(rank_label)

            img = Gtk.Image(pixel_size=DASHBOARD_TRACK_COVER_SIZE, css_classes=["album-cover-img"])
            cover = app.backend.get_artwork_url(track, 320)
            if not cover:
                cover = getattr(track, "cover", None) or getattr(getattr(track, "album", None), "cover", None)
            if cover:
                utils.load_img(img, cover, app.cache_dir, DASHBOARD_TRACK_COVER_SIZE)
            else:
                img.set_from_icon_name("audio-x-generic-symbolic")
            row_box.append(_build_feed_media_overlay(img, DASHBOARD_TRACK_COVER_SIZE, "album-cover-img"))

            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
            track_name = str(getattr(track, "name", "") or "Unknown Track")
            album_name = str(getattr(getattr(track, "album", None), "name", "") or "")
            title = Gtk.Label(label=track_name, xalign=0, ellipsize=3, max_width_chars=26, css_classes=["home-card-title"])
            text_box.append(title)
            if album_name:
                subtitle = Gtk.Label(label=album_name, xalign=0, ellipsize=3, max_width_chars=28, css_classes=["dim-label", "home-card-subtitle"])
                text_box.append(subtitle)
            row_box.append(text_box)

            duration_txt = _format_track_duration_label(track)
            if duration_txt:
                dur_lbl = Gtk.Label(label=duration_txt, xalign=1.0, css_classes=["dim-label", "home-card-subtitle"])
                dur_lbl.set_halign(Gtk.Align.END)
                dur_lbl.set_size_request(42, -1)
                row_box.append(dur_lbl)

            playing_icon = Gtk.Image(icon_name="media-playback-start-symbolic", pixel_size=14)
            playing_icon.set_halign(Gtk.Align.END)
            playing_icon.set_valign(Gtk.Align.CENTER)
            playing_icon.add_css_class("track-row-playing-icon")
            playing_icon.set_visible(is_playing)
            row_box.append(playing_icon)

            btn = Gtk.Button(css_classes=_dashboard_track_row_button_classes(is_playing))
            btn.set_hexpand(True)
            btn.set_halign(Gtk.Align.FILL)
            btn._dashboard_track_id = str(getattr(track, "id", "") or "").strip()
            btn._dashboard_track_name = _norm_trackish_text(track_name)
            btn._dashboard_track_artist = _norm_trackish_text(str(getattr(getattr(track, "artist", None), "name", "") or ""))
            btn._dashboard_playing_icon = playing_icon
            btn.set_child(row_box)
            btn.connect(
                "clicked",
                lambda _b, arr=list(all_tracks), idx=rank_idx: (
                    setattr(app, "current_track_list", list(arr)),
                    app._set_play_queue(list(arr)),
                    app.play_track(idx),
                ),
            )
            return btn

        total = len(tracks)
        left_count = (total + 1) // 2
        right_count = total - left_count
        for row in range(left_count):
            left_idx = row
            top_grid.attach(_build_top_track_btn(tracks[left_idx], left_idx, tracks), 0, row, 1, 1)
            if row < right_count:
                right_idx = left_count + row
                top_grid.attach(_build_top_track_btn(tracks[right_idx], right_idx, tracks), 1, row, 1, 1)

    def _render_expandable_album_section(items, flow, more_btn, action_row, local_token):
        _clear_container(flow)
        total = len(items)
        if total <= 0:
            more_btn.set_visible(False)
            action_row.set_visible(False)
            return

        initial_count = min(total, _artist_release_initial_visible_count(app))
        visible = list(items[:initial_count])
        remaining = list(items[initial_count:])
        app.batch_load_albums(
            visible,
            _flow=flow,
            _token=local_token,
            _token_attr="_artist_albums_render_token",
        )

        if not remaining:
            more_btn.set_visible(False)
            action_row.set_visible(False)
            return

        action_row.set_visible(True)
        more_btn.set_visible(True)
        more_btn.set_label(f"Show more ({len(remaining)})")

        def _on_more(_btn, rem=list(remaining), target_flow=flow, target_token=local_token, btn_ref=more_btn, row_ref=action_row):
            if int(getattr(app, "_artist_albums_render_token", 0) or 0) != target_token:
                return
            btn_ref.set_sensitive(False)
            app.batch_load_albums(
                rem,
                _flow=target_flow,
                _token=target_token,
                _token_attr="_artist_albums_render_token",
            )
            row_ref.set_visible(False)
            btn_ref.set_visible(False)

        more_btn.connect("clicked", _on_more)

    def _append_empty_hint(section, loading_label, text):
        if loading_label.get_parent() is not None:
            section.remove(loading_label)
        section.append(
            Gtk.Label(
                label=text,
                xalign=0,
                css_classes=["dim-label"],
                margin_start=8,
                margin_top=8,
            )
        )

    def _load_top_tracks(local_token=token):
        started = time.monotonic()
        top_tracks = list(app.backend.get_artist_top_tracks(artist, limit=10) or [])

        def apply():
            if int(getattr(app, "_artist_albums_render_token", 0) or 0) != local_token:
                return False
            logger.info(
                "ARTIST DETAIL section=top_tracks artist=%s count=%s elapsed_ms=%.1f total_since_open_ms=%.1f",
                getattr(artist, "name", "Unknown"),
                len(top_tracks),
                (time.monotonic() - started) * 1000.0,
                (time.monotonic() - detail_t0) * 1000.0,
            )
            _render_track_rows(top_tracks)
            return False

        GLib.idle_add(apply)

    def _load_albums(local_token=token):
        started = time.monotonic()
        albums = _sort_artist_release_groups(app.backend.get_artist_albums_all(artist, limit=2000) or [])

        def apply():
            if int(getattr(app, "_artist_albums_render_token", 0) or 0) != local_token:
                return False
            logger.info(
                "ARTIST DETAIL section=albums artist=%s count=%s elapsed_ms=%.1f total_since_open_ms=%.1f",
                getattr(artist, "name", "Unknown"),
                len(albums),
                (time.monotonic() - started) * 1000.0,
                (time.monotonic() - detail_t0) * 1000.0,
            )
            if albums_loading.get_parent() is not None:
                albums_section.remove(albums_loading)
            _render_expandable_album_section(albums, albums_flow, albums_more_btn, albums_action_row, local_token)
            if not albums:
                albums_action_row.set_visible(False)
                _append_empty_hint(albums_section, albums_loading, "No albums available.")
            return False

        GLib.idle_add(apply)

    def _load_eps(local_token=token):
        started = time.monotonic()
        eps = _sort_artist_release_groups(app.backend.get_artist_ep_singles_all(artist, limit=2000) or [])

        def apply():
            if int(getattr(app, "_artist_albums_render_token", 0) or 0) != local_token:
                return False
            logger.info(
                "ARTIST DETAIL section=eps artist=%s count=%s elapsed_ms=%.1f total_since_open_ms=%.1f",
                getattr(artist, "name", "Unknown"),
                len(eps),
                (time.monotonic() - started) * 1000.0,
                (time.monotonic() - detail_t0) * 1000.0,
            )
            if eps:
                if eps_loading.get_parent() is not None:
                    eps_section.remove(eps_loading)
                eps_section.set_visible(True)
                _render_expandable_album_section(eps, eps_flow, eps_more_btn, eps_action_row, local_token)
            else:
                eps_section.set_visible(False)
            return False

        GLib.idle_add(apply)

    def _load_similar_artists(local_token=token):
        similar = app.backend.get_similar_artists(artist)

        def _build_artist_card(sim_art):
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=_artist_card_classes())
            img = Gtk.Image(pixel_size=150, css_classes=["circular-avatar"])
            utils.load_img(img, lambda a=sim_art: app.backend.get_artist_artwork_url(a, 320), app.cache_dir, 150)
            v.append(_build_feed_media_overlay(img, 150, "circular-avatar"))
            v.append(Gtk.Label(
                label=str(getattr(sim_art, "name", "") or ""),
                ellipsize=2, halign=Gtk.Align.CENTER,
                wrap=True, max_width_chars=14,
                css_classes=["heading", "home-card-title"],
            ))
            btn = Gtk.Button(css_classes=["flat", "history-card-btn", "home-feed-btn"])
            btn.set_child(v)
            btn.connect("clicked", lambda _b, a=sim_art: app.on_artist_clicked(a))
            return btn

        def apply():
            if int(getattr(app, "_artist_albums_render_token", 0) or 0) != local_token:
                return False
            if not similar:
                fans_section.set_visible(False)
                return False
            _clear_container(fans_flow)
            for sim_art in similar:
                fans_flow.append(_build_artist_card(sim_art))

            fans_more_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            fans_more_row.append(Gtk.Box(hexpand=True))
            more_btn = Gtk.Button(css_classes=["flat", "liked-action-btn"])
            more_btn.set_visible(False)
            fans_more_row.append(more_btn)
            fans_more_row.set_visible(False)
            fans_section.append(fans_more_row)
            fans_section.set_visible(True)

            expanded = [False]

            def _apply_2_row_limit():
                if expanded[0]:
                    return False
                if fans_flow.get_parent() is None:
                    return False
                if fans_flow.get_height() == 0:
                    GLib.idle_add(_apply_2_row_limit)
                    return False
                children = []
                ch = fans_flow.get_first_child()
                while ch:
                    children.append(ch)
                    ch = ch.get_next_sibling()
                if not children:
                    return False
                row_ys = []
                for ch in children:
                    try:
                        y = ch.get_allocation().y
                    except Exception:
                        continue
                    if not row_ys or y > row_ys[-1] + 10:
                        row_ys.append(y)
                if len(row_ys) <= 2:
                    for ch in children:
                        ch.set_visible(True)
                    fans_more_row.set_visible(False)
                    return False
                cutoff_y = row_ys[2]
                hidden = 0
                for ch in children:
                    try:
                        visible = ch.get_allocation().y < cutoff_y
                    except Exception:
                        visible = True
                    ch.set_visible(visible)
                    if not visible:
                        hidden += 1
                if hidden > 0:
                    more_btn.set_label(f"Show more ({hidden})")
                    more_btn.set_visible(True)
                    fans_more_row.set_visible(True)
                else:
                    fans_more_row.set_visible(False)
                return False

            def _on_more(_btn):
                expanded[0] = True
                ch = fans_flow.get_first_child()
                while ch:
                    ch.set_visible(True)
                    ch = ch.get_next_sibling()
                fans_more_row.set_visible(False)

            more_btn.connect("clicked", _on_more)
            GLib.idle_add(_apply_2_row_limit)

            # Re-apply on window width change
            scroll = getattr(app, "alb_scroll", None)
            if scroll is not None:
                def _on_width_changed(*_):
                    if not expanded[0] and fans_flow.get_parent() is not None:
                        GLib.idle_add(_apply_2_row_limit)
                hid = scroll.connect("notify::width", _on_width_changed)
                existing = list(getattr(app, "_artist_detail_layout_handler_ids", []) or [])
                existing.append((scroll, hid))
                app._artist_detail_layout_handler_ids = existing

            return False

        GLib.idle_add(apply)

    Thread(target=_load_top_tracks, daemon=True).start()
    Thread(target=_load_albums, daemon=True).start()
    Thread(target=_load_eps, daemon=True).start()
    Thread(target=_load_similar_artists, daemon=True).start()

    def _scroll_to_top():
        try:
            vadj = app.alb_scroll.get_vadjustment() if getattr(app, "alb_scroll", None) else None
            if vadj is not None:
                vadj.set_value(0.0)
        except Exception:
            pass
        return False

    GLib.idle_add(_scroll_to_top)


def batch_load_home(app, sections):
    if not sections:
        return
    render_token = int(getattr(app, "_home_render_token", 0) or 0) + 1
    app._home_render_token = render_token

    def _open_item(item_data):
        if not item_data:
            return
        obj = item_data.get("obj")
        typ = item_data.get("type")
        if typ in {"PageItem", "PageLink"} and obj is not None and hasattr(obj, "get") and callable(obj.get):
            def task():
                try:
                    resolved = obj.get()
                except Exception:
                    resolved = None
                if resolved is None:
                    return

                def apply():
                    resolved_type = type(resolved).__name__
                    if "Track" in resolved_type:
                        app._play_single_track(resolved)
                    elif "Artist" in resolved_type:
                        app.on_artist_clicked(resolved)
                    elif "Playlist" in resolved_type:
                        app.on_remote_playlist_card_clicked(resolved)
                    else:
                        app.show_album_details(resolved)
                    return False

                GLib.idle_add(apply)

            Thread(target=task, daemon=True).start()
            return
        if typ == "Track":
            app._play_single_track(obj)
            return
        if typ == "Artist":
            app.on_artist_clicked(obj)
            return
        if "Playlist" in str(typ or ""):
            app.on_remote_playlist_card_clicked(obj)
            return
        app.show_album_details(obj)

    def _build_home_item_button(item_data):
        return _build_feed_item_button(app, item_data, _open_item)

    render_queue = []
    for sec in sections:
        section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
        section_head = Gtk.Box(spacing=8, css_classes=["home-section-head"])
        context_header = sec.get("context_header") or {}
        context_image_url = str(context_header.get("image_url", "") or "").strip()
        if context_image_url:
            context_img = Gtk.Image(pixel_size=48, css_classes=["album-cover-img"])
            context_img.set_size_request(48, 48)
            utils.load_img(context_img, context_image_url, app.cache_dir, 48)
            if context_header.get("obj") is not None:
                ctx_btn = Gtk.Button(css_classes=["flat", "history-card-btn"])
                ctx_btn.set_child(context_img)
                ctx_btn.connect("clicked", lambda _b, d=context_header: _open_item(d))
                section_head.append(ctx_btn)
            else:
                section_head.append(context_img)
        heading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        header_lines = _home_section_header_lines(sec)
        if header_lines["kicker"]:
            heading_box.append(
                Gtk.Label(
                    label=header_lines["kicker"],
                    xalign=0,
                    hexpand=True,
                    wrap=True,
                    css_classes=["dim-label", "home-card-subtitle", "home-section-subtitle"],
                )
            )
        if context_header.get("obj") is not None:
            section_title_label = Gtk.Label(label=header_lines["title"], xalign=0, css_classes=["home-section-title", "home-section-title-link"])
            section_title_btn = Gtk.Button(css_classes=["home-section-title-btn"], hexpand=True, halign=Gtk.Align.FILL)
            section_title_btn.set_child(section_title_label)
            section_title_btn.connect("clicked", lambda _b, d=context_header: _open_item(d))
            heading_box.append(section_title_btn)
        else:
            section_title = Gtk.Label(label=header_lines["title"], xalign=0, hexpand=True, css_classes=["home-section-title"])
            heading_box.append(section_title)
        section_subtitle = header_lines["secondary"]
        if section_subtitle:
            heading_box.append(
                Gtk.Label(
                    label=section_subtitle,
                    xalign=0,
                    hexpand=True,
                    wrap=True,
                    css_classes=["dim-label", "home-card-subtitle", "home-section-subtitle"],
                )
            )
        section_head.append(heading_box)
        section_box.append(section_head)

        flow = Gtk.FlowBox(
            homogeneous=False,
            min_children_per_line=2,
            max_children_per_line=16,
            column_spacing=16,
            row_spacing=16,
            selection_mode=Gtk.SelectionMode.NONE,
        )
        section_box.append(flow)
        app.collection_content_box.append(section_box)
        render_queue.append({"flow": flow, "items": list(sec["items"]), "index": 0})

    # Render cards progressively to avoid one long UI stall on Home.
    def _render_home_chunk():
        # Stop rendering immediately when Home/Top is no longer active or this render got superseded.
        current_token = int(getattr(app, "_home_render_token", 0) or 0)
        if current_token != render_token:
            return False
        row = app.nav_list.get_selected_row() if getattr(app, "nav_list", None) is not None else None
        if not row or getattr(row, "nav_id", None) not in {"home", "top"}:
            return False
        budget = 10  # number of cards per tick
        while budget > 0 and render_queue:
            ctx = render_queue[0]
            i = int(ctx["index"])
            items = ctx["items"]
            if i >= len(items):
                render_queue.pop(0)
                continue
            item_data = items[i]
            btn = _build_home_item_button(item_data)
            child = Gtk.FlowBoxChild()
            child.set_child(btn)
            ctx["flow"].append(child)
            ctx["index"] = i + 1
            budget -= 1

        if render_queue:
            GLib.timeout_add(12, _render_home_chunk)
        return False

    GLib.idle_add(_render_home_chunk)


def render_history_dashboard(app):
    _clear_container(app.collection_content_box)

    recent_albums = app.history_mgr.get_albums() if hasattr(app, "history_mgr") else []
    top_tracks = app.history_mgr.get_top_tracks(limit=20) if hasattr(app, "history_mgr") else []

    tabs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    history_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
    history_stack.set_hhomogeneous(False)
    history_stack.set_vhomogeneous(False)
    history_switcher = Gtk.StackSwitcher(stack=history_stack)
    history_switcher.set_halign(Gtk.Align.START)
    tabs_box.append(history_switcher)
    tabs_box.append(history_stack)

    # --- Tab 1: Top 20 (shell + header) ---
    sec_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section", "history-section"])
    top_grid = Gtk.Grid(column_spacing=16, row_spacing=8, hexpand=True)
    sec_top.append(top_grid)
    history_stack.add_titled(sec_top, "history-top20", "Top 20")

    # --- Tab 2: Recent Albums (shell + header only, content populated lazily) ---
    sec_recent = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section", "history-section"])
    flow_recent = Gtk.FlowBox(
        homogeneous=True,
        min_children_per_line=1,
        max_children_per_line=12,
        column_spacing=16,
        row_spacing=16,
        selection_mode=Gtk.SelectionMode.NONE,
    )
    flow_recent.set_hexpand(True)
    sec_recent.append(flow_recent)
    history_stack.add_titled(sec_recent, "history-recent", "Recent Albums")

    history_stack.set_visible_child_name("history-top20")
    app.collection_content_box.append(tabs_box)

    def _norm_text(v):
        s = str(v or "").strip().lower()
        keep = []
        for ch in s:
            if ch.isalnum() or ch.isspace():
                keep.append(ch)
        return " ".join("".join(keep).split())

    _playing_track = getattr(app, "playing_track", None)
    _playing_id = str(getattr(app, "playing_track_id", "") or "").strip()
    _now_name = _norm_text(getattr(_playing_track, "name", "")) if _playing_track else ""
    _now_artist = _norm_text(getattr(getattr(_playing_track, "artist", None), "name", "")) if _playing_track else ""

    # --- Populate Tab 1 immediately (data is local, 20 items max) ---
    for i, tr in enumerate(top_tracks):
        row_box = Gtk.Box(spacing=10, margin_start=6, margin_end=6, margin_top=4, margin_bottom=4)
        rank_classes = ["history-rank-chip"]
        if i == 0:
            rank_classes.append("history-rank-top1")
        elif i == 1:
            rank_classes.append("history-rank-top2")
        elif i == 2:
            rank_classes.append("history-rank-top3")
        rank_label = Gtk.Label(label=f"{i + 1:02d}", xalign=0.5, css_classes=rank_classes)
        rank_label.set_size_request(24, 24)
        rank_label.set_valign(Gtk.Align.CENTER)
        rank_label.set_vexpand(False)
        row_box.append(rank_label)

        img = Gtk.Image(pixel_size=DASHBOARD_TRACK_COVER_SIZE, css_classes=["album-cover-img"])
        cover = app.backend.get_artwork_url(tr, 320)
        if not cover:
            cover = getattr(tr, "cover", None)
        if not cover:
            cover = getattr(getattr(tr, "album", None), "cover", None)
        if cover:
            utils.load_img(img, cover, app.cache_dir, DASHBOARD_TRACK_COVER_SIZE)
        else:
            img.set_from_icon_name("audio-x-generic-symbolic")
        row_box.append(_build_feed_media_overlay(img, DASHBOARD_TRACK_COVER_SIZE, "album-cover-img"))

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        track_name = getattr(tr, "name", "Unknown Track")
        artist_name = getattr(getattr(tr, "artist", None), "name", "Unknown")
        title = Gtk.Label(
            label=track_name,
            xalign=0,
            ellipsize=3,
            max_width_chars=26,
            css_classes=["home-card-title"],
        )
        subtitle = Gtk.Label(
            label=artist_name,
            xalign=0,
            ellipsize=3,
            max_width_chars=28,
            css_classes=["dim-label", "home-card-subtitle"],
        )
        text_box.append(title)
        text_box.append(subtitle)
        row_box.append(text_box)

        play_count = int(getattr(tr, "play_count", 0) or 0)
        play_count_label = Gtk.Label(label=f"x{play_count}", xalign=1.0, css_classes=["dim-label", "home-card-subtitle"])
        play_count_label.set_halign(Gtk.Align.END)
        play_count_label.set_size_request(42, -1)
        row_box.append(play_count_label)

        track_id = getattr(tr, "id", None) or getattr(tr, "track_id", None)
        row_name_norm = _norm_text(track_name)
        row_artist_norm = _norm_text(artist_name)
        is_playing = False
        if _playing_id and track_id is not None and str(track_id).strip() == _playing_id:
            is_playing = True
        else:
            name_match = bool(
                _now_name
                and row_name_norm
                and (row_name_norm == _now_name or row_name_norm in _now_name or _now_name in row_name_norm)
            )
            if name_match:
                if not _now_artist:
                    is_playing = True
                else:
                    is_playing = bool(
                        row_artist_norm
                        and (row_artist_norm == _now_artist or row_artist_norm in _now_artist or _now_artist in row_artist_norm)
                    )

        playing_icon = Gtk.Image(icon_name="media-playback-start-symbolic", pixel_size=14)
        playing_icon.set_halign(Gtk.Align.END)
        playing_icon.set_valign(Gtk.Align.CENTER)
        playing_icon.add_css_class("track-row-playing-icon")
        playing_icon.set_visible(is_playing)
        row_box.append(playing_icon)

        btn = Gtk.Button(css_classes=_dashboard_track_row_button_classes(is_playing))
        btn.set_hexpand(True)
        btn.set_halign(Gtk.Align.FILL)
        btn._dashboard_track_id = str(track_id or "").strip()
        btn._dashboard_track_name = row_name_norm
        btn._dashboard_track_artist = row_artist_norm
        btn._dashboard_playing_icon = playing_icon
        btn.set_child(row_box)
        btn.connect("clicked", lambda _b, idx=i: app.on_history_track_clicked(top_tracks, idx))

        col = 0 if i < 10 else 1
        row = i if i < 10 else i - 10
        top_grid.attach(btn, col, row, 1, 1)

    # --- Populate Tab 2 lazily on first switch ---
    _recent_populated = [False]

    def _populate_recent():
        if _recent_populated[0]:
            return
        _recent_populated[0] = True
        for alb in recent_albums:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=_feed_card_classes("history-card"))
            img = Gtk.Image(pixel_size=utils.COVER_SIZE, css_classes=["album-cover-img"])
            cover = app.backend.get_artwork_url(alb, 320)
            if cover:
                utils.load_img(img, cover, app.cache_dir, utils.COVER_SIZE)
            else:
                img.set_from_icon_name("audio-x-generic-symbolic")
            card.append(_build_feed_media_overlay(img, utils.COVER_SIZE, "album-cover-img"))
            card.append(
                Gtk.Label(
                    label=getattr(alb, "name", "Unknown Album"),
                    halign=Gtk.Align.CENTER,
                    ellipsize=3,
                    wrap=True,
                    max_width_chars=14,
                    css_classes=["home-card-title"],
                )
            )
            artist_name = getattr(getattr(alb, "artist", None), "name", "Unknown")
            card.append(Gtk.Label(label=artist_name, halign=Gtk.Align.CENTER, ellipsize=3, css_classes=["dim-label", "home-card-subtitle"]))
            btn = Gtk.Button(css_classes=["flat", "history-card-btn", "home-feed-btn"])
            btn.set_child(card)
            btn.connect("clicked", lambda _b, a=alb: app.on_history_album_clicked(a))
            child = Gtk.FlowBoxChild()
            child.set_child(btn)
            flow_recent.append(child)

    def _on_history_tab_changed(stack, _pspec):
        try:
            name = str(stack.get_visible_child_name() or "")
        except Exception:
            name = ""
        if name == "history-recent":
            _populate_recent()

    history_stack.connect("notify::visible-child-name", _on_history_tab_changed)


def render_top_dashboard(app, prefer_cache=True):
    _clear_container(app.collection_content_box)

    def _render_sections(sections):
        _clear_container(app.collection_content_box)
        if sections:
            app._top_sections_cache = list(sections)
            app._top_sections_cache_time = time.monotonic()
            tabs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            top_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
            top_stack.set_hhomogeneous(False)
            top_stack.set_vhomogeneous(False)
            top_switcher = Gtk.StackSwitcher(stack=top_stack)
            top_switcher.set_halign(Gtk.Align.START)
            tabs_box.append(top_switcher)
            tabs_box.append(top_stack)

            def _open_item(item_data):
                if not item_data:
                    return
                obj = item_data.get("obj")
                typ = item_data.get("type")
                if typ in {"PageItem", "PageLink"} and obj is not None and hasattr(obj, "get") and callable(obj.get):
                    def task():
                        try:
                            resolved = obj.get()
                        except Exception:
                            resolved = None
                        if resolved is None:
                            return

                        def apply():
                            resolved_type = type(resolved).__name__
                            if "Track" in resolved_type:
                                app._play_single_track(resolved)
                            elif "Artist" in resolved_type:
                                app.on_artist_clicked(resolved)
                            elif "Playlist" in resolved_type:
                                app.on_remote_playlist_card_clicked(resolved)
                            else:
                                app.show_album_details(resolved)
                            return False

                        GLib.idle_add(apply)

                    Thread(target=task, daemon=True).start()
                    return
                if typ == "Track":
                    app._play_single_track(obj)
                    return
                if typ == "Artist":
                    app.on_artist_clicked(obj)
                    return
                if "Playlist" in str(typ or ""):
                    app.on_remote_playlist_card_clicked(obj)
                    return
                app.show_album_details(obj)

            def _build_home_item_button(item_data):
                return _build_feed_item_button(app, item_data, _open_item)

            def _play_tracks_section(items, clicked_src_idx):
                def _resolve_track(item_data):
                    obj = item_data.get("obj")
                    if obj is None:
                        return None
                    try:
                        resolved = obj.get() if hasattr(obj, "get") and callable(obj.get) else obj
                    except Exception:
                        resolved = None
                    if resolved is None:
                        return None
                    if "Track" in str(type(resolved).__name__):
                        return resolved
                    return None

                def task():
                    pairs = []
                    for src_idx, it in enumerate(list(items or [])):
                        t = _resolve_track(it)
                        if t is not None:
                            pairs.append((src_idx, t))

                    if not pairs:
                        clicked = list(items or [])[clicked_src_idx] if 0 <= clicked_src_idx < len(list(items or [])) else None
                        if clicked is not None:
                            GLib.idle_add(lambda: (_open_item(clicked), False)[1])
                        return

                    tracks = [t for _, t in pairs]
                    play_idx = None
                    for i, (src_idx, _t) in enumerate(pairs):
                        if src_idx == clicked_src_idx:
                            play_idx = i
                            break

                    if play_idx is None:
                        # Clicked item didn't resolve as a playable track (e.g. mix/album
                        # in a mixed section) — open it instead of silently playing track 0.
                        clicked = list(items or [])[clicked_src_idx] if 0 <= clicked_src_idx < len(list(items or [])) else None
                        if clicked is not None:
                            GLib.idle_add(lambda: (_open_item(clicked), False)[1])
                        return

                    def apply():
                        app.current_track_list = list(tracks)
                        app._set_play_queue(list(tracks))
                        app.play_track(play_idx)
                        return False

                    GLib.idle_add(apply)

                Thread(target=task, daemon=True).start()

            def _norm_text(v):
                s = str(v or "").strip().lower()
                keep = []
                for ch in s:
                    if ch.isalnum() or ch.isspace():
                        keep.append(ch)
                return " ".join("".join(keep).split())

            # Pre-compute once for all rows — playing_track doesn't change while building
            _playing_track = getattr(app, "playing_track", None)
            _playing_id = str(getattr(app, "playing_track_id", "") or "").strip()
            _now_name = _norm_text(getattr(_playing_track, "name", "")) if _playing_track else ""
            _now_artist = _norm_text(getattr(getattr(_playing_track, "artist", None), "name", "")) if _playing_track else ""

            def _build_top_track_row(item_data, rank_idx, section_items, src_idx):
                def _is_playing_item(data):
                    obj = data.get("obj")
                    item_id = None
                    if obj is not None:
                        item_id = getattr(obj, "id", None) or getattr(obj, "track_id", None)
                        if item_id is None and isinstance(obj, dict):
                            item_id = obj.get("id") or obj.get("track_id")
                    if _playing_id and item_id is not None and str(item_id).strip() == _playing_id:
                        return True
                    # Fallback for page items without direct id fields.
                    if _playing_track is None:
                        return False
                    item_name = _norm_text(data.get("name"))
                    item_artist = _norm_text(data.get("sub_title"))
                    name_match = bool(
                        _now_name
                        and item_name
                        and (item_name == _now_name or item_name in _now_name or _now_name in item_name)
                    )
                    if not name_match:
                        return False
                    if not _now_artist:
                        return True
                    return bool(
                        item_artist
                        and (item_artist == _now_artist or item_artist in _now_artist or _now_artist in item_artist)
                    )

                is_playing = _is_playing_item(item_data)
                row_box = Gtk.Box(spacing=10, margin_start=6, margin_end=6, margin_top=4, margin_bottom=4)
                row_box.set_hexpand(True)
                rank_classes = ["history-rank-chip"]
                if rank_idx == 0:
                    rank_classes.append("history-rank-top1")
                elif rank_idx == 1:
                    rank_classes.append("history-rank-top2")
                elif rank_idx == 2:
                    rank_classes.append("history-rank-top3")
                rank_label = Gtk.Label(label=f"{rank_idx + 1:02d}", xalign=0.5, css_classes=rank_classes)
                rank_label.set_size_request(24, 24)
                rank_label.set_valign(Gtk.Align.CENTER)
                row_box.append(rank_label)

                img = Gtk.Image(pixel_size=DASHBOARD_TRACK_COVER_SIZE, css_classes=["album-cover-img"])
                cover = item_data.get("image_url")
                if cover:
                    utils.load_img(img, cover, app.cache_dir, DASHBOARD_TRACK_COVER_SIZE)
                else:
                    img.set_from_icon_name("audio-x-generic-symbolic")
                row_box.append(_build_feed_media_overlay(img, DASHBOARD_TRACK_COVER_SIZE, "album-cover-img"))

                text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
                text_box.append(
                    Gtk.Label(
                        label=str(item_data.get("name") or "Unknown Track"),
                        xalign=0,
                        ellipsize=3,
                        max_width_chars=48,
                        css_classes=["home-card-title"],
                    )
                )
                subtitle = str(item_data.get("sub_title") or "")
                if subtitle:
                    text_box.append(
                        Gtk.Label(
                            label=subtitle,
                            xalign=0,
                            ellipsize=3,
                            max_width_chars=56,
                            css_classes=["dim-label", "home-card-subtitle"],
                        )
                    )
                row_box.append(text_box)

                playing_icon = Gtk.Image(icon_name="media-playback-start-symbolic", pixel_size=14)
                playing_icon.set_halign(Gtk.Align.END)
                playing_icon.set_valign(Gtk.Align.CENTER)
                playing_icon.add_css_class("track-row-playing-icon")
                playing_icon.set_visible(is_playing)
                row_box.append(playing_icon)

                btn = Gtk.Button(css_classes=_dashboard_track_row_button_classes(is_playing))
                btn.set_hexpand(True)
                btn.set_halign(Gtk.Align.FILL)
                obj = item_data.get("obj")
                item_id = None
                if obj is not None:
                    item_id = getattr(obj, "id", None) or getattr(obj, "track_id", None)
                    if item_id is None and isinstance(obj, dict):
                        item_id = obj.get("id") or obj.get("track_id")
                btn._dashboard_track_id = str(item_id or "").strip()
                btn._dashboard_track_name = _norm_text(item_data.get("name"))
                btn._dashboard_track_artist = _norm_text(item_data.get("sub_title"))
                btn._dashboard_playing_icon = playing_icon
                btn.set_child(row_box)
                btn.connect("clicked", lambda _b, arr=section_items, idx=src_idx: _play_tracks_section(arr, idx))
                return btn

            def _is_tracks_section(sec):
                title = str(sec.get("title", "") or "")
                title_lc = title.lower()
                return ("track" in title_lc or "song" in title_lc or "单曲" in title or "歌曲" in title or "曲" in title)

            ordered_sections = sorted(
                enumerate(sections),
                key=lambda pair: (0 if _is_tracks_section(pair[1]) else 1, int(pair[0])),
            )

            # Build tab shells immediately (fast), populate content lazily per tab
            _tab_data = {}  # tab_name -> (is_tracks_tab, items, page_box)
            for new_idx, (_orig_idx, sec) in enumerate(ordered_sections):
                page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
                page_box.set_valign(Gtk.Align.START)
                page_box.set_vexpand(False)
                title = str(sec.get("title", "") or f"Top {new_idx + 1}")
                items = list(sec.get("items", []) or [])
                title_lc = title.lower()
                is_tracks_tab = ("track" in title_lc or "song" in title_lc) and items
                tab_name = f"top-sec-{new_idx}"
                _tab_data[tab_name] = (is_tracks_tab, items, page_box)
                top_stack.add_titled(page_box, tab_name, title)

            section_names = [f"top-sec-{i}" for i in range(len(ordered_sections))]
            selected = str(getattr(app, "_top_selected_tab", "") or "")
            initial_tab = selected if selected in section_names else (section_names[0] if section_names else None)
            if initial_tab:
                top_stack.set_visible_child_name(initial_tab)

            _populated_tabs = set()

            def _populate_top_tab(tab_name):
                if tab_name in _populated_tabs or tab_name not in _tab_data:
                    return
                _populated_tabs.add(tab_name)
                is_tracks, tab_items, tab_page_box = _tab_data[tab_name]
                if is_tracks:
                    grid = Gtk.Grid(column_spacing=16, row_spacing=4, hexpand=True)
                    grid.set_column_homogeneous(True)
                    grid.set_halign(Gtk.Align.FILL)
                    tab_page_box.append(grid)
                    total = len(tab_items)
                    left_count = (total + 1) // 2
                    right_count = total - left_count
                    row_state = [0]

                    def _build_top_rows(grid=grid, tab_items=tab_items,
                                        left_count=left_count, right_count=right_count,
                                        row_state=row_state):
                        for _ in range(8):
                            row = row_state[0]
                            if row >= left_count:
                                return False
                            left_idx = row
                            grid.attach(_build_top_track_row(tab_items[left_idx], left_idx, tab_items, left_idx), 0, row, 1, 1)
                            if row < right_count:
                                right_idx = left_count + row
                                grid.attach(_build_top_track_row(tab_items[right_idx], right_idx, tab_items, right_idx), 1, row, 1, 1)
                            row_state[0] += 1
                        return row_state[0] < left_count

                    GLib.idle_add(_build_top_rows)
                else:
                    flow = Gtk.FlowBox(
                        homogeneous=True,
                        min_children_per_line=2,
                        max_children_per_line=16,
                        column_spacing=16,
                        row_spacing=16,
                        selection_mode=Gtk.SelectionMode.NONE,
                    )
                    tab_page_box.append(flow)
                    idx_state = [0]

                    def _build_top_flow(flow=flow, tab_items=tab_items, idx_state=idx_state):
                        for _ in range(8):
                            idx = idx_state[0]
                            if idx >= len(tab_items):
                                return False
                            btn = _build_home_item_button(tab_items[idx])
                            child = Gtk.FlowBoxChild()
                            child.set_child(btn)
                            flow.append(child)
                            idx_state[0] += 1
                        return idx_state[0] < len(tab_items)

                    GLib.idle_add(_build_top_flow)

            def _on_top_tab_changed(stack, _pspec):
                try:
                    name = str(stack.get_visible_child_name() or "")
                except Exception:
                    name = ""
                if name:
                    app._top_selected_tab = name
                    _populate_top_tab(name)

            top_stack.connect("notify::visible-child-name", _on_top_tab_changed)
            app.collection_content_box.append(tabs_box)
            if initial_tab:
                _populate_top_tab(initial_tab)
        else:
            app._top_sections_cache = None
            app.collection_content_box.append(
                Gtk.Label(
                    label="No official Top sections are available for current account/region.",
                    xalign=0,
                    css_classes=["dim-label"],
                    margin_start=8,
                    margin_top=8,
                )
            )

    cached = list(getattr(app, "_top_sections_cache", None) or [])
    cache_age = time.monotonic() - getattr(app, "_top_sections_cache_time", 0)
    cache_is_fresh = bool(cached) and cache_age < 300

    if prefer_cache and cached:
        _render_sections(cached)

    if not cache_is_fresh:
        def task():
            sections = list(app.backend.get_top_page() or [])
            if not sections:
                # Fallback: try Home sections and keep chart/top-like titles.
                fallback = list(app.backend.get_home_page() or [])
                keys = ("top", "chart", "hit", "popular", "trending", "排行", "热门", "チャート", "トップ")
                sections = [s for s in fallback if any(k in str(s.get("title", "")).lower() for k in keys)]

            def apply():
                _render_sections(sections)
                return False

            GLib.idle_add(apply)

        Thread(target=task, daemon=True).start()


def render_new_dashboard(app, prefer_cache=True):
    _clear_container(app.collection_content_box)

    def _render_sections(sections):
        _clear_container(app.collection_content_box)
        if sections:
            app._new_sections_cache = list(sections)
            app._new_sections_cache_time = time.monotonic()
            tabs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            new_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
            new_stack.set_hhomogeneous(False)
            new_stack.set_vhomogeneous(False)
            new_switcher = Gtk.StackSwitcher(stack=new_stack)
            new_switcher.set_halign(Gtk.Align.START)
            tabs_box.append(new_switcher)
            tabs_box.append(new_stack)

            def _open_item(item_data):
                if not item_data:
                    return
                obj = item_data.get("obj")
                typ = item_data.get("type")
                if typ in {"PageItem", "PageLink"} and obj is not None and hasattr(obj, "get") and callable(obj.get):
                    def task():
                        try:
                            resolved = obj.get()
                        except Exception:
                            resolved = None
                        if resolved is None:
                            return

                        def apply():
                            resolved_type = type(resolved).__name__
                            if "Track" in resolved_type:
                                app._play_single_track(resolved)
                            elif "Artist" in resolved_type:
                                app.on_artist_clicked(resolved)
                            elif "Playlist" in resolved_type:
                                app.on_remote_playlist_card_clicked(resolved)
                            else:
                                app.show_album_details(resolved)
                            return False

                        GLib.idle_add(apply)

                    Thread(target=task, daemon=True).start()
                    return
                if typ == "Track":
                    app._play_single_track(obj)
                    return
                if typ == "Artist":
                    app.on_artist_clicked(obj)
                    return
                if "Playlist" in str(typ or ""):
                    app.on_remote_playlist_card_clicked(obj)
                    return
                app.show_album_details(obj)

            def _build_item_button(item_data):
                return _build_feed_item_button(app, item_data, _open_item)

            def _play_tracks_section(items, clicked_src_idx):
                def _resolve_track(item_data):
                    obj = item_data.get("obj")
                    if obj is None:
                        return None
                    try:
                        resolved = obj.get() if hasattr(obj, "get") and callable(obj.get) else obj
                    except Exception:
                        resolved = None
                    if resolved is None:
                        return None
                    if "Track" in str(type(resolved).__name__):
                        return resolved
                    return None

                def task():
                    pairs = []
                    for src_idx, it in enumerate(list(items or [])):
                        t = _resolve_track(it)
                        if t is not None:
                            pairs.append((src_idx, t))

                    if not pairs:
                        clicked = list(items or [])[clicked_src_idx] if 0 <= clicked_src_idx < len(list(items or [])) else None
                        if clicked is not None:
                            GLib.idle_add(lambda: (_open_item(clicked), False)[1])
                        return

                    tracks = [t for _, t in pairs]
                    play_idx = None
                    for i, (src_idx, _t) in enumerate(pairs):
                        if src_idx == clicked_src_idx:
                            play_idx = i
                            break

                    if play_idx is None:
                        clicked = list(items or [])[clicked_src_idx] if 0 <= clicked_src_idx < len(list(items or [])) else None
                        if clicked is not None:
                            GLib.idle_add(lambda: (_open_item(clicked), False)[1])
                        return

                    def apply():
                        app.current_track_list = list(tracks)
                        app._set_play_queue(list(tracks))
                        app.play_track(play_idx)
                        return False

                    GLib.idle_add(apply)

                Thread(target=task, daemon=True).start()

            def _norm_text(v):
                s = str(v or "").strip().lower()
                keep = []
                for ch in s:
                    if ch.isalnum() or ch.isspace():
                        keep.append(ch)
                return " ".join("".join(keep).split())

            # Pre-compute once for all rows — playing_track doesn't change while building
            _playing_track = getattr(app, "playing_track", None)
            _playing_id = str(getattr(app, "playing_track_id", "") or "").strip()
            _now_name = _norm_text(getattr(_playing_track, "name", "")) if _playing_track else ""
            _now_artist = _norm_text(getattr(getattr(_playing_track, "artist", None), "name", "")) if _playing_track else ""

            def _build_new_track_row(item_data, section_items, src_idx):
                def _is_playing_item(data):
                    obj = data.get("obj")
                    item_id = None
                    if obj is not None:
                        item_id = getattr(obj, "id", None) or getattr(obj, "track_id", None)
                        if item_id is None and isinstance(obj, dict):
                            item_id = obj.get("id") or obj.get("track_id")
                    if _playing_id and item_id is not None and str(item_id).strip() == _playing_id:
                        return True
                    # Fallback for page items without direct id fields.
                    if _playing_track is None:
                        return False
                    item_name = _norm_text(data.get("name"))
                    item_artist = _norm_text(data.get("sub_title"))
                    name_match = bool(
                        _now_name
                        and item_name
                        and (item_name == _now_name or item_name in _now_name or _now_name in item_name)
                    )
                    if not name_match:
                        return False
                    if not _now_artist:
                        return True
                    return bool(
                        item_artist
                        and (item_artist == _now_artist or item_artist in _now_artist or _now_artist in item_artist)
                    )

                is_playing = _is_playing_item(item_data)
                row_box = Gtk.Box(spacing=10, margin_start=6, margin_end=6, margin_top=4, margin_bottom=4)
                row_box.set_hexpand(True)

                img = Gtk.Image(pixel_size=DASHBOARD_TRACK_COVER_SIZE, css_classes=["album-cover-img"])
                cover = item_data.get("image_url")
                if cover:
                    utils.load_img(img, cover, app.cache_dir, DASHBOARD_TRACK_COVER_SIZE)
                else:
                    img.set_from_icon_name("audio-x-generic-symbolic")
                row_box.append(_build_feed_media_overlay(img, DASHBOARD_TRACK_COVER_SIZE, "album-cover-img"))

                text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
                text_box.append(
                    Gtk.Label(
                        label=str(item_data.get("name") or "Unknown Track"),
                        xalign=0,
                        ellipsize=3,
                        max_width_chars=48,
                        css_classes=["home-card-title"],
                    )
                )
                subtitle = str(item_data.get("sub_title") or "")
                if subtitle:
                    text_box.append(
                        Gtk.Label(
                            label=subtitle,
                            xalign=0,
                            ellipsize=3,
                            max_width_chars=56,
                            css_classes=["dim-label", "home-card-subtitle"],
                        )
                    )
                row_box.append(text_box)

                playing_icon = Gtk.Image(icon_name="media-playback-start-symbolic", pixel_size=14)
                playing_icon.set_halign(Gtk.Align.END)
                playing_icon.set_valign(Gtk.Align.CENTER)
                playing_icon.add_css_class("track-row-playing-icon")
                playing_icon.set_visible(is_playing)
                row_box.append(playing_icon)

                btn = Gtk.Button(css_classes=_dashboard_track_row_button_classes(is_playing))
                btn.set_hexpand(True)
                btn.set_halign(Gtk.Align.FILL)
                obj = item_data.get("obj")
                item_id = None
                if obj is not None:
                    item_id = getattr(obj, "id", None) or getattr(obj, "track_id", None)
                    if item_id is None and isinstance(obj, dict):
                        item_id = obj.get("id") or obj.get("track_id")
                btn._dashboard_track_id = str(item_id or "").strip()
                btn._dashboard_track_name = _norm_text(item_data.get("name"))
                btn._dashboard_track_artist = _norm_text(item_data.get("sub_title"))
                btn._dashboard_playing_icon = playing_icon
                btn.set_child(row_box)
                btn.connect("clicked", lambda _b, arr=section_items, idx=src_idx: _play_tracks_section(arr, idx))
                return btn

            def _is_tracks_section(sec):
                title = str(sec.get("title", "") or "")
                title_lc = title.lower()
                return ("track" in title_lc or "song" in title_lc or "单曲" in title or "歌曲" in title or "曲" in title)

            ordered_sections = sorted(
                enumerate(sections),
                key=lambda pair: (0 if _is_tracks_section(pair[1]) else 1, int(pair[0])),
            )

            # Build tab shells immediately (fast), populate content lazily per tab
            _new_tab_data = {}  # tab_name -> (is_tracks_tab, items, page_box)
            for idx, (_orig_idx, sec) in enumerate(ordered_sections):
                page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
                page_box.set_valign(Gtk.Align.START)
                page_box.set_vexpand(False)
                title = str(sec.get("title", "") or f"New {idx + 1}")
                items = list(sec.get("items", []) or [])
                title_lc = title.lower()
                is_tracks_tab = ("track" in title_lc or "song" in title_lc or "单曲" in title or "歌曲" in title)
                tab_name = f"new-sec-{idx}"
                _new_tab_data[tab_name] = (is_tracks_tab, items, page_box)
                new_stack.add_titled(page_box, tab_name, title)

            section_names = [f"new-sec-{i}" for i in range(len(ordered_sections))]
            selected = str(getattr(app, "_new_selected_tab", "") or "")
            initial_tab = selected if selected in section_names else (section_names[0] if section_names else None)
            if initial_tab:
                new_stack.set_visible_child_name(initial_tab)

            _new_populated_tabs = set()

            def _populate_new_tab(tab_name):
                if tab_name in _new_populated_tabs or tab_name not in _new_tab_data:
                    return
                _new_populated_tabs.add(tab_name)
                is_tracks, tab_items, tab_page_box = _new_tab_data[tab_name]
                if is_tracks and tab_items:
                    grid = Gtk.Grid(column_spacing=16, row_spacing=4, hexpand=True)
                    grid.set_column_homogeneous(True)
                    grid.set_halign(Gtk.Align.FILL)
                    tab_page_box.append(grid)
                    total = len(tab_items)
                    left_count = (total + 1) // 2
                    right_count = total - left_count
                    row_state = [0]

                    def _build_new_rows(grid=grid, tab_items=tab_items,
                                        left_count=left_count, right_count=right_count,
                                        row_state=row_state):
                        for _ in range(8):
                            row = row_state[0]
                            if row >= left_count:
                                return False
                            left_idx = row
                            grid.attach(_build_new_track_row(tab_items[left_idx], tab_items, left_idx), 0, row, 1, 1)
                            if row < right_count:
                                right_idx = left_count + row
                                grid.attach(_build_new_track_row(tab_items[right_idx], tab_items, right_idx), 1, row, 1, 1)
                            row_state[0] += 1
                        return row_state[0] < left_count

                    GLib.idle_add(_build_new_rows)
                else:
                    flow = Gtk.FlowBox(
                        homogeneous=True,
                        min_children_per_line=2,
                        max_children_per_line=16,
                        column_spacing=16,
                        row_spacing=16,
                        selection_mode=Gtk.SelectionMode.NONE,
                    )
                    tab_page_box.append(flow)
                    idx_state = [0]

                    def _build_new_flow(flow=flow, tab_items=tab_items, idx_state=idx_state):
                        for _ in range(8):
                            idx = idx_state[0]
                            if idx >= len(tab_items):
                                return False
                            btn = _build_item_button(tab_items[idx])
                            child = Gtk.FlowBoxChild()
                            child.set_child(btn)
                            flow.append(child)
                            idx_state[0] += 1
                        return idx_state[0] < len(tab_items)

                    GLib.idle_add(_build_new_flow)

            def _on_new_tab_changed(stack, _pspec):
                try:
                    name = str(stack.get_visible_child_name() or "")
                except Exception:
                    name = ""
                if name:
                    app._new_selected_tab = name
                    _populate_new_tab(name)

            new_stack.connect("notify::visible-child-name", _on_new_tab_changed)
            app.collection_content_box.append(tabs_box)
            if initial_tab:
                _populate_new_tab(initial_tab)
        else:
            app._new_sections_cache = None
            app.collection_content_box.append(
                Gtk.Label(
                    label="No official New sections are available for current account/region.",
                    xalign=0,
                    css_classes=["dim-label"],
                    margin_start=8,
                    margin_top=8,
                )
            )

    cached = list(getattr(app, "_new_sections_cache", None) or [])
    cache_age = time.monotonic() - getattr(app, "_new_sections_cache_time", 0)
    cache_is_fresh = bool(cached) and cache_age < 300

    if prefer_cache and cached:
        _render_sections(cached)

    if not cache_is_fresh:
        def task():
            sections = list(app.backend.get_new_page() or [])
            if not sections:
                fallback = list(app.backend.get_home_page() or [])
                keys = ("new", "latest", "fresh", "新", "最新", "新着", "new music")
                sections = [
                    s for s in fallback
                    if any(k in str(s.get("title", "")).lower() for k in keys)
                    and "video" not in str(s.get("title", "")).lower()
                ]

            GLib.idle_add(lambda: (_render_sections(sections), False)[1])

        Thread(target=task, daemon=True).start()


def render_hires_dashboard(app, prefer_cache=True):
    _clear_container(app.collection_content_box)

    def _render_sections(sections):
        _clear_container(app.collection_content_box)
        visible_sections = _filter_hires_sections(sections)
        if visible_sections:
            app._hires_sections_cache = list(visible_sections)
            app._hires_sections_cache_time = time.monotonic()
            tabs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            hires_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
            hires_stack.set_hhomogeneous(False)
            hires_stack.set_vhomogeneous(False)
            hires_switcher = Gtk.StackSwitcher(stack=hires_stack)
            hires_switcher.set_halign(Gtk.Align.START)
            tabs_box.append(hires_switcher)
            tabs_box.append(hires_stack)

            def _open_item(item_data):
                if not item_data:
                    return
                obj = item_data.get("obj")
                typ = item_data.get("type")
                if typ in {"PageItem", "PageLink"} and obj is not None and hasattr(obj, "get") and callable(obj.get):
                    def task():
                        try:
                            resolved = obj.get()
                        except Exception:
                            resolved = None
                        if resolved is None:
                            return
                        def apply():
                            resolved_type = type(resolved).__name__
                            if "Track" in resolved_type:
                                app._play_single_track(resolved)
                            elif "Artist" in resolved_type:
                                app.on_artist_clicked(resolved)
                            elif "Playlist" in resolved_type:
                                app.on_remote_playlist_card_clicked(resolved)
                            else:
                                app.show_album_details(resolved)
                            return False
                        GLib.idle_add(apply)
                    Thread(target=task, daemon=True).start()
                    return
                if typ == "Track":
                    app._play_single_track(obj)
                    return
                if typ == "Artist":
                    app.on_artist_clicked(obj)
                    return
                if "Playlist" in str(typ or ""):
                    app.on_remote_playlist_card_clicked(obj)
                    return
                app.show_album_details(obj)

            def _build_item_button(item_data):
                return _build_feed_item_button(app, item_data, _open_item)

            _tab_data = {}
            for idx, sec in enumerate(visible_sections):
                page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
                page_box.set_valign(Gtk.Align.START)
                page_box.set_vexpand(False)
                title = str(sec.get("title", "") or f"Hi-Res {idx + 1}")
                items = list(sec.get("items", []) or [])
                tab_name = f"hires-sec-{idx}"
                _tab_data[tab_name] = (items, page_box)
                hires_stack.add_titled(page_box, tab_name, title)

            section_names = list(_tab_data.keys())
            selected = str(getattr(app, "_hires_selected_tab", "") or "")
            initial_tab = selected if selected in section_names else (section_names[0] if section_names else None)
            if initial_tab:
                hires_stack.set_visible_child_name(initial_tab)

            _populated_tabs = set()

            def _populate_hires_tab(tab_name):
                if tab_name in _populated_tabs or tab_name not in _tab_data:
                    return
                _populated_tabs.add(tab_name)
                tab_items, tab_page_box = _tab_data[tab_name]
                flow = Gtk.FlowBox(
                    homogeneous=True,
                    min_children_per_line=2,
                    max_children_per_line=16,
                    column_spacing=16,
                    row_spacing=16,
                    selection_mode=Gtk.SelectionMode.NONE,
                )
                tab_page_box.append(flow)
                idx_state = [0]

                def _build_hires_flow(flow=flow, tab_items=tab_items, idx_state=idx_state):
                    for _ in range(8):
                        idx = idx_state[0]
                        if idx >= len(tab_items):
                            return False
                        btn = _build_item_button(tab_items[idx])
                        child = Gtk.FlowBoxChild()
                        child.set_child(btn)
                        flow.append(child)
                        idx_state[0] += 1
                    return idx_state[0] < len(tab_items)

                GLib.idle_add(_build_hires_flow)

            def _on_hires_tab_changed(stack, _pspec):
                try:
                    name = str(stack.get_visible_child_name() or "")
                except Exception:
                    name = ""
                if name:
                    app._hires_selected_tab = name
                    _populate_hires_tab(name)

            hires_stack.connect("notify::visible-child-name", _on_hires_tab_changed)
            app.collection_content_box.append(tabs_box)
            if initial_tab:
                _populate_hires_tab(initial_tab)
        else:
            app._hires_sections_cache = None
            app.collection_content_box.append(
                Gtk.Label(
                    label="Hi-Res content is not available for your account or region.",
                    xalign=0,
                    css_classes=["dim-label"],
                    margin_start=8,
                    margin_top=8,
                )
            )

    cached = list(getattr(app, "_hires_sections_cache", None) or [])
    cache_age = time.monotonic() - getattr(app, "_hires_sections_cache_time", 0)
    cache_is_fresh = bool(cached) and cache_age < 300

    if prefer_cache and cached:
        _render_sections(cached)

    if not cache_is_fresh:
        def task():
            sections = list(app.backend.get_hires_page() or [])
            GLib.idle_add(lambda: (_render_sections(sections), False)[1])
        Thread(target=task, daemon=True).start()


def render_decades_dashboard(app, prefer_cache=True):
    _clear_container(app.collection_content_box)

    def _open_item(item_data):
        if not item_data:
            return
        obj = item_data.get("obj")
        typ = item_data.get("type")
        if typ in {"PageItem", "PageLink"} and obj is not None and hasattr(obj, "get") and callable(obj.get):
            def task():
                try:
                    resolved = obj.get()
                except Exception:
                    resolved = None
                if resolved is None:
                    return
                def apply():
                    resolved_type = type(resolved).__name__
                    if "Track" in resolved_type:
                        app._play_single_track(resolved)
                    elif "Artist" in resolved_type:
                        app.on_artist_clicked(resolved)
                    elif "Playlist" in resolved_type:
                        app.on_remote_playlist_card_clicked(resolved)
                    else:
                        app.show_album_details(resolved)
                    return False
                GLib.idle_add(apply)
            Thread(target=task, daemon=True).start()
            return
        if typ == "Track":
            app._play_single_track(obj)
            return
        if typ == "Artist":
            app.on_artist_clicked(obj)
            return
        if "Playlist" in str(typ or ""):
            app.on_remote_playlist_card_clicked(obj)
            return
        app.show_album_details(obj)

    def _populate_category(cat_box, items):
        """Progressively append items into a FlowBox inside cat_box."""
        flow = Gtk.FlowBox(
            homogeneous=True,
            min_children_per_line=2,
            max_children_per_line=16,
            column_spacing=16,
            row_spacing=16,
            selection_mode=Gtk.SelectionMode.NONE,
        )
        cat_box.append(flow)
        idx_state = [0]

        def _tick(flow=flow, items=items, idx_state=idx_state):
            for _ in range(8):
                i = idx_state[0]
                if i >= len(items):
                    return False
                btn = _build_feed_item_button(app, items[i], _open_item)
                child = Gtk.FlowBoxChild()
                child.set_child(btn)
                flow.append(child)
                idx_state[0] += 1
            return idx_state[0] < len(items)

        GLib.idle_add(_tick)

    def _build_decade_tab(sec):
        """Build the scrollable content box for one decade tab."""
        tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        tab_box.set_valign(Gtk.Align.START)
        tab_box.set_vexpand(False)
        for cat in list(sec.get("categories", []) or []):
            cat_title = str(cat.get("title", "") or "")
            items = list(cat.get("items", []) or [])
            if not items:
                continue
            # Section header label
            lbl = Gtk.Label(label=cat_title, xalign=0, css_classes=["home-section-title"])
            lbl.set_margin_top(4)
            tab_box.append(lbl)
            cat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            tab_box.append(cat_box)
            _populate_category(cat_box, items)
        return tab_box

    def _build_ui(definitions, tab_cache):
        """Build the full tab structure. definitions = [(label, path), …].
        tab_cache = {label: sec} for already-fetched decades."""
        _clear_container(app.collection_content_box)

        if not definitions:
            app.collection_content_box.append(
                Gtk.Label(
                    label="Decades content is not available for your account or region.",
                    xalign=0,
                    css_classes=["dim-label"],
                    margin_start=8,
                    margin_top=8,
                )
            )
            return

        tabs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        decades_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        decades_stack.set_hhomogeneous(False)
        decades_switcher = Gtk.StackSwitcher(stack=decades_stack)
        decades_switcher.set_halign(Gtk.Align.START)
        tabs_box.append(decades_switcher)
        tabs_box.append(decades_stack)

        # placeholder boxes keyed by label
        _placeholders = {}
        _built_tabs = set()
        _loading_tabs = set()

        for label, _path in definitions:
            placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            _placeholders[label] = placeholder
            decades_stack.add_titled(placeholder, label, label)

        selected = str(getattr(app, "_decades_selected_tab", "") or "")
        labels = [d[0] for d in definitions]
        initial = selected if selected in labels else (labels[0] if labels else None)
        if initial:
            decades_stack.set_visible_child_name(initial)

        def _populate_placeholder(label, sec):
            placeholder = _placeholders.get(label)
            if placeholder is None:
                return
            # Remove loading spinner if present
            child = placeholder.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                placeholder.remove(child)
                child = nxt
            if sec:
                placeholder.append(_build_decade_tab(sec))
            else:
                placeholder.append(Gtk.Label(
                    label="Content not available.",
                    xalign=0, css_classes=["dim-label"],
                    margin_start=8, margin_top=8,
                ))

        def _ensure_tab_loaded(label):
            if label in _built_tabs or label in _loading_tabs:
                return
            # Already in cache?
            sec = tab_cache.get(label)
            if sec is not None:
                _built_tabs.add(label)
                _populate_placeholder(label, sec)
                return
            # Need to fetch — show spinner first
            _loading_tabs.add(label)
            spinner = Gtk.Spinner()
            spinner.set_margin_top(24)
            spinner.set_halign(Gtk.Align.CENTER)
            spinner.start()
            placeholder = _placeholders.get(label)
            if placeholder:
                placeholder.append(spinner)

            path = next((p for l, p in definitions if l == label), None)
            if not path:
                _loading_tabs.discard(label)
                return

            def fetch(label=label, path=path):
                sec = app.backend.get_decade_section(label, path)
                def apply(label=label, sec=sec):
                    tab_cache[label] = sec
                    _loading_tabs.discard(label)
                    _built_tabs.add(label)
                    _populate_placeholder(label, sec)
                    return False
                GLib.idle_add(apply)
            Thread(target=fetch, daemon=True).start()

        def _on_tab_changed(stack, _pspec):
            try:
                name = str(stack.get_visible_child_name() or "")
            except Exception:
                name = ""
            if name:
                app._decades_selected_tab = name
                _ensure_tab_loaded(name)

        decades_stack.connect("notify::visible-child-name", _on_tab_changed)
        app.collection_content_box.append(tabs_box)
        if initial:
            _ensure_tab_loaded(initial)

    # Per-decade cache: {label: sec}, survives across re-renders
    tab_cache = getattr(app, "_decades_tab_cache", None)
    definitions = getattr(app, "_decades_definitions", None)
    cache_time = getattr(app, "_decades_cache_time", 0)
    cache_is_fresh = bool(definitions) and (time.monotonic() - cache_time) < 300

    if prefer_cache and definitions:
        _build_ui(definitions, tab_cache or {})

    if not cache_is_fresh:
        def task():
            defs, eager = app.backend.get_decades_page()
            new_cache = dict(getattr(app, "_decades_tab_cache", None) or {})
            for sec in eager:
                if sec:
                    new_cache[sec["title"]] = sec

            def apply(defs=defs, new_cache=new_cache):
                app._decades_definitions = defs
                app._decades_tab_cache = new_cache
                app._decades_cache_time = time.monotonic()
                _build_ui(defs, new_cache)
                return False
            GLib.idle_add(apply)
        Thread(target=task, daemon=True).start()


def _render_tabbed_page_dashboard(app, cfg, prefer_cache=True):
    _clear_container(app.collection_content_box)

    def _genre_category_visible_count(sample_item=None, widget=None):
        available_width = 0
        try:
            if widget is not None:
                available_width = int(widget.get_width() or 0)
        except Exception:
            available_width = 0

        if available_width <= 0:
            try:
                content_box = getattr(app, "collection_content_box", None)
                if content_box is not None:
                    available_width = int(content_box.get_width() or 0)
            except Exception:
                available_width = 0

        if available_width <= 0:
            try:
                win = getattr(app, "win", None)
                if win is not None:
                    available_width = int(win.get_width() or 0)
            except Exception:
                available_width = 0

        if available_width <= 0:
            try:
                base_width = int(getattr(app, "saved_width", 0) or 0)
            except Exception:
                base_width = 0
            if base_width <= 0:
                base_width = int(getattr(ui_config, "WINDOW_WIDTH", 1250) or 1250)
            sidebar_width = max(int(base_width * float(getattr(ui_config, "SIDEBAR_RATIO", 0.15))), 120)
            available_width = max(320, base_width - sidebar_width - 64)

        layout = _home_card_layout(sample_item or {}, utils.COVER_SIZE)
        # Feed cards add 8 px horizontal padding on each side via the shared
        # `.card` class, so visible columns must be computed from the outer slot
        # width rather than the media width alone. This is especially important
        # for Track cards, whose media is only 88 px wide.
        item_width = max(88, int(layout.get("card_width", getattr(utils, "COVER_SIZE", 170) or 170)) + 16)
        gap = 16
        columns = max(1, min(16, int((available_width + gap) // (item_width + gap)) or 1))
        return max(1, columns * 2)

    def _open_item(item_data):
        if not item_data:
            return
        obj = item_data.get("obj")
        typ = item_data.get("type")
        if typ in {"PageItem", "PageLink"} and obj is not None and hasattr(obj, "get") and callable(obj.get):
            def task():
                try:
                    resolved = obj.get()
                except Exception:
                    resolved = None
                if resolved is None:
                    return
                def apply():
                    resolved_type = type(resolved).__name__
                    if "Track" in resolved_type:
                        app._play_single_track(resolved)
                    elif "Artist" in resolved_type:
                        app.on_artist_clicked(resolved)
                    elif "Playlist" in resolved_type:
                        app.on_remote_playlist_card_clicked(resolved)
                    else:
                        app.show_album_details(resolved)
                    return False
                GLib.idle_add(apply)
            Thread(target=task, daemon=True).start()
            return
        if typ == "Track":
            app._play_single_track(obj)
            return
        if typ == "Artist":
            app.on_artist_clicked(obj)
            return
        if "Playlist" in str(typ or ""):
            app.on_remote_playlist_card_clicked(obj)
            return
        app.show_album_details(obj)

    def _populate_category(cat_box, items, more_path=None):
        flow = Gtk.FlowBox(
            homogeneous=True,
            min_children_per_line=2,
            max_children_per_line=16,
            column_spacing=16,
            row_spacing=16,
            selection_mode=Gtk.SelectionMode.NONE,
        )
        cat_box.append(flow)
        idx_state = [0]
        resolved_chunk_size = [0]
        more_row = None

        def _append_items(limit, flow=flow, items=items, idx_state=idx_state):
            appended = 0
            while appended < limit:
                i = idx_state[0]
                if i >= len(items):
                    break
                btn = _build_feed_item_button(app, items[i], _open_item)
                child = Gtk.FlowBoxChild()
                child.set_child(btn)
                flow.append(child)
                idx_state[0] += 1
                appended += 1

        def _measured_chunk_size(flow=flow, items=items):
            gap = 16
            flow_width = 0
            try:
                flow_width = int(flow.get_allocated_width() or 0)
            except Exception:
                flow_width = 0
            if flow_width <= 0:
                try:
                    flow_width = int(flow.get_width() or 0)
                except Exception:
                    flow_width = 0

            first_child = flow.get_first_child() if hasattr(flow, "get_first_child") else None
            first_widget = None
            if first_child is not None:
                if hasattr(first_child, "get_first_child"):
                    try:
                        first_widget = first_child.get_first_child()
                    except Exception:
                        first_widget = None
                if first_widget is None:
                    first_widget = getattr(first_child, "child", None)

            child_width = 0
            if first_widget is not None:
                try:
                    child_width = int(first_widget.get_allocated_width() or 0)
                except Exception:
                    child_width = 0
                if child_width <= 0:
                    try:
                        child_width = int(first_widget.get_width() or 0)
                    except Exception:
                        child_width = 0

            if flow_width > 0 and child_width > 0:
                columns = max(1, min(16, int((flow_width + gap) // (child_width + gap)) or 1))
                return max(1, columns * 2)

            return _genre_category_visible_count(
                items[0] if items else None,
                flow,
            )

        def _rendered_two_row_capacity(flow=flow):
            children = []
            child = flow.get_first_child() if hasattr(flow, "get_first_child") else None
            while child is not None:
                children.append(child)
                if not hasattr(child, "get_next_sibling"):
                    return 0
                child = child.get_next_sibling() if hasattr(child, "get_next_sibling") else None

            if not children:
                return 0

            row_positions = []
            count = 0
            for child in children:
                try:
                    alloc = child.get_allocation()
                except Exception:
                    alloc = None
                y = int(getattr(alloc, "y", 0) or 0)
                height = int(getattr(alloc, "height", 0) or 0)
                if height <= 0:
                    try:
                        height = int(child.get_allocated_height() or 0)
                    except Exception:
                        height = 0
                tolerance = max(4, int(height // 4) if height > 0 else 4)

                matched = False
                for row_y in row_positions:
                    if abs(y - row_y) <= tolerance:
                        matched = True
                        break
                if not matched:
                    row_positions.append(y)
                    if len(row_positions) > 2:
                        break
                count += 1
            return count if count > 0 else 0

        more_exhausted = [False]
        more_loading = [False]
        more_auto_fill_ran = [False]

        def _dedup_new_items(new_items):
            """Filter new_items to exclude anything already present in items."""
            seen = set()
            for it in items:
                obj = it.get("obj")
                item_id = getattr(obj, "id", None) if obj is not None else None
                typ = str(it.get("type") or "")
                if item_id:
                    seen.add((typ, str(item_id).strip()))
                else:
                    seen.add((typ, str(it.get("name") or "").lower(),
                              str(it.get("sub_title") or "").lower()))
            result = []
            for it in new_items:
                obj = it.get("obj")
                item_id = getattr(obj, "id", None) if obj is not None else None
                typ = str(it.get("type") or "")
                key = (typ, str(item_id).strip()) if item_id else (
                    typ, str(it.get("name") or "").lower(),
                    str(it.get("sub_title") or "").lower()
                )
                if key not in seen:
                    seen.add(key)
                    result.append(it)
            return result

        def _sync_more_row():
            if more_row is not None:
                has_more = idx_state[0] < len(items) or (
                    bool(more_path) and not more_exhausted[0]
                )
                more_row.set_visible(has_more)

        def _append_chunk(flow=flow, items=items, idx_state=idx_state):
            chunk_size = resolved_chunk_size[0] or _measured_chunk_size()
            _append_items(chunk_size)
            _sync_more_row()
            return False

        def _finalize_initial_layout(flow=flow, items=items, idx_state=idx_state):
            chunk_size = _rendered_two_row_capacity() or _measured_chunk_size()
            resolved_chunk_size[0] = chunk_size
            rendered = idx_state[0]
            if rendered > chunk_size:
                _clear_container(flow)
                idx_state[0] = 0
                _append_items(chunk_size)
            elif rendered < chunk_size:
                _append_items(chunk_size - rendered)
            _sync_more_row()
            # If the initial items from the main page aren't enough to fill 2
            # rows (common for Track categories which only return ~5 items
            # upfront), silently auto-fetch the _more link so the grid looks
            # full without requiring the user to click "Show More".
            if (idx_state[0] >= len(items) and more_path
                    and not more_exhausted[0] and not more_loading[0]
                    and not more_auto_fill_ran[0]):
                _auto_fill_rows()
            return False

        def _auto_fill_rows():
            """Transparently fetch _more items to fill up to the 2-row capacity.
            Only called once per category (guarded by more_auto_fill_ran).

            _rendered_two_row_capacity() may under-report when fewer items than
            one full row are available (all items land in row 1, so it counts
            them as the "2-row capacity").  Use _measured_chunk_size() here
            which derives the column count from the FlowBox width and is
            reliable regardless of how many rows are actually rendered.
            """
            more_loading[0] = True
            more_auto_fill_ran[0] = True

            def fetch():
                new_items = app.backend.fetch_genre_more(more_path)

                def apply(new_items=new_items):
                    more_loading[0] = False
                    deduped = _dedup_new_items(new_items)
                    if deduped:
                        items.extend(deduped)
                        # Probe-append up to 48 items so the FlowBox has enough
                        # children to render multiple real rows.  Then delegate to
                        # _finalize_initial_layout which calls
                        # _rendered_two_row_capacity() on the live layout to get
                        # the exact 2-row capacity and trims the FlowBox to it.
                        # This sidesteps all width-estimation issues: homogeneous
                        # FlowBox with few items stretches children to fill the
                        # row, making card-width-based column math unreliable.
                        probe = min(len(items) - idx_state[0], 48)
                        if probe > 0:
                            _append_items(probe)
                        GLib.idle_add(_finalize_initial_layout)
                    else:
                        more_exhausted[0] = True
                        _sync_more_row()
                    return False

                GLib.idle_add(apply)

            Thread(target=fetch, daemon=True).start()

        if len(items) > 2:
            more_row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                hexpand=True,
                css_classes=["genres-show-more-row"],
            )
            more_row.set_halign(Gtk.Align.FILL)
            more_row.set_visible(False)
            more_row.append(Gtk.Box(hexpand=True))
            more_btn = Gtk.Button(label="Show More", css_classes=["flat", "genres-show-more-btn"])
            more_btn.set_halign(Gtk.Align.END)

            def _on_show_more(_btn, btn=more_btn):
                if idx_state[0] < len(items):
                    GLib.idle_add(_append_chunk)
                    return
                # Local items exhausted — fetch from server _more link if available.
                if not more_path or more_exhausted[0] or more_loading[0]:
                    return
                more_loading[0] = True
                btn.set_sensitive(False)

                def _fetch_more(btn=btn):
                    new_items = app.backend.fetch_genre_more(more_path)

                    def _apply(new_items=new_items, btn=btn):
                        more_loading[0] = False
                        btn.set_sensitive(True)
                        deduped = _dedup_new_items(new_items)
                        if deduped:
                            items.extend(deduped)
                            GLib.idle_add(_append_chunk)
                        else:
                            more_exhausted[0] = True
                        _sync_more_row()
                        return False

                    GLib.idle_add(_apply)

                Thread(target=_fetch_more, daemon=True).start()

            more_btn.connect("clicked", _on_show_more)
            more_row.append(more_btn)
            cat_box.append(more_row)

        # Let FlowBox lay out a representative sample first, then clamp the
        # initial visible range to the real two-row capacity for this distro/theme.
        # FlowBox caps at 16 children per line here, so 48 items guarantees
        # we probe at least 3 full rows even for tiny Track cards.
        _append_items(min(len(items), 48))
        GLib.idle_add(_finalize_initial_layout)

    def _build_genre_tab(sec):
        tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        tab_box.set_valign(Gtk.Align.START)
        tab_box.set_vexpand(False)
        for cat in list(sec.get("categories", []) or []):
            cat_title = str(cat.get("title", "") or "")
            items = list(cat.get("items", []) or [])
            if not items:
                continue
            more_path = cat.get("more_path")
            lbl = Gtk.Label(label=cat_title, xalign=0, css_classes=["home-section-title"])
            lbl.set_margin_top(4)
            tab_box.append(lbl)
            cat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            tab_box.append(cat_box)
            _populate_category(cat_box, items, more_path=more_path)
        return tab_box

    def _build_ui(definitions, tab_cache):
        _clear_container(app.collection_content_box)

        if not definitions:
            app.collection_content_box.append(
                Gtk.Label(
                    label=cfg.get("empty_msg", "Content is not available for your account or region."),
                    xalign=0,
                    css_classes=["dim-label"],
                    margin_start=8,
                    margin_top=8,
                )
            )
            return

        tabs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        tabs_box.set_valign(Gtk.Align.START)
        tabs_box.set_vexpand(False)
        genres_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        genres_stack.set_hhomogeneous(False)
        genres_stack.set_vhomogeneous(False)
        genres_stack.set_valign(Gtk.Align.START)
        genres_stack.set_vexpand(False)
        genres_switcher = Gtk.StackSwitcher(stack=genres_stack)
        genres_switcher.set_halign(Gtk.Align.START)

        genres_tabs_prev_btn = Gtk.Button(
            icon_name="go-previous-symbolic",
            css_classes=["flat", "circular", "liked-artist-scroll-btn"],
            valign=Gtk.Align.CENTER,
        )
        genres_tabs_prev_btn.set_tooltip_text("Scroll genres left")
        genres_tabs_next_btn = Gtk.Button(
            icon_name="go-next-symbolic",
            css_classes=["flat", "circular", "liked-artist-scroll-btn"],
            valign=Gtk.Align.CENTER,
        )
        genres_tabs_next_btn.set_tooltip_text("Scroll genres right")

        switcher_scroller = Gtk.ScrolledWindow(
            hexpand=True,
            vexpand=False,
            css_classes=["genres-tabs-scroll"],
        )
        switcher_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        if hasattr(switcher_scroller, "set_overlay_scrolling"):
            switcher_scroller.set_overlay_scrolling(True)
        if hasattr(switcher_scroller, "set_propagate_natural_height"):
            switcher_scroller.set_propagate_natural_height(True)
        switcher_scroller.set_child(genres_switcher)
        try:
            h_scrollbar = switcher_scroller.get_hscrollbar()
        except Exception:
            h_scrollbar = None
        if h_scrollbar is not None and hasattr(h_scrollbar, "set_visible"):
            h_scrollbar.set_visible(False)

        genres_tabs_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        genres_tabs_row.append(genres_tabs_prev_btn)
        genres_tabs_row.append(switcher_scroller)
        genres_tabs_row.append(genres_tabs_next_btn)

        tabs_box.append(genres_tabs_row)
        tabs_box.append(genres_stack)

        _bind_horizontal_scroll_buttons(switcher_scroller, genres_tabs_prev_btn, genres_tabs_next_btn)

        def _scroll_genres_tabs(direction):
            h_adj = switcher_scroller.get_hadjustment()
            if h_adj is None:
                return
            step = max(120.0, float(h_adj.get_page_size() or 0.0) * 0.75)
            lower = float(h_adj.get_lower() or 0.0)
            upper = float(h_adj.get_upper() or 0.0)
            page = float(h_adj.get_page_size() or 0.0)
            max_value = max(lower, upper - page)
            cur = float(h_adj.get_value() or 0.0)
            target = cur + (step * direction)
            h_adj.set_value(max(lower, min(max_value, target)))

        genres_tabs_prev_btn.connect("clicked", lambda _b: _scroll_genres_tabs(-1))
        genres_tabs_next_btn.connect("clicked", lambda _b: _scroll_genres_tabs(1))

        _placeholders = {}
        _built_tabs = set()
        _loading_tabs = set()

        for label, _path in definitions:
            placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            placeholder.set_valign(Gtk.Align.START)
            placeholder.set_vexpand(False)
            _placeholders[label] = placeholder
            genres_stack.add_titled(placeholder, label, label)

        selected = str(getattr(app, cfg["selected_tab_attr"], "") or "")
        labels = [d[0] for d in definitions]
        initial = selected if selected in labels else (labels[0] if labels else None)
        if initial:
            genres_stack.set_visible_child_name(initial)

        def _populate_placeholder(label, sec):
            placeholder = _placeholders.get(label)
            if placeholder is None:
                return
            _clear_container(placeholder)
            if sec:
                placeholder.append(_build_genre_tab(sec))
            else:
                placeholder.append(
                    Gtk.Label(
                        label="Content not available.",
                        xalign=0,
                        css_classes=["dim-label"],
                        margin_start=8,
                        margin_top=8,
                    )
                )

        def _prefetch_tab(label):
            """Silently pre-load a tab into tab_cache without rendering."""
            if label in tab_cache or label in _loading_tabs or label in _built_tabs:
                return
            path = next((p for l, p in definitions if l == label), None)
            if not path:
                return
            _loading_tabs.add(label)

            def fetch(label=label, path=path):
                sec = app.backend.get_genre_section(label, path)

                def cache(label=label, sec=sec):
                    tab_cache[label] = sec
                    _loading_tabs.discard(label)
                    return False

                GLib.idle_add(cache)

            Thread(target=fetch, daemon=True).start()

        def _ensure_tab_loaded(label):
            if label in _built_tabs or label in _loading_tabs:
                return
            sec = tab_cache.get(label)
            if sec is not None:
                _built_tabs.add(label)
                _populate_placeholder(label, sec)
                # Cache hit — schedule prefetch of the next two tabs.
                labels = [d[0] for d in definitions]
                try:
                    idx = labels.index(label)
                    for next_label in labels[idx + 1:idx + 3]:
                        GLib.idle_add(lambda lbl=next_label: _prefetch_tab(lbl) or False)
                except ValueError:
                    pass
                return

            _loading_tabs.add(label)
            spinner = Gtk.Spinner()
            spinner.set_margin_top(24)
            spinner.set_halign(Gtk.Align.CENTER)
            spinner.start()
            placeholder = _placeholders.get(label)
            if placeholder:
                placeholder.append(spinner)

            path = next((p for l, p in definitions if l == label), None)
            if not path:
                _loading_tabs.discard(label)
                return

            def fetch(label=label, path=path):
                sec = app.backend.get_genre_section(label, path)

                def apply(label=label, sec=sec):
                    tab_cache[label] = sec
                    _loading_tabs.discard(label)
                    _built_tabs.add(label)
                    _populate_placeholder(label, sec)
                    # After rendering, prefetch the next two tabs in the background.
                    labels = [d[0] for d in definitions]
                    try:
                        idx = labels.index(label)
                        for next_label in labels[idx + 1:idx + 3]:
                            GLib.idle_add(lambda lbl=next_label: _prefetch_tab(lbl) or False)
                    except ValueError:
                        pass
                    return False

                GLib.idle_add(apply)

            Thread(target=fetch, daemon=True).start()

        def _on_tab_changed(stack, _pspec):
            try:
                name = str(stack.get_visible_child_name() or "")
            except Exception:
                name = ""
            if name:
                setattr(app, cfg["selected_tab_attr"], name)
                _ensure_tab_loaded(name)

        genres_stack.connect("notify::visible-child-name", _on_tab_changed)
        app.collection_content_box.append(tabs_box)
        if initial:
            _ensure_tab_loaded(initial)

    tab_cache = getattr(app, cfg["tab_cache_attr"], None)
    if not isinstance(tab_cache, dict):
        tab_cache = {}
        setattr(app, cfg["tab_cache_attr"], tab_cache)
    definitions = getattr(app, cfg["defs_attr"], None)
    cache_time = getattr(app, cfg["cache_time_attr"], 0)
    cache_is_fresh = bool(definitions) and (time.monotonic() - cache_time) < 300

    if prefer_cache and definitions:
        _build_ui(definitions, tab_cache)

    if not cache_is_fresh:
        def task():
            defs, eager = cfg["get_page_fn"]()
            new_cache = dict(tab_cache)
            for sec in eager:
                if sec:
                    new_cache[sec["title"]] = sec

            def apply(defs=defs, new_cache=new_cache):
                setattr(app, cfg["defs_attr"], defs)
                setattr(app, cfg["tab_cache_attr"], new_cache)
                setattr(app, cfg["cache_time_attr"], time.monotonic())
                _build_ui(defs, new_cache)
                return False
            GLib.idle_add(apply)
        Thread(target=task, daemon=True).start()


def render_genres_dashboard(app, prefer_cache=True):
    _render_tabbed_page_dashboard(app, {
        "get_page_fn": app.backend.get_genres_page,
        "defs_attr": "_genres_definitions",
        "tab_cache_attr": "_genres_tab_cache",
        "cache_time_attr": "_genres_cache_time",
        "selected_tab_attr": "_genres_selected_tab",
        "empty_msg": "Genres content is not available for your account or region.",
    }, prefer_cache=prefer_cache)


def render_moods_dashboard(app, prefer_cache=True):
    _render_tabbed_page_dashboard(app, {
        "get_page_fn": app.backend.get_moods_page,
        "defs_attr": "_moods_definitions",
        "tab_cache_attr": "_moods_tab_cache",
        "cache_time_attr": "_moods_cache_time",
        "selected_tab_attr": "_moods_selected_tab",
        "empty_msg": "Moods & Activities content is not available for your account or region.",
    }, prefer_cache=prefer_cache)


def refresh_dashboard_playing_state(app):
    def _norm_text(v):
        s = str(v or "").strip().lower()
        keep = []
        for ch in s:
            if ch.isalnum() or ch.isspace():
                keep.append(ch)
        return " ".join("".join(keep).split())

    def _iter_widgets(root):
        if root is None:
            return
        stack = [root]
        while stack:
            w = stack.pop()
            yield w
            if not hasattr(w, "get_first_child"):
                continue
            child = w.get_first_child()
            while child is not None:
                stack.append(child)
                child = child.get_next_sibling() if hasattr(child, "get_next_sibling") else None

    playing_id = str(getattr(app, "playing_track_id", "") or "").strip()
    track = getattr(app, "playing_track", None)
    now_name = _norm_text(getattr(track, "name", ""))
    now_artist = _norm_text(getattr(getattr(track, "artist", None), "name", ""))

    root = getattr(app, "collection_content_box", None)
    for w in _iter_widgets(root):
        row_name = getattr(w, "_dashboard_track_name", None)
        if row_name is None:
            continue

        row_id = str(getattr(w, "_dashboard_track_id", "") or "").strip()
        row_artist = str(getattr(w, "_dashboard_track_artist", "") or "")
        is_playing = False
        if playing_id and row_id and row_id == playing_id:
            is_playing = True
        else:
            name_match = bool(
                now_name
                and row_name
                and (row_name == now_name or row_name in now_name or now_name in row_name)
            )
            if name_match:
                if not now_artist:
                    is_playing = True
                else:
                    is_playing = bool(
                        row_artist
                        and (row_artist == now_artist or row_artist in now_artist or now_artist in row_artist)
                    )

        if is_playing:
            w.add_css_class("track-row-playing")
        else:
            w.remove_css_class("track-row-playing")
        icon = getattr(w, "_dashboard_playing_icon", None)
        if icon is not None:
            icon.set_visible(is_playing)


def render_collection_dashboard(app, favorite_tracks=None, favorite_albums=None):
    _clear_container(app.collection_content_box)
    app.playlist_track_list = None
    app.queue_track_list = None

    # Store all albums for pagination and search
    app._all_albums = list(favorite_albums or [])
    app._filtered_albums = list(app._all_albums)
    app._albums_page = 0
    app._albums_page_size = 50

    def _get_paginated_albums(page):
        start = page * app._albums_page_size
        end = start + app._albums_page_size
        return app._filtered_albums[start:end]

    def _get_total_pages():
        return (len(app._filtered_albums) + app._albums_page_size - 1) // app._albums_page_size

    def _build_paged_grid_section():
        """Build a paged grid section using FlowBox with pagination and search."""
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section", "history-section"])

        # Search bar with sort and pagination
        search_box = Gtk.Box(spacing=8, margin_start=0, margin_end=0, margin_top=6, margin_bottom=8, css_classes=["search-bar"])
        search_entry = Gtk.Entry(placeholder_text="Search albums...", css_classes=["search-entry"])
        search_entry.set_hexpand(True)
        search_box.append(search_entry)

        # Sort dropdown
        sort_model = Gtk.StringList()
        sort_model.append("Recently Added")
        sort_model.append("Album Name (A-Z)")
        sort_model.append("Album Name (Z-A)")
        sort_model.append("Artist Name (A-Z)")
        sort_model.append("Artist Name (Z-A)")
        sort_dropdown = Gtk.DropDown(model=sort_model, css_classes=["sort-dropdown"])
        sort_dropdown.set_tooltip_text("Sort albums")
        sort_dropdown.set_size_request(150, -1)
        search_box.append(sort_dropdown)

        # Pagination controls
        prev_btn = Gtk.Button(label="Prev", css_classes=["flat", "liked-action-btn"])
        prev_btn.set_tooltip_text("Previous page")
        search_box.append(prev_btn)

        next_btn = Gtk.Button(label="Next", css_classes=["flat", "liked-action-btn"])
        next_btn.set_tooltip_text("Next page")
        search_box.append(next_btn)

        section.append(search_box)

        # FlowBox grid
        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True, css_classes=["history-row-scroller"])
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        flow = Gtk.FlowBox(
            homogeneous=True,
            min_children_per_line=4,
            max_children_per_line=10,
            column_spacing=16,
            row_spacing=16,
            selection_mode=Gtk.SelectionMode.NONE,
        )
        scroller.set_child(flow)
        section.append(scroller)

        return section, flow, prev_btn, next_btn, search_entry, sort_dropdown

    def _render_album_page(flow, albums_page):
        """Render albums for a specific page."""
        _clear_container(flow)
        for alb in albums_page:
            flow.append(_build_my_albums_style_button(app, alb, app.on_history_album_clicked))

    def _update_pagination():
        """Update pagination UI and re-render current page."""
        total = _get_total_pages()
        prev_btn.set_sensitive(app._albums_page > 0)
        next_btn.set_sensitive(app._albums_page < total - 1)
        page_albums = _get_paginated_albums(app._albums_page)
        _render_album_page(flow_albums, page_albums)

    def _on_prev_clicked(_btn):
        if app._albums_page > 0:
            app._albums_page -= 1
            _update_pagination()

    def _on_next_clicked(_btn):
        if app._albums_page < _get_total_pages() - 1:
            app._albums_page += 1
            _update_pagination()

    def _on_search_changed(entry):
        """Handle search input."""
        query = entry.get_text().strip().lower()
        if not query:
            app._filtered_albums = list(app._all_albums)
        else:
            app._filtered_albums = [
                alb for alb in app._all_albums
                if query in getattr(alb, "name", "").lower()
                or query in getattr(getattr(alb, "artist", None), "name", "").lower()
            ]
        app._albums_page = 0
        _apply_sort()
        _update_pagination()

    def _on_sort_changed(dropdown, _pspec):
        """Handle sort option change."""
        _apply_sort()
        app._albums_page = 0
        _update_pagination()

    def _apply_sort():
        """Apply current sort option to filtered albums."""
        sort_idx = sort_dropdown.get_selected()
        if sort_idx == 0:  # Recently Added
            app._filtered_albums.sort(
                key=lambda a: getattr(a, "user_date_added", None) or datetime.min,
                reverse=True,
            )
        elif sort_idx == 1:  # Album Name (A-Z)
            app._filtered_albums.sort(key=lambda a: getattr(a, "name", "").lower())
        elif sort_idx == 2:  # Album Name (Z-A)
            app._filtered_albums.sort(key=lambda a: getattr(a, "name", "").lower(), reverse=True)
        elif sort_idx == 3:  # Artist Name (A-Z)
            app._filtered_albums.sort(key=lambda a: getattr(getattr(a, "artist", None), "name", "").lower())
        elif sort_idx == 4:  # Artist Name (Z-A)
            app._filtered_albums.sort(key=lambda a: getattr(getattr(a, "artist", None), "name", "").lower(), reverse=True)

    # Build the section
    sec_albums, flow_albums, prev_btn, next_btn, search_entry, sort_dropdown = _build_paged_grid_section()
    prev_btn.connect("clicked", _on_prev_clicked)
    next_btn.connect("clicked", _on_next_clicked)
    search_entry.connect("changed", _on_search_changed)
    sort_dropdown.connect("notify::selected", _on_sort_changed)

    # Initial render
    _apply_sort()
    _update_pagination()
    app.collection_content_box.append(sec_albums)


def render_queue_dashboard(app):
    _clear_container(app.collection_content_box)
    app.playlist_track_list = None
    app.queue_track_list = None

    tracks = app._get_active_queue() if hasattr(app, "_get_active_queue") else list(getattr(app, "current_track_list", []) or [])
    current_idx = int(getattr(app, "current_track_index", -1) or -1)

    head = Gtk.Box(spacing=8, css_classes=["home-section-head"], margin_start=6, margin_end=6, margin_bottom=8)
    head.append(Gtk.Label(label="Now Playing Queue", xalign=0, hexpand=True, css_classes=["home-section-title"]))
    head.append(Gtk.Label(label=f"{len(tracks)} tracks", css_classes=["home-section-count"]))
    clear_btn = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat", "playlist-tool-btn"])
    clear_btn.set_tooltip_text("Clear Queue")
    clear_btn.set_sensitive(bool(tracks))
    clear_btn.connect("clicked", app.on_queue_clear_clicked)
    head.append(clear_btn)
    app.collection_content_box.append(head)

    if not tracks:
        hint = Gtk.Label(
            label="Queue is empty. Play an album/playlist/track to build a queue.",
            xalign=0,
            css_classes=["dim-label"],
            margin_start=8,
            margin_top=8,
        )
        app.collection_content_box.append(hint)
        return

    table_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    app.collection_content_box.append(table_box)

    tracks_head, _head_btns = build_tracks_header(
        on_sort_title=lambda _b: None,
        on_sort_artist=lambda _b: None,
        on_sort_album=lambda _b: None,
        on_sort_time=lambda _b: None,
    )
    append_header_action_spacers(tracks_head, ["fav", "remove"])
    table_box.append(tracks_head)

    list_box = Gtk.ListBox(css_classes=["tracks-list"], margin_start=0, margin_end=0, margin_bottom=32)
    list_box.queue_tracks = tracks
    list_box.connect("row-activated", app.on_queue_track_selected)
    app.queue_track_list = list_box
    table_box.append(list_box)

    _populate_queue_rows(app, list_box, tracks, current_idx, compact=False)

    if hasattr(app, "_update_track_list_icon"):
        app._update_track_list_icon(target_list=list_box)


def render_liked_songs_dashboard(app, tracks=None):
    all_tracks = list(tracks or [])
    n = len(all_tracks)
    curr_sig = _liked_tracks_signature(all_tracks)

    # Fast path: track list identical — skip full widget rebuild, only re-apply filters.
    prev_sig = getattr(app, "_liked_tracks_view_sig", None)
    apply_fn = getattr(app, "_liked_tracks_apply_fn", None)
    if (prev_sig is not None and prev_sig == curr_sig
            and apply_fn is not None
            and getattr(app, "liked_track_list", None) is not None):
        logger.info("Liked songs dashboard: data unchanged (sig=%s), skipping full rebuild", curr_sig)
        app.liked_tracks_data = all_tracks
        if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
            app.grid_subtitle_label.set_text(f"{n} Liked Songs")
        apply_fn()
        return

    logger.info("Liked songs dashboard opened: tracks=%s", n)
    _clear_container(app.collection_content_box)
    app.playlist_track_list = None
    app.queue_track_list = None
    app._liked_tracks_view_sig = None  # clear until full build completes
    app._liked_tracks_apply_fn = None

    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_text(f"{n} Liked Songs")
    app.liked_tracks_data = all_tracks
    app.liked_tracks_sort = getattr(app, "liked_tracks_sort", "recent")
    app.liked_tracks_query = getattr(app, "liked_tracks_query", "")
    app.liked_tracks_artist_filter = getattr(app, "liked_tracks_artist_filter", None)
    app.liked_tracks_page_size = max(1, int(getattr(app, "liked_tracks_page_size", 50) or 50))
    app.liked_tracks_page = max(0, int(getattr(app, "liked_tracks_page", 0) or 0))

    toolbar = Gtk.Box(spacing=8, margin_start=0, margin_end=0, margin_top=6, margin_bottom=8)
    search_entry = Gtk.Entry(hexpand=True)
    search_entry.set_placeholder_text("Search in liked songs")
    search_entry.set_text(app.liked_tracks_query or "")
    toolbar.append(search_entry)
    sort_label = Gtk.Label(label="Sort by", css_classes=["dim-label"], valign=Gtk.Align.CENTER)
    toolbar.append(sort_label)
    sort_dd = Gtk.DropDown(model=Gtk.StringList.new(["Recent", "Title", "Artist", "Album", "Duration"]))
    sort_map = {"recent": 0, "title": 1, "artist": 2, "album": 3, "duration": 4}
    sort_dd.set_selected(sort_map.get(app.liked_tracks_sort, 0))
    toolbar.append(sort_dd)
    play_all_btn = Gtk.Button(label="Play all", css_classes=["flat", "liked-action-btn", "liked-action-btn-primary"])
    play_all_btn.set_tooltip_text("Play all liked songs in current view")
    toolbar.append(play_all_btn)
    shuffle_btn = Gtk.Button(label="Shuffle", css_classes=["flat", "liked-action-btn"])
    shuffle_btn.set_tooltip_text("Shuffle current liked songs and play")
    toolbar.append(shuffle_btn)
    prev_page_btn = Gtk.Button(label="Prev", css_classes=["flat", "liked-action-btn"])
    next_page_btn = Gtk.Button(label="Next", css_classes=["flat", "liked-action-btn"])
    prev_page_btn.set_tooltip_text("Previous page")
    next_page_btn.set_tooltip_text("Next page")
    toolbar.append(prev_page_btn)
    toolbar.append(next_page_btn)
    app.collection_content_box.append(toolbar)

    artist_scroll_prev_btn = Gtk.Button(
        icon_name="go-previous-symbolic",
        css_classes=["flat", "circular", "liked-artist-scroll-btn"],
        valign=Gtk.Align.CENTER,
    )
    artist_scroll_prev_btn.set_tooltip_text("Scroll artists left")
    artist_scroll_next_btn = Gtk.Button(
        icon_name="go-next-symbolic",
        css_classes=["flat", "circular", "liked-artist-scroll-btn"],
        valign=Gtk.Align.CENTER,
    )
    artist_scroll_next_btn.set_tooltip_text("Scroll artists right")

    def _artist_key_and_u64(artist_obj):
        aid = getattr(artist_obj, "id", None)
        if aid is not None:
            try:
                aid_int = int(aid)
                key = f"id:{aid_int}"
                # Keep id-keys in high bit space to avoid name-hash collisions.
                return key, ((1 << 63) | (aid_int & ((1 << 63) - 1)))
            except Exception:
                pass
        name = str(getattr(artist_obj, "name", "Unknown") or "Unknown").strip().lower()
        key = f"name:{name}"
        return key, (_stable_u64_from_text(key) & ((1 << 63) - 1))

    artist_meta = {}
    artist_key_strs = []
    artist_key_u64 = []
    title_lc = []
    artist_lc = []
    album_lc = []
    durations = []
    key_to_u64 = {}
    u64_to_key = {}
    key_collision = False
    for t in all_tracks:
        artist_obj = getattr(t, "artist", None)
        key_str, key_u64 = _artist_key_and_u64(artist_obj)
        key_to_u64[key_str] = key_u64
        prev = u64_to_key.get(key_u64)
        if prev is None:
            u64_to_key[key_u64] = key_str
        elif prev != key_str:
            key_collision = True
        if key_str not in artist_meta:
            artist_meta[key_str] = {
                "key": key_str,
                "artist": artist_obj,
                "name": str(getattr(artist_obj, "name", "Unknown") or "Unknown"),
            }
        artist_key_strs.append(key_str)
        artist_key_u64.append(key_u64)
        title_lc.append(str(getattr(t, "name", "") or "").lower())
        artist_lc.append(str(getattr(artist_obj, "name", "") or "").lower())
        album_lc.append(str(getattr(getattr(t, "album", None), "name", "") or "").lower())
        durations.append(int(getattr(t, "duration", 0) or 0))

    title_rank = _build_rank(title_lc)
    artist_rank = _build_rank(artist_lc)
    album_rank = _build_rank(album_lc)
    sort_mode_id = {"recent": 0, "title": 1, "artist": 2, "album": 3, "duration": 4}

    # Build a compact UTF-8 blob for Rust query filtering.
    search_blob = bytearray()
    search_offsets = []
    search_lens = []
    for i in range(len(all_tracks)):
        s = f"{title_lc[i]}\n{artist_lc[i]}\n{album_lc[i]}"
        b = s.encode("utf-8", "ignore")
        search_offsets.append(len(search_blob))
        search_lens.append(len(b))
        search_blob.extend(b)

    artist_counts = None
    rust_core = _get_rust_collection_core()
    if rust_core is not None and getattr(rust_core, "available", False) and not key_collision:
        try:
            artist_counts = rust_core.count_artist_keys(artist_key_u64)
            logger.info("Liked songs artist aggregation path: Rust")
        except Exception:
            artist_counts = None
            logger.exception("Rust artist aggregation failed; fallback to Python")

    if artist_counts is not None:
        artist_items = []
        for key_u64, count in artist_counts:
            key_str = u64_to_key.get(int(key_u64))
            if not key_str:
                continue
            meta = artist_meta.get(key_str, {})
            artist_items.append(
                {
                    "key": key_str,
                    "artist": meta.get("artist"),
                    "name": str(meta.get("name", "Unknown") or "Unknown"),
                    "count": int(count),
                }
            )
    else:
        artist_groups = {}
        for i, key_str in enumerate(artist_key_strs):
            if key_str not in artist_groups:
                meta = artist_meta.get(key_str, {})
                artist_groups[key_str] = {
                    "key": key_str,
                    "artist": meta.get("artist"),
                    "name": str(meta.get("name", "Unknown") or "Unknown"),
                    "count": 0,
                }
            artist_groups[key_str]["count"] += 1
        artist_items = sorted(
            artist_groups.values(),
            key=lambda it: (-int(it.get("count", 0) or 0), str(it.get("name", "")).lower()),
        )
    max_artist_filters = 120
    artist_items = artist_items[:max_artist_filters]

    artist_filter_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_bottom=8)
    artist_filter_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=False, css_classes=["liked-artist-filter-scroll"])
    artist_filter_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
    artist_filter_scroll.set_min_content_height(90)
    artist_filter_flow = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=10,
        css_classes=["liked-artist-filter-flow"],
    )
    artist_filter_scroll.set_child(artist_filter_flow)

    artist_filter_row.append(artist_scroll_prev_btn)
    artist_filter_row.append(artist_filter_scroll)
    artist_filter_row.append(artist_scroll_next_btn)
    app.collection_content_box.append(artist_filter_row)

    app.liked_artist_filter_buttons = {}

    def _refresh_artist_filter_buttons():
        selected = getattr(app, "liked_tracks_artist_filter", None)
        for key, btn in dict(getattr(app, "liked_artist_filter_buttons", {}) or {}).items():
            if selected and key == selected:
                btn.add_css_class("active")
            else:
                btn.remove_css_class("active")

    def _on_artist_filter_clicked(key):
        current = getattr(app, "liked_tracks_artist_filter", None)
        app.liked_tracks_artist_filter = None if current == key else key
        app.liked_tracks_page = 0
        _refresh_artist_filter_buttons()
        _apply_filters()

    for item in artist_items:
        artist_obj = item.get("artist")
        key = item.get("key")
        name = str(item.get("name", "Unknown") or "Unknown")
        count = int(item.get("count", 0) or 0)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=Gtk.Align.CENTER)
        overlay = Gtk.Overlay()
        img = Gtk.Image(css_classes=["circular-avatar", "liked-artist-filter-img"])
        img.set_size_request(96, 96)
        img.set_pixel_size(96)
        img.set_from_icon_name("avatar-default-symbolic")
        if artist_obj is not None:
            utils.load_img(
                img,
                # Keep behavior aligned with Artists page: allow full fallback chain,
                # including album-art fallback when artist artwork is unavailable.
                lambda a=artist_obj: app.backend.get_artist_artwork_url(a, 320),
                app.cache_dir,
                96,
            )
        overlay.set_child(img)

        badge = Gtk.Label(label=str(count), css_classes=["liked-artist-count-badge"])
        badge.set_halign(Gtk.Align.END)
        badge.set_valign(Gtk.Align.END)
        overlay.add_overlay(badge)
        card.append(overlay)
        card.append(Gtk.Label(label=name, css_classes=["dim-label", "liked-artist-filter-name"], max_width_chars=16, ellipsize=3))

        btn = Gtk.Button(css_classes=["flat", "liked-artist-filter-btn"])
        btn.set_tooltip_text(f"Show {name} tracks")
        btn.set_child(card)
        btn.connect("clicked", lambda _b, k=key: _on_artist_filter_clicked(k))
        app.liked_artist_filter_buttons[key] = btn

        artist_filter_flow.append(btn)

    h_adj = artist_filter_scroll.get_hadjustment()

    def _update_artist_scroll_btns(*_args):
        if h_adj is None:
            return
        lower = float(h_adj.get_lower() or 0.0)
        upper = float(h_adj.get_upper() or 0.0)
        page = float(h_adj.get_page_size() or 0.0)
        value = float(h_adj.get_value() or 0.0)
        max_value = max(lower, upper - page)
        has_overflow = upper > page + 1.0
        artist_scroll_prev_btn.set_sensitive(has_overflow and value > lower + 1.0)
        artist_scroll_next_btn.set_sensitive(has_overflow and value < max_value - 1.0)

    def _scroll_artist_filter(direction):
        if h_adj is None:
            return
        step = max(120.0, float(h_adj.get_page_size() or 0.0) * 0.75)
        lower = float(h_adj.get_lower() or 0.0)
        upper = float(h_adj.get_upper() or 0.0)
        page = float(h_adj.get_page_size() or 0.0)
        max_value = max(lower, upper - page)
        cur = float(h_adj.get_value() or 0.0)
        target = cur + (step * direction)
        h_adj.set_value(max(lower, min(max_value, target)))
        _update_artist_scroll_btns()

    artist_scroll_prev_btn.connect("clicked", lambda _b: _scroll_artist_filter(-1))
    artist_scroll_next_btn.connect("clicked", lambda _b: _scroll_artist_filter(1))
    if h_adj is not None:
        h_adj.connect("changed", _update_artist_scroll_btns)
        h_adj.connect("value-changed", _update_artist_scroll_btns)
    GLib.idle_add(_update_artist_scroll_btns)

    table_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    app.collection_content_box.append(table_box)

    tracks_head, head_btns = build_tracks_header(
        on_sort_title=lambda _b: None,
        on_sort_artist=lambda _b: None,
        on_sort_album=lambda _b: None,
        on_sort_time=lambda _b: None,
    )
    for key in ("title", "artist", "album", "time"):
        lbl = head_btns.get(key)
        if lbl is None:
            continue
        lbl.set_xalign(0.0)
        lbl.set_halign(Gtk.Align.FILL)
    append_header_action_spacers(tracks_head, ["fav", "add"])

    table_box.append(tracks_head)

    list_box = Gtk.ListBox(css_classes=["tracks-list"], margin_start=0, margin_end=0, margin_bottom=32)
    app.liked_track_list = list_box
    list_box.connect("row-activated", lambda box, row: app.on_history_track_clicked(getattr(box, "liked_tracks", []), getattr(row, "liked_track_index", -1)))
    table_box.append(list_box)

    def _play_liked_tracks(tracks, shuffle=False):
        items = [t for t in list(tracks or []) if t is not None]
        if not items:
            return
        queue = list(items)
        if shuffle:
            random.shuffle(queue)
        app.current_track_list = queue
        if hasattr(app, "_set_play_queue"):
            app._set_play_queue(queue)
        else:
            app.play_queue = queue
        app.play_track(0)

    def _queue_liked_tracks_next(tracks):
        items = [t for t in list(tracks or []) if t is not None]
        if not items:
            return
        playing = getattr(app, "playing_track", None)
        if playing is None:
            _play_liked_tracks(items, shuffle=False)
            return

        base_queue = list(app._get_active_queue() if hasattr(app, "_get_active_queue") else (getattr(app, "play_queue", []) or []))
        if not base_queue:
            _play_liked_tracks(items, shuffle=False)
            return

        current_idx = int(getattr(app, "current_track_index", -1) or -1)
        if current_idx < 0 or current_idx >= len(base_queue):
            current_idx = 0
        insert_at = min(len(base_queue), current_idx + 1)
        new_queue = list(base_queue)
        new_queue[insert_at:insert_at] = items
        if hasattr(app, "_set_play_queue"):
            app._set_play_queue(new_queue)
        else:
            app.play_queue = new_queue
        if hasattr(app, "_refresh_queue_views"):
            GLib.idle_add(app._refresh_queue_views)

    play_all_btn.connect("clicked", lambda _b: _play_liked_tracks(getattr(list_box, "liked_tracks", []), shuffle=False))
    shuffle_btn.connect("clicked", lambda _b: _play_liked_tracks(getattr(list_box, "liked_tracks", []), shuffle=True))

    def _apply_filters():
        q = str(getattr(app, "liked_tracks_query", "") or "").strip().lower()
        mode = getattr(app, "liked_tracks_sort", "recent")
        artist_filter = getattr(app, "liked_tracks_artist_filter", None)
        filtered_indices = None

        # Fast path: when query is empty, offload filter/sort to Rust.
        if not q and rust_core is not None and getattr(rust_core, "available", False):
            try:
                use_filter = bool(artist_filter and artist_filter in key_to_u64)
                filter_key = int(key_to_u64.get(artist_filter, 0))
                filtered_indices = rust_core.filter_sort_indices_no_query(
                    artist_keys=artist_key_u64,
                    title_rank=title_rank,
                    artist_rank=artist_rank,
                    album_rank=album_rank,
                    durations=durations,
                    sort_mode=int(sort_mode_id.get(mode, 0)),
                    artist_filter_key=filter_key,
                    use_artist_filter=use_filter,
                )
                logger.info(
                    "Liked songs filter/sort path: Rust-noquery (mode=%s, artist_filter=%s, total=%s, result=%s)",
                    mode,
                    "on" if use_filter else "off",
                    len(all_tracks),
                    len(filtered_indices or []),
                )
            except Exception:
                filtered_indices = None
                logger.exception("Rust liked-songs filter/sort failed; fallback to Python")

        if filtered_indices is None and q and rust_core is not None and getattr(rust_core, "available", False):
            try:
                use_filter = bool(artist_filter and artist_filter in key_to_u64)
                filter_key = int(key_to_u64.get(artist_filter, 0))
                filtered_indices = rust_core.filter_sort_indices_with_query(
                    search_blob=bytes(search_blob),
                    search_offsets=search_offsets,
                    search_lens=search_lens,
                    artist_keys=artist_key_u64,
                    title_rank=title_rank,
                    artist_rank=artist_rank,
                    album_rank=album_rank,
                    durations=durations,
                    sort_mode=int(sort_mode_id.get(mode, 0)),
                    query=q,
                    artist_filter_key=filter_key,
                    use_artist_filter=use_filter,
                )
                logger.info(
                    "Liked songs filter/sort path: Rust-query (mode=%s, artist_filter=%s, query_len=%s, total=%s, result=%s)",
                    mode,
                    "on" if use_filter else "off",
                    len(q),
                    len(all_tracks),
                    len(filtered_indices or []),
                )
            except Exception:
                filtered_indices = None
                logger.exception("Rust liked-songs query filter/sort failed; fallback to Python")

        if filtered_indices is None:
            logger.info(
                "Liked songs filter/sort path: Python-fallback (mode=%s, query_len=%s, artist_filter=%s, total=%s)",
                mode,
                len(q),
                "on" if bool(artist_filter) else "off",
                len(all_tracks),
            )
            filtered_indices = list(range(len(all_tracks)))
            if artist_filter:
                filtered_indices = [i for i in filtered_indices if artist_key_strs[i] == artist_filter]
            if q:
                filtered_indices = [
                    i
                    for i in filtered_indices
                    if (q in title_lc[i] or q in artist_lc[i] or q in album_lc[i])
                ]
            if mode == "title":
                filtered_indices.sort(key=lambda i: title_rank[i])
            elif mode == "artist":
                filtered_indices.sort(key=lambda i: artist_rank[i])
            elif mode == "album":
                filtered_indices.sort(key=lambda i: album_rank[i])
            elif mode == "duration":
                filtered_indices.sort(key=lambda i: durations[i])
            # recent => keep backend order

        filtered = [all_tracks[i] for i in filtered_indices]

        _clear_container(list_box)
        list_box.liked_tracks = filtered

        total = len(filtered)
        page_size = max(1, int(getattr(app, "liked_tracks_page_size", 50) or 50))
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = int(getattr(app, "liked_tracks_page", 0) or 0)
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        app.liked_tracks_page = page
        start = page * page_size
        end = min(start + page_size, total)
        page_items = filtered[start:end] if total > 0 else []

        play_all_btn.set_sensitive(bool(filtered))
        shuffle_btn.set_sensitive(bool(filtered))
        prev_page_btn.set_sensitive(page > 0)
        next_page_btn.set_sensitive(page < (total_pages - 1))

        if not page_items:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            row.set_child(Gtk.Label(label="No liked songs found.", xalign=0, css_classes=["dim-label"], margin_start=12, margin_top=12, margin_bottom=12))
            list_box.append(row)
            return

        for i, t in enumerate(page_items):
            abs_i = start + i
            row = Gtk.ListBoxRow(css_classes=["track-row"])
            row.liked_track_index = abs_i
            row.track_id = getattr(t, "id", None)
            box = Gtk.Box(
                spacing=LAYOUT["col_gap"],
                margin_top=LAYOUT["row_margin_y"],
                margin_bottom=LAYOUT["row_margin_y"],
                margin_start=0,
                margin_end=0,
            )
            stack = Gtk.Stack()
            stack.set_size_request(LAYOUT["index_width"], -1)
            stack.add_css_class("track-index-stack")
            idx = Gtk.Label(label=str(abs_i + 1), css_classes=["dim-label"])
            stack.add_named(idx, "num")
            icon = Gtk.Image(icon_name="media-playback-start-symbolic")
            icon.add_css_class("accent")
            stack.add_named(icon, "icon")
            stack.set_visible_child_name("num")
            box.append(stack)

            title = str(getattr(t, "name", "Unknown Track") or "Unknown Track")
            title_lbl = Gtk.Label(label=title, xalign=0, ellipsize=3, hexpand=True, css_classes=["track-title"])
            title_lbl.set_tooltip_text(title)
            box.append(title_lbl)

            artist_name = str(getattr(getattr(t, "artist", None), "name", "Unknown") or "Unknown")
            artist_lbl = Gtk.Label(label=artist_name, xalign=0, ellipsize=3, css_classes=["dim-label", "track-artist"])
            artist_lbl.set_tooltip_text(artist_name)
            artist_lbl.set_size_request(LAYOUT["artist_width"], -1)
            artist_lbl.set_max_width_chars(16)
            artist_lbl.set_margin_end(LAYOUT["cell_margin_end"])
            box.append(artist_lbl)

            album_name = str(getattr(getattr(t, "album", None), "name", "Unknown Album") or "Unknown Album")
            album_lbl = Gtk.Label(label=album_name, xalign=0, ellipsize=3, css_classes=["dim-label", "track-album"])
            album_lbl.set_tooltip_text(album_name)
            album_lbl.set_size_request(LAYOUT["album_width"], -1)
            album_lbl.set_max_width_chars(16)
            album_lbl.set_margin_end(LAYOUT["cell_margin_end"])
            box.append(album_lbl)

            dur = int(getattr(t, "duration", 0) or 0)
            m, s = divmod(max(0, dur), 60)
            d = Gtk.Label(label=f"{m}:{s:02d}", xalign=0, css_classes=["dim-label", "track-duration"])
            d.set_attributes(Pango.AttrList.from_string("font-features 'tnum=1'"))
            d.set_size_request(LAYOUT["time_width"], -1)
            d.set_halign(Gtk.Align.FILL)
            box.append(d)

            fav_btn = app.create_track_fav_button(t)
            fav_btn.connect("clicked", lambda _b: GLib.timeout_add(260, lambda: app.refresh_liked_songs_dashboard(force=True)))
            box.append(fav_btn)

            add_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
            add_btn.set_tooltip_text("Add to Playlist")
            add_btn.connect("clicked", lambda _b, tr=t: app.on_add_single_track_to_playlist(tr))
            box.append(add_btn)
            row.set_child(box)
            list_box.append(row)

        if hasattr(app, "_update_track_list_icon"):
            app._update_track_list_icon(target_list=list_box)

    def _on_search_changed(entry):
        app.liked_tracks_query = entry.get_text()
        app.liked_tracks_page = 0
        _apply_filters()

    def _on_sort_changed(dd, _pspec):
        idx = int(dd.get_selected())
        app.liked_tracks_sort = {0: "recent", 1: "title", 2: "artist", 3: "album", 4: "duration"}.get(idx, "recent")
        app.liked_tracks_page = 0
        _apply_filters()

    def _on_prev_page(_btn):
        app.liked_tracks_page = max(0, int(getattr(app, "liked_tracks_page", 0) or 0) - 1)
        _apply_filters()

    def _on_next_page(_btn):
        app.liked_tracks_page = int(getattr(app, "liked_tracks_page", 0) or 0) + 1
        _apply_filters()

    search_entry.connect("changed", _on_search_changed)
    sort_dd.connect("notify::selected", _on_sort_changed)
    prev_page_btn.connect("clicked", _on_prev_page)
    next_page_btn.connect("clicked", _on_next_page)
    _refresh_artist_filter_buttons()
    # Save signature and filter function so subsequent renders with the same
    # data can skip the full widget rebuild and just re-run filters.
    app._liked_tracks_view_sig = curr_sig
    app._liked_tracks_apply_fn = _apply_filters
    _apply_filters()


def render_queue_drawer(app):
    list_box = getattr(app, "queue_drawer_list", None)
    if list_box is None:
        return
    tracks = app._get_active_queue() if hasattr(app, "_get_active_queue") else list(getattr(app, "current_track_list", []) or [])
    current_idx = int(getattr(app, "current_track_index", -1) or -1)
    count_lbl = getattr(app, "queue_count_label", None)
    if count_lbl is not None:
        count_lbl.set_text(f"{len(tracks)} tracks")
    clear_btn = getattr(app, "queue_clear_btn", None)
    if clear_btn is not None:
        clear_btn.set_sensitive(bool(tracks))

    # Fast path: when queue content and playback index are unchanged, keep
    # existing row widgets to avoid costly full rebuild on drawer open.
    # Use only the rendered window for the signature — iterating thousands of
    # track IDs on every open is itself a noticeable cost.
    total = len(tracks)
    anchor = max(0, min(current_idx, total - 1)) if total > 0 else 0
    sig_start = max(0, anchor - _QUEUE_WINDOW_BEFORE)
    sig_end   = min(total, anchor + _QUEUE_WINDOW_AFTER + 1)
    sig_ids = (total, tuple(str(getattr(t, "id", f"obj:{id(t)}")) for t in tracks[sig_start:sig_end]))
    sig = (sig_ids, current_idx)
    prev_sig = getattr(app, "_queue_drawer_render_sig", None)
    if prev_sig == sig and list_box.get_first_child() is not None:
        return

    _clear_container(list_box)
    if not tracks:
        app._queue_drawer_render_sig = sig
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        hint = Gtk.Label(
            label="Queue is empty.\nPlay something to build it.",
            xalign=0,
            css_classes=["dim-label"],
            margin_start=12,
            margin_end=12,
            margin_top=16,
            margin_bottom=16,
        )
        row.set_child(hint)
        list_box.append(row)
        return

    _populate_queue_rows(app, list_box, tracks, current_idx, compact=True)
    app._queue_drawer_render_sig = sig
    if hasattr(app, "_update_track_list_icon"):
        app._update_track_list_icon(target_list=list_box)


def render_playlists_home(app):
    _clear_container(app.collection_content_box)
    app.playlist_track_list = None

    section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section", "home-generic-section"])

    head = Gtk.Box(spacing=8, css_classes=["home-section-head"], margin_start=6, margin_end=6, margin_bottom=8, margin_top=6)
    stack = list(getattr(app, "current_playlist_folder_stack", []) or [])
    if stack:
        crumbs = " / ".join([str(x.get("name", "Folder")) for x in stack])
        title_txt = f"Folders / {crumbs}"
    else:
        title_txt = "Your Playlists"
    head.append(Gtk.Label(label=title_txt, xalign=0, hexpand=True, css_classes=["home-section-title"]))
    count_lbl = Gtk.Label(label="", css_classes=["home-section-count"])
    head.append(count_lbl)
    up_btn = Gtk.Button(icon_name="go-up-symbolic", css_classes=["flat", "playlist-add-top-btn"])
    up_btn.set_tooltip_text("Up Folder")
    up_btn.set_sensitive(bool(stack))
    up_btn.connect("clicked", app.on_playlist_folder_up_clicked)
    head.append(up_btn)
    if stack:
        rename_folder_btn = Gtk.Button(icon_name="document-edit-symbolic", css_classes=["playlist-add-top-btn"])
        rename_folder_btn.set_tooltip_text("Rename Current Folder")
        rename_folder_btn.connect("clicked", lambda _b: app.on_playlist_folder_rename_clicked())
        head.append(rename_folder_btn)
        delete_folder_btn = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["playlist-add-top-btn"])
        delete_folder_btn.set_tooltip_text("Delete Current Folder")
        delete_folder_btn.connect("clicked", lambda _b: app.on_playlist_folder_delete_clicked())
        head.append(delete_folder_btn)
    if not stack:
        create_btn = Gtk.MenuButton(icon_name="list-add-symbolic", css_classes=["playlist-add-top-btn"])
        create_btn.set_tooltip_text("Create...")
        create_pop = Gtk.Popover()
        create_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            margin_top=8,
            margin_bottom=8,
            margin_start=8,
            margin_end=8,
        )
        new_folder_btn = Gtk.Button(label="New Folder", css_classes=["flat"])
        new_folder_btn.connect("clicked", lambda _b: (create_pop.popdown(), app.on_create_playlist_folder_clicked()))
        create_box.append(new_folder_btn)

        new_playlist_btn = Gtk.Button(label="New Playlist", css_classes=["flat"])
        new_playlist_btn.connect("clicked", lambda _b: (create_pop.popdown(), app.on_create_playlist_clicked()))
        create_box.append(new_playlist_btn)

        create_pop.set_child(create_box)
        create_btn.set_popover(create_pop)
    else:
        create_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["playlist-add-top-btn"])
        create_btn.set_tooltip_text("Create Playlist")
        create_btn.connect("clicked", app.on_create_playlist_clicked)
    head.append(create_btn)
    section_box.append(head)

    flow = Gtk.FlowBox(
        valign=Gtk.Align.START,
        max_children_per_line=30,
        selection_mode=Gtk.SelectionMode.NONE,
        column_spacing=24,
        row_spacing=28,
        css_classes=["home-flow"],
    )
    section_box.append(flow)
    app.collection_content_box.append(section_box)

    def task():
        parent_folder = getattr(app, "current_playlist_folder", None)
        payload = dict(app.backend.get_playlists_and_folders(parent_folder=parent_folder, limit=1000) or {})
        folders = list(payload.get("folders", []) or [])
        playlists = list(payload.get("playlists", []) or [])

        # Phase 1: render all cards immediately with placeholder collages.
        # Phase 2: async per-folder preview artwork fetching without blocking the UI.
        folder_collage_imgs: dict = {}  # fid -> list[Gtk.Image]

        def apply():
            nonlocal folder_collage_imgs
            count_lbl.set_text(f"{len(folders)} folders • {len(playlists)} playlists")

            for f in folders:
                fid = str(getattr(f, "id", "") or "")
                card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=_feed_card_classes())
                overlay = Gtk.Overlay(css_classes=["home-feed-media"])
                cover = Gtk.Box(css_classes=["playlist-folder-cover"])
                cover.set_size_request(utils.COVER_SIZE, utils.COVER_SIZE)
                overlay.set_child(cover)
                overlay.add_overlay(_build_feed_media_tint(utils.COVER_SIZE, "playlist-folder-shape"))

                collage = Gtk.Grid(css_classes=["playlist-folder-collage"])
                collage.set_row_homogeneous(True)
                collage.set_column_homogeneous(True)
                collage.set_size_request(utils.COVER_SIZE, utils.COVER_SIZE)
                # All 4 slots start as placeholders; async task fills in real artwork.
                for idx in range(4):
                    cell = Gtk.Box(css_classes=["playlist-folder-cell"])
                    img = Gtk.Image(css_classes=["album-cover-img", "playlist-cover-img", "playlist-folder-preview-img"])
                    img.set_size_request(utils.COVER_SIZE // 2, utils.COVER_SIZE // 2)
                    img.set_pixel_size(utils.COVER_SIZE // 2)
                    img.set_from_icon_name("audio-x-generic-symbolic")
                    img.set_opacity(0.35)
                    cell.append(img)
                    collage.attach(cell, idx % 2, idx // 2, 1, 1)
                collage.set_row_spacing(2)
                collage.set_column_spacing(2)
                cover.append(collage)
                # Save img widgets for async artwork population below.
                if fid:
                    slot_imgs = [collage.get_child_at(i % 2, i // 2).get_first_child() for i in range(4)]
                    folder_collage_imgs[fid] = (f, slot_imgs)

                folder_items = int(getattr(f, "total_number_of_items", 0) or 0)
                badge = Gtk.Label(label=str(folder_items), css_classes=["playlist-folder-badge"])
                badge.set_halign(Gtk.Align.END)
                badge.set_valign(Gtk.Align.START)
                badge.set_margin_end(0)
                badge.set_margin_top(3)
                overlay.add_overlay(badge)
                overlay.set_clip_overlay(badge, False)
                card.append(overlay)
                card.append(
                    Gtk.Label(
                        label=getattr(f, "name", None) or "Folder",
                        ellipsize=3,
                        halign=Gtk.Align.CENTER,
                        wrap=True,
                        max_width_chars=16,
                        css_classes=["home-card-title"],
                    )
                )
                open_btn = Gtk.Button(css_classes=["flat", "history-card-btn", "home-feed-btn"])
                open_btn.set_child(card)
                open_btn.connect("clicked", lambda _b, fd=f: app.on_playlist_folder_card_clicked(fd))
                more_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
                more_btn.set_halign(Gtk.Align.END)
                more_btn.set_valign(Gtk.Align.END)
                more_btn.set_margin_end(6)
                more_btn.set_margin_bottom(29)
                more_btn.set_tooltip_text("Folder actions")
                pop = Gtk.Popover()
                pop_box = Gtk.Box(
                    orientation=Gtk.Orientation.VERTICAL,
                    spacing=4,
                    margin_top=8,
                    margin_bottom=8,
                    margin_start=8,
                    margin_end=8,
                )
                rename_btn = Gtk.Button(label="Rename Folder", css_classes=["flat"])
                rename_btn.connect("clicked", lambda _b, fd=f, p=pop: (p.popdown(), app.on_playlist_folder_rename_clicked(fd)))
                pop_box.append(rename_btn)
                delete_btn = Gtk.Button(label="Delete Folder", css_classes=["flat"])
                delete_btn.connect("clicked", lambda _b, fd=f, p=pop: (p.popdown(), app.on_playlist_folder_delete_clicked(fd)))
                pop_box.append(delete_btn)
                pop.set_child(pop_box)
                more_btn.set_popover(pop)
                wrapper_ov = Gtk.Overlay()
                wrapper_ov.set_child(open_btn)
                wrapper_ov.add_overlay(more_btn)
                wrapper_ov.set_clip_overlay(more_btn, False)
                child = Gtk.FlowBoxChild()
                child.set_child(wrapper_ov)
                flow.append(child)

            for p in playlists:
                card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=_feed_card_classes())
                img = Gtk.Image(css_classes=["album-cover-img", "playlist-cover-img"])
                img.set_size_request(utils.COVER_SIZE, utils.COVER_SIZE)
                utils.load_img(img, lambda pl=p: app.backend.get_artwork_url(pl, 320), app.cache_dir, utils.COVER_SIZE)
                card.append(_build_feed_media_overlay(img, utils.COVER_SIZE, "album-cover-img"))
                card.append(
                    Gtk.Label(
                        label=getattr(p, "name", None) or "Untitled Playlist",
                        ellipsize=3,
                        halign=Gtk.Align.CENTER,
                        wrap=True,
                        max_width_chars=16,
                        css_classes=["home-card-title"],
                    )
                )
                open_btn = Gtk.Button(css_classes=["flat", "history-card-btn", "home-feed-btn"])
                open_btn.set_child(card)
                open_btn.connect("clicked", lambda _b, pl=p: app.on_remote_playlist_card_clicked(pl))
                child = Gtk.FlowBoxChild()
                child.set_child(open_btn)
                flow.append(child)

            if not playlists and not folders:
                hint = Gtk.Label(
                    label="No folders or playlists found here. Create one to get started.",
                    xalign=0,
                    css_classes=["dim-label"],
                    margin_start=8,
                    margin_top=8,
                )
                section_box.append(hint)

            # Phase 2: fetch folder preview artworks asynchronously so the page
            # renders immediately without waiting for per-folder API calls.
            if folder_collage_imgs:
                def _fetch_folder_previews(collage_map=dict(folder_collage_imgs)):
                    for fid, (f_obj, slot_imgs) in collage_map.items():
                        try:
                            urls = list(app.backend.get_folder_preview_artworks(f_obj, limit=4, size=320) or [])
                        except Exception:
                            urls = []
                        captured = list(zip(urls, slot_imgs))

                        def _apply_previews(pairs=captured):
                            for url, img in pairs:
                                if url:
                                    img.set_opacity(1.0)
                                    utils.load_img(img, url, app.cache_dir, utils.COVER_SIZE // 2)
                            return False

                        GLib.idle_add(_apply_previews)

                Thread(target=_fetch_folder_previews, daemon=True).start()

            return False

        GLib.idle_add(apply)

    Thread(target=task, daemon=True).start()


def render_playlist_detail(app, playlist_id):
    _clear_container(app.collection_content_box)
    p = app.playlist_mgr.get_playlist(playlist_id) if hasattr(app, "playlist_mgr") else None
    if not p:
        render_playlists_home(app)
        return
    detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    app.collection_content_box.append(detail_box)

    header_box = Gtk.Box(spacing=24, css_classes=["album-header-box"])
    cover = Gtk.Image(pixel_size=utils.COVER_SIZE, css_classes=["header-art"])
    cover.set_size_request(utils.COVER_SIZE, utils.COVER_SIZE)
    refs = app.playlist_mgr.get_cover_refs(p, limit=4)
    collage_dir = os.path.join(app.cache_dir, "playlist_covers")
    collage = utils.generate_auto_collage_cover(
        refs,
        image_cache_dir=app.cache_dir,
        collage_cache_dir=collage_dir,
        key_prefix=f"playlist_{p.get('id', 'x')}_{p.get('updated_at', 0)}",
        size=256,
        overlay_alpha=0.34,
        overlay_style="mix",
    )
    if collage:
        utils.load_img(cover, collage, app.cache_dir, utils.COVER_SIZE)
    else:
        cover.set_pixel_size(utils.COVER_SIZE)
        cover.set_from_icon_name("audio-x-generic-symbolic")
    header_box.append(cover)

    info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
    info.append(Gtk.Label(label="Playlist", xalign=0, css_classes=["album-kicker"]))

    title_box = Gtk.Box(spacing=8)
    if bool(getattr(app, "playlist_rename_mode", False)):
        rename_entry = Gtk.Entry(text=p.get("name", "Playlist"))
        rename_entry.set_hexpand(True)
        rename_entry.set_width_chars(28)
        rename_entry.connect("activate", lambda e: app.on_playlist_commit_inline_rename(p.get("id"), e.get_text()))
        title_box.append(rename_entry)
        save_btn = Gtk.Button(icon_name="object-select-symbolic", css_classes=["flat", "playlist-tool-btn", "playlist-title-edit-btn"])
        save_btn.set_tooltip_text("Save")
        save_btn.connect("clicked", lambda _b: app.on_playlist_commit_inline_rename(p.get("id"), rename_entry.get_text()))
        title_box.append(save_btn)
        cancel_btn = Gtk.Button(icon_name="window-close-symbolic", css_classes=["flat", "playlist-tool-btn", "playlist-title-edit-btn"])
        cancel_btn.set_tooltip_text("Cancel")
        cancel_btn.connect("clicked", lambda _b: app.on_playlist_cancel_inline_rename(p.get("id")))
        title_box.append(cancel_btn)
    else:
        title_lbl = Gtk.Label(label=p.get("name", "Playlist"), xalign=0, css_classes=["album-title-large"])
        title_box.append(title_lbl)
        rename_btn = Gtk.Button(icon_name="document-edit-symbolic", css_classes=["flat", "playlist-tool-btn", "playlist-title-edit-btn"])
        rename_btn.set_tooltip_text("Rename Playlist")
        rename_btn.connect("clicked", lambda _b: app.on_playlist_start_inline_rename(p.get("id")))
        title_box.append(rename_btn)
    info.append(title_box)
    created_at = p.get("created_at")
    created_text = "Created just now"
    try:
        if created_at:
            created_text = f"Created {datetime.fromtimestamp(int(created_at)).strftime('%Y-%m-%d %H:%M')}"
    except Exception:
        pass
    subtitle_line = f"{created_text}  •  {len(p.get('tracks', []))} tracks"
    info.append(Gtk.Label(label=subtitle_line, xalign=0, css_classes=["album-meta"]))
    if getattr(app, "playlist_edit_mode", False):
        info.append(Gtk.Label(label="Edit mode: drag tracks to reorder", xalign=0, css_classes=["album-meta", "album-meta-pill"]))
    header_box.append(info)

    actions_box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
    edit_icon = "object-select-symbolic" if getattr(app, "playlist_edit_mode", False) else "view-sort-ascending-symbolic"
    edit_btn = Gtk.Button(icon_name=edit_icon, css_classes=["flat", "playlist-tool-btn"])
    edit_btn.set_tooltip_text("Done" if getattr(app, "playlist_edit_mode", False) else "Edit Playlist")
    edit_btn.connect("clicked", app.on_playlist_toggle_edit)
    actions_box.append(edit_btn)
    del_btn = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat", "playlist-tool-btn"])
    del_btn.set_tooltip_text("Delete Playlist")
    del_btn.connect("clicked", lambda _b: app.on_playlist_delete_clicked(p.get("id")))
    actions_box.append(del_btn)
    add_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat", "playlist-tool-btn"])
    add_btn.set_tooltip_text("Add Current Playing Track")
    actions_box.append(add_btn)
    header_box.append(actions_box)
    detail_box.append(header_box)

    def _on_add_current(_btn):
        tr = getattr(app, "playing_track", None)
        if tr is None:
            return
        cover_url = app.backend.get_artwork_url(tr, 320)
        app.playlist_mgr.add_track(p.get("id"), tr, cover_url=cover_url)
        app.render_playlist_detail(p.get("id"))

    add_btn.connect("clicked", _on_add_current)

    tracks = app.get_sorted_playlist_tracks(p.get("id")) if hasattr(app, "get_sorted_playlist_tracks") else app.playlist_mgr.get_tracks(p.get("id"))
    if not tracks:
        app.playlist_track_list = None
        empty = Gtk.Label(label="No tracks yet.", xalign=0, css_classes=["dim-label"], margin_start=8, margin_top=8)
        detail_box.append(empty)
        return

    edit_mode = bool(getattr(app, "playlist_edit_mode", False))

    tracks_head, head_btns = build_tracks_header(
        on_sort_title=lambda _b: app.on_playlist_sort_clicked("title"),
        on_sort_artist=lambda _b: app.on_playlist_sort_clicked("artist"),
        on_sort_album=lambda _b: app.on_playlist_sort_clicked("album"),
        on_sort_time=lambda _b: app.on_playlist_sort_clicked("time"),
        title_text=app._format_sort_label("Title", "title", getattr(app, "playlist_sort_field", None), getattr(app, "playlist_sort_asc", True)),
        artist_text=app._format_sort_label("Artist", "artist", getattr(app, "playlist_sort_field", None), getattr(app, "playlist_sort_asc", True)),
        album_text=app._format_sort_label("Album", "album", getattr(app, "playlist_sort_field", None), getattr(app, "playlist_sort_asc", True)),
        time_text=app._format_sort_label("Time", "time", getattr(app, "playlist_sort_field", None), getattr(app, "playlist_sort_asc", True)),
    )
    if edit_mode:
        append_header_action_spacers(tracks_head, ["fav", "drag", "playlist_remove"])
    else:
        append_header_action_spacers(tracks_head, ["fav", "add"])
    title_head = head_btns["title"]
    artist_head = head_btns["artist"]
    album_head = head_btns["album"]
    dur_head = head_btns["time"]
    detail_box.append(tracks_head)

    list_box = Gtk.ListBox(css_classes=["tracks-list"], margin_start=0, margin_end=0, margin_bottom=32)
    app.playlist_track_list = list_box
    list_box.playlist_tracks = tracks
    list_box.connect("row-activated", app.on_playlist_track_selected)
    title_head.set_sensitive(not edit_mode)
    artist_head.set_sensitive(not edit_mode)
    album_head.set_sensitive(not edit_mode)
    dur_head.set_sensitive(not edit_mode)

    def _build_playlist_row(i, t):
        row = Gtk.ListBoxRow(css_classes=["track-row"])
        row.playlist_track_index = i
        row.track_id = getattr(t, "id", None)
        box = Gtk.Box(
            spacing=LAYOUT["col_gap"],
            margin_top=LAYOUT["row_margin_y"],
            margin_bottom=LAYOUT["row_margin_y"],
            margin_start=LAYOUT["row_margin_x"],
            margin_end=LAYOUT["row_margin_x"],
        )
        stack = Gtk.Stack()
        stack.set_size_request(LAYOUT["index_width"], -1)
        stack.add_css_class("track-index-stack")
        idx = Gtk.Label(label=str(i + 1), css_classes=["dim-label"])
        stack.add_named(idx, "num")
        icon = Gtk.Image(icon_name="media-playback-start-symbolic")
        icon.add_css_class("accent")
        stack.add_named(icon, "icon")
        stack.set_visible_child_name("num")
        box.append(stack)
        title_lbl = Gtk.Label(label=getattr(t, "name", "Unknown Track"), xalign=0, ellipsize=3, hexpand=True, css_classes=["track-title"])
        title_lbl.set_tooltip_text(getattr(t, "name", "Unknown Track"))
        box.append(title_lbl)
        artist_name = getattr(getattr(t, "artist", None), "name", "Unknown")
        artist = Gtk.Label(label=artist_name, xalign=0, ellipsize=3, css_classes=["dim-label", "track-artist"])
        artist.set_tooltip_text(artist_name)
        artist.set_size_request(LAYOUT["artist_width"], -1)
        artist.set_max_width_chars(16)
        artist.set_margin_end(LAYOUT["cell_margin_end"])
        box.append(artist)
        album_name = getattr(getattr(t, "album", None), "name", "Unknown Album")
        alb = Gtk.Label(label=album_name, xalign=0, ellipsize=3, css_classes=["dim-label", "track-album"])
        alb.set_tooltip_text(album_name)
        alb.set_size_request(LAYOUT["album_width"], -1)
        alb.set_max_width_chars(16)
        alb.set_margin_end(LAYOUT["cell_margin_end"])
        box.append(alb)
        dur = int(getattr(t, "duration", 0) or 0)
        if dur > 0:
            m, s = divmod(dur, 60)
            d = Gtk.Label(label=f"{m}:{s:02d}", xalign=1, css_classes=["dim-label", "track-duration"])
            d.set_attributes(Pango.AttrList.from_string("font-features 'tnum=1'"))
            d.set_size_request(LAYOUT["time_width"], -1)
            box.append(d)
        fav_btn = app.create_track_fav_button(t)
        box.append(fav_btn)
        if edit_mode:
            drag_hint = Gtk.Image.new_from_icon_name("open-menu-symbolic")
            drag_hint.add_css_class("dim-label")
            box.append(drag_hint)
            rm_btn = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat", "playlist-tool-btn"])
            rm_btn.set_tooltip_text("Remove from Playlist")
            rm_btn.connect("clicked", lambda _b, pid=p.get("id"), idx=i: app.on_playlist_remove_track_clicked(pid, idx))
            box.append(rm_btn)
        else:
            # Keep identical row height/footprint with album rows by reserving a hidden action button slot.
            ghost_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat", "circular", "history-scroll-btn", "ghost-row-btn"])
            ghost_btn.set_sensitive(False)
            ghost_btn.set_focusable(False)
            box.append(ghost_btn)
        row.set_child(box)

        if edit_mode:
            drag_source = Gtk.DragSource.new()
            drag_source.set_actions(Gdk.DragAction.MOVE)
            drag_source.connect("prepare", lambda _src, _x, _y, idx=i: Gdk.ContentProvider.new_for_value(str(idx)))
            row.add_controller(drag_source)

            drop_target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)

            def _on_drop(_target, value, _x, _y, dst=i, pid=p.get("id")):
                try:
                    src = int(str(value))
                except Exception:
                    return False
                app.on_playlist_reorder_track(pid, src, dst)
                return True

            drop_target.connect("drop", _on_drop)
            row.add_controller(drop_target)

        return row

    render_token = int(getattr(app, "_playlist_detail_render_token", 0) or 0) + 1
    app._playlist_detail_render_token = render_token
    app._playlist_detail_tracks_total = len(tracks)
    app._playlist_detail_loaded_count = 0

    try:
        old_vadj = getattr(app, "_playlist_lazy_vadj", None)
        old_handler = int(getattr(app, "_playlist_lazy_handler_id", 0) or 0)
        if old_vadj is not None and old_handler:
            old_vadj.disconnect(old_handler)
    except Exception:
        pass
    app._playlist_lazy_vadj = None
    app._playlist_lazy_handler_id = 0

    initial_rows = 20
    chunk_rows = 40

    def _append_playlist_rows(limit):
        if int(getattr(app, "_playlist_detail_render_token", 0) or 0) != render_token:
            return False
        start = int(getattr(app, "_playlist_detail_loaded_count", 0) or 0)
        end = min(len(tracks), start + int(limit))
        for i in range(start, end):
            list_box.append(_build_playlist_row(i, tracks[i]))
        app._playlist_detail_loaded_count = end
        if hasattr(app, "_update_track_list_icon"):
            app._update_track_list_icon(list_box)
        return end < len(tracks)

    def _maybe_load_more(_adj=None):
        if int(getattr(app, "_playlist_detail_render_token", 0) or 0) != render_token:
            return
        vadj = app.alb_scroll.get_vadjustment() if getattr(app, "alb_scroll", None) is not None else None
        if vadj is None:
            return
        # Keep first screen fixed at 20 rows; only start lazy loading after user scrolls.
        if float(vadj.get_value()) <= 1.0:
            return
        remain = float(vadj.get_upper()) - (float(vadj.get_value()) + float(vadj.get_page_size()))
        if remain <= 280:
            has_more = _append_playlist_rows(chunk_rows)
            if not has_more:
                try:
                    handler_id = int(getattr(app, "_playlist_lazy_handler_id", 0) or 0)
                    if handler_id:
                        vadj.disconnect(handler_id)
                except Exception:
                    pass
                app._playlist_lazy_vadj = None
                app._playlist_lazy_handler_id = 0

    _append_playlist_rows(initial_rows)
    vadj = app.alb_scroll.get_vadjustment() if getattr(app, "alb_scroll", None) is not None else None
    if vadj is not None and app._playlist_detail_loaded_count < len(tracks):
        app._playlist_lazy_vadj = vadj
        app._playlist_lazy_handler_id = vadj.connect("value-changed", _maybe_load_more)

    detail_box.append(list_box)


def render_daily_mixes(app, mixes):
    _clear_container(app.collection_content_box)

    if not mixes:
        empty = Gtk.Label(
            label="No enough play history yet. Play more tracks and come back tomorrow.",
            xalign=0,
            css_classes=["dim-label"],
            margin_start=8,
            margin_top=8,
        )
        app.collection_content_box.append(empty)
        return

    for mix in mixes:
        tracks = list(mix.get("tracks", []))
        if not tracks:
            continue

        section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
        head = Gtk.Box(spacing=8, css_classes=["home-section-head"])
        collage = Gtk.Image(pixel_size=42, css_classes=["playlist-cover-thumb", "album-cover-img"])
        cover_refs = []
        for t in tracks:
            u = app.backend.get_artwork_url(t, 320)
            if u:
                cover_refs.append(u)
            if len(cover_refs) >= 4:
                break
        collage_dir = os.path.join(app.cache_dir, "playlist_covers")
        collage_path = utils.generate_auto_collage_cover(
            cover_refs,
            image_cache_dir=app.cache_dir,
            collage_cache_dir=collage_dir,
            key_prefix=f"daily_mix_{mix.get('date_label', 'today')}",
            size=256,
        )
        if collage_path:
            utils.load_img(collage, collage_path, app.cache_dir, 42)
        head.append(collage)
        title = Gtk.Label(
            label=f"{mix.get('title', 'Daily Mix')} · {mix.get('date_label', '')}",
            xalign=0,
            hexpand=True,
            css_classes=["home-section-title"],
        )
        count = Gtk.Label(label=f"{len(tracks)} tracks", css_classes=["home-section-count"])
        head.append(title)
        head.append(count)
        section_box.append(head)

        flow = Gtk.FlowBox(
            valign=Gtk.Align.START,
            max_children_per_line=30,
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=20,
            row_spacing=20,
            css_classes=["home-flow", "daily-mix-flow"],
        )
        flow.daily_tracks = tracks
        flow.connect("child-activated", app.on_daily_mix_item_activated)

        for i, t in enumerate(tracks):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=_feed_card_classes("daily-mix-card"))
            img = Gtk.Image(pixel_size=120, css_classes=["album-cover-img"])
            cover_url = app.backend.get_artwork_url(t, 320)
            if cover_url:
                utils.load_img(img, cover_url, app.cache_dir, 120)
            else:
                img.set_from_icon_name("audio-x-generic-symbolic")
            card.append(_build_feed_media_overlay(img, 120, "album-cover-img"))

            title_lbl = Gtk.Label(
                label=getattr(t, "name", "Unknown Track"),
                xalign=0.5,
                halign=Gtk.Align.CENTER,
                ellipsize=3,
                wrap=True,
                max_width_chars=14,
                css_classes=["home-card-title"],
            )
            card.append(title_lbl)

            artist_name = getattr(getattr(t, "artist", None), "name", "Unknown")
            artist_lbl = Gtk.Label(
                label=artist_name,
                xalign=0.5,
                halign=Gtk.Align.CENTER,
                ellipsize=3,
                max_width_chars=16,
                css_classes=["dim-label", "home-card-subtitle"],
            )
            card.append(artist_lbl)

            child = Gtk.FlowBoxChild()
            child.daily_track_index = i
            child.set_child(card)
            flow.append(child)

        section_box.append(flow)
        app.collection_content_box.append(section_box)
