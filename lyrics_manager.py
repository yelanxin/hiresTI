import re
import logging

logger = logging.getLogger(__name__)

class LyricsManager:
    def __init__(self):
        self.lyrics_map = {} 
        self.time_points = [] 
        self.karaoke_map = {}
        self.raw_text = ""
        self.has_synced = False
        self.has_karaoke = False

    def _parse_karaoke_words(self, content):
        """
        Parse enhanced LRC word timestamps, e.g.
        <00:10.20>Hello <00:10.60>world
        Returns: (plain_text, [(start_sec, word_text), ...])
        """
        pattern = re.compile(r'<(\d{2}):(\d{2}\.\d{2,3})>')
        matches = list(pattern.finditer(content or ""))
        if not matches:
            return (content or "").strip(), []

        words = []
        plain_parts = []
        for i, m in enumerate(matches):
            start = (int(m.group(1)) * 60) + float(m.group(2))
            seg_start = m.end()
            seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            seg_text = content[seg_start:seg_end]
            if seg_text:
                words.append((start, seg_text))
                plain_parts.append(seg_text)

        plain_text = "".join(plain_parts).strip()
        if not plain_text:
            plain_text = pattern.sub("", content or "").strip()
        return plain_text, words

    def load_lyrics(self, text):
        logger.debug("Loading lyrics text. length=%s", len(text) if text else 0)
        self.lyrics_map = {}
        self.time_points = []
        self.karaoke_map = {}
        self.raw_text = text if text else ""
        self.has_synced = False
        self.has_karaoke = False
        
        if not text: return

        # 匹配 [00:12.34] 格式
        pattern = re.compile(r'\[(\d{2}):(\d{2}\.\d{2,3})\](.*)')
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            match = pattern.match(line)
            
            if match:
                self.has_synced = True
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                content = match.group(3).strip()
                total_seconds = minutes * 60 + seconds
                plain_text, karaoke_words = self._parse_karaoke_words(content)
                self.lyrics_map[total_seconds] = plain_text
                if karaoke_words:
                    self.karaoke_map[total_seconds] = karaoke_words
                    self.has_karaoke = True
                self.time_points.append(total_seconds)
                
        self.time_points.sort()
        logger.debug("Lyrics parsed. synced=%s lines=%s", self.has_synced, len(self.time_points))

    def get_lyric_for_time(self, current_time):
        if not self.has_synced or not self.time_points: return None
        found_time = -1
        for t in self.time_points:
            if t <= current_time: found_time = t
            else: break 
        return self.lyrics_map[found_time] if found_time != -1 else None
