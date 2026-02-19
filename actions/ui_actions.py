from threading import Thread
import logging
import os
import random
from datetime import datetime
import subprocess

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango, Gdk, GObject

import utils
from ui.track_table import LAYOUT, build_tracks_header, append_header_action_spacers
from app_errors import classify_exception, user_message

logger = logging.getLogger(__name__)
MAX_SEARCH_HISTORY = 10

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


def _populate_queue_rows(app, list_box, tracks, current_idx, compact=False):
    _clear_container(list_box)
    for i, t in enumerate(tracks):
        row = Gtk.ListBoxRow(css_classes=["track-row"])
        row.queue_track_index = i
        row.track_id = getattr(t, "id", None)

        row_margin_y = 1 if compact else LAYOUT["row_margin_y"]
        col_gap = 5 if compact else LAYOUT["col_gap"]
        row_margin_x = 0 if compact else LAYOUT["row_margin_x"]
        idx_width = 14 if compact else LAYOUT["index_width"]
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
        idx = Gtk.Label(label=str(i + 1), css_classes=["dim-label"])
        stack.add_named(idx, "num")
        icon = Gtk.Image(icon_name="media-playback-start-symbolic")
        icon.add_css_class("accent")
        stack.add_named(icon, "icon")
        stack.set_visible_child_name("icon" if i == current_idx else "num")
        box.append(stack)

        title = getattr(t, "name", "Unknown Track")
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
            else:
                box.append(Gtk.Box(width_request=LAYOUT["time_width"]))

        fav_btn = app.create_track_fav_button(t)
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
        list_box.append(row)


