# file: mashina_parser.py

import time
import re
from typing import Optional, Dict, List
from urllib.parse import urljoin

import requests
import pandas as pd
from bs4 import BeautifulSoup

BASE_URL = "https://mashina.kg/search/passenger"
DOMAIN = "https://mashina.kg"
MAX_PAGES = 10
DELAY_SECONDS = 1.5
OUTPUT_FILE = "mashina_kg_cars.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}
session = requests.Session()
session.headers.update(HEADERS)
# ---------------- HTTP ----------------

def get_html(url: str, retries: int = 3) -> Optional[str]:
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=15)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            print(f"[WARN] {url} attempt {attempt}: {e}")
            time.sleep(2 ** attempt)
    return None
# ---------------- PARSING HELPERS ----------------

def clean_int(text: str) -> Optional[int]:
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def parse_price_usd(text: str) -> Optional[int]:
    if "$" not in text:
        return None
    return clean_int(text)


def parse_price_kgs(text: str) -> Optional[int]:
    if not text:
        return None

    text = text.replace("\xa0", " ").strip()

    if "В кредит" in text:
        text = text.split("В кредит")[0]

    match = re.search(r"(\d[\d\s]*)\s*(?:⃀|сом|KGS)", text)
    return clean_int(match.group(1)) if match else None


def parse_year_mileage(text: str):
    # "2019/113413 km"
    match = re.search(r"(19\d{2}|20\d{2})\s*/\s*([\d\s]+)", text)
    if not match:
        return None, None

    year = int(match.group(1))
    mileage = clean_int(match.group(2))
    return year, mileage


def parse_engine_trans(text: str):
    # "1.6 л. / вариатор"
    if "/" not in text:
        return None, None
    parts = [p.strip() for p in text.split("/")]
    if len(parts) != 2:
        return None, None
    return parts[0], parts[1]
# ---------------- PAGINATION ----------------

def get_total_pages(soup: BeautifulSoup) -> int:
    buttons = soup.select(".pagination_button")
    pages = []

    for b in buttons:
        t = b.get_text(strip=True)
        if t.isdigit():
            pages.append(int(t))

    return max(pages) if pages else 1
# ---------------- CARD PARSER ----------------

def parse_card(card) -> Dict:
    a_tag = card if card.name == "a" else card.find("a")
    if not a_tag:
        return {}

    href = a_tag.get("href", "")
    if not href.startswith("/details/"):
        return {}

    url = urljoin(DOMAIN, href)

    # title
    title_tag = a_tag.find("h3")
    title = title_tag.get_text(strip=True) if title_tag else None

    # image
    img = a_tag.find("img")
    image_url = img.get("src") if img else None

    # city
    city_tag = a_tag.select_one("span.text-white.text-sm.leading-5.truncate")
    city = city_tag.get_text(strip=True) if city_tag else None

    # price spans
    spans = a_tag.find_all("span")

    price_usd = None
    price_kgs = None
    year = None
    mileage = None
    engine = None
    transmission = None

    for sp in spans:
        text = sp.get_text(" ", strip=True)

        if "$" in text:
            price_usd = parse_price_usd(text)

        if "⃀" in text and "от" not in text:
            price_kgs = parse_price_kgs(text)

        if "/" in text and re.search(r"\d{4}", text):
            year, mileage = parse_year_mileage(text)

        if "/" in text and "л" in text:
            engine, transmission = parse_engine_trans(text)

    return {
        "url": url,
        "title": title,
        "price_usd": price_usd,
        "price_kgs": price_kgs,
        "year": year,
        "mileage_km": mileage,
        "engine": engine,
        "transmission": transmission,
        "city": city,
        "image_url": image_url,
    }
# ---------------- PAGE PARSER ----------------

def parse_page(html: str):
    soup = BeautifulSoup(html, "lxml")

    cards = soup.select('a[href^="/details/"]')

    items = []
    seen = set()

    for c in cards:
        data = parse_card(c)
        if not data:
            continue

        if data["url"] in seen:
            continue

        seen.add(data["url"])
        items.append(data)

    total_pages = get_total_pages(soup)

    return items, total_pages
# ---------------- SCRAPER ----------------

def fetch_all_pages(max_pages: int):
    all_items = []
    seen_urls = set()

    first_html = get_html(BASE_URL)
    if not first_html:
        return []

    first_items, total_pages = parse_page(first_html)

    pages_to_fetch = min(max_pages or total_pages, total_pages)

    all_items.extend(first_items)
    seen_urls.update(i["url"] for i in first_items)

    print(f"[INFO] Total pages: {total_pages}, scraping: {pages_to_fetch}")

    for page in range(2, pages_to_fetch + 1):
        url = f"{BASE_URL}?page={page}"
        html = get_html(url)

        if not html:
            continue

        items, _ = parse_page(html)

        new_count = 0
        for i in items:
            if i["url"] in seen_urls:
                continue
            seen_urls.add(i["url"])
            all_items.append(i)
            new_count += 1

        print(f"[PAGE {page}] +{new_count}")

        time.sleep(DELAY_SECONDS)

    return all_items
# ---------------- SAVE ----------------

def save_to_csv(data: List[Dict], filename: str):
    df = pd.DataFrame(data)
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"[DONE] Saved: {filename} ({len(df)} rows)")
# ---------------- MAIN ----------------

def main():
    data = fetch_all_pages(MAX_PAGES)
    save_to_csv(data, OUTPUT_FILE)


if __name__ == "__main__":
    main()