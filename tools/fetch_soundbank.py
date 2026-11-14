"""Download individually labeled Chiikawa Usagi effects, retaining provenance.

Uses only Python's standard library and ffprobe. Does not identify speakers by
their pitch: the individual source page must explicitly identify Chiikawa Usagi.
"""
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib
import json
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.source_policy import allowed_source

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.myinstants.com"
SEARCH = BASE + "/ko/search/?name=chiikawa"


def get(url):
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as response:
        return response.read()


class Listing(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sound = self.link = None
        self.name = ""
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "button" and "small-button" in attrs.get("class", ""):
            match = re.search(r"play\('([^']+)'", attrs.get("onclick", ""))
            self.sound = match.group(1) if match else None
        if tag == "a" and "instant-link" in attrs.get("class", ""):
            self.link, self.name = attrs.get("href"), ""

    def handle_data(self, text):
        if self.link:
            self.name += text

    def handle_endtag(self, tag):
        if tag == "a" and self.link:
            self.items.append({"name": self.name, "page": self.link, "url": self.sound})
            self.link = None


def fetch(item):
    identifier = item['page'].rstrip('/').split('/')[-1]
    if not allowed_source({'id': identifier}):
        return None
    # Known other characters and music mashups are not Usagi voice sources.
    if re.search(r"momonga|hachiware|car honk|gangnam|chiikawa_yada", item["name"], re.I):
        return None
    page = BASE + item["page"]
    html = get(page).decode()
    match = re.search(r'<div id="instant-page-description">(.*?)</div>', html, re.S)
    description = unescape(re.sub(r"<[^>]+>", " ", match.group(1))).strip() if match else ""
    if not re.search(r"chiikawa\s+usagi|usagi.*chiikawa", description, re.I):
        return None
    if re.search(r"hachiware|momonga", description, re.I):
        return None
    if not item["url"] or not item["url"].startswith("/media/sounds/"):
        return None
    identifier = item["page"].rstrip("/").split("/")[-1]
    filename = "assets/sources/" + identifier + ".mp3"
    data = get(BASE + item["url"])
    if not allowed_source({'id': identifier, 'sha256': hashlib.sha256(data).hexdigest()}):
        return None
    (ROOT / filename).write_bytes(data)
    info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(ROOT / filename)]))
    duration = float(info["format"]["duration"])
    name = item["name"]
    group = "phrases" if re.search(r"wulala|wula wula|yahawula|puriyaha|wuyayiha|yahayaha|unayaha|una-na|curry|urararusk|spell", name, re.I) else "long" if duration > 2.5 else "short"
    return {"id": identifier, "name": name, "page": page, "url": BASE + item["url"], "description": description, "file": filename, "duration": duration, "group": group, "sha256": hashlib.sha256(data).hexdigest(), "useInMelody": not bool(re.search(r"party|singing|fight", name, re.I))}


def main():
    (ROOT / "assets/sources").mkdir(parents=True, exist_ok=True)
    listing = Listing()
    listing.feed(get(SEARCH).decode())
    with ThreadPoolExecutor(max_workers=4) as executor:
        entries = [item for item in executor.map(fetch, listing.items) if item]
    unique = {}
    for item in entries:
        if item["sha256"] in unique:
            unique[item["sha256"]].setdefault("aliases", []).append({"name": item["name"], "page": item["page"]})
        else:
            unique[item["sha256"]] = item
    bank = list(unique.values())
    if len(bank) < 8:
        raise ValueError("Too few explicitly labeled Usagi samples; do not replace the existing bank")
    target = ROOT / "assets/sources/manifest.json"
    target.write_text(json.dumps(bank, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "assets/soundbank.js").write_text("window.USAGI_SOUNDBANK = " + json.dumps(bank, ensure_ascii=False) + ";\n")
    print(f"Saved {len(bank)} individually labeled effects; original MP3 bytes retained.")
    for item in bank:
        print(f'{item["group"]:8} {item["duration"]:5.2f}s {item["name"]}')


if __name__ == "__main__":
    main()