def render_search_history(app):
    if not hasattr(app, "search_history_section") or not hasattr(app, "search_history_flow"):
        return

    _clear_container(app.search_history_flow)
    history = list(getattr(app, "search_history", []))
    if not history:
        app.search_history_section.set_visible(False)
        return

    for query in history:
        btn = Gtk.Button(label=query, css_classes=["flat"])
        btn.connect("clicked", lambda _b, q=query: _run_search(app, q))
        child = Gtk.FlowBoxChild()
        child.set_child(btn)
        app.search_history_flow.append(child)

    app.search_history_section.set_visible(not app.search_entry.get_text().strip())


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
        app.res_hist_box.set_visible(False)
        app.res_trk_box.set_visible(False)
        render_search_history(app)
        return

    app.search_history_section.set_visible(False)

    def _debounced():
        app._search_debounce_source = 0
        _run_search(app, q)
        return False

    app._search_debounce_source = GLib.timeout_add(300, _debounced)


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

    query_variants = _generate_search_variants(q)
    if not query_variants:
        query_variants = [q]

    _remember_query(app, q)
    app.nav_history.clear()
    app.right_stack.set_visible_child_name("search_view")
    if hasattr(app, "_remember_last_view"):
        app._remember_last_view("search_view")
    app.nav_list.select_row(None)
    app.back_btn.set_sensitive(True)
    app.search_history_section.set_visible(False)
    set_search_status(app, "Searching...")
    app._search_request_id = getattr(app, "_search_request_id", 0) + 1
    request_id = app._search_request_id
    local_results = _build_local_search_results(app, query_variants)

    _clear_container(app.res_art_flow)
    _clear_container(app.res_alb_flow)
    _clear_container(app.res_pl_flow)
    _clear_container(app.res_hist_list)
    _clear_container(app.res_trk_list)

    app.res_art_box.set_visible(False)
    app.res_alb_box.set_visible(False)
    app.res_pl_box.set_visible(False)
    app.res_hist_box.set_visible(False)
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
    history_tracks = res.get("history_tracks", [])
    if artists or albums or tracks or playlists or history_tracks:
        set_search_status(app, None)
    else:
        set_search_status(app, "No results found.")

    logger.info(
        "Rendering search results: %s artists, %s albums, %s playlists, %s history tracks, %s tracks",
        len(artists),
        len(albums),
        len(playlists),
        len(history_tracks),
        len(tracks),
    )

    app.res_art_box.set_visible(bool(artists))
    for art in artists:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "home-card"])
        img = Gtk.Image(pixel_size=100, css_classes=["circular-avatar"])
        url = app.backend.get_artist_artwork_url(art, 320)
        logger.debug("Artist '%s' image URL: %s", getattr(art, "name", "Unknown"), url)
        utils.load_img(img, url, app.cache_dir, 100)
        card.append(img)
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
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "home-card"])
        img = Gtk.Image(pixel_size=110, css_classes=["album-cover-img"])
        url = app.backend.get_artwork_url(alb, 320)
        alb_title = getattr(alb, "title", getattr(alb, "name", "Unknown Album"))
        logger.debug("Album '%s' image URL: %s", alb_title, url)
        utils.load_img(img, url, app.cache_dir, 110)
        card.append(img)
        card.append(Gtk.Label(label=alb_title, ellipsize=2, wrap=True, max_width_chars=14, css_classes=["home-card-title"]))
        child = Gtk.FlowBoxChild()
        child.set_child(card)
        child.data_item = {"obj": alb, "type": "Album"}
        app.res_alb_flow.append(child)

    app.res_pl_box.set_visible(bool(playlists))
    for p in playlists:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "home-card"])
        img = Gtk.Image(css_classes=["album-cover-img", "playlist-cover-img"])
        img.set_size_request(110, 110)
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
            utils.load_img(img, collage, app.cache_dir, 110)
        else:
            img.set_pixel_size(110)
            img.set_from_icon_name("audio-x-generic-symbolic")
        card.append(img)
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
        btn = Gtk.Button(css_classes=["flat", "history-card-btn"])
        btn.set_child(card)
        btn.connect("clicked", lambda _b, pid=p.get("id"): app.on_playlist_card_clicked(pid))
        child = Gtk.FlowBoxChild()
        child.set_child(btn)
        app.res_pl_flow.append(child)

    app.res_hist_box.set_visible(bool(history_tracks))
    app.search_history_track_data = history_tracks
    for t in history_tracks:
        row_box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        img = Gtk.Image(pixel_size=48, css_classes=["album-cover-img"])
        cover = app.backend.get_artwork_url(t, 80)
        if not cover:
            cover = getattr(t, "cover", None)
        if not cover:
            cover = getattr(getattr(t, "album", None), "cover", None)
        if cover:
            utils.load_img(img, cover, app.cache_dir, 48)
        else:
            img.set_from_icon_name("audio-x-generic-symbolic")
        row_box.append(img)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        track_name = getattr(t, "name", "Unknown")
        info.append(Gtk.Label(label=track_name, xalign=0, ellipsize=3, css_classes=["heading", "track-title"]))
        artist_name = getattr(getattr(t, "artist", None), "name", "Unknown")
        info.append(Gtk.Label(label=artist_name, xalign=0, css_classes=["dim-label", "track-artist"]))
        row_box.append(info)

        dur_sec = int(getattr(t, "duration", 0) or 0)
        if dur_sec > 0:
            m, s = divmod(dur_sec, 60)
            dur_str = f"{m}:{s:02d}"
            lbl_dur = Gtk.Label(label=dur_str, xalign=1, css_classes=["dim-label", "track-duration"])
            lbl_dur.set_attributes(Pango.AttrList.from_string("font-features 'tnum=1'"))
            lbl_dur.set_size_request(64, -1)
            row_box.append(Gtk.Box(hexpand=True))
            row_box.append(lbl_dur)
        else:
            row_box.append(Gtk.Box(hexpand=True))

        add_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
        add_btn.set_tooltip_text("Add to Playlist")
        add_btn.connect("clicked", lambda _b, tr=t: app.on_add_single_track_to_playlist(tr))
        fav_btn = app.create_track_fav_button(t)
        row_box.append(fav_btn)
        row_box.append(add_btn)

        lb_row = Gtk.ListBoxRow()
        lb_row.add_css_class("track-row")
        lb_row.set_child(row_box)
        app.res_hist_list.append(lb_row)

    app.res_trk_box.set_visible(bool(tracks))
    app.search_track_data = tracks
    for idx, t in enumerate(tracks):
        row_box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        sel_cb = Gtk.CheckButton()
        sel_cb.set_valign(Gtk.Align.CENTER)
        sel_cb.connect("toggled", lambda cb, i=idx: app.on_search_track_checkbox_toggled(cb, i, cb.get_active()))
        row_box.append(sel_cb)
        img = Gtk.Image(pixel_size=48, css_classes=["album-cover-img"])
        url = app.backend.get_artwork_url(t, 80)
        utils.load_img(img, url, app.cache_dir, 48)
        row_box.append(img)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        info.append(Gtk.Label(label=getattr(t, "name", "Unknown"), xalign=0, ellipsize=3, css_classes=["heading", "track-title"]))
        artist_name = getattr(t.artist, "name", "Unknown") if hasattr(t, "artist") else "Unknown"
        info.append(Gtk.Label(label=artist_name, xalign=0, css_classes=["dim-label", "track-artist"]))
        row_box.append(info)

        dur_sec = getattr(t, "duration", 0)
        if dur_sec:
            m, s = divmod(dur_sec, 60)
            dur_str = f"{m}:{s:02d}"
            lbl_dur = Gtk.Label(label=dur_str, xalign=1, css_classes=["dim-label", "track-duration"])
            lbl_dur.set_attributes(Pango.AttrList.from_string("font-features 'tnum=1'"))
            lbl_dur.set_size_request(64, -1)
            row_box.append(Gtk.Box(hexpand=True))
            row_box.append(lbl_dur)
        else:
            row_box.append(Gtk.Box(hexpand=True))

        add_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
        add_btn.set_tooltip_text("Add to Playlist")
        add_btn.connect("clicked", lambda _b, tr=t: app.on_add_single_track_to_playlist(tr))
        fav_btn = app.create_track_fav_button(t)
        row_box.append(fav_btn)
        row_box.append(add_btn)

        lb_row = Gtk.ListBoxRow()
        lb_row.add_css_class("track-row")
        lb_row.set_child(row_box)
        app.res_trk_list.append(lb_row)

    logger.debug("Search rendering complete")


