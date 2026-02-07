import re

class TrustedChannels:
    def __init__(self):
        # 1. GLOBAL TOP LABELS
        self.GLOBAL_LABELS = [
            "vevo", "topic", "official audio", "official video",
            "sony music", "universal music", "warner records", 
            "atlantic records", "republic records", "interscope records",
            "capitol records", "rca records", "columbia records", "def jam",
            "island records", "epic records", "vevo", "umg", "wmg", "sme"
        ]

        # 2. INDIAN MAJOR LABELS
        self.INDIAN_LABELS = [
            "t-series", "zee music", "saregama", "tips official",
            "yrf", "times music", "sony music india", "think music",
            "aditya music", "lahari music", "anand audio", "muzik247",
            "satyam audios", "millennium audios", "manorama music",
            "mazhavil manorama", "mathrubhumi music", "speed audio"
        ]

        # 3. K-POP / J-POP
        self.EAST_ASIAN_LABELS = [
            "hybe labels", "sm entertainment", "jyp entertainment", 
            "yg entertainment", "stone music", "avex", "king records"
        ]

        # 4. REGIONAL SPECIALS (UAE/EU)
        self.REGIONAL_LABELS = [
            "rotana music", "platinum records", "mazzika", "spinnin' records", 
            "armada music", "ministry of sound"
        ]

        # 5. HARD NON-MUSIC BLOCK LIST
        self.HARD_BLOCK_KEYWORDS = [
            "trailer", "teaser", "scene", "movie", "film", "cinema",
            "full movie", "climax", "dialogue", "comedy", "fight",
            "news", "live news", "breaking", "report", "journalist",
            "media", "press", "debate",
            "interview", "speech", "motivation", "explained",
            "review", "reaction", "vlog", "shorts"
        ]

        # 6. MUSIC SPAM BLOCK LIST
        self.SPAM_KEYWORDS = [
            "8d", "3d", "spatial", "360",
            "slowed", "reverb", "nightcore", "sped up", "speed up",
            "bass boosted", "boosted", "karaoke", "instrumental",
            "remix", "dj", "mix", "mashup", "bgm", "background music",
            "status", "edit", "tiktok"
        ]

        self.ALL_TRUSTED = self.GLOBAL_LABELS + self.INDIAN_LABELS + self.EAST_ASIAN_LABELS + self.REGIONAL_LABELS

    def normalize(self, text: str) -> str:
        if not text: return ""
        text = text.lower().strip()
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text

    def calculate_trust_score(self, channel_name: str, video_title: str) -> int:
        c = self.normalize(channel_name)
        t = self.normalize(video_title)
        
        score = 0
        
        # Match trusted channel words
        if any(label in c for label in self.ALL_TRUSTED):
            score += 50
            
        # High Priority Identifiers
        if "vevo" in c or "vevo" in t: score += 40
        if "topic" in c: score += 40
        
        # Audio Quality Identifiers
        audio_signals = ["official audio", "official music video", "song", "audio"]
        if any(signal in t for signal in audio_signals):
            score += 20
        elif "official" in t:
            score += 10

        return score

    def is_spam(self, title: str, query: str) -> bool:
        t = self.normalize(title)
        q = self.normalize(query)
        
        # 1. Hard block non-music content
        if any(k in t for k in self.HARD_BLOCK_KEYWORDS):
            return True
            
        # 2. Block spam music types unless user specifically asked for them
        for word in self.SPAM_KEYWORDS:
            if word in t and word not in q:
                return True
        return False

# Export singleton
trusted_channels = TrustedChannels()
