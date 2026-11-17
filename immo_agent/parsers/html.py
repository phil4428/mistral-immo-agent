import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

NUM_RE = re.compile(r"(\d[\d\s\u00a0.,]*)")


def parse_number(text):
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    match = NUM_RE.search(str(text))
    if not match:
        return None
    raw = match.group(1).replace("\u00a0", "").replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        parts = raw.split(",")
        if len(parts[-1]) == 2:
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "." in raw:
        parts = raw.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_int(text):
    number = parse_number(text)
    return int(number) if number is not None else None


def _extract_tag_value(tag, rule):
    attr = rule.get("attr", "text")
    if attr == "text":
        value = tag.get_text(" ", strip=True)
    else:
        value = tag.get(attr, "")
        if isinstance(value, list):
            value = " ".join(value)
    regex = rule.get("regex")
    if regex:
        match = re.search(regex, value, re.DOTALL)
        if match:
            value = match.group(1) if match.groups() else match.group(0)
    kind = rule.get("type", "str")
    if kind == "float":
        value = parse_number(value)
    elif kind == "int":
        value = parse_int(value)
    return value


def extract_fields(element, fields_spec):
    result = {}
    for name, rule in fields_spec.items():
        if "value" in rule:
            result[name] = rule["value"]
            continue
        if rule.get("multiple"):
            values = []
            attr = rule.get("attr", "text")
            for tag in element.select(rule["selector"]):
                if attr == "text":
                    values.append(tag.get_text(" ", strip=True))
                else:
                    value = tag.get(attr, "")
                    if isinstance(value, list):
                        value = " ".join(value)
                    values.append(value)
            if values:
                result[name] = values
            continue
        tag = element.select_one(rule["selector"])
        if tag is None:
            continue
        result[name] = _extract_tag_value(tag, rule)
    return result


def extract_items(html_text, item_selector, fields_spec, base_url):
    soup = BeautifulSoup(html_text, "html.parser")
    items = []
    for element in soup.select(item_selector):
        data = extract_fields(element, fields_spec)
        if data.get("url"):
            data["url"] = urljoin(base_url, str(data["url"]))
        items.append(data)
    return items


def extract_page_fields(html_text, fields_spec, base_url):
    soup = BeautifulSoup(html_text, "html.parser")
    data = extract_fields(soup, fields_spec)
    if data.get("url"):
        data["url"] = urljoin(base_url, str(data["url"]))
    return data


def find_next_page(html_text, selector, base_url):
    soup = BeautifulSoup(html_text, "html.parser")
    tag = soup.select_one(selector)
    if tag is None:
        return None
    href = tag.get("href")
    return urljoin(base_url, href) if href else None