def show_album_details(app, alb):
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

    artist_name = "Various Artists"
    if hasattr(alb, "artist") and alb.artist:
        artist_name = alb.artist.name if hasattr(alb.artist, "name") else str(alb.artist)
    app.header_artist.set_text(artist_name)
    app.header_artist.set_tooltip_text(artist_name)

    utils.load_img(app.header_art, lambda: app.backend.get_artwork_url(alb, 640), app.cache_dir, 160)
    is_fav = app.backend.is_favorite(getattr(alb, "id", ""))
    app._update_fav_icon(app.fav_btn, is_fav)

    while c := app.track_list.get_first_child():
        app.track_list.remove(c)
    app.album_sort_field = None
    app.album_sort_asc = True
    if hasattr(app, "_update_album_sort_headers"):
        app._update_album_sort_headers()

    def detail_task():
        ts = app.backend.get_tracks(alb)
        desc = ""
        if hasattr(alb, "release_date") and alb.release_date:
            desc += str(alb.release_date.year)
        elif hasattr(alb, "last_updated"):
            desc += "Updated Recently"
        count = len(ts) if ts else 0
        if count > 0:
            desc += f"  •  {count} Tracks"
        GLib.idle_add(lambda: app.header_meta.set_text(desc.strip(" • ")))
        GLib.idle_add(app.load_album_tracks, ts)

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

        add_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
        add_btn.set_tooltip_text("Add to Playlist")
        add_btn.connect("clicked", lambda _b, tr=t: app.on_add_single_track_to_playlist(tr))
        fav_btn = app.create_track_fav_button(t)
        box.append(fav_btn)
        box.append(add_btn)

        row.set_child(box)
        app.track_list.append(row)

    if hasattr(app, "_update_track_list_icon"):
        app._update_track_list_icon()


def batch_load_albums(app, albs, batch=6):
    if not albs:
        return False
    curr, rem = albs[:batch], albs[batch:]
    for alb in curr:
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "home-card"])
        img = Gtk.Image(css_classes=["album-cover-img"])
        utils.load_img(img, lambda a=alb: app.backend.get_artwork_url(a, 640), app.cache_dir, 130)
        v.append(img)
        v.append(
            Gtk.Label(
                label=alb.name,
                ellipsize=3,
                halign=Gtk.Align.CENTER,
                wrap=True,
                max_width_chars=16,
                css_classes=["home-card-title"],
            )
        )
        c = Gtk.FlowBoxChild()
        c.set_child(v)
        c.data_item = {"obj": alb, "type": "Album"}
        app.main_flow.append(c)
    if rem:
        GLib.timeout_add(50, app.batch_load_albums, rem, batch)
    return False


def batch_load_artists(app, artists, batch=10):
    if not artists:
        return False
    curr, rem = artists[:batch], artists[batch:]
    for art in curr:
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "home-card"])
        img = Gtk.Image(pixel_size=120, css_classes=["circular-avatar"])
        utils.load_img(img, lambda a=art: app.backend.get_artist_artwork_url(a, 320), app.cache_dir, 120)
        v.append(img)
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
        app.main_flow.append(c)
    if rem:
        GLib.timeout_add(50, app.batch_load_artists, rem, batch)
    return False


def batch_load_home(app, sections):
    if not sections:
        return

    def _scroll_h(scroller, direction=1):
        adj = scroller.get_hadjustment()
        if adj is None:
            return
        page = max(120.0, float(adj.get_page_size()) * 0.85)
        target = adj.get_value() + (page * direction)
        lower = float(adj.get_lower())
        upper = float(adj.get_upper()) - float(adj.get_page_size())
        if target < lower:
            target = lower
        if target > upper:
            target = upper
        adj.set_value(target)

    def _open_item(item_data):
        if not item_data:
            return
        obj = item_data.get("obj")
        typ = item_data.get("type")
        if typ == "Track":
            app._play_single_track(obj)
            return
        if typ == "Artist":
            app.on_artist_clicked(obj)
            return
        app.show_album_details(obj)

    for sec in sections:
        section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section"])
        section_head = Gtk.Box(spacing=8, css_classes=["home-section-head"])
        section_title = Gtk.Label(label=sec["title"], xalign=0, hexpand=True, css_classes=["home-section-title"])
        section_count = Gtk.Label(label=f"{len(sec['items'])} items", css_classes=["home-section-count"])
        left_btn = Gtk.Button(icon_name="go-previous-symbolic", css_classes=["flat", "circular", "home-scroll-btn"])
        right_btn = Gtk.Button(icon_name="go-next-symbolic", css_classes=["flat", "circular", "home-scroll-btn"])
        section_head.append(section_title)
        section_head.append(section_count)
        section_head.append(left_btn)
        section_head.append(right_btn)
        section_box.append(section_head)

        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=False, css_classes=["home-row-scroller"])
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        grid = Gtk.Grid(column_spacing=20, row_spacing=20)
        scroller.set_child(grid)
        left_btn.connect("clicked", lambda _b: _scroll_h(scroller, -1))
        right_btn.connect("clicked", lambda _b: _scroll_h(scroller, 1))
        _bind_horizontal_scroll_buttons(scroller, left_btn, right_btn)
        section_box.append(scroller)
        app.collection_content_box.append(section_box)

        for i, item_data in enumerate(sec["items"]):
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "home-card"])
            img_size = 130
            img_cls = "album-cover-img"
            if item_data["type"] == "Track":
                img_size = 88
                v.add_css_class("home-track-card")
            elif item_data["type"] == "Artist" or "Radio" in item_data["name"]:
                img_size = 120
                img_cls = "circular-avatar"
            img = Gtk.Image(pixel_size=img_size, css_classes=[img_cls])
            if item_data["image_url"]:
                utils.load_img(img, item_data["image_url"], app.cache_dir, img_size)
            else:
                img.set_from_icon_name("audio-x-generic-symbolic")
            v.append(img)
            v.append(
                Gtk.Label(
                    label=item_data["name"],
                    ellipsize=2,
                    halign=Gtk.Align.CENTER,
                    wrap=True,
                    max_width_chars=16,
                    css_classes=["heading", "home-card-title"],
                )
            )
            if item_data["sub_title"]:
                v.append(
                    Gtk.Label(
                        label=item_data["sub_title"],
                        ellipsize=1,
                        halign=Gtk.Align.CENTER,
                        css_classes=["caption", "dim-label", "home-card-subtitle"],
                    )
                )
            btn = Gtk.Button(css_classes=["flat", "history-card-btn"])
            btn.set_child(v)
            btn.connect("clicked", lambda _b, d=item_data: _open_item(d))
            grid.attach(btn, i // 2, i % 2, 1, 1)


def render_history_dashboard(app):
    _clear_container(app.collection_content_box)

    recent_albums = app.history_mgr.get_albums() if hasattr(app, "history_mgr") else []
    top_tracks = app.history_mgr.get_top_tracks(limit=20) if hasattr(app, "history_mgr") else []

    def _scroll_h(scroller, direction=1):
        adj = scroller.get_hadjustment()
        if adj is None:
            return
        page = max(120.0, float(adj.get_page_size()) * 0.85)
        target = adj.get_value() + (page * direction)
        lower = float(adj.get_lower())
        upper = float(adj.get_upper()) - float(adj.get_page_size())
        if target < lower:
            target = lower
        if target > upper:
            target = upper
        adj.set_value(target)

    def _build_two_row_section(title_text, count_text):
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section", "history-section"])
        head = Gtk.Box(spacing=8, css_classes=["home-section-head"])
        head.append(Gtk.Label(label=title_text, xalign=0, hexpand=True, css_classes=["home-section-title"]))
        head.append(Gtk.Label(label=count_text, css_classes=["home-section-count"]))
        left_btn = Gtk.Button(icon_name="go-previous-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
        right_btn = Gtk.Button(icon_name="go-next-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
        head.append(left_btn)
        head.append(right_btn)
        section.append(head)
        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=False, css_classes=["history-row-scroller"])
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        grid = Gtk.Grid(column_spacing=16, row_spacing=16)
        scroller.set_child(grid)
        left_btn.connect("clicked", lambda _b: _scroll_h(scroller, -1))
        right_btn.connect("clicked", lambda _b: _scroll_h(scroller, 1))
        _bind_horizontal_scroll_buttons(scroller, left_btn, right_btn)
        section.append(scroller)
        return section, grid

    sec_top, grid_top = _build_two_row_section("Top 20 Most Played Tracks", f"{len(top_tracks)} tracks")
    for i, tr in enumerate(top_tracks):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "home-card", "history-card", "history-track-card"])
        cover_overlay = Gtk.Overlay()
        img = Gtk.Image(pixel_size=88, css_classes=["album-cover-img"])
        cover = app.backend.get_artwork_url(tr, 320)
        if not cover:
            cover = getattr(tr, "cover", None)
        if not cover:
            cover = getattr(getattr(tr, "album", None), "cover", None)
        if cover:
            utils.load_img(img, cover, app.cache_dir, 88)
        else:
            img.set_from_icon_name("audio-x-generic-symbolic")
        cover_overlay.set_child(img)
        rank_badge = Gtk.Label(label=str(i + 1), css_classes=["history-rank-badge"])
        rank_badge.set_halign(Gtk.Align.START)
        rank_badge.set_valign(Gtk.Align.START)
        rank_badge.set_margin_start(6)
        rank_badge.set_margin_top(6)
        cover_overlay.add_overlay(rank_badge)
        play_count = int(getattr(tr, "play_count", 0) or 0)
        count_badge = Gtk.Label(label=f"x{play_count}", css_classes=["history-play-count-badge"])
        count_badge.set_halign(Gtk.Align.END)
        count_badge.set_valign(Gtk.Align.END)
        count_badge.set_margin_end(6)
        count_badge.set_margin_bottom(6)
        cover_overlay.add_overlay(count_badge)
        card.append(cover_overlay)

        track_name = getattr(tr, "name", "Unknown Track")
        artist_name = getattr(getattr(tr, "artist", None), "name", "Unknown")
        card.append(
            Gtk.Label(
                label=track_name,
                halign=Gtk.Align.CENTER,
                ellipsize=3,
                wrap=True,
                max_width_chars=16,
                css_classes=["home-card-title"],
            )
        )
        card.append(
            Gtk.Label(
                label=artist_name,
                halign=Gtk.Align.CENTER,
                ellipsize=3,
                wrap=True,
                max_width_chars=16,
                css_classes=["dim-label", "home-card-subtitle"],
            )
        )
        btn = Gtk.Button(css_classes=["flat", "history-card-btn"])
        btn.set_child(card)
        btn.connect("clicked", lambda _b, idx=i: app.on_history_track_clicked(top_tracks, idx))
        grid_top.attach(btn, i // 2, i % 2, 1, 1)
    app.collection_content_box.append(sec_top)

    sec_recent, grid_recent = _build_two_row_section("Recently Played Albums", f"{len(recent_albums)} items")
    for i, alb in enumerate(recent_albums):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "home-card", "history-card"])
        img = Gtk.Image(pixel_size=120, css_classes=["album-cover-img"])
        cover = app.backend.get_artwork_url(alb, 320)
        if cover:
            utils.load_img(img, cover, app.cache_dir, 120)
        else:
            img.set_from_icon_name("audio-x-generic-symbolic")
        card.append(img)
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
        btn = Gtk.Button(css_classes=["flat", "history-card-btn"])
        btn.set_child(card)
        btn.connect("clicked", lambda _b, a=alb: app.on_history_album_clicked(a))
        grid_recent.attach(btn, i // 2, i % 2, 1, 1)
    app.collection_content_box.append(sec_recent)


def render_collection_dashboard(app, favorite_tracks=None, favorite_albums=None):
    _clear_container(app.collection_content_box)
    app.playlist_track_list = None
    app.queue_track_list = None

    albums = list(favorite_albums or [])

    def _scroll_h(scroller, direction=1):
        adj = scroller.get_hadjustment()
        if adj is None:
            return
        page = max(120.0, float(adj.get_page_size()) * 0.85)
        target = adj.get_value() + (page * direction)
        lower = float(adj.get_lower())
        upper = float(adj.get_upper()) - float(adj.get_page_size())
        if target < lower:
            target = lower
        if target > upper:
            target = upper
        adj.set_value(target)

    def _build_two_row_section(title_text, count_text):
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section", "history-section"])
        head = Gtk.Box(spacing=8, css_classes=["home-section-head"])
        head.append(Gtk.Label(label=title_text, xalign=0, hexpand=True, css_classes=["home-section-title"]))
        head.append(Gtk.Label(label=count_text, css_classes=["home-section-count"]))
        left_btn = Gtk.Button(icon_name="go-previous-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
        right_btn = Gtk.Button(icon_name="go-next-symbolic", css_classes=["flat", "circular", "history-scroll-btn"])
        head.append(left_btn)
        head.append(right_btn)
        section.append(head)
        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=False, css_classes=["history-row-scroller"])
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        grid = Gtk.Grid(column_spacing=16, row_spacing=16)
        scroller.set_child(grid)
        left_btn.connect("clicked", lambda _b: _scroll_h(scroller, -1))
        right_btn.connect("clicked", lambda _b: _scroll_h(scroller, 1))
        _bind_horizontal_scroll_buttons(scroller, left_btn, right_btn)
        section.append(scroller)
        return section, grid

    sec_albums, grid_albums = _build_two_row_section("Saved Albums", f"{len(albums)} items")
    for i, alb in enumerate(albums):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "home-card", "history-card"])
        img = Gtk.Image(pixel_size=120, css_classes=["album-cover-img"])
        cover = app.backend.get_artwork_url(alb, 320)
        if cover:
            utils.load_img(img, cover, app.cache_dir, 120)
        else:
            img.set_from_icon_name("audio-x-generic-symbolic")
        card.append(img)
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
        btn = Gtk.Button(css_classes=["flat", "history-card-btn"])
        btn.set_child(card)
        btn.connect("clicked", lambda _b, a=alb: app.on_history_album_clicked(a))
        grid_albums.attach(btn, i // 2, i % 2, 1, 1)
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
    _clear_container(app.collection_content_box)
    app.playlist_track_list = None
    app.queue_track_list = None

    all_tracks = list(tracks or [])
    if hasattr(app, "grid_subtitle_label") and app.grid_subtitle_label is not None:
        app.grid_subtitle_label.set_text(f"{len(all_tracks)} Liked Songs")
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
    play_next_btn = Gtk.Button(label="Play next", css_classes=["flat", "liked-action-btn"])
    play_next_btn.set_tooltip_text("Queue current liked songs to play next")
    toolbar.append(play_next_btn)
    app.collection_content_box.append(toolbar)

    pager_bar = Gtk.Box(spacing=8, margin_start=0, margin_end=0, margin_bottom=8)
    prev_page_btn = Gtk.Button(label="Prev", css_classes=["flat", "liked-action-btn"])
    next_page_btn = Gtk.Button(label="Next", css_classes=["flat", "liked-action-btn"])
    page_info_lbl = Gtk.Label(label="", css_classes=["dim-label"], xalign=0)
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
    pager_bar.append(prev_page_btn)
    pager_bar.append(next_page_btn)
    pager_bar.append(page_info_lbl)
    pager_bar.append(Gtk.Box(hexpand=True))
    pager_bar.append(artist_scroll_prev_btn)
    pager_bar.append(artist_scroll_next_btn)
    app.collection_content_box.append(pager_bar)

    artist_groups = {}

    def _artist_key(artist_obj):
        aid = getattr(artist_obj, "id", None)
        if aid is not None:
            return f"id:{aid}"
        name = str(getattr(artist_obj, "name", "Unknown") or "Unknown").strip().lower()
        return f"name:{name}"

    for t in all_tracks:
        artist_obj = getattr(t, "artist", None)
        key = _artist_key(artist_obj)
        if key not in artist_groups:
            artist_groups[key] = {
                "key": key,
                "artist": artist_obj,
                "name": str(getattr(artist_obj, "name", "Unknown") or "Unknown"),
                "count": 0,
            }
        artist_groups[key]["count"] += 1

    artist_items = sorted(
        artist_groups.values(),
        key=lambda it: (-int(it.get("count", 0) or 0), str(it.get("name", "")).lower()),
    )

    artist_filter_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    artist_filter_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=False, css_classes=["liked-artist-filter-scroll"])
    artist_filter_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
    artist_filter_scroll.set_min_content_height(90)
    artist_filter_flow = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=10,
        css_classes=["liked-artist-filter-flow"],
    )
    artist_filter_scroll.set_child(artist_filter_flow)

    artist_filter_row.append(artist_filter_scroll)
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
        img.set_size_request(54, 54)
        img.set_pixel_size(54)
        img.set_from_icon_name("avatar-default-symbolic")
        if artist_obj is not None:
            utils.load_img(
                img,
                lambda a=artist_obj: app.backend.get_artist_artwork_url(a, 320),
                app.cache_dir,
                54,
            )
        overlay.set_child(img)

        badge = Gtk.Label(label=str(count), css_classes=["liked-artist-count-badge"])
        badge.set_halign(Gtk.Align.END)
        badge.set_valign(Gtk.Align.END)
        overlay.add_overlay(badge)
        card.append(overlay)
        card.append(Gtk.Label(label=name, css_classes=["dim-label"], max_width_chars=12, ellipsize=3))

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
    play_next_btn.connect("clicked", lambda _b: _queue_liked_tracks_next(getattr(list_box, "liked_tracks", [])))

    def _apply_filters():
        q = str(getattr(app, "liked_tracks_query", "") or "").strip().lower()
        mode = getattr(app, "liked_tracks_sort", "recent")
        artist_filter = getattr(app, "liked_tracks_artist_filter", None)
        filtered = list(all_tracks)
        if artist_filter:
            filtered = [t for t in filtered if _artist_key(getattr(t, "artist", None)) == artist_filter]
        if q:
            def _match(t):
                title = str(getattr(t, "name", "") or "").lower()
                artist = str(getattr(getattr(t, "artist", None), "name", "") or "").lower()
                album = str(getattr(getattr(t, "album", None), "name", "") or "").lower()
                return q in title or q in artist or q in album
            filtered = [t for t in filtered if _match(t)]

        if mode == "title":
            filtered.sort(key=lambda t: str(getattr(t, "name", "") or "").lower())
        elif mode == "artist":
            filtered.sort(key=lambda t: str(getattr(getattr(t, "artist", None), "name", "") or "").lower())
        elif mode == "album":
            filtered.sort(key=lambda t: str(getattr(getattr(t, "album", None), "name", "") or "").lower())
        elif mode == "duration":
            filtered.sort(key=lambda t: int(getattr(t, "duration", 0) or 0))
        # recent => keep backend order

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
        play_next_btn.set_sensitive(bool(filtered))
        prev_page_btn.set_sensitive(page > 0)
        next_page_btn.set_sensitive(page < (total_pages - 1))
        if total > 0:
            page_info_lbl.set_text(f"Page {page + 1}/{total_pages}  ({start + 1}-{end} of {total})")
        else:
            page_info_lbl.set_text("Page 1/1  (0 songs)")

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
            fav_btn.connect("clicked", lambda _b: GLib.timeout_add(260, app.refresh_liked_songs_dashboard))
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

    _clear_container(list_box)
    if not tracks:
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
    if hasattr(app, "_update_track_list_icon"):
        app._update_track_list_icon(target_list=list_box)


def render_playlists_home(app):
    _clear_container(app.collection_content_box)
    app.playlist_track_list = None

    top = Gtk.Box(spacing=8, css_classes=["home-section-head"], margin_start=6, margin_end=6, margin_bottom=8)
    top.append(Gtk.Label(label="Playlists", xalign=0, hexpand=True, css_classes=["home-section-title"]))
    create_btn = Gtk.Button(icon_name="list-add-symbolic", css_classes=["playlist-add-top-btn"])
    create_btn.set_tooltip_text("Create Local Playlist")
    create_btn.connect("clicked", app.on_create_playlist_clicked)
    top.append(create_btn)
    app.collection_content_box.append(top)

    local_head = Gtk.Box(spacing=8, css_classes=["home-section-head"], margin_start=6, margin_end=6, margin_bottom=8, margin_top=6)
    local_head.append(Gtk.Label(label="Local Playlists", xalign=0, hexpand=True, css_classes=["home-section-title"]))
    app.collection_content_box.append(local_head)

    section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["home-section", "home-generic-section"])
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

    playlists = app.playlist_mgr.list_playlists() if hasattr(app, "playlist_mgr") else []
    for p in playlists:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "home-card"])
        img = Gtk.Image(css_classes=["album-cover-img", "playlist-cover-img"])
        img.set_size_request(130, 130)
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
            utils.load_img(img, collage, app.cache_dir, 130)
        else:
            img.set_pixel_size(130)
            img.set_from_icon_name("audio-x-generic-symbolic")
        card.append(img)
        card.append(
            Gtk.Label(
                label=p.get("name", "Untitled Playlist"),
                ellipsize=3,
                halign=Gtk.Align.CENTER,
                wrap=True,
                max_width_chars=16,
                css_classes=["home-card-title"],
            )
        )
        btn = Gtk.Button(css_classes=["flat", "history-card-btn"])
        btn.set_child(card)
        btn.connect("clicked", lambda _b, pid=p.get("id"): app.on_playlist_card_clicked(pid))
        child = Gtk.FlowBoxChild()
        child.set_child(btn)
        flow.append(child)

    if not playlists:
        hint = Gtk.Label(label="No local playlists yet. Click New Playlist to create one.", xalign=0, css_classes=["dim-label"], margin_start=8, margin_top=8)
        app.collection_content_box.append(hint)


def render_playlist_detail(app, playlist_id):
    _clear_container(app.collection_content_box)
    p = app.playlist_mgr.get_playlist(playlist_id) if hasattr(app, "playlist_mgr") else None
    if not p:
        render_playlists_home(app)
        return
    detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    app.collection_content_box.append(detail_box)

    header_box = Gtk.Box(spacing=24, css_classes=["album-header-box"])
    cover = Gtk.Image(pixel_size=160, css_classes=["header-art"])
    cover.set_size_request(160, 160)
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
        utils.load_img(cover, collage, app.cache_dir, 160)
    else:
        cover.set_pixel_size(160)
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
    for i, t in enumerate(tracks):
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

        list_box.append(row)
    detail_box.append(list_box)
    if hasattr(app, "_update_track_list_icon"):
        app._update_track_list_icon(list_box)


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
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card", "home-card", "daily-mix-card"])
            img = Gtk.Image(pixel_size=120, css_classes=["album-cover-img"])
            cover_url = app.backend.get_artwork_url(t, 320)
            if cover_url:
                utils.load_img(img, cover_url, app.cache_dir, 120)
            else:
                img.set_from_icon_name("audio-x-generic-symbolic")
            card.append(img)

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
